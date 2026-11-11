"""Org-wide landslide-hazard + household-vuln presets — super-admin API (P8)."""

from __future__ import annotations

import uuid

from app.models.user import User, UserRole


def _register(client, email: str) -> str:
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Tester"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _login(client, email: str) -> dict:
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _norm(client, db):
    email = f"p-{uuid.uuid4().hex[:8]}@example.com"
    _register(client, email)
    return _login(client, email)


def _super(client, db):
    email = f"s-{uuid.uuid4().hex[:8]}@example.com"
    uid = _register(client, email)
    user = db.query(User).filter(User.id == uid).first()
    user.role = UserRole.SUPER_ADMIN
    db.commit()
    return _login(client, email)


def test_non_super_admin_is_403(client, db):
    r = client.get("/api/admin/hazard-vuln-profiles", headers=_norm(client, db))
    assert r.status_code == 403


def test_seeded_profiles_present(client, db):
    r = client.get("/api/admin/hazard-vuln-profiles", headers=_super(client, db))
    assert r.status_code == 200, r.text
    keys = {p["key"] for p in r.json()}
    assert {"terai", "chure", "mid_hill", "high_mountain"} <= keys
    chure = next(p for p in r.json() if p["key"] == "chure")
    assert chure["physiography_hint"] == "Chure Hillslopes"
    assert chure["params"] == {}  # seeded empty


def test_put_upsert_and_get_roundtrip(client, db):
    h = _super(client, db)
    body = {
        "label_ne": "परीक्षण",
        "label_en": "Test",
        "physiography_hint": "Dun",
        "params": {
            "landslide": {"method": "ahp"},
            "factor_of_safety": {"saturation_ratio_m": 0.9},
        },
        "sort_order": 99,
    }
    r = client.put("/api/admin/hazard-vuln-profiles/test_dun", headers=h, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["params"]["landslide"]["method"] == "ahp"

    g = client.get("/api/admin/hazard-vuln-profiles/test_dun", headers=h)
    assert g.status_code == 200
    assert g.json()["params"]["factor_of_safety"]["saturation_ratio_m"] == 0.9
    assert g.json()["sort_order"] == 99


def test_put_invalid_params_is_422(client, db):
    h = _super(client, db)
    r = client.put(
        "/api/admin/hazard-vuln-profiles/bad",
        headers=h,
        json={
            "label_ne": "x",
            "label_en": "x",
            "params": {"factor_of_safety": {"fs_class_breaks": [1.5, 1.0]}},
        },
    )
    assert r.status_code == 422
    assert (
        client.get("/api/admin/hazard-vuln-profiles/bad", headers=h).status_code == 404
    )


def test_delete(client, db):
    h = _super(client, db)
    client.put(
        "/api/admin/hazard-vuln-profiles/tmp",
        headers=h,
        json={"label_ne": "x", "label_en": "x", "params": {}},
    )
    d = client.delete("/api/admin/hazard-vuln-profiles/tmp", headers=h)
    assert d.status_code == 200 and d.json()["deleted"] == "tmp"
    assert (
        client.get("/api/admin/hazard-vuln-profiles/tmp", headers=h).status_code == 404
    )


def test_resolve_params_applies_the_profile_layer(monkeypatch):
    from app.services.operational_plan import hazard_vuln_config as cfg

    monkeypatch.setattr(
        cfg,
        "_load_global_profile",
        lambda db, cid: {"factor_of_safety": {"saturation_ratio_m": 0.85}},
    )
    monkeypatch.setattr(
        cfg,
        "_load_forest_override",
        lambda db, cid: {"household": {"top_n": 25}},
    )
    p = cfg.resolve_params(db=None, calculation_id=None)
    assert p.factor_of_safety.saturation_ratio_m == 0.85  # from the profile
    assert p.household.top_n == 25  # from the per-forest override
    assert p.landslide.method == "weighted_overlay"  # untouched → code default
    assert p._provenance["factor_of_safety"] == "profile"
    assert p._provenance["household"] == "forest"
