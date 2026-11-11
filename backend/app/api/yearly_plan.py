"""Calculation-scoped facade over the yearly activity plan (YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.1).

The map workspace never handles plan lines directly: it draws a *place* for an activity, and the plan
line, its year rows and the feature are created in one transaction. The Plan table and the legacy
page edit a line's numbers through one all-or-nothing ``PUT``. Everything is owner-only (D9) and goes
through ``yearly_plan_service`` so the legacy endpoints and these routes cannot drift apart.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.errors import CalculationErrors
from ..core.exceptions import i18n_error
from ..core.idempotent_route import IdempotentRoute
from ..models.calculation import Calculation
from ..models.user import User
from ..models.yearly_activities import (
    ActivityDrawnFeature,
    PotentialActivity,
    ProposedYearlyActivity,
)
from ..schemas.yearly_plan import (
    ActivityFeatureCreate,
    ActivityFeatureCreated,
    ActivityFeatureOut,
    ActivityFeatureUpdate,
    PlanLineConfirm,
    PlanLineCreate,
    PlanLineCreated,
    PlanLineResult,
    PlanLineUpdate,
)
from ..services import yearly_plan_export as export
from ..services import sub_area_plan
from ..services import yearly_plan_service as plan
from ..services import yearly_plan_status as plan_status
from ..services.plan_health_service import compute_health
from ..services.audit_service import log_geometry_audit
from ..services.operational_plan.feature_kinds import KINDS, resolve_feature_kind
from ..services.optimistic_lock import check_and_bump
from ..services.yearly_plan_rules import (
    is_planned,
    effective_budget,
    effective_quantity,
)
from ..utils.auth import get_current_user
from ..utils.geometry_utils import compute_geometry_properties, strip_geo_fields
from .yearly_activities import _drawn_feature_response

logger = logging.getLogger(__name__)

router = APIRouter(route_class=IdempotentRoute)


# ------------------------------------------------------------------------------ helpers
def _owned_calculation(db: Session, calculation_id: UUID, user: User) -> Calculation:
    """Owner only — a super-admin gets the same 404 (plan D9)."""
    calc = (
        db.query(Calculation)
        .filter(Calculation.id == calculation_id, Calculation.user_id == user.id)
        .first()
    )
    if not calc:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    return calc


def _owned_line(
    db: Session, calculation_id: UUID, line_id: UUID
) -> ProposedYearlyActivity:
    line = (
        db.query(ProposedYearlyActivity)
        .filter(
            ProposedYearlyActivity.id == line_id,
            ProposedYearlyActivity.calculation_id == calculation_id,
        )
        .first()
    )
    if not line:
        raise HTTPException(status_code=404, detail="Plan line not found")
    return line


def _shapely_geometry(feature_type: str, geojson: str):
    import shapely

    try:
        coords = json.loads(geojson)["coordinates"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(
            status_code=422, detail="geometry must be a GeoJSON geometry"
        )
    if feature_type == "point":
        return shapely.Point(coords)
    if feature_type == "line":
        if len(coords) < 2:
            raise HTTPException(
                status_code=400, detail="Line requires at least 2 points"
            )
        return shapely.LineString(coords)
    ring = (
        coords[0] if coords and coords[0] and isinstance(coords[0][0], list) else coords
    )
    if len(ring) < 4:
        raise HTTPException(
            status_code=400,
            detail="Polygon must have at least 4 points (including closing)",
        )
    return shapely.Polygon(ring)


def _audit(
    db: Session,
    request: Request,
    calculation_id: UUID,
    operation: str,
    entity_id: Any,
    user: User,
    previous: Optional[dict] = None,
    new: Optional[dict] = None,
    entity: str = "feature",
) -> None:
    """Best-effort audit row: who changed which plan line / feature, and from which screen.

    An audit trail must never destroy the write it records, so the insert runs in a SAVEPOINT
    (a failed insert aborts the transaction) and a failure is logged, not raised.
    """
    meta = {
        "client_type": "web",
        "screen": request.headers.get("x-cfms-screen", ""),
        "entity": entity,
        "correlation_id": request.headers.get("x-correlation-id"),
    }
    try:
        with db.begin_nested():
            log_geometry_audit(
                db,
                str(calculation_id),
                "activity_features",
                operation,
                str(entity_id),
                previous,
                new,
                user_id=str(user.id),
                metadata=meta,
            )
    except Exception:  # noqa: BLE001 -- the audit must not fail the write
        logger.warning(
            "yearly_plan audit failed for %s %s", entity, entity_id, exc_info=True
        )


def _line_view(db: Session, calc: Calculation, line_id: UUID) -> Dict[str, Any]:
    for item in plan.plan_view(db, calc):
        if item["id"] == str(line_id):
            return item
    raise HTTPException(status_code=404, detail="Plan line not found")


def _feature_out(
    db: Session,
    calc: Calculation,
    feature: ActivityDrawnFeature,
    master: Optional[PotentialActivity],
) -> ActivityFeatureOut:
    from geoalchemy2.shape import to_shape

    props = feature.properties or {}
    try:
        wkt = to_shape(feature.geometry).wkt
        location = plan.derive_location(db, calc, wkt)
    except Exception:  # noqa: BLE001 -- location is a convenience read
        location = {"blocks": [], "sub_areas": []}
    return ActivityFeatureOut(
        **_drawn_feature_response(feature).model_dump(),
        activity_name=getattr(master, "activities", None),
        program_name=getattr(master, "progarms", None),
        block_name=None,
        kind=resolve_feature_kind(
            props.get("kind"), getattr(master, "map_kind", None), feature.feature_type
        ),
        block_names=location["blocks"],
        sub_area_names=location["sub_areas"],
    )


def _validate_years_planned(
    db: Session, line: ProposedYearlyActivity, years, plan_years: bool
):
    """A feature's years must be planned years of its line — or the caller says "plan them too"."""
    rows = plan.year_rows_for(db, [line.id]).get(line.id, {})
    unplanned = [
        y
        for y in years
        if not is_planned(
            effective_quantity(rows.get(y), line.default_quantity),
            effective_budget(rows.get(y), line.default_yearly_budget),
        )
    ]
    if not unplanned:
        return []
    if not plan_years:
        raise HTTPException(
            status_code=422,
            detail={"code": "YEAR_NOT_PLANNED", "years": unplanned},
        )
    check_and_bump(db, "yearly_plan", line.id, None)
    return plan.plan_years_too(db, line, unplanned)


