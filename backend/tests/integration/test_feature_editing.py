"""Phase E-1 integration tests — feature geometry editing API.

Covers the single-authority geometry editing router (`app/api/editing.py`) and
the shared validated pipeline (`app/services/geometry_edit_service.py`):

  - E1.1 pipeline: sanitize → clip (R1) → overlap/shared-edge (R6)
  - E1.2 routes: edit-geometry, cut-polygon, divide-equal-areas,
    divide-preview, copy-boundary-to-block, delete-guard, DELETE boundary
  - E1.3 locks: structure_locked (423) + map_lifecycle_status (409),
    ``?force=true`` bypasses lifecycle but never structure lock
  - review-fix #8: legacy PATCH endpoints reject the ``geometry`` key with a 400
  - E-3 snapshot / restore: undo restores exactly one row (R5)
"""
import re
import json
import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import MultiPolygon, Polygon, box, shape
from sqlalchemy import text

from app.api.editing import _flatten_and_clean_pieces
from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock
from app.models.workspace_layer import WorkspaceLayer
from app.services.geometry_edit_service import area_sqm

import pytest

pytestmark = pytest.mark.usefixtures("forget_forests")  # fixed coordinates + committed rows: see conftest



# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _register(client):
    """Register + login a fresh user; returns (headers, user_id)."""
    email = f"edit-repro-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Edit Repro",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _calc(db, user_id, boundary=box(83.0, 27.0, 84.0, 28.0)):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name="Edit Repro Forest",
        boundary_geom=shp_wkt.dumps(boundary),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _block(db, calc, geom=None, name="Block 1", index=0, **kwargs):
    if geom is None:
        geom = box(83.2, 27.2, 83.8, 27.7)
    block = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        geometry=shp_wkt.dumps(geom),
        area_hectares=1.0,
        index=index,
        **kwargs,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def _block_geojson(db, block_id):
    row = db.execute(text(
        "SELECT ST_AsGeoJSON(geometry) AS g FROM forest_blocks WHERE id = :id"
    ), {"id": str(block_id)}).first()
    return row.g if row else None


def _gj(geom):
    return shape(geom).__geo_interface__


def _edit_url(calc_id, api="/api/v1"):
    return f"{api}/calculations/{calc_id}/geometry"


# ---------------------------------------------------------------------------
# E1.1 / E1.2 — edit-geometry
# ---------------------------------------------------------------------------

def test_edit_geometry_persists_validated_geometry(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _block(db, calc)
    db.expire_all()

    move = box(83.2, 27.2, 83.9, 27.7)
    resp = client.post(
        f"{_edit_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "geometry": _gj(move)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["feature"]["id"] == str(block.id)
    geojson = _block_geojson(db, block.id)
    assert geojson is not None


def test_edit_geometry_rejects_overlapping_neighbour(client, db):
    """R6: dragging one block onto another is rejected TOPOLOGY_REJECTED."""
    headers, uid = _register(client)
    calc = _calc(db, uid)
    a = _block(db, calc, geom=box(83.2, 27.2, 83.5, 27.5), name="A", index=0)
    _block(db, calc, geom=box(83.5, 27.2, 83.8, 27.5), name="B", index=1)
    db.expire_all()

    overlapping = box(83.2, 27.2, 83.6, 27.5)
    resp = client.post(
        f"{_edit_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(a.id), "geometry": _gj(overlapping)},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "TOPOLOGY_REJECTED"


def test_edit_geometry_clip_to_boundary(client, db):
    """R1: block edit spilling past the boundary gets clipped (warn) or rejected."""
    headers, uid = _register(client)
    calc = _calc(db, uid)
    _block(db, calc)
    db.expire_all()
    db.refresh(calc)

    spilling = box(83.95, 27.95, 84.3, 28.2)
    block = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).first()
    resp = client.post(
        f"{_edit_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "geometry": _gj(spilling)},
    )
    assert resp.status_code in (200, 409), resp.text
    if resp.status_code == 200:
        # partially-inside edit must be clipped → warning surfaced
        assert "CLIPPED_TO_BOUNDARY" in resp.json()["warnings"]


def test_edit_geometry_structural_fully_outside_rejected(client, db):
    """UE-3.1: a structural layer (block) edit that lies ENTIRELY outside the
    forest boundary is rejected — it can never exist outside the boundary."""
    headers, uid = _register(client)
    calc = _calc(db, uid)  # boundary box(83,27,84,28)
    _block(db, calc)
    db.expire_all()

    outside = box(90.0, 30.0, 91.0, 31.0)
    block = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).first()
    resp = client.post(
        f"{_edit_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "geometry": _gj(outside)},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "TOPOLOGY_REJECTED"


def test_edit_geometry_imported_not_clipped(client, db):
    """UE-3.1 rule: imported-layer edits are NEVER clipped to the forest boundary —
    the geometry is persisted exactly as sent even when it extends outside."""
    headers, uid = _register(client)
    calc = _calc(db, uid)  # boundary box(83,27,84,28)
    layer = _imported_layer_multi(
        db, calc, uid,
        [box(83.2, 27.2, 83.5, 27.5), box(83.5, 27.2, 83.8, 27.5)],
    )
    db.expire_all()

    # edit feature imp-1 to a geometry that pokes OUTSIDE the boundary
    outside = box(83.2, 27.2, 84.5, 27.5)
    resp = client.post(
        f"{_edit_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "imported", "layer_id": layer.id,
              "feature_id": "imp-1", "geometry": _gj(outside)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["warnings"] == [], body["warnings"]
    # no clipping happened — the stored geometry is unchanged
    fresh = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer.id).first()
    feats = fresh.layer_data["features"]
    imp1 = [f for f in feats if f["properties"]["featureId"] == "imp-1"][0]
    stored = shape(imp1["geometry"])
    assert abs(stored.bounds[2] - 84.5) < 1e-9  # right edge 84.5 kept, NOT clipped to 84.0


def test_boundary_edit_geometry_guarded_and_persisted(client, db):
    """VR-3 (was UE-4.2): edit-geometry now ENFORCES Rule A for the boundary
    instead of refusing it outright.

    The old contract was a blanket 400 "boundary is edited via the boundary
    toolbar" — which meant the rule was checked nowhere, since `PUT /boundary`
    had no structure check either.  This very test proved it: step 1 asserted
    the route was "guarded", then step 2 performed the same edit through the
    unguarded route.  With no structural feature present the edit is legal, so
    edit-geometry accepts it and writes the FULL boundary (geom + result_data
    + geodesic area).  The refusal case is covered in test_vertex_guard_api."""
    headers, uid = _register(client)
    # a small in-Nepal boundary — the four forest-boundary rules now run on the
    # PUT /boundary establish path (within Nepal · ≤ 1000 ha · …).
    calc = _calc(db, uid, box(83.0, 27.0, 83.02, 27.02))
    calc.structure_locked = False
    db.commit()
    db.expire_all()

    # 1) no blocks exist → Rule A allows the edit, and edit-geometry persists it
    moved = box(83.0, 27.0, 83.025, 27.025)  # ~690 ha, under the 1000 ha cap
    resp = client.post(
        f"{_edit_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "boundary", "feature_id": "boundary", "geometry": _gj(moved)},
    )
    assert resp.status_code == 200, resp.text
    db.expire_all()
    db.refresh(calc)
    assert (calc.result_data or {}).get("area_hectares"), "area must be recomputed here too"

    # 2) the boundary toolbar route (`PUT /boundary`) persists the edit
    put = client.put(
        f"/api/forests/calculations/{calc.id}/boundary",
        headers=headers,
        json={"geometry": _gj(moved), "area_hectares": 2500},
    )
    assert put.status_code == 200, put.text
    db.expire_all()
    db.refresh(calc)
    from geoalchemy2.shape import to_shape
    assert to_shape(calc.boundary_geom).equals(moved), "boundary_geom not updated"
    assert shape(calc.result_data["geometry"]).equals(moved), "result_data geometry not synced"
    assert calc.result_data["area_hectares"] == 2500

    # 3) a re-fetch of the boundary feature returns the new geometry
    feat = client.get(
        f"{_edit_url(calc.id)}/feature",
        headers=headers,
        params={"layer_type": "boundary", "feature_id": "boundary"},
    )
    assert feat.status_code == 200, feat.text
    assert shape(feat.json()["snapshot"]["geometry"]).equals(moved)


def test_merge_structural_rejects_fully_outside(client, db):
    """UE-3.1: a structural merge that clips to nothing (both sources outside the
    boundary) is rejected, not persisted un-clipped."""
    from shapely.geometry import box as _box
    headers, uid = _register(client)
    calc = _calc(db, uid)  # boundary box(83,27,84,28)
    a = _block(db, calc, geom=_box(83.2, 27.2, 83.5, 27.5), name="East", index=0)
    b = _block(db, calc, geom=_box(83.5, 27.2, 83.8, 27.5), name="West", index=1)
    db.expire_all()
    # overwrite both geometries so the union sits outside the boundary
    db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).update(
        {"geometry": shp_wkt.dumps(_box(90.0, 30.0, 91.0, 31.0))},
        synchronize_session=False,
    )
    db.commit()
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "blocks", "feature_ids": [str(a.id), str(b.id)]},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "TOPOLOGY_REJECTED"


# ---------------------------------------------------------------------------
# divide / preview
# ---------------------------------------------------------------------------

def test_boundary_divide_stores_blocks(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(1.0, 1.0, 5.0, 5.0))
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "boundary", "feature_id": "boundary", "method": "strips", "count": 2, "direction": "vertical"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["boundary_pieces_stored_as"] == "blocks"
    assert len(resp.json()["pieces"]) == 2
    count = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count()
    assert count == 2


