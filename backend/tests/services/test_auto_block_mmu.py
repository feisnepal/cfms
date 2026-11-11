"""Auto-Block MMU generation tests (Phase A.4, plan IMPLEMENTATION_PLAN_AUTO_BLOCK_MMU).

3-tier hybrid (user-confirmed):
1. Pure-logic unit tests — sliver absorb, overlap dedupe, merge plan parity,
   adjacency edges (no DB; shapely only).
2. API guard tests — 409 BLOCKS_EXIST / 409 NO_BOUNDARY / 423 structure-lock /
   400 bad-level / 400 empty-blocks (all short-circuit BEFORE any GIS query).
3. Commit-path tests against the test DB — serial `name`/`block_name`,
   `natural_name`, `division_level`, idempotent re-commit 409.
4. One seeded preview test — inserts tiny fake rows into base.mmu / river.* /
   admin.settlement in cf_db_test to exercise the real preview SQL end-to-end.
"""
import re
import json
import uuid

import pytest
from geoalchemy2 import WKBElement
from geoalchemy2.shape import to_shape
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services import auto_block_service as svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _square(x, y, size=0.01):
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def _make_user(db, email=None):
    user = User(
        email=email or f"mmu{uuid.uuid4().hex[:8]}@test.com",
        full_name="MMU Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    return user


def _make_calc(db, boundary=None, structure_locked=False):
    user = _make_user(db)
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="mmu-test.csv",
        is_draft=False,
        structure_locked=structure_locked,
    )
    db.add(calc)
    db.flush()
    if boundary is not None:
        from geoalchemy2.shape import from_shape
        calc.boundary_geom = from_shape(boundary, srid=4326)
        db.flush()
    return calc


def _block_payloads(pieces):
    return [{
        "index": f["properties"]["index"],
        "name": f["properties"]["name"],
        "block_name": f["properties"]["block_name"],
        "natural_name": f["properties"]["natural_name"],
        "geometry": f["geometry"],
    } for f in pieces]


def _seed_gis_layers(db, calc_id):
    """Insert tiny fake reference-layer features for the preview SQL (tables are
    created once per test DB; INSERTs are idempotent via ON CONFLICT DO NOTHING)."""
    import random
    rid = random.randint(1, 1_000_000)
    ddl = [
        "CREATE SCHEMA IF NOT EXISTS base",
        "CREATE SCHEMA IF NOT EXISTS river",
        "CREATE SCHEMA IF NOT EXISTS admin",
        """CREATE TABLE IF NOT EXISTS base.mmu (
            mmuid INTEGER PRIMARY KEY,
            geom geometry(MultiPolygon, 4326),
            area_ha DOUBLE PRECISION,
            centroid_lon DOUBLE PRECISION,
            centroid_lat DOUBLE PRECISION
        )""",
        """CREATE TABLE IF NOT EXISTS river.ridge (
            id INTEGER PRIMARY KEY, geom geometry(LineString, 4326), ridge_name VARCHAR(255)
        )""",
        """CREATE TABLE IF NOT EXISTS river.river84 (
            objectid INTEGER PRIMARY KEY, shape geometry(LineString, 4326),
            "river name" VARCHAR(255), "sub river system name" VARCHAR(255)
        )""",
        """CREATE TABLE IF NOT EXISTS river.river_line (
            id INTEGER PRIMARY KEY, geom geometry(LineString, 4326), river_name VARCHAR(255)
        )""",
        """CREATE TABLE IF NOT EXISTS admin.settlement (
            objectid INTEGER PRIMARY KEY, shape geometry(Point, 4326), vil_name VARCHAR(255),
            asl INTEGER, x REAL, y REAL
        )""",
    ]
    for stmt in ddl:
        db.execute(text(stmt))
    db.commit()
    db.execute(text("""
        INSERT INTO base.mmu (mmuid, geom, area_ha) VALUES
        (:r, ST_GeomFromText('MULTIPOLYGON(((85.03 27.41,85.04 27.41,85.04 27.42,85.03 27.42,85.03 27.41)))', 4326), 1),
        (:r2, ST_GeomFromText('MULTIPOLYGON(((85.04 27.41,85.05 27.41,85.05 27.42,85.04 27.42,85.04 27.41)))', 4326), 1)
        ON CONFLICT (mmuid) DO NOTHING
    """), {"r": rid, "r2": rid + 1})
    db.execute(text("""
        INSERT INTO admin.settlement (objectid, shape, vil_name) VALUES
        (:r, ST_SetSRID(ST_MakePoint(85.045, 27.415), 4326), 'Testgaun')
        ON CONFLICT (objectid) DO NOTHING
    """), {"r": rid})
    db.execute(text("""
        INSERT INTO river.river_line (id, geom, river_name) VALUES
        (:r, ST_GeomFromText('LINESTRING(85.03 27.43,85.05 27.43)', 4326), 'Testkhola')
        ON CONFLICT (id) DO NOTHING
    """), {"r": rid})
    db.commit()

    # Give the calc a boundary that exactly matches the seeded MMU tile extents
    # so MMU coverage is complete (pieces_ha == boundary_ha).
    db.execute(text("""
        UPDATE calculations SET boundary_geom =
            ST_GeomFromText('POLYGON((85.03 27.41,85.05 27.41,85.05 27.42,85.03 27.42,85.03 27.41))', 4326)
        WHERE id = :cid
    """), {"cid": str(calc_id)})
    db.commit()


# ---------------------------------------------------------------------------
# Tier 1 — pure-logic unit tests
# ---------------------------------------------------------------------------

def test_absorb_slivers_into_largest_neighbour():
    big = _square(0, 0, 0.02)
    small = _square(0.02, 0.005, 0.0002)  # ≈(0.0002*111320)² ≈ 496 m² << 1000 m²; protrudes from big's east edge
    kept, absorbed = svc._absorb_slivers([small, big])
    assert absorbed == 1
    assert len(kept) == 1
    # total area preserved (sliver folded into big); UTM geodesic projection
    # distorts the joined shape slightly, so allow a small relative margin
    assert abs(svc._area_m2(kept[0]) - (svc._area_m2(big) + svc._area_m2(small))) < max(10.0, 0.05 * svc._area_m2(small))


def test_absorb_slivers_keeps_orphan():
    lone = _square(0, 0, 0.0002)  # ≈496 m² sliver, no neighbour
    kept, absorbed = svc._absorb_slivers([lone])
    assert absorbed == 0
    assert len(kept) == 1  # never delete area


def test_absorb_slivers_force_absorbs_orphan_into_largest():
    # `tiny` has NO shared border with either neighbour. With the flag it must
    # fold into the LARGEST piece by area (the far `big`), NOT the nearest one
    # (the close `small`) — near-centroid would pick `small`, area picks `big`.
    big = _square(0, 0, 0.02)  # ~5.0 ha — largest, far from the island
    small = _square(0.09, 0.08, 0.004)  # ~0.2 ha — close to the island
    tiny = _square(0.09, 0.09, 0.0002)  # ~496 m² island, touches neither
    kept, absorbed = svc._absorb_slivers(
        [tiny, small, big], sliver_area_m2=1000.0, force_absorb_orphans=True
    )
    assert absorbed == 1
    assert len(kept) == 2
    areas = sorted((svc._area_m2(p) for p in kept), reverse=True)
    # largest piece == big + tiny (orphan folded into the largest-area piece)
    assert abs(areas[0] - (svc._area_m2(big) + svc._area_m2(tiny))) < max(
        10.0, 0.05 * svc._area_m2(tiny)
    )


