"""C1 message endpoint: access and cap are enforced, the help tool is the only tool, a failing provider falls through to the next, answers are stored."""
import uuid

import pytest
from sqlalchemy import text

from app.models.chat import ChatMessage as ChatMessageRow
from app.models.user import User, UserRole
from app.services.chatbot import help_search
from app.services.chatbot.providers import ChatProvider, ChatReply, ProviderError, ToolCall, Usage
from app.utils.auth import create_access_token

API = "/api/v1/chat"


class FakeProvider(ChatProvider):
    """Scripted replies; records every call. A ProviderError instance in the script is raised instead of returned."""

    def __init__(self, script, name="fake"):
        super().__init__(name, "fake-1", "synthetic_only")
        self.script, self.calls = list(script), []

    async def chat(self, messages, tools=None, *, max_tokens=1024, temperature=0.2):
        self.calls.append((list(messages), tools))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def reply(text="", calls=(), tin=100, tout=20):
    return ChatReply(text=text, tool_calls=tuple(calls), usage=Usage(tin, tout), finish_reason="stop", model="fake-1", provider="fake")


@pytest.fixture(autouse=True)
def _clean(db):
    db.execute(text("TRUNCATE chat_access, chat_usage, chat_messages CASCADE"))
    db.execute(text("UPDATE chat_settings SET enabled = true, pool_daily_tokens = NULL"))
    db.commit()
    help_search.load_cards(db)
    yield


def _user(db, role=UserRole.USER):
    u = User(email=f"msg{uuid.uuid4().hex[:10]}@test.com", full_name="Msg Tester", role=role, hashed_password="x")
    db.add(u)
    db.commit()
    return u


def _h(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'email': user.email})}"}


def _approved(client, db, cap=None):
    admin, u = _user(db, UserRole.SUPER_ADMIN), _user(db)
    client.post(f"{API}/access/request", json={}, headers=_h(u))
    assert client.post(f"{API}/admin/access/{u.id}/approve", json={"daily_cap_tokens": cap} if cap else {}, headers=_h(admin)).status_code == 200
    return u


def _use(monkeypatch, *providers):
    monkeypatch.setattr("app.api.chat.configured_providers", lambda: list(providers))


def _ask(client, user, message="How wide is a fire line?", **extra):
    return client.post(f"{API}/messages", json={"message": message, **extra}, headers=_h(user))


def test_needs_sign_in(client):
    assert client.post(f"{API}/messages", json={"message": "hi"}).status_code in (401, 403)


def test_unapproved_user_is_refused_and_the_provider_is_never_called(client, db, monkeypatch):
    p = FakeProvider([reply("hello")])
    _use(monkeypatch, p)
    r = _ask(client, _user(db))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "chat.none"
    assert p.calls == []


def test_approved_user_gets_an_answer_stored_and_charged(client, db, monkeypatch):
    u = _approved(client, db)
    _use(monkeypatch, FakeProvider([reply("It is 1.5 m on each side.", tin=300, tout=40)]))
    r = _ask(client, u)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"].startswith("It is 1.5 m") and body["state"]["tokens_used_today"] == 340
    rows = db.query(ChatMessageRow).filter_by(user_id=u.id).order_by(ChatMessageRow.created_at).all()
    assert [x.role for x in rows] == ["user", "assistant"] and rows[1].tokens_in == 300 and rows[1].provider == "fake"


def test_help_search_is_the_only_tool_and_its_passages_become_sources(client, db, monkeypatch):
    u = _approved(client, db)
    p = FakeProvider([reply(calls=[ToolCall("c1", "search_help", {"query": "fire line width"})]), reply("1.5 m per side.")])
    _use(monkeypatch, p)
    r = _ask(client, u)
    assert r.status_code == 200 and r.json()["sources"]
    assert [t.name for t in p.calls[0][1]] == ["search_help"]
    tool_msg = [m for m in p.calls[1][0] if m.role == "tool"][0]
    assert "REFERENCE_TEXT" in tool_msg.content


def test_an_unknown_tool_is_refused_not_run(client, db, monkeypatch):
    u = _approved(client, db)
    p = FakeProvider([reply(calls=[ToolCall("c1", "export_op_docx", {})]), reply("I cannot do that here.")])
    _use(monkeypatch, p)
    assert _ask(client, u).status_code == 200
    assert "unknown_tool" in [m for m in p.calls[1][0] if m.role == "tool"][0].content


def test_second_message_carries_the_history(client, db, monkeypatch):
    u = _approved(client, db)
    p = FakeProvider([reply("first answer"), reply("second answer")])
    _use(monkeypatch, p)
    sid = _ask(client, u).json()["session_id"]
    _ask(client, u, "and for rivers?", session_id=sid)
    sent = [m.content for m in p.calls[1][0]]
    assert "How wide is a fire line?" in sent and "first answer" in sent and sent[-1] == "and for rivers?"


