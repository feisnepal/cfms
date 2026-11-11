"""CBA auto-populate / re-populate sync (CBA_MODULE_PLAN.md P2).

Reads the *current* system state and syncs the auto-sourced cost / benefit rows
of one scenario. A row is **auto** when ``source_link`` is set — it is
overwritten on every re-populate and deleted when its source disappears. A row
is **manual** when ``source_link IS NULL`` — it is never created, changed or
removed here.

Sources:
- costs   ← ``ProposedYearlyActivity`` (one row per activity; ``amount_per_year``
            = the 10-year average budget; ``source_link = "activity:{uuid}"``).
- benefits ← ``FieldInventoryBlockSummary`` timber / fuelwood / carbon per block
            (``source_link = "block:{name}:{kind}"``), and the owner's NTFP harvest
            plan (``source_link = "ntfp:{species_key}:{part}"``).

Re-populate is idempotent: a second call with unchanged system data makes no
inserts or deletes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Set
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.yearly_plan_rules import budget_runs
from app.models.cost_benefit import (
    CBABenefitItem,
    CBACostItem,
    CostBenefitAnalysis,
)

logger = logging.getLogger(__name__)

_PLAN_YEARS = list(range(1, 11))  # the plan horizon; activity cost rows span the runs of budget within it

# Fallback depot / market rates, used when the scenario's ``default_rates`` has
# no entry. The UI's Default Rates panel edits ``default_rates``; this is only
# the floor.
FALLBACK_RATES: Dict[str, float] = {
    "timber_sal": 12000.0,
    "timber_mixed": 8000.0,
    "timber_softwood": 5000.0,
    "fuelwood": 1500.0,
    "poles": 300.0,
    "carbon": 3000.0,
    "grass": 500.0,
    "bedding": 300.0,
}


def _load_org_rates(db: Session) -> Dict[str, float]:
    """The org-wide ``global`` rate row (CBA_MODULE_PLAN.md P8), or ``{}``. Wrapped
    in a SAVEPOINT so a bare test DB missing the table can't poison the txn."""
    try:
        with db.begin_nested():
            from app.models.cba_rate_profile import CbaRateProfile

            row = db.get(CbaRateProfile, "global")
            return (
                {k: float(v) for k, v in (row.rates or {}).items() if v is not None}
                if row
                else {}
            )
    except Exception:  # noqa: BLE001 -- table missing / DB hiccup
        return {}


def _new_stats() -> Dict[str, Any]:
    return {
        "updated": {"costs": 0, "benefits": 0},
        "inserted": {"costs": 0, "benefits": 0},
        "deleted": {"costs": 0, "benefits": 0},
        "warnings": [],
    }


def _sync_activity_costs(
    db: Session,
    calc_id: UUID,
    cba_id: UUID,
    auto_costs: Dict[str, CBACostItem],
    current: Set[str],
    stats: dict,
) -> None:
    from app.models.yearly_activities import (
        ActivityYearDetail,
        PotentialActivity,
        ProposedYearlyActivity,
    )

    acts = (
        db.query(ProposedYearlyActivity)
        .filter(ProposedYearlyActivity.calculation_id == calc_id)
        .all()
    )
    if not acts:
        return

    pa_ids = {a.potential_activity_id for a in acts}
    pa_map = {
        pa.id: pa
        for pa in db.query(PotentialActivity)
        .filter(PotentialActivity.id.in_(pa_ids))
        .all()
    }

    act_ids = [a.id for a in acts]
    yd_by_act: Dict[UUID, Dict[int, ActivityYearDetail]] = {}
    for yd in (
        db.query(ActivityYearDetail)
        .filter(ActivityYearDetail.proposed_activity_id.in_(act_ids))
        .all()
    ):
        yd_by_act.setdefault(yd.proposed_activity_id, {})[yd.year_number] = yd

    # A manual / locked row that carries an activity's name would be counted twice next to the new
    # automatic rows (it was once an averaged auto row that the user "locked"): warn, never delete.
    manual_names = {
        c.description
        for c in db.query(CBACostItem).filter(
            CBACostItem.cba_id == cba_id, CBACostItem.source_link.is_(None)
        )
    }

    for act in acts:
        pa = pa_map.get(act.potential_activity_id)
        category = (pa.progarms if pa and pa.progarms else "Other")[:200]
        description = (
            pa.activities
            if pa and pa.activities
            else f"Activity {act.potential_activity_id}"
        )
        order = (pa.display_order or 0) if pa else 0

        # One cost row per RUN of equal yearly budgets (D28), so the CBA discounts the money in the
        # years it is spent: Years 1-3 at NPR 60,000 is one row for years 1-3, not 18,000 over ten
        # years. A line with nothing budgeted makes no row and marks no key current, so a row that
        # already exists is swept below instead of staying at its old amount (plan section 5.8
        # item 3). Manual / locked rows have no source_link and are never touched.
        runs = budget_runs(act.default_yearly_budget, yd_by_act.get(act.id, {}))
        if runs and description in manual_names:
            warning = (
                f"'{description}': a manual cost row with the same name exists, and the activity is "
                "now also added automatically - it may be counted twice."
            )
            if warning not in stats["warnings"]:
                stats["warnings"].append(warning)

        for year_from, year_to, amount in runs:
            sk = f"activity:{act.id}:{year_from}-{year_to}"
            current.add(sk)
            per_year = round(float(amount), 2)
            total = round(per_year * (year_to - year_from + 1), 2)

            existing = auto_costs.get(sk)
            if existing is not None:
                existing.category = category
                existing.description = description
                existing.year_from = year_from
                existing.year_to = year_to
                existing.amount_per_year = per_year
                existing.total_amount = total
                existing.display_order = order
                stats["updated"]["costs"] += 1
            else:
                db.add(
                    CBACostItem(
                        cba_id=cba_id,
                        category=category,
                        description=description,
                        year_from=year_from,
                        year_to=year_to,
                        amount_per_year=per_year,
                        total_amount=total,
                        source_link=sk,
                        display_order=order,
                    )
                )
                stats["inserted"]["costs"] += 1


