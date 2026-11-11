"""Demand-supply analysis API endpoints.

Provides endpoints for household timber/fuelwood demand vs. forest supply
calculation, including AAH-based supply, private land supply, and
Nepali-language description generation.

See also:
    app.services.demand_supply_service — business logic
    app.schemas.metadata_form — demand-supply input schemas
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.services.demand_supply_service import (
    get_demand,
    get_community_forest_regular_supply,
    get_community_forest_aah_supply,
    get_private_supply,
    build_nepali_description,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/calculations/{calculation_id}/demand-supply")
def get_demand_supply(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return demand vs supply data for all forest product categories"""
    try:
        demand = get_demand(db, calculation_id)
        cf_regular = get_community_forest_regular_supply(db, calculation_id)
        cf_aah = get_community_forest_aah_supply(db, calculation_id)
        private = get_private_supply(db, calculation_id)

        products = ["firewood_bhari", "grass_bhari", "bedding_bhari", "timber_cft", "poles_count"]
        total_supply = {}
        deficit = {}

        for key in products:
            cr = cf_regular.get(key)
            ca = cf_aah.get(key)
            pr = private.get(key)
            d = demand.get(key, 0) or 0

            parts = [v for v in (cr, ca, pr) if v is not None]
            total = sum(parts) if parts else 0
            total_supply[key] = round(total, 2) if isinstance(total, float) else total

            deficit[key] = round(total - d, 2) if isinstance(total, float) else (total - d)

        nepali_desc = build_nepali_description(
            demand, cf_regular, cf_aah, private, total_supply, deficit
        )

        return {
            "demand": demand,
            "supply_cf_regular": cf_regular,
            "supply_cf_aah": cf_aah,
            "supply_private": private,
            "total_supply": total_supply,
            "deficit": deficit,
            "nepali_description": nepali_desc,
        }
    except Exception as e:
        logger.error(f"Error computing demand-supply: {e}")
        raise HTTPException(status_code=500, detail=str(e))
