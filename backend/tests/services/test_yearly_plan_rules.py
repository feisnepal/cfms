"""The one definition of a planned year (YEARLY_ACTIVITIES plan §5.4).

Planned in a year <=> effective quantity > 0 OR effective budget > 0, where effective = the year
row's value when it is not NULL (a real 0 included), else the plan-line default.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.yearly_plan_rules import (
    effective_budget,
    effective_quantity,
    index_year_rows,
    is_planned,
    planned_years,
    total_budget,
)


def row(year, quantity=None, budget=None):
    return SimpleNamespace(year_number=year, quantity=quantity, yearly_budget=budget)


@pytest.mark.parametrize(
    "quantity, budget, planned",
    [
        (5, 5, True),  # planned and funded
        (5, 0, True),  # planned, no cost (voluntary work)
        (0, 5, True),  # funded, no countable output
        (0, 0, False),  # not planned this year
        (None, None, False),
        (
            Decimal("0.00"),
            Decimal("0.00"),
            False,
        ),  # Decimal('0.00') is falsy but is a value
    ],
)
def test_is_planned_matrix(quantity, budget, planned):
    assert is_planned(quantity, budget) is planned


def test_a_stored_zero_is_a_value_not_the_default():
    zero = row(1, quantity=Decimal(0), budget=Decimal("0.00"))
    assert effective_budget(zero, 5000) == 0
    assert effective_quantity(zero, 3) == 0


def test_null_and_missing_rows_fall_back_to_the_default():
    assert effective_budget(row(1, budget=None), 5000) == 5000
    assert effective_budget(None, 5000) == 5000
    assert effective_quantity(row(1, quantity=None), 3) == 3
    assert effective_quantity(None, 3) == 3


def test_a_line_with_no_year_rows_is_planned_in_all_ten_years():
    assert planned_years(1, 5000, []) == list(range(1, 11))
    assert planned_years(1, 5000, None) == list(range(1, 11))


def test_years_one_to_three_only_is_expressed_with_explicit_zero_rows():
    rows = [row(y, 0, 0) for y in range(4, 11)]
    assert planned_years(5, 60000, rows) == [1, 2, 3]


def test_budget_only_and_quantity_only_years_count():
    rows = [row(1, quantity=0, budget=10), row(2, quantity=4, budget=0), row(3, 0, 0)]
    assert planned_years(0, 0, rows)[:3] == [
        1,
        2,
    ]  # year 3 is 0/0 and unplanned; 4..10 use 0/0 defaults
    assert 3 not in planned_years(0, 0, rows)


def test_total_budget_respects_explicit_zero_years():
    # default 1000; year 1 is an explicit 0, year 2 overrides to 500, the other 8 use the default
    rows = [row(1, budget=Decimal(0)), row(2, budget=Decimal(500))]
    assert total_budget(1000, rows) == Decimal(500 + 8 * 1000)


def test_index_year_rows_accepts_a_mapping_or_an_iterable():
    rows = [row(1), row(2)]
    assert set(index_year_rows(rows)) == {1, 2}
    assert set(index_year_rows({3: row(3)})) == {3}
    assert index_year_rows(None) == {}


from app.services.yearly_plan_rules import budget_runs  # noqa: E402


def test_budget_runs_are_stretches_of_consecutive_equal_positive_budgets():
    rows = [row(y, budget=0) for y in range(4, 11)]
    assert budget_runs(60000, rows) == [(1, 3, Decimal(60000))]
    two = [
        row(2, budget=0),
        row(4, budget=0),
        *[row(y, budget=0) for y in range(5, 11)],
    ]
    assert budget_runs(500, two) == [(1, 1, Decimal(500)), (3, 3, Decimal(500))]
    changing = [row(3, budget=Decimal(200))] + [row(y, budget=0) for y in range(4, 11)]
    assert budget_runs(100, changing) == [(1, 2, Decimal(100)), (3, 3, Decimal(200))]


def test_a_zero_budget_makes_no_run_and_a_missing_row_uses_the_default():
    assert budget_runs(0, []) == []
    assert budget_runs(1000, []) == [(1, 10, Decimal(1000))]
    assert budget_runs(1000, [row(1, budget=Decimal(0))]) == [(2, 10, Decimal(1000))]