def test_boundary_divide_rejects_more_than_20_pieces(client, db):
    """A huge `count` used to run the full per-piece shapely division
    unbounded (user report, 2026-09-13: "if user enters a large number it
    may get hanged") — now rejected up front with a 400, before any division
    work runs."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(1.0, 1.0, 5.0, 5.0))
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "boundary", "feature_id": "boundary", "method": "strips", "count": 500, "direction": "vertical"},
    )
    assert resp.status_code == 400, resp.text
    count = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count()
    assert count == 0  # nothing persisted


def test_boundary_divide_rejects_grid_whose_rows_times_cols_exceeds_20(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(1.0, 1.0, 5.0, 5.0))
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "boundary", "feature_id": "boundary", "method": "grid", "rows": 10, "cols": 10},
    )
    assert resp.status_code == 400, resp.text


def test_boundary_divide_allows_exactly_20_pieces(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(1.0, 1.0, 5.0, 5.0))
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "boundary", "feature_id": "boundary", "method": "strips", "count": 20, "direction": "vertical"},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["pieces"]) == 20


def test_divide_compartments_self_divide_splits_selected_compartment(client, db):
    """Selecting an EXISTING compartment (not a block) and dividing the
    `compartments` layer must split that compartment in place into N smaller
    compartments — same parent block, same division_level — instead of the
    old behaviour of requiring a block selection."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    parent_block = _block(db, calc, geom=box(83.2, 27.2, 83.8, 27.7), name="Block 1", index=0)
    compartment = _block(
        db, calc,
        geom=box(83.2, 27.2, 83.8, 27.7),
        name="Block 1-C1",
        index=1,
        is_compartment=True,
        parent_block_id=parent_block.id,
        division_level=1,
        compartment_code="Block 1-C1",
    )
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={
            "layer_type": "compartments", "feature_id": str(compartment.id),
            "method": "strips", "count": 2, "direction": "vertical",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["pieces"]) == 2
    # "split_history_id" only exists on the parent-child (divide_compartment)
    # response shape — this response must be the GENERIC replace shape.
    assert "split_history_id" not in body
    # The frontend success toast reads these two fields unconditionally
    # (EqualAreaDividePanel.handleAccept) regardless of which backend path
    # served the divide — missing them crashed with "Cannot read properties
    # of undefined (reading 'toLocaleString')".
    assert body["n_children"] == 2
    assert body["trees_reassigned"] == 0

    db.expire_all()
    rows = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id, ForestBlock.is_compartment == True,  # noqa: E712
    ).all()
    assert len(rows) == 2
    for row in rows:
        assert row.parent_block_id == parent_block.id
        assert row.division_level == 1
    # The original compartment row is gone, replaced by its two pieces.
    assert str(compartment.id) not in {str(r.id) for r in rows}
    # The parent block itself is untouched.
    still_there = db.query(ForestBlock).filter(ForestBlock.id == parent_block.id).first()
    assert still_there is not None


def test_divide_compartments_from_block_still_carves_fresh_set(client, db):
    """Selecting the PARENT BLOCK (not an existing compartment) still goes
    through the original parent-child divide_compartment path — the new
    self-divide branch must not shadow this, the far more common case."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    parent_block = _block(db, calc, geom=box(83.2, 27.2, 83.8, 27.7), name="Block 1", index=0)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={
            "layer_type": "compartments", "feature_id": str(parent_block.id),
            "method": "strips", "count": 2, "direction": "vertical",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["n_children"] == 2
    assert body["split_history_id"]

    db.expire_all()
    children = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id, ForestBlock.is_compartment == True,  # noqa: E712
    ).all()
    assert len(children) == 2
    for c in children:
        assert c.parent_block_id == parent_block.id
        assert c.division_level == 1
    # The block itself survives (it's the parent, not replaced).
    still_there = db.query(ForestBlock).filter(ForestBlock.id == parent_block.id).first()
    assert still_there is not None


def test_divide_compartments_from_block_carries_working_circle_and_style(client, db):
    """Owner request, 2026-09-15: dividing a block into a fresh set of
    compartments must carry its forest/management character onto every
    child, exactly like cutting does -- previously this path (the
    carve-fresh-children branch, distinct code from cut/self-divide) reset
    every child to management_orientation=None / style=None / natural_name=
    None / a fresh palette color regardless of the parent.

    working_circle='protection' is deliberately NOT exercised here: a
    protection unit's own geometry is excluded from any divide as "already
    spoken for" (PROTECTION_WORKING_CIRCLE_PLAN.md P2 -- exclude_geom in
    _exclusion_for_parent), so a protection block can never reach this
    carve-a-fresh-set code path to begin with. That mechanism is exercised
    instead by the cut-polygon inheritance test above, which shares the
    same child_inherit_kwargs helper.
    """
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    parent_block = _block(
        db, calc, geom=box(83.2, 27.2, 83.8, 27.7), name="Block 1", index=0,
        management_orientation="Conservation",
        style={"stroke": "#ff0000"},
        natural_name="Some Ridge",
        color="#abcdef",
    )
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={
            "layer_type": "compartments", "feature_id": str(parent_block.id),
            "method": "strips", "count": 2, "direction": "vertical",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["n_children"] == 2

    db.expire_all()
    children = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id, ForestBlock.is_compartment == True,  # noqa: E712
    ).all()
    assert len(children) == 2
    for c in children:
        assert c.management_orientation == "Conservation"
        assert c.style == {"stroke": "#ff0000"}
        assert c.natural_name == "Some Ridge"
        assert c.color == "#abcdef"


def test_divide_layer_gate(client, db):
    """sub_areas is NOT in DIVIDE_ALLOWED_LAYERS → 400 (R2)."""
    headers, uid = _register(client)
    calc = _calc(db, uid)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "sub_areas", "feature_id": "x", "method": "strips", "count": 2},
    )
    assert resp.status_code == 400, resp.text
    assert "not allowed" in resp.json()["detail"].lower()


def test_divide_preview_no_persist(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2.0, 2.0, 4.0, 4.0))
    block = _block(db, calc)
    db.expire_all()
    before = _block_geojson(db, block.id)

    resp = client.post(
        f"{_edit_url(calc.id)}/divide-preview",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "method": "strips", "count": 2, "direction": "vertical"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_pieces"] == 2
    assert _block_geojson(db, block.id) == before


def test_divide_preview_compartments_async_path(client, db):
    """Compartments preview goes through the async service; must be awaited (regression for 'coroutine object is not subscriptable')."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2.0, 2.0, 4.0, 4.0))
    block = _block(db, calc)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/divide-preview",
        headers=headers,
        json={"layer_type": "compartments", "feature_id": str(block.id), "method": "strips", "count": 2, "direction": "vertical"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["total_pieces"] == 2
    assert body["pieces"][0]["name"].endswith("-C1")
    assert db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count() == 1


def test_divide_preview_self_divide_on_existing_compartment(client, db):
    """The live preview the divide panel calls first must route a selected
    EXISTING compartment the same way commit does (self-divide) — not 400
    with BLOCK_REQUIRED, which is what happened here before divide-preview
    got the same fix divide-equal-areas did."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    parent_block = _block(db, calc, geom=box(83.2, 27.2, 83.8, 27.7), name="Block 1", index=0)
    compartment = _block(
        db, calc,
        geom=box(83.2, 27.2, 83.8, 27.7),
        name="Block 1-C1",
        index=1,
        is_compartment=True,
        parent_block_id=parent_block.id,
        division_level=1,
        compartment_code="Block 1-C1",
    )
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/divide-preview",
        headers=headers,
        json={
            "layer_type": "compartments", "feature_id": str(compartment.id),
            "method": "strips", "count": 2, "direction": "vertical",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["total_pieces"] == 2
    # The ghost-overlay renderer (EqualAreaDividePanel) reads p.geometry /
    # p.name / p.area_hectares per piece — a bare GeoJSON geometry (no
    # wrapper) silently drew nothing on the map, which is what happened
    # here before this shape was fixed to match preview_divide_compartment's.
    for i, piece in enumerate(body["pieces"], start=1):
        assert piece["geometry"]["type"] == "Polygon"
        assert piece["name"] == f"Block 1-C1-{i}"
        assert piece["area_hectares"] > 0
    # Preview must not persist anything.
    assert db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count() == 2


def test_divide_preview_self_divide_by_area_threads_target(client, db):
    """Regression: the live divide panel preview crashed with a 500
    general.unexpected_error on a self-divide in by-area ("area per piece")
    mode. The preview endpoint routed self-divides through `_divide_geometry`
    WITHOUT `target_area_sqm` — so with count:null it fell into
    equal_area_strips(n=None) → `None <= 0` → TypeError → unhandled → 500.
    The commit endpoint already threaded it; the preview must too (the panel
    calls preview first, live, on every input change)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    parent_block = _block(db, calc, geom=box(83.2, 27.2, 83.8, 27.7), name="Block 1", index=0)
    compartment = _block(
        db, calc,
        geom=box(83.2, 27.2, 83.8, 27.7),
        name="Block 1-C1",
        index=1,
        is_compartment=True,
        parent_block_id=parent_block.id,
        division_level=1,
        compartment_code="Block 1-C1",
    )
    db.expire_all()

    # Target ≈ half the compartment area → exactly 2 pieces.
    comp_area_m2 = area_sqm(box(83.2, 27.2, 83.8, 27.7))
    resp = client.post(
        f"{_edit_url(calc.id)}/divide-preview",
        headers=headers,
        json={
            "layer_type": "compartments", "feature_id": str(compartment.id),
            "method": "strips", "count": None, "direction": "vertical",
            "target_area_sqm": comp_area_m2 / 2,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["total_pieces"] == 2
    for i, piece in enumerate(body["pieces"], start=1):
        assert piece["geometry"]["type"] == "Polygon"
        assert piece["name"] == f"Block 1-C1-{i}"
        assert piece["area_hectares"] > 0
    # Preview must not persist anything.
    assert db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count() == 2


def test_divide_preview_missing_count_and_target_400s(client, db):
    """A divide call carrying neither a piece count nor an area-per-piece
    target must be a clean 400 (editing.divide_count_required), never a 500.
    This used to crash with `None <= 0` (TypeError) in equal_area_strips."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    parent_block = _block(db, calc, geom=box(83.2, 27.2, 83.8, 27.7), name="Block 1", index=0)
    compartment = _block(
        db, calc,
        geom=box(83.2, 27.2, 83.8, 27.7),
        name="Block 1-C1",
        index=1,
        is_compartment=True,
        parent_block_id=parent_block.id,
        division_level=1,
        compartment_code="Block 1-C1",
    )
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/divide-preview",
        headers=headers,
        json={
            "layer_type": "compartments", "feature_id": str(compartment.id),
            "method": "strips", "direction": "vertical",
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "editing.divide_count_required"


def test_flatten_and_clean_pieces_drops_degenerate_slivers_and_explodes_multiparts():
    """Reproduces the exact corruption reported live: a compartment stored
    as ONE row whose geometry was a MultiPolygon with 2 real parts + 16
    near-zero-area needle fragments (0.06 ha reported area, 3.15 km
    reported perimeter). `_replace_feature_with_pieces` used to store
    whatever it was handed verbatim, one row per list item, with no
    explode and no filter — this is the fix."""
    real_a = Polygon([(0, 0), (0, 0.001), (0.001, 0.001), (0.001, 0)])  # a few hundred m^2 at these coords
    real_b = Polygon([(1, 1), (1, 1.001), (1.001, 1.001), (1.001, 1)])
    # A needle: near-zero width, real (non-trivial) length -- exactly the
    # "thousandths of a m^2 area, tens-to-hundreds of metres of perimeter"
    # shape the live bug produced.
    needle = Polygon([(2, 2), (2, 2.0001), (2.00000001, 2.0001), (2.00000001, 2)])
    bundled = MultiPolygon([real_a, real_b, needle])

    cleaned = _flatten_and_clean_pieces([bundled])

    assert len(cleaned) == 2  # the needle is dropped, the 2 real parts survive AND explode into separate items
    assert all(isinstance(p, Polygon) for p in cleaned)


def test_cut_polygon_preserves_auto_block_classification(client, db):
    """Cutting a compartment that carries an Auto-Block source classification
    (dominant_slope_band/aspect/canopy_class) must leave every resulting
    piece with the SAME value — a cut changes geometry only, it does not
    reclassify (unlike Auto-Block's own merge, which recombines potentially
    unrelated pieces)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    compartment = _block(
        db, calc, geom=box(2.5, 2.5, 5.5, 5.5),
        is_compartment=True, division_level=1,
        dominant_slope_band=3, dominant_aspect=None, dominant_canopy_class=None,
    )
    db.expire_all()

    cut = {"type": "LineString", "coordinates": [[3.0, 2.0], [3.0, 6.0]]}
    resp = client.post(
        f"{_edit_url(calc.id)}/cut-polygon",
        headers=headers,
        json={"layer_type": "compartments", "feature_id": str(compartment.id), "cut_line": cut},
    )
    assert resp.status_code == 200, resp.text
    piece_ids = resp.json()["piece_ids"]
    assert len(piece_ids) >= 2

    db.expire_all()
    pieces = db.query(ForestBlock).filter(ForestBlock.id.in_(piece_ids)).all()
    assert len(pieces) == len(piece_ids)
    for p in pieces:
        assert p.dominant_slope_band == 3
        assert p.dominant_aspect is None
        assert p.dominant_canopy_class is None


def test_cut_polygon_preserves_working_circle_orientation_and_style(client, db):
    """Owner request, 2026-09-15: a cut/divide changes geometry only -- the
    forest/management character of a block (working circle, management
    orientation, per-feature style override) must carry over to every piece
    identically, not just the slope/aspect/canopy classification. Previously
    every piece silently reset to working_circle='production' /
    management_orientation=None / style=None regardless of the source."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(
        db, calc, geom=box(2.5, 2.5, 5.5, 5.5),
        working_circle="protection",
        management_orientation="Protection",
        style={"fill": "#00ff00", "fillOpacity": 0.5},
    )
    db.expire_all()

    cut = {"type": "LineString", "coordinates": [[3.0, 2.0], [3.0, 6.0]]}
    resp = client.post(
        f"{_edit_url(calc.id)}/cut-polygon",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "cut_line": cut},
    )
    assert resp.status_code == 200, resp.text
    piece_ids = resp.json()["piece_ids"]
    assert len(piece_ids) >= 2

    db.expire_all()
    pieces = db.query(ForestBlock).filter(ForestBlock.id.in_(piece_ids)).all()
    assert len(pieces) == len(piece_ids)
    for p in pieces:
        assert p.working_circle == "protection"
        assert p.management_orientation == "Protection"
        assert p.style == {"fill": "#00ff00", "fillOpacity": 0.5}


def test_cut_polygon_persists_pieces(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc, geom=box(2.5, 2.5, 5.5, 5.5))
    db.expire_all()

    cut = {"type": "LineString", "coordinates": [[3.0, 2.0], [3.0, 6.0]]}
    resp = client.post(
        f"{_edit_url(calc.id)}/cut-polygon",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "cut_line": cut},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["pieces"]) >= 2
    count = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count()
    # 2 pieces from cut + 1 remainder block (invariant fills uncovered boundary)
    assert count >= 3
    # UE-3.2: cut returns the created piece row ids so undo can delete them.
    # A truthy-only check here (the old assertion) doesn't fail on the
    # literal string "None" — the actual bug: piece_row.id was read before
    # the flush that populates it (its default is Python-side, applied on
    # flush, not at construction). Resolve every id against the DB instead.
    piece_ids = resp.json()["piece_ids"]
    assert piece_ids and len(piece_ids) == count - 1  # remainder not in piece_ids
    db.expire_all()
    found = db.query(ForestBlock).filter(ForestBlock.id.in_(piece_ids)).count()
    assert found == len(piece_ids)


def test_cut_polygon_zigzag_line_inside_polygon(client, db):
    """A multi-vertex / zig-zag cut line whose ends stop inside the polygon must
    still split it from edge to edge (end-extension of the cut line)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc, geom=box(2.5, 2.5, 5.5, 5.5))
    db.expire_all()

    cut = {
        "type": "LineString",
        # zig-zag path crossing the block interior, both ends INSIDE the block
        "coordinates": [[3.2, 3.1], [3.6, 3.6], [3.3, 4.1], [3.7, 4.6], [3.4, 5.2]],
    }
    resp = client.post(
        f"{_edit_url(calc.id)}/cut-polygon",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "cut_line": cut},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["pieces"]) >= 2
    count = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count()
    assert count >= 2


def test_cut_polygon_boundary_stores_pieces_as_blocks(client, db):
    """Cutting the forest boundary must NOT replace the boundary in place — the
    pieces are persisted as NEW blocks (R2 boundary semantics, UE-1)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    db.expire_all()

    cut = {
        "type": "LineString",
        "coordinates": [[83.5, 27.2], [83.5, 27.8]],
    }
    resp = client.post(
        f"{_edit_url(calc.id)}/cut-polygon",
        headers=headers,
        json={"layer_type": "boundary", "feature_id": "boundary", "cut_line": cut},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["pieces"]) >= 2
    # pieces become blocks, not a boundary rewrite
    count = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count()
    assert count >= 2
    # the persisted blocks keep the total area (persister precomputes area_hectares)
    covered = 0.0
    for row in db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id):
        covered += row.area_sqm or 0.0
    assert covered > 75.0e6  # 83..84 x 27..28 = ~100 km2 * 0.9 for the two-piece division line
    # UE-3.2: boundary-split returns the created block ids for undo delete.
    # Resolve against the DB rather than a truthy-only check — see the same
    # note in test_cut_polygon_persists_pieces for why that didn't catch the
    # underlying "None"-string bug.
    block_ids = resp.json()["boundary_piece_block_ids"]
    assert block_ids and len(block_ids) == count
    db.expire_all()
    found = db.query(ForestBlock).filter(ForestBlock.id.in_(block_ids)).count()
    assert found == len(block_ids)


def _imported_layer(db, calc, uid, geom, name="Imported Layer", purpose="custom"):
    """Create a WorkspaceLayer with a single Feature (featureId 'imp-1')."""
    from shapely.geometry import mapping as _mapping
    from app.utils.geometry_utils import compute_geometry_properties

    target = {"type": "Feature", "geometry": _mapping(geom), "properties": {"featureId": "imp-1", "name": name}}
    target["properties"].update(compute_geometry_properties(geom))
    layer = WorkspaceLayer(
        calculation_id=calc.id,
        name=name,
        purpose=purpose,
        source_format="geojson",
        feature_count=1,
        geometry_types=["Polygon"],
        layer_data={"type": "FeatureCollection", "features": [target]},
        is_draft=False,
        created_by=uid,
    )
    db.add(layer)
    db.commit()
    db.refresh(layer)
    return layer


def test_cut_polygon_imported_stores_pieces(client, db):
    """UE-1.2 — cutting an imported feature replaces it with N pieces inside the
    layer's layer_data (fresh featureIds), never touching built-in tables."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    layer = _imported_layer(db, calc, uid, box(83.2, 27.2, 83.8, 27.7))
    db.expire_all()

    cut = {"type": "LineString", "coordinates": [[83.5, 27.25], [83.5, 27.65]]}
    resp = client.post(
        f"{_edit_url(calc.id)}/cut-polygon",
        headers=headers,
        json={"layer_type": "imported", "layer_id": layer.id, "feature_id": "imp-1", "cut_line": cut},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["pieces"]) >= 2

    db.expire_all()
    fresh = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer.id).first()
    feats = fresh.layer_data["features"]
    assert len(feats) == 2
    assert all(str(f["properties"]["featureId"]).startswith("imp-1-piece-") for f in feats)
    # UE-3.2: imported split returns the created piece featureIds (undo delete).
    piece_feature_ids = body.get("piece_feature_ids") or []
    assert piece_feature_ids and len(piece_feature_ids) == 2
    assert all(str(pid).startswith("imp-1-piece-") for pid in piece_feature_ids)
    # areas conserved (2 pieces of the 0.6 x 0.5 deg box ≈ 329,000 ha)
    total = sum(float(f["properties"].get("area_hectares", 0)) for f in feats)
    assert 320_000 < total < 335_000


