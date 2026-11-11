"""Auto-Block, slope-class source (SLOPE_COMPARTMENT_AND_STRATIFIED_SAMPLING_PLAN,
Part A). Carve compartments along slope-class breaks (rasters.slope_regulation,
कार्यविधि §15.2) instead of base.mmu rivers/ridges — same preview/commit engine
as `test_auto_block_mmu.py`, only the piece-fetch source differs.

Raster fixture mirrors `test_sfm_slope_vectorize.py::slope_raster`: a 20x20
grid, left half band 1, right half band 3, plus one isolated band-3 sliver
cell buried in the band-1 half (must be dropped, not survive as its own tiny
compartment).
"""

from __future__ import annotations

import re
import uuid

import pytest
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Polygon, shape
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services import auto_block_service as svc

# 20x20 grid: cols 1..10 -> band 1, cols 11..20 -> band 3, one isolated band-3 cell.
_GRID = [[3 if c >= 11 else 1 for c in range(1, 21)] for _r in range(1, 21)]
_GRID[4][4] = 3  # isolated sliver, deep inside the band-1 half
_ARR = (
    "ARRAY["
    + ",".join("ARRAY[" + ",".join(str(v) for v in row) + "]" for row in _GRID)
    + "]::double precision[][]"
)

# Raster footprint exactly matches the forest boundary below.
_BBOX = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])


@pytest.fixture()
def slope_raster(db):
    db.execute(text("CREATE SCHEMA IF NOT EXISTS rasters"))
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS rasters.slope_regulation "
            "(rid serial PRIMARY KEY, rast raster)"
        )
    )
    db.execute(text("DELETE FROM rasters.slope_regulation"))
    db.execute(
        text(
            "INSERT INTO rasters.slope_regulation (rast) SELECT ST_SetValues("
            "  ST_AddBand("
            "    ST_MakeEmptyRaster(20, 20, 84.0, 27.002, 0.0001, -0.0001, 0, 0, 4326),"
            "    '8BUI'::text, 0, 0),"
            f"  1, 1, 1, {_ARR})"
        )
    )
    db.commit()
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.slope_regulation"))
    db.commit()


