"""
API endpoints for yearly activities management with spatial integration
# business: CFMG §X.Y — yearly activity plan structure: harvesting, planting, maintenance, etc.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from uuid import UUID
from decimal import Decimal
import json

from ..core.database import get_db
from ..core.idempotent_route import IdempotentRoute
from ..core.exceptions import i18n_success
from ..utils.auth import get_current_user
from ..models.user import User
from ..models.calculation import Calculation
from ..models.yearly_activities import PotentialActivity, ProposedYearlyActivity, ActivityYearDetail, ActivitySpatialAssignment, ActivityDrawnFeature
from ..models.forest_block import ForestBlock
import logging
from app.core.errors import CalculationErrors

from app.core.dropped import report_dropped

logger = logging.getLogger(__name__)

from ..services.operational_plan.feature_kinds import resolve_feature_kind
from ..services.optimistic_lock import check_and_bump
from ..services.yearly_plan_rules import (
    effective_budget,
    index_year_rows,
    total_budget as plan_total_budget,
)
from ..schemas.yearly_activities import (
    CalculationDrawnFeatureResponse,
    PotentialActivityResponse,
    ProposedActivityCreate,
    ProposedActivityUpdate,
    ProposedActivityResponse,
    ProposedActivityWithYears,
    ProposedActivityEnhancedResponse,
    YearDetailCreate,
    YearDetailUpdate,
    YearDetailResponse,
    ActivitySummary,
    ActivityLocationSummary,
    BulkProposedActivityCreate,
    DefaultActivitiesRequest,
    SpatialAssignmentCreate,
    SpatialAssignmentResponse,
    DrawnFeatureCreate,
    DrawnFeatureUpdate,
    DrawnFeatureResponse,
    BlockWithSubAreasResponse
)

router = APIRouter(route_class=IdempotentRoute)


def get_sub_area_info_from_result_data(result_data: dict, sub_area_id: UUID) -> dict:
    """Get sub-area name and category from calculation result_data"""
    if not result_data or not result_data.get('sub_areas'):
        return {}
    
    sub_area_id_str = str(sub_area_id)
    for sa in result_data.get('sub_areas', []):
        if str(sa.get('id')) == sub_area_id_str:
            return {
                "sub_area_name": sa.get('name'),
                "sub_area_category": sa.get('category')
            }
    return {}


# ===== POTENTIAL ACTIVITIES (Master List) =====
# business: master list of activity types seeded in potential_activities table

def _owned_activity(db: Session, activity_id: UUID, current_user: User) -> ProposedYearlyActivity:
    """The plan line, but only for the owner of its forest.

    Owner only — a super-admin gets the same 404 as anyone else (YEARLY_ACTIVITIES plan D9); the
    per-activity routes used to take ``current_user`` and never compare it to the owner (F12).
    """
    activity = (
        db.query(ProposedYearlyActivity)
        .join(Calculation, Calculation.id == ProposedYearlyActivity.calculation_id)
        .filter(
            ProposedYearlyActivity.id == activity_id,
            Calculation.user_id == current_user.id,
        )
        .first()
    )
    if not activity:
        raise HTTPException(status_code=404, detail="Proposed activity not found")
    return activity


@router.get("/potential-activities", response_model=List[PotentialActivityResponse])
def list_potential_activities(
    project_name: Optional[str] = Query(None),
    program: Optional[str] = Query(None),
    is_default: Optional[str] = Query(None),
    is_active: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all potential activities from master list.
    Used to populate the activity selection table.
    """
    query = db.query(PotentialActivity).filter(PotentialActivity.is_active == is_active)

    if project_name:
        query = query.filter(PotentialActivity.project_name == project_name)
    if program:
        query = query.filter(PotentialActivity.progarms == program)  # Note: typo in column name
    if is_default:
        query = query.filter(PotentialActivity.is_default == is_default)

    # Return as stored in database (by id, not alphabetical)
    query = query.order_by(PotentialActivity.id)
    activities = query.all()
    return [PotentialActivityResponse.from_orm(act) for act in activities]


