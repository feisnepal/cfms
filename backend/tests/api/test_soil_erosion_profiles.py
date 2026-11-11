"""Org-wide RUSLE parameter presets — super-admin API (P7)."""

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
    r = client.get("/api/admin/soil-erosion-profiles", headers=_norm(client, db))
    assert r.status_code == 403


def test_seeded_profiles_present(client, db):
    r = client.get("/api/admin/soil-erosion-profiles", headers=_super(client, db))
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
        "params": {"ls_method": "desmet_govers", "sdr_enabled": True},
        "sort_order": 99,
    }
    r = client.put("/api/admin/soil-erosion-profiles/test_dun", headers=h, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["params"]["ls_method"] == "desmet_govers"

    g = client.get("/api/admin/soil-erosion-profiles/test_dun", headers=h)
    assert g.status_code == 200
    assert g.json()["params"]["sdr_enabled"] is True
    assert g.json()["sort_order"] == 99


def test_put_invalid_params_is_422(client, db):
    h = _super(client, db)
    r = client.put(
        "/api/admin/soil-erosion-profiles/bad",
        headers=h,
        json={
            "label_ne": "x",
            "label_en": "x",
            "params": {"severity_breaks": [40, 20, 10]},
        },
    )
    assert r.status_code == 422
    assert (
        client.get("/api/admin/soil-erosion-profiles/bad", headers=h).status_code == 404
    )


def test_delete(client, db):
    h = _super(client, db)
    client.put(
        "/api/admin/soil-erosion-profiles/tmp",
        headers=h,
        json={"label_ne": "x", "label_en": "x", "params": {}},
    )
    d = client.delete("/api/admin/soil-erosion-profiles/tmp", headers=h)
    assert d.status_code == 200 and d.json()["deleted"] == "tmp"
    assert (
        client.get("/api/admin/soil-erosion-profiles/tmp", headers=h).status_code == 404
    )


# ── resolver: the profile layer merges between defaults and the per-forest patch
def test_resolve_params_applies_the_profile_layer(monkeypatch):
    from app.services.operational_plan import soil_erosion_config as cfg

    monkeypatch.setattr(cfg, "_load_global_profile", lambda db, cid: {"ls_cap": 45.0})
    monkeypatch.setattr(
        cfg, "_load_forest_override", lambda db, cid: {"tolerable_soil_loss": 7.0}
    )
    p = cfg.resolve_params(db=None, calculation_id=None)
    assert p.ls_cap == 45.0  # from the profile
    assert p.tolerable_soil_loss == 7.0  # from the per-forest override
    assert p.r_method == "mfi"  # untouched → code default
    assert p._provenance["ls_cap"] == "profile"
    assert p._provenance["tolerable_soil_loss"] == "forest"