def _make_user(db):
    user = User(
        email=f"slopeblk{uuid.uuid4().hex[:8]}@test.com",
        full_name="Slope Block Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    return user


def _make_calc(db, boundary=_BBOX, structure_locked=False):
    user = _make_user(db)
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="slope-block-test.csv",
        is_draft=False,
        structure_locked=structure_locked,
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
        svc.preview_slope_blocks(db, calc, level="blocks")


def test_preview_no_raster_raises_no_slope_coverage(db):
    calc = _make_calc(db)
    with pytest.raises(ValueError, match="no_slope_coverage"):
        svc.preview_slope_blocks(db, calc, level="blocks")
    # transaction survives the missing-table SAVEPOINT rollback
    assert db.execute(text("SELECT 1")).scalar() == 1


# ---------------------------------------------------------------------------
# With the synthetic raster
# ---------------------------------------------------------------------------
def test_preview_carves_along_slope_bands_and_drops_sliver(db, slope_raster):
    calc = _make_calc(db)
    res = svc.preview_slope_blocks(db, calc, level="blocks")
    m = res["meta"]
    feats = res["pieces"]["features"]

    assert m["source_layer"] == "rasters.slope_regulation"
    assert m["level"] == "blocks"
    # 2 real halves survive; the isolated sub-sliver cell does not become a
    # third piece (it is far below the ~1000 m² slope sliver floor).
    assert len(feats) == 2
    assert m["piece_count"] == 2
    # coverage preserved (sliver's area absorbed into a neighbour, not lost)
    assert abs(m["pieces_ha"] - m["boundary_ha"]) < 0.05
    # serial naming + descending-by-area ordering
    assert all(f["properties"]["name"].startswith("B") for f in feats)
    areas = [f["properties"]["area_hectares"] for f in feats]
    assert areas == sorted(areas, reverse=True)
    # each output piece is re-classified by its OWN dominant band (1 or 3
    # here), not an input tag that could go stale after sliver-absorb/merge
    bands = {f["properties"]["slope_band"] for f in feats}
    assert bands == {1, 3}
    for f in feats:
        assert f["properties"]["slope_band_label_en"]
        assert f["properties"]["slope_band_label_ne"]


def test_preview_compartments_level_naming(db, slope_raster):
    calc = _make_calc(db)
    res = svc.preview_slope_blocks(db, calc, level="compartments")
    feats = res["pieces"]["features"]
    assert all(re.fullmatch(r"C\d+", f["properties"]["name"]) for f in feats)  # C1, C2 - not C-1
    assert res["meta"]["level"] == "compartments"


def test_preview_desired_n_merges_across_bands(db, slope_raster):
    calc = _make_calc(db)
    res = svc.preview_slope_blocks(db, calc, level="blocks", desired_n=1)
    assert res["meta"]["piece_count"] == 1
    assert abs(res["meta"]["pieces_ha"] - res["meta"]["boundary_ha"]) < 0.05


def test_preview_all_pieces_single_part(db, slope_raster):
    calc = _make_calc(db)
    res = svc.preview_slope_blocks(db, calc, level="blocks")
    for f in res["pieces"]["features"]:
        g = shape(f["geometry"])
        assert g.geom_type == "Polygon", f"expected single-part Polygon, got {g.geom_type}"


def test_commit_after_slope_preview_persists_generic_rows(db, slope_raster):
    """`commit_blocks` needs no slope-specific handling — it already accepts the
    generic {geometry, name, block_name, natural_name, dominant_slope_band,
    index} shape regardless of which preview produced it. `dominant_slope_band`
    (migration 084) is what actually survives into the attribute table after
    commit — the preview response's slope_band/labels are otherwise transient."""
    calc = _make_calc(db)
    res = svc.preview_slope_blocks(db, calc, level="blocks")
    payload = [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"],
            "natural_name": f["properties"]["natural_name"],
            "dominant_slope_band": f["properties"]["slope_band"],
            "geometry": f["geometry"],
        }
        for f in res["pieces"]["features"]
    ]
    created = svc.commit_blocks(db, calc, payload, level="blocks")
    assert len(created) == 2
    assert {c["dominant_slope_band"] for c in created} == {1, 3}
    rows = (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calc.id)
        .order_by(ForestBlock.index)
        .all()
    )
    assert {r.name for r in rows} == {"B1", "B2"}
    assert {r.dominant_slope_band for r in rows} == {1, 3}
    assert all(r.division_level == 1 for r in rows)
    assert all(to_shape(r.geometry).geom_type == "Polygon" for r in rows)


def test_commit_without_dominant_slope_band_leaves_it_null(db, slope_raster):
    """MMU-sourced commits never send dominant_slope_band — it must default to
    NULL, not error or coerce to some placeholder."""
    calc = _make_calc(db)
    res = svc.preview_slope_blocks(db, calc, level="blocks")
    payload = [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"],
            "natural_name": f["properties"]["natural_name"],
            "geometry": f["geometry"],
        }
        for f in res["pieces"]["features"]
    ]
    svc.commit_blocks(db, calc, payload, level="blocks")
    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    assert all(r.dominant_slope_band is None for r in rows)


# ---------------------------------------------------------------------------
# management_orientation auto-suggestion (user report, 2026-09-12) — reuses
# SFM's own build_sfm() wholesale rather than re-deriving the classification
# chain here, so these tests control build_sfm's *output* directly rather
# than standing up the full zone/species/raster stack it would otherwise need.
# ---------------------------------------------------------------------------
def _slope_payload(res):
    return [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"],
            "natural_name": f["properties"]["natural_name"],
            "dominant_slope_band": f["properties"]["slope_band"],
            "geometry": f["geometry"],
        }
        for f in res["pieces"]["features"]
    ]


