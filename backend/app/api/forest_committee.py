"""
Forest User Committee API endpoints
Handles CRUD operations for forest committee management
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from uuid import UUID

from ..core.database import get_db
from ..core.idempotent_route import IdempotentRoute
from ..core.exceptions import i18n_success
from ..utils.auth import get_current_user
from ..models.user import User
from ..models.calculation import Calculation
from ..models.forest_committee import ForestUserCommittee, AdvisoryCommittee, FinancialCommittee
from ..schemas.forest_committee import (
    ForestUserCommitteeCreate,
    ForestUserCommitteeUpdate,
    ForestUserCommitteeResponse,
    AdvisoryCommitteeCreate,
    AdvisoryCommitteeUpdate,
    AdvisoryCommitteeResponse,
    FinancialCommitteeCreate,
    FinancialCommitteeUpdate,
    FinancialCommitteeResponse,
    AllCommitteesResponse,
    CommitteeSummary,
    BulkCommitteeCreate
)
from ..services.forest_committee_service import ForestCommitteeValidation

router = APIRouter(route_class=IdempotentRoute)


# ============================================================================
# Get All Committees for a User Group
# ============================================================================

@router.get("/user-groups/{calculation_id}", response_model=AllCommitteesResponse)
def get_all_committees(
    calculation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all committee data for a user group"""
    # Verify calculation belongs to user
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=404, detail="User group not found")

    # Get all committee members
    main_members = db.query(ForestUserCommittee).filter(
        ForestUserCommittee.calculation_id == calculation_id
    ).order_by(ForestUserCommittee.serial_no).all()

    advisory_members = db.query(AdvisoryCommittee).filter(
        AdvisoryCommittee.calculation_id == calculation_id
    ).order_by(AdvisoryCommittee.serial_no).all()

    financial_members = db.query(FinancialCommittee).filter(
        FinancialCommittee.calculation_id == calculation_id
    ).order_by(FinancialCommittee.serial_no).all()

    # Calculate summary if there are main committee members
    summary = None
    if main_members:
        main_members_data = [
            {
                'gender': m.gender,
                'position': m.position,
                'name': m.name
            }
            for m in main_members
        ]

        stats = ForestCommitteeValidation.calculate_committee_summary(main_members_data)
        _, composition_warnings = ForestCommitteeValidation.validate_committee_composition(main_members_data)

        summary = CommitteeSummary(
            main_committee_size=stats['total'],
            main_committee_women=stats['women'],
            main_committee_men=stats['men'],
            women_percentage=stats['women_percentage'],
            meets_50_percent_rule=stats['meets_50_percent'],
            positions_filled=stats['positions_filled'],
            positions_unfilled=stats['unfilled_positions'],
            key_position_warnings=composition_warnings,
            advisory_committee_size=len(advisory_members),
            financial_committee_size=len(financial_members),
            validation_warnings=composition_warnings,
            validation_errors=[]
        )

    return AllCommitteesResponse(
        main_committee=[ForestUserCommitteeResponse.from_orm(m) for m in main_members],
        advisory_committee=[AdvisoryCommitteeResponse.from_orm(m) for m in advisory_members],
        financial_committee=[FinancialCommitteeResponse.from_orm(m) for m in financial_members],
        summary=summary
    )


# ============================================================================
# Create Committee Members (Bulk)
# ============================================================================