def test_edit_geometry_imported_replaces_feature(client, db):
    """UE-1.2 — vertex/move commit replaces the imported feature geometry and
    recomputes geo_* from the authoritative stored geometry."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    layer = _imported_layer(db, calc, uid, box(83.2, 27.2, 83.8, 27.7))
    db.expire_all()

    moved = {"type": "Polygon", "coordinates": [[[83.25, 27.25], [83.85, 27.25], [83.85, 27.6], [83.25, 27.6], [83.25, 27.25]]]}
    resp = client.post(
        f"{_edit_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "imported", "layer_id": layer.id, "feature_id": "imp-1", "geometry": moved},
    )
    assert resp.status_code == 200, resp.text
    db.expire_all()
    fresh = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer.id).first()
    feat = fresh.layer_data["features"][0]
    assert feat["geometry"]["coordinates"][0][0][0] == 83.25
    assert float(feat["properties"]["geo_area_ha"]) > 3000


def test_imported_edit_rejected_when_structure_locked(client, db):
    """UE-1.2 — imported edits honour the structure lock (423), unlike the old
    unguarded workspace PATCH."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    layer = _imported_layer(db, calc, uid, box(83.2, 27.2, 83.8, 27.7))
    calc.structure_locked = True
    db.commit()
    db.expire_all()

    cut = {"type": "LineString", "coordinates": [[83.5, 27.25], [83.5, 27.65]]}
    resp = client.post(
        f"{_edit_url(calc.id)}/cut-polygon",
        headers=headers,
        json={"layer_type": "imported", "layer_id": layer.id, "feature_id": "imp-1", "cut_line": cut},
    )
    assert resp.status_code == 423
    assert resp.json()["detail"]["code"] == "structure_locked"


# ---------------------------------------------------------------------------
# UE-2.2 — merge-features
# ---------------------------------------------------------------------------

def _imported_layer_multi(db, calc, uid, geoms, name="Imported Layer", purpose="custom"):
    """Create a WorkspaceLayer with N Features (featureIds imp-1..imp-N)."""
    from shapely.geometry import mapping as _mapping
    from app.utils.geometry_utils import compute_geometry_properties

    features = []
    for i, geom in enumerate(geoms, start=1):
        target = {"type": "Feature", "geometry": _mapping(geom),
                  "properties": {"featureId": f"imp-{i}", "name": f"{name} {i}"}}
        target["properties"].update(compute_geometry_properties(geom))
        features.append(target)
    layer = WorkspaceLayer(
        calculation_id=calc.id,
        name=name,
        purpose=purpose,
        source_format="geojson",
        feature_count=len(features),
        geometry_types=["Polygon"],
        layer_data={"type": "FeatureCollection", "features": features},
        is_draft=False,
        created_by=uid,
    )
    db.add(layer)
    db.commit()
    db.refresh(layer)
    return layer


