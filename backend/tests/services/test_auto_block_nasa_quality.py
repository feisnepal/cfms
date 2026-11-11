"""Auto-Block, NASA 2020 forest-quality source (RS-2.4). Carve along
`rasters.nasa_forest_2020` class breaks (1 = Primary, 2 = Young Secondary,
3 = Old Secondary, plus code 0 = non-forest) — same preview/commit engine as
`test_auto_block_slope.py` / `test_auto_block_canopy.py`, only the source
spec differs. The NASA source goes through the generic `raster_class_vectorize`
engine (`class_pieces` / `dominant_code` + the `NASA_QUALITY` spec), NOT the
flat-file canopy path.

Fixture mirrors the slope test's synthetic raster: a 20x20 grid, left half
value 1 (Primary), right half value 3 (Old Secondary), one isolated value-2
(Young Secondary) sliver cell that must not survive as its own piece.
"""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path

import pytest
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Polygon, shape
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services import auto_block_service as svc
from app.services.raster_class_vectorize import NASA_QUALITY, effective_floor_ha

# 20x20 grid: cols 1..10 -> 1 (Primary), cols 11..20 -> 3 (Old Secondary),
# one isolated value-2 (Young Secondary) cell inside the Primary half.
_GRID = [[3 if c >= 11 else 1 for c in range(1, 21)] for _r in range(1, 21)]
_GRID[4][4] = 2
_ARR = (
    "ARRAY["
    + ",".join("ARRAY[" + ",".join(str(v) for v in row) + "]" for row in _GRID)
    + "]::double precision[][]"
)

# Raster footprint exactly matches the forest boundary below.
_BBOX = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])

# The forest boundary the raster footprint above tiles.
_FOREST = _BBOX


@pytest.fixture()
def nasa_raster_non_forest(db):
    """RS-2.5 carve-and-anonymous: a large code-0 (non-forest) region inside
    the boundary. Left half = 0 (non-forest), right half = 1 (Primary).
    Code 0 must still become geometry (exact tiling) but never claim a NASA
    class, and must not persist as one.

    D39: `ST_AddBand` silently forces NoData to 0 on this build and
    `ST_DumpAsPolygons` drops NoData pixels, so a fixture that means to express
    class 0 must clear NoData explicitly. The live `nasa_forest_2020` band has
    NoData NULL (D39), so the fixture matches it."""
    _grid0 = [[1 if c >= 11 else 0 for c in range(1, 21)] for _r in range(1, 21)]
    arr0 = (
        "ARRAY["
        + ",".join("ARRAY[" + ",".join(str(v) for v in row) + "]" for row in _grid0)
        + "]::double precision[][]"
    )
    db.execute(text("CREATE SCHEMA IF NOT EXISTS rasters"))
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS rasters.nasa_forest_2020 "
            "(rid serial PRIMARY KEY, rast raster)"
        )
    )
    db.execute(text("DELETE FROM rasters.nasa_forest_2020"))
    db.execute(
        text(
            "INSERT INTO rasters.nasa_forest_2020 (rast) SELECT ST_SetBandNoDataValue("
            "  ST_SetValues("
            "    ST_AddBand("
            "      ST_MakeEmptyRaster(20, 20, 84.0, 27.002, 0.0001, -0.0001, 0, 0, 4326),"
            "      '8BUI'::text, 0, 0),"
            f"    1, 1, 1, {arr0}),"
            "  1, NULL)"
        )
    )
    db.commit()
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.nasa_forest_2020"))
    db.commit()


@pytest.fixture()
def nasa_raster(db):
    db.execute(text("CREATE SCHEMA IF NOT EXISTS rasters"))
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS rasters.nasa_forest_2020 "
            "(rid serial PRIMARY KEY, rast raster)"
        )
    )
    db.execute(text("DELETE FROM rasters.nasa_forest_2020"))
    db.execute(
        text(
            "INSERT INTO rasters.nasa_forest_2020 (rast) SELECT ST_SetValues("
            "  ST_AddBand("
            "    ST_MakeEmptyRaster(20, 20, 84.0, 27.002, 0.0001, -0.0001, 0, 0, 4326),"
            "    '8BUI'::text, 0, 0),"
            f"  1, 1, 1, {_ARR})"
        )
    )
    db.commit()
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.nasa_forest_2020"))
    db.commit()