# -------------------------------------------------------------------------- features
@router.post(
    "/calculations/{calculation_id}/activity-features",
    response_model=ActivityFeatureCreated,
)
def create_activity_feature(
    calculation_id: UUID,
    body: ActivityFeatureCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Draw a place for an activity: plan line + year rows + feature, in ONE transaction."""
    calc = _owned_calculation(db, calculation_id, current_user)
    master = (
        db.query(PotentialActivity)
        .filter(
            PotentialActivity.id == body.potential_activity_id,
            PotentialActivity.is_active.is_(True),
        )
        .first()
    )
    if not master:
        raise HTTPException(status_code=404, detail="Potential activity not found")
    if body.kind and body.kind not in KINDS:
        raise HTTPException(
            status_code=422, detail=f"Unknown feature kind: {body.kind}"
        )

    geom = _shapely_geometry(body.feature_type, body.geometry)
    numbers = (
        plan.PlanNumbers(quantity=body.quantity, budget=body.budget)
        if body.quantity is not None or body.budget is not None
        else None
    )
    try:
        line, created, created_rows = plan.get_or_create_line(
            db, calc.id, master.id, numbers=numbers, years=body.years
        )
        added = (
            []
            if created
            else _validate_years_planned(db, line, body.years, body.plan_years)
        )

        props = strip_geo_fields(
            {
                "name": (body.name or "").strip() or master.activities or "",
                "years": body.years,
                **({"kind": body.kind} if body.kind else {}),
            }
        )
        props.update(compute_geometry_properties(geom))
        feature = ActivityDrawnFeature(
            proposed_activity_id=line.id,
            calculation_id=calc.id,
            feature_type=body.feature_type,
            geometry=f"SRID=4326;{geom.wkt}",
            properties=props,
            created_by=current_user.id,
        )
        db.add(feature)
        db.flush()
        _audit(
            db,
            request,
            calc.id,
            "CREATE",
            feature.id,
            current_user,
            None,
            {"plan_line": str(line.id)},
        )
        measured = plan.quantity_from_geometry(db, line.id, master.unit)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(feature)
    db.refresh(line)
    return ActivityFeatureCreated(
        feature=_feature_out(db, calc, feature, master),
        plan_line=_line_view(db, calc, line.id),
        created_plan_line=created,
        created_year_rows=created_rows,
        planned_years_added=added,
        measured_quantity=measured,
        unit=master.unit,
    )


def _live_feature(
    db: Session, calculation_id: UUID, feature_id: UUID
) -> ActivityDrawnFeature:
    feature = (
        db.query(ActivityDrawnFeature)
        .join(
            ProposedYearlyActivity,
            ActivityDrawnFeature.proposed_activity_id == ProposedYearlyActivity.id,
        )
        .filter(
            ActivityDrawnFeature.id == feature_id,
            ProposedYearlyActivity.calculation_id == calculation_id,
            ActivityDrawnFeature.deleted_at.is_(None),
        )
        .first()
    )
    if not feature:
        raise HTTPException(status_code=404, detail="Drawn feature not found")
    return feature


@router.patch(
    "/calculations/{calculation_id}/activity-features/{feature_id}",
    response_model=ActivityFeatureOut,
)
def update_activity_feature(
    calculation_id: UUID,
    feature_id: UUID,
    body: ActivityFeatureUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit a feature's name, years or symbol, or move it to another activity (guarded, D5)."""
    calc = _owned_calculation(db, calculation_id, current_user)
    feature = _live_feature(db, calc.id, feature_id)
    line = db.get(ProposedYearlyActivity, feature.proposed_activity_id)
    previous = dict(feature.properties or {})
    props = dict(previous)
    fields = body.model_fields_set

    if "kind" in fields and body.kind and body.kind not in KINDS:
        raise HTTPException(
            status_code=422, detail=f"Unknown feature kind: {body.kind}"
        )
    try:
        if (
            body.potential_activity_id is not None
            and body.potential_activity_id != line.potential_activity_id
        ):
            target_master = (
                db.query(PotentialActivity)
                .filter(
                    PotentialActivity.id == body.potential_activity_id,
                    PotentialActivity.is_active.is_(True),
                )
                .first()
            )
            if not target_master:
                raise HTTPException(
                    status_code=404, detail="Potential activity not found"
                )
            line, _c, _r = plan.get_or_create_line(
                db,
                calc.id,
                target_master.id,
                years=body.years or props.get("years") or [1],
            )
            feature.proposed_activity_id = line.id
        if "years" in fields and body.years is not None:
            _validate_years_planned(db, line, body.years, body.plan_years)
            props["years"] = body.years
        if "name" in fields:
            master_name = (
                db.query(PotentialActivity.activities)
                .filter(PotentialActivity.id == line.potential_activity_id)
                .scalar()
            )
            props["name"] = (body.name or "").strip() or master_name or ""
        if "kind" in fields:
            if body.kind:
                props["kind"] = body.kind
            else:
                props.pop("kind", None)
        feature.properties = props
        db.flush()
        _audit(
            db, request, calc.id, "UPDATE", feature.id, current_user, previous, props
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(feature)
    master = db.get(PotentialActivity, line.potential_activity_id)
    return _feature_out(db, calc, feature, master)


@router.delete("/calculations/{calculation_id}/activity-features/{feature_id}")
def delete_activity_feature(
    calculation_id: UUID,
    feature_id: UUID,
    request: Request,
    remove_plan_line: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a feature. The plan line stays (D6) unless ``remove_plan_line`` and it has no others."""
    calc = _owned_calculation(db, calculation_id, current_user)
    feature = _live_feature(db, calc.id, feature_id)
    line_id = feature.proposed_activity_id
    try:
        feature.deleted_at = datetime.now(timezone.utc)
        db.flush()
        _audit(
            db,
            request,
            calc.id,
            "DELETE",
            feature.id,
            current_user,
            dict(feature.properties or {}),
            None,
        )
        removed_line = False
        if remove_plan_line and not plan.feature_counts(db, [line_id]).get(line_id):
            line = db.get(ProposedYearlyActivity, line_id)
            if line is not None:
                db.delete(line)
                removed_line = True
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"deleted": True, "id": str(feature_id), "plan_line_removed": removed_line}


# ---------------------------------------------------------------------------- done mark (workflow step 15)
class YearlyPlanDone(BaseModel):
    done: bool


@router.get("/calculations/{calculation_id}/yearly-plan/status")
def get_yearly_plan_status(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Has the owner said the yearly activities are finished? (Reopens by itself when the plan changes.)"""
    _owned_calculation(db, calculation_id, current_user)
    return plan_status.get_status(db, calculation_id)


@router.put("/calculations/{calculation_id}/yearly-plan/status")
def put_yearly_plan_status(
    calculation_id: UUID,
    body: YearlyPlanDone,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark the yearly activities done, or open them again. Whoever may edit the plan (its owner) may do this."""
    _owned_calculation(db, calculation_id, current_user)
    return plan_status.set_done(db, calculation_id, body.done, current_user.id)


# ---------------------------------------------------------------------------- plan
@router.get("/calculations/{calculation_id}/yearly-plan")
def get_yearly_plan(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Plan lines with the per-year matrix, feature counts, the location mode and the review state."""
    calc = _owned_calculation(db, calculation_id, current_user)
    lines = plan.plan_view(db, calc)
    return {
        "lines": lines,
        "total_budget": round(sum(item["total_budget"] for item in lines), 2),
    }


@router.post(
    "/calculations/{calculation_id}/yearly-plan",
    response_model=PlanLineCreated,
)
def add_activity_to_plan(
    calculation_id: UUID,
    body: PlanLineCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add an activity to the plan without drawing a place, in ONE transaction.

    For an activity that needs no map, one that applies to the whole forest, or a place decided later.
    The user typed the numbers, so a new line is created reviewed. An activity that is already in the plan
    is left as it is (its numbers are edited through PUT); only whole_forest is still applied.
    """
    calc = _owned_calculation(db, calculation_id, current_user)
    master = (
        db.query(PotentialActivity)
        .filter(
            PotentialActivity.id == body.potential_activity_id,
            PotentialActivity.is_active.is_(True),
        )
        .first()
    )
    if not master:
        raise HTTPException(status_code=404, detail="Potential activity not found")
    try:
        line, created, _rows = plan.get_or_create_line(
            db,
            calc.id,
            master.id,
            numbers=plan.PlanNumbers(quantity=body.quantity, budget=body.budget),
            years=body.years,
        )
        if created and body.year_values:
            plan.apply_line_edit(
                db,
                line,
                plan.LineEdit(
                    years=[
                        plan.YearEdit(
                            year=item.year,
                            quantity=item.quantity,
                            budget=item.budget,
                            set_quantity="quantity" in item.model_fields_set
                            and item.quantity is not None,
                            set_budget="budget" in item.model_fields_set
                            and item.budget is not None,
                        )
                        for item in body.year_values
                    ]
                ),
                None,
            )
        if body.whole_forest and not line.assign_to_all_blocks:
            check_and_bump(db, "yearly_plan", line.id, None)
            line.assign_to_all_blocks = True
        db.flush()
        _audit(
            db,
            request,
            calc.id,
            "CREATE" if created else "UPDATE",
            line.id,
            current_user,
            None,
            {"potential_activity_id": master.id, "whole_forest": body.whole_forest},
            entity="plan_line",
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(line)
    return PlanLineCreated(
        plan_line=_line_view(db, calc, line.id),
        created_plan_line=created,
        unit=master.unit,
    )


@router.get("/calculations/{calculation_id}/plan-units")
def plan_units(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The units (blocks / compartments) an activity can be assigned to, with their sub-areas (owner only)."""
    calc = _owned_calculation(db, calculation_id, current_user)
    return plan.forest_units_with_subareas(db, calc)


class SubAreaPlanBody(BaseModel):
    potential_activity_ids: List[int]


@router.get("/calculations/{calculation_id}/sub-areas/plan-status")
def sub_area_plan_status(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every sub-area with its state (exempt / planned / needs_plan / no_unit / no_id), the real lines tied to it and the
    activities suggested for its category. Pure read."""
    calc = _owned_calculation(db, calculation_id, current_user)
    status = sub_area_plan.sub_area_plan_status(db, calc)
    by_category: Dict[str, Any] = {}
    for item in status:
        if item["state"] in (sub_area_plan.NEEDS_PLAN, sub_area_plan.NO_UNIT):
            if item["category"] not in by_category:
                by_category[item["category"]] = sub_area_plan.suggested_activities(db, item["category"])
            item["suggestions"] = by_category[item["category"]]
    return {"sub_areas": status, "needs_plan": len(sub_area_plan.sub_areas_needing_plan(status))}


@router.post("/calculations/{calculation_id}/sub-areas/plan-suggested")
def plan_sub_areas_with_suggestions(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Plan every sub-area that needs one with the FIRST suggested activity of its category; those with no suggestion are left
    and listed. One step per sub-area, so one failure does not undo the others."""
    calc = _owned_calculation(db, calculation_id, current_user)
    planned, skipped = [], []
    for item in sub_area_plan.sub_area_plan_status(db, calc):
        if item["state"] != sub_area_plan.NEEDS_PLAN:
            continue
        suggestions = sub_area_plan.suggested_activities(db, item["category"])
        if not suggestions:
            skipped.append({"id": item["id"], "name": item["name"], "reason": "no_suggestion"})
            continue
        try:
            with db.begin_nested():
                sub_area_plan.create_plan_lines(db, calc, item["id"], [suggestions[0]["id"]])
            planned.append({"id": item["id"], "name": item["name"], "activity": suggestions[0]["activity"]})
        except (LookupError, ValueError):
            skipped.append({"id": item["id"], "name": item["name"], "reason": "failed"})
    db.commit()
    return {"planned": planned, "skipped": skipped}


@router.post("/calculations/{calculation_id}/sub-areas/{sub_area_id}/plan")
def plan_sub_area(
    calculation_id: UUID,
    sub_area_id: str,
    body: SubAreaPlanBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tie a sub-area to the plan: one line per chosen activity (a hectare activity starts at the sub-area area)."""
    calc = _owned_calculation(db, calculation_id, current_user)
    try:
        made = sub_area_plan.create_plan_lines(db, calc, sub_area_id, body.potential_activity_ids)
        db.commit()
    except (LookupError, ValueError) as exc:
        db.rollback()
        raise i18n_error(404 if isinstance(exc, LookupError) else 409, f"yearly_plan.{exc}")
    except Exception:
        db.rollback()
        raise
    return {"lines": made}


@router.put(
    "/calculations/{calculation_id}/yearly-plan/{line_id}",
    response_model=PlanLineResult,
)
def update_yearly_plan_line(
    calculation_id: UUID,
    line_id: UUID,
    body: PlanLineUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit a plan line's numbers in ONE transaction: all or nothing, one version check."""
    calc = _owned_calculation(db, calculation_id, current_user)
    line = _owned_line(db, calc.id, line_id)
    before = _line_view(db, calc, line.id)
    edit = plan.LineEdit(
        default_quantity=body.default_quantity,
        default_yearly_budget=body.default_yearly_budget,
        years=[
            plan.YearEdit(
                year=item.year,
                quantity=item.quantity,
                budget=item.budget,
                set_quantity="quantity" in item.model_fields_set
                and item.quantity is not None,
                set_budget="budget" in item.model_fields_set
                and item.budget is not None,
            )
            for item in body.years
        ],
        notes=body.notes,
        set_notes="notes" in body.model_fields_set,
        status=body.status,
        unreview=body.unreview,
    )
    try:
        filled = plan.apply_line_edit(db, line, edit, body.expected_version)
        after = _line_view_after_flush(db, calc, line)
        _audit(
            db,
            request,
            calc.id,
            "UPDATE",
            line.id,
            current_user,
            {
                "years": before["years"],
                "default_quantity": before["default_quantity"],
                "default_yearly_budget": before["default_yearly_budget"],
            },
            {
                "years": after["years"],
                "default_quantity": after["default_quantity"],
                "default_yearly_budget": after["default_yearly_budget"],
                "filled_years": filled,
            },
            entity="plan_line",
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(line)
    return PlanLineResult(plan_line=_line_view(db, calc, line.id), filled_years=filled)


def _line_view_after_flush(
    db: Session, calc: Calculation, line: ProposedYearlyActivity
) -> Dict[str, Any]:
    db.flush()
    return _line_view(db, calc, line.id)


@router.post(
    "/calculations/{calculation_id}/yearly-plan/{line_id}/confirm",
    response_model=PlanLineResult,
)
def confirm_yearly_plan_line(
    calculation_id: UUID,
    line_id: UUID,
    request: Request,
    body: Optional[PlanLineConfirm] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ "These numbers are right": mark the line reviewed without changing them."""
    calc = _owned_calculation(db, calculation_id, current_user)
    line = _owned_line(db, calc.id, line_id)
    try:
        plan.confirm_line(db, line, body.expected_version if body else None)
        _audit(
            db,
            request,
            calc.id,
            "UPDATE",
            line.id,
            current_user,
            None,
            {"confirmed": True},
            entity="plan_line",
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(line)
    return PlanLineResult(plan_line=_line_view(db, calc, line.id))


@router.get("/calculations/{calculation_id}/yearly-plan/health")
def get_yearly_plan_health(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What is missing, as codes: per-activity states, the one next step, and plan-level notes.

    Pure read. Both screens, the Next-step card and the Plan check before export read this, so they
    cannot disagree (plan §4.5).
    """
    calc = _owned_calculation(db, calculation_id, current_user)
    return compute_health(db, calc, cba_out_of_date=_cba_out_of_date(db, calc))


def _cba_out_of_date(db: Session, calc: Calculation) -> bool:
    """True when a base cost-benefit scenario exists and Auto-populate would change it. Best effort:
    a problem in the CBA must never take the plan-health document down."""
    try:
        from ..models.cost_benefit import CostBenefitAnalysis
        from ..services.cost_benefit.repopulate import plan_drift

        base = (
            db.query(CostBenefitAnalysis)
            .filter(
                CostBenefitAnalysis.calculation_id == calc.id,
                CostBenefitAnalysis.is_base_scenario.is_(True),
            )
            .first()
        )
        return bool(base is not None and plan_drift(base.id, db)["out_of_date"])
    except Exception:  # noqa: BLE001 -- informational; log and move on
        logger.warning(
            "plan health: CBA drift check failed for %s", calc.id, exc_info=True
        )
        return False


# ------------------------------------------------------------------------------ exports
def _csv_response(calc: Calculation, kind: str, headers, rows) -> Response:
    """The one CSV response both screens use: same builder, same bytes for the same saved data."""
    name = export.filename(calc, kind)
    ascii_name = name.encode("ascii", "ignore").decode() or f"YearlyActivity_{kind}.csv"
    return Response(
        content=export.to_csv(headers, rows),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
        },
    )


@router.get("/calculations/{calculation_id}/yearly-plan/export")
def export_yearly_plan(
    calculation_id: UUID,
    format: str = Query("csv"),
    lang: str = Query("en"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Yearly plan — every activity, spatial and not, one row per plan line (saved data, never a draft)."""
    calc = _owned_calculation(db, calculation_id, current_user)
    if format != "csv":
        raise HTTPException(status_code=400, detail="Only format=csv is available")
    headers, rows = export.plan_table(db, calc, lang)
    return _csv_response(calc, "Plan", headers, rows)


@router.get("/calculations/{calculation_id}/activity-features/export")
def export_activity_features(
    calculation_id: UUID,
    format: str = Query("csv"),
    lang: str = Query("en"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Activity features — the places drawn on the map, one row per feature."""
    calc = _owned_calculation(db, calculation_id, current_user)
    if format != "csv":
        raise HTTPException(status_code=400, detail="Only format=csv is available")
    headers, rows = export.features_table(db, calc, lang)
    return _csv_response(calc, "Features", headers, rows)
