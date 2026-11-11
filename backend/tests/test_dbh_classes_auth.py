"""H2.3 / S1-03 — the DBH classification endpoints were entirely unauthenticated.

All six routes took no credentials of any kind. Two of them mutate
`dbh_class_systems`, the table that decides which DBH class every measured tree
falls into — and through `stand_type`, which trees count as harvestable. An
anonymous PUT could shift a class boundary and change the allowable cut on
every operational plan the system produces, silently and retroactively, because
classification is applied at read time.

`dbh_classification_changes` has existed since migration 034 and the history
endpoint reads it, but no code path ever inserted a row: the audit trail was
empty by construction. Worse, DELETE erased the history along with the system.

These tests pin both halves — who may call, and what gets recorded.
"""
import uuid

import pytest
from sqlalchemy import text

from app.models.user import User, UserRole, UserStatus
from app.utils.auth import hash_password

BASE = "/api/dbh-classes"
SYSTEMS = f"{BASE}/systems"


def _login(client, db, role):
    email = f"{role.value}-{uuid.uuid4().hex[:8]}@example.com"
    db.add(User(
        id=uuid.uuid4(), email=email, hashed_password=hash_password("TestPass123!"),
        full_name=role.value, role=role, status=UserStatus.ACTIVE,
    ))
    db.commit()
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin_headers(client, db):
    return _login(client, db, UserRole.ORG_ADMIN)


@pytest.fixture()
def custom_system(db):
    """A non-default system, so DELETE and rename are permitted on it."""
    name = f"custom_{uuid.uuid4().hex[:8]}"
    db.execute(
        text("""INSERT INTO dbh_class_systems
                    (system_name, version, description, class_defs, is_active, is_system_default)
                VALUES (:sn, '1.0', 'test fixture', CAST(:cd AS jsonb), true, false)"""),
        {"sn": name, "cd": '[{"key":"a","lower":0,"upper":10,"label_en":"A","label_np":"A"}]'},
    )
    db.commit()
    return name


class TestEveryRouteRequiresCredentials:
    """The finding is that *all six* were open, so all six are checked."""

    def test_list_systems_is_closed(self, client):
        assert client.get(SYSTEMS).status_code in (401, 403)

    def test_get_system_is_closed(self, client):
        assert client.get(f"{SYSTEMS}/guideline_2061").status_code in (401, 403)

    def test_classify_is_closed(self, client):
        assert client.post(f"{BASE}/classify?dbh=25.5&system=guideline_2061").status_code in (401, 403)

    def test_history_is_closed(self, client):
        assert client.get(f"{SYSTEMS}/guideline_2061/history").status_code in (401, 403)

    def test_update_is_closed(self, client):
        r = client.put(f"{SYSTEMS}/guideline_2061", json={"description": "anonymous edit"})
        assert r.status_code in (401, 403)

    def test_delete_is_closed(self, client):
        assert client.delete(f"{SYSTEMS}/guideline_2061").status_code in (401, 403)


class TestMutationRequiresAdmin:
    """Authentication alone is not the boundary — an ordinary user must not
    be able to redefine the classes the whole calculation rests on."""

    def test_ordinary_user_cannot_update(self, client, auth_headers, custom_system):
        r = client.put(f"{SYSTEMS}/{custom_system}", json={"description": "nope"},
                       headers=auth_headers)
        assert r.status_code == 403, r.text

    def test_ordinary_user_cannot_delete(self, client, auth_headers, custom_system):
        r = client.delete(f"{SYSTEMS}/{custom_system}", headers=auth_headers)
        assert r.status_code == 403, r.text

    def test_ordinary_user_cannot_read_the_audit_history(self, client, auth_headers):
        r = client.get(f"{SYSTEMS}/guideline_2061/history", headers=auth_headers)
        assert r.status_code == 403, r.text

    def test_ordinary_user_can_still_read_and_classify(self, client, auth_headers):
        """Reference data stays usable — the app itself needs it on every page."""
        assert client.get(SYSTEMS, headers=auth_headers).status_code == 200
        assert client.post(f"{BASE}/classify?dbh=25.5&system=guideline_2061",
                           headers=auth_headers).status_code == 200


class TestChangesAreRecorded:
    def test_update_writes_a_history_row_naming_the_editor(
        self, client, db, admin_headers, custom_system
    ):
        before = client.get(f"{SYSTEMS}/{custom_system}/history", headers=admin_headers).json()
        r = client.put(f"{SYSTEMS}/{custom_system}", json={"description": "revised"},
                       headers=admin_headers)
        assert r.status_code == 200, r.text

        after = client.get(f"{SYSTEMS}/{custom_system}/history", headers=admin_headers).json()
        assert len(after) == len(before) + 1, "the change was not recorded"
        entry = after[0]
        assert entry["change_type"] == "update"
        assert entry["changed_by"], "changed_by is NULL — the trail names nobody"

    def test_delete_writes_a_history_row_and_keeps_the_trail(
        self, client, db, admin_headers, custom_system
    ):
        client.put(f"{SYSTEMS}/{custom_system}", json={"description": "revised"},
                   headers=admin_headers)
        r = client.delete(f"{SYSTEMS}/{custom_system}", headers=admin_headers)
        assert r.status_code == 200, r.text

        after = client.get(f"{SYSTEMS}/{custom_system}/history", headers=admin_headers).json()
        assert any(e["change_type"] == "delete" for e in after)
        assert any(e["change_type"] == "update" for e in after), \
            "deleting the system erased the history that recorded what happened to it"

    def test_system_defaults_are_still_protected(self, client, admin_headers):
        """Admin rights do not extend to removing a statutory classification."""
        assert client.delete(f"{SYSTEMS}/guideline_2061", headers=admin_headers).status_code == 403