def test_merge_features_blocks_unions(client, db):
    """UE-2.2 — two adjacent blocks merge into ONE new block; sources deleted.

    The attribute basis (name, colour, classification, ...) is the LARGER of
    the two source features (user report, 2026-09-12), not whichever was
    selected first — "West" is deliberately the smaller box and is selected
    FIRST here, so a pass proves the size rule, not selection order."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    # East: 0.4 x 0.3 deg (larger). West: 0.2 x 0.3 deg (smaller), selected first.
    a = _block(db, calc, geom=box(83.2, 27.2, 83.6, 27.5), name="East", index=0)
    b = _block(db, calc, geom=box(83.6, 27.2, 83.8, 27.5), name="West", index=1)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "blocks", "feature_ids": [str(b.id), str(a.id)]},
    )
    assert resp.status_code == 200, resp.text
    merged = resp.json()["feature"]
    assert merged["name"] == "East_merged"

    db.expire_all()
    remaining = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    # 1 merged block + 1 remainder block (invariant fills uncovered boundary)
    assert len(remaining) == 2
    merged_block = next(r for r in remaining if str(r.id) == str(merged["id"]))
    remainder = next(r for r in remaining if str(r.id) != str(merged["id"]))
    assert re.fullmatch(r"B\d+", remainder.name), remainder.name  # system-named remainder: B<n>
    assert str(merged_block.id) == str(merged["id"])
    # 0.4x0.3 + 0.2x0.3 adjacent deg boxes at this latitude ≈ 197,500 ha total
    assert abs(merged_block.area_hectares - 197500) < 3000


def test_merge_features_heals_a_make_valid_geometry_collection(client, db):
    """2026-09-12 live bug: merging two genuinely-adjoining features whose
    union needed shapely's make_valid() repair 500'd instead of succeeding.

    make_valid() on a self-touching/degenerate shape (a real polygon with a
    zero-width spike -- exactly what independent per-piece smoothing can
    leave along a shared boundary) can return
    GeometryCollection(Polygon, LineString), not a bare Polygon or
    MultiPolygon. `_union_geometries` used to hand that straight through:
    the "reject disjoint merge" check (`geom_type == "MultiPolygon"`) never
    fired for a GeometryCollection, and the single-part-geometry ORM guard
    (correctly) refused to persist a GeometryCollection it didn't know how
    to unwrap -- surfacing as a generic 500, not a successful merge."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    # East (with the spike) is deliberately larger than West, so the merged
    # name assertion below is unambiguous under the "largest wins" attribute
    # rule (2026-09-12) rather than relying on a near-tied area.
    lollipop = Polygon([
        (83.2, 27.2), (83.6, 27.2), (83.6, 27.5), (83.2, 27.5), (83.2, 27.2),
        (83.2, 27.2), (83.1, 27.2), (83.2, 27.2),  # zero-width dangling spike
    ])
    assert not lollipop.is_valid
    a = _block(db, calc, geom=lollipop, name="East", index=0)
    b = _block(db, calc, geom=box(83.6, 27.2, 83.8, 27.5), name="West", index=1)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "blocks", "feature_ids": [str(a.id), str(b.id)]},
    )
    assert resp.status_code == 200, resp.text
    merged = resp.json()["feature"]
    assert merged["name"] == "East_merged"

    db.expire_all()
    from geoalchemy2.shape import to_shape
    row = db.query(ForestBlock).filter(ForestBlock.id == merged["id"]).first()
    assert row is not None
    stored = to_shape(row.geometry)
    assert stored.geom_type == "Polygon"


def test_merge_features_attribute_basis_is_the_larger_feature_not_selection_order(client, db):
    """User report, 2026-09-12: "the largest size attribute will remain, the
    smaller size attribute will vanish" -- the merged row's non-geometry
    attributes (name basis, natural name, classification, colour, working
    circle) come from whichever SOURCE feature is larger, never from
    whichever was clicked/selected first. The geometry itself is still a
    plain union either way (unaffected by which one is "base")."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    small = _block(
        db, calc, geom=box(83.6, 27.2, 83.8, 27.5), name="Small",
        block_name="Small", natural_name="Small River", color="#111111",
        dominant_slope_band=1, index=0,
    )
    big = _block(
        db, calc, geom=box(83.2, 27.2, 83.6, 27.5), name="Big",
        block_name="Big", natural_name="Big River", color="#222222",
        dominant_slope_band=4, index=1,
    )
    db.expire_all()

    # "Small" is selected FIRST -- under the old "first selected" rule it
    # would have won; under the size rule "Big" must win regardless.
    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "blocks", "feature_ids": [str(small.id), str(big.id)]},
    )
    assert resp.status_code == 200, resp.text
    merged = resp.json()["feature"]
    assert merged["name"] == "Big_merged"

    db.expire_all()
    row = db.query(ForestBlock).filter(ForestBlock.id == merged["id"]).first()
    assert row.block_name == "Big_merged"
    assert row.natural_name == "Big River"
    assert row.color == "#222222"
    assert row.dominant_slope_band == 4


def test_merge_features_carries_management_orientation_from_the_larger_feature(client, db):
    """Owner request, 2026-09-15: management_orientation was the one
    attribute even the merge path (otherwise the most complete of the four
    child-building code paths) still dropped -- every merged row came out
    with management_orientation=None regardless of the sources. Same
    largest-feature-wins basis as working_circle/style/color above."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    small = _block(
        db, calc, geom=box(83.6, 27.2, 83.8, 27.5), name="Small", index=0,
        management_orientation="Production",
    )
    big = _block(
        db, calc, geom=box(83.2, 27.2, 83.6, 27.5), name="Big", index=1,
        management_orientation="Protection",
    )
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "blocks", "feature_ids": [str(small.id), str(big.id)]},
    )
    assert resp.status_code == 200, resp.text
    merged = resp.json()["feature"]

    db.expire_all()
    row = db.query(ForestBlock).filter(ForestBlock.id == merged["id"]).first()
    assert row.management_orientation == "Protection"


def test_merge_features_glues_a_single_point_corner_touch(client, db):
    """User report, 2026-09-12 (महाभारत compartments-1_merged_merged /
    Compartment-10): two features that visually "touch" at exactly one
    shared corner vertex (a diagonal chessboard-square touch, not a shared
    edge) used to be rejected as "not adjacent" -- topologically correct for
    a plain union (a single point can't become a shared edge on its own),
    but not what a genuinely-touching pair deserves. A small buffer
    round-trip now fuses them into one clean polygon, flagged with the
    POINT_TOUCH_GLUED warning."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    # Two squares touching only at (83.1, 27.1) -- verified distance=0.0,
    # boundary intersection is a single Point, plain union is a MultiPolygon.
    geom_a, geom_b = box(83.0, 27.0, 83.1, 27.1), box(83.1, 27.1, 83.2, 27.2)
    a = _block(db, calc, geom=geom_a, name="A", index=0)
    b = _block(db, calc, geom=geom_b, name="B", index=1)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "blocks", "feature_ids": [str(a.id), str(b.id)]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "POINT_TOUCH_GLUED" in body["warnings"]

    db.expire_all()
    from geoalchemy2.shape import to_shape
    from app.utils.geometry_utils import calculate_area_geodesic_from_shapely
    row = db.query(ForestBlock).filter(ForestBlock.id == body["feature"]["id"]).first()
    assert row is not None
    stored = to_shape(row.geometry)
    assert stored.geom_type == "Polygon"
    # Both original squares' area is preserved (the glue is area-neutral to
    # within the tiny buffer's own rounding, not a resize) -- the 1m glue
    # radius is negligible next to these ~11 km squares.
    expected_sqm = sum(calculate_area_geodesic_from_shapely(g)[0] for g in (geom_a, geom_b))
    assert abs(row.area_sqm - expected_sqm) < expected_sqm * 0.01


def test_merge_features_still_rejects_a_real_gap(client, db):
    """The point-touch glue must not widen the safety net: two features with
    a real gap between them (tens of metres, not a degenerate point) still
    get rejected, exactly as before."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    a = _block(db, calc, geom=box(83.0, 27.0, 83.1, 27.1), name="A", index=0)
    # A real gap (~1.6 km at the nearest corners) -- genuinely disjoint, not
    # touching at any point.
    b = _block(db, calc, geom=box(83.11, 27.11, 83.2, 27.2), name="B", index=1)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "blocks", "feature_ids": [str(a.id), str(b.id)]},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "TOPOLOGY_REJECTED"


def test_merge_features_requires_at_least_two(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    a = _block(db, calc, geom=box(83.2, 27.2, 83.5, 27.5), name="A", index=0)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "blocks", "feature_ids": [str(a.id)]},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# FS-4a.8 — merge: siblings only (D1), sub-units re-parented (D13)
# ---------------------------------------------------------------------------

def test_merge_rejects_a_block_and_a_compartment(client, db):
    """A block and a compartment are never siblings (different branches, D1) --
    no guard caught this before FS-4a.8, even though the two rows were
    adjacent and would have unioned into a single-branch-agnostic mess."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    a = _block(db, calc, geom=box(83.2, 27.2, 83.5, 27.5), name="Block-1",
               is_compartment=False, division_level=1, index=0)
    b = _block(db, calc, geom=box(83.5, 27.2, 83.8, 27.5), name="C1",
               is_compartment=True, division_level=1, index=1)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "blocks", "feature_ids": [str(a.id), str(b.id)]},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "MERGE_NOT_SIBLINGS"


def test_merge_rejects_sub_compartments_with_different_parents(client, db):
    """Two sub-compartments under DIFFERENT parent compartments are never
    siblings, even on the same branch and even if geometrically adjacent."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    parent_a = _block(db, calc, geom=box(83.0, 27.0, 83.5, 27.5), name="C1",
                       is_compartment=True, division_level=1, index=0)
    parent_b = _block(db, calc, geom=box(83.5, 27.0, 84.0, 27.5), name="C2",
                       is_compartment=True, division_level=1, index=1)
    sub_a = _block(db, calc, geom=box(83.1, 27.1, 83.4, 27.4), name="C1-SC1",
                    is_compartment=True, division_level=2, parent_block_id=parent_a.id, index=2)
    sub_b = _block(db, calc, geom=box(83.6, 27.1, 83.9, 27.4), name="C2-SC1",
                    is_compartment=True, division_level=2, parent_block_id=parent_b.id, index=3)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "sub_compartments", "feature_ids": [str(sub_a.id), str(sub_b.id)]},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "MERGE_NOT_SIBLINGS"


