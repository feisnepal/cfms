"""
Sampling list API endpoint - lists all sampling designs across calculations.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.models.calculation import Calculation
from app.models.sampling import SamplingDesign

router = APIRouter()


@router.get("/sampling")
def list_all_sampling_designs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all sampling designs for the current user across all calculations.
    """
    # Get all sampling designs for the user
    designs = db.query(
        SamplingDesign,
        Calculation.forest_name
    ).join(
        Calculation, SamplingDesign.calculation_id == Calculation.id
    ).filter(
        Calculation.user_id == current_user.id
    ).order_by(
        SamplingDesign.created_at.desc()
    ).all()

    samplings = []
    for design, forest_name in designs:
        samplings.append({
            "id": str(design.id),
            "calculation_id": str(design.calculation_id),
            "forest_name": forest_name or "Unnamed Forest",
            "design_type": design.sampling_type,
            "plot_count": design.total_plots,
            "plot_size": design.plot_size_sqm,
            "plot_shape": design.plot_shape,
            "created_at": design.created_at.isoformat() if design.created_at else None
        })

    return samplings
