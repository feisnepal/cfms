"""C1.8: private data is refused on the way in and removed on the way out; a tool cannot hand the model a field nobody listed."""
import pytest

from app.services.chatbot import leak
from tests.services.chatbot.test_chat_messages_api import API, FakeProvider, _ask, _approved, _h, _use, _user, reply  # noqa: F401
from tests.services.chatbot.test_chat_messages_api import _clean  # noqa: F401  (the autouse table cleaner)

from app.models.chat import ChatMessage as ChatMessageRow
from app.services.chatbot.providers import ToolCall

PRIVATE = [
    "Here is one household: Ram Bahadur Thapa, 9841000000, 27.7172, 85.3240. Please fix their caste entry.",
    "call me on +977-9851234567",
    "मेरो नम्बर ९८४१०००००० हो",
    "the plot is at 27.71720, 85.32400",
    "point 27.7172;85.3240 is the gate",
    "E 345678 N 3071234 is the corner",
    "३४५६७८, ३०७१२३४ यो कुना हो",
]
ORDINARY = [
    "How wide is a fire line? It is 1.5 m on each side.",
    "We have 312 households and 52.3 ha of user group land.",
    "The plan covers 2082/83, steps 1, 2 and 12.",
    "DBH 12.5, height 14.2",            # two numbers with one decimal: not a coordinate pair
    "area 155.0 ha and 148.6 ha",
    "फायर लाइन १.५ मिटर चौडा हुन्छ।",
    "Call the Fire lines panel from the sub-areas menu",
]


@pytest.mark.parametrize("text", PRIVATE)
def test_private_data_is_recognised_without_being_returned(text):
    kind = leak.private_data_in(text)
    assert kind in {"phone number", "coordinates"}


@pytest.mark.parametrize("text", ORDINARY)
def test_ordinary_questions_pass(text):
    assert leak.private_data_in(text) is None, text


def test_a_latitude_out_of_range_is_not_a_coordinate_pair():
    assert leak.private_data_in("values 123.456, 234.567") is None


def test_redact_removes_phone_coordinates_and_email_only():
    out = leak.redact("Call 9841000000 or mail ram@example.com; gate at 27.7172, 85.3240; width 1.5 m.")
    assert "9841000000" not in out and "ram@example.com" not in out and "27.7172" not in out
    assert "[phone removed]" in out and "[email removed]" in out and "[coordinates removed]" in out and "width 1.5 m" in out


def test_redact_leaves_ordinary_nepali_numerals_as_written():
    assert leak.redact("फायर लाइन १.५ मिटर चौडा हुन्छ।") == "फायर लाइन १.५ मिटर चौडा हुन्छ।"


def test_tool_result_keeps_only_allowed_fields_and_redacts_them():
    out = leak.filter_tool_result("search_help", {"reference": "ring 9841000000", "note": "n", "owner_phone": "9841000000", "rows": [{"a": 1}]})
    assert set(out) == {"reference", "note"} and "9841000000" not in out["reference"]


def test_unknown_tool_result_is_only_an_error():
    assert leak.filter_tool_result("export_op_docx", {"download": "/dl/1"}) == {"error": "unknown_tool"}


# ── through the endpoint ─────────────────────────────────────────────────────────────────────────────────────

def test_pasted_household_row_is_refused_not_stored_not_charged_and_never_reaches_the_provider(client, db, monkeypatch):
    u = _approved(client, db)
    p = FakeProvider([reply("never")])
    _use(monkeypatch, p)
    r = _ask(client, u, PRIVATE[0])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "chat.private_data"
    body = r.text
    assert "9841000000" not in body and "Thapa" not in body and "27.7172" not in body
    assert p.calls == [] and db.query(ChatMessageRow).filter_by(user_id=u.id).count() == 0
    assert client.get(f"{API}/access/me", headers=_h(u)).json()["tokens_used_today"] == 0


def test_a_model_reply_that_repeats_a_phone_number_is_redacted_before_it_is_stored_and_shown(client, db, monkeypatch):
    u = _approved(client, db)
    _use(monkeypatch, FakeProvider([reply("Ask the secretary on 9841000000 or at gate 27.7172, 85.3240.")]))
    r = _ask(client, u)
    assert r.status_code == 200 and "9841000000" not in r.json()["reply"] and "27.7172" not in r.json()["reply"]
    assert "9841000000" not in db.query(ChatMessageRow).filter_by(user_id=u.id, role="assistant").one().content


def test_a_forum_passage_with_a_phone_number_is_redacted_before_the_model_sees_it(client, db, monkeypatch):
    from sqlalchemy import text
    u = _approved(client, db)
    db.execute(text("UPDATE chat_help_chunks SET body = body || ' Ring 9841000000 for help.' WHERE id = 'fire-line-width'"))
    db.commit()
    p = FakeProvider([reply(calls=[ToolCall("c1", "search_help", {"query": "fire line width"})]), reply("1.5 m.")])
    _use(monkeypatch, p)
    assert _ask(client, u).status_code == 200
    tool_msg = [m for m in p.calls[1][0] if m.role == "tool"][0].content
    assert "9841000000" not in tool_msg and "phone removed" in tool_msg