def _make_user(db):
    user = User(
        email=f"nasablk{uuid.uuid4().hex[:8]}@test.com",
        full_name="NASA Block Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    return user


def _make_calc(db, boundary=_BBOX):
    user = _make_user(db)
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="nasa-block-test.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    if boundary is not None:
        calc.boundary_geom = from_shape(boundary, srid=4326)
        db.flush()
    return calc


# ---------------------------------------------------------------------------
# No raster / no boundary -> graceful, never poisons the transaction
# ---------------------------------------------------------------------------
def test_preview_no_boundary_raises(db):
    calc = _make_calc(db, boundary=None)
    with pytest.raises(ValueError, match="no_boundary"):
        svc.preview_nasa_quality_blocks(db, calc, level="blocks")


def test_preview_no_raster_raises_no_nasa_quality_coverage(db):
    calc = _make_calc(db)
    with pytest.raises(ValueError, match="no_nasa_quality_coverage"):
        svc.preview_nasa_quality_blocks(db, calc, level="blocks")
    # transaction survives the missing-table SAVEPOINT rollback
    assert db.execute(text("SELECT 1")).scalar() == 1


# ---------------------------------------------------------------------------
# With the synthetic raster
# ---------------------------------------------------------------------------
def test_registered_in_collapsed_registry():
    assert "nasa_quality" in svc.PREVIEW_FN_BY_SOURCE
    assert svc.PREVIEW_FN_BY_SOURCE["nasa_quality"] is svc.preview_nasa_quality_blocks
    assert "nasa_quality" in svc.DIVIDE_SOURCES
    assert svc.is_valid_source("nasa_quality")
    assert svc.resolve_source_fn("nasa_quality") is svc.preview_nasa_quality_blocks


def test_preview_carves_along_nasa_quality_and_drops_sliver(db, nasa_raster):
    calc = _make_calc(db)
    res = svc.preview_nasa_quality_blocks(db, calc, level="blocks")
    m = res["meta"]
    feats = res["pieces"]["features"]

    assert m["source_layer"] == "rasters.nasa_forest_2020"
    assert m["level"] == "blocks"
    # 2 real halves survive; the isolated sub-sliver value-2 cell does not
    # become a third piece (far below the ~1000 m² NASA sliver floor).
    assert len(feats) == 2
    assert m["piece_count"] == 2
    # coverage preserved (sliver's area absorbed into a neighbour, not lost)
    assert abs(m["pieces_ha"] - m["boundary_ha"]) < 0.05
    # serial naming + descending-by-area ordering
    assert all(
        re.fullmatch(r"B\d+", f["properties"]["name"]) for f in feats
    )
    areas = [f["properties"]["area_hectares"] for f in feats]
    assert areas == sorted(areas, reverse=True)
    # the two pieces tile the scope exactly (no overlap, no gap)
    assert abs(m["pieces_ha"] - m["boundary_ha"]) < 0.05

    codes = {f["properties"]["nasa_quality"] for f in feats}
    assert codes == {1, 3}
    labels = {f["properties"]["nasa_quality_label"] for f in feats}
    assert labels == {"Primary Forest", "Old Secondary Forest"}


def test_preview_code0_carved_anonymous_persists_null(db, nasa_raster_non_forest):
    """RS-2.5: code 0 (non-forest) is carved as geometry so the pieces still
    tile the boundary exactly, but it is *anonymous*: it never claims a NASA
    class, and it is never stored as one (the RS-2.3 bounds are 1-3)."""
    calc = _make_calc(db)
    res = svc.preview_nasa_quality_blocks(db, calc, level="blocks")
    feats = res["pieces"]["features"]
    # rule 9: the code-0 region still becomes geometry, so both halves exist
    assert len(feats) == 2
    assert abs(res["meta"]["pieces_ha"] - res["meta"]["boundary_ha"]) < 0.05

    codes = {f["properties"]["nasa_quality"] for f in feats}
    labels = {f["properties"]["nasa_quality_label"] for f in feats}
    # the non-forest half is anonymous (None), the forest half keeps its class
    assert codes == {None, 1}
    assert labels == {None, "Primary Forest"}
    assert "Non-forest" not in labels

    # and a commit round-trip stores null for the non-forest half
    payload = [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"],
            "natural_name": f["properties"]["natural_name"],
            "dominant_nasa_quality": f["properties"]["nasa_quality"],
            "geometry": f["geometry"],
        }
        for f in feats
    ]
    created = svc.commit_blocks(db, calc, payload, level="blocks")
    assert {c["dominant_nasa_quality"] for c in created} == {None, 1}
    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    assert {r.dominant_nasa_quality for r in rows} == {None, 1}


