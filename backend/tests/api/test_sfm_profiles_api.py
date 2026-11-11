"""Org-wide SFM parameter presets — super-admin API (SUSTAINABLE_FOREST_MANAGEMENT_PLAN P7)."""

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


def _norm(client) -> dict:
    email = f"p-{uuid.uuid4().hex[:8]}@example.com"
    _register(client, email)
    return _login(client, email)


def _super(client, db) -> dict:
    email = f"s-{uuid.uuid4().hex[:8]}@example.com"
    uid = _register(client, email)
    user = db.query(User).filter(User.id == uid).first()
    user.role = UserRole.SUPER_ADMIN
    db.commit()
    return _login(client, email)


def test_non_super_admin_is_403(client, db):
    assert (
        client.get("/api/admin/sfm-profiles", headers=_norm(client)).status_code == 403
    )


def test_seeded_profiles_present(client, db):
    r = client.get("/api/admin/sfm-profiles", headers=_super(client, db))
    assert r.status_code == 200, r.text
    keys = {p["key"] for p in r.json()}
    assert {"terai", "chure", "mid_hill", "high_mountain"} <= keys
    for p in r.json():
        assert p["params"] == {}  # seeded empty


def test_put_upsert_get_and_delete_roundtrip(client, db):
    h = _super(client, db)
    body = {
        "label_ne": "परीक्षण",
        "label_en": "Test",
        "physiography_hint": "Dun",
        "params": {"seedling_threshold": 4000, "harvestable_dbh_min_cm": 30.0},
        "sort_order": 99,
    }
    r = client.put("/api/admin/sfm-profiles/test_dun", headers=h, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["params"]["seedling_threshold"] == 4000

    g = client.get("/api/admin/sfm-profiles/test_dun", headers=h)
    assert g.json()["params"]["harvestable_dbh_min_cm"] == 30.0
    assert g.json()["sort_order"] == 99

    d = client.delete("/api/admin/sfm-profiles/test_dun", headers=h)
    assert d.status_code == 200 and d.json()["deleted"] == "test_dun"
    assert client.get("/api/admin/sfm-profiles/test_dun", headers=h).status_code == 404


def test_put_invalid_params_is_422_and_not_persisted(client, db):
    h = _super(client, db)
    for bad in (
        {"harvestable_dbh_min_cm": -1},  # out of range
        {"not_a_real_key": 1},  # extra='forbid'
        {"protection_slope_band": 9},  # 1..4
    ):
        r = client.put(
            "/api/admin/sfm-profiles/bad",
            headers=h,
            json={"label_ne": "x", "label_en": "x", "params": bad},
        )
        assert r.status_code == 422, (bad, r.text)
    assert client.get("/api/admin/sfm-profiles/bad", headers=h).status_code == 404


def test_resolve_params_applies_the_profile_layer(monkeypatch):
    from app.services.sustainable_fm import sfm_config as cfg

    monkeypatch.setattr(
        cfg, "_load_global_profile", lambda db, cid: {"crown_density_default": 40}
    )
    monkeypatch.setattr(
        cfg,
        "_load_forest_override",
        lambda db, cid: {"seedling_threshold": 4500},
    )
    p = cfg.resolve_params(db=None, calculation_id=None)
    assert p.crown_density_default == 40  # from the profile
    assert p.seedling_threshold == 4500  # from the per-forest override
    assert p.harvestable_dbh_min_cm == 40.0  # untouched → code default
    assert p._provenance["crown_density_default"] == "profile"
    assert p._provenance["seedling_threshold"] == "forest"
