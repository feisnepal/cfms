"""V-2 — atomic shared-vertex move (D2) integration tests.

Covers the plan §4 V-2:
  - 2 blocks, move a shared vertex → BOTH geometries updated, no gap, no
    overlap, accepted (was: rejected)
  - move a vertex ON the boundary (junction) → rejected 409 (locked shell)
  - move an interior shared vertex on a 3-block junction → all 3 updated
  - mid-edge shared vertex: move along the edge → accepted, single feature;
    move off the edge → R6 rejected
  - shared_moves validation gate (only structural layers)
"""
import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import box
from sqlalchemy import text

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock


def _register(client):
    email = f"v2-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "V2 Repro",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _calc(db, user_id, boundary=box(83.0, 27.0, 84.0, 28.0)):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name="V2 Forest",
        boundary_geom=shp_wkt.dumps(boundary),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _block(db, calc, geom, name="B", index=0, **kwargs):
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


def _gj(geom):
    from shapely.geometry import shape
    return shape(geom).__geo_interface__


def _block_geojson(db, block_id):
    row = db.execute(text(
        "SELECT ST_AsGeoJSON(geometry) AS g FROM forest_blocks WHERE id = :id"
    ), {"id": str(block_id)}).first()
    return row.g if row else None


def _url(calc_id, api="/api/v1"):
    return f"{api}/calculations/{calc_id}/geometry"


# ---------------------------------------------------------------------------
# D2 — atomic shared-vertex move
# ---------------------------------------------------------------------------

