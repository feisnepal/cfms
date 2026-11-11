"""The yearly-plan table on the map (YEARLY_ACTIVITIES plan P4, YA-4.5) must add up exactly as the operational
plan's ya_* variables do — for every year and overall, including the awkward shapes: a year at 0/0, a year
with only one of the two at 0, and a year with no row at all (it takes the line's default)."""

from __future__ import annotations

import uuid

import pytest

from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.models.yearly_activities import (
    ActivityYearDetail,
    PotentialActivity,
    ProposedYearlyActivity,
)
from app.services.operational_plan.data_collector import _collect_yearly_activities_data
from app.services.yearly_plan_service import plan_view


@pytest.fixture()
def calc(db):
    user = User(
        email=f"tot{uuid.uuid4().hex[:8]}@test.com",
        full_name="Totals Tester",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(user)
    db.flush()
    c = Calculation(
        id=str(uuid.uuid4()), user_id=user.id, uploaded_filename="t.csv", is_draft=False
    )
    db.add(c)
    db.commit()
    return c


def _line(db, calc, name, quantity, budget, rows):
    master = PotentialActivity(
        progarms="P",
        activities=f"{name}-{uuid.uuid4().hex[:4]}",
        display_order=0,
        requires_map=False,
        unit="वटा",
    )
    db.add(master)
    db.flush()
    line = ProposedYearlyActivity(
        calculation_id=calc.id,
        potential_activity_id=master.id,
        default_quantity=quantity,
        default_yearly_budget=budget,
    )
    db.add(line)
    db.flush()
    for year, (q, b) in rows.items():
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


def test_the_tables_year_totals_and_grand_total_equal_the_operational_plans(db, calc):
    # planned and funded in 1-2; planned with no cost in 3; funded with no output in 4; 0/0 in 5 — years 6-10 have no
    # row and take the default (quantity 2, NPR 1,000)
    _line(
        db,
        calc,
        "A",
        2,
        1000,
        {1: (2, 1000), 2: (2, 1000), 3: (5, 0), 4: (0, 700), 5: (0, 0)},
    )
    # a line with a zero default budget and one funded year
    _line(db, calc, "B", 1, 0, {y: (1, 0) for y in range(1, 11)} | {7: (1, 250)})
    # nothing planned at all in any year
    _line(db, calc, "C", 1, 5000, {y: (0, 0) for y in range(1, 11)})

    table = plan_view(db, calc)
    op = _collect_yearly_activities_data(db, str(calc.id))

    for year in range(1, 11):
        in_table = sum(line["years"][year - 1]["budget"] for line in table)
        assert in_table == pytest.approx(
            float(op["year_summary"][year - 1]["total_budget"])
        ), year

    grand_total = sum(line["total_budget"] for line in table)
    assert grand_total == pytest.approx(
        sum(float(y["total_budget"]) for y in op["year_summary"])
    )
    # and each line's own total is the sum of its years, so the last column and the grid can never disagree
    for line in table:
        assert line["total_budget"] == pytest.approx(
            sum(y["budget"] for y in line["years"])
        )


def test_a_year_with_no_row_takes_the_default_and_a_zero_is_not_a_default(db, calc):
    _line(
        db, calc, "A", 2, 1000, {1: (0, 0)}
    )  # year 1 explicitly 0/0; years 2-10 have no row

    (row,) = plan_view(db, calc)

    assert (
        row["years"][0]["quantity"],
        row["years"][0]["budget"],
        row["years"][0]["planned"],
    ) == (0.0, 0.0, False)
    assert (
        row["years"][1]["quantity"],
        row["years"][1]["budget"],
        row["years"][1]["planned"],
    ) == (2.0, 1000.0, True)
    assert (
        row["total_budget"] == 9000.0
    )  # nine years at the default; the explicit zero is not turned into 1000


def test_the_per_year_budget_variables_hold_all_ten_years(db, calc):
    """`ya_total_budget_by_year` and `ya_budget_year_trend` were keyed by a stale loop variable (always 10), so each held
    ONE entry — year 10 — in every plan document."""
    _line(db, calc, "A", 2, 1000, {1: (2, 1000), 2: (2, 2500), 3: (0, 0)})

    op = _collect_yearly_activities_data(db, str(calc.id))

    assert sorted(op["total_budget_by_year"], key=int) == [str(y) for y in range(1, 11)]
    assert sorted(op["budget_year_trend"], key=int) == [str(y) for y in range(1, 11)]
    assert op["total_budget_by_year"]["1"] == 1000.0
    assert op["total_budget_by_year"]["2"] == 2500.0
    assert (
        op["total_budget_by_year"]["3"] == 0.0
    )  # an explicit 0/0 year is not turned into the default
    assert op["total_budget_by_year"]["4"] == 1000.0  # no row: the line's default
    assert sum(op["total_budget_by_year"].values()) == op["total_ten_year_budget"]
    assert op["budget_year_trend"]["2"] == 2500.0
