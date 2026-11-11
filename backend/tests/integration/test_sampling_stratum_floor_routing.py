"""SS-1.4: endpoint-level proof that a below-floor SFM कार्यविधि §16 sampling
request is rejected with the bilingual registry message ({code, message,
message_np}) naming the unit and its floor, for BOTH engines and BOTH the
create and preview endpoints (D1/D2). The service-level payload shape
({unit, stratum, floor, value}) is already covered by
test_stratum_sampling_enforcement.py (guideline engine) and
test_stratum_sampling_manual_engine.py (manual engine); this file proves the
same ValueError survives HTTPException + resolve_service_detail unchanged.
"""

import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock

BOUNDARY = box(83.4, 27.4, 83.6, 27.6)


def _register(client):
    email = f"floor-route-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Floor Route"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _calc_with_production_block(db, user_id, forest_name="Floor Route Forest"):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name=forest_name,
        boundary_geom=shp_wkt.dumps(BOUNDARY),
        is_draft=True,
        result_data={},
    )
    db.add(calc)
    db.add(
        ForestBlock(
            id=uuid.uuid4(),
            calculation_id=calc.id,
            name="Prod-1",
            block_name="Prod-1",
            compartment_code=None,
            geometry=shp_wkt.dumps(BOUNDARY.buffer(-0.01)),
            area_hectares=5.0,
            index=0,
            is_compartment=False,
            division_level=1,
        )
    )
    db.commit()
    db.refresh(calc)
    return calc


def _me_id(client, headers):
    return client.get("/api/auth/me", headers=headers).json()["id"]


def test_manual_engine_below_floor_returns_bilingual_400(client, db):
    """Manual/intensity engine: 1.0% on a (default) production block, floor 2.0%."""
    headers = _register(client)
    calc = _calc_with_production_block(db, _me_id(client, headers))

    resp = client.post(
        f"/api/calculations/{calc.id}/sampling/create",
        json={
            "sampling_method": "manual",
            "sampling_type": "systematic",
            "sampling_intensity_percent": 1.0,
        },
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "sampling.intensity_below_floor"
    assert "Prod-1" in detail["message"]
    assert "2.0" in detail["message"]
    assert "Prod-1" in detail["message_np"]
    assert detail["message_np"] != detail["message"]


def test_guideline_engine_below_floor_returns_same_shape(client, db):
    """Guideline-2061 engine hits the identical registry code/shape."""
    headers = _register(client)
    calc = _calc_with_production_block(db, _me_id(client, headers))

    resp = client.post(
        f"/api/calculations/{calc.id}/sampling/create",
        json={
            "sampling_method": "guideline_2061",
            "productive_intensity": "1.0",
            "plot_size_sqm": 500,
        },
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "sampling.intensity_below_floor"
    assert "Prod-1" in detail["message"]
    assert "2.0" in detail["message"]


def test_preview_matches_create_for_below_floor(client, db):
    """The preview endpoint (rule F) enforces the identical floor as create —
    same shared service function, same 400 shape."""
    headers = _register(client)
    calc = _calc_with_production_block(db, _me_id(client, headers))

    body = {
        "sampling_method": "manual",
        "sampling_type": "systematic",
        "sampling_intensity_percent": 1.0,
    }

    create_resp = client.post(
        f"/api/calculations/{calc.id}/sampling/create", json=body, headers=headers
    )
    preview_resp = client.post(
        f"/api/calculations/{calc.id}/sampling/preview", json=body, headers=headers
    )

    assert create_resp.status_code == 400, create_resp.text
    assert preview_resp.status_code == 400, preview_resp.text
    assert create_resp.json()["detail"]["code"] == preview_resp.json()["detail"]["code"]
    assert (
        create_resp.json()["detail"]["message"]
        == preview_resp.json()["detail"]["message"]
    )