def test_merge_redistributes_sub_units_onto_the_merged_row(client, db):
    """D13: merging two sibling compartments, each with its own sub-compartment,
    must not silently destroy either sub-compartment -- both re-parent onto
    the ONE merged row."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    parent = _block(db, calc, geom=box(83.0, 27.0, 84.0, 27.5), name="Block-1",
                     is_compartment=False, division_level=1, index=0)
    comp_a = _block(db, calc, geom=box(83.0, 27.0, 83.5, 27.5), name="C1",
                     is_compartment=True, division_level=1, parent_block_id=parent.id, index=1)
    comp_b = _block(db, calc, geom=box(83.5, 27.0, 84.0, 27.5), name="C2",
                     is_compartment=True, division_level=1, parent_block_id=parent.id, index=2)
    sub_a = _block(db, calc, geom=box(83.1, 27.1, 83.3, 27.3), name="C1-SC1",
                    is_compartment=True, division_level=2, parent_block_id=comp_a.id, index=3)
    sub_b = _block(db, calc, geom=box(83.6, 27.1, 83.8, 27.3), name="C2-SC1",
                    is_compartment=True, division_level=2, parent_block_id=comp_b.id, index=4)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "compartments", "feature_ids": [str(comp_a.id), str(comp_b.id)]},
    )
    assert resp.status_code == 200, resp.text
    merged_id = resp.json()["feature"]["id"]

    db.expire_all()
    remaining_ids = {
        str(r.id) for r in db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    }
    assert str(comp_a.id) not in remaining_ids
    assert str(comp_b.id) not in remaining_ids
    assert str(sub_a.id) not in remaining_ids  # old sub-compartment rows gone
    assert str(sub_b.id) not in remaining_ids

    new_subs = (
        db.query(ForestBlock)
        .filter(ForestBlock.parent_block_id == merged_id)
        .all()
    )
    assert len(new_subs) == 2  # both survived, re-parented onto the merged row
    for s in new_subs:
        assert s.division_level == 2
        assert s.is_compartment is True


def test_edit_geometry_reshape_reclips_sub_blocks(client, db):
    """G2 (FS-4a.10), end-to-end through the real edit-geometry endpoint:
    reshaping a block that has sub-blocks re-clips them -- ground the edit
    removes trims a sub-block, ground it adds becomes a remainder sub-block."""
    headers, uid = _register(client)
    # Boundary well clear of the block on every side -- none of the block's
    # vertices sit on the forest boundary edge, so VR-3's outer-vertex lock
    # (only meant for a vertex actually shared with the boundary) never fires.
    calc = _calc(db, uid, box(80.0, 20.0, 90.0, 30.0))
    parent = _block(db, calc, geom=box(83.0, 27.0, 83.10, 27.10), name="Block-1",
                     is_compartment=False, division_level=1, index=0)
    # Two sub-blocks that fully tile the parent (west / east half).
    west = _block(db, calc, geom=box(83.0, 27.0, 83.05, 27.10), name="Block-1-SB1",
                  is_compartment=False, division_level=2, parent_block_id=parent.id, index=1)
    east = _block(db, calc, geom=box(83.05, 27.0, 83.10, 27.10), name="Block-1-SB2",
                  is_compartment=False, division_level=2, parent_block_id=parent.id, index=2)
    db.expire_all()

    # Reshape the parent: shrink the east edge (removes ground under `east`)
    # AND grow past the west edge (adds ground no sub-block covers).
    new_shape = box(82.95, 27.0, 83.08, 27.10)
    resp = client.post(
        f"{_edit_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(parent.id), "geometry": _gj(new_shape)},
    )
    assert resp.status_code == 200, resp.text

    db.expire_all()
    children = (
        db.query(ForestBlock)
        .filter(ForestBlock.parent_block_id == parent.id)
        .all()
    )
    # west (grown past its old western edge) + east (trimmed) + a new
    # remainder covering the newly-added western strip.
    assert len(children) == 3
    ids = {str(c.id) for c in children}
    assert str(west.id) in ids
    assert str(east.id) in ids
    remainder = next(c for c in children if str(c.id) not in {str(west.id), str(east.id)})
    assert remainder.division_level == 2
    assert remainder.is_compartment is False

    west_row = next(c for c in children if str(c.id) == str(west.id))
    east_row = next(c for c in children if str(c.id) == str(east.id))
    # A child only ever SHRINKS via intersection -- it never grows into newly
    # added ground (that's what the remainder is for). west is unaffected
    # (the edit didn't remove any of its ground); east is trimmed to the new
    # eastern edge (83.08); the remainder covers the newly-added western
    # strip (82.95-83.0) no existing child ever claimed.
    assert shape(json.loads(_block_geojson(db, west_row.id))).bounds[0] == pytest.approx(83.0, abs=1e-6)
    assert shape(json.loads(_block_geojson(db, east_row.id))).bounds[2] <= 83.08 + 1e-6
    remainder_bounds = shape(json.loads(_block_geojson(db, remainder.id))).bounds
    assert remainder_bounds[0] == pytest.approx(82.95, abs=1e-6)
    assert remainder_bounds[2] <= 83.0 + 1e-6

    # The three sub-blocks together tile the new parent shape.
    total = sum(
        area_sqm(shape(json.loads(_block_geojson(db, c.id))))
        for c in children
    )
    assert abs(total - area_sqm(new_shape)) < 100.0


def test_paste_units_preview_then_apply_takes_ground_from_a_sibling(client, db):
    """D12 (FS-4a.11), end-to-end through the real paste-units endpoint:
    preview shows the same result apply persists, and the pasted sub-block
    takes ground from an overlapping sibling."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(80.0, 20.0, 90.0, 30.0))
    parent = _block(db, calc, geom=box(83.0, 27.0, 83.10, 27.10), name="Block-1",
                     is_compartment=False, division_level=1, index=0)
    sib = _block(db, calc, geom=box(83.0, 27.0, 83.06, 27.10), name="Block-1-SB1",
                 is_compartment=False, division_level=2, parent_block_id=parent.id, index=1)
    db.expire_all()

    paste_geom = _gj(box(83.04, 27.0, 83.08, 27.10))

    preview_resp = client.post(
        f"{_edit_url(calc.id)}/paste-units",
        headers=headers,
        json={
            "layer_type": "sub_blocks",
            "parent_id": str(parent.id),
            "features": [paste_geom],
            "preview": True,
        },
    )
    assert preview_resp.status_code == 200, preview_resp.text
    preview_body = preview_resp.json()
    assert preview_body["preview"] is True
    assert len(preview_body["new_pieces"]) == 1
    assert len(preview_body["trimmed"]) == 1

    # Preview persisted nothing.
    db.expire_all()
    assert db.query(ForestBlock).filter(ForestBlock.parent_block_id == parent.id).count() == 1

    apply_resp = client.post(
        f"{_edit_url(calc.id)}/paste-units",
        headers=headers,
        json={
            "layer_type": "sub_blocks",
            "parent_id": str(parent.id),
            "features": [paste_geom],
            "preview": False,
        },
    )
    assert apply_resp.status_code == 200, apply_resp.text
    apply_body = apply_resp.json()
    assert apply_body["preview"] is False
    assert len(apply_body["new_pieces"]) == 1
    assert apply_body["new_pieces"][0]["id"]

    db.expire_all()
    children = db.query(ForestBlock).filter(ForestBlock.parent_block_id == parent.id).all()
    # trimmed sib + the new pasted piece + a remainder sub-unit completing the parent (owner rule
    # 2026-10-03: a divided unit's children always tile it -- no gap)
    assert len(children) == 3
    assert len(apply_body["remainder_added"]) == 1
    ids = {str(c.id) for c in children}
    assert str(sib.id) in ids
    sib_row = next(c for c in children if str(c.id) == str(sib.id))
    assert shape(json.loads(_block_geojson(db, sib_row.id))).bounds[2] <= 83.04 + 1e-6


def test_paste_units_same_place_refused(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(80.0, 20.0, 90.0, 30.0))
    parent = _block(db, calc, geom=box(83.0, 27.0, 83.10, 27.10), name="Block-1",
                     is_compartment=False, division_level=1, index=0)
    sib_geom = box(83.0, 27.0, 83.05, 27.10)
    _block(db, calc, geom=sib_geom, name="Block-1-SB1",
           is_compartment=False, division_level=2, parent_block_id=parent.id, index=1)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/paste-units",
        headers=headers,
        json={
            "layer_type": "sub_blocks",
            "parent_id": str(parent.id),
            "features": [_gj(sib_geom)],
            "preview": True,
        },
    )
    assert resp.status_code == 409, resp.text


def test_paste_units_cross_stream_refused_when_other_branch_has_rows(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(80.0, 20.0, 90.0, 30.0))
    _block(db, calc, geom=box(83.0, 27.0, 83.10, 27.10), name="Block-1",
           is_compartment=False, division_level=1, index=0)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/paste-units",
        headers=headers,
        json={
            "layer_type": "compartments",
            "parent_id": None,
            "features": [_gj(box(84.0, 27.0, 84.05, 27.05))],
            "preview": True,
        },
    )
    assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------------
# Phase C (auto-block) — UE toolset works on auto-generated blocks
# ---------------------------------------------------------------------------

def test_cut_polygon_pieces_preserve_block_and_natural_name(client, db):
    """C.1: splitting an auto-generated block (has block_name + natural_name)
    keeps the serial and natural name on every piece."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc, geom=box(2.5, 2.5, 5.5, 5.5),
                   name="Block-1", block_name="Block-1", natural_name="Rapati Nadi")
    db.expire_all()

    cut = {"type": "LineString", "coordinates": [[3.0, 2.0], [3.0, 6.0]]}
    resp = client.post(
        f"{_edit_url(calc.id)}/cut-polygon",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "cut_line": cut},
    )
    assert resp.status_code == 200, resp.text
    pieces = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    # 2 pieces from cut + 1 remainder block (invariant fills uncovered boundary)
    assert len(pieces) >= 3
    # Find the cut pieces (exclude remainder which has auto-generated name)
    cut_pieces = [p for p in pieces if p.block_name and p.block_name.startswith("Block-1-")]
    assert len(cut_pieces) >= 2
    for p in cut_pieces:
        assert p.block_name and p.block_name.startswith("Block-1-")
        assert p.natural_name == "Rapati Nadi"


def test_merge_features_carries_block_and_natural_name(client, db):
    """C.1: merging two auto-generated blocks produces a row whose block_name /
    natural_name survive (serial carries the _merged suffix, natural name kept)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    # Block-1 (larger) must win the attribute basis under the "largest wins"
    # rule (2026-09-12), independent of the size difference being the point.
    a = _block(db, calc, geom=box(83.2, 27.2, 83.6, 27.5),
               name="Block-1", block_name="Block-1", natural_name="Rapati Nadi", index=0)
    b = _block(db, calc, geom=box(83.6, 27.2, 83.8, 27.5),
               name="Block-2", block_name="Block-2", natural_name="Rapati Nadi", index=1)
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "blocks", "feature_ids": [str(a.id), str(b.id)]},
    )
    assert resp.status_code == 200, resp.text
    merged = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    # 1 merged block + 1 remainder block (invariant fills uncovered boundary)
    assert len(merged) == 2
    merged_block = next(m for m in merged if m.block_name == "Block-1_merged")
    remainder = next(m for m in merged if m.block_name != "Block-1_merged")
    assert merged_block.block_name == "Block-1_merged"
    assert merged_block.natural_name == "Rapati Nadi"
    assert re.fullmatch(r"B\d+", remainder.name), remainder.name  # system-named remainder: B<n>


