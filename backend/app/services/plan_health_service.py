"""Plan health: the server says what is missing (YEARLY_ACTIVITIES_WORKSPACE_PLAN §4.5).

Both screens, the Next-step card and the Plan check read this one document, so they cannot disagree.
Issues carry **codes and parameters, never sentences**: the frontend turns them into words from one
i18n catalogue, so the wording can be edited in one place (§4.6).

States (the first that applies): needs_location -> needs_numbers -> needs_review -> ready.
"""

from __future__ import annotations

from statistics import median
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from ..models.calculation import Calculation
from ..models.yearly_activities import ActivityDrawnFeature
from . import yearly_plan_service as plan

# D23: an "unusual amount" is a yearly budget above ~20x the median of the plan's other activities,
# or above NPR 10,00,000 a year. Only ever a check, never an error.
UNUSUAL_ABSOLUTE = 1_000_000.0
UNUSUAL_MEDIAN_FACTOR = 20.0
_MIN_OTHERS_FOR_MEDIAN = 3

STATE_ORDER = ("needs_location", "needs_numbers", "needs_review")
_CODE_STATE = {
    "NO_LOCATION": "needs_location",
    "PLACEHOLDER_NUMBERS": "needs_numbers",
    "NOT_PLANNED_ANY_YEAR": "needs_numbers",
    "NO_BUDGET_ANY_YEAR": "needs_review",
    "FEATURE_YEAR_UNPLANNED": "needs_review",
    "UNUSUAL_AMOUNT": "needs_review",
}
_ACTION = {
    "NO_LOCATION": "show_on_map",
    "PLACEHOLDER_NUMBERS": "enter_numbers",
    "NOT_PLANNED_ANY_YEAR": "choose_years",
    "NO_BUDGET_ANY_YEAR": "confirm",
    "FEATURE_YEAR_UNPLANNED": "plan_year",
    "UNUSUAL_AMOUNT": "check_amount",
}
_SEVERITY = {
    "NO_LOCATION": "todo",
    "PLACEHOLDER_NUMBERS": "todo",
    "NOT_PLANNED_ANY_YEAR": "todo",
    "NO_BUDGET_ANY_YEAR": "info",
    "FEATURE_YEAR_UNPLANNED": "warn",
    "UNUSUAL_AMOUNT": "check",
}
# The Next-step card shows exactly one thing, chosen in this order (§4.3): a mappable activity with no
# place, then placeholder / missing numbers, then something to double-check.
_NEXT_STEP_ORDER = (
    "NO_LOCATION",
    "PLACEHOLDER_NUMBERS",
    "NOT_PLANNED_ANY_YEAR",
    "FEATURE_YEAR_UNPLANNED",
    "UNUSUAL_AMOUNT",
    "NO_BUDGET_ANY_YEAR",
)


def _issue(code: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": _SEVERITY[code],
        "params": params or {},
        "action": _ACTION[code],
    }


def _max_yearly_budget(line: Dict[str, Any]) -> float:
    return max((y["budget"] for y in line["years"] if y["planned"]), default=0.0)


def _feature_years(db: Session, line_ids: List[UUID]) -> Dict[str, List[List[int]]]:
    out: Dict[str, List[List[int]]] = {}
    if not line_ids:
        return out
    rows = (
        db.query(
            ActivityDrawnFeature.proposed_activity_id, ActivityDrawnFeature.properties
        )
        .filter(
            ActivityDrawnFeature.proposed_activity_id.in_(line_ids),
            ActivityDrawnFeature.deleted_at.is_(None),
        )
        .all()
    )
    for line_id, props in rows:
        years = [
            int(y)
            for y in ((props or {}).get("years") or [])
            if isinstance(y, (int, float))
        ]
        out.setdefault(str(line_id), []).append(years)
    return out