@router.get("/calculations/{calculation_id}/potential-activities", response_model=List[PotentialActivityResponse])
def get_calculation_potential_activities(
    calculation_id: UUID,
    project_name: Optional[str] = Query(None),
    program: Optional[str] = Query(None),
    is_default: Optional[str] = Query(None),
    is_active: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List potential activities for a specific calculation.
    Returns all active potential activities that can be proposed for this forest.
    """
    query = db.query(PotentialActivity).filter(PotentialActivity.is_active == is_active)

    if project_name:
        query = query.filter(PotentialActivity.project_name == project_name)
    if program:
        query = query.filter(PotentialActivity.progarms == program)
    if is_default:
        query = query.filter(PotentialActivity.is_default == is_default)

    query = query.order_by(PotentialActivity.id)
    activities = query.all()
    return [PotentialActivityResponse.from_orm(act) for act in activities]


# ===== PROPOSED ACTIVITIES (Per Forest) =====
# constraint: fiscal year runs Ashadh end to Shrawan start (Nepali calendar)

@router.get("/calculations/{calculation_id}/proposed-activities", response_model=List[ProposedActivityWithYears])
def list_proposed_activities(
    calculation_id: UUID,
    block_id: Optional[UUID] = Query(None),
    sub_area_id: Optional[UUID] = Query(None),  # NEW: Spatial filtering
    sub_area_category: Optional[str] = Query(None),  # NEW: Filter by category
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all proposed activities for a specific forest.
    Includes spatial filtering by block, sub-area, or sub-area category.
    """
    # Verify ownership
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    # Query with eager loading
    query = db.query(ProposedYearlyActivity).options(
        joinedload(ProposedYearlyActivity.potential_activity),
        joinedload(ProposedYearlyActivity.block),
        joinedload(ProposedYearlyActivity.year_details),
        joinedload(ProposedYearlyActivity.spatial_assignments).joinedload(ActivitySpatialAssignment.block)
    ).filter(ProposedYearlyActivity.calculation_id == calculation_id)

    # Apply filters
    if block_id:
        query = query.filter(ProposedYearlyActivity.block_id == block_id)
    if sub_area_id:
        query = query.filter(ProposedYearlyActivity.sub_area_id == sub_area_id)
    if status:
        query = query.filter(ProposedYearlyActivity.status == status)

    proposed_activities = query.all()

    # Filter by sub_area_category using result_data
    if sub_area_category:
        proposed_activities = [
            pa for pa in proposed_activities
            if pa.sub_area_id and (
                get_sub_area_info_from_result_data(calculation.result_data, pa.sub_area_id).get("sub_area_category") == sub_area_category
            )
        ]

    # Format response with spatial details
    result = []
    for pa in proposed_activities:
        # Create base response
        pa_dict = {
            "id": pa.id,
            "calculation_id": pa.calculation_id,
            "potential_activity_id": pa.potential_activity_id,
            "block_id": pa.block_id,
            "sub_area_id": pa.sub_area_id,
            "default_quantity": pa.default_quantity,
            "default_yearly_budget": pa.default_yearly_budget,
            "notes": pa.notes,
            "status": pa.status,
            "created_at": pa.created_at,
            "updated_at": pa.updated_at,
            "version": pa.version,
            "reviewed_at": pa.reviewed_at,
        }

        # Add potential activity details
        if pa.potential_activity:
            pa_dict["potential_activity"] = PotentialActivityResponse.from_orm(pa.potential_activity)

        # Add spatial details
        if pa.block:
            pa_dict["block_name"] = pa.block.name

        if pa.sub_area_id:
            sub_area_info = get_sub_area_info_from_result_data(calculation.result_data, pa.sub_area_id)
            if sub_area_info:
                pa_dict["sub_area_name"] = sub_area_info.get("sub_area_name")
                pa_dict["sub_area_category"] = sub_area_info.get("sub_area_category")
                pa_dict["location_description"] = f"{sub_area_info.get('sub_area_name')} ({sub_area_info.get('sub_area_category')}), {pa_dict.get('block_name', '')}"
            else:
                pa_dict["location_description"] = f"Block: {pa_dict.get('block_name', '')} (Sub-Area ID: {pa.sub_area_id})"
        elif pa.block:
            pa_dict["location_description"] = f"{pa.block.name} (entire block)"
        else:
            pa_dict["location_description"] = "Entire forest"

        # Add year details
        pa_dict["year_details"] = [YearDetailResponse.from_orm(yd) for yd in pa.year_details]

        # Add spatial assignments with names
        sa_list = []
        for sa in pa.spatial_assignments:
            sa_dict = {
                "id": sa.id,
                "proposed_activity_id": sa.proposed_activity_id,
                "block_id": sa.block_id,
                "sub_area_id": sa.sub_area_id,
                "assignment_type": sa.assignment_type,
                "created_at": sa.created_at,
                "block_name": None,
                "sub_area_name": None
            }
            # Load block name if block_id exists
            if sa.block_id and sa.block:
                sa_dict["block_name"] = sa.block.name
            # Load sub-area name from result_data
            if sa.sub_area_id:
                sub_area_info = get_sub_area_info_from_result_data(calculation.result_data, sa.sub_area_id)
                if sub_area_info:
                    sa_dict["sub_area_name"] = sub_area_info.get("sub_area_name")
            sa_list.append(sa_dict)
        
        pa_dict["assign_to_all_blocks"] = pa.assign_to_all_blocks
        pa_dict["spatial_assignments"] = sa_list

        # Total budget over the ten years — a stored 0 is a real value, not "use the default"
        pa_dict["total_budget_10_years"] = plan_total_budget(
            pa.default_yearly_budget, pa.year_details
        )

        result.append(ProposedActivityWithYears(**pa_dict))

    return result


@router.post("/calculations/{calculation_id}/proposed-activities", response_model=ProposedActivityResponse)
def create_proposed_activity(
    calculation_id: UUID,
    activity_data: ProposedActivityCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Add a single activity to the forest's yearly plan.
    Supports spatial assignment to blocks and sub-areas.
    """
    # Verify ownership
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    # Verify potential activity exists
    potential = db.query(PotentialActivity).filter(
        PotentialActivity.id == activity_data.potential_activity_id,
        PotentialActivity.is_active == True
    ).first()
    if not potential:
        raise HTTPException(status_code=404, detail="Potential activity not found")

    # Check for duplicates (same activity, same block, same sub-area). `col == NULL` never matches
    # in SQL, so compare NULLs with IS NULL; the partial unique indexes (migration 091) are the
    # backstop for a concurrent double-submit.
    existing = db.query(ProposedYearlyActivity).filter(
        ProposedYearlyActivity.calculation_id == calculation_id,
        ProposedYearlyActivity.potential_activity_id == activity_data.potential_activity_id,
        (ProposedYearlyActivity.block_id == activity_data.block_id)
        if activity_data.block_id is not None
        else ProposedYearlyActivity.block_id.is_(None),
        (ProposedYearlyActivity.sub_area_id == activity_data.sub_area_id)
        if activity_data.sub_area_id is not None
        else ProposedYearlyActivity.sub_area_id.is_(None),
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Activity already added for this location")

    # Create proposed activity
    proposed = ProposedYearlyActivity(
        calculation_id=calculation_id,
        **activity_data.dict()
    )
    db.add(proposed)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Activity already added for this location")
    db.refresh(proposed)

    # Load relationships
    db.refresh(proposed, ['potential_activity', 'block'])

    # Get sub-area info from result_data
    sub_area_info = {}
    if proposed.sub_area_id:
        sub_area_info = get_sub_area_info_from_result_data(calculation.result_data, proposed.sub_area_id)

    # Format response
    response_dict = {
        "id": proposed.id,
        "calculation_id": proposed.calculation_id,
        "potential_activity_id": proposed.potential_activity_id,
        "block_id": proposed.block_id,
        "sub_area_id": proposed.sub_area_id,
        "default_quantity": proposed.default_quantity,
        "default_yearly_budget": proposed.default_yearly_budget,
        "notes": proposed.notes,
        "status": proposed.status,
        "created_at": proposed.created_at,
        "updated_at": proposed.updated_at,
        "assign_to_all_blocks": bool(proposed.assign_to_all_blocks),
        "version": proposed.version,
        "reviewed_at": proposed.reviewed_at,
    }

    if proposed.potential_activity:
        response_dict["potential_activity"] = PotentialActivityResponse.from_orm(proposed.potential_activity)
    if proposed.block:
        response_dict["block_name"] = proposed.block.name
    if proposed.sub_area_id and sub_area_info:
        response_dict["sub_area_name"] = sub_area_info.get("sub_area_name")
        response_dict["sub_area_category"] = sub_area_info.get("sub_area_category")
        response_dict["location_description"] = f"{sub_area_info.get('sub_area_name')} ({sub_area_info.get('sub_area_category')}), {proposed.block.name if proposed.block else ''}"
    elif proposed.block:
        response_dict["location_description"] = f"{proposed.block.name} (entire block)"
    else:
        response_dict["location_description"] = "Entire forest"

    return ProposedActivityResponse(**response_dict)


@router.patch("/proposed-activities/{proposed_activity_id}", response_model=ProposedActivityResponse)
def update_proposed_activity(
    proposed_activity_id: UUID,
    activity_update: ProposedActivityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update a proposed activity (e.g., change quantity, budget, block, sub-area assignment).
    """
    proposed = db.query(ProposedYearlyActivity).filter(
        ProposedYearlyActivity.id == proposed_activity_id
    ).first()
    if not proposed:
        raise HTTPException(status_code=404, detail="Proposed activity not found")

    # Verify ownership
    calculation = db.query(Calculation).filter(Calculation.id == proposed.calculation_id).first()
    if calculation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Take the plan line's version first (G-SYNC-2: a versioned row is not updated without it).
    # No version sent = accepted and logged, like the other web clients; a stale one is a 409.
    changes = activity_update.dict(exclude_unset=True)
    expected_version = changes.pop("expected_version", None)
    check_and_bump(db, "yearly_plan", proposed.id, expected_version)

    # Update fields
    for field, value in changes.items():
        setattr(proposed, field, value)

    db.commit()
    db.refresh(proposed, ['potential_activity', 'block'])

    # Get sub-area info from result_data
    sub_area_info = {}
    if proposed.sub_area_id:
        sub_area_info = get_sub_area_info_from_result_data(calculation.result_data, proposed.sub_area_id)

    # Format response
    response_dict = {
        "id": proposed.id,
        "calculation_id": proposed.calculation_id,
        "potential_activity_id": proposed.potential_activity_id,
        "block_id": proposed.block_id,
        "sub_area_id": proposed.sub_area_id,
        "default_quantity": proposed.default_quantity,
        "default_yearly_budget": proposed.default_yearly_budget,
        "notes": proposed.notes,
        "status": proposed.status,
        "created_at": proposed.created_at,
        "updated_at": proposed.updated_at,
        "assign_to_all_blocks": bool(proposed.assign_to_all_blocks),
        "version": proposed.version,
        "reviewed_at": proposed.reviewed_at,
    }

    if proposed.potential_activity:
        response_dict["potential_activity"] = PotentialActivityResponse.from_orm(proposed.potential_activity)
    if proposed.block:
        response_dict["block_name"] = proposed.block.name
    if proposed.sub_area_id and sub_area_info:
        response_dict["sub_area_name"] = sub_area_info.get("sub_area_name")
        response_dict["sub_area_category"] = sub_area_info.get("sub_area_category")
        response_dict["location_description"] = f"{sub_area_info.get('sub_area_name')} ({sub_area_info.get('sub_area_category')}), {proposed.block.name if proposed.block else ''}"
    elif proposed.block:
        response_dict["location_description"] = f"{proposed.block.name} (entire block)"
    else:
        response_dict["location_description"] = "Entire forest"

    return ProposedActivityResponse(**response_dict)


@router.delete("/proposed-activities/{proposed_activity_id}")
def delete_proposed_activity(
    proposed_activity_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Remove an activity from the forest's yearly plan.
    """
    proposed = db.query(ProposedYearlyActivity).filter(
        ProposedYearlyActivity.id == proposed_activity_id
    ).first()
    if not proposed:
        raise HTTPException(status_code=404, detail="Proposed activity not found")

    # Verify ownership
    calculation = db.query(Calculation).filter(Calculation.id == proposed.calculation_id).first()
    if calculation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    db.delete(proposed)
    db.commit()

    return {"status": "deleted", "id": str(proposed_activity_id)}


# ===== NEW: SPATIAL ENDPOINTS =====
# why: activities can be drawn as polygons on map or selected from predefined list

@router.get("/calculations/{calculation_id}/proposed-activities/spatial")
def get_activities_with_geometry(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all proposed activities with their spatial geometries.
    Used for map visualization.

    Returns GeoJSON-like structure with activity details.
    """
    # Verify ownership
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    # Query activities with spatial data
    query = db.query(
        ProposedYearlyActivity,
        PotentialActivity,
        ForestBlock
    ).join(
        PotentialActivity,
        ProposedYearlyActivity.potential_activity_id == PotentialActivity.id
    ).outerjoin(
        ForestBlock,
        ProposedYearlyActivity.block_id == ForestBlock.id
    ).filter(
        ProposedYearlyActivity.calculation_id == calculation_id
    )

    results = query.all()

    # Build sub-area lookup from result_data
    sub_areas_by_id = {}
    if calculation.result_data and calculation.result_data.get('sub_areas'):
        for sa in calculation.result_data.get('sub_areas', []):
            sub_areas_by_id[str(sa.get('id'))] = sa

    # Format for map display
    features = []
    for pa, pot, block in results:
        # Get sub-area info from result_data
        if not pa.sub_area_id:
            continue  # Skip activities without sub-area assignment
        
        sub_area = sub_areas_by_id.get(str(pa.sub_area_id))
        if not sub_area:
            continue  # Sub-area not found in result_data

        geometry = sub_area.get('geometry')

        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "activity_id": str(pa.id),
                "activity_name": pot.activities,
                "project_name": pot.project_name,
                "program": pot.progarms,
                "sub_area_name": sub_area.get('name'),
                "sub_area_category": sub_area.get('category'),
                "block_name": block.name if block else None,
                "quantity": float(pa.default_quantity),
                "unit": pot.unit,
                "yearly_budget": float(pa.default_yearly_budget),
                "total_budget_10_years": float(pa.default_yearly_budget * 10),
                "status": pa.status,
                "location_description": f"{pot.activities} in {sub_area.get('name')} ({sub_area.get('category')})"
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features
    }


@router.get("/calculations/{calculation_id}/location-summary", response_model=ActivityLocationSummary)
def get_activity_location_summary(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get summary of activities by spatial location.
    """
    # Verify ownership
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    # Get all proposed activities with relationships
    proposed_activities = db.query(ProposedYearlyActivity).options(
        joinedload(ProposedYearlyActivity.block)
    ).filter(ProposedYearlyActivity.calculation_id == calculation_id).all()

    # Initialize counters
    by_block = {}
    by_sub_area_category = {}
    by_sub_area = {}
    whole_forest_count = 0

    for pa in proposed_activities:
        # Count by block
        if pa.block:
            block_name = pa.block.name
            by_block[block_name] = by_block.get(block_name, 0) + 1
        else:
            whole_forest_count += 1

        # Count by sub-area
        if pa.sub_area_id:
            sub_area_info = get_sub_area_info_from_result_data(calculation.result_data, pa.sub_area_id)
            sub_area_name = sub_area_info.get("sub_area_name")
            category = sub_area_info.get("sub_area_category")

            if sub_area_name:
                by_sub_area[sub_area_name] = by_sub_area.get(sub_area_name, 0) + 1
            if category:
                by_sub_area_category[category] = by_sub_area_category.get(category, 0) + 1

    return ActivityLocationSummary(
        by_block=by_block,
        by_sub_area_category=by_sub_area_category,
        by_sub_area=by_sub_area,
        whole_forest_count=whole_forest_count
    )


# ===== SUMMARY & REPORTING =====
# why: activity summary aggregated by project/program/block/year for OP document

@router.get("/calculations/{calculation_id}/summary", response_model=ActivitySummary)
def get_activity_summary(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get summary statistics for all proposed activities.
    """
    # Verify ownership
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    # Get all proposed activities with relationships
    proposed_activities = db.query(ProposedYearlyActivity).options(
        joinedload(ProposedYearlyActivity.potential_activity),
        joinedload(ProposedYearlyActivity.block),
        joinedload(ProposedYearlyActivity.year_details)
    ).filter(ProposedYearlyActivity.calculation_id == calculation_id).all()

    # Initialize counters
    total_budget = Decimal(0)
    by_project = {}
    by_program = {}
    by_block = {}
    by_year = {year: Decimal(0) for year in range(1, 11)}
    # constraint: management plan horizon is 10 years (year 1-10)
    by_status = {}

    for pa in proposed_activities:
        pot = pa.potential_activity

        # Count by project
        if pot and pot.project_name:
            by_project[pot.project_name] = by_project.get(pot.project_name, 0) + 1

        # Count by program
        if pot and pot.progarms:
            by_program[pot.progarms] = by_program.get(pot.progarms, 0) + 1

        # Count by block
        block_name = pa.block.name if pa.block else "Unassigned"
        by_block[block_name] = by_block.get(block_name, 0) + 1

        # Count by status
        by_status[pa.status] = by_status.get(pa.status, 0) + 1

        # Calculate budget by year
        rows_by_year = index_year_rows(pa.year_details)
        for year in range(1, 11):
            budget = effective_budget(rows_by_year.get(year), pa.default_yearly_budget)

            by_year[year] += budget
            total_budget += budget

    return ActivitySummary(
        total_activities=len(proposed_activities),
        total_budget_10_years=total_budget,
        by_project=by_project,
        by_program=by_program,
        by_block=by_block,
        by_year={str(k): float(v) for k, v in by_year.items()},
        by_status=by_status
    )


# ===== NEW: SPATIAL ASSIGNMENT ENDPOINTS =====
# business: spatial assignments link activities to sub-areas via ActivitySpatialAssignment

@router.get("/proposed-activities/{activity_id}/spatial", response_model=List[SpatialAssignmentResponse])
def get_spatial_assignments(
    activity_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all spatial assignments for a proposed activity"""
    activity = _owned_activity(db, activity_id, current_user)
    
    assignments = db.query(ActivitySpatialAssignment).filter(
        ActivitySpatialAssignment.proposed_activity_id == activity_id
    ).all()
    
    # Get sub-area names from calculation result_data
    calculation = db.query(Calculation).filter(Calculation.id == activity.calculation_id).first()
    sub_area_names = {}
    if calculation and calculation.result_data and calculation.result_data.get('sub_areas'):
        for sa in calculation.result_data.get('sub_areas', []):
            sub_area_names[str(sa.get('id'))] = sa.get('name') or 'Sub-Area'
    
    result = []
    for a in assignments:
        sub_area_name = None
        if a.sub_area_id:
            sub_area_name = sub_area_names.get(str(a.sub_area_id))
        
        data = {
            "id": a.id,
            "proposed_activity_id": a.proposed_activity_id,
            "block_id": a.block_id,
            "sub_area_id": a.sub_area_id,
            "assignment_type": a.assignment_type,
            "created_at": a.created_at,
            "block_name": a.block.name if a.block else None,
            "sub_area_name": sub_area_name
        }
        result.append(SpatialAssignmentResponse(**data))
    
    return result


@router.post("/proposed-activities/{activity_id}/spatial", response_model=SpatialAssignmentResponse)
def create_spatial_assignment(
    activity_id: UUID,
    assignment_data: SpatialAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add spatial assignment for a proposed activity"""
    activity = _owned_activity(db, activity_id, current_user)
    
    check_and_bump(db, "yearly_plan", activity_id, None)
    assignment = ActivitySpatialAssignment(
        proposed_activity_id=activity_id,
        block_id=assignment_data.block_id,
        sub_area_id=assignment_data.sub_area_id,
        assignment_type=assignment_data.assignment_type
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    
    # Get sub-area name from calculation result_data
    calculation = db.query(Calculation).filter(Calculation.id == activity.calculation_id).first()
    sub_area_name = None
    if assignment.sub_area_id and calculation and calculation.result_data and calculation.result_data.get('sub_areas'):
        for sa in calculation.result_data.get('sub_areas', []):
            if str(sa.get('id')) == str(assignment.sub_area_id):
                sub_area_name = sa.get('name') or 'Sub-Area'
                break
    
    return SpatialAssignmentResponse(
        id=assignment.id,
        proposed_activity_id=assignment.proposed_activity_id,
        block_id=assignment.block_id,
        sub_area_id=assignment.sub_area_id,
        assignment_type=assignment.assignment_type,
        created_at=assignment.created_at,
        block_name=assignment.block.name if assignment.block else None,
        sub_area_name=sub_area_name
    )


@router.delete("/proposed-activities/{activity_id}/spatial/{assignment_id}")
def delete_spatial_assignment(
    activity_id: UUID,
    assignment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove spatial assignment"""
    _owned_activity(db, activity_id, current_user)
    check_and_bump(db, "yearly_plan", activity_id, None)
    assignment = db.query(ActivitySpatialAssignment).filter(
        ActivitySpatialAssignment.id == assignment_id,
        ActivitySpatialAssignment.proposed_activity_id == activity_id
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Spatial assignment not found")
    
    db.delete(assignment)
    db.commit()
    
    return {**i18n_success("success.spatial_assignment_deleted")}


# ===== NEW: DRAWN FEATURES ENDPOINTS =====

def _calculation_drawn_features(db: Session, calculation_id: UUID):
    """Query: the live drawn features of one calculation, via the activity that owns them.

    `activity_drawn_features.calculation_id` was added (migration 038) as a nullable column
    that no writer ever filled, so filtering on it alone matched nothing and the workspace's
    Activity Features layer was always empty. The owning activity always carries the
    calculation, so ask it - correct with or without the backfill (migration 089).
    """
    return (
        db.query(ActivityDrawnFeature)
        .join(ProposedYearlyActivity, ActivityDrawnFeature.proposed_activity_id == ProposedYearlyActivity.id)
        .filter(
            ProposedYearlyActivity.calculation_id == calculation_id,
            ActivityDrawnFeature.deleted_at.is_(None),
        )
    )


def _drawn_feature_response(f: ActivityDrawnFeature) -> DrawnFeatureResponse:
    """A drawn feature as the API returns it: `geometry` is a GeoJSON *string* (the schema's contract)."""
    from shapely.geometry import mapping as shapely_mapping
    from geoalchemy2.shape import to_shape

    try:
        geom_json = shapely_mapping(to_shape(f.geometry))
    except Exception as e:  # noqa: BLE001 -- one unreadable geometry must not blank the whole layer
        logger.error(f"Error mapping geometry of drawn feature {f.id}: {e}")
        geom_json = {"type": f.feature_type, "coordinates": []}
    return DrawnFeatureResponse(
        id=f.id,
        proposed_activity_id=f.proposed_activity_id,
        feature_type=f.feature_type,
        geometry=json.dumps(geom_json),
        properties=f.properties or {},
        created_at=f.created_at,
        updated_at=f.updated_at,
    )


@router.get("/proposed-activities/{activity_id}/drawn-features", response_model=List[DrawnFeatureResponse])
def get_drawn_features(
    activity_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all drawn features for a proposed activity"""
    _owned_activity(db, activity_id, current_user)
    
    features = db.query(ActivityDrawnFeature).filter(
        ActivityDrawnFeature.proposed_activity_id == activity_id
    ).order_by(ActivityDrawnFeature.created_at).all()
    
    result = []
    import shapely
    from shapely.geometry import mapping as shapely_mapping
    from geoalchemy2.shape import to_shape
    
    for f in features:
        try:
            feat_geom = to_shape(f.geometry)
            geom_json = shapely_mapping(feat_geom)
        except Exception as e:
            logger.error(f"Error mapping geometry: {e}")
            geom_json = {"type": f.feature_type, "coordinates": []}
        
        result.append(DrawnFeatureResponse(
            id=f.id,
            proposed_activity_id=f.proposed_activity_id,
            feature_type=f.feature_type,
            geometry=json.dumps(geom_json),
            properties=f.properties,
            created_at=f.created_at,
            updated_at=f.updated_at
        ))
    
    return result


@router.post("/proposed-activities/{activity_id}/drawn-features", response_model=DrawnFeatureResponse)
def create_drawn_feature(
    activity_id: UUID,
    feature_data: DrawnFeatureCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create drawn feature for a proposed activity"""
    import shapely
    from shapely.geometry import mapping as shapely_mapping
    from geoalchemy2.shape import to_shape
    from ..utils.geometry_utils import compute_geometry_properties, strip_geo_fields
    
    logger.debug(f"[create_drawn_feature] feature_data.properties: {feature_data.properties}")
    
    activity = _owned_activity(db, activity_id, current_user)
    
    # Strip geo_* from client payload (tamper-proof)
    clean_properties = strip_geo_fields(feature_data.properties or {})

    # No name given: use the activity's own, so every consumer (map label, attribute table,
    # KML) says what the feature is instead of "Feature 1".
    if not str(clean_properties.get("name") or "").strip():
        default_name = (
            db.query(PotentialActivity.activities)
            .filter(PotentialActivity.id == activity.potential_activity_id)
            .scalar()
        )
        if default_name:
            clean_properties["name"] = default_name
    
    geojson = json.loads(feature_data.geometry)
    coords = geojson["coordinates"]
    if feature_data.feature_type == "point":
        geom = shapely.Point(coords)
    elif feature_data.feature_type == "line":
        if len(coords) < 2:
            raise HTTPException(status_code=400, detail="Line requires at least 2 points")
        geom = shapely.LineString(coords)
    else:
        ring = coords[0] if coords and coords[0] and isinstance(coords[0][0], list) else coords
        if len(ring) < 4:
            raise HTTPException(status_code=400, detail="Polygon must have at least 4 points (including closing)")
        geom = shapely.Polygon(ring)
    
    # Compute geometry-derived properties (authoritative)
    geo_props = compute_geometry_properties(geom)
    
    # Merge computed properties into feature properties
    for k, v in geo_props.items():
        clean_properties[k] = v
    
    feature = ActivityDrawnFeature(
        proposed_activity_id=activity_id,
        calculation_id=activity.calculation_id,
        feature_type=feature_data.feature_type,
        geometry=f"SRID=4326;{geom.wkt}",  # lon/lat; SRID 0 makes every ST_Intersects against a block error
        properties=clean_properties,
        created_by=current_user.id,
    )
    db.add(feature)
    db.commit()
    db.refresh(feature)
    
    logger.debug(f"[create_drawn_feature] feature.properties after save: {feature.properties}")
    
    try:
        feat_geom = to_shape(feature.geometry)
        geom_json = shapely_mapping(feat_geom)
    except Exception as e:
        logger.error(f"Error mapping geometry: {e}")
        geom_json = {"type": feature_data.feature_type, "coordinates": []}
    
    response = DrawnFeatureResponse(
        id=feature.id,
        proposed_activity_id=feature.proposed_activity_id,
        feature_type=feature.feature_type,
        geometry=json.dumps(geom_json),
        properties=feature.properties,
        created_at=feature.created_at,
        updated_at=feature.updated_at
    )
    logger.debug(f"[create_drawn_feature] returning response.properties: {response.properties}")
    return response


@router.patch("/proposed-activities/{activity_id}/drawn-features/{feature_id}", response_model=DrawnFeatureResponse)
def update_drawn_feature(
    activity_id: UUID,
    feature_id: UUID,
    feature_data: DrawnFeatureUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update drawn feature"""
    _owned_activity(db, activity_id, current_user)
    import shapely
    from shapely.geometry import mapping as shapely_mapping
    from geoalchemy2.shape import to_shape
    from ..utils.geometry_utils import compute_geometry_properties, strip_geo_fields
    
    feature = db.query(ActivityDrawnFeature).filter(
        ActivityDrawnFeature.id == feature_id,
        ActivityDrawnFeature.proposed_activity_id == activity_id
    ).first()
    if not feature:
        raise HTTPException(status_code=404, detail="Drawn feature not found")
    
    # Strip geo_* from incoming properties (tamper-proof)
    props = dict(feature.properties or {})
    if feature_data.properties:
        client_props = strip_geo_fields(feature_data.properties)
        props.update(client_props)
    
    if feature_data.feature_type:
        feature.feature_type = feature_data.feature_type
    if feature_data.geometry:
        geojson = json.loads(feature_data.geometry)
        logger.debug(f"[update_drawn_feature] geometry: {feature_data.geometry}")
        coords = geojson["coordinates"]
        logger.debug(f"[update_drawn_feature] coords: {coords}, type: {feature_data.feature_type}")
        if feature_data.feature_type == "point":
            if coords and len(coords) >= 2 and coords[0] is not None and coords[1] is not None:
                geom = shapely.Point(coords)
            else:
                geom = shapely.Point(coords)
        elif feature_data.feature_type == "line":
            valid_coords = [c for c in coords if isinstance(c, list) and len(c) >= 2 and c[0] is not None and c[1] is not None]
            if len(valid_coords) < 2:
                raise HTTPException(status_code=400, detail="Line requires at least 2 valid points")
            geom = shapely.LineString(valid_coords)
        elif feature_data.feature_type == "polygon":
            ring = coords[0] if coords and coords[0] and isinstance(coords[0][0], list) else coords
            valid_ring = [c for c in ring if isinstance(c, list) and len(c) >= 2 and c[0] is not None and c[1] is not None]
            if len(valid_ring) < 3:
                raise HTTPException(status_code=400, detail="Polygon must have at least 3 valid coordinates")
            geom = shapely.Polygon(valid_ring)
        else:
            if coords and len(coords) >= 2 and coords[0] is not None and coords[1] is not None:
                geom = shapely.Point(coords)
            else:
                raise HTTPException(status_code=400, detail="Point requires valid coordinates")
        feature.geometry = geom.wkt
        
        # Compute geometry-derived properties on geometry change (authoritative)
        geo_props = compute_geometry_properties(geom)
        for k, v in geo_props.items():
            props[k] = v
    
    feature.properties = props
    db.commit()
    db.refresh(feature)
    
    try:
        feat_geom = to_shape(feature.geometry)
        geom_json = shapely_mapping(feat_geom)
    except Exception as e:
        logger.error(f"Error mapping geometry: {e}")
        geom_json = {"type": feature.feature_type, "coordinates": []}
    
    return DrawnFeatureResponse(
        id=feature.id,
        proposed_activity_id=feature.proposed_activity_id,
        feature_type=feature.feature_type,
        geometry=json.dumps(geom_json),
        properties=feature.properties,
        created_at=feature.created_at,
        updated_at=feature.updated_at
    )


@router.delete("/proposed-activities/{activity_id}/drawn-features/{feature_id}")
def delete_drawn_feature(
    activity_id: UUID,
    feature_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete drawn feature"""
    _owned_activity(db, activity_id, current_user)
    feature = db.query(ActivityDrawnFeature).filter(
        ActivityDrawnFeature.id == feature_id,
        ActivityDrawnFeature.proposed_activity_id == activity_id
    ).first()
    if not feature:
        raise HTTPException(status_code=404, detail="Drawn feature not found")
    
    db.delete(feature)
    db.commit()
    
    return {**i18n_success("success.drawn_feature_deleted")}


@router.get("/calculations/{calculation_id}/drawn-features/intersecting")
def get_intersecting_drawn_features(
    calculation_id: UUID,
    block_id: UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get drawn features that intersect a given block geometry."""
    calc = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id,
    ).first()
    if not calc:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    block = db.query(ForestBlock).filter(
        ForestBlock.id == block_id,
        ForestBlock.calculation_id == calculation_id,
    ).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")

    intersecting = (
        _calculation_drawn_features(db, calculation_id)
        .filter(
            func.ST_Intersects(
                func.ST_SetSRID(block.geometry, 4326),
                func.ST_SetSRID(ActivityDrawnFeature.geometry, 4326),
            ),
        )
        .all()
    )

    features = []
    for f in intersecting:
        features.append({
            "id": str(f.id),
            "name": f.properties.get("name") if f.properties else None,
            "type": "Point",
            "years": f.properties.get("years", []) if f.properties else [],
        })

    return {"features": features}


@router.post("/proposed-activities/{activity_id}/drawn-features/{feature_id}/copy", response_model=DrawnFeatureResponse)
def copy_drawn_feature(
    activity_id: UUID,
    feature_id: UUID,
    request: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Copy a drawn feature to a different year"""
    _owned_activity(db, activity_id, current_user)
    from shapely.geometry import mapping as shapely_mapping
    from geoalchemy2.shape import to_shape
    
    # Get the source feature
    source_feature = db.query(ActivityDrawnFeature).filter(
        ActivityDrawnFeature.id == feature_id,
        ActivityDrawnFeature.proposed_activity_id == activity_id
    ).first()
    if not source_feature:
        raise HTTPException(status_code=404, detail="Source feature not found")
    
    target_year = request.get('target_year')
    if not target_year:
        raise HTTPException(status_code=400, detail="target_year is required")
    
    # Check if feature with same geometry already exists for target year
    existing = db.query(ActivityDrawnFeature).filter(
        ActivityDrawnFeature.proposed_activity_id == activity_id,
        ActivityDrawnFeature.geometry == source_feature.geometry,
        ActivityDrawnFeature.properties['year'].astext == str(target_year)  # jsonb = integer does not exist
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail=f"Feature already exists for year {target_year}")
    
    # Create new feature
    new_feature = ActivityDrawnFeature(
        proposed_activity_id=activity_id,
        calculation_id=source_feature.calculation_id
        or db.query(ProposedYearlyActivity.calculation_id).filter(ProposedYearlyActivity.id == activity_id).scalar(),
        created_by=current_user.id,
        feature_type=source_feature.feature_type,
        geometry=source_feature.geometry,
        properties={
            **source_feature.properties,
            'year': target_year,
            'copied_from': str(source_feature.id)
        }
    )
    
    db.add(new_feature)
    db.commit()
    db.refresh(new_feature)
    
    try:
        feat_geom = to_shape(new_feature.geometry)
        geom_json = shapely_mapping(feat_geom)
    except Exception as e:
        logger.error(f"Error mapping geometry: {e}")
        geom_json = {"type": source_feature.feature_type, "coordinates": []}
    
    return DrawnFeatureResponse(
        id=new_feature.id,
        proposed_activity_id=new_feature.proposed_activity_id,
        feature_type=new_feature.feature_type,
        geometry=json.dumps(geom_json),
        properties=new_feature.properties,
        created_at=new_feature.created_at,
        updated_at=new_feature.updated_at
    )


# ===== YEAR DETAILS =====

@router.get("/proposed-activities/{activity_id}/year-details", response_model=List[YearDetailResponse])
def list_year_details(
    activity_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all year details for a proposed activity"""
    _owned_activity(db, activity_id, current_user)
    
    details = db.query(ActivityYearDetail).filter(
        ActivityYearDetail.proposed_activity_id == activity_id
    ).order_by(ActivityYearDetail.year_number).all()
    
    return [YearDetailResponse.from_orm(d) for d in details]


@router.post("/proposed-activities/{activity_id}/year-details", response_model=YearDetailResponse)
def create_year_detail(
    activity_id: UUID,
    detail_data: YearDetailCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a year detail for a proposed activity"""
    _owned_activity(db, activity_id, current_user)
    
    # Check if year detail already exists
    existing = db.query(ActivityYearDetail).filter(
        ActivityYearDetail.proposed_activity_id == activity_id,
        ActivityYearDetail.year_number == detail_data.year_number
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail=f"Year detail for year {detail_data.year_number} already exists")
    
    # a year edit bumps its plan line (version lock, plan §5.5)
    check_and_bump(db, "yearly_plan", activity_id, detail_data.expected_version)

    detail = ActivityYearDetail(
        proposed_activity_id=activity_id,
        year_number=detail_data.year_number,
        quantity=detail_data.quantity,
        yearly_budget=detail_data.yearly_budget,
        target_completion_month=detail_data.target_completion_month,
        actual_quantity=detail_data.actual_quantity,
        actual_budget=detail_data.actual_budget,
        status=detail_data.status or 'planned',
        notes=detail_data.notes
    )
    
    db.add(detail)
    db.commit()
    db.refresh(detail)
    
    return YearDetailResponse.from_orm(detail)


@router.patch("/proposed-activities/{activity_id}/year-details/{detail_id}", response_model=YearDetailResponse)
def update_year_detail(
    activity_id: UUID,
    detail_id: UUID,
    detail_data: YearDetailUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a year detail"""
    _owned_activity(db, activity_id, current_user)
    check_and_bump(db, "yearly_plan", activity_id, detail_data.expected_version)
    detail = db.query(ActivityYearDetail).filter(
        ActivityYearDetail.id == detail_id,
        ActivityYearDetail.proposed_activity_id == activity_id
    ).first()
    
    if not detail:
        raise HTTPException(status_code=404, detail="Year detail not found")
    
    # Update fields
    if detail_data.quantity is not None:
        detail.quantity = detail_data.quantity
    if detail_data.yearly_budget is not None:
        detail.yearly_budget = detail_data.yearly_budget
    if detail_data.target_completion_month is not None:
        detail.target_completion_month = detail_data.target_completion_month
    if detail_data.actual_quantity is not None:
        detail.actual_quantity = detail_data.actual_quantity
    if detail_data.actual_budget is not None:
        detail.actual_budget = detail_data.actual_budget
    if detail_data.status is not None:
        detail.status = detail_data.status
    if detail_data.notes is not None:
        detail.notes = detail_data.notes
    
    db.commit()
    db.refresh(detail)
    
    return YearDetailResponse.from_orm(detail)


@router.delete("/proposed-activities/{activity_id}/year-details/{detail_id}")
def delete_year_detail(
    activity_id: UUID,
    detail_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a year detail"""
    _owned_activity(db, activity_id, current_user)
    check_and_bump(db, "yearly_plan", activity_id, None)
    detail = db.query(ActivityYearDetail).filter(
        ActivityYearDetail.id == detail_id,
        ActivityYearDetail.proposed_activity_id == activity_id
    ).first()
    
    if not detail:
        raise HTTPException(status_code=404, detail="Year detail not found")
    
    db.delete(detail)
    db.commit()
    
    return {**i18n_success("success.year_detail_deleted")}


@router.get("/calculations/{calculation_id}/blocks-with-subareas")
def get_blocks_with_subareas(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get blocks with their sub-areas for a calculation"""
    from geoalchemy2.shape import to_shape
    from shapely.geometry import mapping
    
    # Verify ownership
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    
    result = []
    
    # 1. Return the forest boundary as "boundary" type (for map display)
    try:
        if calculation.boundary_geom:
            shp = to_shape(calculation.boundary_geom)
            geom_dict = mapping(shp)
            
            result.append({
                "id": f"{str(calculation.id)[:8]}-boundary",
                "name": calculation.forest_name or "Forest Boundary",
                "type": "boundary",
                "geometry": geom_dict
            })
    except Exception as e:
        logger.error(f"[DEBUG] Boundary Error: {e}")
    
    # 2. Return blocks from result_data (for map display)
    try:
        if calculation.result_data and calculation.result_data.get('blocks'):
            blocks = calculation.result_data.get('blocks', [])
            for block in blocks:
                block_geom = block.get('geometry')
                block_id = block.get('id') or block.get('block_id')
                if block_geom and block_id and len(str(block_id)) == 36:
                    result.append({
                        "id": str(block_id),
                        "name": block.get('block_name') or block.get('name') or "Block",
                        "type": "block",
                        "area_hectares": block.get('area_hectares') or block.get('area') or 0,
                        "geometry": block_geom
                    })
    except Exception as e:
        logger.error(f"[DEBUG] Blocks Error: {e}")
    
    # 3. Return sub-areas from result_data (primary source)
    try:
        if calculation.result_data and calculation.result_data.get('sub_areas'):
            sub_areas = calculation.result_data.get('sub_areas', [])
            
            for sa in sub_areas:
                sa_id = str(sa.get('id'))
                # Skip if not a valid UUID
                if not sa_id or len(sa_id) != 36:
                    continue
                    
                block_name = ""
                
                # Try to get block name from blocks in result_data
                if calculation.result_data.get('blocks'):
                    for block in calculation.result_data.get('blocks', []):
                        if block.get('block_id') == sa.get('blockId') or block.get('id') == sa.get('blockId'):
                            block_name = block.get('block_name') or block.get('name') or ""
                            break
                
                result.append({
                    "id": sa_id,
                    "name": sa.get('name') or "Sub-Area",
                    "type": "sub_area",
                    "category": sa.get('category') or '',
                    "area_hectares": sa.get('area_hectares') or 0,
                    "block_id": sa.get('blockId') or None,
                    "block_name": sa.get('blockName') or block_name,
                    "geometry": sa.get('geometry') or None
                })
    except Exception as e:
        logger.error(f"[DEBUG] SubAreas Error: {e}")
    
    return result


@router.get("/calculations/{calculation_id}/drawn-features", response_model=List[CalculationDrawnFeatureResponse])
def list_calculation_drawn_features(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all drawn features for a calculation (soft-delete excluded)."""
    calc = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()
    if not calc:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    rows = (
        _calculation_drawn_features(db, calculation_id)
        .outerjoin(PotentialActivity, PotentialActivity.id == ProposedYearlyActivity.potential_activity_id)
        .outerjoin(ForestBlock, ForestBlock.id == ProposedYearlyActivity.block_id)
        .add_columns(
            PotentialActivity.activities,
            PotentialActivity.progarms,
            ForestBlock.name,
            PotentialActivity.map_kind,
            PotentialActivity.unit,
            ProposedYearlyActivity.default_quantity,
        )
        .order_by(ActivityDrawnFeature.created_at.desc())
        .all()
    )
    # every place of one activity shares the plan line's quantity: say how many share it
    shared = {}
    for row in rows:
        shared[row[0].proposed_activity_id] = shared.get(row[0].proposed_activity_id, 0) + 1
    return [
        CalculationDrawnFeatureResponse(
            **_drawn_feature_response(f).model_dump(),
            activity_name=activity_name,
            program_name=program_name,
            block_name=block_name,
            kind=resolve_feature_kind((f.properties or {}).get("kind"), map_kind, f.feature_type),
            plan_quantity=float(default_quantity) if default_quantity is not None else None,
            plan_unit=unit,
            shared_count=shared[f.proposed_activity_id],
        )
        for f, activity_name, program_name, block_name, map_kind, unit, default_quantity in rows
    ]


@router.get("/calculations/{calculation_id}/drawn-features/collision-check")
def check_feature_collision(
    calculation_id: UUID,
    geometry: str = Query(..., description="GeoJSON geometry string"),
    exclude_feature_id: Optional[UUID] = None,
    buffer_meters: float = Query(0.5, description="Collision buffer in meters"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check if a proposed geometry collides with existing drawn features."""
    from geoalchemy2 import WKTElement
    from geoalchemy2.shape import from_shape, to_shape
    from shapely.geometry import shape
    from shapely import buffer as shapely_buffer

    calc = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()
    if not calc:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    try:
        geom_dict = json.loads(geometry)
        input_shape = shape(geom_dict)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid GeoJSON geometry")

    buffered = shapely_buffer(input_shape, buffer_meters / 111320.0)  # Approx deg per meter
    buffered_wkt = buffered.wkt

    query = _calculation_drawn_features(db, calculation_id).filter(
        func.ST_Intersects(
            func.ST_SetSRID(ActivityDrawnFeature.geometry, 4326),
            func.ST_GeomFromText(buffered_wkt, 4326),
        )
    )
    if exclude_feature_id:
        query = query.filter(ActivityDrawnFeature.id != exclude_feature_id)

    from geoalchemy2.shape import to_shape as g2s
    from shapely.geometry import mapping as shp_mapping

    colliding = query.all()

    collisions = []
    for f in colliding:
        try:
            f_shape = g2s(f.geometry)
            dist = round(input_shape.distance(f_shape) * 111320.0, 2)
        except Exception:
            report_dropped(
                logger, "collision distance",
                "the collision is reported with no distance to the feature",
            )
            dist = None
        collisions.append({
            "feature_id": str(f.id),
            "feature_type": f.feature_type,
            "properties": f.properties,
            "distance_from_input_m": dist,
        })

    return {
        "has_collision": len(colliding) > 0,
        "collision_count": len(colliding),
        "collisions": collisions,
    }


# ===== EXPORT SPATIAL FEATURES =====

@router.get("/proposed-activities/{activity_id}/export/kml")
def export_spatial_features_kml(
    activity_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Export drawn spatial features to KML format.
    """
    from xml.etree import ElementTree as ET
    from fastapi.responses import StreamingResponse
    from geoalchemy2.shape import to_shape
    import io
    
    activity = db.query(ProposedYearlyActivity).filter(
        ProposedYearlyActivity.id == activity_id
    ).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Proposed activity not found")
    
    calc = db.query(Calculation).filter(Calculation.id == activity.calculation_id).first()
    if not calc or calc.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    features = db.query(ActivityDrawnFeature).filter(
        ActivityDrawnFeature.proposed_activity_id == activity_id
    ).all()
    
    # Allow export even if no features (just reference layers)
    # if not features:
    #     raise HTTPException(status_code=404, detail="No spatial features to export")
    
    activity_name = "Spatial Features"
    if activity.potential_activity:
        activity_name = activity.potential_activity.activities or activity_name
    
    kml = ET.Element('kml', {'xmlns': 'http://www.opengis.net/kml/2.2'})
    document = ET.SubElement(kml, 'Document')
    
    ET.SubElement(document, 'name').text = f'{activity_name} - Spatial Features'
    ET.SubElement(document, 'description').text = (
        f'Exported from Community Forest Management System. '
        f'Activity: {activity_name}. '
        f'Total features: {len(features)}.'
    )
    
    # Add features folder (only drawn spatial features)
    features_folder = ET.SubElement(document, 'Folder')
    ET.SubElement(features_folder, 'name').text = f'Drawn Features ({len(features)})'
    
    style_map = {}
    
    for idx, feature in enumerate(features):
        from geoalchemy2.shape import to_shape
        from shapely.geometry import mapping as shapely_mapping
        
        try:
            geom = to_shape(feature.geometry)
        except Exception as e:
            logger.error(f"Error mapping geometry: {e}")
            continue
        
        feature_type = feature.feature_type
        feature_name = feature.properties.get('name', f'Feature {idx + 1}') if feature.properties else f'Feature {idx + 1}'
        feature_year = feature.properties.get('year', 'N/A') if feature.properties else 'N/A'
        
        if feature_type not in style_map:
            style_id = f'style_{feature_type}'
            style = ET.SubElement(document, 'Style', {'id': style_id})
            
            if feature_type == 'point':
                icon_style = ET.SubElement(style, 'IconStyle')
                ET.SubElement(icon_style, 'scale').text = '1.2'
                icon = ET.SubElement(icon_style, 'Icon')
                ET.SubElement(icon, 'href').text = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'
            elif feature_type == 'line':
                line_style = ET.SubElement(style, 'LineStyle')
                ET.SubElement(line_style, 'color').text = 'ff00ff00'
                ET.SubElement(line_style, 'width').text = '3'
            elif feature_type == 'polygon':
                poly_style = ET.SubElement(style, 'PolygonStyle')
                ET.SubElement(poly_style, 'color').text = '8000ff00'
                ET.SubElement(poly_style, 'outline').text = '1'
            
            style_map[feature_type] = style_id
        
        placemark = ET.SubElement(features_folder, 'Placemark')
        ET.SubElement(placemark, 'name').text = feature_name
        ET.SubElement(placemark, 'styleUrl').text = f'#{style_map[feature_type]}'
        
        desc = f'<b>{feature_name}</b><br/>'
        desc += f'Type: {feature_type.capitalize()}<br/>'
        desc += f'Year: {feature_year}<br/>'
        if feature.properties:
            for key, value in feature.properties.items():
                if key not in ['name', 'year']:
                    desc += f'{key}: {value}<br/>'
        
        ET.SubElement(placemark, 'description').text = desc
        
        if feature_type == 'point':
            coords = f'{geom.x:.7f},{geom.y:.7f},0'
            point_elem = ET.SubElement(placemark, 'Point')
            ET.SubElement(point_elem, 'coordinates').text = coords
        elif feature_type == 'line':
            coords_list = ' '.join([f'{p[0]:.7f},{p[1]:.7f},0' for p in geom.coords])
            ls_elem = ET.SubElement(placemark, 'LineString')
            ET.SubElement(ls_elem, 'tessellate').text = '1'
            ET.SubElement(ls_elem, 'coordinates').text = coords_list
        elif feature_type == 'polygon':
            ext_coords = ' '.join([f'{p[0]:.7f},{p[1]:.7f},0' for p in geom.exterior.coords])
            poly_elem = ET.SubElement(placemark, 'Polygon')
            outer = ET.SubElement(poly_elem, 'outerBoundaryIs')
            ls = ET.SubElement(outer, 'LinearRing')
            ET.SubElement(ls, 'coordinates').text = ext_coords
    
    ET.indent(kml)
    kml_bytes = ET.tostring(kml, encoding='unicode').encode('utf-8')
    
    # Use forest name and date in filename with proper Unicode encoding
    from datetime import datetime, timezone
    from urllib.parse import quote
    forest_name = calc.forest_name if calc.forest_name else 'Forest'
    date_str = datetime.now(timezone.utc).strftime('%Y%m%d')
    filename = f"{forest_name}_yearly_activities_{date_str}.kml"
    encoded_filename = quote(filename)
    
    return StreamingResponse(
        io.BytesIO(kml_bytes),
        media_type='application/vnd.google-earth.kml+xml',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"}
    )


@router.get("/proposed-activities/{activity_id}/export/gpkg")
def export_spatial_features_gpkg(
    activity_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Export drawn spatial features to GPKG format.
    """
    from fastapi.responses import StreamingResponse
    import io
    import tempfile
    import os
    
    activity = db.query(ProposedYearlyActivity).filter(
        ProposedYearlyActivity.id == activity_id
    ).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Proposed activity not found")
    
    calc = db.query(Calculation).filter(Calculation.id == activity.calculation_id).first()
    if not calc or calc.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    features = db.query(ActivityDrawnFeature).filter(
        ActivityDrawnFeature.proposed_activity_id == activity_id
    ).all()
    
    # Allow export even if no features (just reference layers)
    # if not features:
    #     raise HTTPException(status_code=404, detail="No spatial features to export")
    
    activity_name = "Spatial Features"
    if activity.potential_activity:
        activity_name = activity.potential_activity.activities or activity_name
    
    try:
        import geopandas as gpd
        from shapely.geometry import mapping
        from geoalchemy2.shape import to_shape
        import pandas as pd
        
        all_records = []
        
        # Add drawn features only
        for idx, feature in enumerate(features):
            try:
                geom = to_shape(feature.geometry)
                all_records.append({
                    'id': str(feature.id),
                    'name': feature.properties.get('name', f'Feature {idx + 1}') if feature.properties else f'Feature {idx + 1}',
                    'feature_type': feature.feature_type,
                    'year': feature.properties.get('year', '') if feature.properties else '',
                    'properties_json': json.dumps(feature.properties) if feature.properties else '{}',
                    'created_at': str(feature.created_at) if feature.created_at else '',
                    'geometry': geom
                })
            except Exception as e:
                logger.error(f"Error processing feature {feature.id}: {e}")
        
        if not all_records:
            raise HTTPException(status_code=404, detail="Failed to process any features")
        
        gdf = gpd.GeoDataFrame(all_records, crs='EPSG:4326')
        
        with tempfile.NamedTemporaryFile(suffix='.gpkg', delete=False) as tmp:
            tmp_path = tmp.name
        
        try:
            # Write all records to GPKG with layer column
            gdf.to_file(tmp_path, layer='spatial_data', driver='GPKG')
            
            with open(tmp_path, 'rb') as f:
                gpkg_bytes = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        
        # Use forest name and date in filename with proper Unicode encoding
        from urllib.parse import quote
        from datetime import datetime, timezone
        forest_name = calc.forest_name if calc.forest_name else 'Forest'
        date_str = datetime.now(timezone.utc).strftime('%Y%m%d')
        filename = f"{forest_name}_yearly_activities_{date_str}.gpkg"
        encoded_filename = quote(filename)
        
        return StreamingResponse(
            io.BytesIO(gpkg_bytes),
            media_type='application/octet-stream',
            headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"}
        )
        
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Required library not installed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