def _upsert_benefit(
    db: Session,
    cba_id: UUID,
    auto_benefits: Dict[str, CBABenefitItem],
    sk: str,
    *,
    source: str,
    description: str,
    quantity: float,
    unit_price: float,
    stats: dict,
) -> None:
    amt = round(quantity * unit_price, 2)
    existing = auto_benefits.get(sk)
    if existing is not None:
        existing.source = source
        existing.description = description
        existing.year_from = 1
        existing.year_to = 10
        existing.quantity = quantity
        existing.unit_price = unit_price
        existing.amount_per_year = amt
        existing.total_amount = round(amt * 10, 2)
        stats["updated"]["benefits"] += 1
    else:
        db.add(
            CBABenefitItem(
                cba_id=cba_id,
                source=source,
                description=description,
                year_from=1,
                year_to=10,
                quantity=quantity,
                unit_price=unit_price,
                amount_per_year=amt,
                total_amount=round(amt * 10, 2),
                source_link=sk,
            )
        )
        stats["inserted"]["benefits"] += 1


def _sync_block_benefits(
    db: Session,
    calc_id: UUID,
    cba_id: UUID,
    auto_benefits: Dict[str, CBABenefitItem],
    current: Set[str],
    rates: Dict[str, float],
    stats: dict,
) -> None:
    from app.models.field_inventory import (
        FieldInventoryBlockSummary,
        FieldInventoryCalculation,
    )

    fi = (
        db.query(FieldInventoryCalculation)
        .filter(FieldInventoryCalculation.calculation_id == calc_id)
        .first()
    )
    if fi is None:
        return

    blocks = (
        db.query(FieldInventoryBlockSummary)
        .filter(FieldInventoryBlockSummary.field_inventory_calculation_id == fi.id)
        .all()
    )
    for bs in blocks:
        timber = float(bs.tree_timber_m3_per_ha or 0) + float(
            bs.pole_timber_m3_per_ha or 0
        )
        fuelwood = float(bs.tree_firewood_m3_per_ha or 0) + float(
            bs.pole_firewood_m3_per_ha or 0
        )
        carbon = float(bs.co2_equivalent_tco2_per_ha or 0)

        for source, qty, rate_key in (
            ("timber", timber, "timber_mixed"),
            ("fuelwood", fuelwood, "fuelwood"),
            ("carbon", carbon, "carbon"),
        ):
            if qty <= 0:
                continue
            sk = f"block:{bs.block_name}:{source}"
            current.add(sk)
            _upsert_benefit(
                db,
                cba_id,
                auto_benefits,
                sk,
                source=source,
                description=f"{bs.block_name} — {source.title()}",
                quantity=round(qty, 2),
                unit_price=float(rates.get(rate_key, FALLBACK_RATES[rate_key])),
                stats=stats,
            )


def _sync_ntfp_benefits(
    db: Session,
    calc_id: UUID,
    cba_id: UUID,
    auto_benefits: Dict[str, CBABenefitItem],
    current: Set[str],
    rates: Dict[str, float],
    stats: dict,
) -> None:
    """NTFP benefits from the owner's annual harvest plan (the NTFP inventory page): one row per planned (species, part), quantity x unit price.

    Read in a SAVEPOINT, like the org rates, so a bare database without the table cannot poison the transaction."""
    try:
        with db.begin_nested():
            from app.services.ntfp_harvest_service import benefit_rows

            rows = benefit_rows(db, calc_id)
    except Exception:  # noqa: BLE001 -- NTFP benefits are optional: logged, and the scenario syncs without them
        logger.warning("CBA re-populate: NTFP harvest plan unavailable — skipping NTFP benefits", exc_info=True)
        return
    for row in rows:
        current.add(row["source_link"])
        _upsert_benefit(
            db,
            cba_id,
            auto_benefits,
            row["source_link"],
            source="ntfp",
            description=row["description"],
            quantity=round(row["quantity"], 2),
            unit_price=row["unit_price"],
            stats=stats,
        )


