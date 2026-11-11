"""C0.3: the question sets are well-formed (both files together: unique ids, languages, every category, known tools and phases)."""
import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).parent
BASE = json.loads((HERE / "testset_v1.json").read_text(encoding="utf-8"))
EXTRA = json.loads((HERE / "testset_v1_extra.json").read_text(encoding="utf-8"))
EXTRA2 = json.loads((HERE / "testset_v1_extra2.json").read_text(encoding="utf-8"))
QUESTIONS = BASE["questions"] + EXTRA["questions"] + EXTRA2["questions"]
KNOWN_TOOLS = {t.strip() for t in BASE["how_to_read"]["tools"].split("Planned tool names (none exist yet).")[1].split(",")}
TYPES = {"answer", "tool", "confirm", "refuse", "unmatched"}
PHASES = {"C1", "C2", "C3", "C4", "C5", "C6", "C6U"}
CATEGORIES = {"help", "rules", "data", "export", "slides", "upload", "write", "safety", "robustness", "system"}
ROLES = {"user", "owner", "super_admin", "read_only"}
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def test_base_set_is_still_the_forty_the_owner_approved():
    assert len(BASE["questions"]) == 40
    assert [q["id"] for q in BASE["questions"]][:3] == ["H01", "H02", "H03"]


def test_combined_size_ids_languages_and_categories():
    assert len(EXTRA["questions"]) == 84 and len(EXTRA2["questions"]) == 76
    assert len(QUESTIONS) == 200
    assert len({q["id"] for q in QUESTIONS}) == len(QUESTIONS)
    langs = [q["lang"] for q in QUESTIONS]
    assert set(langs) == {"en", "ne", "ne-roman", "mixed"}
    assert langs.count("ne") >= 50
    assert {q["category"] for q in QUESTIONS} == CATEGORIES


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q["id"])
def test_each_question_is_complete(q):
    e = q["expected"]
    assert e["type"] in TYPES and e["phase"] in PHASES
    assert set(e["tools"]) <= KNOWN_TOOLS
    assert e["must_include"] or e["type"] == "refuse"
    assert q["role"] in ROLES
    has_dev = bool(DEVANAGARI.search(q["question"]))
    expected_dev = {"en": False, "ne": True, "ne-roman": False, "mixed": True}[q["lang"]]
    # X02 (a pasted SQL statement) is the one deliberate exception: it is English text labelled en
    assert has_dev == expected_dev
    if e["type"] in {"tool", "confirm"} and q["id"] not in {"X10"}:
        assert e["tools"]
    for turn in q.get("history", []):
        assert turn["role"] in {"user", "assistant"} and turn["text"]


def test_safety_write_and_follow_up_rules_are_covered():
    by_id = {q["id"]: q["expected"] for q in QUESTIONS}
    for refuse in ("X01", "X02", "X05", "X06", "X07", "X09", "X11", "X12", "X13", "X14", "X16", "X17", "X18", "X19", "W11", "Y01", "Y03", "Y04", "Y07", "Y08", "Y11", "W02", "W05", "W06", "W07", "W08", "E07", "U05"):
        assert by_id[refuse]["type"] == "refuse", refuse
    for confirm in ("W01", "W03", "W04", "X10"):
        assert by_id[confirm]["type"] == "confirm", confirm
    assert by_id["D08"]["type"] == "unmatched"
    assert sum(1 for q in QUESTIONS if q.get("history")) >= 3


def test_every_numbered_workflow_step_and_both_languages_are_covered_by_help_or_rules_questions():
    steps = {q["context"].get("step") for q in QUESTIONS if q["category"] in {"help", "rules", "data"}}
    for step in ("unified", "usergroup", "fieldbook", "sampling", "fieldinventory", "forestmetadata", "biodiversity",
                 "treemapping", "detaildescription", "areadetail", "sustainablefm", "cba", "yearly", "issuesubmit",
                 "ntfp", "analysis", "hazarderosion"):
        assert step in steps, step