def test_preview_compartments_level_naming(db, nasa_raster):
    calc = _make_calc(db)
    res = svc.preview_nasa_quality_blocks(db, calc, level="compartments")
    feats = res["pieces"]["features"]
    names = [f["properties"]["name"] for f in feats]
    assert names and len(set(names)) == len(names)
    assert all(re.fullmatch(r"C\d+", n) for n in names), names
    assert all(f["properties"]["block_name"] == f["properties"]["name"] for f in feats)
    assert res["meta"]["level"] == "compartments"


def test_preview_desired_n_merges_across_classes(db, nasa_raster):
    calc = _make_calc(db)
    res = svc.preview_nasa_quality_blocks(db, calc, level="blocks", desired_n=1)
    assert res["meta"]["piece_count"] == 1
    assert abs(res["meta"]["pieces_ha"] - res["meta"]["boundary_ha"]) < 0.05


def test_preview_all_pieces_single_part(db, nasa_raster):
    calc = _make_calc(db)
    res = svc.preview_nasa_quality_blocks(db, calc, level="blocks")
    for f in res["pieces"]["features"]:
        g = shape(f["geometry"])
        assert g.geom_type == "Polygon", f"expected single-part Polygon, got {g.geom_type}"


def test_commit_after_nasa_preview_persists_dominant_nasa_quality(db, nasa_raster):
    calc = _make_calc(db)
    res = svc.preview_nasa_quality_blocks(db, calc, level="blocks")
    payload = [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"],
            "natural_name": f["properties"]["natural_name"],
            "dominant_nasa_quality": f["properties"]["nasa_quality"],
            "geometry": f["geometry"],
        }
        for f in res["pieces"]["features"]
    ]
    created = svc.commit_blocks(db, calc, payload, level="blocks")
    assert len(created) == 2
    assert {c["dominant_nasa_quality"] for c in created} == {1, 3}
    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    assert {r.dominant_nasa_quality for r in rows} == {1, 3}
    # none of the sibling raster sources leak into a NASA run
    assert all(r.dominant_health_class is None for r in rows)
    assert all(r.dominant_landcover is None for r in rows)
    assert all(r.dominant_elevation_zone is None for r in rows)
    assert all(r.elevation_min_m is None for r in rows)
    assert all(r.elevation_mean_m is None for r in rows)
    assert all(r.elevation_max_m is None for r in rows)
    assert all(r.dominant_slope_band is None for r in rows)
    assert all(r.dominant_aspect is None for r in rows)
    assert all(r.dominant_canopy_class is None for r in rows)
    assert all(to_shape(r.geometry).geom_type == "Polygon" for r in rows)


def test_children_end_to_end_tiles_parent_and_persists_dominant_nasa_quality(
    db, nasa_raster
):
    """RS-2.4 gate: carve preview -> commit round-trips through the divide
    path, pieces tile the parent scope, and the parent's code lands on the
    children. Mirrors `test_auto_divide_children.py`'s mechanism test with the
    NASA source and the raster-class engine."""
    user = _make_user(db)
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="nasa-divide.csv",
        is_draft=False,
        structure_locked=False,
        result_data={},
    )
    db.add(calc)
    db.flush()
    calc.boundary_geom = from_shape(_FOREST, srid=4326)
    db.flush()

    parent = ForestBlock(
        calculation_id=calc.id,
        name="B1",
        block_name="B1",
        geometry=from_shape(_FOREST, srid=4326),
        area_hectares=_FOREST.area * 111000 * 111000 / 10000,
        area_sqm=_FOREST.area * 111000 * 111000,
        index=1,
        is_compartment=False,
        division_level=1,
        is_locked=False,
        child_count=0,
    )
    db.add(parent)
    db.commit()

    preview = svc.preview_children(db, calc, parent.id, source="nasa_quality")
    feats = preview["pieces"]["features"]
    assert len(feats) == 2, feats
    # pieces tile the parent scope
    assert abs(preview["meta"]["pieces_ha"] - preview["meta"]["boundary_ha"]) < 0.05

    payload = [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "natural_name": f["properties"]["natural_name"],
            "dominant_nasa_quality": f["properties"]["nasa_quality"],
            "geometry": f["geometry"],
        }
        for f in feats
    ]
    done = svc.commit_children(
        db, calc, parent.id, payload, source="nasa_quality", created_by=user.id
    )
    assert done["n_children"] == 2, done

    kids = (
        db.query(ForestBlock)
        .filter(ForestBlock.parent_block_id == parent.id)
        .order_by(ForestBlock.display_order)
        .all()
    )
    assert {k.dominant_nasa_quality for k in kids} == {1, 3}
    assert all(k.dominant_slope_band is None for k in kids)
    # union of children tiles the parent
    from shapely.ops import unary_union

    union = unary_union([to_shape(k.geometry) for k in kids])
    assert union.difference(_FOREST).area < 1e-9
    assert _FOREST.difference(union).area < 1e-9