def _sync_scenario(cba_id: UUID, db: Session) -> dict:
    """Sync every auto-sourced row of the scenario **without committing**. Manual rows are untouched.

    Split out of ``repopulate_scenario`` so the read-only drift check can run exactly the same
    calculation inside a SAVEPOINT and roll it back (YEARLY_ACTIVITIES plan §5.8 item 5).
    """
    cba = db.get(CostBenefitAnalysis, cba_id)
    if cba is None:
        raise ValueError(f"CBA scenario {cba_id} not found")

    calc_id = cba.calculation_id
    # code fallback ▸ org 'global' row ▸ per-scenario default_rates
    rates = {
        **FALLBACK_RATES,
        **_load_org_rates(db),
        **(cba.default_rates or {}),
    }

    existing_costs = db.query(CBACostItem).filter(CBACostItem.cba_id == cba_id).all()
    existing_benefits = (
        db.query(CBABenefitItem).filter(CBABenefitItem.cba_id == cba_id).all()
    )
    auto_costs = {c.source_link: c for c in existing_costs if c.source_link}
    auto_benefits = {b.source_link: b for b in existing_benefits if b.source_link}

    current: Set[str] = set()
    stats = _new_stats()

    _sync_activity_costs(db, calc_id, cba_id, auto_costs, current, stats)
    _sync_block_benefits(db, calc_id, cba_id, auto_benefits, current, rates, stats)
    _sync_ntfp_benefits(db, calc_id, cba_id, auto_benefits, current, rates, stats)

    for sk, item in list(auto_costs.items()):
        if sk not in current:
            db.delete(item)
            stats["deleted"]["costs"] += 1
    for sk, item in list(auto_benefits.items()):
        if sk not in current:
            db.delete(item)
            stats["deleted"]["benefits"] += 1

    n_upd = stats["updated"]["costs"] + stats["updated"]["benefits"]
    n_ins = stats["inserted"]["costs"] + stats["inserted"]["benefits"]
    n_del = stats["deleted"]["costs"] + stats["deleted"]["benefits"]
    stats["message"] = (
        f"Auto-populate complete. {n_upd} rows updated, {n_ins} inserted, "
        f"{n_del} deleted."
    )
    return stats


def repopulate_scenario(cba_id: UUID, db: Session) -> dict:
    """Sync every auto-sourced row of the scenario. Manual rows are untouched.

    Returns ``{updated, inserted, deleted, message}`` with per-kind counts.
    """
    stats = _sync_scenario(cba_id, db)
    db.commit()
    return stats


def _auto_snapshot(db: Session, cba_id: UUID) -> dict:
    """``{source_link: comparable tuple}`` of the scenario's auto rows, as flushed in this session."""
    db.flush()
    out = {}
    for model, kind in ((CBACostItem, "cost"), (CBABenefitItem, "benefit")):
        for row in db.query(model).filter(model.cba_id == cba_id, model.source_link.isnot(None)):
            out[(kind, row.source_link)] = (
                row.category,
                row.description,
                row.year_from,
                row.year_to,
                float(row.amount_per_year or 0),
                float(row.total_amount or 0),
            )
    return out


def plan_drift(cba_id: UUID, db: Session) -> dict:
    """What an Auto-populate would change right now — **without changing anything**.

    Runs the real sync inside a SAVEPOINT, compares the auto rows before and after, and rolls the
    savepoint back. No timestamp column is needed, and unlike a "modified since" check it also sees a
    plan line that was deleted. Empty right after a re-populate; non-empty once the plan (or a
    source) has moved on. It never updates the scenario: the user may have tuned rates and manual rows.
    """
    before = _auto_snapshot(db, cba_id)
    nested = db.begin_nested()
    try:
        _sync_scenario(cba_id, db)
        after = _auto_snapshot(db, cba_id)
    finally:
        nested.rollback()
    added = sorted(k[1] for k in after.keys() - before.keys())
    removed = sorted(k[1] for k in before.keys() - after.keys())
    changed = sorted(k[1] for k in after.keys() & before.keys() if after[k] != before[k])
    return {
        "out_of_date": bool(added or removed or changed),
        "added": added,
        "removed": removed,
        "changed": changed,
    }