def test_shared_vertex_move_updates_both_blocks(client, db):
    """2 blocks sharing the vertical edge x=83.5.  Move the shared bottom-left
    corner of A rightward → B's matching corner must move too (one transaction).
    """
    headers = _register(client)
    user = client.get("/api/auth/me", headers=headers).json()["id"]
    calc = _calc(db, user)
    a = _block(db, calc, box(83.2, 27.2, 83.5, 27.8), name="A", index=0)
    b = _block(db, calc, box(83.5, 27.2, 83.8, 27.8), name="B", index=1)
    db.expire_all()

    # A's shared corner (83.5,27.2) → (83.6,27.2).  Both A and B carry a vertex
    # at (83.5,27.2); B's copy must move to (83.6,27.2) too.
    a_moved = {
        "type": "Polygon",
        "coordinates": [[[83.2, 27.2], [83.6, 27.2], [83.5, 27.8], [83.2, 27.8], [83.2, 27.2]]],
    }
    b_moved = {
        "type": "Polygon",
        "coordinates": [[[83.6, 27.2], [83.8, 27.2], [83.8, 27.8], [83.5, 27.8], [83.6, 27.2]]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        headers=headers,
        json={
            "layer_type": "blocks",
            "feature_id": str(a.id),
            "geometry": a_moved,
            "shared_moves": [{"feature_id": str(b.id), "geometry": b_moved}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["shared_moves_applied"] == 1
    assert set(body["updated_feature_ids"]) == {str(a.id), str(b.id)}

    db.expire_all()
    a2 = _block_geojson(db, a.id)
    b2 = _block_geojson(db, b.id)
    assert "83.6" in a2
    assert "83.6" in b2


def test_shared_vertex_move_without_propagation_rejected(client, db):
    """Regression guard: moving A's shared corner WITHOUT propagating B still
    gets rejected by R6 (gap opens against the unchanged neighbour)."""
    headers = _register(client)
    user = client.get("/api/auth/me", headers=headers).json()["id"]
    calc = _calc(db, user)
    a = _block(db, calc, box(83.2, 27.2, 83.5, 27.8), name="A", index=0)
    _block(db, calc, box(83.5, 27.2, 83.8, 27.8), name="B", index=1)
    db.expire_all()

    a_moved = {
        "type": "Polygon",
        "coordinates": [[[83.2, 27.2], [83.6, 27.2], [83.5, 27.8], [83.2, 27.8], [83.2, 27.2]]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(a.id), "geometry": a_moved},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "TOPOLOGY_REJECTED"


def test_outer_shell_vertex_move_is_refused(client, db):
    """VR-3: a shell vertex move is now REFUSED BY THE SERVER.

    This test used to assert the opposite, and its own docstring named the
    hole: "frontend-gated (V-3) — but a single-feature move is still accepted
    by the backend".  Hiding a marker is not enforcement; undo/redo, a retried
    request or any other client could move the vertex and the API stored it.
    (83.0, 27.5) lies on the forest boundary's left edge, so it is a shell
    vertex and the write is rejected with VERTEX_LOCKED."""
    headers = _register(client)
    user = client.get("/api/auth/me", headers=headers).json()["id"]
    calc = _calc(db, user, box(83.0, 27.0, 84.0, 28.0))
    a = _block(db, calc, box(83.0, 27.0, 83.5, 27.5), name="A", index=0)
    db.expire_all()

    a_moved = {
        "type": "Polygon",
        "coordinates": [[[83.0, 27.0], [83.5, 27.0], [83.5, 27.5], [83.1, 27.5], [83.0, 27.0]]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(a.id), "geometry": a_moved},
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "VERTEX_LOCKED"
    assert detail["locked_indices"], "the response must name the locked vertices"


def test_three_block_junction_all_updated(client, db):
    """3 blocks meeting at an interior point → moving that shared vertex must
    update all three geometries."""
    headers = _register(client)
    user = client.get("/api/auth/me", headers=headers).json()["id"]
    calc = _calc(db, user)

    # three quads around the shared point (83.5, 27.5)
    a = _block(db, calc, box(83.2, 27.2, 83.5, 27.5), name="A", index=0)
    b = _block(db, calc, box(83.5, 27.2, 83.8, 27.5), name="B", index=1)
    c = _block(db, calc, box(83.3, 27.5, 83.7, 27.8), name="C", index=2)
    db.expire_all()

    # move the shared corner (83.5,27.5) of A to (83.6,27.4); B and C carry a
    # coincident vertex there too and must move along.
    a_moved = {
        "type": "Polygon",
        "coordinates": [[[83.2, 27.2], [83.5, 27.2], [83.6, 27.4], [83.2, 27.5], [83.2, 27.2]]],
    }
    b_moved = {
        "type": "Polygon",
        "coordinates": [[[83.5, 27.2], [83.8, 27.2], [83.8, 27.5], [83.6, 27.4], [83.5, 27.2]]],
    }
    c_moved = {
        "type": "Polygon",
        "coordinates": [[[83.3, 27.5], [83.6, 27.4], [83.7, 27.5], [83.7, 27.8], [83.3, 27.5]]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        headers=headers,
        json={
            "layer_type": "blocks",
            "feature_id": str(a.id),
            "geometry": a_moved,
            "shared_moves": [
                {"feature_id": str(b.id), "geometry": b_moved},
                {"feature_id": str(c.id), "geometry": c_moved},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["shared_moves_applied"] == 2
    assert set(body["updated_feature_ids"]) == {str(a.id), str(b.id), str(c.id)}

    db.expire_all()
    for blk in (a, b, c):
        geojson = _block_geojson(db, blk.id)
        assert "83.6" in geojson and "27.4" in geojson


def test_mid_edge_move_along_edge_single_feature(client, db):
    """A mid-edge vertex moved ALONG the shared segment keeps the geometry
    coincident → accepted WITHOUT shared_moves (R6 alone verifies)."""
    headers = _register(client)
    user = client.get("/api/auth/me", headers=headers).json()["id"]
    calc = _calc(db, user)
    a = _block(db, calc, box(83.2, 27.2, 83.5, 27.8), name="A", index=0)
    _block(db, calc, box(83.5, 27.2, 83.8, 27.8), name="B", index=1)
    db.expire_all()

    # A inserts a mid-edge vertex at (83.5,27.5) — on B's left segment — and
    # slides it ALONG the edge to (83.5,27.6).
    a_moved = {
        "type": "Polygon",
        "coordinates": [[
            [83.2, 27.2], [83.5, 27.2], [83.5, 27.6], [83.5, 27.8], [83.2, 27.8], [83.2, 27.2],
        ]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(a.id), "geometry": a_moved},
    )
    assert resp.status_code == 200, resp.text
    assert "shared_moves" not in resp.json() or not resp.json().get("updated_feature_ids") or len(resp.json().get("updated_feature_ids", [])) <= 1


def test_mid_edge_move_off_edge_rejected(client, db):
    """Moving a mid-edge shared vertex OFF the shared segment opens a gap →
    R6 rejects."""
    headers = _register(client)
    user = client.get("/api/auth/me", headers=headers).json()["id"]
    calc = _calc(db, user)
    a = _block(db, calc, box(83.2, 27.2, 83.5, 27.8), name="A", index=0)
    _block(db, calc, box(83.5, 27.2, 83.8, 27.8), name="B", index=1)
    db.expire_all()

    # push the mid-edge vertex OFF B's segment (into B's interior) → overlap
    a_moved = {
        "type": "Polygon",
        "coordinates": [[
            [83.2, 27.2], [83.5, 27.2], [83.55, 27.5], [83.5, 27.8], [83.2, 27.8], [83.2, 27.2],
        ]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(a.id), "geometry": a_moved},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "TOPOLOGY_REJECTED"


def test_shared_moves_gate_rejects_imported(client, db):
    """shared_moves is only valid for structural layers."""
    headers = _register(client)
    user = client.get("/api/auth/me", headers=headers).json()["id"]
    calc = _calc(db, user)
    _block(db, calc, box(83.2, 27.2, 83.5, 27.8), name="A", index=0)
    db.expire_all()

    from shapely.geometry import mapping as _mapping
    from app.utils.geometry_utils import compute_geometry_properties
    from app.models.workspace_layer import WorkspaceLayer

    target = {"type": "Feature", "geometry": _mapping(box(83.2, 27.2, 83.5, 27.5)),
              "properties": {"featureId": "imp-1", "name": "Imported"}}
    target["properties"].update(compute_geometry_properties(box(83.2, 27.2, 83.5, 27.5)))
    layer = WorkspaceLayer(
        calculation_id=calc.id, name="Imported Layer", purpose="custom",
        source_format="geojson", feature_count=1, geometry_types=["Polygon"],
        layer_data={"type": "FeatureCollection", "features": [target]},
        is_draft=False, created_by=user,
    )
    db.add(layer)
    db.commit()
    db.expire_all()

    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        headers=headers,
        json={
            "layer_type": "imported",
            "layer_id": layer.id,
            "feature_id": "imp-1",
            "geometry": _mapping(box(83.2, 27.2, 83.6, 27.5)),
            "shared_moves": [{"feature_id": "x", "geometry": {}}],
        },
    )
    assert resp.status_code == 400, resp.text


def test_shared_moves_malformed_rejected(client, db):
    headers = _register(client)
    user = client.get("/api/auth/me", headers=headers).json()["id"]
    calc = _calc(db, user)
    a = _block(db, calc, box(83.2, 27.2, 83.5, 27.8), name="A", index=0)
    b = _block(db, calc, box(83.5, 27.2, 83.8, 27.8), name="B", index=1)
    db.expire_all()

    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        headers=headers,
        json={
            "layer_type": "blocks",
            "feature_id": str(a.id),
            "geometry": _gj(box(83.2, 27.2, 83.5, 27.8)),
            "shared_moves": "not-a-list",
        },
    )
    assert resp.status_code == 400, resp.text

    resp2 = client.post(
        f"{_url(calc.id)}/edit-geometry",
        headers=headers,
        json={
            "layer_type": "blocks",
            "feature_id": str(a.id),
            "geometry": _gj(box(83.2, 27.2, 83.5, 27.8)),
            "shared_moves": [{"feature_id": str(b.id)}],  # missing geometry
        },
    )
    assert resp2.status_code == 400, resp2.text
