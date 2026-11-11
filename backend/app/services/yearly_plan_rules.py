"""The one definition of a *planned year* for the yearly activity plan.

A plan line (``proposed_yearly_activities``) carries a default quantity and a default yearly
budget; a year row (``activity_year_details``) may override either for one year, and a year with
no row (or a NULL value) uses the default. A year is **planned** when its *effective* quantity is
greater than 0 **or** its effective budget is greater than 0; both 0 means *not planned that year*.

This is exactly how the operational plan's ``ya_*`` variables already count. It exists as one
module because three API totals, the plan-map collector and the map service each used to do it
their own way — and three of them treated a stored **0** as "use the default", which made an
unplanned year impossible to represent (YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.4, F2/F9/F11).

Keep this module free of database and web imports: it is pure so every consumer can share it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, List, Mapping, Tuple, Union

PLAN_YEARS = tuple(
    range(1, 11)
)  # constraint: the management plan horizon is years 1-10

_ZERO = Decimal(0)

Number = Union[int, float, Decimal, str, None]
YearRows = Union[None, Mapping[int, Any], Iterable[Any]]


def _num(value: Number) -> Decimal:
    if value is None:
        return _ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def index_year_rows(rows: YearRows) -> dict:
    """``{year_number: row}`` from a mapping or an iterable of rows with ``year_number``."""
    if rows is None:
        return {}
    if isinstance(rows, Mapping):
        return dict(rows)
    return {row.year_number: row for row in rows}


def effective_quantity(year_row: Any, default_quantity: Number) -> Decimal:
    """The year row's quantity when it is set (a real 0 included), else the plan-line default."""
    if year_row is not None and getattr(year_row, "quantity", None) is not None:
        return _num(year_row.quantity)
    return _num(default_quantity)


def effective_budget(year_row: Any, default_budget: Number) -> Decimal:
    """The year row's budget when it is set (a real 0 included), else the plan-line default.

    ``is not None`` — never truthiness: ``Decimal('0.00')`` is falsy, and treating it as "not set"
    is the defect this module exists to remove.
    """
    if year_row is not None and getattr(year_row, "yearly_budget", None) is not None:
        return _num(year_row.yearly_budget)
    return _num(default_budget)


def is_planned(quantity: Number, budget: Number) -> bool:
    """Planned in a year <=> quantity > 0 or budget > 0 (both 0 = not planned)."""
    return _num(quantity) > 0 or _num(budget) > 0


def planned_years(
    default_quantity: Number,
    default_budget: Number,
    year_rows: YearRows = None,
    years: Iterable[int] = PLAN_YEARS,
) -> List[int]:
    """The years (ascending) in which the line is planned, by effective values."""
    by_year = index_year_rows(year_rows)
    out: List[int] = []
    for year in years:
        row = by_year.get(year)
        if is_planned(
            effective_quantity(row, default_quantity),
            effective_budget(row, default_budget),
        ):
            out.append(year)
    return out


def total_budget(
    default_budget: Number,
    year_rows: YearRows = None,
    years: Iterable[int] = PLAN_YEARS,
) -> Decimal:
    """Sum of the effective yearly budgets over the plan years."""
    by_year = index_year_rows(year_rows)
    return sum(
        (effective_budget(by_year.get(year), default_budget) for year in years), _ZERO
    )


def line_planned_years(plan_line: Any, year_rows: YearRows = None) -> List[int]:
    """``planned_years`` for a ``ProposedYearlyActivity``-shaped object."""
    return planned_years(
        getattr(plan_line, "default_quantity", None),
        getattr(plan_line, "default_yearly_budget", None),
        year_rows,
    )


def budget_runs(
    default_budget: Number,
    year_rows: YearRows = None,
    years: Iterable[int] = PLAN_YEARS,
) -> List[Tuple[int, int, Decimal]]:
    """``[(year_from, year_to, amount_per_year)]``: stretches of CONSECUTIVE years with the same
    yearly budget above 0.

    A 0-budget year ends a run and makes none; the same amount in two separate stretches (Year 1 and
    Year 3) is two runs. The sum of ``amount * (to - from + 1)`` over the runs is the line's ten-year
    total. The cost-benefit analysis writes one cost row per run so its discounting sees *when* the
    money is spent, not a ten-year average (YEARLY_ACTIVITIES plan D28).
    """
    by_year = index_year_rows(year_rows)
    runs: List[Tuple[int, int, Decimal]] = []
    start = prev = None
    amount = _ZERO
    for year in years:
        budget = effective_budget(by_year.get(year), default_budget)
        if budget > 0 and start is not None and prev == year - 1 and budget == amount:
            prev = year
            continue
        if start is not None:
            runs.append((start, prev, amount))
            start = None
        if budget > 0:
            start, prev, amount = year, year, budget
    if start is not None:
        runs.append((start, prev, amount))
    return runs
