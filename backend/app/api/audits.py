"""
Audit trail API endpoint for geometry mutations.
# business: all geometry changes must be traceable per QA.12
"""
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from ..core.database import get_db
from ..models.user import User
from ..utils.auth import get_current_active_user
from ..services.audit_service import get_audit_trail

router = APIRouter(tags=["audits"])


@router.get("/api/calculations/{calculation_id}/audits")
def get_audits(
    calculation_id: UUID,
    layer_type: Optional[str] = Query(None),
    operation: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get the audit trail for a calculation's geometry mutations."""
    return get_audit_trail(
        db=db,
        calculation_id=str(calculation_id),
        layer_type=layer_type,
        operation=operation,
        limit=limit,
        offset=offset,
    )
