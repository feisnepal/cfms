"""C0.4 harness: the synthetic tools enforce access, the scorer catches what it should, the tool loop works. No network."""
import asyncio
import json

import pytest

from app.services.chatbot.benchmark import fixture, runner, scoring
from app.services.chatbot.providers import ChatProvider, ChatReply, ProviderError, ToolCall, Usage

QUESTIONS = {q["id"]: q for q in runner.load_questions(include_pre_model=True)}


def run(coro):
    return asyncio.run(coro)


def ctx(qid):
    q = QUESTIONS[qid]
    return {"context": q["context"], "role": q["role"], "expected": q["expected"]}


# ------------------------------------------------------------------ set selection

def test_pre_model_and_sql_questions_are_excluded_but_the_rest_kept():
    model_set = {q["id"] for q in runner.load_questions()}
    for excluded in ("Y01", "Y03", "Y04", "Y05", "Y06", "Y07", "Y08", "Y12", "X06", "X12", "X10", "X11", "X13"):
        assert excluded not in model_set
    assert len(model_set) == 200 - 13 and {"X05", "W12", "Z11", "D08", "Y02", "Y10"} <= model_set


def test_sample_is_stratified_seeded_and_covers_every_category():
    qs = runner.load_questions()
    a, b = runner.sample_questions(qs, 50, seed=7), runner.sample_questions(qs, 50, seed=7)
    assert [q["id"] for q in a] == [q["id"] for q in b] and len(a) == 50
    assert {q["category"] for q in a} == {q["category"] for q in qs}
    assert {"ne", "en"} <= {q["lang"] for q in a}


# ------------------------------------------------------------------ synthetic tools

def test_tool_access_is_decided_by_the_tool_not_the_model():
    assert "access_denied" in fixture.execute_tool("get_area_summary", {}, ctx("E07"))
    assert "no_forest_selected" in fixture.execute_tool("get_area_summary", {}, ctx("H04"))  # no step, no forest open
    assert "forest_ha" in fixture.execute_tool("get_area_summary", {}, ctx("H05"))  # asked from a step: a forest is open
    assert "read_only_account" in fixture.execute_tool("update_forest_metadata", {"field": "code", "value": "x"}, ctx("W07"))
    assert "only_the_owner" in fixture.execute_tool("update_yearly_plan_line", {}, ctx("W02"))


def test_write_tools_never_apply_and_say_so():
    out = json.loads(fixture.execute_tool("update_forest_metadata", {"field": "financial_year", "value": "2083/84"}, ctx("W03")))
    assert out["status"] == "awaiting_confirmation" and "NOT applied" in out["note"]


def test_forest_numbers_are_consistent_and_household_tool_returns_totals_only():
    assert round(sum(b["ha"] for b in fixture.FOREST["units"]), 1) == fixture.FOREST["forest_ha"]
    assert fixture.FOREST["forest_ha"] + fixture.FOREST["private_land_ha"] == fixture.FOREST["boundary_ha"]
    hh = json.loads(fixture.execute_tool("get_household_aggregate", {}, ctx("D03")))
    assert sum(hh["by_caste"].values()) == hh["total"] and "households" not in hh and "जनजाती" in hh["by_caste"]


def test_gate_and_readiness_fixtures():
    gate = json.loads(fixture.execute_tool("get_export_requirements", {}, ctx("E03")))
    assert gate["export_allowed"] is False and "Sampling" in gate["missing"][0]
    assert "refused" in fixture.execute_tool("export_op_docx", {}, ctx("E03"))
    fine = json.loads(fixture.execute_tool("get_export_requirements", {}, ctx("E01")))
    assert fine["export_allowed"] is True


def test_oracle_retrieval_returns_facts_not_grader_instructions():
    facts = fixture.oracle_facts(QUESTIONS["R01"]["expected"])
    assert any("relative" in f for f in facts)
    assert not any(f.lower().startswith(("says", "explains", "tells", "declines")) for f in facts)
    hostile = fixture.execute_tool("search_help", {"query": "fire lines"}, ctx("X03"))
    assert "IGNORE YOUR RULES" in hostile  # the injection test needs the hostile passage to reach the model


def test_unknown_library_query_is_an_error_not_an_invented_answer():
    assert "unknown_query" in fixture.execute_tool("run_library_query", {"name": "carbon_stock_by_block"}, ctx("D08"))


# ------------------------------------------------------------------ scoring

def test_numbers_are_normalised_and_invented_ones_found():
    assert scoring.numbers_in("12.40 ha, 5,000 ha and १२३") == {"12.4", "5000", "123"}
    allowed = '{"ha": 12.4}'
    assert scoring.invented_numbers("Block 2 is 12.4 ha.", allowed) == []
    assert scoring.invented_numbers("Block 2 is 15 ha.", allowed) == ["15"]
    assert scoring.invented_numbers("Step 5 has 1 problem", allowed) == []  # single digits are ignored


