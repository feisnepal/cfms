"""ND-6 — the OP must not render a stale CBA result.

``auto_populate_cba`` rewrites the line items but never recomputes the cached
``CBAResult``; the plan then showed NPV ``०`` and a missing B/C ratio while the
items carried real numbers. The collector now refreshes a stale result before
reading it, and the OP data cache is distrusted while the result is stale.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.calculation import Calculation
from app.models.cost_benefit import (
    CBABenefitItem,
    CBACostItem,
    CBAResult,
    CostBenefitAnalysis,
)
from app.models.user import User, UserRole
from app.services.cost_benefit import engine, result_sync
from app.services.operational_plan.data_collector import get_cost_benefit_data

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


class _Stub:
    def __init__(self, computed_at):
        self.computed_at = computed_at


def test_result_is_stale_truth_table():
    older = NOW - timedelta(days=7)
    # never computed but items exist
    assert result_sync.result_is_stale(None, NOW) is True
    # no result, no items → nothing to compute
    assert result_sync.result_is_stale(None, None) is False
    # items newer than the result (the real bug)
    assert result_sync.result_is_stale(_Stub(older), NOW) is True
    # same write (within the tolerance) → fresh
    assert (
        result_sync.result_is_stale(_Stub(NOW), NOW + timedelta(milliseconds=200))
        is False
    )
    # result computed after the last item edit → fresh
    assert result_sync.result_is_stale(_Stub(NOW), older) is False
    # result with every item deleted → describes data that is gone
    assert result_sync.result_is_stale(_Stub(NOW), None) is True
    # naive stamps are tolerated
    assert result_sync.result_is_stale(_Stub(older.replace(tzinfo=None)), NOW) is True


def _seed(db, *, item_ts, result_ts, result=None):
    u = User(
        email=f"cbasync{uuid.uuid4().hex[:8]}@t.com",
        full_name="x",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    c = Calculation(user_id=u.id, uploaded_filename="x.csv")
    db.add(c)
    db.flush()
    s = CostBenefitAnalysis(
        calculation_id=c.id,
        name="Base",
        is_base_scenario=True,
        discount_rate=10,
        time_horizon_years=10,
    )
    db.add(s)
    db.flush()
    db.add_all(
        [
            CBACostItem(
                cba_id=s.id,
                category="Harvest",
                year_from=1,
                year_to=10,
                amount_per_year=20000,
                created_at=item_ts,
                updated_at=item_ts,
            ),
            CBABenefitItem(
                cba_id=s.id,
                source="timber",
                year_from=1,
                year_to=10,
                amount_per_year=600000,
                created_at=item_ts,
                updated_at=item_ts,
            ),
        ]
    )
    if result is not None:
        db.add(CBAResult(cba_id=s.id, computed_at=result_ts, **result))
    db.commit()
    return c, s


_ITEMS = (
    [{"year_from": 1, "year_to": 10, "amount_per_year": 20000.0}],
    [
        {
            "year_from": 1,
            "year_to": 10,
            "amount_per_year": 600000.0,
            "quantity": None,
            "unit_price": None,
        }
    ],
)


def test_collector_recomputes_stale_zero_result(db):
    """The exact bug: a zero result computed a week before the items existed."""
    calc, scn = _seed(
        db,
        item_ts=NOW - timedelta(days=7),
        result_ts=NOW - timedelta(days=14),
        result={
            "npv": 0,
            "irr": None,
            "benefit_cost_ratio": None,
            "payback_period_years": 0,
            "total_cost_pv": 0,
            "total_benefit_pv": 0,
            "cash_flow_data": [
                {"year": y, "cost": 0, "benefit": 0, "net": 0} for y in range(1, 11)
            ],
        },
    )

    d = get_cost_benefit_data(db, str(calc.id))

    expected = engine.compute_all(*_ITEMS, 10.0, 10, 1)
    assert d["cba_base_npv"] == round(expected["npv"]) > 0  # cba_base_npv is _num(npv, 0)
    assert d["cba_base_bc_ratio"] == expected["benefit_cost_ratio"] is not None
    assert d["cba_verdict"].startswith("यो योजना आर्थिक रूपले व्यवहार्य")

    stored = db.query(CBAResult).filter(CBAResult.cba_id == scn.id).one()
    assert float(stored.npv) == expected["npv"]
    assert float(stored.total_benefit_pv) == expected["total_benefit_pv"]
    # the stamp is refreshed, otherwise every later read would recompute again
    assert result_sync._as_utc(stored.computed_at) > result_sync._as_utc(NOW)


def test_collector_keeps_fresh_result(db):
    calc, scn = _seed(
        db,
        item_ts=NOW - timedelta(days=2),
        result_ts=NOW,
        result={
            "npv": 1842842,
            "irr": None,
            "benefit_cost_ratio": 1.6,
            "payback_period_years": 0,
            "total_cost_pv": 1500000,
            "total_benefit_pv": 2400000,
            "cash_flow_data": [{"year": 1, "cost": 1, "benefit": 2, "net": 1}],
        },
    )

    d = get_cost_benefit_data(db, str(calc.id))

    assert d["cba_base_npv"] == 1842842
    assert d["cba_base_bc_ratio"] == 1.6
    stored = db.query(CBAResult).filter(CBAResult.cba_id == scn.id).one()
    assert float(stored.npv) == 1842842


def test_scenario_needs_recompute_probe(db):
    calc, scn = _seed(
        db,
        item_ts=NOW,
        result_ts=NOW - timedelta(days=7),
        result={"npv": 0, "total_cost_pv": 0, "total_benefit_pv": 0},
    )
    assert result_sync.scenario_needs_recompute(db, calc.id) is True

    recent, recent_scn = _seed(
        db,
        item_ts=NOW - timedelta(days=2),
        result_ts=NOW,
        result={"npv": 1, "total_cost_pv": 1, "total_benefit_pv": 2},
    )
    assert result_sync.scenario_needs_recompute(db, recent.id) is False

    # unknown calculation / empty scenario → never force a recollect
    assert result_sync.scenario_needs_recompute(db, uuid.uuid4()) is False

    u = User(
        email=f"cbaempty{uuid.uuid4().hex[:8]}@t.com",
        full_name="x",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    empty = Calculation(user_id=u.id, uploaded_filename="x.csv")
    db.add(empty)
    db.flush()
    db.add(
        CostBenefitAnalysis(
            calculation_id=empty.id,
            name="Base",
            is_base_scenario=True,
            discount_rate=10,
            time_horizon_years=10,
        )
    )
    db.commit()
    assert result_sync.scenario_needs_recompute(db, empty.id) is False
