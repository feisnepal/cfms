"""A template can be renamed from "Untitled" without leaving review (owner request 2026-10-11)."""
from __future__ import annotations

import uuid

from app.models.op_template import OPTemplate


def _owner(client, db, prefix):
    from app.models.user import User

    email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "Tpl Tester"})
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, db.query(User).filter(User.email == email).first()


def _template(db, user, status):
    t = OPTemplate(name="शीर्षकविहीन टेम्प्लेट", description="", tree=[], created_by=user.id, status=status, is_system=False)
    db.add(t)
    db.commit()
    return t


def test_renaming_keeps_a_template_in_review(client, db):
    headers, user = _owner(client, db, "tplrename")
    t = _template(db, user, "in_review")
    resp = client.put(f"/api/operational-plans/templates/{t.id}", json={"name": "FMP revision brief"}, headers=headers)
    assert resp.status_code == 200, resp.text
    db.expire_all()
    fresh = db.get(OPTemplate, t.id)
    assert fresh.name == "FMP revision brief"
    assert fresh.status == "in_review"  # only editing the content tree sends a template back to draft


def test_someone_else_cannot_rename_it(client, db):
    _, owner = _owner(client, db, "tplowner")
    other_headers, _ = _owner(client, db, "tplother")
    t = _template(db, owner, "draft")
    resp = client.put(f"/api/operational-plans/templates/{t.id}", json={"name": "Mine now"}, headers=other_headers)
    assert resp.status_code == 403
    db.expire_all()
    assert db.get(OPTemplate, t.id).name == "शीर्षकविहीन टेम्प्लेट"