def line_issues(
    line: Dict[str, Any], feature_years: List[List[int]], others_max: List[float]
) -> List[Dict[str, Any]]:
    """The issues of one plan line (a ``plan_view`` item)."""
    issues: List[Dict[str, Any]] = []
    reviewed = line["reviewed_at"] is not None
    planned = set(line["planned_years"])

    if line["location_mode"] == "needs_location":
        issues.append(_issue("NO_LOCATION"))
    if line["placeholder_fields"]:
        issues.append(
            _issue("PLACEHOLDER_NUMBERS", {"fields": line["placeholder_fields"]})
        )
    if not planned:
        issues.append(_issue("NOT_PLANNED_ANY_YEAR"))
    bad_years = sorted(
        {y for years in feature_years for y in years if y not in planned}
    )
    if bad_years:
        issues.append(_issue("FEATURE_YEAR_UNPLANNED", {"years": bad_years}))
    # These two are acknowledged by Confirm ("these numbers are right"), which is how a genuinely
    # voluntary or genuinely large line stops being raised.
    if not reviewed:
        peak = _max_yearly_budget(line)
        if planned and all(y["budget"] == 0 for y in line["years"] if y["planned"]):
            issues.append(_issue("NO_BUDGET_ANY_YEAR"))
        big_vs_others = len(
            others_max
        ) >= _MIN_OTHERS_FOR_MEDIAN and peak > UNUSUAL_MEDIAN_FACTOR * median(
            others_max
        )
        if peak > UNUSUAL_ABSOLUTE or big_vs_others:
            issues.append(_issue("UNUSUAL_AMOUNT", {"yearly_budget": peak}))
    return issues


def state_of(issues: List[Dict[str, Any]]) -> str:
    states = {_CODE_STATE[i["code"]] for i in issues if i["code"] in _CODE_STATE}
    for state in STATE_ORDER:
        if state in states:
            return state
    return "ready"


def compute_health(
    db: Session, calculation: Calculation, *, cba_out_of_date: bool = False
) -> Dict[str, Any]:
    """The plan-health document of §4.5."""
    lines = plan.plan_view(db, calculation)
    feature_years = _feature_years(db, [UUID(item["id"]) for item in lines])
    peaks = {item["id"]: _max_yearly_budget(item) for item in lines}

    items: List[Dict[str, Any]] = []
    for line in lines:
        others = [v for k, v in peaks.items() if k != line["id"] and v > 0]
        issues = line_issues(line, feature_years.get(line["id"], []), others)
        items.append(
            {
                "activity_id": line["id"],
                "potential_activity_id": line["potential_activity_id"],
                "activity": line["activity"],
                "state": state_of(issues),
                "issues": issues,
            }
        )

    ready = sum(1 for i in items if i["state"] == "ready")
    plan_issues: List[Dict[str, Any]] = []
    if cba_out_of_date:
        # informational only; it never affects an activity's state or the ready count
        plan_issues.append(
            {
                "code": "CBA_OUT_OF_DATE",
                "severity": "info",
                "params": {},
                "action": "update_cba",
            }
        )

    # Owner rule 2026-10-08: a sub-area must be tied to the plan (private land excepted). Unlike every other issue this one
    # BLOCKS issuing the plan; the user may add the plan later.
    from . import sub_area_plan

    unplanned = sub_area_plan.sub_areas_needing_plan(sub_area_plan.sub_area_plan_status(db, calculation))
    if unplanned:
        plan_issues.append(
            {
                "code": "SUB_AREA_NO_PLAN",
                "severity": "blocking",
                "params": {
                    "count": len(unplanned),
                    "sub_areas": [{"id": u["id"], "name": u["name"], "state": u["state"]} for u in unplanned],
                },
                "action": "plan_sub_areas",
            }
        )

    return {
        "summary": {
            "ready": ready,
            "needs_attention": len(items) - ready,
            "total": len(items),
            # the ten-year budget of the whole plan, for the "your plan is ready" message
            "total_budget": round(sum(line["total_budget"] for line in lines), 2),
        },
        "next_step": _next_step(items),
        "items": items,
        "plan_issues": plan_issues,
    }


def _next_step(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not items:
        return {
            "code": "EMPTY_PLAN",
            "activity_id": None,
            "params": {},
            "action": "add_first_activity",
        }
    for code in _NEXT_STEP_ORDER:
        for item in items:
            for issue in item["issues"]:
                if issue["code"] == code:
                    return {
                        "code": code,
                        "activity_id": item["activity_id"],
                        "activity": item["activity"],
                        "params": issue["params"],
                        "action": issue["action"],
                    }
    return {
        "code": "ALL_READY",
        "activity_id": None,
        "params": {},
        "action": "create_plan",
    }