def test_merge_features_imported_unions(client, db):
    """UE-2.2 — two imported features union into ONE new featureId; sources removed.

    "Imported Layer 1" (imp-1) is deliberately the larger feature, so it wins
    the attribute basis under the "largest wins" rule (2026-09-12)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    layer = _imported_layer_multi(
        db, calc, uid,
        [box(83.2, 27.2, 83.6, 27.5), box(83.6, 27.2, 83.8, 27.5)],
    )
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "imported", "layer_id": layer.id,
              "feature_ids": ["imp-1", "imp-2"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["feature"]["properties"]["name"] == "Imported Layer 1_merged"

    db.expire_all()
    fresh = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer.id).first()
    feats = fresh.layer_data["features"]
    assert len(feats) == 1
    assert feats[0]["properties"]["featureId"] == "imp-1-merged"
    assert float(feats[0]["properties"]["geo_area_ha"]) > 60_000


def test_merge_features_imported_small_geometries(client, db):
    """UE-2.2 — small-but-valid polygons (merged area < 1e-4 deg^2) still merge;
    the emptiness guard must never reject tiny real forest patches.

    imp-1 is deliberately the larger of the two so it wins the attribute
    basis under the "largest wins" rule (2026-09-12)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    layer = _imported_layer_multi(
        db, calc, uid,
        [box(83.5, 27.2, 83.508, 27.205), box(83.509, 27.2, 83.511, 27.205)],
    )
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "imported", "layer_id": layer.id,
              "feature_ids": ["imp-1", "imp-2"]},
    )
    assert resp.status_code == 200, resp.text
    db.expire_all()
    fresh = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer.id).first()
    feats = fresh.layer_data["features"]
    assert len(feats) == 1
    assert feats[0]["properties"]["featureId"] == "imp-1-merged"
    assert float(feats[0]["properties"]["geo_area_ha"]) > 0


def test_merge_features_imported_structure_locked(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    layer = _imported_layer_multi(
        db, calc, uid,
        [box(83.2, 27.2, 83.5, 27.5), box(83.5, 27.2, 83.8, 27.5)],
    )
    calc.structure_locked = True
    db.commit()
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "imported", "layer_id": layer.id,
              "feature_ids": ["imp-1", "imp-2"]},
    )
    assert resp.status_code == 423
    assert resp.json()["detail"]["code"] == "structure_locked"


