"""C1.2: who may use the assistant. No anonymous use, approval by a super admin, caps, expiry, revocation, kill switch, Nepal-day rollover."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.models.chat import ChatAccess, ChatUsage
from app.models.user import User, UserRole
from app.services.chatbot import access
from app.utils.auth import create_access_token

API = "/api/v1/chat"


@pytest.fixture(autouse=True)
def _clean(db):
    db.execute(text("TRUNCATE chat_access, chat_usage, chat_messages CASCADE"))
    db.execute(text("UPDATE chat_settings SET enabled = true, pool_daily_tokens = NULL"))
    db.commit()
    yield


def _user(db, role=UserRole.USER, user_type=None):
    u = User(email=f"chat{uuid.uuid4().hex[:10]}@test.com", full_name="Chat Tester", role=role, hashed_password="x", user_type=user_type)
    db.add(u)
    db.commit()
    return u


def _h(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'email': user.email})}"}


def _me(client, user):
    r = client.get(f"{API}/access/me", headers=_h(user))
    assert r.status_code == 200, r.text
    return r.json()


def _approve(client, admin, user, **body):
    return client.post(f"{API}/admin/access/{user.id}/approve", json=body, headers=_h(admin))


# ── no anonymous use ────────────────────────────────────────────────────────────────────────────────────────

def test_every_route_needs_a_signed_in_user(client, db):
    u = _user(db)
    assert client.get(f"{API}/access/me").status_code in (401, 403)
    assert client.post(f"{API}/access/request", json={}).status_code in (401, 403)
    assert client.get(f"{API}/admin/access").status_code in (401, 403)
    assert client.post(f"{API}/admin/access/{u.id}/approve", json={}).status_code in (401, 403)


# ── asking ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_new_member_sees_none_then_requested_and_asking_twice_changes_nothing(client, db):
    u = _user(db)
    assert _me(client, u)["state"] == "none" and _me(client, u)["allowed"] is False
    r = client.post(f"{API}/access/request", json={"note": "I am the secretary of our group"}, headers=_h(u))
    assert r.status_code == 200 and r.json()["state"] == "requested" and r.json()["allowed"] is False
    again = client.post(f"{API}/access/request", json={}, headers=_h(u))
    assert again.json()["state"] == "requested"
    assert db.query(ChatAccess).filter(ChatAccess.user_id == u.id).count() == 1


def test_a_guest_cannot_ask_and_is_not_eligible(client, db):
    g = _user(db, role=UserRole.GUEST)
    assert _me(client, g)["state"] == "not_eligible"
    r = client.post(f"{API}/access/request", json={}, headers=_h(g))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "chat.not_eligible"


@pytest.mark.parametrize("role", [UserRole.USER, UserRole.ORG_ADMIN, UserRole.TEMPLATE_DESIGNER])
def test_the_eligible_roles_can_ask_and_be_approved(client, db, role):
    admin, u = _user(db, UserRole.SUPER_ADMIN), _user(db, role)
    client.post(f"{API}/access/request", json={}, headers=_h(u))
    assert _approve(client, admin, u).status_code == 200
    assert _me(client, u)["allowed"] is True


# ── approving ───────────────────────────────────────────────────────────────────────────────────────────────

def test_only_a_super_admin_can_approve_revoke_set_caps_or_list(client, db):
    org_admin, u = _user(db, UserRole.ORG_ADMIN), _user(db)
    client.post(f"{API}/access/request", json={}, headers=_h(u))
    assert _approve(client, org_admin, u).status_code == 403
    assert client.post(f"{API}/admin/access/{u.id}/revoke", headers=_h(org_admin)).status_code == 403
    assert client.put(f"{API}/admin/access/{u.id}/cap", json={"daily_cap_tokens": 5}, headers=_h(org_admin)).status_code == 403
    assert client.get(f"{API}/admin/access", headers=_h(org_admin)).status_code == 403


def test_approval_gives_the_default_cap_and_a_questions_estimate(client, db):
    admin, u = _user(db, UserRole.SUPER_ADMIN), _user(db)
    client.post(f"{API}/access/request", json={}, headers=_h(u))
    r = _approve(client, admin, u)
    body = r.json()
    assert body["state"] == "approved" and body["allowed"] and body["daily_cap_tokens"] == 100_000
    assert body["tokens_left_today"] == 100_000 and body["approx_questions_left"] == 10


def test_a_super_admin_can_approve_someone_who_never_asked_with_their_own_cap(client, db):
    admin, u = _user(db, UserRole.SUPER_ADMIN), _user(db)
    r = _approve(client, admin, u, daily_cap_tokens=50_000)
    assert r.status_code == 200 and r.json()["daily_cap_tokens"] == 50_000 and r.json()["allowed"]


def test_refused_approvals(client, db):
    admin, guest, other_admin, u = _user(db, UserRole.SUPER_ADMIN), _user(db, UserRole.GUEST), _user(db, UserRole.SUPER_ADMIN), _user(db)
    assert _approve(client, admin, guest).status_code == 422
    assert _approve(client, admin, other_admin).json()["detail"]["code"] == "chat.super_admin"
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert _approve(client, admin, u, expires_at=past).json()["detail"]["code"] == "chat.bad_expiry"
    assert _approve(client, admin, u, daily_cap_tokens=access.MAX_CAP_TOKENS + 1).json()["detail"]["code"] == "chat.bad_cap"
    ghost = client.post(f"{API}/admin/access/{uuid.uuid4()}/approve", json={}, headers=_h(admin))
    assert ghost.status_code == 404


# ── cap, usage, expiry, revoke ──────────────────────────────────────────────────────────────────────────────

def test_today_usage_including_the_reserved_hold_reduces_what_is_left(client, db):
    admin, u = _user(db, UserRole.SUPER_ADMIN), _user(db)
    _approve(client, admin, u, daily_cap_tokens=20_000)
    db.add(ChatUsage(user_id=u.id, day=access.nepal_today(), tokens_in=6_000, tokens_out=1_000, reserved=3_000))
    db.commit()
    s = _me(client, u)
    assert s["tokens_used_today"] == 10_000 and s["tokens_left_today"] == 10_000 and s["approx_questions_left"] == 1
    db.query(ChatUsage).update({"tokens_in": 30_000})
    db.commit()
    assert _me(client, u)["tokens_left_today"] == 0  # never negative


def test_changing_the_cap(client, db):
    admin, u = _user(db, UserRole.SUPER_ADMIN), _user(db)
    _approve(client, admin, u)
    r = client.put(f"{API}/admin/access/{u.id}/cap", json={"daily_cap_tokens": 250_000}, headers=_h(admin))
    assert r.status_code == 200 and r.json()["daily_cap_tokens"] == 250_000
    nobody = client.put(f"{API}/admin/access/{_user(db).id}/cap", json={"daily_cap_tokens": 1}, headers=_h(admin))
    assert nobody.status_code == 404


def test_an_expired_approval_is_expired_until_the_member_asks_again(client, db):
    admin, u = _user(db, UserRole.SUPER_ADMIN), _user(db)
    _approve(client, admin, u)
    db.query(ChatAccess).filter(ChatAccess.user_id == u.id).update({"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
    db.commit()
    s = _me(client, u)
    assert s["state"] == "expired" and s["allowed"] is False
    assert client.post(f"{API}/access/request", json={}, headers=_h(u)).json()["state"] == "requested"


def test_revoking_stops_access_and_the_member_can_ask_again(client, db):
    admin, u = _user(db, UserRole.SUPER_ADMIN), _user(db)
    _approve(client, admin, u)
    r = client.post(f"{API}/admin/access/{u.id}/revoke", headers=_h(admin))
    assert r.status_code == 200 and r.json()["state"] == "revoked" and not r.json()["allowed"]
    assert _me(client, u)["state"] == "revoked"
    assert client.post(f"{API}/access/request", json={}, headers=_h(u)).json()["state"] == "requested"
    assert client.post(f"{API}/admin/access/{_user(db).id}/revoke", headers=_h(admin)).status_code == 404


def test_an_active_approval_is_not_reset_by_asking_again(client, db):
    admin, u = _user(db, UserRole.SUPER_ADMIN), _user(db)
    _approve(client, admin, u, daily_cap_tokens=77_000)
    assert client.post(f"{API}/access/request", json={}, headers=_h(u)).json()["state"] == "approved"
    assert _me(client, u)["daily_cap_tokens"] == 77_000


def test_the_admin_list_filters_by_status(client, db):
    admin, a, b = _user(db, UserRole.SUPER_ADMIN), _user(db), _user(db)
    client.post(f"{API}/access/request", json={"note": "please"}, headers=_h(a))
    client.post(f"{API}/access/request", json={}, headers=_h(b))
    _approve(client, admin, b)
    waiting = client.get(f"{API}/admin/access?status=requested", headers=_h(admin)).json()
    assert [r["user_id"] for r in waiting] == [str(a.id)] and waiting[0]["request_note"] == "please"
    assert len(client.get(f"{API}/admin/access", headers=_h(admin)).json()) == 2
    assert client.get(f"{API}/admin/access?status=banana", headers=_h(admin)).status_code == 422


# ── super admin, read-only, kill switch, day rollover ───────────────────────────────────────────────────────

def test_a_super_admin_is_always_allowed_with_the_larger_cap_and_needs_no_row(client, db):
    admin = _user(db, UserRole.SUPER_ADMIN)
    s = _me(client, admin)
    assert s["allowed"] and s["daily_cap_tokens"] == 500_000
    assert db.query(ChatAccess).filter(ChatAccess.user_id == admin.id).count() == 0


def test_a_read_only_account_can_be_approved_and_is_flagged_so_write_tools_stay_off(client, db):
    admin, student = _user(db, UserRole.SUPER_ADMIN), _user(db, user_type="student")
    _approve(client, admin, student)
    s = _me(client, student)
    assert s["allowed"] is True and s["read_only"] is True
    assert _me(client, _user(db))["read_only"] is False


def test_the_kill_switch_beats_everything_including_a_super_admin(client, db):
    admin, u = _user(db, UserRole.SUPER_ADMIN), _user(db)
    _approve(client, admin, u)
    db.execute(text("UPDATE chat_settings SET enabled = false"))
    db.commit()
    assert _me(client, u)["state"] == "switched_off" and not _me(client, u)["allowed"]
    assert _me(client, admin)["state"] == "switched_off" and not _me(client, admin)["allowed"]
    db.execute(text("UPDATE chat_settings SET enabled = true"))
    db.commit()
    assert _me(client, u)["allowed"] is True


def test_the_usage_day_rolls_over_at_midnight_in_nepal_not_utc():
    before = datetime(2026, 11, 10, 18, 14, tzinfo=timezone.utc)   # 23:59 in Nepal (UTC+5:45)
    after = datetime(2026, 11, 10, 18, 15, tzinfo=timezone.utc)    # 00:00 next day in Nepal
    assert access.nepal_today(before) == date(2026, 11, 10)
    assert access.nepal_today(after) == date(2026, 11, 11)
