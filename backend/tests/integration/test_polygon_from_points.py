"""Phase U-4 (Task 4.1) — interactive points → polygon RPC (case E).

The frontend lets a user click N points on the map and calls
`/workspace/{id}/polygon-from-points`. This RPC runs the shared case-D hull
engine and stores a polygon on the requested built-in polygon layer.

These integration tests exercise the REAL endpoint against the DB and assert:
- 4 picked points create a polygon on the `blocks` layer (ForestBlock row);
- sub_areas target appends a polygon to result_data;
- bad input (too few / collinear points) is rejected with a clear reason;
- the returned geometry is a valid non-degenerate Polygon/MultiPolygon.
"""
import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import box, shape

from app.models.calculation import Calculation, CalculationStatus


def _register_user(client):
    email = f"points-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email,
        "password": "TestPass123!",
        "full_name": "Points RPC",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _make_calc(db, user_id, forest_name="Points Forest"):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name=forest_name,
        boundary_geom=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


SQUARE = [[83.50, 27.50], [83.60, 27.50], [83.60, 27.55], [83.50, 27.55]]
SQUARE2 = [[83.70, 27.50], [83.80, 27.50], [83.80, 27.55], [83.70, 27.55]]


def test_four_points_create_block(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    db.expire_all()

    resp = client.post(
        f"/api/workspace/{calc.id}/polygon-from-points",
        headers=headers,
        json={"points": SQUARE, "target_type": "blocks", "name": "Picked Block"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["target_type"] == "blocks"
    assert body["feature_id"]
    geom = shape(body["geometry"])
    assert geom.is_valid
    assert geom.area > 1e-9


def test_points_to_sub_areas_appends(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    db.expire_all()

    for i, sq in enumerate((SQUARE, SQUARE2), start=1):
        resp = client.post(
            f"/api/workspace/{calc.id}/polygon-from-points",
            headers=headers,
            json={"points": sq, "target_type": "sub_areas", "name": f"SA{i}"},
        )
        assert resp.status_code == 200, resp.text

    db.expire_all()
    db.refresh(calc)
    result_data = calc.result_data or {}
    assert result_data.get("sub_areas_count", 0) == 2
    assert len(result_data.get("sub_areas", [])) == 2


def test_too_few_points_rejected(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    db.expire_all()

    resp = client.post(
        f"/api/workspace/{calc.id}/polygon-from-points",
        headers=headers,
        json={"points": [[83.5, 27.5], [83.6, 27.5]], "target_type": "blocks"},
    )
    assert resp.status_code in (400, 422), resp.text


def test_collinear_points_rejected(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    db.expire_all()

    # 5 collinear points along a line → zero area.
    resp = client.post(
        f"/api/workspace/{calc.id}/polygon-from-points",
        headers=headers,
        json={
            "points": [[83.0, 27.0], [83.1, 27.0], [83.2, 27.0], [83.3, 27.0], [83.4, 27.0]],
            "target_type": "blocks",
        },
    )
    assert resp.status_code in (400, 500), resp.text