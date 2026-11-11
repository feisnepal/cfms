"""C1.1: the chat tables exist, enforce their rules, follow their user, and have no link to a forest (migration 147, applied by the conftest)."""
import uuid
from datetime import date

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.database import Base
from app.models.chat import ChatAccess, ChatMessage, ChatSettings, ChatUsage
from app.models.user import User, UserRole

CHAT_TABLES = ("chat_access", "chat_usage", "chat_messages", "chat_settings")


def _user(db):
    u = User(email=f"chat{uuid.uuid4().hex[:10]}@test.com", full_name="Chat Tester", role=UserRole.USER, hashed_password="x")
    db.add(u)
    db.flush()
    return u


def test_no_chat_table_links_to_a_forest_or_calculation(db):
    inspector = inspect(db.get_bind())
    for table in CHAT_TABLES:
        targets = {fk["referred_table"] for fk in inspector.get_foreign_keys(table)}
        assert targets <= {"users"}, (table, targets)
    for table in CHAT_TABLES:
        columns = {c["name"] for c in inspector.get_columns(table)}
        assert not {"calculation_id", "forest_id"} & columns, table


def test_access_defaults_and_status_check(db):
    u = _user(db)
    row = ChatAccess(user_id=u.id)
    db.add(row)
    db.flush()
    db.refresh(row)
    assert row.status == "requested" and row.daily_cap_tokens == 100_000 and row.plan == "approved" and row.requested_at
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(ChatAccess(user_id=_user(db).id, status="maybe"))
            db.flush()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(ChatAccess(user_id=_user(db).id, daily_cap_tokens=-1))
            db.flush()


def test_usage_is_one_row_per_user_per_day_and_never_negative(db):
    u = _user(db)
    db.add(ChatUsage(user_id=u.id, day=date(2026, 11, 10), tokens_in=10, tokens_out=5))
    db.flush()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(ChatUsage(user_id=u.id, day=date(2026, 11, 10)))
            db.flush()
    db.add(ChatUsage(user_id=u.id, day=date(2026, 11, 11)))  # another day is fine
    db.flush()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(ChatUsage(user_id=u.id, day=date(2026, 11, 12), reserved=-1))
            db.flush()


def test_message_rules_and_purge_keeps_counters(db):
    u = _user(db)
    sid = uuid.uuid4()
    m = ChatMessage(user_id=u.id, session_id=sid, role="assistant", content="hello", tool_names=["get_area_summary"], tokens_in=30, tokens_out=8)
    db.add(m)
    db.flush()
    db.refresh(m)
    assert m.tool_names == ["get_area_summary"] and m.feedback is None and m.created_at
    for bad in ({"role": "system"}, {"role": "user", "feedback": 5}):
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(ChatMessage(user_id=u.id, session_id=sid, **{"role": "user", **bad}))
                db.flush()
    # what the 30-day purge does (R13): text goes, counters stay
    db.execute(text("UPDATE chat_messages SET content = NULL, content_purged_at = now() WHERE id = :i"), {"i": m.id})
    db.refresh(m)
    assert m.content is None and m.content_purged_at and m.tokens_in == 30


def test_deleting_a_user_deletes_their_chat_rows(db):
    u = _user(db)
    db.add(ChatAccess(user_id=u.id))
    db.add(ChatUsage(user_id=u.id, day=date(2026, 11, 10)))
    db.add(ChatMessage(user_id=u.id, session_id=uuid.uuid4(), role="user", content="q"))
    db.flush()
    db.execute(text("DELETE FROM users WHERE id = :i"), {"i": u.id})
    for table in ("chat_access", "chat_usage", "chat_messages"):
        assert db.execute(text(f"SELECT count(*) FROM {table} WHERE user_id = :i"), {"i": u.id}).scalar() == 0


def test_settings_is_a_single_row_and_starts_enabled(db):
    row = db.get(ChatSettings, 1)
    assert row is not None and row.enabled is True and row.pool_daily_tokens is None
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(ChatSettings(id=2))
            db.flush()


def test_models_registered_with_the_metadata():
    assert set(CHAT_TABLES) <= set(Base.metadata.tables)
