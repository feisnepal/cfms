"""Coverage for the OP export endpoint's real HTTP branches (H4.2).

`export_operational_plan` mints a verification code, hashes the finished bytes
and records the issuance -- but no test ever drove the route, so the mint call,
the hashing/`record_issuance` call and the StreamingResponse were uncovered.
The document build itself is a heavy multi-hundred-line flow, so it is stubbed;
everything else is the genuine endpoint code.
"""
from __future__ import annotations

import uuid
from io import BytesIO

from app.models.calculation import Calculation
from app.models.operational_plan import OperationalPlan
from app.api import operational_plans as api_mod


def _owner(client, db, prefix):
    from app.models.user import User

    email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "OP Tester",
    })
    resp = client.post("/api/auth/login", json={
        "email": email, "password": "TestPass123!",
    })
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    user = db.query(User).filter(User.email == email).first()
    return headers, user


def _seed_plan(db, user_id):
    c = Calculation(user_id=user_id, forest_name=f"OP Export CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.flush()
    p = OperationalPlan(calculation_id=c.id, forest_name=c.forest_name)
    db.add(p)
    db.commit()
    return c.id, p.id


def test_export_refused_until_mandatory_steps_complete(client, db):
    """Owner rule 2026-10-10: an incomplete forest gets a 409 naming every unfinished step."""
    headers, user = _owner(client, db, "expgate")
    _calc_id, plan_id = _seed_plan(db, user.id)

    resp = client.get(f"/api/operational-plans/{plan_id}/export", headers=headers)
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "EXPORT_REQUIREMENTS_INCOMPLETE"
    keys = {i["key"] for i in detail["items"]}
    assert {"raster", "sampling", "field_inventory", "biodiversity", "households",
            "yearly_activities", "cba", "committee", "metadata"} <= keys

    req = client.get(f"/api/operational-plans/{plan_id}/export-requirements", headers=headers)
    assert req.status_code == 200 and req.json()["ready"] is False


def test_export_mints_hashes_and_records_issuance(client, db, monkeypatch):
    headers, user = _owner(client, db, "exp")
    calc_id, plan_id = _seed_plan(db, user.id)

    monkeypatch.setattr(
        api_mod, "build_op_document",
        lambda *a, **k: BytesIO(b"PK\x03\x04 fake-op-docx bytes"),
    )
    # The mandatory-steps gate has its own test below; this one is about minting.
    monkeypatch.setattr(
        "app.services.operational_plan.export_requirements.assert_export_ready",
        lambda *a, **k: None,
    )

    resp = client.get(
        f"/api/operational-plans/{plan_id}/export", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Verification-Code")
    assert resp.headers.get("X-Document-SHA256")
    assert resp.content.startswith(b"PK\x03\x04")

    from sqlalchemy import text
    rec = db.execute(text(
        "SELECT verification_code FROM document_issuances "
        "WHERE plan_id = CAST(:p AS uuid)"),
        {"p": str(plan_id)}).first()
    assert rec is not None, "issuance was recorded"
    assert rec[0] == resp.headers["X-Verification-Code"]
