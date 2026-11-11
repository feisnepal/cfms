"""Cost-Benefit Analysis OP data wiring (CBA_MODULE_PLAN.md P7).

``data_collector.get_cost_benefit_data`` never raises, returns a
JSON-serialisable dict keyed by the exact ``cba_*`` variable names, and fixes
the six rendering bugs from ``cba_variable_maintance_detail_plan.md``:
#1 ``Decimal('0.00')`` truthiness, #2 three distinct tables, #5 flat cash flow,
#6 the individual items are collected. Every ``cba_*`` variable is registered
under the Financial-Analysis section and routes through the resolver.
"""

from __future__ import annotations

import json
import uuid

from app.models.calculation import Calculation
from app.models.cost_benefit import (
    CBABenefitItem,
    CBACostItem,
    CBAResult,
    CostBenefitAnalysis,
)
from app.models.user import User, UserRole
from app.services.operational_plan import variable_registry as vr
from app.services.operational_plan.data_collector import (
    OP_DATA_CACHE_VERSION,
    get_cost_benefit_data,
)

_LIST_KEYS = (
    "cba_summary_table",
    "cba_cash_flow_table",
    "cba_cost_breakdown",
    "cba_benefit_breakdown",
)


def test_cache_version_bumped_to_20():
    assert OP_DATA_CACHE_VERSION >= 20


def test_empty_path_shape(db):
    d = get_cost_benefit_data(db, str(uuid.uuid4()))
    assert d["cba_available"] is False
    for k in _LIST_KEYS:
        assert d[k] == [], k
    assert d["cba_base_npv"] is None
    json.dumps(d)  # serialisable — no Decimal / datetime leaks


def _seed(db):
    u = User(
        email=f"cbaop{uuid.uuid4().hex[:8]}@t.com",
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
            ),
            CBACostItem(
                cba_id=s.id,
                category="Nursery",
                year_from=1,
                year_to=10,
                amount_per_year=5000,
            ),
            CBABenefitItem(
                cba_id=s.id,
                source="timber",
                year_from=1,
                year_to=10,
                amount_per_year=600000,
            ),
            CBABenefitItem(
                cba_id=s.id,
                source="fuelwood",
                year_from=1,
                year_to=10,
                amount_per_year=100000,
            ),
        ]
    )
    db.add(
        CBAResult(
            cba_id=s.id,
            npv=1842842,
            irr=None,  # all-positive net → undefined
            benefit_cost_ratio=1.6,
            payback_period_years=0,  # bug #1 — 0 must not become None
            total_cost_pv=1500000,
            total_benefit_pv=2400000,
            cash_flow_data=[
                {"year": y, "cost": 25000, "benefit": 700000, "net": 675000}
                for y in range(1, 11)
            ],
        )
    )
    db.commit()
    return c


def test_populated_tables_and_bug_fixes(db):
    calc = _seed(db)
    d = get_cost_benefit_data(db, str(calc.id))

    assert d["cba_available"] is True
    assert d["cba_base_bc_ratio"] == 1.6
    # bug #1 — payback 0.0 survives as 0, not None
    assert d["cba_base_payback"] == 0.0
    assert d["cba_base_irr"] is None  # genuinely undefined, not "0"

    # bug #2 — three distinct tables
    summary = d["cba_summary_table"]
    assert len(summary) == 8
    assert summary[0]["सूचकांक"].startswith("खुद वर्तमान")
    assert {row["लागत_शीर्षक"] for row in d["cba_cost_breakdown"]} == {
        "Harvest",
        "Nursery",
    }
    assert {row["लाभ_स्रोत"] for row in d["cba_benefit_breakdown"]} == {
        "timber",
        "fuelwood",
    }
    # breakdown percentages sum to ~100
    assert abs(sum(r["प्रतिशत"] for r in d["cba_cost_breakdown"]) - 100) < 0.5

    # bug #5 — cash flow is a flat list of scalars, no nested structure
    cf = d["cba_cash_flow_table"]
    assert len(cf) == 10
    assert set(cf[0].keys()) == {"वर्ष", "लागत", "लाभ", "शुद्ध"}
    assert all(not isinstance(v, (dict, list)) for v in cf[0].values())

    # bug #6 — breakdowns are non-empty because the items were read
    assert d["cba_cost_breakdown"] and d["cba_benefit_breakdown"]

    json.dumps(d)


def test_cba_vars_registered_under_financial_section():
    cba = vr.get_variables_by_source("cost_benefit")
    keys = {v.key for v in cba}
    for expect in (
        "cba_base_npv",
        "cba_summary_table",
        "cba_cash_flow_table",
        "cba_cost_breakdown",
        "cba_benefit_breakdown",
        "cba_verdict",
    ):
        assert expect in keys
    for v in cba:
        assert v.category == "A", v.key
        assert v.section == "S14", v.key
        assert v.label_ne and v.label_en, v.key


def test_list_vars_typed_list():
    for key in _LIST_KEYS:
        v = vr.get_variable(key)
        assert v is not None and v.var_type == "list", key


def test_resolver_and_docx_scan_include_cost_benefit():
    import inspect

    from app.services.operational_plan import op_docx_builder as odb
    from app.services.operational_plan.variable_resolver import VariableResolver

    assert '"cost_benefit": "cost_benefit"' in inspect.getsource(
        VariableResolver.__dict__["_resolve_category_a"]
    )
    assert '"cost_benefit"' in inspect.getsource(odb._resolve_var_from_raw)


def test_seed_tree_has_the_cba_subsection():
    from app.services.operational_plan.seed_data import get_default_seed_tree
    from app.services.operational_plan.tree_models import TreeOperations

    titles = {n.title_en for n in TreeOperations.flatten(get_default_seed_tree())}
    assert "Cost-Benefit Analysis" in titles
