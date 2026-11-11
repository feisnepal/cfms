"""SL-6a / SL-7 -- every way a unit can change keeps "undivided units tile the boundary exactly once".

Owner rule, 2026-10-03: sub-compartment total = compartment total = forest outer-boundary area, always.
The Sub-Compartment / Sub-Block layers show every undivided unit, so for a forest built in this system the
undivided (LEAF) units must tile the boundary: no overlap, nothing outside, no gap.

This file is the proof harness. ``tiling()`` is the oracle; each scenario drives ONE real endpoint on a
synthetic forest (``fixtures.py``) and asserts the oracle afterwards. A scenario that fails is a path that
can break the owner's rule -- that is the finding, not a test to loosen.

Run: ``cd backend && python -m pytest tests/structure/test_unit_coverage_invariant.py -p no:cacheprovider``
"""

from __future__ import annotations

import pytest
from geoalchemy2.shape import to_shape
from shapely.ops import unary_union

from app.models.calculation import Calculation
from app.models.user import User, UserStatus
from app.services.forest_units import queries as fu
from app.services.geometry_edit_service import area_sqm
from app.utils.auth import hash_password

PASSWORD = "TestPass123!"
# Relative tolerance on each measured quantity. The fixtures are degree-sized rectangles, and the
# operations clip/union in lon-lat space, so tiny float slivers are expected; anything near 0.1 % is a bug.
REL_TOL = 0.001


def tiling(db, calc_id):
    """Measure how the undivided units sit on the boundary. Returns hectares and a verdict."""
    db.expire_all()
    calc = db.query(Calculation).filter(Calculation.id == str(calc_id)).first()
    boundary = to_shape(calc.boundary_geom)
    rows = fu.unit_rows(db, calc_id, fu.View.LEAF)
    geoms = [to_shape(r.geometry) for r in rows if r.geometry is not None]
    assert geoms, "forest has no undivided units"
    union = unary_union(geoms)
    ha = lambda g: area_sqm(g) / 10_000.0 if not g.is_empty else 0.0  # noqa: E731
    boundary_ha = ha(boundary)
    units_ha = sum(ha(g) for g in geoms)
    out = {
        "n": len(geoms),
        "boundary_ha": boundary_ha,
        "units_ha": units_ha,
        "overlap_ha": max(units_ha - ha(union), 0.0),
        "outside_ha": ha(union.difference(boundary)),
        "gap_ha": ha(boundary.difference(union)),
    }
    tol = boundary_ha * REL_TOL
    out["ok"] = all(out[k] <= tol for k in ("overlap_ha", "outside_ha", "gap_ha"))
    return out


def assert_tiles(db, calc_id, label=""):
    t = tiling(db, calc_id)
    assert t["ok"], f"{label}: units do not tile the boundary: {t}"
    return t


@pytest.fixture()
def owner_headers(client, db):
    """Headers for the fixture forest's own owner (the fixtures give each forest its own user)."""

    def _for(forest):
        user = db.query(User).filter(User.id == forest.user_id).first()
        user.hashed_password = hash_password(PASSWORD)
        user.status = UserStatus.ACTIVE
        db.commit()
        r = client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _for


def _post(client, headers, forest, path, body):
    return client.post(f"/api/calculations/{forest.calc_id}/{path}", json=body, headers=headers)


def _line(x0, y0, x1, y1):
    return {"type": "LineString", "coordinates": [[x0, y0], [x1, y1]]}


# ---------------------------------------------------------------------------------------------
# the oracle itself
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["F1", "F2", "F3", "F4"])
def test_fixture_forests_start_tiled(db, make_forest, key):
    """Guards the oracle: the synthetic forests tile their boundary, so a later failure is the operation's."""
    f = make_forest(key)
    assert_tiles(db, f.calc_id, key)


def test_oracle_detects_a_gap_overlap_and_outside(db, make_forest):
    from geoalchemy2.shape import from_shape
    from shapely.geometry import box

    from app.models.forest_block import ForestBlock

    f = make_forest("F2")
    x0, y0, x1, y1 = f.unit_geoms["C3"].bounds
    w = x1 - x0
    row = db.query(ForestBlock).filter(ForestBlock.id == f.units["C3"]).first()

    row.geometry = from_shape(box(x0, y0, x0 + w * 0.8, y1), srid=4326)  # shrink C3 -> gap
    db.commit()
    t = tiling(db, f.calc_id)
    assert not t["ok"] and t["gap_ha"] > 0

    row.geometry = from_shape(box(x0 - w * 0.2, y0, x1, y1), srid=4326)  # overlap C2
    db.commit()
    t = tiling(db, f.calc_id)
    assert not t["ok"] and t["overlap_ha"] > 0

    row.geometry = from_shape(box(x0, y0, x1 + w * 0.2, y1), srid=4326)  # outside the boundary
    db.commit()
    t = tiling(db, f.calc_id)
    assert not t["ok"] and t["outside_ha"] > 0


