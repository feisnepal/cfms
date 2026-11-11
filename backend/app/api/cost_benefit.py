"""Cost-Benefit Analysis API (CBA_MODULE_PLAN.md P3).

Scenario CRUD lives under ``/calculations/{calculation_id}/cba``; the line-item,
compute and export routes under ``/cba/{cba_id}`` (the scenario id already
identifies the calculation). Every mutation drops the calculation's
``OpDataCache`` rows so the next OP preview / export picks up fresh numbers.

Access: owner-or-``SUPER_ADMIN`` on the parent calculation, mirroring
``soil_erosion_params`` / ``hazard_erosion``.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.models.calculation import Calculation
from app.models.cost_benefit import (
    CBABenefitItem,
    CBACostItem,
    CBAResult,
    CostBenefitAnalysis,
)
from app.models.user import User, UserRole
from app.schemas.cost_benefit import (
    CBABenefitItemCreate,
    CBABenefitItemResponse,
    CBABenefitItemUpdate,
    CBACloneRequest,
    CBACompareItem,
    CBACompareRequest,
    CBACostItemCreate,
    CBACostItemResponse,
    CBACostItemUpdate,
    CBAExportData,
    CBARepopulateResponse,
    CBAResultResponse,
    CBAScenarioCreate,
    CBAScenarioListItem,
    CBAScenarioResponse,
    CBAScenarioUpdate,
)
from app.services.cost_benefit import engine
from app.services.cost_benefit.repopulate import plan_drift, repopulate_scenario
from app.utils.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Cost-Benefit Analysis"])


# ── helpers ─────────────────────────────────────────────────────────────────


def _require_calc_access(
    db: Session, calculation_id: str, current_user: User
) -> Calculation:
    try:
        calc = (
            db.query(Calculation)
            .filter(Calculation.id == UUID(str(calculation_id)))
            .first()
        )
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Calculation not found")
    if not calc:
        raise HTTPException(status_code=404, detail="Calculation not found")
    if calc.user_id != current_user.id and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    return calc


def _scenario_or_404(
    db: Session, cba_id: str, calculation_id: Optional[str] = None
) -> CostBenefitAnalysis:
    try:
        scn = (
            db.query(CostBenefitAnalysis)
            .options(
                joinedload(CostBenefitAnalysis.cost_items),
                joinedload(CostBenefitAnalysis.benefit_items),
                joinedload(CostBenefitAnalysis.result),
            )
            .filter(CostBenefitAnalysis.id == UUID(str(cba_id)))
            .first()
        )
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="CBA scenario not found")
    if scn is None:
        raise HTTPException(status_code=404, detail="CBA scenario not found")
    if calculation_id is not None and str(scn.calculation_id) != str(calculation_id):
        raise HTTPException(status_code=404, detail="CBA scenario not found")
    return scn


def _require_scenario_access(
    db: Session, cba_id: str, current_user: User
) -> CostBenefitAnalysis:
    scn = _scenario_or_404(db, cba_id)
    _require_calc_access(db, str(scn.calculation_id), current_user)
    return scn


def _invalidate_op_cache(db: Session, calculation_id: UUID) -> None:
    """Drop the OP data cache for this calculation so the next preview / export
    reflects the edited scenario. Best-effort."""
    try:
        from app.models.op_data_cache import OpDataCache

        db.query(OpDataCache).filter(
            OpDataCache.calculation_id == calculation_id
        ).delete(synchronize_session=False)
    except Exception:  # noqa: BLE001 -- best-effort
        logger.warning(
            "CBA: op_data_cache invalidation failed for %s",
            calculation_id,
            exc_info=True,
        )


def _n_years(year_from: int, year_to: int) -> int:
    return max(0, int(year_to) - int(year_from) + 1)


def _cost_total(item: CBACostItem) -> Decimal:
    return Decimal(item.amount_per_year or 0) * _n_years(item.year_from, item.year_to)


def _benefit_total(item: CBABenefitItem) -> Decimal:
    apy = Decimal(item.amount_per_year or 0)
    if apy == 0 and item.quantity is not None and item.unit_price is not None:
        apy = Decimal(item.quantity) * Decimal(item.unit_price)
    return apy * _n_years(item.year_from, item.year_to)


def _list_item(scn: CostBenefitAnalysis) -> CBAScenarioListItem:
    r = scn.result
    return CBAScenarioListItem(
        id=scn.id,
        name=scn.name,
        is_base_scenario=scn.is_base_scenario,
        status=scn.status,
        discount_rate=scn.discount_rate,
        cost_count=len(scn.cost_items),
        benefit_count=len(scn.benefit_items),
        has_result=r is not None,
        npv=r.npv if r else None,
        irr=r.irr if r else None,
        benefit_cost_ratio=r.benefit_cost_ratio if r else None,
        payback_period_years=r.payback_period_years if r else None,
        created_at=scn.created_at,
    )


# ── scenario CRUD ──────────────────────────────────────────────────────────


@router.get(
    "/calculations/{calculation_id}/cba",
    response_model=List[CBAScenarioListItem],
)
def list_cba_scenarios(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_calc_access(db, calculation_id, current_user)
    scenarios = (
        db.query(CostBenefitAnalysis)
        .options(
            joinedload(CostBenefitAnalysis.cost_items),
            joinedload(CostBenefitAnalysis.benefit_items),
            joinedload(CostBenefitAnalysis.result),
        )
        .filter(CostBenefitAnalysis.calculation_id == UUID(calculation_id))
        .order_by(CostBenefitAnalysis.created_at.asc())
        .all()
    )
    return [_list_item(s) for s in scenarios]


@router.post(
    "/calculations/{calculation_id}/cba",
    response_model=CBAScenarioResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_cba_scenario(
    calculation_id: str,
    body: CBAScenarioCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _require_calc_access(db, calculation_id, current_user)
    is_first = (
        db.query(CostBenefitAnalysis)
        .filter(CostBenefitAnalysis.calculation_id == calc.id)
        .count()
        == 0
    )
    scn = CostBenefitAnalysis(
        calculation_id=calc.id,
        name=body.name,
        description=body.description,
        discount_rate=body.discount_rate,
        time_horizon_years=body.time_horizon_years,
        irr_start_year=body.irr_start_year,
        currency=body.currency,
        default_rates=body.default_rates or {},
        is_base_scenario=is_first,
        status="draft",
        created_by=current_user.id,
    )
    db.add(scn)
    db.commit()
    db.refresh(scn)
    return _scenario_or_404(db, str(scn.id))


@router.get(
    "/calculations/{calculation_id}/cba/{cba_id}",
    response_model=CBAScenarioResponse,
)
def get_cba_scenario(
    calculation_id: str,
    cba_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_calc_access(db, calculation_id, current_user)
    return _scenario_or_404(db, cba_id, calculation_id)


@router.put(
    "/calculations/{calculation_id}/cba/{cba_id}",
    response_model=CBAScenarioResponse,
)
def update_cba_scenario(
    calculation_id: str,
    cba_id: str,
    body: CBAScenarioUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_calc_access(db, calculation_id, current_user)
    scn = _scenario_or_404(db, cba_id, calculation_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(scn, field, value)
    db.add(scn)
    _invalidate_op_cache(db, scn.calculation_id)
    db.commit()
    return _scenario_or_404(db, cba_id)


@router.delete(
    "/calculations/{calculation_id}/cba/{cba_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_cba_scenario(
    calculation_id: str,
    cba_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_calc_access(db, calculation_id, current_user)
    scn = _scenario_or_404(db, cba_id, calculation_id)
    calc_id = scn.calculation_id
    db.delete(scn)
    _invalidate_op_cache(db, calc_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/calculations/{calculation_id}/cba/{cba_id}/set-base",
    response_model=List[CBAScenarioListItem],
)
def set_base_scenario(
    calculation_id: str,
    cba_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _require_calc_access(db, calculation_id, current_user)
    target = _scenario_or_404(db, cba_id, calculation_id)
    for s in (
        db.query(CostBenefitAnalysis)
        .filter(CostBenefitAnalysis.calculation_id == calc.id)
        .all()
    ):
        s.is_base_scenario = s.id == target.id
    _invalidate_op_cache(db, calc.id)
    db.commit()
    return list_cba_scenarios(calculation_id, db, current_user)


@router.post(
    "/calculations/{calculation_id}/cba/{cba_id}/clone",
    response_model=CBAScenarioResponse,
    status_code=status.HTTP_201_CREATED,
)
def clone_cba_scenario(
    calculation_id: str,
    cba_id: str,
    body: CBACloneRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_calc_access(db, calculation_id, current_user)
    src = _scenario_or_404(db, cba_id, calculation_id)

    clone = CostBenefitAnalysis(
        calculation_id=src.calculation_id,
        name=body.name or f"{src.name} (Copy)",
        description=src.description,
        discount_rate=src.discount_rate,
        time_horizon_years=src.time_horizon_years,
        irr_start_year=src.irr_start_year,
        currency=src.currency,
        default_rates=dict(src.default_rates or {}),
        is_base_scenario=False,
        status="draft",
        created_by=current_user.id,
    )
    db.add(clone)
    db.flush()

    for c in src.cost_items:
        db.add(
            CBACostItem(
                cba_id=clone.id,
                category=c.category,
                description=c.description,
                year_from=c.year_from,
                year_to=c.year_to,
                amount_per_year=c.amount_per_year,
                is_recurring=c.is_recurring,
                total_amount=c.total_amount,
                source_link=c.source_link,
                notes=c.notes,
                display_order=c.display_order,
            )
        )
    for b in src.benefit_items:
        db.add(
            CBABenefitItem(
                cba_id=clone.id,
                source=b.source,
                description=b.description,
                year_from=b.year_from,
                year_to=b.year_to,
                quantity=b.quantity,
                unit_price=b.unit_price,
                amount_per_year=b.amount_per_year,
                is_recurring=b.is_recurring,
                total_amount=b.total_amount,
                source_link=b.source_link,
                notes=b.notes,
                display_order=b.display_order,
            )
        )
    db.commit()
    return _scenario_or_404(db, str(clone.id))


# ── cost items ────────────────────────────────────────────────────────────


@router.get("/cba/{cba_id}/costs", response_model=List[CBACostItemResponse])
def list_cba_costs(
    cba_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scn = _require_scenario_access(db, cba_id, current_user)
    return sorted(scn.cost_items, key=lambda c: c.display_order)


@router.post(
    "/cba/{cba_id}/costs",
    response_model=CBACostItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_cba_cost(
    cba_id: str,
    body: CBACostItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scn = _require_scenario_access(db, cba_id, current_user)
    item = CBACostItem(cba_id=scn.id, **body.model_dump())
    item.total_amount = Decimal(item.amount_per_year or 0) * _n_years(
        item.year_from, item.year_to
    )
    db.add(item)
    _invalidate_op_cache(db, scn.calculation_id)
    db.commit()
    db.refresh(item)
    return item


@router.put("/cba/{cba_id}/costs/{cost_id}", response_model=CBACostItemResponse)
def update_cba_cost(
    cba_id: str,
    cost_id: str,
    body: CBACostItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scn = _require_scenario_access(db, cba_id, current_user)
    item = next((c for c in scn.cost_items if str(c.id) == cost_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Cost item not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    item.total_amount = Decimal(item.amount_per_year or 0) * _n_years(
        item.year_from, item.year_to
    )
    _invalidate_op_cache(db, scn.calculation_id)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/cba/{cba_id}/costs/{cost_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cba_cost(
    cba_id: str,
    cost_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scn = _require_scenario_access(db, cba_id, current_user)
    item = next((c for c in scn.cost_items if str(c.id) == cost_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Cost item not found")
    db.delete(item)
    _invalidate_op_cache(db, scn.calculation_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── benefit items ─────────────────────────────────────────────────────────


@router.get("/cba/{cba_id}/benefits", response_model=List[CBABenefitItemResponse])
def list_cba_benefits(
    cba_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scn = _require_scenario_access(db, cba_id, current_user)
    return sorted(scn.benefit_items, key=lambda b: b.display_order)


def _benefit_apy(item: CBABenefitItem) -> Decimal:
    apy = Decimal(item.amount_per_year or 0)
    if apy == 0 and item.quantity is not None and item.unit_price is not None:
        apy = Decimal(item.quantity) * Decimal(item.unit_price)
    return apy


@router.post(
    "/cba/{cba_id}/benefits",
    response_model=CBABenefitItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_cba_benefit(
    cba_id: str,
    body: CBABenefitItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scn = _require_scenario_access(db, cba_id, current_user)
    item = CBABenefitItem(cba_id=scn.id, **body.model_dump())
    item.total_amount = _benefit_apy(item) * _n_years(item.year_from, item.year_to)
    db.add(item)
    _invalidate_op_cache(db, scn.calculation_id)
    db.commit()
    db.refresh(item)
    return item


@router.put(
    "/cba/{cba_id}/benefits/{benefit_id}",
    response_model=CBABenefitItemResponse,
)
def update_cba_benefit(
    cba_id: str,
    benefit_id: str,
    body: CBABenefitItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scn = _require_scenario_access(db, cba_id, current_user)
    item = next((b for b in scn.benefit_items if str(b.id) == benefit_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Benefit item not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    item.total_amount = _benefit_apy(item) * _n_years(item.year_from, item.year_to)
    _invalidate_op_cache(db, scn.calculation_id)
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/cba/{cba_id}/benefits/{benefit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_cba_benefit(
    cba_id: str,
    benefit_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scn = _require_scenario_access(db, cba_id, current_user)
    item = next((b for b in scn.benefit_items if str(b.id) == benefit_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Benefit item not found")
    db.delete(item)
    _invalidate_op_cache(db, scn.calculation_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── auto-populate / compute / compare / export ────────────────────────────


@router.post("/cba/{cba_id}/auto-populate", response_model=CBARepopulateResponse)
def auto_populate_cba(
    cba_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scn = _require_scenario_access(db, cba_id, current_user)
    stats = repopulate_scenario(scn.id, db)
    _invalidate_op_cache(db, scn.calculation_id)
    db.commit()
    return CBARepopulateResponse(**stats)


def _engine_inputs(scn: CostBenefitAnalysis):
    from app.services.cost_benefit import result_sync

    return result_sync.engine_inputs(scn)


@router.get("/cba/{cba_id}/plan-drift")
def cba_plan_drift(
    cba_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Has the yearly plan (or another source) moved on since this scenario was last populated?

    Read-only: runs the real Auto-populate inside a savepoint, compares, and rolls it back — nothing
    is written. Never updates the scenario by itself: the user may have tuned rates and manual rows.
    """
    scn = _require_scenario_access(db, cba_id, current_user)
    return plan_drift(scn.id, db)