def test_a_failing_provider_falls_through_to_the_next(client, db, monkeypatch):
    u = _approved(client, db)
    bad = FakeProvider([ProviderError("down", "http", 503)], name="bad")
    good = FakeProvider([reply("fine")], name="good")
    _use(monkeypatch, bad, good)
    r = _ask(client, u)
    assert r.status_code == 200 and r.json()["reply"] == "fine"
    assert db.query(ChatMessageRow).filter_by(user_id=u.id, role="assistant").one().provider == "good"


def test_every_provider_failing_is_a_503_and_charges_nothing(client, db, monkeypatch):
    u = _approved(client, db)
    _use(monkeypatch, FakeProvider([ProviderError("down", "timeout")]))
    r = _ask(client, u)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "chat.provider_unavailable"
    assert client.get(f"{API}/access/me", headers=_h(u)).json()["tokens_used_today"] == 0
    assert db.query(ChatMessageRow).filter_by(user_id=u.id).count() == 0


def test_no_provider_configured_is_a_503(client, db, monkeypatch):
    u = _approved(client, db)
    _use(monkeypatch)
    assert _ask(client, u).json()["detail"]["code"] == "chat.no_provider"


def test_a_spent_cap_is_a_429_and_the_provider_is_not_called(client, db, monkeypatch):
    u = _approved(client, db, cap=100)
    p = FakeProvider([reply("never")])
    _use(monkeypatch, p)
    r = _ask(client, u)
    assert r.status_code == 429 and r.json()["detail"]["code"].startswith("chat.")
    assert p.calls == []


def test_empty_and_overlong_questions_are_422(client, db, monkeypatch):
    u = _approved(client, db)
    _use(monkeypatch, FakeProvider([reply("x")]))
    assert _ask(client, u, "   ").status_code == 422
    assert _ask(client, u, "x" * 2500).status_code == 422


def test_feedback_only_on_your_own_assistant_answers(client, db, monkeypatch):
    u, other = _approved(client, db), _approved(client, db)
    _use(monkeypatch, FakeProvider([reply("an answer")]))
    mid = _ask(client, u).json()["message_id"]
    assert client.put(f"{API}/messages/{mid}/feedback", json={"value": -1}, headers=_h(other)).status_code == 404
    assert client.put(f"{API}/messages/{mid}/feedback", json={"value": -1}, headers=_h(u)).status_code == 204
    assert db.get(ChatMessageRow, uuid.UUID(mid)).feedback == -1
    db.expire_all()
    client.put(f"{API}/messages/{mid}/feedback", json={"value": 0}, headers=_h(u))
    db.expire_all()
    assert db.get(ChatMessageRow, uuid.UUID(mid)).feedback is None


# ── C1.6: what the super admin screen reads and sets ───────────────────────────────────────────────────────

def test_admin_list_shows_usage_and_thumbs_down_per_user(client, db, monkeypatch):
    admin = _user(db, UserRole.SUPER_ADMIN)
    u = _approved(client, db)
    _use(monkeypatch, FakeProvider([reply("an answer", tin=300, tout=40)]))
    mid = _ask(client, u).json()["message_id"]
    client.put(f"{API}/messages/{mid}/feedback", json={"value": -1}, headers=_h(u))
    row = [r for r in client.get(f"{API}/admin/access", headers=_h(admin)).json() if r["user_id"] == str(u.id)][0]
    assert (row["tokens_used_today"], row["messages_today"], row["thumbs_down_30d"]) == (340, 1, 1)


def test_settings_need_a_super_admin_and_the_kill_switch_stops_answers(client, db, monkeypatch):
    admin, u = _user(db, UserRole.SUPER_ADMIN), _approved(client, db)
    assert client.get(f"{API}/admin/settings", headers=_h(u)).status_code == 403
    assert client.put(f"{API}/admin/settings", json={"enabled": False}, headers=_h(u)).status_code == 403
    p = FakeProvider([reply("never")])
    _use(monkeypatch, p)
    r = client.put(f"{API}/admin/settings", json={"enabled": False, "pool_daily_tokens": 5000}, headers=_h(admin))
    assert r.status_code == 200 and r.json()["enabled"] is False and r.json()["pool_daily_tokens"] == 5000
    assert _ask(client, u).status_code == 403 and p.calls == []
    assert client.put(f"{API}/admin/settings", json={"enabled": True}, headers=_h(admin)).json()["pool_daily_tokens"] is None
    p.script = [reply("back")]
    assert _ask(client, u).status_code == 200


def test_settings_report_the_pool_used_today_and_refuse_a_negative_pool(client, db, monkeypatch):
    admin, u = _user(db, UserRole.SUPER_ADMIN), _approved(client, db)
    _use(monkeypatch, FakeProvider([reply("x", tin=200, tout=50)]))
    _ask(client, u)
    assert client.get(f"{API}/admin/settings", headers=_h(admin)).json()["pool_used_today"] == 250
    assert client.put(f"{API}/admin/settings", json={"enabled": True, "pool_daily_tokens": -1}, headers=_h(admin)).status_code == 422