# ---------------------------------------------------------------------------------------------
# scenarios: one real endpoint each
# ---------------------------------------------------------------------------------------------

def _box_geojson(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def test_delete_a_unit_keeps_the_forest_tiled(client, db, make_forest, owner_headers):
    f = make_forest("F2")
    h = owner_headers(f)
    r = client.delete(f"/api/forests/calculations/{f.calc_id}/blocks/{f.units['C2']}?confirm_children=true", headers=h)
    assert r.status_code in (200, 204), r.text
    assert_tiles(db, f.calc_id, "delete C2")


def test_cut_a_unit_keeps_the_forest_tiled(client, db, make_forest, owner_headers):
    f = make_forest("F2")
    h = owner_headers(f)
    x0, y0, x1, y1 = f.unit_geoms["C2"].bounds
    xm = (x0 + x1) / 2
    r = _post(client, h, f, "geometry/cut-polygon", {
        "layer_type": "compartments", "feature_id": str(f.units["C2"]),
        "cut_line": _line(xm, y0 - 0.01, xm, y1 + 0.01),
    })
    assert r.status_code == 200, r.text
    t = assert_tiles(db, f.calc_id, "cut C2")
    assert t["n"] == 4  # C1, two halves, C3


def test_merge_two_units_keeps_the_forest_tiled(client, db, make_forest, owner_headers):
    f = make_forest("F2")
    h = owner_headers(f)
    r = _post(client, h, f, "geometry/merge-features", {
        "layer_type": "compartments", "feature_ids": [str(f.units["C1"]), str(f.units["C2"])],
    })
    assert r.status_code == 200, r.text
    t = assert_tiles(db, f.calc_id, "merge C1+C2")
    assert t["n"] == 2


@pytest.mark.parametrize("key,layer,unit", [("F2", "sub_compartments", "C2"), ("F1", "sub_blocks", "B1")])
def test_divide_a_unit_keeps_the_forest_tiled(client, db, make_forest, owner_headers, key, layer, unit):
    f = make_forest(key)
    h = owner_headers(f)
    r = _post(client, h, f, "geometry/divide-equal-areas", {
        "layer_type": layer, "feature_id": str(f.units[unit]), "method": "strips",
        "count": 3, "direction": "vertical",
    })
    assert r.status_code == 200, r.text
    t = assert_tiles(db, f.calc_id, f"divide {unit}")
    assert t["n"] == len(f.units) - 1 + 3  # the divided unit is replaced by 3 children


def _poly_geojson(*pts):
    return {"type": "Polygon", "coordinates": [[list(p) for p in pts] + [list(pts[0])]]}


def _bulge(left, right, d):
    """Two neighbours sharing a vertical edge. Move the MIDDLE of that edge by ``d`` (an interior shared
    vertex -- the only kind the vertex rules let a user move); both outlines stay consistent, so the pair
    still tiles. ``left``/``right`` are the (minx, miny, maxx, maxy) bounds of each."""
    ym = (left[1] + left[3]) / 2
    xs = left[2]
    mid = (xs + d, ym)
    left_geom = _poly_geojson((left[0], left[1]), (xs, left[1]), mid, (xs, left[3]), (left[0], left[3]))
    right_geom = _poly_geojson((xs, right[1]), (right[2], right[1]), (right[2], right[3]), (xs, right[3]), mid)
    return left_geom, right_geom


@pytest.mark.parametrize("move", ["into_right", "into_left"])
def test_move_a_shared_edge_keeps_the_forest_tiled(client, db, make_forest, owner_headers, move):
    """Two undivided neighbours share an edge; moving its middle vertex (shared_moves) must keep them tiling."""
    f = make_forest("F2")
    h = owner_headers(f)
    c1, c2 = f.unit_geoms["C1"].bounds, f.unit_geoms["C2"].bounds
    d = (c1[2] - c1[0]) * 0.25 * (1 if move == "into_right" else -1)
    g1, g2 = _bulge(c1, c2, d)
    r = _post(client, h, f, "geometry/edit-geometry", {
        "layer_type": "compartments", "feature_id": str(f.units["C1"]), "geometry": g1,
        "shared_moves": [{"feature_id": str(f.units["C2"]), "geometry": g2}],
    })
    assert r.status_code == 200, r.text
    assert_tiles(db, f.calc_id, f"move shared edge ({move})")


@pytest.mark.parametrize("move", ["grow_parent", "shrink_parent"])
def test_reshape_a_divided_parent_keeps_the_forest_tiled(client, db, make_forest, owner_headers, move):
    """F3: B1 is divided into SB1/SB2, B2 is undivided. Move the middle of the B1/B2 edge; B1's children
    must be re-clipped (trimmed, or a remainder sub-unit added) so the undivided units still tile."""
    f = make_forest("F3")
    h = owner_headers(f)
    b1, b2 = f.unit_geoms["B1"].bounds, f.unit_geoms["B2"].bounds
    d = (b1[2] - b1[0]) * 0.25 * (1 if move == "grow_parent" else -1)
    g1, g2 = _bulge(b1, b2, d)
    r = _post(client, h, f, "geometry/edit-geometry", {
        "layer_type": "blocks", "feature_id": str(f.units["B1"]), "geometry": g1,
        "shared_moves": [{"feature_id": str(f.units["B2"]), "geometry": g2}],
    })
    assert r.status_code == 200, r.text
    assert_tiles(db, f.calc_id, f"reshape divided parent ({move})")


def test_draw_over_existing_units_never_breaks_tiling(client, db, make_forest, owner_headers):
    """The forest is fully covered, so any drawn unit overlaps something. It may be refused or carved --
    but after the call the units must still tile the boundary."""
    f = make_forest("F2")
    h = owner_headers(f)
    x0, y0, x1, y1 = f.unit_geoms["C3"].bounds
    r = _post(client, h, f, "blocks/draw", {
        "level": "compartments", "name": "Drawn",
        "geometry": _box_geojson(x0 + (x1 - x0) * 0.5, y0, x1 + (x1 - x0) * 0.2, y1),
    })
    assert r.status_code < 500, r.text
    assert_tiles(db, f.calc_id, f"draw (HTTP {r.status_code})")


# ---------------------------------------------------------------------------------------------
# creation paths that ADD units: each must be refused, carved, or completed -- never leave a gap/overlap
# ---------------------------------------------------------------------------------------------

def _points_over(geom, frac=0.5):
    """Click points forming a rectangle over the right part of ``geom`` (and a little past it)."""
    x0, y0, x1, y1 = geom.bounds
    w = x1 - x0
    xa, xb = x0 + w * frac, x1 + w * 0.1
    return [[xa, y0], [xb, y0], [xb, y1], [xa, y1]]


@pytest.mark.parametrize("key,target,over", [
    ("F2", "compartments", "C3"),
    ("F2", "sub_compartments", "C2"),
    ("F1", "blocks", "B2"),
    ("F1", "sub_blocks", "B1"),
])
def test_polygon_from_points_never_breaks_tiling(client, db, make_forest, owner_headers, key, target, over):
    f = make_forest(key)
    h = owner_headers(f)
    r = client.post(
        f"/api/workspace/{f.calc_id}/polygon-from-points",
        json={"points": _points_over(f.unit_geoms[over]), "target_type": target, "name": "FromPoints"},
        headers=h,
    )
    assert r.status_code < 500, r.text
    assert_tiles(db, f.calc_id, f"polygon-from-points -> {target} (HTTP {r.status_code})")


@pytest.mark.parametrize("key,layer,over,parent", [
    ("F2", "compartments", "C3", None),
    ("F2", "sub_compartments", "C2", "C2"),
    ("F1", "blocks", "B2", None),
    ("F1", "sub_blocks", "B1", "B1"),
])
def test_paste_never_breaks_tiling(client, db, make_forest, owner_headers, key, layer, over, parent):
    f = make_forest(key)
    h = owner_headers(f)
    x0, y0, x1, y1 = f.unit_geoms[over].bounds
    w = x1 - x0
    geom = _box_geojson(x0 + w * 0.5, y0, x1 + w * 0.1, y1)
    body = {"layer_type": layer, "features": [geom], "preview": False}
    if parent:
        body["parent_id"] = str(f.units[parent])
    r = _post(client, h, f, "geometry/paste-units", body)
    assert r.status_code < 500, r.text
    assert_tiles(db, f.calc_id, f"paste -> {layer} (HTTP {r.status_code})")


def _two_halves(boundary):
    x0, y0, x1, y1 = boundary.bounds
    xm = (x0 + x1) / 2
    return [
        {"geometry": _box_geojson(x0, y0, xm, y1), "name": "P1", "block_name": "P1", "index": 1},
        {"geometry": _box_geojson(xm, y0, x1, y1), "name": "P2", "block_name": "P2", "index": 2},
    ]


@pytest.mark.parametrize("coverage", ["full", "left_60_percent"])
@pytest.mark.parametrize("level", ["blocks", "compartments"])
def test_auto_block_commit_then_promote_tiles_the_forest(client, db, make_forest, owner_headers, level, coverage):
    """Carve a whole forest from a source, commit it as an unpromoted layer, promote it: the promoted units
    must tile the boundary (a partial carve is completed with a Remainder unit by the area invariant)."""
    f = make_forest("F0")
    h = owner_headers(f)
    pieces = _two_halves(f.boundary)
    if coverage != "full":
        x0, y0, x1, y1 = f.boundary.bounds
        pieces = [{"geometry": _box_geojson(x0, y0, x0 + (x1 - x0) * 0.6, y1), "name": "P1", "block_name": "P1", "index": 1}]
    r = _post(client, h, f, "auto-blocks/commit", {"level": level, "blocks": pieces, "source": "mmu"})
    assert r.status_code == 200, r.text
    layers = client.get(f"/api/calculations/{f.calc_id}/auto-block-layers", headers=h)
    assert layers.status_code == 200, layers.text
    layer_id = layers.json()["layers"][0]["id"] if isinstance(layers.json(), dict) else layers.json()[0]["id"]
    p = _post(client, h, f, f"auto-block-layers/{layer_id}/promote", {"as_level": level})
    assert p.status_code == 200, p.text
    assert_tiles(db, f.calc_id, f"commit+promote {level} ({coverage})")


def test_paste_over_a_divided_sibling_keeps_the_forest_tiled(client, db, make_forest, owner_headers):
    """F3: B1 is divided (SB1/SB2). A block pasted over B1's right half takes that ground, so B1 shrinks --
    and B1's own children must shrink with it, or they would still cover ground the new block owns."""
    f = make_forest("F3")
    h = owner_headers(f)
    x0, y0, x1, y1 = f.unit_geoms["B1"].bounds
    w = x1 - x0
    r = _post(client, h, f, "geometry/paste-units", {
        "layer_type": "blocks", "features": [_box_geojson(x0 + w * 0.6, y0, x1, y1)], "preview": False,
    })
    assert r.status_code == 200, r.text
    assert_tiles(db, f.calc_id, "paste over a divided sibling")


def test_delete_then_restore_a_unit_keeps_the_forest_tiled(client, db, make_forest, owner_headers):
    """Undo of a delete. Deleting C2 makes the area invariant add a Remainder over the gap; restoring C2
    (same id, same ground) must not leave it overlapping that Remainder."""
    from geoalchemy2.shape import to_shape as _ts

    from app.models.forest_block import ForestBlock

    f = make_forest("F2")
    h = owner_headers(f)
    row = db.query(ForestBlock).filter(ForestBlock.id == f.units["C2"]).first()
    snapshot = {
        "name": row.name, "geometry": __import__("shapely.geometry", fromlist=["mapping"]).mapping(_ts(row.geometry)),
        "area_hectares": row.area_hectares, "area_sqm": row.area_sqm, "index": row.index,
        "is_compartment": True, "division_level": row.division_level, "parent_block_id": None,
    }
    d = client.delete(f"/api/forests/calculations/{f.calc_id}/blocks/{f.units['C2']}?confirm_children=true", headers=h)
    assert d.status_code in (200, 204), d.text
    r = _post(client, h, f, "geometry/restore-feature", {
        "layer_type": "compartments", "feature_id": str(f.units["C2"]), "snapshot": snapshot,
    })
    assert r.status_code < 500, r.text
    assert_tiles(db, f.calc_id, f"delete then restore (restore HTTP {r.status_code})")


def test_copy_boundary_to_block_on_an_empty_forest_tiles_it(client, db, make_forest, owner_headers):
    f = make_forest("F0")
    h = owner_headers(f)
    r = _post(client, h, f, "geometry/copy-boundary-to-block", {"level": "blocks"})
    assert r.status_code < 500, r.text
    if r.status_code == 200:
        assert_tiles(db, f.calc_id, "copy boundary to block")


@pytest.mark.parametrize("method,params", [
    ("parallel", {"direction_angle": 90, "num_compartments": 3}),
])
def test_legacy_sub_divide_keeps_the_forest_tiled(client, db, make_forest, owner_headers, method, params):
    """The older `/compartments/blocks/{id}/sub-divide` endpoint the UI still calls."""
    f = make_forest("F2")
    h = owner_headers(f)
    r = client.post(
        f"/api/compartments/blocks/{f.units['C2']}/sub-divide",
        json={"method": method, "parameters": params, "naming_pattern": "{parent_name}-S{index}", "reassign_trees": False},
        headers=h,
    )
    assert r.status_code < 500, r.text
    assert_tiles(db, f.calc_id, f"legacy sub-divide (HTTP {r.status_code})")


def _layer_with_pieces(db, forest, pieces, level_is_compartment=True):
    """An UNPROMOTED Auto-Block layer carrying ``pieces`` (shapely polygons), as a commit would leave it."""
    from geoalchemy2.shape import from_shape

    from app.models.forest_block import ForestBlock
    from app.services.auto_block_service import _create_layer
    from app.services.geometry_edit_service import area_sqm as _area

    calc = db.query(Calculation).filter(Calculation.id == str(forest.calc_id)).first()
    layer = _create_layer(db, calc, "mmu")
    db.flush()
    for i, g in enumerate(pieces, start=1):
        db.add(ForestBlock(
            calculation_id=calc.id, name=f"L{i}", block_name=f"L{i}", geometry=from_shape(g, srid=4326),
            area_hectares=round(_area(g) / 10_000.0, 4), area_sqm=round(_area(g), 2), index=i,
            is_compartment=level_is_compartment, division_level=1, raster_layer_id=layer.id,
        ))
    db.commit()
    return layer


@pytest.mark.parametrize("key,parent,is_comp", [("F2", "C2", True), ("F1", "B1", False)])
@pytest.mark.parametrize("coverage", ["covers_parent", "covers_half_of_parent"])
def test_assign_layer_as_children_keeps_the_forest_tiled(client, db, make_forest, owner_headers, key, parent, is_comp, coverage):
    from shapely.geometry import box

    f = make_forest(key)
    h = owner_headers(f)
    x0, y0, x1, y1 = f.unit_geoms[parent].bounds
    if coverage == "covers_parent":
        xm = (x0 + x1) / 2
        pieces = [box(x0 - 0.001, y0 - 0.001, xm, y1 + 0.001), box(xm, y0 - 0.001, x1 + 0.001, y1 + 0.001)]
    else:
        xm = (x0 + x1) / 2
        pieces = [box(x0, y0, xm, y1)]  # the layer only reaches half the parent
    layer = _layer_with_pieces(db, f, pieces, level_is_compartment=is_comp)
    r = _post(client, h, f, f"auto-block-layers/{layer.id}/assign-children", {"parent_id": str(f.units[parent])})
    assert r.status_code < 500, r.text
    assert_tiles(db, f.calc_id, f"assign layer as children ({coverage}, HTTP {r.status_code})")


def test_import_blocks_never_breaks_tiling(client, db, make_forest, owner_headers):
    """The block importer (`import-blocks`): a file that covers only part of the forest, or overlaps what is
    there, must still leave the undivided units tiling the boundary."""
    f = make_forest("F1")
    h = owner_headers(f)
    x0, y0, x1, y1 = f.boundary.bounds
    xm = (x0 + x1) / 2
    r = client.post(
        f"/api/forests/calculations/{f.calc_id}/import-blocks",
        json={"blocks": [{"geometry": _box_geojson(x0, y0, xm + (x1 - x0) * 0.1, y1), "name": "Imported", "index": 0}]},
        headers=h,
    )
    assert r.status_code < 500, r.text
    assert_tiles(db, f.calc_id, f"import-blocks (HTTP {r.status_code})")


# ---------------------------------------------------------------------------------------------
# a promoted Auto-Block layer's units keep their layer through every edit (owner report 2026-10-03)
# ---------------------------------------------------------------------------------------------

def _visible_units(db, calc_id):
    db.expire_all()
    return fu.unit_rows(db, calc_id, fu.View.LEAF)


def _promote_two_halves(client, db, f, h, level="compartments"):
    r = _post(client, h, f, "auto-blocks/commit", {"level": level, "blocks": _two_halves(f.boundary), "source": "slope"})
    assert r.status_code == 200, r.text
    layers = client.get(f"/api/calculations/{f.calc_id}/auto-block-layers", headers=h).json()
    layer_id = layers["layers"][0]["id"] if isinstance(layers, dict) else layers[0]["id"]
    p = _post(client, h, f, f"auto-block-layers/{layer_id}/promote", {"as_level": level})
    assert p.status_code == 200, p.text
    return layer_id


@pytest.mark.parametrize("edit", ["divide", "cut", "merge"])
def test_edits_on_a_promoted_layer_stay_in_the_layer_so_demote_and_repromote_work(client, db, make_forest, owner_headers, edit):
    """Promote a layer, edit its units (equal-area divide / cut / merge), demote it. Everything that came from
    the layer must go back to being a trial with it -- no orphan unit left visible -- and the layer must be
    promotable again (it used to fail with 'This forest already has blocks/compartments created before layers
    existed', because the edit's new rows carried no layer and read as legacy structure)."""
    f = make_forest("F0")
    h = owner_headers(f)
    layer_id = _promote_two_halves(client, db, f, h)
    units = _visible_units(db, f.calc_id)
    assert len(units) == 2
    first = units[0]

    if edit == "divide":
        r = _post(client, h, f, "geometry/divide-equal-areas", {
            "layer_type": "sub_compartments", "feature_id": str(first.id), "method": "strips", "count": 3, "direction": "vertical"})
    elif edit == "cut":
        x0, y0, x1, y1 = to_shape(first.geometry).bounds
        xm = (x0 + x1) / 2
        r = _post(client, h, f, "geometry/cut-polygon", {
            "layer_type": "compartments", "feature_id": str(first.id), "cut_line": _line(xm, y0 - 0.01, xm, y1 + 0.01)})
    else:
        r = _post(client, h, f, "geometry/merge-features", {
            "layer_type": "compartments", "feature_ids": [str(u.id) for u in units]})
    assert r.status_code == 200, r.text
    assert_tiles(db, f.calc_id, f"after {edit}")
    edited = len(_visible_units(db, f.calc_id))

    d = client.post(f"/api/calculations/{f.calc_id}/auto-block-layers/{layer_id}/demote", headers=h)
    assert d.status_code == 200, d.text
    assert _visible_units(db, f.calc_id) == [], f"demote left {len(_visible_units(db, f.calc_id))} orphan unit(s) visible after {edit}"

    p = _post(client, h, f, f"auto-block-layers/{layer_id}/promote", {"as_level": "compartments"})
    assert p.status_code == 200, f"re-promote after {edit} refused: {p.text[:200]}"
    assert len(_visible_units(db, f.calc_id)) == edited
    assert_tiles(db, f.calc_id, f"re-promoted after {edit}")


def test_paste_into_a_promoted_layer_joins_the_layer(client, db, make_forest, owner_headers):
    """A unit pasted (or drawn from points) at the top level of a forest whose structure IS a promoted layer
    takes ground from that layer's units, so it belongs to the layer: demote must hide it too."""
    f = make_forest("F0")
    h = owner_headers(f)
    layer_id = _promote_two_halves(client, db, f, h)
    first = _visible_units(db, f.calc_id)[0]
    x0, y0, x1, y1 = to_shape(first.geometry).bounds
    w = x1 - x0
    r = _post(client, h, f, "geometry/paste-units", {
        "layer_type": "compartments", "features": [_box_geojson(x0 + w * 0.5, y0, x1, y1)], "preview": False})
    assert r.status_code == 200, r.text
    assert_tiles(db, f.calc_id, "paste into a promoted layer")
    edited = len(_visible_units(db, f.calc_id))
    d = client.post(f"/api/calculations/{f.calc_id}/auto-block-layers/{layer_id}/demote", headers=h)
    assert d.status_code == 200, d.text
    assert _visible_units(db, f.calc_id) == [], "the pasted unit stayed visible after demote"
    p = _post(client, h, f, f"auto-block-layers/{layer_id}/promote", {"as_level": "compartments"})
    assert p.status_code == 200, p.text[:200]
    assert len(_visible_units(db, f.calc_id)) == edited
