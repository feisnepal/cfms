"""FS-4a.15 - POST /calculations/{id}/structure/preview-change (api/structure.py)."""

from __future__ import annotations

import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import box, mapping

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock


def _register(client):
    email = f"structpreview-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Struct Preview",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _calc(db, user_id, boundary=box(83.0, 27.0, 83.10, 27.10)):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name="Struct Preview Forest",
        boundary_geom=shp_wkt.dumps(boundary),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _block(db, calc, geom, name="Block 1", index=0, **kwargs):
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


def test_preview_change_with_no_downstream_data_is_all_zero(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _block(db, calc, geom=box(83.0, 27.0, 83.10, 27.10), division_level=1)
    db.expire_all()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/structure/preview-change",
        headers=headers,
        json={"feature_ids": [str(block.id)]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["affected_unit_ids"] == [str(block.id)]
    assert body["trees"] == {"at_risk": 0, "stays": 0, "moves": 0, "unassigned": 0}
    assert body["plots"] == {"at_risk": 0, "stays": 0, "moves": 0, "unassigned": 0}
    assert body["sampling_designs_affected"] == 0
    assert set(body["stale_domains"]) == {"analysis", "sampling", "field_inventory"}


def test_preview_change_with_new_geometry(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _block(db, calc, geom=box(83.0, 27.0, 83.10, 27.10), division_level=1)
    db.expire_all()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/structure/preview-change",
        headers=headers,
        json={
            "feature_ids": [str(block.id)],
            "new_geometry": mapping(box(83.0, 27.0, 83.05, 27.10)),
        },
    )
    assert resp.status_code == 200, resp.text


def test_preview_change_unknown_feature_id_404s(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    db.expire_all()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/structure/preview-change",
        headers=headers,
        json={"feature_ids": [str(uuid.uuid4())]},
    )
    assert resp.status_code == 404, resp.text


def test_preview_change_another_users_calc_is_403(client, db):
    headers1, uid1 = _register(client)
    calc = _calc(db, uid1)
    block = _block(db, calc, geom=box(83.0, 27.0, 83.10, 27.10), division_level=1)
    db.expire_all()

    headers2, _uid2 = _register(client)
    resp = client.post(
        f"/api/v1/calculations/{calc.id}/structure/preview-change",
        headers=headers2,
        json={"feature_ids": [str(block.id)]},
    )
    assert resp.status_code == 403, resp.text


def test_preview_change_missing_calc_is_404(client, db):
    headers, _uid = _register(client)
    resp = client.post(
        f"/api/v1/calculations/{uuid.uuid4()}/structure/preview-change",
        headers=headers,
        json={"feature_ids": [str(uuid.uuid4())]},
    )
    assert resp.status_code == 404, resp.text


def test_preview_change_empty_feature_ids_422s(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    db.expire_all()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/structure/preview-change",
        headers=headers,
        json={"feature_ids": []},
    )
    assert resp.status_code == 422, resp.text
