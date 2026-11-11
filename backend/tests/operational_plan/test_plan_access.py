"""Who may open (and so edit) an operational plan: the forest's owner and a super admin, nobody else.

The plan page now gives every owner the document editor (owner, 2026-10-16), so this server rule is the only thing
between one user's plan and another user's edits.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.operational_plans import _check_calc_access
from app.models.user import UserRole


def _db(owner_id):
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(id=uuid4(), user_id=owner_id)
    return db


def _user(role=UserRole.USER):
    return SimpleNamespace(id=uuid4(), role=role)


def test_owner_may_open_the_plan():
    owner = _user()
    assert _check_calc_access(uuid4(), owner, _db(owner.id)) is not None


def test_another_user_may_not():
    owner, other = _user(), _user()
    with pytest.raises(HTTPException) as exc:
        _check_calc_access(uuid4(), other, _db(owner.id))
    assert exc.value.status_code == 403


def test_a_template_designer_is_not_a_second_owner():
    owner, designer = _user(), _user(UserRole.TEMPLATE_DESIGNER)
    with pytest.raises(HTTPException):
        _check_calc_access(uuid4(), designer, _db(owner.id))


def test_super_admin_may():
    owner, admin = _user(), _user(UserRole.SUPER_ADMIN)
    assert _check_calc_access(uuid4(), admin, _db(owner.id)) is not None


def test_checklist_before_a_plan_exists_is_the_same_gate_and_owner_only(client, auth_headers, db):
    from app.models.calculation import Calculation
    from app.models.user import User

    user = db.query(User).filter(User.email == "testuser@example.com").first()
    mine = Calculation(user_id=user.id, uploaded_filename="m.csv", forest_name="Mine")
    other = User(email="owner-of-other@example.com", hashed_password="x", full_name="O")
    db.add_all([mine, other])
    db.commit()
    theirs = Calculation(user_id=other.id, uploaded_filename="t.csv", forest_name="Theirs")
    db.add(theirs)
    db.commit()

    r = client.get(f"/api/operational-plans/calculation/{mine.id}/export-requirements", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ready"] is False and "sub_areas_planned" in [i["key"] for i in body["items"]]
    assert all(i["step"] for i in body["items"])

    r = client.get(f"/api/operational-plans/calculation/{theirs.id}/export-requirements", headers=auth_headers)
    assert r.status_code == 403