# ---------------------------------------------------------------------------
# API wiring
# ---------------------------------------------------------------------------
def _owner(client, db):
    email = f"nasaapi-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "NASA API"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def test_api_preview_source_nasa_quality(client, db, nasa_raster):
    headers, user = _owner(client, db)
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "nasa_quality"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["meta"]["source_layer"] == "rasters.nasa_forest_2020"
    assert len(body["pieces"]["features"]) == 2

    commit = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/commit",
        headers=headers,
        json={
            "level": "blocks",
            "blocks": [
                {
                    "index": f["properties"]["index"],
                    "name": f["properties"]["name"],
                    "block_name": f["properties"]["block_name"],
                    "natural_name": f["properties"]["natural_name"],
                    "dominant_nasa_quality": f["properties"]["nasa_quality"],
                    "geometry": f["geometry"],
                }
                for f in body["pieces"]["features"]
            ],
        },
    )
    assert commit.status_code == 200, commit.text


def test_api_preview_bad_source_still_rejected(client, db, nasa_raster):
    headers, user = _owner(client, db)
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "nasa_quality_bogus"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "blocks.bad_source"


# ---------------------------------------------------------------------------
# RS-2.9 / D45 -- the floor is area-aware, and the API reports the floor that
# is actually applied instead of a hardcoded 5 ha.
#
# Before this row `"minimize_floor_ha": 5.0` was a literal in all five previews
# over a filter that no preview applied: the only size filter was the 0.1 ha
# `default_sliver_m2`, which returned 467 pieces across the 14 live boundaries.
# `effective_floor_ha` existed, was exported and was unit-tested, but was called
# from nothing outside its own tests. The two static guards below exist because
# that combination -- a passing suite over behaviour that never ran -- is exactly
# what let the gap survive from RS-1.3 through RS-2.8.
# ---------------------------------------------------------------------------
def test_no_preview_hardcodes_a_five_hectare_floor():
    """A constant in the meta is the defect D45 found, and it is invisible to
    every behavioural test, so it is pinned at the source level.

    Parsed as AST rather than grepped, because a plain substring match also
    fires on any *comment* naming the literal -- which the RS-2.9 comments in
    `preview_nasa_quality_blocks` legitimately do. A guard that trips on prose
    is a guard that gets deleted, so this one looks only at real dict values.
    """
    tree = ast.parse(Path(svc.__file__).read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant)
                and key.value == "minimize_floor_ha"
                and isinstance(value, ast.Constant)
            ):
                offenders.append((key.lineno, value.value))
    assert offenders == [], (
        "a preview states a constant floor instead of deriving it from the value "
        f"in force: {offenders} (see _applied_floor_ha)"
    )


def test_effective_floor_is_called_in_production_not_merely_defined():
    """Guard the dead-code failure mode directly: at least one production CALL.

    Was pinned to exactly 1 when NASA was the only source using the
    area-aware floor; RS-9.1/9.2 (forest_health, landcover) added their own
    call sites the same way, which is growth, not a regression — the
    property worth protecting is "not zero" (dead code), not "exactly one
    file's worth of sources so far". Pinning the exact count is the same
    over-specific-assert trap this repo's own history already names (see
    CLAUDE.md's migration-heads example): each new legitimate call site
    would break this test for a reason unrelated to what it guards.
    """
    calls = re.findall(r"effective_floor_ha\(", Path(svc.__file__).read_text(encoding="utf-8"))
    assert len(calls) >= 1, (
        "expected at least one production call of effective_floor_ha in "
        "auto_block_service; 0 means the function is dead code again "
        "(the RS-1.3 regression)"
    )


def test_nasa_reports_the_area_aware_floor_not_five_ha(db, nasa_raster):
    """The reported floor is derived, and for this ~4.9 ha fixture it lands on
    the 1 ha lower bound -- emphatically not the 5 ha the API used to claim."""
    calc = _make_calc(db)
    res = svc.preview_nasa_quality_blocks(db, calc, level="blocks")
    reported = res["meta"]["minimize_floor_ha"]

    area_ha = svc._area_m2(_BBOX) / 10_000.0
    expected = effective_floor_ha(NASA_QUALITY, area_ha * 10_000.0)
    assert reported == pytest.approx(round(expected, 2)), (reported, expected)
    assert reported < 5.0, "the fixture forest is smaller than the advertised floor"