@router.post("/user-groups/{calculation_id}/bulk", response_model=AllCommitteesResponse)
def create_committees_bulk(
    calculation_id: UUID,
    data: BulkCommitteeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create multiple committee members at once"""
    # Verify calculation belongs to user
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=404, detail="User group not found")

    # Delete existing committee data
    db.query(ForestUserCommittee).filter(ForestUserCommittee.calculation_id == calculation_id).delete()
    db.query(AdvisoryCommittee).filter(AdvisoryCommittee.calculation_id == calculation_id).delete()
    db.query(FinancialCommittee).filter(FinancialCommittee.calculation_id == calculation_id).delete()

    # Create main committee members
    for member_data in data.main_committee:
        member = ForestUserCommittee(
            calculation_id=calculation_id,
            created_by=current_user.id,
            **member_data.dict()
        )
        db.add(member)

    # Create advisory committee members
    for member_data in data.advisory_committee:
        member = AdvisoryCommittee(
            calculation_id=calculation_id,
            created_by=current_user.id,
            **member_data.dict()
        )
        db.add(member)

    # Create financial committee members
    for member_data in data.financial_committee:
        member = FinancialCommittee(
            calculation_id=calculation_id,
            created_by=current_user.id,
            **member_data.dict()
        )
        db.add(member)

    db.commit()

    # Invalidate OP data cache so {{uc_members}} etc. show fresh data
    from app.models.op_data_cache import OpDataCache
    db.query(OpDataCache).filter(
        OpDataCache.calculation_id == calculation_id
    ).delete(synchronize_session=False)
    db.commit()

    # Return all committees
    return get_all_committees(calculation_id, current_user, db)


# ============================================================================
# Main Committee CRUD
# ============================================================================

@router.post("/user-groups/{calculation_id}/main", response_model=ForestUserCommitteeResponse)
def create_main_committee_member(
    calculation_id: UUID,
    member: ForestUserCommitteeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a single main committee member"""
    # Verify calculation belongs to user
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=404, detail="User group not found")

    # Check member count limit
    existing_count = db.query(ForestUserCommittee).filter(
        ForestUserCommittee.calculation_id == calculation_id
    ).count()

    if existing_count >= 15:
        raise HTTPException(status_code=400, detail="Main committee cannot exceed 15 members")

    new_member = ForestUserCommittee(
        calculation_id=calculation_id,
        created_by=current_user.id,
        **member.dict()
    )
    db.add(new_member)
    db.commit()
    db.refresh(new_member)

    return ForestUserCommitteeResponse.from_orm(new_member)


