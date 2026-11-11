"""Structural-change impact preview (FS-4a.15, the last task of P4a §11.2).

    POST /calculations/{id}/structure/preview-change   read-only dry-run

Wraps `forest_units.structure_impact.preview_structure_change` -- see that
module for the read-only classification logic. This router exists only to
expose it; it has no state of its own and writes nothing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.calculation import Calculation
from ..models.forest_block import ForestBlock
from ..models.user import User, UserRole
from ..utils.auth import get_current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Structure Impact"])


def _require_calc_access(
    db: Session, calculation_id: UUID, current_user: User
) -> Calculation:
    """Owner-or-SUPER_ADMIN gate (mirrors hazard_erosion/soil_erosion_params)."""
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc:
        raise HTTPException(status_code=404, detail="Calculation not found")
    if calc.user_id != current_user.id and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    return calc


class PreviewChangeRequest(BaseModel):
    feature_ids: List[str] = Field(
        ...,
        min_length=1,
        description="The unit(s) about to be reshaped/cut/merged/deleted.",
    )
    new_geometry: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "A GeoJSON geometry: the proposed replacement shape for the "
            "affected unit(s) (a reshape). Omit for delete/merge/cut, where "
            "the affected units simply stop existing."
        ),
    )


class PreviewImpactCounts(BaseModel):
    at_risk: int
    stays: int
    moves: int
    unassigned: int


class PreviewChangeResponse(BaseModel):
    affected_unit_ids: List[str]
    trees: PreviewImpactCounts
    plots: PreviewImpactCounts
    sampling_designs_affected: int
    stale_domains: List[str]


@router.post(
    "/calculations/{calculation_id}/structure/preview-change",
    response_model=PreviewChangeResponse,
)
def preview_change(
    calculation_id: UUID,
    body: PreviewChangeRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Read-only: what would happen to trees/plots/sampling if
    ``feature_ids`` changed to ``new_geometry`` (or were simply removed,
    when ``new_geometry`` is omitted)? Never writes anything -- safe to
    call speculatively before the user confirms an edit.

    404 when a given feature id does not belong to this calculation, so a
    stale client can't preview against another forest's units by accident.
    """
    calc = _require_calc_access(db, calculation_id, current_user)

    owned = (
        db.query(ForestBlock.id)
        .filter(
            ForestBlock.calculation_id == calc.id,
            ForestBlock.id.in_(body.feature_ids),
        )
        .count()
    )
    if owned != len(set(body.feature_ids)):
        raise HTTPException(
            status_code=404,
            detail="One or more feature_ids do not belong to this calculation",
        )

    from ..services.forest_units.structure_impact import preview_structure_change

    result = preview_structure_change(
        db, calc, feature_ids=body.feature_ids, new_geometry=body.new_geometry
    )
    return result
