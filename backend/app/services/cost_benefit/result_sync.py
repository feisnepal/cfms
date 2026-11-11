"""Keep the cached ``CBAResult`` honest (ND-6).

The OP document reads the **cached** ``cba_results`` row. Line items move on
without it — ``auto_populate_cba`` regenerates the items but never recomputes
the result — so a plan can show a zero NPV (``0``) and no B/C ratio (NULL → the
no-data marker) while its items carry real numbers. Two days of DB evidence:
the subject scenario's result was computed 2026-10-11, its items created
2026-10-18.

This module detects that staleness (items newer than the cached result, or the
result missing while items exist) and rewrites the result from the current
items. Recomputing is pure Python (:mod:`engine`) and cheap — tens of items ×
the horizon — so it also runs safely on the OP data-collection path.

Nothing here commits: the caller owns the transaction (the OP collector commits
once at the end, and a rolled-back collection must leave the result untouched).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.cost_benefit import engine

logger = logging.getLogger(__name__)

# Items and their result are usually written in the same transaction, so their
# timestamps can land microseconds apart. A stamp within this window of the
# result is "the same write", not an edit — a real edit is days or hours away.
STALENESS_TOLERANCE = timedelta(seconds=1)


def engine_inputs(scn) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The ``engine`` input dicts for one scenario's line items."""
    costs = [
        {
            "year_from": c.year_from,
            "year_to": c.year_to,
            "amount_per_year": float(c.amount_per_year or 0),
        }
        for c in scn.cost_items
    ]
    benefits = [
        {
            "year_from": b.year_from,
            "year_to": b.year_to,
            "amount_per_year": float(b.amount_per_year or 0),
            "quantity": float(b.quantity) if b.quantity is not None else None,
            "unit_price": (float(b.unit_price) if b.unit_price is not None else None),
        }
        for b in scn.benefit_items
    ]
    return costs, benefits


def _as_utc(ts: Optional[datetime]) -> Optional[datetime]:
    if ts is None:
        return None
    if ts.tzinfo is None:  # the columns are tz-aware, but never assume
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def result_is_stale(
    result: Optional[Any], newest_item_ts: Optional[datetime]
) -> bool:
    """Is the cached result out of step with the items?

    - no result yet, but items exist → stale (never computed);
    - a result with no items left → stale (it describes deleted items);
    - items newer than ``computed_at`` (beyond the tolerance) → stale.
    """
    if result is None:
        return newest_item_ts is not None
    computed = _as_utc(getattr(result, "computed_at", None))
    if computed is None:
        return True
    newest = _as_utc(newest_item_ts)
    if newest is None:
        return True
    return (newest - computed) > STALENESS_TOLERANCE


def apply_result(result, out: Dict[str, Any]):
    """Write an ``engine.compute_all`` payload onto a ``CBAResult`` row."""
    result.npv = out["npv"]
    result.irr = out["irr"]  # stored as a fraction (0.1854)
    result.benefit_cost_ratio = out["benefit_cost_ratio"]
    result.payback_period_years = out["payback_period_years"]
    result.total_cost_pv = out["total_cost_pv"]
    result.total_benefit_pv = out["total_benefit_pv"]
    result.cash_flow_data = out["cash_flow_data"]
    result.computed_at = datetime.now(timezone.utc)
    return result


def recompute(scn, db, result=None):
    """Recompute and persist ``scn``'s result from its current items."""
    from app.models.cost_benefit import CBAResult

    costs, benefits = engine_inputs(scn)
    out = engine.compute_all(
        costs,
        benefits,
        float(scn.discount_rate),
        scn.time_horizon_years,
        scn.irr_start_year,
    )
    if result is None:
        result = db.query(CBAResult).filter(CBAResult.cba_id == scn.id).first()
    if result is None:
        result = CBAResult(cba_id=scn.id)
        db.add(result)
    apply_result(result, out)
    db.flush()
    return result


def ensure_result_current(db, scn):
    """Return ``scn``'s ``CBAResult``, recomputing it if the items have moved on.

    Never raises: a recompute failure is logged and the stored row (if any) is
    returned, so OP generation is unaffected.
    """
    from app.models.cost_benefit import CBAResult

    try:
        result = db.query(CBAResult).filter(CBAResult.cba_id == scn.id).first()
        newest = max(
            (i.updated_at for i in (*scn.cost_items, *scn.benefit_items) if i.updated_at),
            default=None,
        )
        if result_is_stale(result, newest):
            logger.info(
                "CBA: recomputing stale result for scenario=%s (items newer than "
                "computed_at=%s)",
                scn.id,
                getattr(result, "computed_at", None),
            )
            return recompute(scn, db, result)
        return result
    except Exception:  # noqa: BLE001 -- CBA must never break OP generation
        logger.warning(
            "CBA: staleness recompute failed for scenario=%s", scn.id, exc_info=True
        )
        try:
            return db.query(CBAResult).filter(CBAResult.cba_id == scn.id).first()
        except Exception:  # noqa: BLE001
            return None


def scenario_needs_recompute(db, calculation_id) -> bool:
    """Cheap check (max timestamps only) — used to distrust a stale OP cache."""
    from sqlalchemy import func

    from app.models.cost_benefit import (
        CBABenefitItem,
        CBACostItem,
        CBAResult,
        CostBenefitAnalysis,
    )

    try:
        base = (
            db.query(CostBenefitAnalysis)
            .filter(
                CostBenefitAnalysis.calculation_id == calculation_id,
                CostBenefitAnalysis.is_base_scenario.is_(True),
            )
            .first()
        )
        if base is None:
            return False
        result = db.query(CBAResult).filter(CBAResult.cba_id == base.id).first()
        newest = max(
            (
                ts
                for ts in (
                    db.query(func.max(CBACostItem.updated_at))
                    .filter(CBACostItem.cba_id == base.id)
                    .scalar(),
                    db.query(func.max(CBABenefitItem.updated_at))
                    .filter(CBABenefitItem.cba_id == base.id)
                    .scalar(),
                )
                if ts is not None
            ),
            default=None,
        )
        if result is None and newest is None:
            return False  # an empty scenario has nothing to cache
        return result_is_stale(result, newest)
    except Exception:  # noqa: BLE001 -- never force a recollect on a probe error
        logger.warning(
            "CBA: staleness probe failed for calc=%s", calculation_id, exc_info=True
        )
        return False