def test_absorb_slivers_force_off_keeps_orphan_with_neighbours():
    # Without the flag an orphan (no shared border) is kept even when
    # neighbours exist — only touching slivers are absorbed.
    tiny = _square(0.09, 0.09, 0.0002)
    big = _square(0, 0, 0.02)
    kept, absorbed = svc._absorb_slivers([tiny, big], sliver_area_m2=1000.0)
    assert absorbed == 0
    assert len(kept) == 2


def test_reabsorb_after_explode_keeps_force_merged_orphan_merged():
    """Regression for the live चुरे report: the pipeline absorbs a sub-floor
    orphan, then `_explode_multiparts` splits the (disjoint) union straight back
    into the island — so sub-threshold pieces still reached the preview and the
    attribute table and "adjusting the minimum area works partially but not
    fully". The floor absorb must run once more AFTER the explode, and its
    merged multi-part result must survive (no sub-floor piece on its own)."""
    floor = 1000.0
    big = _square(0, 0, 0.02)  # ~5.0 ha — largest
    island = _square(0.09, 0.09, 0.0002)  # ~496 m² — touches nothing
    pieces, absorbed = svc._absorb_slivers([island, big], floor, force_absorb_orphans=True)
    assert absorbed == 1
    exploded = svc._explode_multiparts(pieces)
    assert len(exploded) == 2  # disjoint union split apart again -> island back
    pieces, reabsorbed = svc._absorb_slivers(exploded, floor, force_absorb_orphans=True)
    assert reabsorbed == 1  # re-absorbed as the LAST geometry step
    assert len(pieces) == 1
    assert pieces[0].geom_type == "MultiPolygon"
    assert all(svc._area_m2(p) >= floor for p in pieces)
    assert abs(
        svc._area_m2(pieces[0]) - (svc._area_m2(big) + svc._area_m2(island))
    ) < max(50.0, 0.05 * svc._area_m2(island))


def test_dedupe_overlaps_keeps_larger():
    a = _square(0, 0, 0.02)
    b = _square(0.005, 0.005, 0.02)  # substantial overlap with a
    cleaned = svc._dedupe_overlaps([a, b])
    assert len(cleaned) == 2  # both survive, overlap carved from smaller
    total = sum(svc._area_m2(c) for c in cleaned)
    # no double-count: total == union area
    expected = svc._area_m2(unary_union([a, b]))
    assert abs(total - expected) < max(10.0, 0.05 * expected)


def test_merge_plan_exactly_n():
    pieces = [_square(i * 0.02, 0, 0.01) for i in range(5)]  # 5 adjacent squares
    edges = svc._adjacency_edges(pieces)
    merged = svc._merge_plan(pieces, edges, 2)
    assert len(merged) == 2
    total = sum(svc._area_m2(m) for m in merged)
    assert abs(total - sum(svc._area_m2(p) for p in pieces)) < 1.0


def test_adjacency_edges_count():
    a = _square(0, 0)
    b = _square(0.01, 0)
    edges = svc._adjacency_edges([a, b])
    assert len(edges) == 1
    assert edges[0]["shared_m"] > 100.0


# ---------------------------------------------------------------------------
# GeometryCollection safety (found live on हिमाल forest, 2026-09-13):
# ``make_valid`` on a union can come back as a GeometryCollection mixing a
# real polygon with degenerate LineString/Point repair noise. The old
# `_explode_multiparts` silently dropped such a piece *in its entirety*
# (only handled Polygon/MultiPolygon), and `_shared_boundary_m` crashed on it
# (`GeometryCollection.boundary` is `None` in shapely, not raised, not
# empty) -- together these turned a slope-carved 273 ha forest into only
# ~81 ha of committed blocks (a huge coverage gap silently dropped, then
# patched with one crude remainder block: "no outer boundary, only inner
# polygons") and corrupted the adjacency graph used to reduce block count
# (the "reduce to N blocks -> 400 Bad Request" report).
# ---------------------------------------------------------------------------

def test_explode_multiparts_keeps_the_polygon_out_of_a_geometrycollection():
    from shapely.geometry import GeometryCollection, LineString

    real = _square(0, 0, 0.02)
    noise = LineString([(0.05, 0.05), (0.06, 0.06)])  # zero-area repair remnant
    gc = GeometryCollection([real, noise])
    exploded = svc._explode_multiparts([gc])
    assert len(exploded) == 1
    assert exploded[0].geom_type == "Polygon"
    assert abs(svc._area_m2(exploded[0]) - svc._area_m2(real)) < 1.0


def test_explode_multiparts_keeps_both_polygons_out_of_a_geometrycollection():
    from shapely.geometry import GeometryCollection, LineString

    a = _square(0, 0, 0.02)
    b = _square(1, 1, 0.02)
    noise = LineString([(5, 5), (6, 6)])
    gc = GeometryCollection([a, noise, b])
    exploded = svc._explode_multiparts([gc])
    total = sum(svc._area_m2(p) for p in exploded)
    assert abs(total - (svc._area_m2(a) + svc._area_m2(b))) < 1.0


def test_shared_boundary_m_does_not_raise_on_a_geometrycollection():
    from shapely.geometry import GeometryCollection, LineString

    a = _square(0, 0, 0.02)
    gc = GeometryCollection([_square(0.01, 0, 0.02), LineString([(9, 9), (10, 10)])])
    # Must degrade to "no shared edge", never raise AttributeError.
    assert svc._shared_boundary_m(a, gc) == 0.0
    assert svc._shared_boundary_m(gc, a) == 0.0


def test_as_polygonal_normalizes_a_geometrycollection_back_to_real_area():
    from shapely.geometry import GeometryCollection, LineString

    real = _square(0, 0, 0.02)
    gc = GeometryCollection([real, LineString([(9, 9), (10, 10)])])
    normalized = svc._as_polygonal(gc)
    assert normalized.geom_type in ("Polygon", "MultiPolygon")
    assert abs(svc._area_m2(normalized) - svc._area_m2(real)) < 1.0


