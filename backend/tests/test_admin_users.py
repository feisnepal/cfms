"""Super-admin user panel: only a super admin sees it, can give a role, never to themselves, and every change is logged."""
import uuid

import pytest

from app.models.user import User, UserRole
from app.models.user_role_change import UserRoleChange


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _register(client, email: str) -> str:
    r = client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "Tester"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _login(client, email: str) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user_with_role(client, db, role: UserRole):
    email = _uniq(role.value)
    uid = _register(client, email)
    u = db.query(User).filter(User.id == uid).first()
    u.role = role
    db.commit()
    return uid, _login(client, email)


@pytest.fixture()
def admin(client, db):
    uid, headers = _user_with_role(client, db, UserRole.SUPER_ADMIN)
    return uid, headers


@pytest.mark.parametrize("role", [UserRole.USER, UserRole.ORG_ADMIN, UserRole.TEMPLATE_DESIGNER])
def test_only_a_super_admin_may_use_the_panel(client, db, role):
    _uid, headers = _user_with_role(client, db, role)
    assert client.get("/api/admin/users", headers=headers).status_code == 403
    assert client.get("/api/admin/users/roles", headers=headers).status_code == 403
    target = _register(client, _uniq("t"))
    assert client.patch(f"/api/admin/users/{target}/role", json={"role": "template_designer"}, headers=headers).status_code == 403


def test_anonymous_is_refused(client):
    assert client.get("/api/admin/users").status_code == 401


def test_the_role_list_comes_from_the_enum(client, admin):
    r = client.get("/api/admin/users/roles", headers=admin[1])
    assert r.status_code == 200
    assert {x["value"] for x in r.json()} == {role.value for role in UserRole}  # a role added to the enum appears with no other change
    designer = next(x for x in r.json() if x["value"] == "template_designer")
    assert "template" in designer["description"].lower()


def test_a_super_admin_can_make_a_user_a_template_designer_and_it_is_logged(client, db, admin):
    admin_id, headers = admin
    target = _register(client, _uniq("future-designer"))
    r = client.patch(f"/api/admin/users/{target}/role", json={"role": "template_designer"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "template_designer"
    db.expire_all()
    assert db.query(User).filter(User.id == target).one().role == UserRole.TEMPLATE_DESIGNER
    log = db.query(UserRoleChange).filter(UserRoleChange.user_id == target).all()
    assert [(c.old_role, c.new_role, str(c.changed_by)) for c in log] == [("user", "template_designer", admin_id)]


def test_the_new_role_takes_effect_on_the_next_request(client, db, admin):
    email = _uniq("designer")
    uid = _register(client, email)
    headers = _login(client, email)
    assert client.get("/api/admin/users", headers=headers).status_code == 403
    client.patch(f"/api/admin/users/{uid}/role", json={"role": "super_admin"}, headers=admin[1])
    assert client.get("/api/admin/users", headers=headers).status_code == 200  # same token, new role


def test_setting_the_same_role_again_is_a_no_op_and_not_logged(client, db, admin):
    target = _register(client, _uniq("same"))
    client.patch(f"/api/admin/users/{target}/role", json={"role": "org_admin"}, headers=admin[1])
    client.patch(f"/api/admin/users/{target}/role", json={"role": "org_admin"}, headers=admin[1])
    assert db.query(UserRoleChange).filter(UserRoleChange.user_id == target).count() == 1


def test_you_cannot_change_your_own_role(client, db, admin):
    admin_id, headers = admin
    r = client.patch(f"/api/admin/users/{admin_id}/role", json={"role": "user"}, headers=headers)
    assert r.status_code == 400
    db.expire_all()
    assert db.query(User).filter(User.id == admin_id).one().role == UserRole.SUPER_ADMIN


def test_an_unknown_role_and_an_unknown_user_are_refused(client, admin):
    target = _register(client, _uniq("x"))
    assert client.patch(f"/api/admin/users/{target}/role", json={"role": "wizard"}, headers=admin[1]).status_code == 422
    assert client.patch(f"/api/admin/users/{uuid.uuid4()}/role", json={"role": "user"}, headers=admin[1]).status_code == 404


def test_the_list_can_be_searched_and_filtered(client, db, admin):
    marker = uuid.uuid4().hex[:8]
    a = _register(client, f"find-{marker}-a@example.com")
    _register(client, f"find-{marker}-b@example.com")
    client.patch(f"/api/admin/users/{a}/role", json={"role": "template_designer"}, headers=admin[1])
    both = client.get(f"/api/admin/users?q={marker}", headers=admin[1]).json()
    assert len(both) == 2
    only = client.get(f"/api/admin/users?q={marker}&role=template_designer", headers=admin[1]).json()
    assert [u["id"] for u in only] == [a]
