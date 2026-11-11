"""User types: what each type must declare, read-only access for students and researchers, expiry,
and organisations as groups (owner, members, vouching)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.organization import Organization
from app.models.user import User
from tests.test_registration_approval import (  # noqa: F401  (outbox is a fixture)
    BASE, LOGIN, REGISTER, _login, _payload, _super_admin, outbox,
)

pytestmark = pytest.mark.real_registration

STUDENT = {"level": "university", "institution": "Tribhuvan University", "programme": "MSc Forestry",
           "supervisor_name": "Dr. Rai", "supervisor_email": "rai@tu.edu.np"}
RESEARCHER = {"affiliation": "ICIMOD", "topic": "Carbon stock", "orcid": "0000-0002-1825-0097"}


def _org(name, kind="cfug", position="Chairperson"):
    return {"organization_name": name, "org_kind": kind, "position": position}


def _typed(client, outbox, user_type, details=None, **over):
    body = _payload(client, outbox, user_type=user_type, **over)
    body.pop("designation"), body.pop("sub_division")
    if details is not None:
        body["details"] = details
    return body


def _register(client, db, outbox, user_type, details=None, **over):
    body = _typed(client, outbox, user_type, details, **over)
    r = client.post(REGISTER, json=body)
    assert r.status_code == 201, r.text
    return body, db.query(User).filter(User.email == body["email"]).one(), r.json()


def _code(r):
    detail = r.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else detail


class TestDeclaredType:
    @pytest.mark.parametrize("kind,details", [("student", STUDENT), ("researcher", RESEARCHER),
                                              ("organization", _org("Rampur CFUG"))])
    def test_each_type_registers_with_its_own_fields(self, client, db, outbox, kind, details):
        _, user, body = _register(client, db, outbox, kind, details)
        assert user.user_type == kind and body["user_type"] == kind
        assert user.designation is None and body["profile_complete"] is True
        assert user.type_details

    @pytest.mark.parametrize("kind,details,missing", [
        ("student", {k: v for k, v in STUDENT.items() if k != "supervisor_email"}, "supervisor_email"),
        ("student", {**STUDENT, "level": "school"}, "level"),
        ("researcher", {**RESEARCHER, "orcid": "123"}, "orcid"),
        ("organization", _org("X", kind="club"), "org_kind"),
    ])
    def test_a_missing_or_malformed_field_is_named(self, client, db, outbox, kind, details, missing):
        r = client.post(REGISTER, json=_typed(client, outbox, kind, details))
        assert r.status_code == 400 and r.json()["detail"]["field"] == missing

    def test_an_official_still_needs_designation_and_sub_division(self, client, outbox):
        body = _payload(client, outbox, user_type="official")
        body.pop("sub_division")
        r = client.post(REGISTER, json=body)
        assert r.status_code == 400 and r.json()["detail"]["field"] == "sub_division"

    def test_orcid_is_optional(self, client, db, outbox):
        _register(client, db, outbox, "researcher", {k: v for k, v in RESEARCHER.items() if k != "orcid"})


class TestReadOnlyAndExpiry:
    FOREST = f"/api/v1/calculations/{uuid.uuid4()}/cba/{uuid.uuid4()}"

    def test_a_student_can_read_but_not_change(self, client, db, outbox):
        body, user, resp = _register(client, db, outbox, "student", STUDENT)
        assert resp["access_level"] == "read_only"
        h = _login(client, body)
        assert client.get(f"{BASE}/me", headers=h).status_code == 200
        r = client.delete(self.FOREST, headers=h)
        assert r.status_code == 403 and _code(r) == "auth.read_only_account"

    def test_an_official_is_not_held_back(self, client, db, outbox):
        body = _payload(client, outbox)
        client.post(REGISTER, json=body)
        r = client.delete(self.FOREST, headers=_login(client, body))
        assert _code(r) != "auth.read_only_account"

    def test_a_student_can_still_edit_their_own_account(self, client, db, outbox):
        body, *_ = _register(client, db, outbox, "student", STUDENT)
        r = client.patch(f"{BASE}/me/profile", headers=_login(client, body), json={"instagram_handle": "@sita"})
        assert r.status_code == 200

    def test_expired_access_is_refused_everywhere(self, client, db, outbox):
        body, user, _ = _register(client, db, outbox, "researcher", RESEARCHER)
        h = _login(client, body)
        user.access_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()
        assert _code(client.get(f"{BASE}/me", headers=h)) == "auth.access_expired"
        r = client.post(LOGIN, json={"email": body["email"], "password": body["password"]})
        assert r.status_code == 403 and _code(r) == "auth.access_expired"

    def test_super_admin_sets_and_clears_the_end_date(self, client, db, outbox):
        body, user, _ = _register(client, db, outbox, "student", STUDENT)
        admin = _super_admin(client, db)
        end = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        r = client.patch(f"{BASE}/users/{user.id}/access", headers=admin, json={"access_expires_at": end})
        assert r.status_code == 200 and r.json()["access_expires_at"]
        r = client.patch(f"{BASE}/users/{user.id}/access", headers=admin, json={"access_expires_at": None})
        assert r.json()["access_expires_at"] is None
        assert client.patch(f"{BASE}/users/{user.id}/access", headers=_login(client, body), json={}).status_code == 403

    def test_an_approved_account_cannot_change_its_own_type(self, client, db, outbox):
        body, user, _ = _register(client, db, outbox, "student", STUDENT)
        client.post(f"{BASE}/users/{user.id}/approve", headers=_super_admin(client, db))
        r = client.patch(f"{BASE}/me/profile", headers=_login(client, body),
                         json={"user_type": "official", "designation": "ranger", "sub_division": "Banepa"})
        assert r.status_code == 403 and _code(r) == "auth.type_locked"


class TestOrganizations:
    def test_first_person_owns_a_new_organization_and_the_next_joins(self, client, db, outbox):
        name = f"Green Nepal {uuid.uuid4().hex[:6]}"
        _, owner, _ = _register(client, db, outbox, "organization", _org(name))
        _, member, _ = _register(client, db, outbox, "organization", _org(name.upper(), position="Officer"))
        assert owner.org_member_role == "owner" and member.org_member_role == "member"
        assert owner.organization_id == member.organization_id
        org = db.query(Organization).filter_by(id=owner.organization_id).one()
        assert org.verified_at is None and org.kind == "cfug"

    def test_vouching_needs_a_verified_organization_and_its_owner(self, client, db, outbox):
        name = f"Forest Trust {uuid.uuid4().hex[:6]}"
        ob, owner, _ = _register(client, db, outbox, "organization", _org(name))
        mb, member, _ = _register(client, db, outbox, "organization", _org(name))
        oh, mh = _login(client, ob), _login(client, mb)
        url = f"{BASE}/organization/members/{member.id}/vouch"
        assert client.post(url, headers=oh).status_code == 403          # not verified yet
        assert client.post(f"{BASE}/organizations/{owner.organization_id}/verify", headers=oh).status_code == 403
        assert client.post(f"{BASE}/organizations/{owner.organization_id}/verify",
                           headers=_super_admin(client, db)).status_code == 204
        assert client.post(url, headers=mh).status_code == 403          # a member cannot vouch
        r = client.post(url, headers=oh)
        assert r.status_code == 200 and r.json()["org_vouched_at"]
        assert client.get(f"{BASE}/me", headers=mh).json()["organization_verified"] is True

    def test_only_the_owner_lists_members_and_only_their_own(self, client, db, outbox):
        name = f"Hill Group {uuid.uuid4().hex[:6]}"
        ob, *_ = _register(client, db, outbox, "organization", _org(name))
        mb, *_ = _register(client, db, outbox, "organization", _org(name))
        _register(client, db, outbox, "organization", _org(f"Other {uuid.uuid4().hex[:6]}"))
        assert len(client.get(f"{BASE}/organization/members", headers=_login(client, ob)).json()) == 2
        assert client.get(f"{BASE}/organization/members", headers=_login(client, mb)).status_code == 403
