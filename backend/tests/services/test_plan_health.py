"""Plan health (YEARLY_ACTIVITIES_WORKSPACE_PLAN §4.5): each code is raised by exactly the data that
should raise it, on the shapes the live data actually has."""

from __future__ import annotations

import itertools
import uuid

import pytest

from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.models.yearly_activities import (
    ActivityDrawnFeature,
    ActivityYearDetail,
    PotentialActivity,
    ProposedYearlyActivity,
)
from app.services.plan_health_service import compute_health
from datetime import datetime, timedelta, timezone


@pytest.fixture()
def calc(db):
    user = User(
        email=f"health{uuid.uuid4().hex[:8]}@test.com",
        full_name="Health Tester",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(user)
    db.flush()
    c = Calculation(
        id=str(uuid.uuid4()), user_id=user.id, uploaded_filename="h.csv", is_draft=False
    )
    db.add(c)
    db.commit()
    return c


_clock = itertools.count()


def _next_created_at() -> datetime:
    """A creation time one second after the last line's. The plan lists lines by creation time; two lines made in the same instant tie
    and fall back to random ids, which made the tests that read a line by its position pass or fail by chance."""
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=next(_clock))


def _line(
    db,
    calc,
    name="Nursery",
    *,
    requires_map=True,
    quantity=1,
    budget=5000,
    rows=None,
    reviewed=False,
    whole_forest=False,
):
    """A plan line. ``rows`` = {year: (quantity, budget)}; ``rows="all"`` = ten rows at the defaults."""
    master = PotentialActivity(
        progarms="P",
        activities=f"{name}-{uuid.uuid4().hex[:4]}",
        display_order=0,
        requires_map=requires_map,
        unit="वटा",
    )
    db.add(master)
    db.flush()
    line = ProposedYearlyActivity(
        calculation_id=calc.id,
        potential_activity_id=master.id,
        default_quantity=quantity,
        default_yearly_budget=budget,
        reviewed_at=datetime.now(timezone.utc) if reviewed else None,
        assign_to_all_blocks=whole_forest,
        created_at=_next_created_at(),
    )
    db.add(line)
    db.flush()
    if rows == "all":
        rows = {y: (quantity, budget) for y in range(1, 11)}
    for year, (q, b) in (rows or {}).items():
        db.add(
            ActivityYearDetail(
                proposed_activity_id=line.id,
                year_number=year,
                quantity=q,
                yearly_budget=b,
            )
        )
    db.commit()
    return line


def _codes(health, index=0):
    return [i["code"] for i in health["items"][index]["issues"]]


def test_an_empty_plan_says_add_the_first_activity(db, calc):
    health = compute_health(db, calc)
    assert health["summary"] == {
        "ready": 0,
        "needs_attention": 0,
        "total": 0,
        "total_budget": 0.0,
    }
    assert health["next_step"]["code"] == "EMPTY_PLAN"
    assert health["items"] == []


@pytest.mark.parametrize(
    "with_rows", [True, False], ids=["with year rows", "no year rows"]
)
def test_the_untouched_placeholder_is_flagged_with_or_without_year_rows(
    db, calc, with_rows
):
    """The live shape: 14 lines with ten 1 x 5,000 rows, 4 with none (same result: the default)."""
    _line(db, calc, rows="all" if with_rows else None)
    health = compute_health(db, calc)
    assert set(_codes(health)) == {"NO_LOCATION", "PLACEHOLDER_NUMBERS"}
    placeholder = next(
        i for i in health["items"][0]["issues"] if i["code"] == "PLACEHOLDER_NUMBERS"
    )
    assert placeholder["params"]["fields"] == ["budget", "quantity"]
    assert (
        health["items"][0]["state"] == "needs_location"
    )  # the first state that applies
    assert health["next_step"]["code"] == "NO_LOCATION"


def test_an_activity_that_needs_no_map_is_never_asked_for_a_location(db, calc):
    _line(db, calc, requires_map=False, rows="all")
    health = compute_health(db, calc)
    assert _codes(health) == ["PLACEHOLDER_NUMBERS"]
    assert health["items"][0]["state"] == "needs_numbers"


def test_a_confirmed_one_by_5000_line_is_ready(db, calc):
    _line(db, calc, requires_map=False, rows="all", reviewed=True)
    health = compute_health(db, calc)
    assert _codes(health) == []
    assert health["items"][0]["state"] == "ready"
    assert health["summary"] == {
        "ready": 1,
        "needs_attention": 0,
        "total": 1,
        "total_budget": 50000.0,
    }
    assert health["next_step"]["code"] == "ALL_READY"


def test_the_live_five_million_line_is_an_unusual_amount_not_a_placeholder(db, calc):
    """The live data has a real-looking 2 x 5,000,000 a year, in every year, never reviewed."""
    _line(db, calc, requires_map=False, quantity=2, budget=5_000_000, rows="all")
    health = compute_health(db, calc)
    assert _codes(health) == ["UNUSUAL_AMOUNT"]
    assert health["items"][0]["state"] == "needs_review"
    assert health["next_step"]["code"] == "UNUSUAL_AMOUNT"


