"""Sign-up verification, the limited tier, approval by a super admin, and recovery.

History: H2.1 / S1-01 stopped self-registration from granting access. Owner decision
2026-10-20 replaced "inert until approved" with a LIMITED TIER: a new account (phone proved
by a code, or a Facebook login) is ACTIVE but `approved_at` stays empty until a super admin
approves it; only a super admin can approve, suspend or issue a reset link.
"""
import re
import uuid

import pytest

from app.models.user import User, UserIdentity, UserRole, UserStatus
from app.services import facebook_auth
from app.utils.auth import hash_password

# These tests exercise the real registration payload; the conftest shim that fills it in
# for older fixtures is switched off by this marker.
pytestmark = pytest.mark.real_registration

BASE = "/api/v1/auth"
REGISTER = f"{BASE}/register"
LOGIN = f"{BASE}/login"
PENDING = f"{BASE}/users/pending"


class _Outbox:
    """Stands in for the SMS provider and the mailer; keeps what would have been sent."""

    def __init__(self):
        self.sms: list[tuple[str, str]] = []
        self.reset_links: list[tuple[str, str]] = []
        self.verify_links: list[tuple[str, str]] = []
        self.notices: list[str] = []

    def code_for(self, phone: str) -> str:
        text = [t for p, t in self.sms if p == phone][-1]
        return re.search(r"\b(\d{6})\b", text).group(1)


@pytest.fixture()
def outbox(monkeypatch):
    box = _Outbox()

    class Sender:
        def send(self, phone, text):
            box.sms.append((phone, text))
            return True

    monkeypatch.setattr("app.api.auth.get_sms_sender", lambda: Sender())
    monkeypatch.setattr("app.api.auth_verification.get_sms_sender", lambda: Sender())
    monkeypatch.setattr("app.services.auth_mailer.send_reset_email", lambda to, t: box.reset_links.append((to, t)) or True)
    monkeypatch.setattr("app.services.auth_mailer.send_verify_email", lambda to, t: box.verify_links.append((to, t)) or True)
    monkeypatch.setattr("app.services.auth_mailer.send_password_changed_notice", lambda to: box.notices.append(to) or True)
    return box


def _phone():
    return "98" + "".join(str(uuid.uuid4().int % 10) for _ in range(8))


def _payload(client, outbox, **over):
    """A complete sign-up body, with a real code obtained through the API."""
    phone = over.pop("phone", _phone())
    r = client.post(f"{BASE}/signup/phone-code", json={"phone": phone})
    assert r.status_code == 202, r.text
    body = {
        "email": f"applicant-{uuid.uuid4().hex[:8]}@example.com",
        "password": "TestPass123!",
        "full_name": "Applicant",
        "phone": phone,
        "phone_code": outbox.code_for("+977" + phone),
        "user_type": "official",
        "designation": "forester",
        "sub_division": "Rampur sub-division",
        "instagram_handle": "@applicant_1",
    }
    body.update(over)
    return body


