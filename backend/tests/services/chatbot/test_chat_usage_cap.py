"""C1.3: the daily cap is enforced before every provider call, concurrently and at the Nepal-midnight boundary (reserve-then-settle, R2)."""
import asyncio
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.chat import ChatAccess, ChatUsage
from app.models.user import User, UserRole
from app.services.chatbot import access, usage
from app.services.chatbot.providers import ChatMessage, ChatReply, ProviderError, Usage

NOON = datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)          # 11:45 in Nepal, 10 Nov
LAST_MINUTE = datetime(2026, 11, 10, 18, 14, tzinfo=timezone.utc)  # 23:59 in Nepal, 10 Nov
NEXT_DAY = datetime(2026, 11, 10, 18, 15, tzinfo=timezone.utc)     # 00:00 in Nepal, 11 Nov


@pytest.fixture(autouse=True)
def _clean(db):
    db.execute(text("TRUNCATE chat_access, chat_usage, chat_messages CASCADE"))
    db.execute(text("UPDATE chat_settings SET enabled = true, pool_daily_tokens = NULL"))
    db.commit()
    yield


def _member(db, cap=10_000, role=UserRole.USER, approved=True):
    u = User(email=f"cap{uuid.uuid4().hex[:10]}@test.com", full_name="Cap Tester", role=role, hashed_password="x")
    db.add(u)
    db.flush()
    if approved and role != UserRole.SUPER_ADMIN:
        db.add(ChatAccess(user_id=u.id, status="approved", daily_cap_tokens=cap))
    db.commit()
    return u


def _row(db, user, day=None):
    db.expire_all()
    return db.get(ChatUsage, (user.id, day or access.nepal_today(NOON)))


def run(coro):
    return asyncio.run(coro)


# ── reserve / settle ────────────────────────────────────────────────────────────────────────────────────────

def test_a_reservation_holds_room_and_settling_swaps_it_for_the_real_figures(db):
    u = _member(db, cap=10_000)
    r = usage.reserve(db, u, 4_000, NOON)
    row = _row(db, u)
    assert row.reserved == 4_000 and row.tokens_in == 0 and row.messages == 1
    usage.settle(db, r, Usage(1_200, 300))
    row = _row(db, u)
    assert (row.reserved, row.tokens_in, row.tokens_out) == (0, 1_200, 300)


def test_call_n_plus_1_is_refused_with_what_the_screen_needs(db):
    u = _member(db, cap=10_000)
    usage.reserve(db, u, 4_000, NOON)
    usage.reserve(db, u, 4_000, NOON)
    with pytest.raises(usage.CapExceeded) as exc:
        usage.reserve(db, u, 4_000, NOON)
    e = exc.value
    assert e.code == usage.CODE_USER_CAP and e.tokens_left == 2_000
    assert e.resets_at == datetime(2026, 11, 10, 18, 15, tzinfo=timezone.utc)  # Nepal midnight, as an aware instant
    assert "midnight" in str(e) and "exports and uploads still work" in str(e)
    assert _row(db, u).reserved == 8_000  # the refused call held nothing


def test_a_failed_call_costs_nothing_and_frees_its_hold(db):
    u = _member(db, cap=10_000)
    r = usage.reserve(db, u, 9_000, NOON)
    usage.settle(db, r, None)
    row = _row(db, u)
    assert (row.reserved, row.tokens_in, row.tokens_out) == (0, 0, 0)
    usage.reserve(db, u, 9_000, NOON)  # the room is back


def test_real_use_above_the_estimate_is_recorded_and_blocks_the_next_call(db):
    u = _member(db, cap=10_000)
    r = usage.reserve(db, u, 2_000, NOON)
    usage.settle(db, r, Usage(9_000, 3_000))  # the model used more than the estimate
    assert _row(db, u).tokens_in + _row(db, u).tokens_out == 12_000
    with pytest.raises(usage.CapExceeded) as exc:
        usage.reserve(db, u, 100, NOON)
    assert exc.value.tokens_left == 0


def test_the_estimated_usage_flag_is_honoured_like_real_usage(db):
    u = _member(db)
    r = usage.reserve(db, u, 3_000, NOON)
    usage.settle(db, r, Usage(900, 100, estimated=True))
    assert _row(db, u).tokens_in == 900


# ── midnight in Nepal ───────────────────────────────────────────────────────────────────────────────────────

def test_counters_reset_at_midnight_nepal_time_not_utc(db):
    u = _member(db, cap=5_000)
    usage.reserve(db, u, 5_000, LAST_MINUTE)
    with pytest.raises(usage.CapExceeded):
        usage.reserve(db, u, 1, LAST_MINUTE)
    usage.reserve(db, u, 5_000, NEXT_DAY)  # one minute later: a new day, a full cap
    assert _row(db, u, access.nepal_today(NEXT_DAY)).reserved == 5_000
    assert _row(db, u, access.nepal_today(LAST_MINUTE)).reserved == 5_000


# ── who may reserve at all ──────────────────────────────────────────────────────────────────────────────────

