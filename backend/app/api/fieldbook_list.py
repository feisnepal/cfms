"""
Fieldbook list API endpoint - lists all fieldbooks across calculations.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, Integer

from app.core.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.models.calculation import Calculation
from app.models.fieldbook import Fieldbook

router = APIRouter()


@router.get("/fieldbook")
def list_all_fieldbooks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all fieldbook records for the current user across all calculations.
    """
    # Get all calculations for the user that have fieldbook entries
    results = db.query(
        Calculation.id.label('calculation_id'),
        Calculation.forest_name,
        Calculation.created_at,
        func.count(Fieldbook.id).label('total_points'),
        func.sum(func.cast(Fieldbook.point_type == 'vertex', Integer)).label('original_vertices'),
        func.sum(func.cast(Fieldbook.point_type == 'interpolated', Integer)).label('interpolated_count')
    ).join(
        Fieldbook, Calculation.id == Fieldbook.calculation_id
    ).filter(
        Calculation.user_id == current_user.id
    ).group_by(
        Calculation.id, Calculation.forest_name, Calculation.created_at
    ).order_by(
        Calculation.created_at.desc()
    ).all()

    fieldbooks = []
    for r in results:
        fieldbooks.append({
            "id": str(r.calculation_id),
            "calculation_id": str(r.calculation_id),
            "forest_name": r.forest_name or "Unnamed Forest",
            "vertex_count": int(r.original_vertices or 0),
            "interpolated_count": int(r.interpolated_count or 0),
            "total_points": int(r.total_points or 0),
            "created_at": r.created_at.isoformat() if r.created_at else None
        })

    return fieldbooks