def test_commit_sets_management_orientation_from_sfm(db, slope_raster, monkeypatch):
    """commit_blocks copies each new block's `orientation` across from
    SFM's own build_sfm() result, matched by block_name -- the exact
    machinery the SFM tab itself runs, so this can never disagree with the
    live "Suggested Orientation" read elsewhere from the same cache."""
    import app.services.sustainable_fm.sfm_service as sfm_service_module

    calc = _make_calc(db)
    res = svc.preview_slope_blocks(db, calc, level="blocks")
    payload = _slope_payload(res)

    captured_variant = {}

    def _fake_build_sfm(calc_arg, db_arg, force=False, variant="baseline"):
        captured_variant["variant"] = variant
        return {
            "blocks": [
                {"block_name": "B1", "orientation": "Conservation"},
                {"block_name": "B2", "orientation": "Production"},
            ]
        }

    monkeypatch.setattr(sfm_service_module, "build_sfm", _fake_build_sfm)
    created = svc.commit_blocks(db, calc, payload, level="blocks")

    # The "user" variant is the one that trusts each new piece's own known
    # dominant_slope_band instead of a slope raster that may not cover this
    # forest at all -- exactly the case this function exists for.
    assert captured_variant["variant"] == "user"

    by_name = {c["name"]: c for c in created}
    assert by_name["B1"]["management_orientation"] == "Conservation"
    assert by_name["B2"]["management_orientation"] == "Production"

    rows = {
        r.name: r
        for r in db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    }
    assert rows["B1"].management_orientation == "Conservation"
    assert rows["B2"].management_orientation == "Production"


def test_commit_management_orientation_is_best_effort(db, slope_raster, monkeypatch):
    """A failing SFM pipeline (missing physiography/species-association
    tables, a raster read error, anything) must never break an otherwise-
    successful Auto-Block commit -- management_orientation just stays NULL,
    still settable by hand afterward."""
    import app.services.sustainable_fm.sfm_service as sfm_service_module

    calc = _make_calc(db)
    res = svc.preview_slope_blocks(db, calc, level="blocks")
    payload = _slope_payload(res)

    def _broken_build_sfm(calc_arg, db_arg, force=False, variant="baseline"):
        raise RuntimeError("simulated SFM pipeline failure")

    monkeypatch.setattr(sfm_service_module, "build_sfm", _broken_build_sfm)
    created = svc.commit_blocks(db, calc, payload, level="blocks")

    assert len(created) == 2
    assert all(c.get("management_orientation") is None for c in created)
    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    assert all(r.management_orientation is None for r in rows)


def test_commit_skips_sfm_call_without_a_slope_band(db, slope_raster, monkeypatch):
    """MMU-sourced commits (no dominant_slope_band at all) never call SFM's
    pipeline -- there is nothing slope-carved to auto-suggest an orientation
    for."""
    import app.services.sustainable_fm.sfm_service as sfm_service_module

    calc = _make_calc(db)
    res = svc.preview_slope_blocks(db, calc, level="blocks")
    payload = [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"],
            "natural_name": f["properties"]["natural_name"],
            "geometry": f["geometry"],
        }
        for f in res["pieces"]["features"]
    ]

    calls = []
    monkeypatch.setattr(
        sfm_service_module, "build_sfm",
        lambda calc_arg, db_arg, force=False: calls.append(1) or {"blocks": []},
    )
    svc.commit_blocks(db, calc, payload, level="blocks")
    assert calls == []


# ---------------------------------------------------------------------------
# API wiring — the new `source` branch in editing.py
# ---------------------------------------------------------------------------
def _owner(client, db):
    email = f"slopeapi-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Slope API"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def test_api_preview_source_slope(client, db, slope_raster):
    headers, user = _owner(client, db)
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "slope"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["meta"]["source_layer"] == "rasters.slope_regulation"
    assert len(body["pieces"]["features"]) == 2


def test_api_preview_bad_source_400(client, db):
    headers, user = _owner(client, db)
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "not-a-real-source"},
    )
    assert resp.status_code == 400