@router.put("/main/{member_id}", response_model=ForestUserCommitteeResponse)
def update_main_committee_member(
    member_id: UUID,
    updates: ForestUserCommitteeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a main committee member"""
    member = db.query(ForestUserCommittee).filter(ForestUserCommittee.id == member_id).first()

    if not member:
        raise HTTPException(status_code=404, detail="Committee member not found")

    # Verify user owns this calculation
    calculation = db.query(Calculation).filter(
        Calculation.id == member.calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Update fields
    update_data = updates.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(member, field, value)

    db.commit()
    db.refresh(member)

    return ForestUserCommitteeResponse.from_orm(member)


@router.delete("/main/{member_id}")
def delete_main_committee_member(
    member_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a main committee member"""
    member = db.query(ForestUserCommittee).filter(ForestUserCommittee.id == member_id).first()

    if not member:
        raise HTTPException(status_code=404, detail="Committee member not found")

    # Verify user owns this calculation
    calculation = db.query(Calculation).filter(
        Calculation.id == member.calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=403, detail="Not authorized")

    db.delete(member)
    db.commit()

    return {**i18n_success("success.committee_member_deleted")}


# ============================================================================
# Advisory Committee CRUD
# ============================================================================

@router.post("/user-groups/{calculation_id}/advisory", response_model=AdvisoryCommitteeResponse)
def create_advisory_member(
    calculation_id: UUID,
    member: AdvisoryCommitteeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create an advisory committee member"""
    # Verify calculation belongs to user
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=404, detail="User group not found")

    # Check member count limit
    existing_count = db.query(AdvisoryCommittee).filter(
        AdvisoryCommittee.calculation_id == calculation_id
    ).count()

    if existing_count >= 10:
        raise HTTPException(status_code=400, detail="Advisory committee cannot exceed 10 members")

    new_member = AdvisoryCommittee(
        calculation_id=calculation_id,
        created_by=current_user.id,
        **member.dict()
    )
    db.add(new_member)
    db.commit()
    db.refresh(new_member)

    return AdvisoryCommitteeResponse.from_orm(new_member)


@router.put("/advisory/{member_id}", response_model=AdvisoryCommitteeResponse)
def update_advisory_member(
    member_id: UUID,
    updates: AdvisoryCommitteeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an advisory committee member"""
    member = db.query(AdvisoryCommittee).filter(AdvisoryCommittee.id == member_id).first()

    if not member:
        raise HTTPException(status_code=404, detail="Committee member not found")

    # Verify user owns this calculation
    calculation = db.query(Calculation).filter(
        Calculation.id == member.calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Update fields
    update_data = updates.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(member, field, value)

    db.commit()
    db.refresh(member)

    return AdvisoryCommitteeResponse.from_orm(member)


@router.delete("/advisory/{member_id}")
def delete_advisory_member(
    member_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an advisory committee member"""
    member = db.query(AdvisoryCommittee).filter(AdvisoryCommittee.id == member_id).first()

    if not member:
        raise HTTPException(status_code=404, detail="Committee member not found")

    # Verify user owns this calculation
    calculation = db.query(Calculation).filter(
        Calculation.id == member.calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=403, detail="Not authorized")

    db.delete(member)
    db.commit()

    return {**i18n_success("success.advisory_member_deleted")}


# ============================================================================
# Financial Committee CRUD
# ============================================================================

@router.post("/user-groups/{calculation_id}/financial", response_model=FinancialCommitteeResponse)
def create_financial_member(
    calculation_id: UUID,
    member: FinancialCommitteeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a financial committee member"""
    # Verify calculation belongs to user
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=404, detail="User group not found")

    # Check member count limit
    existing_count = db.query(FinancialCommittee).filter(
        FinancialCommittee.calculation_id == calculation_id
    ).count()

    if existing_count >= 10:
        raise HTTPException(status_code=400, detail="Financial committee cannot exceed 10 members")

    new_member = FinancialCommittee(
        calculation_id=calculation_id,
        created_by=current_user.id,
        **member.dict()
    )
    db.add(new_member)
    db.commit()
    db.refresh(new_member)

    return FinancialCommitteeResponse.from_orm(new_member)


@router.put("/financial/{member_id}", response_model=FinancialCommitteeResponse)
def update_financial_member(
    member_id: UUID,
    updates: FinancialCommitteeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a financial committee member"""
    member = db.query(FinancialCommittee).filter(FinancialCommittee.id == member_id).first()

    if not member:
        raise HTTPException(status_code=404, detail="Committee member not found")

    # Verify user owns this calculation
    calculation = db.query(Calculation).filter(
        Calculation.id == member.calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Update fields
    update_data = updates.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(member, field, value)

    db.commit()
    db.refresh(member)

    return FinancialCommitteeResponse.from_orm(member)


@router.delete("/financial/{member_id}")
def delete_financial_member(
    member_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a financial committee member"""
    member = db.query(FinancialCommittee).filter(FinancialCommittee.id == member_id).first()

    if not member:
        raise HTTPException(status_code=404, detail="Committee member not found")

    # Verify user owns this calculation
    calculation = db.query(Calculation).filter(
        Calculation.id == member.calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=403, detail="Not authorized")

    db.delete(member)
    db.commit()

    return {**i18n_success("success.financial_member_deleted")}


# ============================================================================
# Delete All Committees
# ============================================================================

@router.delete("/user-groups/{calculation_id}")
def delete_all_committees(
    calculation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete all committee data for a user group"""
    # Verify calculation belongs to user
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=404, detail="User group not found")

    # Delete all committees
    main_deleted = db.query(ForestUserCommittee).filter(
        ForestUserCommittee.calculation_id == calculation_id
    ).delete()

    advisory_deleted = db.query(AdvisoryCommittee).filter(
        AdvisoryCommittee.calculation_id == calculation_id
    ).delete()

    financial_deleted = db.query(FinancialCommittee).filter(
        FinancialCommittee.calculation_id == calculation_id
    ).delete()

    db.commit()

    return {
        **i18n_success("success.committee_data_deleted"),
        "deleted": {
            "main_committee": main_deleted,
            "advisory_committee": advisory_deleted,
            "financial_committee": financial_deleted
        }
    }
