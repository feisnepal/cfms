"""CBA computation — NPV, IRR, B/C ratio, discounted payback.

Pure Python, **no ``numpy_financial``** (CBA_MODULE_PLAN.md D8). All rates are
percentages (``10.0`` == 10 %). Cash-flow lists are 1-indexed by position
(``cash_flows[0]`` is year 1).

Deviation from the recovered July build: ``compute_all`` feeds the **discounted**
net cash flow to ``compute_payback`` (the July code passed the undiscounted
series despite the docstring). Discounted payback is the correct CBA measure and
matches the function's name.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def compute_npv(cash_flows: List[float], discount_rate: float) -> float:
    """NPV = Σ CFₜ / (1 + r)ᵗ for t = 1..T."""
    r = discount_rate / 100.0
    return round(sum(cf / (1 + r) ** t for t, cf in enumerate(cash_flows, start=1)), 2)


def compute_irr(
    cash_flows: List[float],
    start_year: int = 1,
    guess: float = 0.10,
    max_iter: int = 100,
    tolerance: float = 1e-7,
) -> Optional[float]:
    """IRR (as a fraction, e.g. ``0.185``) via Newton-Raphson over
    ``cash_flows[start_year - 1:]``.

    Returns ``None`` when IRR is undefined — no sign change in the series (e.g.
    an all-positive plan), a zero derivative, a non-finite step, or no
    convergence within ``max_iter``.
    """
    cf = cash_flows[max(0, start_year - 1) :]
    if not cf or all(c >= 0 for c in cf) or all(c <= 0 for c in cf):
        return None

    rate = guess
    for _ in range(max_iter):
        npv = 0.0
        dnpv = 0.0
        for t, c in enumerate(cf, start=1):
            denom = (1 + rate) ** t
            npv += c / denom
            dnpv -= t * c / (denom * (1 + rate))
        if abs(dnpv) < 1e-12:
            return None
        new_rate = rate - npv / dnpv
        if not math.isfinite(new_rate) or new_rate <= -1:
            return None
        if abs(new_rate - rate) < tolerance:
            return round(new_rate, 4)
        rate = new_rate
    return None


def compute_bc_ratio(
    costs: List[float], benefits: List[float], discount_rate: float
) -> Optional[float]:
    """B/C = Σ Bₜ/(1+r)ᵗ ÷ Σ Cₜ/(1+r)ᵗ. ``None`` when PV(costs) == 0."""
    r = discount_rate / 100.0
    pv_costs = sum(c / (1 + r) ** t for t, c in enumerate(costs, start=1))
    pv_benefits = sum(b / (1 + r) ** t for t, b in enumerate(benefits, start=1))
    if pv_costs == 0:
        return None
    return round(pv_benefits / pv_costs, 4)


def compute_payback(discounted_net: List[float]) -> Optional[float]:
    """Discounted payback period — the year the cumulative discounted net cash
    flow first reaches ≥ 0, linearly interpolated within that year.

    The caller passes an **already-discounted** net series. Returns ``0.0`` when
    the first year is already ≥ 0 (an all-positive plan — this is a valid
    result, not a bug). ``None`` when the plan never breaks even within the
    horizon.
    """
    cumulative = 0.0
    for t, cf in enumerate(discounted_net, start=1):
        prev = cumulative
        cumulative += cf
        if cumulative >= 0:
            if prev >= 0:  # recovered before year t (only reachable at t == 1)
                return 0.0
            if cf > 0:
                return round((t - 1) + (-prev / cf), 2)
            return float(t)
    return None


def _year_series(items: List[Dict[str, Any]], horizon: int) -> List[float]:
    series = [0.0] * horizon
    for item in items:
        yf = max(1, int(item.get("year_from", 1) or 1))
        yt = min(int(item.get("year_to", 1) or 1), horizon)
        amt = float(item.get("amount_per_year") or 0.0)
        if amt == 0 and item.get("quantity") and item.get("unit_price"):
            amt = float(item["quantity"]) * float(item["unit_price"])
        for y in range(yf, yt + 1):
            series[y - 1] += amt
    return series


def compute_all(
    cost_items: List[Dict[str, Any]],
    benefit_items: List[Dict[str, Any]],
    discount_rate: float,
    time_horizon: int,
    irr_start_year: int = 1,
) -> Dict[str, Any]:
    """Full CBA from raw item lists.

    ``cost_items``    — dicts with ``year_from`` / ``year_to`` / ``amount_per_year``.
    ``benefit_items`` — as above; ``amount_per_year`` falls back to
                        ``quantity × unit_price`` when zero/unset.

    Returns ``npv`` / ``irr`` / ``benefit_cost_ratio`` / ``payback_period_years``
    / ``total_cost_pv`` / ``total_benefit_pv`` / ``cash_flow_data``.
    ``irr`` is a fraction (0.185, not 18.5).
    """
    horizon = max(1, int(time_horizon))
    costs = _year_series(cost_items, horizon)
    benefits = _year_series(benefit_items, horizon)
    net = [b - c for c, b in zip(costs, benefits)]

    r = discount_rate / 100.0
    disc_net = [n / (1 + r) ** t for t, n in enumerate(net, start=1)]

    irr = compute_irr(net, start_year=irr_start_year)
    bc = compute_bc_ratio(costs, benefits, discount_rate)
    payback = compute_payback(disc_net)

    pv_costs = round(sum(c / (1 + r) ** t for t, c in enumerate(costs, start=1)), 2)
    pv_benefits = round(
        sum(b / (1 + r) ** t for t, b in enumerate(benefits, start=1)), 2
    )

    cash_flow_data = [
        {
            "year": t + 1,
            "cost": round(costs[t], 2),
            "benefit": round(benefits[t], 2),
            "net": round(net[t], 2),
        }
        for t in range(horizon)
    ]

    return {
        "npv": compute_npv(net, discount_rate),
        "irr": round(irr, 4) if irr is not None else None,
        "benefit_cost_ratio": round(bc, 4) if bc is not None else None,
        "payback_period_years": (round(payback, 2) if payback is not None else None),
        "total_cost_pv": pv_costs,
        "total_benefit_pv": pv_benefits,
        "cash_flow_data": cash_flow_data,
    }