@router.post("/cba/{cba_id}/compute", response_model=CBAResultResponse)
def compute_cba(
    cba_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scn = _require_scenario_access(db, cba_id, current_user)
    existing = db.query(CBAResult).filter(CBAResult.cba_id == scn.id).first()
    if existing is None:
        existing = CBAResult(cba_id=scn.id)
        db.add(existing)
    costs, benefits = _engine_inputs(scn)
    out = engine.compute_all(
        costs,
        benefits,
        float(scn.discount_rate),
        scn.time_horizon_years,
        scn.irr_start_year,
    )
    # result_sync.apply_result also refreshes computed_at — the staleness stamp
    # the OP collector compares the item timestamps against (ND-6).
    from app.services.cost_benefit import result_sync

    result_sync.apply_result(existing, out)

    _invalidate_op_cache(db, scn.calculation_id)
    db.commit()
    db.refresh(existing)
    return existing


@router.post(
    "/calculations/{calculation_id}/cba/compare",
    response_model=List[CBACompareItem],
)
def compare_cba_scenarios(
    calculation_id: str,
    body: CBACompareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _require_calc_access(db, calculation_id, current_user)
    scenarios = (
        db.query(CostBenefitAnalysis)
        .options(
            joinedload(CostBenefitAnalysis.cost_items),
            joinedload(CostBenefitAnalysis.benefit_items),
            joinedload(CostBenefitAnalysis.result),
        )
        .filter(
            CostBenefitAnalysis.calculation_id == calc.id,
            CostBenefitAnalysis.id.in_(body.cba_ids),
        )
        .all()
    )
    if not scenarios:
        raise HTTPException(status_code=404, detail="No scenarios found")

    out: List[CBACompareItem] = []
    for s in scenarios:
        r = s.result
        out.append(
            CBACompareItem(
                cba_id=s.id,
                name=s.name,
                npv=r.npv if r else None,
                irr=r.irr if r else None,
                benefit_cost_ratio=r.benefit_cost_ratio if r else None,
                payback_period_years=r.payback_period_years if r else None,
                total_cost=sum((_cost_total(c) for c in s.cost_items), Decimal(0)),
                total_benefit=sum(
                    (_benefit_total(b) for b in s.benefit_items), Decimal(0)
                ),
                cost_count=len(s.cost_items),
                benefit_count=len(s.benefit_items),
            )
        )
    return out


def _breakdown(items, key_attr, total_fn):
    groups: dict[str, Decimal] = {}
    for it in items:
        k = getattr(it, key_attr) or "—"
        groups[k] = groups.get(k, Decimal(0)) + total_fn(it)
    grand = sum(groups.values(), Decimal(0))
    return [
        {
            "label": k,
            "amount": float(v),
            "percent": (round(float(v / grand * 100), 1) if grand else 0.0),
        }
        for k, v in sorted(groups.items(), key=lambda kv: -kv[1])
    ]


@router.get("/cba/{cba_id}/export-data", response_model=CBAExportData)
def export_cba_data(
    cba_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scn = _require_scenario_access(db, cba_id, current_user)
    r = scn.result

    def _f(v) -> Optional[float]:
        return float(v) if v is not None else None

    npv = _f(r.npv) if r else None
    irr_frac = _f(r.irr) if r else None
    bcr = _f(r.benefit_cost_ratio) if r else None
    payback = _f(r.payback_period_years) if r else None
    cost_pv = _f(r.total_cost_pv) if r else None
    benefit_pv = _f(r.total_benefit_pv) if r else None

    cost_undisc = float(sum((_cost_total(c) for c in scn.cost_items), Decimal(0)))
    benefit_undisc = float(
        sum((_benefit_total(b) for b in scn.benefit_items), Decimal(0))
    )

    summary_table = [
        {"indicator": "Net Present Value (NPV)", "value": npv},
        {
            "indicator": "Internal Rate of Return (IRR)",
            "value": (round(irr_frac * 100, 2) if irr_frac is not None else "N/A"),
        },
        {
            "indicator": "Benefit-Cost Ratio (B/C)",
            "value": bcr if bcr is not None else "N/A",
        },
        {"indicator": "Payback Period", "value": payback, "unit": "years"},
        {"indicator": "Total Cost (PV)", "value": cost_pv},
        {"indicator": "Total Benefit (PV)", "value": benefit_pv},
        {"indicator": "Total Cost (Undiscounted)", "value": cost_undisc},
        {
            "indicator": "Total Benefit (Undiscounted)",
            "value": benefit_undisc,
        },
    ]

    cash_flow_table = list(r.cash_flow_data) if r and r.cash_flow_data else []

    return CBAExportData(
        base_npv=npv,
        base_irr=(round(irr_frac * 100, 2) if irr_frac is not None else None),
        base_bc_ratio=bcr,
        base_payback=payback,
        summary_table=summary_table,
        cash_flow_table=cash_flow_table,
        cost_breakdown=_breakdown(scn.cost_items, "category", _cost_total),
        benefit_breakdown=_breakdown(scn.benefit_items, "source", _benefit_total),
    )