def test_api_preview_default_source_is_mmu(client, db):
    """Backward compatibility: omitting `source` keeps today's MMU behaviour."""
    headers, user = _owner(client, db)
    calc = _make_calc(db, boundary=None)
    calc.user_id = user.id
    db.commit()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks"},
    )
    # no boundary -> 409, same guard as before this change; proves the
    # default path still runs (and didn't silently switch to slope).
    assert resp.status_code == 409


def test_compartment_tree_surfaces_slope_band_after_commit(client, db, slope_raster):
    """Full round trip: preview (slope) -> commit (compartments) ->
    GET compartment-tree must carry dominant_slope_band (+ block_name /
    natural_name, previously dropped for compartments/sub-compartments) so it
    actually reaches the attribute table, not just the transient preview."""
    headers, user = _owner(client, db)
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    preview = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "compartments", "source": "slope"},
    ).json()
    blocks = [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"],
            "natural_name": f["properties"]["natural_name"],
            "dominant_slope_band": f["properties"]["slope_band"],
            "geometry": f["geometry"],
        }
        for f in preview["pieces"]["features"]
    ]
    commit = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/commit",
        headers=headers,
        json={"level": "compartments", "blocks": blocks, "source": "slope"},
    )
    assert commit.status_code == 200, commit.text

    # RS-2.16 (P2.5): a commit only creates a TRIAL layer now -- it must be
    # promoted before compartment-tree (or any other builtin-layer read)
    # will surface it, same as the owner's own "I created using mmu
    # auto-block... it auto created in compartment or block which I do not
    # want" report fixed by excluding unpromoted layers from these reads.
    layers = client.get(
        f"/api/v1/calculations/{calc.id}/auto-block-layers", headers=headers,
    ).json()["layers"]
    layer_id = next(l["id"] for l in layers if l["source"] == "slope")
    promote = client.post(
        f"/api/v1/calculations/{calc.id}/auto-block-layers/{layer_id}/promote",
        headers=headers, json={"as_level": "compartments"},
    )
    assert promote.status_code == 200, promote.text

    tree = client.get(
        f"/api/compartments/calculations/{calc.id}/compartment-tree",
        headers=headers,
    ).json()
    nodes = tree["blocks"]
    assert len(nodes) == 2
    assert {n["dominant_slope_band"] for n in nodes} == {1, 3}
    assert all(re.fullmatch(r"C\d+", n["block_name"] or "") for n in nodes)


def test_preview_a_second_source_after_committing_the_first_does_not_refuse(client, db, slope_raster):
    """Owner report 2026-10-01: "I am able to auto-create block or compartment
    only once... the system is not allowing me although no layer can be seen
    in compartment/block layer." Root cause: the PREVIEW endpoint (not just
    commit) still had the OLD raw "any row exists" check, never narrowed to
    legacy-only when the commit-side one was -- so the dialogue refused a
    second source's PREVIEW (before Commit is ever clicked) even though
    nothing was promoted or visible anywhere."""
    headers, user = _owner(client, db)
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    preview1 = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers, json={"level": "blocks", "source": "slope"},
    ).json()
    blocks = [
        {
            "index": f["properties"]["index"], "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"], "natural_name": f["properties"]["natural_name"],
            "dominant_slope_band": f["properties"]["slope_band"], "geometry": f["geometry"],
        }
        for f in preview1["pieces"]["features"]
    ]
    commit = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/commit",
        headers=headers, json={"level": "blocks", "blocks": blocks, "source": "slope"},
    )
    assert commit.status_code == 200, commit.text

    # A second source's PREVIEW, with the first still unpromoted, must NOT
    # raise 409 BLOCKS_EXIST -- this is the dialogue's own first call, before
    # any second Commit is attempted.
    preview2 = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers, json={"level": "blocks", "source": "slope"},
    )
    assert preview2.status_code == 200, preview2.text


