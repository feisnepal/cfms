"""Per-forest RUSLE parameter override API (P2).

GET/PATCH/DELETE ``/calculations/{id}/soil-erosion-params`` — these only touch
``calculation.result_data`` (no rasters), so they run against the test DB.
"""

from __future__ import annotations

import uuid

from app.models.calculation import Calculation
from app.models.user import User


def _owner(client, db):
    email = f"se-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "SE"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    user = db.query(User).filter(User.email == email).first()
    return headers, user


def _calc(db, user):
    c = Calculation(user_id=user.id, forest_name=f"SE CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()
    return c


def test_get_returns_defaults_and_provenance(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.get(f"/api/calculations/{c.id}/soil-erosion-params", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["params"]["r_method"] == "mfi"
    assert body["customised"] is False
    assert set(body["provenance"].values()) == {"default"}


def test_patch_persists_and_flips_provenance(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.patch(
        f"/api/calculations/{c.id}/soil-erosion-params",
        headers=headers,
        json={"slope_length_cap_m": 60.0, "tolerable_soil_loss": 7.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["params"]["slope_length_cap_m"] == 60.0
    assert body["params"]["tolerable_soil_loss"] == 7.0
    assert body["customised"] is True
    assert body["provenance"]["slope_length_cap_m"] == "forest"
    assert body["provenance"]["r_method"] == "default"

    db.refresh(c)
    assert c.result_data["soil_erosion_params"]["slope_length_cap_m"] == 60.0


def test_patch_invalid_is_422_and_not_stored(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.patch(
        f"/api/calculations/{c.id}/soil-erosion-params",
        headers=headers,
        json={"severity_breaks": [40, 20, 10]},  # not increasing
    )
    assert r.status_code == 422
    db.refresh(c)
    assert not (c.result_data or {}).get("soil_erosion_params")


def test_delete_reverts_to_default(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    client.patch(
        f"/api/calculations/{c.id}/soil-erosion-params",
        headers=headers,
        json={"k_method": "williams", "slope_length_cap_m": 80.0},
    )
    r = client.delete(f"/api/calculations/{c.id}/soil-erosion-params", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["customised"] is False
    db.refresh(c)
    assert not (c.result_data or {}).get("soil_erosion_params")


def test_other_user_gets_403(client, db):
    headers_a, user_a = _owner(client, db)
    c = _calc(db, user_a)
    headers_b, _ = _owner(client, db)
    r = client.get(f"/api/calculations/{c.id}/soil-erosion-params", headers=headers_b)
    assert r.status_code == 403