def test_floor_scales_with_forest_area():
    """Proportional, not fixed: a different number for a big forest and a small
    one, which is the whole point of dropping the fixed 5 ha. The expected values
    are the ones measured on the live boundaries (D45)."""
    big = effective_floor_ha(NASA_QUALITY, 926.8 * 10_000.0)
    mid = effective_floor_ha(NASA_QUALITY, 186.3 * 10_000.0)
    small = effective_floor_ha(NASA_QUALITY, 13.2 * 10_000.0)

    assert big > mid > small, (big, mid, small)
    assert big == pytest.approx(30.89, abs=0.01), big
    assert mid == pytest.approx(6.21, abs=0.01), mid
    assert small == pytest.approx(1.0), small  # the MIN_FLOOR_HA clamp


def test_explicit_sliver_still_wins_and_is_reported(db, nasa_raster):
    """The API's own `sliver_area_m2` keeps working, and the meta reports what
    the caller asked for rather than the area-aware default."""
    calc = _make_calc(db)
    res = svc.preview_nasa_quality_blocks(
        db, calc, level="blocks", sliver_area_m2=2_500.0
    )
    assert res["meta"]["minimize_floor_ha"] == pytest.approx(0.25)


def test_scope_area_drives_the_floor_not_the_whole_forest(db, nasa_raster):
    """A divide must floor on the piece being carved, not on the parent.

    Handing a sub-hectare scope the floor the whole forest earns would empty it:
    `effective_floor_ha` returns the whole area as one piece in that case, which
    would silently turn a divide into a no-op.
    """
    small_scope = Polygon(
        [(84.0, 27.0), (84.0005, 27.0), (84.0005, 27.0005), (84.0, 27.0005)]
    )
    calc = _make_calc(db, boundary=_BBOX)

    scope_floor = effective_floor_ha(NASA_QUALITY, svc._area_m2(small_scope))
    whole_floor = effective_floor_ha(NASA_QUALITY, svc._area_m2(_BBOX))

    res = svc.preview_nasa_quality_blocks(
        db, calc, level="blocks", scope=small_scope
    )
    assert res["meta"]["minimize_floor_ha"] == pytest.approx(round(scope_floor, 2))
    assert res["meta"]["minimize_floor_ha"] < whole_floor, (
        "the scope must not inherit the whole forest's floor"
    )
    assert res["meta"]["piece_count"] >= 1, "a scoped divide must still yield geometry"


def test_tiny_forest_floors_at_its_own_area_and_still_yields_one_piece(
    db, nasa_raster
):
    """The 'never return nothing' rule (rule 17): below the 1 ha lower bound the
    floor becomes the whole area, so the source returns one piece and surfaces the
    honest DIVISION_TOO_FEW error rather than looking like a broken raster."""
    # 0.0005 deg is ~0.25 ha at 27 N: above the 0.1 ha `default_sliver_m2`
    # pre-filter in `class_pieces` (below it a forest legitimately returns
    # `no_nasa_quality_coverage`, which is a PRE-EXISTING limit of that pre-filter
    # and not what this rule is about) but below the 1 ha `MIN_FLOOR_HA` clamp,
    # which is the band where the "return the whole area" branch is reachable.
    tiny = Polygon(
        [(84.0, 27.0), (84.0005, 27.0), (84.0005, 27.0005), (84.0, 27.0005)]
    )
    calc = _make_calc(db, boundary=tiny)
    area_ha = svc._area_m2(tiny) / 10_000.0
    assert 0.1 < area_ha < 1.0, area_ha

    assert effective_floor_ha(NASA_QUALITY, svc._area_m2(tiny)) == pytest.approx(
        area_ha
    ), "a sub-1ha forest must floor at its own area so exactly one piece survives"

    res = svc.preview_nasa_quality_blocks(db, calc, level="blocks")
    assert res["meta"]["piece_count"] >= 1


def test_minimize_n_agrees_with_the_reported_floor(db, nasa_raster):
    """`minimize_n` is the count the designer's "minimize" button jumps to, and it
    was `total_ha // 5.0` -- a third hardcoded 5 ha, independent of the floor the
    same response reported. The two disagreed, so the tooltip and the button
    described different things. It is now derived from the applied floor, which
    makes this identity the invariant worth pinning."""
    calc = _make_calc(db)
    meta = svc.preview_nasa_quality_blocks(db, calc, level="blocks")["meta"]

    floor = meta["minimize_floor_ha"]
    assert floor > 0, floor
    assert meta["minimize_n"] == max(1, int(meta["pieces_ha"] // floor)), meta
    # and it is genuinely not the old hardcoded 5 ha divisor
    assert meta["minimize_n"] != max(1, int(meta["pieces_ha"] // 5.0)) or floor == 5.0