def test_absorb_coverage_gaps_survives_a_geometrycollection_union(monkeypatch):
    """`make_valid(piece.union(gap_fragment))` returning a GeometryCollection
    (shapely's own repair shape, per `single_part_geometry._polygon_parts`'s
    docstring) must not silently delete that piece's area."""
    from shapely.geometry import GeometryCollection, LineString

    piece = _square(0, 0, 0.02)  # covers [0,0.02]x[0,0.02]
    boundary = _square(0, 0, 0.04)  # forest is twice as big -> one big real gap
    real_make_valid = svc.make_valid
    call_count = {"n": 0}

    def fake_make_valid(geom):
        # `_absorb_coverage_gaps` calls `make_valid` exactly twice for this
        # single-piece/single-gap-fragment setup: once on `boundary_geom`
        # (call 0), once on `pieces[best_idx].union(frag)` (call 1) -- only
        # the second is the one we want to force into a GeometryCollection.
        idx = call_count["n"]
        call_count["n"] += 1
        result = real_make_valid(geom)
        if idx == 1:
            return GeometryCollection([result, LineString([(9, 9), (10, 10)])])
        return result

    monkeypatch.setattr(svc, "make_valid", fake_make_valid)
    pieces = svc._absorb_coverage_gaps([piece], boundary)

    # The gap-absorbed piece must still be there with its full area -- not
    # silently vanished because it was left as a GeometryCollection.
    total = sum(svc._area_m2(p) for p in pieces)
    assert abs(total - svc._area_m2(boundary)) < max(10.0, 0.01 * svc._area_m2(boundary))
    assert all(p.geom_type in ("Polygon", "MultiPolygon") for p in pieces)


# ---------------------------------------------------------------------------
# Tier 3 — commit-path tests against the test DB
# ---------------------------------------------------------------------------

