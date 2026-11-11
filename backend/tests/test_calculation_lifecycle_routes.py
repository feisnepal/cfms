"""The six lifecycle endpoints that answered 404 while the UI called them.

They were defined in `app/api/calculations.py`, which `main.py` never mounted
and which cannot be imported at all. `tests/test_map_lifecycle.py` covers the
state machine underneath — `validate_transition`, `log_state_transition` — and
passed throughout, which is exactly how the endpoints could disappear with a
green suite. These tests go through HTTP, so they fail if the router is ever
unmounted again.

The DFO role check is the one worth reading twice. The original gated on
`role not in ("dfo", "super_admin")`, and there is no `"dfo"` role: `UserRole`
is guest/user/org_admin/super_admin, and **DFO is `ORG_ADMIN`**. That check
denied every real DFO. `test_a_real_dfo_can_approve` is the regression pin.
"""
import uuid

import pytest

from app.models.calculation import Calculation, MapLifecycleStatus
from app.models.user import User, UserRole


@pytest.fixture()
def calc(db, client, lifecycle_user):
    """A calculation owned by the `auth_headers` user."""
    user = lifecycle_user
    calculation = Calculation(
        id=uuid.uuid4(),
        user_id=user.id,
        forest_name="Lifecycle Test Forest",
        map_lifecycle_status=MapLifecycleStatus.DRAFT.value,
    )
    db.add(calculation)
    db.commit()
    db.refresh(calculation)
    return calculation


def _set_state(db, calculation, state):
    calculation.map_lifecycle_status = state
    db.commit()