def test_merge_features_sub_areas_unions(client, db):
    """UE-2.2 — result_data sub-areas merge into ONE.

    "Pine" (sa-1) is deliberately the larger sub-area, so it wins the
    attribute basis under the "largest wins" rule (2026-09-12)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    calc.result_data = {"sub_areas": [
        {"id": "sa-1", "name": "Pine", "category": "plantation",
         "geometry": _gj(box(83.2, 27.2, 83.6, 27.5))},
        {"id": "sa-2", "name": "Oak", "category": "plantation",
         "geometry": _gj(box(83.6, 27.2, 83.8, 27.5))},
    ]}
    db.commit()
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "sub_areas", "feature_ids": ["sa-1", "sa-2"]},
    )
    assert resp.status_code == 200, resp.text
    sa = resp.json()["feature"]
    assert sa["name"] == "Pine_merged"

    db.expire_all()
    subs = (db.get(Calculation, calc.id)).result_data["sub_areas"]
    assert len(subs) == 1
    assert subs[0]["name"] == "Pine_merged"


def test_copy_boundary_to_block(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(5, 5, 9, 9))
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/copy-boundary-to-block",
        headers=headers,
        json={"name": "Boundary Copy"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["block"]["id"]
    fresh = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).first()
    assert fresh.name == "Boundary Copy"


# ---------------------------------------------------------------------------
# delete-guard (R4/R5)
# ---------------------------------------------------------------------------

def test_delete_guard_blocked_on_child_compartments(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _block(db, calc)
    child = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="Comp-1",
        geometry=shp_wkt.dumps(box(83.3, 27.3, 83.5, 27.5)),
        area_hectares=0.5, index=1, division_level=1,
        is_compartment=True, parent_block_id=block.id, compartment_code="C1",
    )
    db.add(child)
    db.commit()
    db.expire_all()

    resp = client.get(
        f"{_edit_url(calc.id)}/delete-guard",
        headers=headers,
        params={"layer_type": "blocks", "feature_id": str(block.id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["blocked"] is True
    assert "child_compartments" in {r["type"] for r in resp.json()["reasons"]}


def test_delete_guard_open_when_clean(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _block(db, calc)
    db.expire_all()

    resp = client.get(
        f"{_edit_url(calc.id)}/delete-guard",
        headers=headers,
        params={"layer_type": "blocks", "feature_id": str(block.id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["blocked"] is False


def test_delete_boundary(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(5, 5, 9, 9))
    # a digitized/imported boundary also lives in result_data (the SSOT the UI
    # and the boundary layer's fetch read); delete must clear it too or the
    # boundary reappears on the next refresh.
    calc.result_data = {
        "geometry": {"type": "Polygon", "coordinates": [[[5, 5], [9, 5], [9, 9], [5, 9], [5, 5]]]},
        "area_hectares": 123.4,
        "boundary_name": "Old",
    }
    db.commit()
    db.expire_all()

    resp = client.delete(f"/api/v1/calculations/{calc.id}/boundary", headers=headers)
    assert resp.status_code == 204, resp.text
    db.expire_all()
    db.refresh(calc)
    assert calc.boundary_geom is None
    rd = calc.result_data or {}
    assert "geometry" not in rd and "area_hectares" not in rd and "boundary_name" not in rd


def test_delete_boundary_rejected_when_blocks_exist(client, db):
    """User rule (2026-08-12): boundary delete is blocked while any dependent
    layer (blocks/compartments/sub-compartments/sub-areas) exists; it may only
    be deleted when no other layer data is present."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(5, 5, 9, 9))
    _block(db, calc)
    db.expire_all()

    resp = client.delete(f"/api/v1/calculations/{calc.id}/boundary", headers=headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "HAS_CHILD_LAYERS"
    db.expire_all()
    db.refresh(calc)
    assert calc.boundary_geom is not None

    # clearing the blocks layer first makes the boundary deletable
    resp = client.delete(
        f"/api/forests/calculations/{calc.id}/blocks",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.delete(f"/api/v1/calculations/{calc.id}/boundary", headers=headers)
    assert resp.status_code == 204, resp.text
    db.expire_all()
    db.refresh(calc)
    assert calc.boundary_geom is None


def test_delete_boundary_rejected_when_sub_areas_exist(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(5, 5, 9, 9))
    calc.result_data = {
        "sub_areas": [
            {
                "id": str(uuid.uuid4()),
                "name": "Sacred Grove",
                "geometry": {"type": "Polygon", "coordinates": [[[5.5, 5.5], [6.5, 5.5], [6.5, 6.5], [5.5, 6.5], [5.5, 5.5]]]},
            }
        ]
    }
    db.commit()
    db.expire_all()

    resp = client.delete(f"/api/v1/calculations/{calc.id}/boundary", headers=headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "HAS_CHILD_LAYERS"
    db.expire_all()
    db.refresh(calc)
    assert calc.boundary_geom is not None

    # server-internal force=true bypasses the guard
    resp = client.delete(
        f"/api/v1/calculations/{calc.id}/boundary?force=true",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text
    db.expire_all()
    db.refresh(calc)
    assert calc.boundary_geom is None


# ---------------------------------------------------------------------------
# E1.3 — locks
# ---------------------------------------------------------------------------

def test_structure_locked_blocked(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _block(db, calc)
    calc.structure_locked = True
    db.commit()
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "geometry": _gj(box(83.2, 27.2, 83.9, 27.7))},
    )
    assert resp.status_code == 423, resp.text
    assert resp.json()["detail"]["code"] == "structure_locked"


def test_map_state_gate_and_force(client, db):
    headers, uid = _register(client)
    # default boundary box(83,27,84,28) encloses both the block and the edit geometry
    calc = _calc(db, uid)
    block = _block(db, calc)
    calc.map_lifecycle_status = "locked"
    db.commit()
    db.expire_all()

    # UI never sends force → 409
    resp = client.post(
        f"{_edit_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "geometry": _gj(box(83.2, 27.2, 83.9, 27.7))},
    )
    assert resp.status_code == 409, resp.text

    # server-internal force=true → allowed
    resp2 = client.post(
        f"{_edit_url(calc.id)}/edit-geometry?force=true",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "geometry": _gj(box(83.2, 27.2, 83.9, 27.7))},
    )
    assert resp2.status_code == 200, resp2.text


# ---------------------------------------------------------------------------
# review-fix #8 — legacy PATCH rejects geometry
# ---------------------------------------------------------------------------

def test_legacy_update_blocks_rejects_geometry(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc)
    db.expire_all()

    resp = client.patch(
        f"/api/v1/blocks/calculations/{calc.id}/update-blocks",
        headers=headers,
        json={"blocks": [{"block_id": str(block.id), "geometry": _gj(box(83.2, 27.2, 83.9, 27.7))}], "update_boundary": False},
    )
    assert resp.status_code == 400, resp.text
    assert "edit-geometry" in resp.json()["detail"]


def test_legacy_sub_area_update_rejects_geometry(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    db.expire_all()

    resp = client.patch(
        f"/api/v1/calculations/{calc.id}/sub-areas/whatever",
        headers=headers,
        json={"name": "Rename Only", "geometry": _gj(box(83.2, 27.2, 83.9, 27.7))},
    )
    assert resp.status_code in (400, 404), resp.text
    if resp.status_code == 400:
        assert "edit-geometry" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Phase C (auto-block) — rename keeps name / block_name / natural_name in sync
# ---------------------------------------------------------------------------

def test_block_rename_body_syncs_block_name_and_natural_name(client, db):
    """C.2: PATCH body {name} renames display name AND block_name (serial);
    {natural_name} is stored separately; response carries all three.
    Exercises the /forests/... route the workspace AttributeTable hits."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc, name="Block-1", block_name="Block-1", natural_name="Rapati Nadi")
    db.expire_all()

    resp = client.patch(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"name": "Dhungre Ban"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Dhungre Ban"
    assert body["block_name"] == "Dhungre Ban"
    assert body["natural_name"] == "Rapati Nadi"

    resp2 = client.patch(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"natural_name": "Mardi Khola"},
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["natural_name"] == "Mardi Khola"
    # name untouched when only natural_name sent
    assert resp2.json()["name"] == "Dhungre Ban"


def test_block_rename_explicit_block_name_keeps_distinct(client, db):
    """C.2: explicit block_name wins over name mirroring."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc, name="Block-1", block_name="Block-1")
    db.expire_all()

    resp = client.patch(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"name": "Comp A", "block_name": "Block-99"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Comp A"
    assert resp.json()["block_name"] == "Block-99"


def test_block_rename_empty_body_rejected(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc)
    db.expire_all()

    resp = client.patch(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={},
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert "at least one" in detail["message"]
    assert detail["message_np"]


def test_block_rename_explicit_null_clears_natural_name(client, db):
    """C.2: `natural_name: null` clears it, but omitting the key keeps it."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc, name="Block-1", block_name="Block-1", natural_name="Rapati Nadi")
    db.expire_all()

    # omit natural_name -> kept
    resp = client.patch(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"name": "Block-2"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["natural_name"] == "Rapati Nadi"

    # explicit null -> cleared
    resp2 = client.patch(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"natural_name": None},
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["natural_name"] is None


def test_block_rename_legacy_query_param_still_works(client, db):
    """C.2: legacy ?name= query param is still honoured."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc, name="Old Name", block_name="Old Name")
    db.expire_all()

    resp = client.patch(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{block.id}?name=Legacy Name",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Legacy Name"
    assert resp.json()["block_name"] == "Legacy Name"


def test_block_rename_edits_classification_and_compartment_code(client, db):
    """User report, 2026-09-12: a merge auto-picks compartment_code/
    dominant_slope_band/dominant_aspect/dominant_canopy_class from the larger
    source feature, but the user must still be able to correct the pick by
    hand -- same PATCH endpoint, same explicit-including-null-clears rule as
    natural_name/style. Exercises the /forests/... route the workspace
    AttributeTable hits."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(
        db, calc, name="Compartment-1", block_name="Compartment-1",
        compartment_code="C-1", dominant_slope_band=1, dominant_aspect=None,
        dominant_canopy_class=None,
    )
    db.expire_all()

    resp = client.patch(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={
            "compartment_code": "C-1-revised",
            "dominant_slope_band": 4,
            "dominant_aspect": 5,
            "dominant_canopy_class": 3,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["compartment_code"] == "C-1-revised"
    assert body["dominant_slope_band"] == 4
    assert body["dominant_aspect"] == 5
    assert body["dominant_canopy_class"] == 3

    db.expire_all()
    db.refresh(block)
    assert block.compartment_code == "C-1-revised"
    assert block.dominant_slope_band == 4
    assert block.dominant_aspect == 5
    assert block.dominant_canopy_class == 3

    # explicit null clears each field back to "not classified"
    resp2 = client.patch(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"dominant_slope_band": None, "compartment_code": None},
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["dominant_slope_band"] is None
    assert resp2.json()["compartment_code"] is None
    # untouched fields survive
    assert resp2.json()["dominant_aspect"] == 5
    assert resp2.json()["dominant_canopy_class"] == 3


def test_block_rename_rejects_out_of_range_classification(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc, name="Compartment-1", block_name="Compartment-1")
    db.expire_all()

    resp = client.patch(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"dominant_slope_band": 5},
    )
    assert resp.status_code == 422, resp.text


def test_block_rename_classification_edit_also_works_on_the_other_mounted_route(client, db):
    """blocks.py duplicates forests.py's update_block (a different mount,
    /api/v1/blocks/... vs /api/v1/forests/...) — both must stay in sync."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc, name="Compartment-1", block_name="Compartment-1")
    db.expire_all()

    resp = client.patch(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"dominant_canopy_class": 2},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["dominant_canopy_class"] == 2


def test_raster_dominant_edit_persists_through_both_routes(client, db):
    """RS-2.3 gate, rule 8: the four Raster-Sources dominant_* codes are
    editable (not write-once) on BOTH mounted PATCH routes, with ge/le
    bounds. The elevation_* trio is response-only — sending it must not be a
    valid field (schema rejects it), and the response still carries it."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(
        db, calc, name="Compartment-1", block_name="Compartment-1",
        dominant_health_class=3, dominant_nasa_quality=2,
        dominant_landcover=50, dominant_elevation_zone=2,
        elevation_min_m="310.0", elevation_mean_m="415.5",
        elevation_max_m="520.0",
    )
    db.expire_all()

    # /api/v1/forests/... (the route the workspace AttributeTable hits)
    resp = client.patch(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"dominant_nasa_quality": 3, "dominant_health_class": 5},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dominant_nasa_quality"] == 3
    assert body["dominant_health_class"] == 5
    assert body["dominant_landcover"] == 50          # untouched survives
    assert body["dominant_elevation_zone"] == 2       # untouched survives
    assert body["elevation_mean_m"] == 415.5          # response-only read-back

    # bounds enforced by the update schema
    resp_bad = client.patch(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"dominant_nasa_quality": 4},
    )
    assert resp_bad.status_code == 422, resp_bad.text

    # elevation is response-only (plan §5.1 item 5: absent from the update
    # schema): a request carrying only `elevation_mean_m` has nothing to apply
    # and is rejected as "nothing to update" -- it is never accepted as a
    # writable field.
    resp_ro = client.patch(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"elevation_mean_m": 999.0},
    )
    assert resp_ro.status_code == 400, resp_ro.text
    db.expire_all()
    db.refresh(block)
    assert float(block.elevation_mean_m) == 415.5

    # /api/v1/blocks/... (the second mount, must stay in sync)
    resp2 = client.patch(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"dominant_nasa_quality": 1},
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["dominant_nasa_quality"] == 1

    db.expire_all()
    db.refresh(block)
    assert block.dominant_nasa_quality == 1
    assert block.dominant_health_class == 5

    # explicit null clears a code back to "not classified" (same rule as the
    # 084/085 fields)
    resp3 = client.patch(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"dominant_nasa_quality": None},
    )
    assert resp3.status_code == 200, resp3.text
    assert resp3.json()["dominant_nasa_quality"] is None
    assert resp3.json()["dominant_health_class"] == 5


def test_merge_auto_picks_raster_dominant_from_the_larger_feature(client, db):
    """RS-2.3 gate: a merge auto-picks the Raster-Sources dominant_* codes
    from the larger source feature — same largest-feature-wins basis as the
    084/085 fields, routed through CHILD_INHERITED_COLUMNS."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    small = _block(
        db, calc, geom=box(83.6, 27.2, 83.8, 27.5), name="Small", index=0,
        dominant_health_class=2, dominant_nasa_quality=2,
        dominant_landcover=40, dominant_elevation_zone=1,
        elevation_min_m="200.0", elevation_mean_m="250.0",
        elevation_max_m="300.0",
    )
    big = _block(
        db, calc, geom=box(83.2, 27.2, 83.6, 27.5), name="Big", index=1,
        dominant_health_class=4, dominant_nasa_quality=3,
        dominant_landcover=60, dominant_elevation_zone=3,
        elevation_min_m="600.0", elevation_mean_m="700.0",
        elevation_max_m="800.0",
    )
    db.expire_all()

    resp = client.post(
        f"{_edit_url(calc.id)}/merge-features",
        headers=headers,
        json={"layer_type": "blocks", "feature_ids": [str(small.id), str(big.id)]},
    )
    assert resp.status_code == 200, resp.text
    merged = resp.json()["feature"]
    assert merged["name"] == "Big_merged"

    db.expire_all()
    row = db.query(ForestBlock).filter(ForestBlock.id == merged["id"]).first()
    assert row.dominant_health_class == 4
    assert row.dominant_nasa_quality == 3
    assert row.dominant_landcover == 60
    assert row.dominant_elevation_zone == 3
    assert float(row.elevation_mean_m) == 700.0


def test_block_rename_edits_management_orientation(client, db):
    """User report, 2026-09-12: a slope-carved block's auto-suggested
    Management Orientation must be correctable by hand, restricted to the
    3 SFM-aligned values, clearable to null, on both mounted routes."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(
        db, calc, name="Compartment-1", block_name="Compartment-1",
        dominant_slope_band=1, management_orientation="Production",
    )
    db.expire_all()

    resp = client.patch(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"management_orientation": "Conservation"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["management_orientation"] == "Conservation"

    db.expire_all()
    db.refresh(block)
    assert block.management_orientation == "Conservation"

    # explicit null clears it back to "not classified"
    resp2 = client.patch(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"management_orientation": None},
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["management_orientation"] is None

    # rejects a value outside the 3-value set
    bad = client.patch(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"management_orientation": "Restoration"},
    )
    assert bad.status_code == 422, bad.text

    # the other mounted route stays in sync
    other = client.patch(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{block.id}",
        headers=headers,
        json={"management_orientation": "Protection"},
    )
    assert other.status_code == 200, other.text
    assert other.json()["management_orientation"] == "Protection"


def test_blocks_fetch_returns_the_commit_time_suggested_orientation(client, db):
    """"Suggested Orientation" is the value persisted when the block was created
    (migration 087), not a live read: a later change in SFM's cache must not move it,
    and a block that never got one (any origin but slope Auto-Block) stays blank."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    kept = _block(
        db, calc, name="Block-1", block_name="Block-1",
        dominant_slope_band=3, management_orientation="Production",
        suggested_orientation="Conservation",
    )
    never = _block(
        db, calc, geom=box(3, 3, 4, 4), name="Block-2", block_name="Block-2", index=1,
    )
    # SFM has since moved on for both blocks.
    calc.result_data = {
        "sfm": {"blocks": [
            {"block_name": "Block-1", "orientation": "Protection"},
            {"block_name": "Block-2", "orientation": "Protection"},
        ]}
    }
    db.commit()
    db.expire_all()

    resp = client.get(
        f"/api/v1/forests/calculations/{calc.id}/blocks", headers=headers,
    )
    assert resp.status_code == 200, resp.text
    rows = {b["id"]: b for b in resp.json()["blocks"]}
    assert rows[str(kept.id)]["management_orientation"] == "Production"
    assert rows[str(kept.id)]["suggested_orientation"] == "Conservation"  # not "Protection"
    assert rows[str(never.id)]["suggested_orientation"] is None


def test_blocks_fetch_returns_the_commit_time_orientation_justification(client, db):
    """The read-only Justification column is persisted alongside the suggested
    orientation, so it is stable for the same reason -- and null, not a KeyError or a
    live SFM read, when the block never got one."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    kept = _block(
        db, calc, name="Block-1", block_name="Block-1",
        dominant_slope_band=3, management_orientation="Production",
        suggested_orientation="Conservation",
        orientation_justification_en="type 8 · slope > 45° · erosion-sensitive",
        orientation_justification_ne="सि.नं. 8 · > ४५° भिरालो · भू-क्षय संवेदनशील",
    )
    never = _block(
        db, calc, geom=box(3, 3, 4, 4), name="Block-2", block_name="Block-2", index=1,
    )
    calc.result_data = {
        "sfm": {"blocks": [{
            "block_name": "Block-2",
            "orientation": "Conservation",
            "orientation_justification_en": "a live value that must not be shown",
            "orientation_justification_ne": "देखाउनु हुँदैन",
        }]}
    }
    db.commit()
    db.expire_all()

    resp = client.get(
        f"/api/v1/forests/calculations/{calc.id}/blocks", headers=headers,
    )
    assert resp.status_code == 200, resp.text
    rows = {b["id"]: b for b in resp.json()["blocks"]}
    assert rows[str(kept.id)]["orientation_justification_en"] == "type 8 · slope > 45° · erosion-sensitive"
    assert rows[str(kept.id)]["orientation_justification_ne"] == "सि.नं. 8 · > ४५° भिरालो · भू-क्षय संवेदनशील"
    assert rows[str(never.id)]["orientation_justification_en"] is None
    assert rows[str(never.id)]["orientation_justification_ne"] is None


# ---------------------------------------------------------------------------
# E-3 — snapshot feature + restore feature (undo of a per-row delete, R5)
# ---------------------------------------------------------------------------

def test_snapshot_block_and_restore_with_original_id(client, db):
    """DELETE a block row, then restore it — original id preserved (R5)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc, name="Del-Me", geom=box(2.5, 2.5, 5.5, 5.5))
    block_id = str(block.id)
    db.expire_all()

    # snapshot BEFORE delete
    snap = client.get(
        f"/api/v1/calculations/{calc.id}/geometry/feature",
        headers=headers,
        params={"layer_type": "blocks", "feature_id": block_id},
    )
    assert snap.status_code == 200, snap.text
    payload = snap.json()
    assert payload["feature_id"] == block_id
    assert "geometry" in payload["snapshot"]
    assert payload["snapshot"]["name"] == "Del-Me"

    # hard-delete the row (simulating a completed delete)
    db.execute(text("DELETE FROM forest_blocks WHERE id = :id"), {"id": block_id})
    db.commit()

    # restore via snapshot
    resp = client.post(
        f"/api/v1/calculations/{calc.id}/geometry/restore-feature",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": block_id, "snapshot": payload["snapshot"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["feature_id"] == block_id

    db.expire_all()
    restored = db.query(ForestBlock).filter(ForestBlock.id == block_id).first()
    assert restored is not None
    assert restored.name == "Del-Me"


def test_snapshot_boundary_and_restore(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(3, 3, 7, 7))
    db.expire_all()

    snap = client.get(
        f"/api/v1/calculations/{calc.id}/geometry/feature",
        headers=headers,
        params={"layer_type": "boundary", "feature_id": "boundary"},
    )
    assert snap.status_code == 200, snap.text
    snapshot = snap.json()["snapshot"]

    # delete boundary
    resp = client.delete(f"/api/v1/calculations/{calc.id}/boundary", headers=headers)
    assert resp.status_code == 204, resp.text
    db.expire_all()
    db.refresh(calc)
    assert calc.boundary_geom is None

    # restore boundary
    resp2 = client.post(
        f"/api/v1/calculations/{calc.id}/geometry/restore-feature",
        headers=headers,
        json={"layer_type": "boundary", "feature_id": "boundary", "snapshot": snapshot},
    )
    assert resp2.status_code == 200, resp2.text
    db.expire_all()
    db.refresh(calc)
    assert calc.boundary_geom is not None


def test_restore_block_structure_locked_rejected(client, db):
    """E1.3: restore honors the write guard (structure lock = 423 always)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc)
    db.expire_all()

    snap = client.get(
        f"/api/v1/calculations/{calc.id}/geometry/feature",
        headers=headers,
        params={"layer_type": "blocks", "feature_id": str(block.id)},
    ).json()["snapshot"]

    calc.structure_locked = True
    db.commit()
    db.expire_all()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/geometry/restore-feature",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "snapshot": snap},
    )
    assert resp.status_code == 423, resp.text


# ---------------------------------------------------------------------------
# E-3 — workspace import-layer per-feature delete + restore
# ---------------------------------------------------------------------------

def _import_layer(db, calc, user_id, features):
    layer = WorkspaceLayer(
        calculation_id=calc.id,
        name="Imported Test Layer",
        purpose="custom",
        source_format=".geojson",
        feature_count=len(features),
        geometry_types=["Polygon"],
        layer_data={"type": "FeatureCollection", "features": features},
        is_draft=False,
        created_by=user_id,
    )
    db.add(layer)
    db.commit()
    db.refresh(layer)
    return layer


def _import_feature(fid, name):
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[
            [3.0, 3.0], [4.0, 3.0], [4.0, 4.0], [3.0, 4.0], [3.0, 3.0],
        ]]},
        "properties": {"featureId": fid, "name": name},
    }


def test_workspace_delete_import_feature(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 8, 8))
    layer = _import_layer(db, calc, uid, features=[
        _import_feature("f1", "A"),
        _import_feature("f2", "B"),
        _import_feature("f3", "C"),
    ])
    db.expire_all()

    resp = client.delete(
        f"/api/v1/workspace/{calc.id}/import-layers/{layer.id}/features/1",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["feature_count"] == 2
    assert body["deleted_feature"]["properties"]["name"] == "B"

    db.expire_all()
    fresh = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer.id).first()
    assert fresh.feature_count == 2
    names = [f["properties"]["name"] for f in fresh.layer_data["features"]]
    assert names == ["A", "C"]


def test_workspace_restore_import_feature_at_index(client, db):
    """Restore re-inserts at the ORIGINAL index → stable redo (R5)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 8, 8))
    layer = _import_layer(db, calc, uid, features=[
        _import_feature("f1", "A"),
        _import_feature("f2", "B"),
        _import_feature("f3", "C"),
    ])
    db.expire_all()

    # delete f2 (index 1) → ["A", "C"]
    del_resp = client.delete(
        f"/api/v1/workspace/{calc.id}/import-layers/{layer.id}/features/1",
        headers=headers,
    )
    assert del_resp.status_code == 200, del_resp.text
    deleted = del_resp.json()["deleted_feature"]

    # undo: restore at original index 1 → ["A", "B", "C"]
    resp = client.post(
        f"/api/v1/workspace/{calc.id}/import-layers/{layer.id}/features/restore",
        headers=headers,
        json={"feature": deleted, "feature_id": "f2", "feature_index": 1},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["feature_count"] == 3

    db.expire_all()
    fresh = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer.id).first()
    names = [f["properties"]["name"] for f in fresh.layer_data["features"]]
    assert names == ["A", "B", "C"]  # re-inserted at original index

    # idempotent: same featureId again → skipped (no duplicate rows)
    resp2 = client.post(
        f"/api/v1/workspace/{calc.id}/import-layers/{layer.id}/features/restore",
        headers=headers,
        json={"feature": deleted, "feature_id": "f2", "feature_index": 1},
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["already_restored"] is True
    assert resp2.json()["feature_count"] == 3
    db.expire_all()
    fresh2 = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer.id).first()
    assert len(fresh2.layer_data["features"]) == 3


def test_workspace_delete_and_restore_roundtrip(client, db):
    """Delete → undo restore → redo delete keeps the row index stable (R5)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 8, 8))
    layer = _import_layer(db, calc, uid, features=[
        _import_feature("f1", "A"),
        _import_feature("f2", "B"),
    ])
    db.expire_all()

    # delete index 0
    resp = client.delete(
        f"/api/v1/workspace/{calc.id}/import-layers/{layer.id}/features/0",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    deleted = resp.json()["deleted_feature"]

    # restore at original index 0
    rest = client.post(
        f"/api/v1/workspace/{calc.id}/import-layers/{layer.id}/features/restore",
        headers=headers,
        json={"feature": deleted, "feature_id": "f1", "feature_index": 0},
    )
    assert rest.status_code == 200, rest.text
    assert rest.json()["feature_count"] == 2

    db.expire_all()
    fresh = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer.id).first()
    names = [f["properties"]["name"] for f in fresh.layer_data["features"]]
    assert names == ["A", "B"]


def test_workspace_delete_import_feature_out_of_range(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 8, 8))
    layer = _import_layer(db, calc, uid, features=[_import_feature("f1", "A")])
    db.expire_all()

    resp = client.delete(
        f"/api/v1/workspace/{calc.id}/import-layers/{layer.id}/features/99",
        headers=headers,
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# D-2026-09-15 — legacy compartments.py split endpoints (a separate router,
# app/api/compartments.py, not app/api/editing.py -- included here anyway
# for the shared _register/_calc/_block fixtures) also went through the
# child_inherit_kwargs fix, closing the gap between these older endpoints and
# the workspace cut/divide tools above.
# ---------------------------------------------------------------------------

def test_legacy_execute_split_carries_working_circle_orientation_and_style(client, db):
    """Owner request, 2026-09-15: the legacy `/api/compartments/execute-split`
    endpoint (independent code from the workspace divide/cut tools, still
    live) previously dropped every non-geometric attribute of the block being
    split -- new compartments always came out working_circle='production' /
    management_orientation=None / style=None / natural_name=None with a
    fresh palette color, regardless of the source block."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    block = _block(
        db, calc, geom=box(83.2, 27.2, 83.8, 27.7), name="Block 1", index=0,
        working_circle="protection",
        management_orientation="Protection",
        style={"fill": "#123456"},
        natural_name="Legacy Ridge",
        color="#654321",
    )
    db.expire_all()

    resp = client.post(
        "/api/compartments/execute-split",
        headers=headers,
        json={
            "block_id": str(block.id),
            "method": "parallel",
            "parameters": {"direction_angle": 90, "num_compartments": 2},
        },
    )
    assert resp.status_code == 200, resp.text

    db.expire_all()
    children = db.query(ForestBlock).filter(
        ForestBlock.parent_block_id == block.id, ForestBlock.is_compartment == True,  # noqa: E712
    ).all()
    assert len(children) == 2
    for c in children:
        assert c.working_circle == "protection"
        assert c.management_orientation == "Protection"
        assert c.style == {"fill": "#123456"}
        assert c.natural_name == "Legacy Ridge"
        assert c.color == "#654321"
        assert c.block_name == c.name  # was dropped entirely before the fix