def test_unapproved_revoked_and_switched_off_accounts_cannot_reserve(db):
    stranger = _member(db, approved=False)
    with pytest.raises(access.AccessError) as exc:
        usage.reserve(db, stranger, 100, NOON)
    assert exc.value.code == "chat.none"
    revoked = _member(db)
    db.query(ChatAccess).filter(ChatAccess.user_id == revoked.id).update({"status": "revoked"})
    db.commit()
    with pytest.raises(access.AccessError) as exc:
        usage.reserve(db, revoked, 100, NOON)
    assert exc.value.code == "chat.revoked"
    ok = _member(db)
    db.execute(text("UPDATE chat_settings SET enabled = false"))
    db.commit()
    with pytest.raises(access.AccessError) as exc:
        usage.reserve(db, ok, 100, NOON)
    assert exc.value.code == "chat.switched_off"
    assert db.query(ChatUsage).count() == 0  # a refusal never creates a usage row


def test_a_super_admin_has_the_larger_cap(db):
    admin = _member(db, role=UserRole.SUPER_ADMIN)
    usage.reserve(db, admin, 400_000, NOON)
    with pytest.raises(usage.CapExceeded) as exc:
        usage.reserve(db, admin, 200_000, NOON)
    assert exc.value.tokens_left == 100_000


# ── the shared pool ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_shared_daily_ceiling_stops_everyone_even_under_their_own_cap(db):
    a, b = _member(db, cap=50_000), _member(db, cap=50_000)
    db.execute(text("UPDATE chat_settings SET pool_daily_tokens = 10000"))
    db.commit()
    usage.reserve(db, a, 7_000, NOON)
    with pytest.raises(usage.CapExceeded) as exc:
        usage.reserve(db, b, 4_000, NOON)
    assert exc.value.code == usage.CODE_POOL and exc.value.tokens_left == 3_000
    usage.reserve(db, b, 3_000, NOON)  # what is left of the pool can still be used
    assert db.query(ChatUsage).count() == 2


# ── concurrency ─────────────────────────────────────────────────────────────────────────────────────────────

def test_ten_simultaneous_requests_cannot_exceed_the_cap(db):
    u = _member(db, cap=100_000)
    uid = u.id  # read once here: the main session's instance must not be touched from ten threads
    Session = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
    results, barrier = [], threading.Barrier(10, timeout=30)

    def worker():
        s = Session()
        try:
            me = s.get(User, uid)
            barrier.wait()
            try:
                usage.reserve(s, me, 30_000, NOON)
                results.append("ok")
            except usage.CapExceeded:
                results.append("refused")
        except Exception as exc:  # noqa: BLE001 -- surfaced by the assertion below instead of hanging the other threads
            results.append(f"error: {exc!r}")
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not [r for r in results if r.startswith("error")], results
    assert results.count("ok") == 3 and results.count("refused") == 7
    assert _row(db, u).reserved == 90_000


def test_simultaneous_requests_cannot_overspend_the_shared_pool(db):
    users = [_member(db, cap=100_000) for _ in range(8)]
    db.execute(text("UPDATE chat_settings SET pool_daily_tokens = 50000"))
    db.commit()
    Session = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
    results, barrier = [], threading.Barrier(8, timeout=30)

    def worker(uid):
        s = Session()
        try:
            me = s.get(User, uid)
            barrier.wait()
            try:
                usage.reserve(s, me, 20_000, NOON)
                results.append("ok")
            except usage.CapExceeded:
                results.append("refused")
        except Exception as exc:  # noqa: BLE001 -- surfaced by the assertion below instead of hanging the other threads
            results.append(f"error: {exc!r}")
        finally:
            s.close()

    threads = [threading.Thread(target=worker, args=(x.id,)) for x in users]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not [r for r in results if r.startswith("error")], results
    assert results.count("ok") == 2 and results.count("refused") == 6  # 2 x 20,000 fits in 50,000, a third would not
    assert db.execute(text("SELECT SUM(reserved) FROM chat_usage")).scalar() == 40_000


# ── the async wrapper around a provider call ────────────────────────────────────────────────────────────────

def _reply(tin, tout):
    return ChatReply("hello", (), Usage(tin, tout), "stop", "m", "p")


def test_with_reservation_settles_real_usage_on_success(db):
    u = _member(db, cap=10_000)

    async def call():
        return _reply(800, 200)

    out = run(usage.with_reservation(db, u, 3_000, call, NOON))
    row = _row(db, u)
    assert out.text == "hello" and (row.reserved, row.tokens_in, row.tokens_out) == (0, 800, 200)


def test_with_reservation_releases_the_hold_when_the_provider_fails(db):
    u = _member(db, cap=10_000)

    async def call():
        raise ProviderError("down", "connect")

    with pytest.raises(ProviderError):
        run(usage.with_reservation(db, u, 3_000, call, NOON))
    row = _row(db, u)
    assert (row.reserved, row.tokens_in, row.tokens_out) == (0, 0, 0)


def test_with_reservation_refuses_before_calling_the_provider_at_all(db):
    u = _member(db, cap=1_000)
    called = []

    async def call():
        called.append(1)
        return _reply(1, 1)

    with pytest.raises(usage.CapExceeded):
        run(usage.with_reservation(db, u, 5_000, call, NOON))
    assert called == []


def test_the_estimate_leans_high_for_devanagari_and_includes_the_reply_limit():
    english = usage.estimate_reservation([ChatMessage("user", "a" * 300)], 1_500)
    assert english == 100 + 1_500
    assert usage.estimate_reservation([ChatMessage("user", "ब" * 300)], 1_500) == english  # chars, not bytes: same guess, still conservative
    assert usage.estimate_reservation([ChatMessage("user", "a" * 300)], 1_500, tools_chars=3_000) == english + 1_000
