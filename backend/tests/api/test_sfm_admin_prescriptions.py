"""The अनुसूची-१ as editable data — super-admin API (SUSTAINABLE_FOREST_MANAGEMENT_PLAN P7)."""

from __future__ import annotations

import copy
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
        client.get("/api/admin/sfm-prescriptions", headers=_norm(client)).status_code
        == 403
    )


def test_list_returns_the_14_seeded_rows(client, db):
    r = client.get("/api/admin/sfm-prescriptions", headers=_super(client, db))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 14
    assert {row["type_no"] for row in rows} == set(range(1, 15))
    t1 = next(x for x in rows if x["type_no"] == 1)
    assert "adequate" in t1["branches"]
    assert t1["branches"]["adequate"]["method"] == "selection_felling_cycle"


def test_put_retunes_a_yield_step_and_the_engine_picks_it_up(client, db):
    """A successful PUT hits the shared seeded row — restore it in ``finally``
    so the yield / seed tests that also read row 1 are not perturbed."""
    from app.services.sustainable_fm.prescription import load_prescriptions
    from app.services.sustainable_fm.yield_regulation import match_step

    h = _super(client, db)
    original = client.get("/api/admin/sfm-prescriptions/1", headers=h).json()
    restore = copy.deepcopy(original)
    restore.pop("type_no")

    try:
        body = copy.deepcopy(original)
        body.pop("type_no")
        # bump the top step from 2.0 % to 2.5 %
        body["branches"]["adequate"]["yield_rules"]["steps"][0]["pct"] = 2.5

        p = client.put("/api/admin/sfm-prescriptions/1", headers=h, json=body)
        assert p.status_code == 200, p.text
        assert (
            p.json()["branches"]["adequate"]["yield_rules"]["steps"][0]["pct"] == 2.5
        )

        # the yield engine reads the live row — no rebuild plumbing needed here
        db.expire_all()
        fresh = load_prescriptions(db)[1]
        steps = fresh.branches["adequate"]["yield_rules"]["steps"]
        assert match_step(steps, 250.0) == 2.5
    finally:
        client.put("/api/admin/sfm-prescriptions/1", headers=h, json=restore)
        db.expire_all()


def test_put_with_overlapping_steps_is_422(client, db):
    h = _super(client, db)
    row = client.get("/api/admin/sfm-prescriptions/1", headers=h).json()
    body = copy.deepcopy(row)
    body.pop("type_no")
    body["branches"]["adequate"]["yield_rules"]["steps"] = [
        {"gs_per_ha_min": 150, "gs_per_ha_max": None, "pct": 2.0},
        {"gs_per_ha_min": 100, "gs_per_ha_max": 200, "pct": 1.0},  # overlaps
    ]
    r = client.put("/api/admin/sfm-prescriptions/1", headers=h, json=body)
    assert r.status_code == 422
    assert "overlap" in r.text.lower()


def test_put_with_bad_method_or_basis_is_422(client, db):
    h = _super(client, db)
    row = client.get("/api/admin/sfm-prescriptions/1", headers=h).json()

    bad_method = copy.deepcopy(row)
    bad_method.pop("type_no")
    bad_method["branches"]["adequate"]["method"] = "clearfell"
    assert (
        client.put(
            "/api/admin/sfm-prescriptions/1", headers=h, json=bad_method
        ).status_code
        == 422
    )

    bad_basis = copy.deepcopy(row)
    bad_basis.pop("type_no")
    bad_basis["branches"]["adequate"]["yield_rules"]["basis"] = "vibes"
    assert (
        client.put(
            "/api/admin/sfm-prescriptions/1", headers=h, json=bad_basis
        ).status_code
        == 422
    )


def test_get_unknown_type_no_is_404(client, db):
    h = _super(client, db)
    assert client.get("/api/admin/sfm-prescriptions/99", headers=h).status_code == 404
