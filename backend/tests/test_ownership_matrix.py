"""H2.7 / S2-07 — one ownership check, and a matrix that exercises it.

Thirty guards across five API modules compared a `UserRole` against a string
literal:

    if calculation.user_id != current_user.id and current_user.role != "SUPER_ADMIN":

`UserRole` is a str-enum whose values are lowercase — `SUPER_ADMIN` is
`"super_admin"` — so `role != "SUPER_ADMIN"` is true for every user alive,
super admins included. Four more sites wrote
`role.value not in ['SUPER_ADMIN', 'ORG_ADMIN']`, true for the same reason.

These failed closed: super admins were denied access they were meant to have.
That is not a breach, and it is worse in one specific way — the escalation
branch had never executed, so the first time anyone "fixed" it by changing the
operand, an untested authorisation path would go live in production. This
matrix is what makes that branch exercised.

The replacement admits owner or super admin. It deliberately does not widen to
org admins: they are denied today (the broken comparison denied everyone), and
granting a role access to every community's data is a policy decision, not a
side effect of a refactor.
"""
import uuid
from pathlib import Path

import pytest

from app.models.calculation import Calculation
from app.models.user import User, UserRole, UserStatus
from app.utils.auth import hash_password
from app.utils.authz import is_owner_or_admin

API_DIR = Path(__file__).resolve().parents[1] / "app"

ALL_ROLES = [UserRole.GUEST, UserRole.USER, UserRole.ORG_ADMIN, UserRole.SUPER_ADMIN]


def _user(db, role):
    u = User(id=uuid.uuid4(), email=f"{role.value}-{uuid.uuid4().hex[:8]}@example.com",
             hashed_password=hash_password("TestPass123!"), full_name=role.value,
             role=role, status=UserStatus.ACTIVE)
    db.add(u)
    db.commit()
    return u


def _headers(client, user):
    r = client.post("/api/v1/auth/login",
                    json={"email": user.email, "password": "TestPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _calc_for(db, owner):
    c = Calculation(id=uuid.uuid4(), user_id=owner.id, forest_name="Matrix Forest")
    db.add(c)
    db.commit()
    return c


class TestHelperMatrix:
    """(role × ownership) → allowed, evaluated directly."""

    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_the_owner_is_always_allowed(self, db, role):
        owner = _user(db, role)
        assert is_owner_or_admin(_calc_for(db, owner), owner) is True

    @pytest.mark.parametrize("role", [UserRole.GUEST, UserRole.USER, UserRole.ORG_ADMIN])
    def test_non_owners_below_super_admin_are_denied(self, db, role):
        owner = _user(db, UserRole.USER)
        calc = _calc_for(db, owner)
        assert is_owner_or_admin(calc, _user(db, role)) is False

    def test_a_super_admin_is_allowed_on_someone_elses_calculation(self, db):
        """The case the old comparison could never reach."""
        owner = _user(db, UserRole.USER)
        calc = _calc_for(db, owner)
        assert is_owner_or_admin(calc, _user(db, UserRole.SUPER_ADMIN)) is True


class TestOverHttp:
    """The same matrix through a real request, on a route that uses the helper."""

    def _get(self, client, db, calc, role):
        return client.get(f"/api/calculations/{calc.id}/tile-token",
                          headers=_headers(client, _user(db, role)))

    def test_the_owner_is_allowed(self, client, db):
        owner = _user(db, UserRole.USER)
        calc = _calc_for(db, owner)
        r = client.get(f"/api/calculations/{calc.id}/tile-token",
                       headers=_headers(client, owner))
        assert r.status_code == 200, r.text

    @pytest.mark.parametrize("role", [UserRole.USER, UserRole.ORG_ADMIN])
    def test_other_users_are_refused(self, client, db, role):
        owner = _user(db, UserRole.USER)
        calc = _calc_for(db, owner)
        assert self._get(client, db, calc, role).status_code == 403

    def test_a_super_admin_is_admitted(self, client, db):
        owner = _user(db, UserRole.USER)
        calc = _calc_for(db, owner)
        assert self._get(client, db, calc, UserRole.SUPER_ADMIN).status_code == 200


class TestNoRoleIsComparedToAStringLiteral:
    """The lint rule, as a test — the defect was silent and reintroducible.

    Nothing failed when these comparisons were wrong: no exception, no log, no
    failing test. Only a reader noticing the letter case would catch it, which
    is precisely what did not happen thirty times.
    """

    FORBIDDEN = [
        'role != "SUPER_ADMIN"', "role != 'SUPER_ADMIN'",
        'role == "SUPER_ADMIN"', "role == 'SUPER_ADMIN'",
        'role != "ORG_ADMIN"', "role == 'ORG_ADMIN'",
        "role.value not in ['SUPER_ADMIN'", 'role.value not in ["SUPER_ADMIN"',
        "role.value in ['SUPER_ADMIN'", 'role.value in ["SUPER_ADMIN"',
    ]

    def test_no_source_file_compares_a_role_to_an_uppercase_literal(self):
        offenders = []
        for path in API_DIR.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for line_no, line in enumerate(text.splitlines(), 1):
                if any(bad in line for bad in self.FORBIDDEN):
                    offenders.append(f"{path.relative_to(API_DIR)}:{line_no}: {line.strip()}")
        assert offenders == [], (
            "role compared against an uppercase string literal — UserRole values "
            "are lowercase, so this never matches:\n" + "\n".join(offenders)
        )

    def test_the_enum_values_really_are_lowercase(self):
        """Pins the assumption the whole finding rests on."""
        assert UserRole.SUPER_ADMIN.value == "super_admin"
        assert UserRole.SUPER_ADMIN != "SUPER_ADMIN"
        assert UserRole.SUPER_ADMIN == "super_admin"