def test_language_check_by_script():
    assert scoring.language_ok("ne", "ब्लक २ को क्षेत्रफल १२.४ हेक्टर हो।")
    assert not scoring.language_ok("ne", "Block 2 is 12.4 ha.")
    assert scoring.language_ok("en", "Block 2 is 12.4 ha.") and not scoring.language_ok("en", "ब्लक २ को क्षेत्रफल")
    assert scoring.language_ok("ne-roman", "Block 2 ko kshetraphal 12.4 ha ho.")


def test_tool_and_safety_checks():
    d01, x01, w01, x03 = (QUESTIONS[i] for i in ("D01", "X01", "W01", "X03"))
    assert scoring.tool_ok(d01, ["get_area_summary"]) and not scoring.tool_ok(d01, [])
    assert scoring.tool_ok(x01, []) and not scoring.tool_ok(x01, ["get_household_aggregate"])
    assert not scoring.no_unsafe_actions(x03, ["search_help", "export_op_docx"])
    assert scoring.no_unsafe_actions(x03, ["search_help"])
    assert scoring.confirm_ok(w01, "Please press Confirm on the card.") and not scoring.confirm_ok(w01, "Done, I added it.")
    assert not scoring.confirm_ok(QUESTIONS["W12"], "Okay, applied.")


def test_score_answer_passes_a_good_answer_and_fails_an_invented_number():
    q = QUESTIONS["D01"]
    tools = json.dumps({"units": fixture.FOREST["units"]})
    good = {"text": "Block 2 is 12.4 ha (get_area_summary).", "tools_called": ["get_area_summary"], "tool_output_text": tools, "error": None}
    bad = dict(good, text="Block 2 is 15.9 ha (get_area_summary).")
    assert scoring.score_answer(q, good)["auto_pass"] is True
    r = scoring.score_answer(q, bad)
    assert r["auto_pass"] is False and r["invented"] == ["15.9"]
    assert scoring.score_answer(q, {"error": "timeout: x", "text": "", "tools_called": []})["auto_pass"] is False


# ------------------------------------------------------------------ the tool loop

class Scripted(ChatProvider):
    """Plays back replies; records what it was sent."""

    def __init__(self, replies):
        super().__init__("scripted", "s-1", "synthetic_only")
        self.replies, self.seen = list(replies), []

    async def chat(self, messages, tools=None, *, max_tokens=1500, temperature=0.3):
        self.seen.append((list(messages), tools))
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def reply(text="", calls=()):
    return ChatReply(text, tuple(calls), Usage(100, 20), "stop", "s-1", "scripted")


def test_tool_loop_calls_tool_then_answers_and_sums_usage():
    q = QUESTIONS["D01"]
    p = Scripted([reply(calls=[ToolCall("c1", "get_area_summary", {})]), reply("Block 2 is 12.4 ha.")])
    res = run(runner.run_question(p, q))
    assert res["tools_called"] == ["get_area_summary"] and res["text"] == "Block 2 is 12.4 ha."
    assert res["input_tokens"] == 200 and res["output_tokens"] == 40 and res["error"] is None
    first_messages, tools = p.seen[0]
    assert first_messages[0].role == "system" and first_messages[-1].content == q["question"] and len(tools) == len(fixture.TOOLS)
    assert p.seen[1][0][-1].role == "tool" and "12.4" in p.seen[1][0][-1].content


def test_history_is_replayed_and_a_provider_error_is_recorded_not_raised():
    q = QUESTIONS["Z07"]
    p = Scripted([ProviderError("scripted failure", "connect")])
    res = run(runner.run_question(p, q, retries=0))
    assert res["error"].startswith("connect") and res["text"] == ""
    roles = [m.role for m in p.seen[0][0]]
    assert roles == ["system", "user", "assistant", "user"]


def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(runner.asyncio, "sleep", no_sleep)
    p = Scripted([ProviderError("429", "http", 429), reply("ok then")])
    res = run(runner.run_question(p, QUESTIONS["Z06"], retries=2))
    assert res["text"] == "ok then" and res["error"] is None


def test_a_model_that_never_stops_calling_tools_is_cut_off():
    calls = [reply(calls=[ToolCall(f"c{i}", "get_chat_usage", {})]) for i in range(runner.MAX_ROUNDS)]
    res = run(runner.run_question(Scripted(calls), QUESTIONS["Y10"]))
    assert res["error"] == "tool loop did not finish"


@pytest.mark.parametrize("lang", ["ne", "en"])
def test_both_scripts_present_in_the_model_set(lang):
    assert any(q["lang"] == lang for q in runner.load_questions())