def test_commit_persists_serial_and_natural_name(db):
    # boundary exactly = union of the two blocks (0.04 x 0.02 rectangle)
    boundary = Polygon([(0, 0), (0.04, 0), (0.04, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    payload = [
        {"index": 1, "name": "B1", "block_name": "B1", "natural_name": "Testgaun",
         "geometry": _square(0, 0, 0.02).__geo_interface__},
        {"index": 2, "name": "B2", "block_name": "B2", "natural_name": None,
         "geometry": _square(0.02, 0, 0.02).__geo_interface__},
    ]
    created = svc.commit_blocks(db, calc, payload, level="blocks")
    assert len(created) == 2
    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).order_by(ForestBlock.index).all()
    assert [r.name for r in rows] == ["B1", "B2"]
    assert [r.block_name for r in rows] == ["B1", "B2"]
    assert [r.natural_name for r in rows] == ["Testgaun", None]
    assert all(r.division_level == 1 for r in rows)
    assert all(r.is_compartment is False for r in rows)
    assert all(r.geometry is not None for r in rows)
    # coverage ≈ boundary area
    assert abs(rows[0].area_hectares + rows[1].area_hectares -
               svc._area_m2(boundary) / 10000.0) < 0.5


def test_commit_compartments_level(db):
    calc = _make_calc(db, boundary=_square(0, 0, 0.05))
    payload = [
        {"index": 1, "name": "Compartment-1", "block_name": "Compartment-1",
         "natural_name": None, "geometry": _square(0, 0, 0.02).__geo_interface__},
    ]
    created = svc.commit_blocks(db, calc, payload, level="compartments")
    row = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).one()
    assert row.division_level == 1
    assert row.is_compartment is True
    assert row.name == "Compartment-1"


def test_commit_refuses_when_blocks_exist(db):
    calc = _make_calc(db, boundary=_square(0, 0, 0.05))
    svc.commit_blocks(db, calc, [
        {"index": 1, "name": "B1", "block_name": "B1",
         "natural_name": None, "geometry": _square(0, 0, 0.02).__geo_interface__},
    ], level="blocks")
    with pytest.raises(ValueError, match="BLOCKS_EXIST"):
        svc.commit_blocks(db, calc, [], level="blocks")


def test_commit_rejects_bad_geometry(db):
    calc = _make_calc(db, boundary=_square(0, 0, 0.05))
    with pytest.raises(ValueError, match="invalid_geometry"):
        svc.commit_blocks(db, calc, [{"index": 1, "name": "X", "geometry": None}], level="blocks")


def test_commit_explodes_multipart_into_single_part_rows(db):
    # A merged block geometry whose parts are disjoint (e.g. user merged two
    # non-adjacent pieces) must NOT persist as one row with several polygons.
    # Each part becomes its own single-part block row.
    boundary = Polygon([(0, 0), (0.06, 0), (0.06, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    left = _square(0, 0, 0.02)
    right = _square(0.04, 0, 0.02)  # gap in between -> disjoint MultiPolygon
    multipart = unary_union([left, right])
    assert multipart.geom_type == "MultiPolygon"
    payload = [{"index": 1, "name": "B1", "block_name": "B1",
                "natural_name": "Brokengaun", "geometry": multipart.__geo_interface__}]
    created = svc.commit_blocks(db, calc, payload, level="blocks")
    assert len(created) == 2
    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).order_by(ForestBlock.index).all()
    assert len(rows) == 2
    assert all(r.geometry is not None for r in rows)
    # each persisted geometry must be a single contiguous polygon, not multipart
    for r in rows:
        g = to_shape(r.geometry)
        assert g.geom_type == "Polygon"
    # both parts carry the block's identity; indices are sequential
    assert [r.name for r in rows] == ["B1", "B1"]
    assert [r.block_name for r in rows] == ["B1", "B1"]
    assert [r.natural_name for r in rows] == ["Brokengaun", "Brokengaun"]
    assert [r.index for r in rows] == [1, 2]
    # coverage preserved (sum of the two pieces, not the gapped boundary)
    total = sum(r.area_hectares for r in rows)
    expected = svc._area_m2(_square(0, 0, 0.02)) * 2 / 10000.0
    assert abs(total - expected) < 0.5


def test_commit_drops_degenerate_sliver_parts(db):
    """A committed geometry with a needle-thin numerical-noise fragment
    (thousandths of a m^2, real perimeter) alongside a real part — the exact
    shape a client-side merge-glue operation can leave behind — must persist
    only the real part(s), not one extra near-zero-area block per fragment."""
    boundary = Polygon([(0, 0), (0.06, 0), (0.06, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    real = _square(0, 0, 0.02)
    needle = Polygon([(0.04, 0.0), (0.04, 0.0001), (0.0400000001, 0.0001), (0.0400000001, 0.0)])
    from shapely.geometry import MultiPolygon
    bundled = MultiPolygon([real, needle])
    payload = [{"index": 1, "name": "B1", "block_name": "B1",
                "natural_name": None, "geometry": bundled.__geo_interface__}]
    created = svc.commit_blocks(db, calc, payload, level="blocks")
    assert len(created) == 1  # the needle never becomes its own block
    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    assert len(rows) == 1
    assert to_shape(rows[0].geometry).geom_type == "Polygon"


def test_commit_folds_subfloor_orphan_into_largest_part(db):
    """A force-merged isolated island must commit as ONE multi-part block row,
    never as its own below-threshold row. Regression: the preview kept the
    island merged, but commit's own `_explode_multiparts` split it straight
    back out into a separate forest_blocks row, so sub-floor blocks re-appeared
    in the attribute table."""
    boundary = Polygon([(0, 0), (0.06, 0), (0.06, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    big = _square(0, 0, 0.02)  # ~5 ha, well above the floor
    island = _square(0.05, 0.008, 0.0002)  # ~496 m², disjoint from big
    multipart = unary_union([big, island])
    assert multipart.geom_type == "MultiPolygon"
    payload = [{"index": 1, "name": "B1", "block_name": "B1",
                "natural_name": None, "geometry": multipart.__geo_interface__}]
    created = svc.commit_blocks(
        db, calc, payload, level="blocks", sliver_area_m2=10000.0
    )
    assert len(created) == 1  # the island never becomes its own row
    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    assert len(rows) == 1
    g = to_shape(rows[0].geometry)
    assert g.geom_type == "MultiPolygon"  # one row carrying both parts
    total = sum(svc._area_m2(p) for p in svc._explode_multiparts([g]))
    assert abs(total - (svc._area_m2(big) + svc._area_m2(island))) < max(
        100.0, 0.05 * svc._area_m2(island)
    )


# ---------------------------------------------------------------------------
# Tier 4 — seeded preview (real SQL against test DB)
# ---------------------------------------------------------------------------

def test_preview_with_seeded_gis_layers(db):
    calc = _make_calc(db)
    _seed_gis_layers(db, calc.id)

    res = svc.preview_mmu_blocks(db, calc, level="blocks")
    m = res["meta"]
    assert m["piece_count"] >= 2
    assert abs(m["pieces_ha"] - m["boundary_ha"]) < 0.5  # coverage preserved
    names = [f["properties"]["natural_name"] for f in res["pieces"]["features"]]
    assert "Testgaun" in names or "Testkhola" in names
    assert all(
        re.fullmatch(r"B\d+", f["properties"]["name"]) for f in res["pieces"]["features"]
    )
    # serial descending by area
    areas = [f["properties"]["area_hectares"] for f in res["pieces"]["features"]]
    assert areas == sorted(areas, reverse=True)


def test_preview_forwards_force_absorb_orphans(db, monkeypatch):
    """Regression: preview_mmu_blocks used to swallow `force_absorb_orphans`
    (line 559) so the checkbox did nothing for mmu — only slope forwarded it.
    The mmu preview must dispatch the flag into `_absorb_slivers`."""
    calc = _make_calc(db)
    _seed_gis_layers(db, calc.id)
    captured = {"force": None}

    def fake_absorb(pieces, sliver_area_m2=None, force_absorb_orphans=False):
        captured["force"] = force_absorb_orphans
        return pieces, 0

    monkeypatch.setattr(svc, "_absorb_slivers", fake_absorb)
    svc.preview_mmu_blocks(db, calc, level="blocks", force_absorb_orphans=True)
    assert captured["force"] is True


def test_preview_desired_n_merge(db):
    calc = _make_calc(db)
    _seed_gis_layers(db, calc.id)
    res = svc.preview_mmu_blocks(db, calc, level="blocks", desired_n=1)
    assert res["meta"]["piece_count"] == 1
    assert abs(res["meta"]["pieces_ha"] - res["meta"]["boundary_ha"]) < 0.5


def test_preview_no_boundary_raises(db):
    calc = _make_calc(db, boundary=None)
    with pytest.raises(ValueError, match="no_boundary"):
        svc.preview_mmu_blocks(db, calc, level="blocks")


def test_preview_all_pieces_single_part(db):
    # Every previewed piece must be a single contiguous polygon so that one
    # click always selects exactly one block (user report, Phase C review).
    calc = _make_calc(db)
    _seed_gis_layers(db, calc.id)
    res = svc.preview_mmu_blocks(db, calc, level="blocks")
    from shapely.geometry import shape as shp
    from shapely.geometry.base import BaseGeometry
    for f in res["pieces"]["features"]:
        g = shp(f["geometry"])
        assert g.geom_type == "Polygon", f"expected single-part Polygon, got {g.geom_type}"
    assert res["meta"]["piece_count"] == len(res["pieces"]["features"])



def test_layer_features_returns_geometry_and_own_attribute_only(db):
    """RS-9 owner directive 2026-10-01: a committed layer's features render
    with real geometry (like any built-in layer) and only that source's own
    classification column, not the other eight dominant_* fields."""
    boundary = Polygon([(0, 0), (0.02, 0), (0.02, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    payload = [
        {
            "index": 1, "name": "B1", "block_name": "B1",
            "natural_name": "Testgaun", "dominant_slope_band": 3,
            "geometry": _square(0, 0, 0.02).__geo_interface__,
        },
    ]
    svc.commit_blocks(db, calc, payload, level="blocks", source="slope")
    layer = db.query(svc.RasterLayer).filter(svc.RasterLayer.calculation_id == calc.id).one()
    feats = svc.layer_features(db, calc, layer.id)
    assert len(feats) == 1
    f = feats[0]
    assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert f["properties"]["Name"] == "B1"
    assert f["properties"]["Natural Name"] == "Testgaun"
    # Owner report 2026-10-01: "provide the slope range like gentle(>19)" --
    # the degree range comes from SFM's own slope-class digitizing aid
    # (§15.2 zonation), not a second number invented here.
    assert f["properties"]["Slope Band"] == "Steep (31–45°)"
    # None of the other sources' labels leak in.
    for leaked in ("NASA Forest Quality", "Land Cover", "Forest Type", "Aspect", "Canopy Class"):
        assert leaked not in f["properties"]


def test_layer_features_unknown_layer_raises(db):
    calc = _make_calc(db, boundary=_square(0, 0, 0.02))
    with pytest.raises(ValueError):
        svc.layer_features(db, calc, uuid.uuid4())


def test_promote_layer_as_children_clips_to_parent_and_keeps_own_classification(db):
    """RS-2.17 owner directive 2026-10-01: assigning a layer to an existing
    parent clips each piece to the parent's scope and each resulting child
    keeps ITS OWN source row's classification, not the parent's."""
    boundary = Polygon([(0, 0), (0.04, 0), (0.04, 0.04), (0, 0.04)])
    calc = _make_calc(db, boundary=boundary)
    # Parent block covering the whole boundary (own trial layer, source="mmu") --
    # NOT a legacy row (raster_layer_id IS NULL), which is the one thing that
    # still makes the second commit_blocks call below refuse with
    # BLOCKS_EXIST (promoted layers stopped refusing 2026-10-01, owner
    # report -- legacy rows are the only remaining refusal reason).
    parent_payload = [{
        "index": 1, "name": "B1", "block_name": "B1",
        "natural_name": None, "geometry": boundary.__geo_interface__,
    }]
    svc.commit_blocks(db, calc, parent_payload, level="blocks", source="mmu")
    parent = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).one()
    # The parent must be REAL structure (the parent picker only lists those): promote its layer.
    svc.promote_layer(db, calc, parent.raster_layer_id, "blocks")

    # A slope layer carved as two halves of the same boundary.
    left = Polygon([(0, 0), (0.02, 0), (0.02, 0.04), (0, 0.04)])
    right = Polygon([(0.02, 0), (0.04, 0), (0.04, 0.04), (0.02, 0.04)])
    layer_payload = [
        {"index": 1, "name": "slope-1", "block_name": "slope-1", "natural_name": None,
         "dominant_slope_band": 1, "geometry": left.__geo_interface__},
        {"index": 2, "name": "slope-2", "block_name": "slope-2", "natural_name": None,
         "dominant_slope_band": 3, "geometry": right.__geo_interface__},
    ]
    svc.commit_blocks(db, calc, layer_payload, level="blocks", source="slope")
    layer = (
        db.query(svc.RasterLayer)
        .filter(svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "slope")
        .one()
    )

    result = svc.promote_layer_as_children(db, calc, layer.id, parent.id)
    assert result["n_children"] == 2
    children = (
        db.query(ForestBlock)
        .filter(ForestBlock.parent_block_id == parent.id)
        .order_by(ForestBlock.dominant_slope_band)
        .all()
    )
    assert len(children) == 2
    assert [c.dominant_slope_band for c in children] == [1, 3]
    # Children belong to their PARENT's layer (not the assigned source layer): real structure while that
    # layer is promoted, and hidden with it if it is demoted -- never a layer-less orphan.
    assert all(c.raster_layer_id == parent.raster_layer_id for c in children)
    assert all(c.division_level == parent.division_level + 1 for c in children)
    assert all(c.is_compartment is False for c in children)
    # The layer itself is untouched -- still unpromoted, still a trial overlay.
    db.refresh(layer)
    assert layer.promoted_as is None


def test_delete_layer_cascades_its_blocks_but_refuses_when_promoted(db):
    """Owner report 2026-10-01: "I can not remove auto created layer. Make it
    deletable." An unpromoted layer deletes cleanly (cascade removes its
    pieces); a promoted one is refused until demoted."""
    boundary = Polygon([(0, 0), (0.02, 0), (0.02, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    payload = [{
        "index": 1, "name": "B1", "block_name": "B1",
        "natural_name": None, "geometry": _square(0, 0, 0.02).__geo_interface__,
    }]
    svc.commit_blocks(db, calc, payload, level="blocks", source="slope")
    layer = db.query(svc.RasterLayer).filter(svc.RasterLayer.calculation_id == calc.id).one()
    layer_id = layer.id

    # Promoted: delete is refused.
    svc.promote_layer(db, calc, layer_id, "blocks")
    with pytest.raises(ValueError, match="PROMOTED_CANNOT_DELETE"):
        svc.delete_layer(db, calc, layer_id)

    # Demoted: delete cascades its pieces.
    svc.demote_layer(db, calc, layer_id)
    assert db.query(ForestBlock).filter(ForestBlock.raster_layer_id == layer_id).count() == 1
    svc.delete_layer(db, calc, layer_id)
    assert db.query(svc.RasterLayer).filter(svc.RasterLayer.id == layer_id).first() is None
    assert db.query(ForestBlock).filter(ForestBlock.raster_layer_id == layer_id).count() == 0


def test_a_promoted_layer_no_longer_blocks_carving_another_source(db):
    """Owner report 2026-10-01: creating a second Auto-Block layer (e.g.
    aspect, after slope) must work even once the first is promoted -- compare
    several sources, decide later which (if any) to assign. Only legacy
    (pre-layer) rows should still refuse."""
    boundary = Polygon([(0, 0), (0.02, 0), (0.02, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    payload = [{
        "index": 1, "name": "B1", "block_name": "B1",
        "natural_name": None, "geometry": boundary.__geo_interface__,
    }]
    svc.commit_blocks(db, calc, payload, level="blocks", source="slope")
    slope_layer = db.query(svc.RasterLayer).filter(svc.RasterLayer.calculation_id == calc.id).one()
    svc.promote_layer(db, calc, slope_layer.id, "blocks")

    # A second source, after the first is promoted, must NOT raise BLOCKS_EXIST.
    aspect_payload = [{
        "index": 1, "name": "aspect-1", "block_name": "aspect-1",
        "natural_name": None, "geometry": boundary.__geo_interface__,
    }]
    created = svc.commit_blocks(db, calc, aspect_payload, level="blocks", source="aspect")
    assert len(created) == 1
    layers = {
        l.source: l.promoted_as
        for l in db.query(svc.RasterLayer).filter(svc.RasterLayer.calculation_id == calc.id).all()
    }
    assert layers == {"slope": "blocks", "aspect": None}


def test_layer_features_aspect_shows_bearing_range(db):
    """Owner report 2026-10-01: same range-enrichment request as slope,
    for aspect's compass bearing."""
    boundary = Polygon([(0, 0), (0.02, 0), (0.02, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    payload = [{
        "index": 1, "name": "B1", "block_name": "B1", "natural_name": None,
        "dominant_aspect": 1, "geometry": _square(0, 0, 0.02).__geo_interface__,
    }]
    svc.commit_blocks(db, calc, payload, level="blocks", source="aspect")
    layer = db.query(svc.RasterLayer).filter(svc.RasterLayer.calculation_id == calc.id).one()
    f = svc.layer_features(db, calc, layer.id)[0]
    assert f["properties"]["Aspect"] == "N (337.5\u2013360\u00b0 / 0\u201322.5\u00b0)"


def test_layer_features_dem_shows_elevation_band_range_from_committed_rows(db):
    """Owner report 2026-10-01: "elevation layer has only high, mid, low
    value. High from m to m is expected alongside." Reconstructed from each
    committed row's own elevation_min_m/_max_m (RS-2.19), not a new column."""
    boundary = Polygon([(0, 0), (0.04, 0), (0.04, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    payload = [
        {
            "index": 1, "name": "C-1", "block_name": "C-1", "natural_name": None,
            "dominant_contour_band": 3,
            "elevation_min_m": 800, "elevation_mean_m": 850, "elevation_max_m": 900,
            "geometry": _square(0, 0, 0.02).__geo_interface__,
        },
        {
            "index": 2, "name": "C-2", "block_name": "C-2", "natural_name": None,
            "dominant_contour_band": 3,
            "elevation_min_m": 850, "elevation_mean_m": 900, "elevation_max_m": 945,
            "geometry": _square(0.02, 0, 0.02).__geo_interface__,
        },
    ]
    svc.commit_blocks(db, calc, payload, level="blocks", source="dem")
    layer = db.query(svc.RasterLayer).filter(svc.RasterLayer.calculation_id == calc.id).one()
    feats = svc.layer_features(db, calc, layer.id)
    # Both pieces share band 3 -- the range is the UNION across the layer's
    # own rows for that band (800 from piece 1, 945 from piece 2), not
    # either piece's own individual min/max.
    for f in feats:
        assert f["properties"]["Elevation Band"] == "High (800\u2013945 m)"


# ---------------------------------------------------------------------------
# Union (P10, RS-10.2) -- Mode B / union_zonal
# ---------------------------------------------------------------------------

def test_union_zonal_auto_creates_mmu_at_5ha_floor_when_absent(db):
    """RS-10.0 (owner, 2026-10-01): a forest with no MMU layer yet gets one
    auto-created at a 5 ha floor (not the 1 ha SSOT default) before Union
    builds on top of it -- and the response says so."""
    calc = _make_calc(db)
    _seed_gis_layers(db, calc.id)
    assert db.query(svc.RasterLayer).filter(
        svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "mmu"
    ).first() is None

    res = svc.preview_union_zonal_blocks(db, calc, level="blocks")

    assert res["meta"]["mmu_auto_created"] is True
    mmu_layer = db.query(svc.RasterLayer).filter(
        svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "mmu"
    ).one()
    assert str(mmu_layer.id) == res["meta"]["mmu_layer_id"]
    assert len(res["pieces"]["features"]) >= 1
    for f in res["pieces"]["features"]:
        props = f["properties"]
        assert props["name"].startswith("Union-")
        # All 9 keys present even though live rasters are absent from the
        # test DB -- they degrade to None rather than raise or vanish.
        for key in (
            "dominant_slope_band", "dominant_aspect", "dominant_canopy_class",
            "dominant_nasa_quality", "dominant_health_class", "dominant_landcover",
            "dominant_forest_type", "dominant_contour_band",
            "sub_area_category", "sub_area_excluded",
        ):
            assert key in props


def test_union_zonal_reuses_existing_mmu_layer_without_recreating(db):
    """A forest that already has an MMU layer must not get a second one --
    union_zonal orchestrates the existing layer, it does not force a new carve."""
    calc = _make_calc(db)
    _seed_gis_layers(db, calc.id)
    mmu_preview = svc.preview_mmu_blocks(db, calc, level="blocks")
    svc.commit_blocks(db, calc, _block_payloads(mmu_preview["pieces"]["features"]), level="blocks", source="mmu")
    existing_mmu_layer = db.query(svc.RasterLayer).filter(
        svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "mmu"
    ).one()

    res = svc.preview_union_zonal_blocks(db, calc, level="blocks")

    assert res["meta"]["mmu_auto_created"] is False
    assert res["meta"]["mmu_layer_id"] == str(existing_mmu_layer.id)
    assert db.query(svc.RasterLayer).filter(
        svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "mmu"
    ).count() == 1


def test_union_zonal_sub_area_largest_overlap_and_private_land_tag(db):
    """Sub-area category comes from largest-area vector overlap against
    ForestSubArea, never a raster vote; a Private Land overlap is tagged via
    sub_area_excluded, not silently dropped from the output (owner-confirmed
    2026-10-01: tag, don't omit)."""
    from geoalchemy2.shape import from_shape
    from app.models.forest_sub_area import ForestSubArea

    boundary = Polygon([(0, 0), (0.02, 0), (0.02, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    _seed_gis_layers(db, calc.id)
    # Re-point the seeded MMU tile to sit under this test's own boundary so
    # the sub-area overlap below actually lands on it.
    db.execute(text("""
        UPDATE calculations SET boundary_geom =
            ST_GeomFromText('POLYGON((0 0,0.02 0,0.02 0.02,0 0.02,0 0))', 4326)
        WHERE id = :cid
    """), {"cid": str(calc.id)})
    db.execute(text("DELETE FROM base.mmu"))
    db.execute(text("""
        INSERT INTO base.mmu (mmuid, geom, area_ha) VALUES
        (987654, ST_GeomFromText('MULTIPOLYGON(((0 0,0.02 0,0.02 0.02,0 0.02,0 0)))', 4326), 1)
    """))
    db.commit()

    # Most of the piece is Plantation; a corner is Private Land (excluded) --
    # Plantation covers more area, so it should win the largest-overlap vote,
    # and the Private Land sliver should NOT make the whole piece vanish.
    plantation = Polygon([(0, 0), (0.015, 0), (0.015, 0.02), (0, 0.02)])
    private = Polygon([(0.015, 0), (0.02, 0), (0.02, 0.02), (0.015, 0.02)])
    db.add(ForestSubArea(
        calculation_id=calc.id, name="Plantation block",
        category="plantation", geometry=from_shape(plantation, srid=4326),
        area_hectares=svc._area_m2(plantation) / svc.SQM_PER_HA, is_excluded=False,
    ))
    db.add(ForestSubArea(
        calculation_id=calc.id, name="Private corner",
        # `is_excluded` is the real Private Land flag -- "private_land" is
        # NOT itself a valid `category` value post-migration-048 (the
        # forest_sub_areas_category_check CHECK constraint only allows the
        # 14 values in sub_area_service.VALID_CATEGORIES), found only by
        # running this test against the real DB constraint rather than the
        # model docstring's "Protected Zone / ... / Private Land" list.
        category="other", geometry=from_shape(private, srid=4326),
        area_hectares=svc._area_m2(private) / svc.SQM_PER_HA, is_excluded=True,
    ))
    db.flush()

    res = svc.preview_union_zonal_blocks(db, calc, level="blocks")
    feats = res["pieces"]["features"]
    assert len(feats) >= 1
    # Every piece is checked rather than assuming index 0, because MMU's own
    # hole-fill/sliver-absorb pipeline is free to produce more than one piece.
    plantation_pieces = [f for f in feats if f["properties"]["sub_area_category"] == "plantation"]
    assert plantation_pieces, feats
    assert all(not f["properties"]["sub_area_excluded"] for f in plantation_pieces)


def test_union_zonal_layer_features_shows_all_9_columns(db):
    """RS-10.4: Union is the deliberate exception to RS-2.16/2.18's
    one-layer-one-column rule -- its attribute table shows all 9 at once."""
    calc = _make_calc(db)
    _seed_gis_layers(db, calc.id)
    svc.preview_union_zonal_blocks(db, calc, level="blocks")
    layer = db.query(svc.RasterLayer).filter(
        svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "union_zonal"
    ).first()
    assert layer is None  # preview alone must not persist anything

    res = svc.preview_union_zonal_blocks(db, calc, level="blocks")
    payload = _block_payloads(res["pieces"]["features"])
    for req, feat in zip(payload, res["pieces"]["features"]):
        req.update(feat["properties"])
    svc.commit_blocks(db, calc, payload, level="blocks", source="union_zonal")
    layer = db.query(svc.RasterLayer).filter(
        svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "union_zonal"
    ).one()

    feats = svc.layer_features(db, calc, layer.id)
    assert feats
    for f in feats:
        # Live rasters are absent from the test DB, so most of the 8
        # classification columns legitimately come back absent (no coverage
        # to vote on) -- the point here is Sub-area + _source are always
        # present and nothing narrows the layer down to one column the way
        # every other source's `layer_features` branch does.
        assert f["properties"]["_source"] == "union_zonal"
        assert "Sub-area" in f["properties"]


def test_union_zonal_promote_and_assign_as_children_both_work(db):
    """RS-10.6: Union needs no source-specific code in either promotion
    path -- `promote_layer` (become the top-level structure) and
    `promote_layer_as_children` (assign into an existing parent), the two
    ways the owner asked a Union layer be assignable."""
    boundary = Polygon([(0, 0), (0.04, 0), (0.04, 0.04), (0, 0.04)])
    calc = _make_calc(db, boundary=boundary)
    _seed_gis_layers(db, calc.id)
    db.execute(text("""
        UPDATE calculations SET boundary_geom =
            ST_GeomFromText('POLYGON((0 0,0.04 0,0.04 0.04,0 0.04,0 0))', 4326)
        WHERE id = :cid
    """), {"cid": str(calc.id)})
    db.execute(text("DELETE FROM base.mmu"))
    db.execute(text("""
        INSERT INTO base.mmu (mmuid, geom, area_ha) VALUES
        (111222, ST_GeomFromText('MULTIPOLYGON(((0 0,0.02 0,0.02 0.04,0 0.04,0 0)))', 4326), 1),
        (111223, ST_GeomFromText('MULTIPOLYGON(((0.02 0,0.04 0,0.04 0.04,0.02 0.04,0.02 0)))', 4326), 1)
    """))
    db.commit()

    res = svc.preview_union_zonal_blocks(db, calc, level="blocks")
    payload = _block_payloads(res["pieces"]["features"])
    for req, feat in zip(payload, res["pieces"]["features"]):
        req.update(feat["properties"])
    svc.commit_blocks(db, calc, payload, level="blocks", source="union_zonal")
    union_layer = db.query(svc.RasterLayer).filter(
        svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "union_zonal"
    ).one()

    # Path 1: promote_layer -- become the top-level structure.
    result = svc.promote_layer(db, calc, union_layer.id, "blocks")
    assert result["promoted_as"] == "blocks"
    # Owner report 2026-10-01: "I see this message 'union_zonal promoted' but
    # actually not promoted." The layer's own `promoted_as` flag flipping is
    # not the same claim as the structural READ endpoints
    # (blocks.py/forests.py/compartments.py, all built on
    # `promoted_or_unlayered`) actually surfacing these rows -- check that
    # directly, the same filter those endpoints apply.
    from app.services.forest_units.queries import promoted_or_unlayered
    visible = promoted_or_unlayered(
        db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id)
    ).all()
    union_rows_visible = [r for r in visible if r.raster_layer_id == union_layer.id]
    assert len(union_rows_visible) >= 1, (
        "promote_layer reported success but the Union rows are not visible "
        "through the promoted_or_unlayered filter every structural read uses"
    )
    svc.demote_layer(db, calc, union_layer.id)

    # Path 2: promote_layer_as_children -- assign into an existing parent.
    # Reuse the MMU layer RS-10.0's auto-create already produced inside
    # preview_union_zonal_blocks above as the assignment parent, rather than
    # committing a second redundant "mmu" layer.
    parent = (
        db.query(ForestBlock)
        .join(svc.RasterLayer, ForestBlock.raster_layer_id == svc.RasterLayer.id)
        .filter(svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "mmu")
        .order_by(ForestBlock.index)
        .first()
    )
    assert parent is not None
    svc.promote_layer(db, calc, parent.raster_layer_id, "blocks")  # the parent must be real structure
    result2 = svc.promote_layer_as_children(db, calc, union_layer.id, parent.id)
    assert result2["n_children"] >= 1
    children = db.query(ForestBlock).filter(ForestBlock.parent_block_id == parent.id).all()
    assert len(children) == result2["n_children"]
    # Children keep the Union layer's own 9-attribute classification, not
    # the parent's (same guarantee every other source's assign-to-parent
    # already gives, per `promote_layer_as_children`'s own docstring).
    for child in children:
        # belongs to the PARENT's (promoted) layer: real structure now, and it follows that layer
        assert child.raster_layer_id == parent.raster_layer_id


def test_union_zonal_switch_promotion_from_another_already_promoted_layer(db):
    """Owner report 2026-10-01: "I see this message 'union_zonal promoted'
    but actually not promoted." The one promotion path not yet covered by
    the test above: switching INTO union_zonal when a DIFFERENT layer
    (e.g. slope, from earlier testing) is already promoted -- the
    force=True "offers to switch" flow (D51). Checks the same
    promoted_or_unlayered-filtered visibility every structural read uses,
    not just the RasterLayer.promoted_as flag."""
    from app.services.forest_units.queries import promoted_or_unlayered

    boundary = Polygon([(0, 0), (0.04, 0), (0.04, 0.04), (0, 0.04)])
    calc = _make_calc(db, boundary=boundary)
    _seed_gis_layers(db, calc.id)
    db.execute(text("""
        UPDATE calculations SET boundary_geom =
            ST_GeomFromText('POLYGON((0 0,0.04 0,0.04 0.04,0 0.04,0 0))', 4326)
        WHERE id = :cid
    """), {"cid": str(calc.id)})
    db.execute(text("DELETE FROM base.mmu"))
    db.execute(text("""
        INSERT INTO base.mmu (mmuid, geom, area_ha) VALUES
        (222333, ST_GeomFromText('MULTIPOLYGON(((0 0,0.02 0,0.02 0.04,0 0.04,0 0)))', 4326), 1),
        (222334, ST_GeomFromText('MULTIPOLYGON(((0.02 0,0.04 0,0.04 0.04,0.02 0.04,0.02 0)))', 4326), 1)
    """))
    db.commit()

    # A different source already promoted (the pre-existing real structure
    # a planner would have from earlier testing).
    slope_payload = [{
        "index": 1, "name": "slope-1", "block_name": "slope-1",
        "natural_name": None, "geometry": boundary.__geo_interface__,
    }]
    svc.commit_blocks(db, calc, slope_payload, level="blocks", source="slope")
    slope_layer = db.query(svc.RasterLayer).filter(
        svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "slope"
    ).one()
    svc.promote_layer(db, calc, slope_layer.id, "blocks")

    # Now build and try to promote union_zonal -- must be refused WITHOUT
    # force, then succeed WITH it (the exact "switch" UX the frontend drives).
    res = svc.preview_union_zonal_blocks(db, calc, level="blocks")
    payload = _block_payloads(res["pieces"]["features"])
    for req, feat in zip(payload, res["pieces"]["features"]):
        req.update(feat["properties"])
    svc.commit_blocks(db, calc, payload, level="blocks", source="union_zonal")
    union_layer = db.query(svc.RasterLayer).filter(
        svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "union_zonal"
    ).one()

    with pytest.raises(ValueError, match="PROMOTED_LAYER_EXISTS"):
        svc.promote_layer(db, calc, union_layer.id, "blocks")

    result = svc.promote_layer(db, calc, union_layer.id, "blocks", force=True)
    assert result["promoted_as"] == "blocks"
    assert result["switched_from"] == str(slope_layer.id)

    db.refresh(slope_layer)
    db.refresh(union_layer)
    assert slope_layer.promoted_as is None
    assert union_layer.promoted_as == "blocks"

    visible = promoted_or_unlayered(
        db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id)
    ).all()
    visible_layer_ids = {r.raster_layer_id for r in visible if r.raster_layer_id is not None}
    assert union_layer.id in visible_layer_ids, "union_zonal reported promoted but its rows aren't visible"
    assert slope_layer.id not in visible_layer_ids, "slope was demoted but its rows are still visible"


def test_union_zonal_promote_as_compartments_then_switch_to_blocks(db):
    """Owner report 2026-10-01: "I did it both compartment and block" --
    the same layer promoted as compartments, then re-promoted as blocks (or
    the reverse), with no OTHER layer involved at all. Checks both the
    `is_compartment` flag and promoted_or_unlayered visibility survive the
    level switch, and that the compartments-level path (not exercised by
    any other union_zonal test, which all used "blocks") works on its own
    first."""
    from app.services.forest_units.queries import promoted_or_unlayered

    boundary = Polygon([(0, 0), (0.04, 0), (0.04, 0.04), (0, 0.04)])
    calc = _make_calc(db, boundary=boundary)
    _seed_gis_layers(db, calc.id)
    db.execute(text("""
        UPDATE calculations SET boundary_geom =
            ST_GeomFromText('POLYGON((0 0,0.04 0,0.04 0.04,0 0.04,0 0))', 4326)
        WHERE id = :cid
    """), {"cid": str(calc.id)})
    db.execute(text("DELETE FROM base.mmu"))
    db.execute(text("""
        INSERT INTO base.mmu (mmuid, geom, area_ha) VALUES
        (333444, ST_GeomFromText('MULTIPOLYGON(((0 0,0.02 0,0.02 0.04,0 0.04,0 0)))', 4326), 1),
        (333445, ST_GeomFromText('MULTIPOLYGON(((0.02 0,0.04 0,0.04 0.04,0.02 0.04,0.02 0)))', 4326), 1)
    """))
    db.commit()

    res = svc.preview_union_zonal_blocks(db, calc, level="blocks")
    payload = _block_payloads(res["pieces"]["features"])
    for req, feat in zip(payload, res["pieces"]["features"]):
        req.update(feat["properties"])
    svc.commit_blocks(db, calc, payload, level="blocks", source="union_zonal")
    union_layer = db.query(svc.RasterLayer).filter(
        svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "union_zonal"
    ).one()

    # Promote as COMPARTMENTS first.
    result = svc.promote_layer(db, calc, union_layer.id, "compartments")
    assert result["promoted_as"] == "compartments"
    db.refresh(union_layer)
    assert union_layer.promoted_as == "compartments"
    rows = db.query(ForestBlock).filter(ForestBlock.raster_layer_id == union_layer.id).all()
    assert rows and all(r.is_compartment for r in rows)
    visible = promoted_or_unlayered(
        db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id)
    ).all()
    assert any(r.raster_layer_id == union_layer.id for r in visible), (
        "promoted as compartments but not visible through promoted_or_unlayered"
    )

    # Then SWITCH the SAME layer to BLOCKS -- no other layer involved, so
    # `other_promoted` in promote_layer is None and the unique-index race
    # RS-10.10 fixed does not apply here; this exercises the simpler
    # same-layer re-promotion path instead.
    result2 = svc.promote_layer(db, calc, union_layer.id, "blocks")
    assert result2["promoted_as"] == "blocks"
    assert result2["switched_from"] is None  # no OTHER layer was demoted
    db.refresh(union_layer)
    assert union_layer.promoted_as == "blocks"
    rows2 = db.query(ForestBlock).filter(ForestBlock.raster_layer_id == union_layer.id).all()
    assert rows2 and all(not r.is_compartment for r in rows2)
    visible2 = promoted_or_unlayered(
        db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id)
    ).all()
    assert any(r.raster_layer_id == union_layer.id for r in visible2), (
        "re-promoted as blocks but not visible through promoted_or_unlayered"
    )


# ---------------------------------------------------------------------------
# RS-2.17: the boundary constraint holds PER LAYER, and switching stays recoverable
# ---------------------------------------------------------------------------

def _commit_layer(db, calc, source, geoms):
    payload = [
        {"index": i + 1, "name": f"{source}-{i + 1}", "block_name": f"{source}-{i + 1}", "natural_name": None,
         "geometry": g.__geo_interface__}
        for i, g in enumerate(geoms)
    ]
    svc.commit_blocks(db, calc, payload, level="blocks", source=source)
    return db.query(svc.RasterLayer).filter(svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == source).one()


def test_a_layer_that_does_not_cover_the_boundary_gets_its_own_remainder_and_leaves_other_layers_alone(db):
    from app.services.block_area_invariant_service import enforce_block_coverage

    boundary = Polygon([(0, 0), (0.02, 0), (0.02, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    full = _commit_layer(db, calc, "aspect", [boundary])                      # tiles the whole forest
    partial = _commit_layer(db, calc, "slope", [_square(0, 0, 0.01)])          # covers only a quarter
    before_full = db.query(ForestBlock).filter(ForestBlock.raster_layer_id == full.id).count()

    result = enforce_block_coverage(db, calc, "blocks", raster_layer_id=partial.id)

    assert result["remainder_added"] is True
    rows = db.query(ForestBlock).filter(ForestBlock.raster_layer_id == partial.id).all()
    assert len(rows) == 2                                                    # its own piece + the remainder, both tagged with ITS layer
    assert sum(to_shape(r.geometry).area for r in rows) == pytest.approx(boundary.area, rel=1e-6)
    assert db.query(ForestBlock).filter(ForestBlock.raster_layer_id == full.id).count() == before_full  # the other layer is untouched


def test_a_layer_that_spills_outside_the_boundary_is_refused_and_only_that_layer_is_judged(db):
    from app.services.block_area_invariant_service import enforce_block_coverage

    boundary = Polygon([(0, 0), (0.02, 0), (0.02, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    ok = _commit_layer(db, calc, "aspect", [boundary])
    spill = _commit_layer(db, calc, "slope", [Polygon([(0, 0), (0.03, 0), (0.03, 0.02), (0, 0.02)])])  # 50 % wider than the forest

    with pytest.raises(ValueError, match="TOPOLOGY_REJECTED"):
        enforce_block_coverage(db, calc, "blocks", raster_layer_id=spill.id)
    assert enforce_block_coverage(db, calc, "blocks", raster_layer_id=ok.id)["remainder_added"] is False  # the good layer is not dragged down


def test_switching_the_promoted_layer_is_recoverable(db):
    """Promote A, switch to B (A is demoted, its rows untouched), and switch back: nothing is lost, one stream at a time."""
    boundary = Polygon([(0, 0), (0.02, 0), (0.02, 0.02), (0, 0.02)])
    calc = _make_calc(db, boundary=boundary)
    a = _commit_layer(db, calc, "aspect", [boundary])
    b = _commit_layer(db, calc, "slope", [boundary])
    svc.promote_layer(db, calc, a.id, "blocks")
    with pytest.raises(ValueError, match="PROMOTED_LAYER_EXISTS"):
        svc.promote_layer(db, calc, b.id, "blocks")                           # a switch is asked for, never silent
    svc.promote_layer(db, calc, b.id, "blocks", force=True)
    db.refresh(a)
    db.refresh(b)
    assert (a.promoted_as, b.promoted_as) == (None, "blocks")
    assert db.query(ForestBlock).filter(ForestBlock.raster_layer_id == a.id).count() == 1   # A's rows survive the switch
    svc.promote_layer(db, calc, a.id, "blocks", force=True)                   # and the switch is reversible
    db.refresh(a)
    db.refresh(b)
    assert (a.promoted_as, b.promoted_as) == ("blocks", None)