def _super_admin(client, db):
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    db.add(User(id=uuid.uuid4(), email=email, hashed_password=hash_password("AdminPass123!"),
                full_name="Admin", role=UserRole.SUPER_ADMIN, status=UserStatus.ACTIVE))
    db.commit()
    r = client.post(LOGIN, json={"email": email, "password": "AdminPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _login(client, p):
    r = client.post(LOGIN, json={"email": p["email"], "password": p["password"]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestRegistration:
    def test_creates_an_active_unapproved_account_with_a_verified_phone(self, client, db, outbox):
        p = _payload(client, outbox)
        r = client.post(REGISTER, json=p)
        assert r.status_code == 201, r.text
        user = db.query(User).filter(User.email == p["email"]).one()
        assert user.status == UserStatus.ACTIVE
        assert user.approved_at is None
        assert user.phone_verified_at is not None and user.phone == "+977" + p["phone"]
        assert (user.designation, user.sub_division, user.instagram_handle) == ("forester", "Rampur sub-division", "applicant_1")
        assert outbox.verify_links and outbox.verify_links[-1][0] == p["email"]

    def test_registration_does_not_return_a_token(self, client, outbox):
        r = client.post(REGISTER, json=_payload(client, outbox))
        body = r.text.lower()
        assert "access_token" not in body and "bearer" not in body

    def test_wrong_code_creates_nothing(self, client, db, outbox):
        p = _payload(client, outbox, phone_code="000000")
        r = client.post(REGISTER, json=p)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "auth.code_wrong"
        assert db.query(User).filter(User.email == p["email"]).first() is None

    def test_code_is_single_use(self, client, outbox):
        p = _payload(client, outbox)
        assert client.post(REGISTER, json=p).status_code == 201
        again = dict(p, email=f"other-{uuid.uuid4().hex[:8]}@example.com")
        assert client.post(REGISTER, json=again).status_code == 400

    def test_five_wrong_guesses_lock_the_code(self, client, outbox):
        p = _payload(client, outbox)
        for _ in range(5):
            client.post(REGISTER, json=dict(p, phone_code="111111"))
        r = client.post(REGISTER, json=p)  # the right code, too late
        assert r.status_code == 400 and r.json()["detail"]["code"] == "auth.code_too_many_attempts"

    @pytest.mark.parametrize("missing", ["user_type", "phone", "phone_code", "email"])
    def test_required_fields(self, client, outbox, missing):
        p = _payload(client, outbox)
        p.pop(missing)
        assert client.post(REGISTER, json=p).status_code == 422

    @pytest.mark.parametrize("missing", ["designation", "sub_division"])
    def test_an_official_must_say_where_and_as_whom(self, client, outbox, missing):
        p = _payload(client, outbox)
        p.pop(missing)
        assert client.post(REGISTER, json=p).status_code == 400

    def test_a_designation_outside_the_list_is_refused(self, client, outbox):
        assert client.post(REGISTER, json=_payload(client, outbox, designation="president")).status_code == 422

    def test_a_social_identity_is_required(self, client, outbox):
        p = _payload(client, outbox)
        p.pop("instagram_handle")
        r = client.post(REGISTER, json=p)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "auth.social_required"

    def test_facebook_token_is_refused_while_facebook_is_not_set_up(self, client, outbox):
        p = _payload(client, outbox, facebook_access_token="abc")
        r = client.post(REGISTER, json=p)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "auth.facebook_unavailable"

    def test_duplicate_email_and_phone_are_refused(self, client, outbox):
        p = _payload(client, outbox)
        assert client.post(REGISTER, json=p).status_code == 201
        r = client.post(REGISTER, json=dict(_payload(client, outbox), email=p["email"]))
        assert r.json()["detail"]["code"] == "auth.email_already_registered"
        r = client.post(f"{BASE}/signup/phone-code", json={"phone": p["phone"]})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "auth.phone_already_registered"

    def test_a_second_code_within_the_cooldown_is_refused(self, client, outbox):
        phone = _phone()
        assert client.post(f"{BASE}/signup/phone-code", json={"phone": phone}).status_code == 202
        r = client.post(f"{BASE}/signup/phone-code", json={"phone": phone})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "auth.code_resend_wait"

    def test_a_malformed_number_is_refused(self, client):
        r = client.post(f"{BASE}/signup/phone-code", json={"phone": "12345"})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "auth.phone_invalid"


class TestLimitedTierAndApproval:
    def test_unapproved_user_can_sign_in_and_is_marked_unapproved(self, client, outbox):
        p = _payload(client, outbox)
        client.post(REGISTER, json=p)
        me = client.get(f"{BASE}/me", headers=_login(client, p)).json()
        assert me["is_approved"] is False and me["profile_complete"] is True

    def test_super_admin_approves(self, client, db, outbox):
        p = _payload(client, outbox)
        client.post(REGISTER, json=p)
        user = db.query(User).filter(User.email == p["email"]).one()
        admin = _super_admin(client, db)
        assert any(u["email"] == p["email"] for u in client.get(PENDING, headers=admin).json())
        r = client.post(f"{BASE}/users/{user.id}/approve", headers=admin)
        assert r.status_code == 200 and r.json()["is_approved"] is True
        assert client.post(f"{BASE}/users/{user.id}/approve", headers=admin).status_code == 200  # idempotent
        assert not any(u["email"] == p["email"] for u in client.get(PENDING, headers=admin).json())

    def test_only_a_super_admin_may_approve(self, client, db, outbox):
        p = _payload(client, outbox)
        client.post(REGISTER, json=p)
        user = db.query(User).filter(User.email == p["email"]).one()
        assert client.post(f"{BASE}/users/{user.id}/approve").status_code in (401, 403)
        assert client.post(f"{BASE}/users/{user.id}/approve", headers=_login(client, p)).status_code == 403
        org = f"org-{uuid.uuid4().hex[:8]}@example.com"
        db.add(User(id=uuid.uuid4(), email=org, hashed_password=hash_password("OrgPass123!"),
                    full_name="Org", role=UserRole.ORG_ADMIN, status=UserStatus.ACTIVE))
        db.commit()
        tok = client.post(LOGIN, json={"email": org, "password": "OrgPass123!"}).json()["access_token"]
        assert client.post(f"{BASE}/users/{user.id}/approve", headers={"Authorization": f"Bearer {tok}"}).status_code == 403
        assert client.get(PENDING).status_code in (401, 403)

    def test_suspension_revokes_sign_in(self, client, db, outbox):
        p = _payload(client, outbox)
        client.post(REGISTER, json=p)
        user = db.query(User).filter(User.email == p["email"]).one()
        admin = _super_admin(client, db)
        assert client.post(f"{BASE}/users/{user.id}/suspend", headers=admin).status_code == 200
        assert client.post(LOGIN, json={"email": p["email"], "password": p["password"]}).status_code == 403

    def test_super_admin_cannot_suspend_themselves(self, client, db):
        admin = _super_admin(client, db)
        me = client.get(f"{BASE}/me", headers=admin).json()
        assert client.post(f"{BASE}/users/{me['id']}/suspend", headers=admin).status_code == 400


class TestPhoneSignIn:
    def test_code_signs_in_and_unknown_numbers_look_the_same(self, client, outbox):
        p = _payload(client, outbox)
        client.post(REGISTER, json=p)
        phone = "+977" + p["phone"]
        assert client.post(f"{BASE}/login/phone-code", json={"phone": p["phone"]}).status_code == 202
        r = client.post(f"{BASE}/login/phone", json={"phone": p["phone"], "code": outbox.code_for(phone)})
        assert r.status_code == 200 and r.json()["access_token"]
        # An unregistered number gets the same 202 and nothing is sent.
        sent = len(outbox.sms)
        assert client.post(f"{BASE}/login/phone-code", json={"phone": _phone()}).status_code == 202
        assert len(outbox.sms) == sent

    def test_wrong_code_is_refused(self, client, outbox):
        p = _payload(client, outbox)
        client.post(REGISTER, json=p)
        client.post(f"{BASE}/login/phone-code", json={"phone": p["phone"]})
        r = client.post(f"{BASE}/login/phone", json={"phone": p["phone"], "code": "000000"})
        assert r.status_code == 400


class TestFacebook:
    def _fake(self, monkeypatch, subject="fb-1", email=None, name="Fb Person"):
        monkeypatch.setattr(
            "app.api.auth_verification.facebook_auth.verify_access_token",
            lambda token: facebook_auth.FacebookProfile(subject=subject, name=name, email=email),
        )

    def test_first_sign_in_creates_a_limited_account_without_a_profile(self, client, db, monkeypatch):
        self._fake(monkeypatch, subject=f"fb-{uuid.uuid4().hex}")
        r = client.post(f"{BASE}/login/facebook", json={"access_token": "t"})
        assert r.status_code == 200, r.text
        me = client.get(f"{BASE}/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
        assert me["status"] == "active" and me["is_approved"] is False and me["profile_complete"] is False

    def test_second_sign_in_is_the_same_account_and_the_profile_can_be_completed(self, client, db, monkeypatch):
        subject = f"fb-{uuid.uuid4().hex}"
        self._fake(monkeypatch, subject=subject)
        t1 = client.post(f"{BASE}/login/facebook", json={"access_token": "t"}).json()["access_token"]
        t2 = client.post(f"{BASE}/login/facebook", json={"access_token": "t"}).json()["access_token"]
        h1, h2 = ({"Authorization": f"Bearer {t}"} for t in (t1, t2))
        assert client.get(f"{BASE}/me", headers=h1).json()["id"] == client.get(f"{BASE}/me", headers=h2).json()["id"]
        r = client.patch(f"{BASE}/me/profile", headers=h1,
                         json={"designation": "ranger", "sub_division": "Banepa", "instagram_handle": "@fb_person"})
        assert r.status_code == 200 and r.json()["profile_complete"] is True
        assert db.query(UserIdentity).filter_by(subject=subject).count() == 1

    def test_unverified_email_is_not_silently_linked(self, client, db, outbox, monkeypatch):
        p = _payload(client, outbox)
        client.post(REGISTER, json=p)
        db.query(User).filter(User.email == p["email"]).update({"email_verified_at": None})
        db.commit()
        self._fake(monkeypatch, subject=f"fb-{uuid.uuid4().hex}", email=p["email"])
        r = client.post(f"{BASE}/login/facebook", json={"access_token": "t"})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "auth.email_already_registered"

    def test_off_until_configured(self, client):
        r = client.post(f"{BASE}/login/facebook", json={"access_token": "t"})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "auth.facebook_unavailable"


class TestPasswordRecovery:
    def _registered(self, client, db, outbox):
        p = _payload(client, outbox)
        client.post(REGISTER, json=p)
        user = db.query(User).filter(User.email == p["email"]).one()
        user.email_verified_at = user.created_at  # as if the sign-up link had been opened
        db.commit()
        return p, user

    def test_email_link_resets_the_password_and_ends_old_sessions(self, client, db, outbox):
        p, user = self._registered(client, db, outbox)
        old = _login(client, p)
        assert client.post(f"{BASE}/forgot-password", json={"identifier": p["email"]}).status_code == 202
        token = outbox.reset_links[-1][1]
        r = client.post(f"{BASE}/reset-password", json={"token": token, "new_password": "NewPass456!"})
        assert r.status_code == 204, r.text
        assert client.post(LOGIN, json={"email": p["email"], "password": p["password"]}).status_code == 401
        assert client.post(LOGIN, json={"email": p["email"], "password": "NewPass456!"}).status_code == 200
        assert client.get(f"{BASE}/me", headers=old).status_code == 401, "old sessions must end"
        assert outbox.notices == [p["email"]]

    def test_link_is_single_use(self, client, db, outbox):
        p, _ = self._registered(client, db, outbox)
        client.post(f"{BASE}/forgot-password", json={"identifier": p["email"]})
        token = outbox.reset_links[-1][1]
        assert client.post(f"{BASE}/reset-password", json={"token": token, "new_password": "NewPass456!"}).status_code == 204
        assert client.post(f"{BASE}/reset-password", json={"token": token, "new_password": "Other789!a"}).status_code == 400

    def test_phone_code_resets_the_password(self, client, db, outbox):
        p, _ = self._registered(client, db, outbox)
        assert client.post(f"{BASE}/forgot-password", json={"identifier": p["phone"]}).status_code == 202
        code = outbox.code_for("+977" + p["phone"])
        r = client.post(f"{BASE}/reset-password",
                        json={"phone": p["phone"], "code": code, "new_password": "NewPass456!"})
        assert r.status_code == 204, r.text

    def test_unknown_and_unverified_contacts_get_the_same_answer_and_nothing_is_sent(self, client, db, outbox):
        p, user = self._registered(client, db, outbox)
        user.email_verified_at = None
        db.commit()
        for ident in (p["email"], "nobody@example.com", _phone()):
            assert client.post(f"{BASE}/forgot-password", json={"identifier": ident}).status_code == 202
        assert outbox.reset_links == []

    def test_super_admin_can_issue_a_one_time_link(self, client, db, outbox):
        p, user = self._registered(client, db, outbox)
        admin = _super_admin(client, db)
        r = client.post(f"{BASE}/users/{user.id}/reset-link", headers=admin)
        assert r.status_code == 200
        token = r.json()["url"].split("token=")[1]
        assert client.post(f"{BASE}/reset-password", json={"token": token, "new_password": "NewPass456!"}).status_code == 204
        p["password"] = "NewPass456!"
        assert client.post(f"{BASE}/users/{user.id}/reset-link", headers=_login(client, p)).status_code == 403


class TestEmailVerification:
    def test_link_marks_the_email_verified(self, client, db, outbox):
        p = _payload(client, outbox)
        client.post(REGISTER, json=p)
        token = outbox.verify_links[-1][1]
        r = client.post(f"{BASE}/email/verify", json={"token": token})
        assert r.status_code == 200 and r.json()["email_verified_at"]
        assert client.post(f"{BASE}/email/verify", json={"token": token}).status_code == 400
