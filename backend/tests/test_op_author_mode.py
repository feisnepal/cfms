"""Author Mode — template-test plans keep {{tokens}} verbatim.

OP_TEMPLATE_MANAGEMENT_PLAN.md §3.2 / T3:
  - POST /operational-plans?authoring=true (designer / super admin only) skips
    auto-population and flags the plan template_test.
  - POST /{plan_id}/auto-populate refuses an author-mode plan.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.calculation import Calculation
from app.models.user import User, UserRole

PREFIX = "/api/v1/operational-plans"
_PW = "TestPass123!"


def _uniq(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:10]}@example.com"


def _user(client, db, role=UserRole.USER, prefix="u"):
    email = _uniq(prefix)
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": _PW, "full_name": "Tester"},
    )
    assert r.status_code in (200, 201), r.text
    u = db.query(User).filter(User.email == email).first()
    if role != UserRole.USER:
        u.role = role
        db.commit()
    lr = client.post("/api/auth/login", json={"email": email, "password": _PW})
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}, u


def _calc(db, user_id) -> str:
    c = Calculation(user_id=user_id, forest_name=f"CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()
    return str(c.id)


def _tokens_in_tree(tree: list) -> bool:
    for n in tree or []:
        if "{{" in (n.get("content") or ""):
            return True
        if _tokens_in_tree(n.get("children") or []):
            return True
    return False


def test_designer_author_mode_keeps_tokens(client, db):
    headers, u = _user(client, db, UserRole.TEMPLATE_DESIGNER, "designer")
    calc_id = _calc(db, u.id)

    r = client.post(
        f"{PREFIX}?authoring=true",
        json={"calculation_id": calc_id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["plan_metadata"].get("authoring") is True
    assert body["plan_metadata"].get("template_test") is True
    assert not body["plan_metadata"].get("auto_populated")
    assert _tokens_in_tree(body["tree"]), "author-mode tree should still hold {{tokens}}"


def test_plain_user_cannot_enter_author_mode(client, db):
    headers, u = _user(client, db, UserRole.USER, "plain")
    calc_id = _calc(db, u.id)

    r = client.post(
        f"{PREFIX}?authoring=true",
        json={"calculation_id": calc_id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert not r.json()["plan_metadata"].get("authoring")


def test_auto_populate_refuses_author_mode_plan(client, db):
    headers, u = _user(client, db, UserRole.SUPER_ADMIN, "super")
    calc_id = _calc(db, u.id)

    cr = client.post(
        f"{PREFIX}?authoring=true",
        json={"calculation_id": calc_id},
        headers=headers,
    )
    assert cr.status_code == 201, cr.text
    pid = cr.json()["id"]

    r = client.post(f"{PREFIX}/{pid}/auto-populate", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "authoring_plan"


def test_auto_populate_still_works_for_a_normal_plan(client, db):
    headers, u = _user(client, db, UserRole.SUPER_ADMIN, "super")
    calc_id = _calc(db, u.id)

    cr = client.post(
        f"{PREFIX}", json={"calculation_id": calc_id}, headers=headers
    )
    assert cr.status_code == 201, cr.text
    pid = cr.json()["id"]

    r = client.post(f"{PREFIX}/{pid}/auto-populate", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["plan_metadata"]["auto_populated"] is True
