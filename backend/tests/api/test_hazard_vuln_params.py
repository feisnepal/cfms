"""Per-forest landslide-hazard / household-vuln parameter override API (P8).

GET/PATCH/DELETE ``/calculations/{id}/hazard-vuln-params`` — these only touch
``calculation.result_data`` (no rasters), so they run against the test DB.
"""

from __future__ import annotations

import uuid

from app.models.calculation import Calculation
from app.models.user import User


def _owner(client, db):
    email = f"hv-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "HV"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    user = db.query(User).filter(User.email == email).first()
    return headers, user


def _calc(db, user):
    c = Calculation(user_id=user.id, forest_name=f"HV CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()
    return c


def test_get_returns_defaults_and_provenance(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.get(f"/api/calculations/{c.id}/hazard-vuln-params", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["params"]["landslide"]["method"] == "weighted_overlay"
    assert body["customised"] is False
    assert set(body["provenance"].values()) == {"default"}


def test_patch_persists_and_flips_provenance(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.patch(
        f"/api/calculations/{c.id}/hazard-vuln-params",
        headers=headers,
        json={"household": {"top_n": 25}, "landslide": {"prone_class_min": 3}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["params"]["household"]["top_n"] == 25
    assert body["params"]["landslide"]["prone_class_min"] == 3
    assert body["customised"] is True
    assert body["provenance"]["household"] == "forest"
    assert body["provenance"]["landslide"] == "forest"
    assert body["provenance"]["factor_of_safety"] == "default"

    db.refresh(c)
    assert c.result_data["hazard_vuln_params"]["household"]["top_n"] == 25


def test_patch_invalid_is_422_and_not_stored(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.patch(
        f"/api/calculations/{c.id}/hazard-vuln-params",
        headers=headers,
        json={"factor_of_safety": {"fs_class_breaks": [1.5, 1.0]}},  # not increasing
    )
    assert r.status_code == 422
    db.refresh(c)
    assert not (c.result_data or {}).get("hazard_vuln_params")


def test_delete_reverts_to_default(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    client.patch(
        f"/api/calculations/{c.id}/hazard-vuln-params",
        headers=headers,
        json={"landslide": {"twi_high_percentile": 90.0}},
    )
    r = client.delete(f"/api/calculations/{c.id}/hazard-vuln-params", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["customised"] is False
    db.refresh(c)
    assert not (c.result_data or {}).get("hazard_vuln_params")


def test_other_user_gets_403(client, db):
    headers_a, user_a = _owner(client, db)
    c = _calc(db, user_a)
    headers_b, _ = _owner(client, db)
    r = client.get(f"/api/calculations/{c.id}/hazard-vuln-params", headers=headers_b)
    assert r.status_code == 403