def test_legacy_subdivide_block_carries_working_circle_orientation_and_style(client, db):
    """Owner request, 2026-09-15: the legacy
    `/api/compartments/blocks/{id}/sub-divide` endpoint (a second,
    independent duplicate of the same child-row-building logic) had the
    same gap as execute-split above."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(83.0, 27.0, 84.0, 28.0))
    compartment = _block(
        db, calc, geom=box(83.2, 27.2, 83.8, 27.7), name="Comp 1", index=0,
        is_compartment=True, division_level=1,
        working_circle="protection",
        management_orientation="Conservation",
        style={"fill": "#abcdef"},
        natural_name="Legacy Sub Ridge",
        color="#fedcba",
    )
    db.expire_all()

    resp = client.post(
        f"/api/compartments/blocks/{compartment.id}/sub-divide",
        headers=headers,
        json={
            "method": "parallel",
            "parameters": {"direction_angle": 90, "num_compartments": 2},
        },
    )
    assert resp.status_code == 200, resp.text

    db.expire_all()
    children = db.query(ForestBlock).filter(
        ForestBlock.parent_block_id == compartment.id,
    ).all()
    assert len(children) == 2
    for c in children:
        assert c.working_circle == "protection"
        assert c.management_orientation == "Conservation"
        assert c.style == {"fill": "#abcdef"}
        assert c.natural_name == "Legacy Sub Ridge"
        assert c.color == "#fedcba"