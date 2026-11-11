"""RUSLE soil-loss parameters — per-forest override API.

``RUSLE_SOIL_LOSS_IMPLEMENTATION_PLAN.md`` §0.1 / §2 (P2).

Every RUSLE input is a *default* the user can override for one forest. The
override is a partial :class:`SoilErosionParams` stored under
``calculation.result_data['soil_erosion_params']``; :func:`resolve_params`
merges ``code default ▸ global profile (P7) ▸ this override``. A bad override
is rejected here (422) before it is ever stored, so the compute path never
sees one.

    GET    /calculations/{id}/soil-erosion-params  → resolved set + provenance
    PATCH  /calculations/{id}/soil-erosion-params  → validate + store a partial
    DELETE /calculations/{id}/soil-erosion-params  → drop the per-forest override
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.services.operational_plan.soil_erosion_config import (
    RESULT_DATA_KEY,
    SoilErosionParams,
    _deep_merge,
    resolve_params,
)
from app.utils.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_calc_access(
    db: Session, calculation_id: str, current_user: User
) -> Calculation:
    """Owner-or-SUPER_ADMIN gate (mirrors user_group._require_calc_access)."""
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


def _payload(calc_id: UUID, db: Session) -> dict[str, Any]:
    params = resolve_params(db, calc_id)
    return {
        "params": params.model_dump(),
        "provenance": dict(params._provenance),
        "customised": params.is_customised(),
    }


def _invalidate(calc_id: UUID) -> None:
    """Drop the soil-loss GeoTIFF cache *and* the rendered-map PNG cache so the
    next request re-computes and re-renders with the new parameters."""
    try:
        from app.services.operational_plan.soil_erosion import clear_cache

        clear_cache(calc_id)
    except Exception:  # noqa: BLE001 -- best-effort
        logger.warning("soil-erosion cache clear failed for %s", calc_id, exc_info=True)
    try:
        from app.services.management_plan_docx.plan_map_service import clear_map_cache

        clear_map_cache(calculation_id=calc_id)
    except Exception:  # noqa: BLE001 -- best-effort
        logger.warning("map cache clear failed for %s", calc_id, exc_info=True)


@router.get("/calculations/{calculation_id}/soil-erosion-params")
def get_soil_erosion_params(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _require_calc_access(db, calculation_id, current_user)
    return _payload(calc.id, db)


@router.patch("/calculations/{calculation_id}/soil-erosion-params")
def patch_soil_erosion_params(
    calculation_id: str,
    partial: dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _require_calc_access(db, calculation_id, current_user)
    if not isinstance(partial, dict) or not partial:
        raise HTTPException(status_code=422, detail="Body must be a non-empty object")

    # merge the incoming partial onto the current per-forest override (not onto
    # the resolved set — an override is a sparse patch), then validate the full
    # resolved result.
    rd = dict(calc.result_data or {})
    current_override = dict(rd.get(RESULT_DATA_KEY) or {})
    new_override = _deep_merge(current_override, partial)

    merged_full = _deep_merge(SoilErosionParams().model_dump(), new_override)
    try:
        SoilErosionParams(**merged_full)
    except ValidationError as e:
        # e.errors() can carry a raw ValueError in ctx (from a model_validator) —
        # e.json() renders it JSON-safe.
        import json

        raise HTTPException(status_code=422, detail=json.loads(e.json()))

    rd[RESULT_DATA_KEY] = new_override
    calc.result_data = rd  # JSONB in-place mutation trap — reassign
    db.commit()
    _invalidate(calc.id)
    return _payload(calc.id, db)


@router.delete("/calculations/{calculation_id}/soil-erosion-params")
def delete_soil_erosion_params(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _require_calc_access(db, calculation_id, current_user)
    rd = dict(calc.result_data or {})
    if RESULT_DATA_KEY in rd:
        rd.pop(RESULT_DATA_KEY, None)
        calc.result_data = rd
        db.commit()
        _invalidate(calc.id)
    return _payload(calc.id, db)