def _other_users_calculation(db) -> Calculation:
    """A calculation belonging to somebody else.

    `calculations.user_id` has a foreign key, so this needs a real second user
    rather than a random UUID.
    """
    from app.models.user import UserStatus

    stranger = db.query(User).filter(User.email == "stranger@example.com").first()
    if stranger is None:
        stranger = User(
            id=uuid.uuid4(),
            email="stranger@example.com",
            hashed_password="not-a-real-hash",
            full_name="Stranger",
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        db.add(stranger)
        db.commit()
    calculation = Calculation(
        id=uuid.uuid4(), user_id=stranger.id, forest_name="Not Yours",
        map_lifecycle_status=MapLifecycleStatus.DRAFT.value,
    )
    db.add(calculation)
    db.commit()
    return calculation


@pytest.fixture()
def lifecycle_user(db):
    """A user private to this module, replacing conftest's shared account.

    conftest's `auth_headers` uses a FIXED email -- it registers
    `testuser@example.com`, ignores the 409 when it already exists, and logs in.
    This file promotes that account to ORG_ADMIN and SUPER_ADMIN to exercise the
    approval routes, so the elevation leaked into every later test that asked
    for an "ordinary user": those assert 403 for a non-privileged caller, got
    200 against a leaked admin, and failed. Four authorisation tests in two
    unrelated files went red on the run that drew the wrong order.

    Restoring the role in teardown is not enough. CI runs `-n auto`, so several
    worker PROCESSES share one database: another worker can read the elevated
    role between the promotion and the reset. The only fix without a race is to
    stop touching the shared row at all.

    It hid locally because pytest runs files in a fixed order there, and only
    surfaced under `-p randomly` in CI.
    """
    from app.models.user import UserStatus
    from app.utils.auth import hash_password

    email = f"lifecycle-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        id=uuid.uuid4(), email=email, hashed_password=hash_password("TestPass123!"),
        full_name="Lifecycle", role=UserRole.USER, status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def auth_headers(client, lifecycle_user):
    """Shadows conftest's fixture for this module only.

    A fixture defined in a test module takes precedence over the same name in
    conftest, so all 32 call sites below get the private user with no edits.
    """
    response = client.post(
        "/api/auth/login",
        json={"email": lifecycle_user.email, "password": "TestPass123!"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _set_role(db, user, role):
    """Promote the module's OWN user. Never the shared fixture account."""
    user.role = role
    db.commit()
    return user


class TestRoutesExist:
    """The bug was a 404, so the first thing to assert is that they are served."""

    @pytest.mark.parametrize("verb,path", [
        ("get",  "/api/v1/calculations/{c}/unified-shell-status"),
        ("post", "/api/calculations/{c}/submit-for-calculation"),
        ("post", "/api/calculations/{c}/super-admin-unlock"),
        ("get",  "/api/calculations/{c}/progress"),
    ])
    def test_unauthenticated_gets_401_not_404(self, client, verb, path):
        """401 means the route exists; 404 was the defect."""
        response = getattr(client, verb)(path.format(c=uuid.uuid4()))
        assert response.status_code == 401, (
            f"{path} returned {response.status_code} - 404 means it is unmounted "
            f"again"
        )

    @pytest.mark.parametrize("path", [
        "/api/calculations/{c}/dfo-approve",
        "/api/calculations/{c}/dfo-reject",
    ])
    def test_dfo_routes_are_served(self, client, calc, path):
        """These resolve the calculation before auth, so a real id is needed.

        With a random UUID they answer 404 from `get_calculation_or_404` and
        look unmounted; with a real one the 401 proves the route is there.
        """
        response = client.post(path.format(c=calc.id), json={})
        assert response.status_code == 401, response.text


class TestSubmit:
    def test_owner_can_submit_a_draft(self, client, auth_headers, calc, db):
        response = client.post(
            f"/api/calculations/{calc.id}/submit-for-calculation",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["map_lifecycle_status"] == "submitted"
        db.refresh(calc)
        assert calc.submitted_by is not None

    def test_submitting_twice_is_a_409(self, client, auth_headers, calc, db):
        """submitted -> submitted is not in ALLOWED_TRANSITIONS."""
        _set_state(db, calc, MapLifecycleStatus.SUBMITTED.value)
        response = client.post(
            f"/api/calculations/{calc.id}/submit-for-calculation",
            headers=auth_headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "INVALID_MAP_STATE"

    def test_a_stranger_cannot_submit(self, lifecycle_user, client, auth_headers, calc, db):
        # Explicit, though `lifecycle_user` is already USER: a super admin
        # legitimately CAN act on anyone's calculation, so this states which
        # role the 403 below is actually about.
        _set_role(db, lifecycle_user, UserRole.USER)
        other = _other_users_calculation(db)
        response = client.post(
            f"/api/calculations/{other.id}/submit-for-calculation",
            headers=auth_headers,
        )
        assert response.status_code == 403


class TestDfoDecision:
    def test_a_real_dfo_can_approve(self, lifecycle_user, client, auth_headers, calc, db):
        """The regression pin. DFO is ORG_ADMIN.

        The original check was `role not in ("dfo", "super_admin")`, which
        denied this user — the role literal it wanted does not exist.
        """
        _set_role(db, lifecycle_user, UserRole.ORG_ADMIN)
        _set_state(db, calc, MapLifecycleStatus.COMPLETED.value)

        response = client.post(
            f"/api/calculations/{calc.id}/dfo-approve",
            headers=auth_headers, json={"notes": "Looks correct"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["map_lifecycle_status"] == "locked"
        assert body["structure_locked"] is True
        db.refresh(calc)
        assert calc.dfo_decision_notes == "Looks correct"

    def test_an_ordinary_user_cannot_approve(self, lifecycle_user, client, auth_headers, calc, db):
        _set_role(db, lifecycle_user, UserRole.USER)
        _set_state(db, calc, MapLifecycleStatus.COMPLETED.value)
        response = client.post(
            f"/api/calculations/{calc.id}/dfo-approve",
            headers=auth_headers, json={"notes": "let me in"},
        )
        assert response.status_code == 403

    def test_a_dfo_can_reject_back_to_draft(self, lifecycle_user, client, auth_headers, calc, db):
        _set_role(db, lifecycle_user, UserRole.ORG_ADMIN)
        _set_state(db, calc, MapLifecycleStatus.COMPLETED.value)
        response = client.post(
            f"/api/calculations/{calc.id}/dfo-reject",
            headers=auth_headers, json={"reason": "Block 3 area is wrong"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["map_lifecycle_status"] == "draft"
        db.refresh(calc)
        assert calc.dfo_decision_notes == "Block 3 area is wrong"

    def test_approving_a_draft_is_a_409(self, lifecycle_user, client, auth_headers, calc, db):
        """Only a completed calculation can be approved."""
        _set_role(db, lifecycle_user, UserRole.ORG_ADMIN)
        response = client.post(
            f"/api/calculations/{calc.id}/dfo-approve",
            headers=auth_headers, json={"notes": "too early"},
        )
        assert response.status_code == 409


class TestSuperAdminUnlock:
    def test_super_admin_can_unlock(self, lifecycle_user, client, auth_headers, calc, db):
        _set_role(db, lifecycle_user, UserRole.SUPER_ADMIN)
        _set_state(db, calc, MapLifecycleStatus.LOCKED.value)
        response = client.post(
            f"/api/calculations/{calc.id}/super-admin-unlock",
            headers=auth_headers, data={"reason": "approved in error"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["structure_locked"] is False
        db.refresh(calc)
        assert calc.locked_reason == "approved in error"

    def test_a_dfo_cannot_unlock(self, lifecycle_user, client, auth_headers, calc, db):
        """Deliberately stricter than approve: a DFO approves, only a super
        admin undoes an approval."""
        _set_role(db, lifecycle_user, UserRole.ORG_ADMIN)
        _set_state(db, calc, MapLifecycleStatus.LOCKED.value)
        response = client.post(
            f"/api/calculations/{calc.id}/super-admin-unlock",
            headers=auth_headers, data={"reason": "let me"},
        )
        assert response.status_code == 403

    def test_reason_is_required(self, lifecycle_user, client, auth_headers, calc, db):
        _set_role(db, lifecycle_user, UserRole.SUPER_ADMIN)
        _set_state(db, calc, MapLifecycleStatus.LOCKED.value)
        response = client.post(
            f"/api/calculations/{calc.id}/super-admin-unlock",
            headers=auth_headers,
        )
        assert response.status_code == 422


class TestUnifiedShellStatus:
    def test_it_answers_for_the_owner(self, client, auth_headers, calc):
        response = client.get(
            f"/api/v1/calculations/{calc.id}/unified-shell-status",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert isinstance(response.json()["enabled"], bool)

    def test_the_calculation_override_wins(self, client, auth_headers, calc, db):
        calc.unified_shell_enabled = True
        db.commit()
        response = client.get(
            f"/api/v1/calculations/{calc.id}/unified-shell-status",
            headers=auth_headers,
        )
        assert response.json() == {"enabled": True}


class TestProgress:
    def test_it_answers_for_the_owner(self, client, auth_headers, calc):
        response = client.get(
            f"/api/calculations/{calc.id}/progress", headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["map_lifecycle_status"] == "draft"

    def test_a_stranger_is_refused(self, lifecycle_user, client, auth_headers, db):
        _set_role(db, lifecycle_user, UserRole.USER)  # see test_a_stranger_cannot_submit
        other = _other_users_calculation(db)
        response = client.get(
            f"/api/calculations/{other.id}/progress", headers=auth_headers,
        )
        assert response.status_code == 403