def test_a_line_that_is_larger_than_twenty_times_the_others_median_is_unusual(db, calc):
    for _ in range(3):
        _line(
            db,
            calc,
            requires_map=False,
            quantity=3,
            budget=1000,
            rows="all",
            reviewed=True,
        )
    _line(
        db, calc, requires_map=False, quantity=3, budget=30_000, rows="all"
    )  # 30x the median of 1,000
    health = compute_health(db, calc)
    assert _codes(health, index=3) == ["UNUSUAL_AMOUNT"]
    assert all(_codes(health, index=i) == [] for i in range(3))


def test_confirm_acknowledges_an_unusual_amount_and_a_voluntary_line(db, calc):
    _line(
        db,
        calc,
        requires_map=False,
        quantity=2,
        budget=5_000_000,
        rows="all",
        reviewed=True,
    )
    _line(db, calc, requires_map=False, quantity=4, budget=0, rows="all", reviewed=True)
    health = compute_health(db, calc)
    assert all(item["issues"] == [] for item in health["items"])


def test_a_voluntary_line_that_was_not_confirmed_asks_whether_that_is_intended(
    db, calc
):
    _line(db, calc, requires_map=False, quantity=4, budget=0, rows="all")
    assert _codes(compute_health(db, calc)) == ["NO_BUDGET_ANY_YEAR"]


def test_a_line_with_zero_in_every_year_is_not_planned_at_all(db, calc):
    _line(
        db,
        calc,
        requires_map=False,
        quantity=1,
        budget=0,
        rows={y: (0, 0) for y in range(1, 11)},
        reviewed=True,
    )
    health = compute_health(db, calc)
    assert "NOT_PLANNED_ANY_YEAR" in _codes(health)
    assert health["items"][0]["state"] == "needs_numbers"
    assert health["next_step"]["code"] == "NOT_PLANNED_ANY_YEAR"


def test_a_feature_in_a_year_the_activity_does_not_plan_is_a_warning_with_the_years(
    db, calc
):
    line = _line(
        db,
        calc,
        rows={**{y: (0, 0) for y in range(4, 11)}},
        quantity=1,
        budget=500,
        reviewed=True,
    )
    db.add(
        ActivityDrawnFeature(
            proposed_activity_id=line.id,
            calculation_id=calc.id,
            feature_type="point",
            geometry="SRID=4326;POINT(85 27)",
            properties={"name": "spot", "years": [2, 5]},
        )
    )
    db.commit()
    health = compute_health(db, calc)
    issue = next(
        i for i in health["items"][0]["issues"] if i["code"] == "FEATURE_YEAR_UNPLANNED"
    )
    assert issue["params"] == {"years": [5]} and issue["severity"] == "warn"


def test_a_mappable_activity_with_a_place_or_marked_whole_forest_has_no_location_issue(
    db, calc
):
    placed = _line(db, calc, rows="all", reviewed=True)
    db.add(
        ActivityDrawnFeature(
            proposed_activity_id=placed.id,
            calculation_id=calc.id,
            feature_type="point",
            geometry="SRID=4326;POINT(85 27)",
            properties={"years": [1]},
        )
    )
    _line(db, calc, rows="all", reviewed=True, whole_forest=True)
    health = compute_health(db, calc)
    assert all("NO_LOCATION" not in _codes(health, i) for i in range(2))


def test_a_budget_only_edit_leaves_the_quantity_flagged(db, calc):
    """The hole the review found: the budget was typed, the quantity is still an invented 1."""
    _line(db, calc, requires_map=False, quantity=1, budget=80000, rows="all")
    health = compute_health(db, calc)
    issue = next(
        i for i in health["items"][0]["issues"] if i["code"] == "PLACEHOLDER_NUMBERS"
    )
    assert issue["params"]["fields"] == ["quantity"]


def test_the_next_step_is_chosen_in_the_documented_order(db, calc):
    _line(
        db, calc, requires_map=False, quantity=2, budget=5_000_000, rows="all"
    )  # unusual
    _line(db, calc, requires_map=False, rows="all")  # placeholder
    no_location = _line(
        db, calc, requires_map=True, quantity=3, budget=100, rows="all", reviewed=True
    )  # no location
    health = compute_health(db, calc)
    assert health["next_step"]["code"] == "NO_LOCATION"  # location first ...
    # (lines come back in id order, which is random: find the line by its id, not by position)
    assert health["next_step"]["activity_id"] == str(no_location.id)

    db.query(ProposedYearlyActivity).filter_by(id=no_location.id).update(
        {"assign_to_all_blocks": True}
    )
    db.commit()
    assert (
        compute_health(db, calc)["next_step"]["code"] == "PLACEHOLDER_NUMBERS"
    )  # ... then numbers


def test_cba_out_of_date_is_plan_level_and_does_not_change_states_or_counts(db, calc):
    _line(
        db, calc, requires_map=False, quantity=2, budget=500, rows="all", reviewed=True
    )
    plain = compute_health(db, calc)
    flagged = compute_health(db, calc, cba_out_of_date=True)
    assert [c["code"] for c in flagged["plan_issues"]] == ["CBA_OUT_OF_DATE"]
    assert plain["plan_issues"] == []
    assert flagged["summary"] == plain["summary"] and flagged["items"] == plain["items"]
    assert flagged["next_step"]["code"] == "ALL_READY"