def test_orientation_is_null_at_commit_but_populated_after_promote(db, slope_raster, monkeypatch):
    """Owner report 2026-10-01: "After promoting in compartment/block ...
    Management Orientation / Suggested Orientation / Justification must be
    populated." Root cause, found by re-reading the real code rather than
    trusting the EXISTING orientation tests above: those mock `build_sfm`
    with a function that returns a fixed dict regardless of what's actually
    in the DB, so they never noticed that `commit_blocks(source="slope", ...)`
    (a LAYER-SCOPED commit, unlike those tests' bare `commit_blocks(...)`
    call with no `source`) leaves the new rows unpromoted -- and the real
    `build_sfm` only sees promoted/unlayered rows
    (`forest_units.queries.unit_rows` -> `promoted_or_unlayered`). This test
    uses a fake `build_sfm` that itself calls the REAL `unit_rows`, so it
    actually exercises that filter instead of papering over it."""
    import app.services.sustainable_fm.sfm_service as sfm_service_module
    from app.services.forest_units import queries as unit_queries

    def _visibility_aware_build_sfm(calc_arg, db_arg, force=False, variant="baseline"):
        visible = unit_queries.unit_rows(db_arg, calc_arg.id, unit_queries.View.LEAF)
        return {
            "blocks": [
                {"block_name": r.block_name or r.name, "orientation": "Conservation"}
                for r in visible
            ]
        }

    monkeypatch.setattr(sfm_service_module, "build_sfm", _visibility_aware_build_sfm)

    calc = _make_calc(db)
    res = svc.preview_slope_blocks(db, calc, level="blocks")
    payload = _slope_payload(res)
    created = svc.commit_blocks(db, calc, payload, level="blocks", source="slope")
    layer = db.query(svc.RasterLayer).filter(svc.RasterLayer.calculation_id == calc.id).one()

    # At commit, the layer is still an unpromoted trial -- the real
    # visibility-aware build_sfm finds nothing to match, so orientation stays
    # NULL. This is the bug the owner reported, now the documented/expected
    # state at THIS point rather than a silent gap.
    rows_after_commit = db.query(ForestBlock).filter(ForestBlock.raster_layer_id == layer.id).all()
    assert all(r.management_orientation is None for r in rows_after_commit)
    assert all(c.get("management_orientation") is None for c in created)

    svc.promote_layer(db, calc, layer.id, "blocks")

    rows_after_promote = db.query(ForestBlock).filter(ForestBlock.raster_layer_id == layer.id).all()
    assert rows_after_promote, "promotion must not have removed the rows"
    assert all(r.management_orientation == "Conservation" for r in rows_after_promote)
    assert all(r.suggested_orientation == "Conservation" for r in rows_after_promote)


def test_orientation_populated_after_assign_as_children(db, slope_raster, monkeypatch):
    """Same fix as above, for the OTHER assignment path (RS-10.6): a layer
    assigned as children under an existing parent becomes real (unlayered)
    structure immediately, so it needs the same orientation call -- it had
    none at all before this fix, not even the commit-time no-op the
    top-level path had."""
    import app.services.sustainable_fm.sfm_service as sfm_service_module
    from app.services.forest_units import queries as unit_queries

    def _visibility_aware_build_sfm(calc_arg, db_arg, force=False, variant="baseline"):
        visible = unit_queries.unit_rows(db_arg, calc_arg.id, unit_queries.View.LEAF)
        return {
            "blocks": [
                {"block_name": r.block_name or r.name, "orientation": "Production"}
                for r in visible
            ]
        }

    monkeypatch.setattr(sfm_service_module, "build_sfm", _visibility_aware_build_sfm)

    boundary = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])
    calc = _make_calc(db, boundary=boundary)
    parent_payload = [{
        "index": 1, "name": "B1", "block_name": "B1",
        "natural_name": None, "geometry": boundary.__geo_interface__,
    }]
    svc.commit_blocks(db, calc, parent_payload, level="blocks", source="mmu")
    parent = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).one()
    svc.promote_layer(db, calc, parent.raster_layer_id, "blocks")  # the parent must be real structure

    res = svc.preview_slope_blocks(db, calc, level="blocks")
    payload = _slope_payload(res)
    svc.commit_blocks(db, calc, payload, level="blocks", source="slope")
    layer = db.query(svc.RasterLayer).filter(
        svc.RasterLayer.calculation_id == calc.id, svc.RasterLayer.source == "slope"
    ).one()

    svc.promote_layer_as_children(db, calc, layer.id, parent.id)

    children = db.query(ForestBlock).filter(ForestBlock.parent_block_id == parent.id).all()
    assert children, "children must have been created"
    assert all(c.management_orientation == "Production" for c in children)
    assert all(c.suggested_orientation == "Production" for c in children)


