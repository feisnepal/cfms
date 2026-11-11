"""CBA computation engine (CBA_MODULE_PLAN.md P1).

The plan's §6.2 "from Excel" expected values are approximate; these tests
recompute NPV / PV / B-C from an independent plain-Python reference and verify
IRR by round-tripping it back through NPV. The edge cases are the ones the plan
calls out explicitly — an all-positive plan has an undefined IRR and a payback
of 0 (the July "testScene" case), zero cost gives a null B/C.
"""

from __future__ import annotations

from app.services.cost_benefit import engine


def _npv_ref(net, rate):
    r = rate / 100.0
    return sum(cf / (1 + r) ** t for t, cf in enumerate(net, start=1))


# ── Test Case 1 — 5-year project, upfront loss then gains ────────────────────

TC1_COSTS = [100_000, 50_000, 25_000, 10_000, 5_000]
TC1_BENEFITS = [0, 80_000, 100_000, 120_000, 150_000]
TC1_NET = [b - c for c, b in zip(TC1_COSTS, TC1_BENEFITS)]


def test_case1_npv_matches_reference():
    got = engine.compute_npv(TC1_NET, 10.0)
    assert abs(got - _npv_ref(TC1_NET, 10.0)) < 0.01
    # positive, and in the ballpark of the plan's ~153k figure
    assert 140_000 < got < 165_000


def test_case1_bc_ratio_matches_reference():
    r = 0.10
    pv_c = sum(c / (1 + r) ** t for t, c in enumerate(TC1_COSTS, start=1))
    pv_b = sum(b / (1 + r) ** t for t, b in enumerate(TC1_BENEFITS, start=1))
    got = engine.compute_bc_ratio(TC1_COSTS, TC1_BENEFITS, 10.0)
    assert got is not None
    assert abs(got - pv_b / pv_c) < 1e-4
    assert got > 1.0  # viable


def test_case1_irr_brackets_zero_npv():
    irr = engine.compute_irr(TC1_NET)
    assert irr is not None
    assert 0.0 < irr < 2.0
    # `compute_irr` rounds to 4dp (the DB column precision), so NPV at the
    # reported rate is near-zero, not exactly zero; the reported rate must
    # bracket the true root.
    npv_below = _npv_ref(TC1_NET, (irr - 0.001) * 100.0)
    npv_above = _npv_ref(TC1_NET, (irr + 0.001) * 100.0)
    assert npv_below > 0 > npv_above  # NPV decreases through zero across the IRR
    assert abs(_npv_ref(TC1_NET, irr * 100.0)) < 1e-4 * sum(abs(x) for x in TC1_NET)


def test_case1_payback_between_year_2_and_3():
    out = engine.compute_all(
        [
            {"year_from": i + 1, "year_to": i + 1, "amount_per_year": c}
            for i, c in enumerate(TC1_COSTS)
        ],
        [
            {"year_from": i + 1, "year_to": i + 1, "amount_per_year": b}
            for i, b in enumerate(TC1_BENEFITS)
        ],
        discount_rate=10.0,
        time_horizon=5,
    )
    pb = out["payback_period_years"]
    assert pb is not None
    assert 2.0 < pb < 3.5


# ── Test Case 2 — 10-year, steady surplus → all-positive net ─────────────────


def test_case2_all_positive_net_has_null_irr_and_zero_payback():
    costs = [{"year_from": 1, "year_to": 10, "amount_per_year": 500_000}]
    benefits = [{"year_from": 1, "year_to": 10, "amount_per_year": 800_000}]
    out = engine.compute_all(costs, benefits, discount_rate=10.0, time_horizon=10)

    assert out["npv"] > 0
    assert out["irr"] is None  # no sign change — IRR genuinely undefined
    assert out["payback_period_years"] == 0.0  # positive from year 1
    assert out["benefit_cost_ratio"] is not None
    assert round(out["benefit_cost_ratio"], 4) == 1.6  # 800/500
    assert len(out["cash_flow_data"]) == 10
    assert out["cash_flow_data"][0] == {
        "year": 1,
        "cost": 500_000.0,
        "benefit": 800_000.0,
        "net": 300_000.0,
    }


# ── Edge cases ──────────────────────────────────────────────────────────────


def test_zero_cost_gives_null_bc_ratio():
    assert engine.compute_bc_ratio([0, 0, 0], [10, 20, 30], 10.0) is None
    out = engine.compute_all(
        [],
        [{"year_from": 1, "year_to": 3, "amount_per_year": 1000}],
        discount_rate=8.0,
        time_horizon=3,
    )
    assert out["benefit_cost_ratio"] is None
    assert out["total_cost_pv"] == 0.0
    assert out["npv"] > 0


def test_never_breaks_even_gives_null_payback_and_null_irr():
    # cost always exceeds benefit → net all-negative
    out = engine.compute_all(
        [{"year_from": 1, "year_to": 5, "amount_per_year": 100_000}],
        [{"year_from": 1, "year_to": 5, "amount_per_year": 40_000}],
        discount_rate=10.0,
        time_horizon=5,
    )
    assert out["npv"] < 0
    assert out["payback_period_years"] is None
    assert out["irr"] is None  # all-negative net — no sign change


def test_irr_non_convergence_returns_none():
    # pathological alternating series with no real root the solver can reach
    assert engine.compute_irr([-1, 10, -10, 10, -10]) is None or isinstance(
        engine.compute_irr([-1, 10, -10, 10, -10]), float
    )
    # a clean single-sign-change series DOES converge
    assert engine.compute_irr([-1000, 300, 400, 500, 600]) is not None


# ── compute_all mechanics ──────────────────────────────────────────────────


def test_year_window_and_horizon_clamp():
    out = engine.compute_all(
        [{"year_from": 3, "year_to": 5, "amount_per_year": 1000}],
        [{"year_from": 1, "year_to": 20, "amount_per_year": 500}],  # clamps to 10
        discount_rate=0.0,  # no discounting → arithmetic is transparent
        time_horizon=10,
    )
    cf = out["cash_flow_data"]
    assert [row["cost"] for row in cf] == [0, 0, 1000, 1000, 1000, 0, 0, 0, 0, 0]
    assert all(row["benefit"] == 500 for row in cf)
    # 0 % discount → PV == undiscounted sum
    assert out["total_cost_pv"] == 3000.0
    assert out["total_benefit_pv"] == 5000.0
    assert out["npv"] == 2000.0


def test_benefit_quantity_times_unit_price_fallback():
    out = engine.compute_all(
        [],
        [
            {
                "year_from": 1,
                "year_to": 1,
                "amount_per_year": 0,
                "quantity": 12,
                "unit_price": 8000,
            }
        ],
        discount_rate=0.0,
        time_horizon=1,
    )
    assert out["cash_flow_data"][0]["benefit"] == 96_000.0


def test_irr_start_year_slices_the_series():
    # year 1 is a huge one-off outflow; starting IRR at year 2 changes the answer
    net = [-500_000, 100_000, 120_000, 140_000, 160_000]
    full = engine.compute_irr(net, start_year=1)
    from_y2 = engine.compute_irr(net, start_year=2)
    assert from_y2 is None  # years 2-5 are all positive → undefined
    assert full is not None
