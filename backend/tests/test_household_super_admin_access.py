"""Household data belongs to whoever uploaded it (owner rule 2026-10-07).

The owner has full control; no other general user can reach it; a super admin can do whatever the owner can, on any forest - and
that access is on the record under the super admin's own account.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.models.user import User, UserRole, UserStatus
from app.utils.auth import hash_password

PASSWORD = "TestPass123!"


def _user(db, role=UserRole.USER):
    u = User(
        email=f"hh-{role.value}-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password(PASSWORD),
        full_name="Household Tester", role=role, status=UserStatus.ACTIVE,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _headers(client, user):
    r = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def forest(db):
    """A forest owned by a general user, with one household."""
    owner = _user(db)
    calc_id = uuid.uuid4()
    db.execute(text("INSERT INTO calculations (id, user_id, forest_name, status) VALUES (:id, :u, 'Owner Forest', 'PROCESSING')"),
               {"id": calc_id, "u": owner.id})
    hh = uuid.uuid4()
    db.execute(text("INSERT INTO household_information (id, calculation_id, house_no, surname, female_count, male_count, created_by, version) "
                    "VALUES (:id, :c, 1, 'Shrestha', 2, 3, :u, 0)"), {"id": hh, "c": calc_id, "u": owner.id})
    db.commit()
    return {"owner": owner, "calc_id": calc_id, "household_id": hh}


def _list(client, h, calc_id):
    return client.get(f"/api/household/calculations/{calc_id}/households", headers=h)


def test_the_owner_has_full_access(client, db, forest):
    r = _list(client, _headers(client, forest["owner"]), forest["calc_id"])
    assert r.status_code == 200 and len(r.json()) == 1


def test_another_general_user_gets_nothing(client, db, forest):
    stranger = _user(db)
    r = _list(client, _headers(client, stranger), forest["calc_id"])
    assert r.status_code == 404  # the forest is not even revealed
    assert client.get(f"/api/household/calculations/{forest['calc_id']}/summary-entry", headers=_headers(client, stranger)).status_code == 404


def test_an_org_admin_is_not_the_super_admin(client, db, forest):
    org_admin = _user(db, UserRole.ORG_ADMIN)
    assert _list(client, _headers(client, org_admin), forest["calc_id"]).status_code == 404


def test_a_super_admin_can_read_any_forests_households(client, db, forest):
    admin = _user(db, UserRole.SUPER_ADMIN)
    h = _headers(client, admin)
    r = _list(client, h, forest["calc_id"])
    assert r.status_code == 200 and len(r.json()) == 1
    assert client.get(f"/api/household/calculations/{forest['calc_id']}/summary-entry", headers=h).status_code == 200


def test_a_super_admins_read_is_logged_under_the_super_admin(client, db, forest):
    admin = _user(db, UserRole.SUPER_ADMIN)
    _list(client, _headers(client, admin), forest["calc_id"])
    who = db.execute(text("SELECT DISTINCT user_id FROM household_access_log WHERE calculation_id = :c"), {"c": forest["calc_id"]}).scalars().all()
    assert [str(w) for w in who] == [str(admin.id)]


def test_a_super_admin_can_also_write_where_the_owner_can(client, db, forest):
    admin = _user(db, UserRole.SUPER_ADMIN)
    r = client.put(
        f"/api/household/calculations/{forest['calc_id']}/summary-entry",
        json={"total_households": 5, "total_population": 20}, headers=_headers(client, admin),
    )
    # 409 "this forest already has household-wise data" is the business rule answering: the access rule let the super admin in
    assert r.status_code == 409 and r.status_code not in (403, 404), r.text


def test_a_forest_that_does_not_exist_is_a_404_for_everyone(client, db):
    admin = _user(db, UserRole.SUPER_ADMIN)
    assert _list(client, _headers(client, admin), uuid.uuid4()).status_code == 404