def test_promote_refuses_loudly_on_a_layer_emptied_by_deleting_its_compartments(client, db, slope_raster):
    """Owner report 2026-10-02: "I promoted union as compartment and I
    deleted compartment. Demoted it as try. And tried to assign as block
    again but it is not assigned. Neither I see any error." Root cause:
    the ordinary compartment DELETE endpoint has no idea a row came from a
    promoted RasterLayer and never touched it, so deleting the layer's
    last compartment left the layer silently orphaned -- still carrying
    `promoted_as`, with zero rows underneath. A later `promote_layer` call
    on that orphan used to commit a bare "success" with nothing to show.

    Two things this test pins: (1) the delete endpoint itself now demotes
    the now-empty layer (`demote_orphaned_layers`), and (2) a second
    `promote_layer` call on it refuses loudly (`EMPTY_LAYER`) instead of
    lying, covering the case where it's STILL somehow marked promoted."""
    headers, user = _owner(client, db)
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    preview = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers, json={"level": "compartments", "source": "slope"},
    ).json()
    blocks = [
        {
            "index": f["properties"]["index"], "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"], "natural_name": f["properties"]["natural_name"],
            "dominant_slope_band": f["properties"]["slope_band"], "geometry": f["geometry"],
        }
        for f in preview["pieces"]["features"]
    ]
    commit = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/commit",
        headers=headers, json={"level": "compartments", "blocks": blocks, "source": "slope"},
    )
    assert commit.status_code == 200, commit.text

    layers = client.get(
        f"/api/v1/calculations/{calc.id}/auto-block-layers", headers=headers,
    ).json()["layers"]
    layer_id = next(l["id"] for l in layers if l["source"] == "slope")
    promote = client.post(
        f"/api/v1/calculations/{calc.id}/auto-block-layers/{layer_id}/promote",
        headers=headers, json={"as_level": "compartments"},
    )
    assert promote.status_code == 200, promote.text

    # Delete every compartment the layer created, through the ORDINARY
    # compartment-delete endpoint -- not auto_block_service.delete_layer.
    compartment_ids = [
        str(r.id) for r in db.query(ForestBlock).filter(ForestBlock.raster_layer_id == layer_id).all()
    ]
    assert compartment_ids
    for cid in compartment_ids:
        d = client.delete(f"/api/compartments/{cid}", headers=headers)
        assert d.status_code == 200, d.text

    # The layer must now be demoted automatically -- no longer claiming to
    # be the forest's real structure with nothing underneath.
    layers_after_delete = client.get(
        f"/api/v1/calculations/{calc.id}/auto-block-layers", headers=headers,
    ).json()["layers"]
    layer_after_delete = next(l for l in layers_after_delete if l["id"] == layer_id)
    assert layer_after_delete["promoted_as"] is None, (
        "deleting the layer's last compartment must demote it, not leave it "
        "silently claiming to be promoted with zero rows"
    )

    # Promoting the now-empty layer again must refuse loudly, never commit
    # a silent no-op "success".
    reassign = client.post(
        f"/api/v1/calculations/{calc.id}/auto-block-layers/{layer_id}/promote",
        headers=headers, json={"as_level": "blocks"},
    )
    assert reassign.status_code == 409, reassign.text
