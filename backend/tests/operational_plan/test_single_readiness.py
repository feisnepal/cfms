"""The export gate and the step rail answer from one set of rules (owner, 2026-10-16).

Before: the rail, the export gate and a second sub-area check each kept their own idea of "ready", so a step could be
green and still block the export, and a refusal could come after the checklist was green.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.operational_plan import export_requirements as er
from app.services.operational_plan import prereq_check
from app.services.operational_plan.workflow_readiness import STEP_PREREQS


def _keys():
    return [r[0] for r in er.REQUIREMENTS]


def test_every_requirement_points_at_a_real_rail_step():
    assert set(er.STEP_FOR) == set(_keys())
    for key, step in er.STEP_FOR.items():
        assert step in STEP_PREREQS, f"{key} -> {step} is not a step of the rail"


def test_sub_areas_are_part_of_the_one_list_not_a_second_check():
    assert "sub_areas_planned" in _keys()


def _db():
    db = MagicMock()
    db.begin_nested.return_value.__enter__ = lambda *_: None
    db.begin_nested.return_value.__exit__ = lambda *_: False
    return db


def _all_done_except(monkeypatch, failing):
    patched = []
    for row in er.REQUIREMENTS:
        key = row[0]
        ok = key != failing
        patched.append(row[:-1] + ((lambda _db, _c, ok=ok: (ok, {"names": ["A"]} if not ok else {})),))
    monkeypatch.setattr(er, "REQUIREMENTS", patched)


def test_unplanned_sub_area_stops_the_export_through_the_same_gate(monkeypatch):
    _all_done_except(monkeypatch, "sub_areas_planned")
    result = er.export_requirements(_db(), "c")
    assert result["ready"] is False
    bad = [i for i in result["items"] if not i["done"]]
    assert [i["key"] for i in bad] == ["sub_areas_planned"] and bad[0]["step"] == "yearly"
    with pytest.raises(HTTPException) as exc:
        er.assert_export_ready(_db(), "c")
    assert exc.value.status_code == 409
    assert [i["key"] for i in exc.value.detail["items"]] == ["sub_areas_planned"]


def test_all_done_is_ready(monkeypatch):
    _all_done_except(monkeypatch, None)
    assert er.export_requirements(_db(), "c")["ready"] is True


def test_cost_benefit_rail_step_and_export_gate_ask_the_same_question(monkeypatch):
    assert STEP_PREREQS["cba"] == ("cba_calculated",)
    assert prereq_check._TAGS["cba_calculated"].predicate is prereq_check._has_cba_result
    seen = []
    monkeypatch.setattr(prereq_check, "_has_cba_result", lambda db, c: seen.append(c) or True)
    assert er._cba(MagicMock(), "calc")[0] is True and seen == ["calc"]


def test_export_route_no_longer_runs_a_separate_sub_area_check():
    import inspect

    from app.api import operational_plans

    src = inspect.getsource(operational_plans.export_operational_plan)
    assert "assert_export_ready" in src and "assert_sub_areas_planned" not in src
