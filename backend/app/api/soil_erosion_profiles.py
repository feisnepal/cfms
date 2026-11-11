"""Org-wide RUSLE parameter presets — super-admin API (P7).

``soil_erosion_profiles`` is the middle layer of the soil-erosion parameter
model (code default ▸ **profile** ▸ per-forest override). A forest with no
per-forest override auto-picks the profile whose ``physiography_hint`` matches
its dominant ``admin.physiography`` zone (see
``soil_erosion_config._load_global_profile``).

    GET    /admin/soil-erosion-profiles           list all
    GET    /admin/soil-erosion-profiles/{key}     one
    PUT    /admin/soil-erosion-profiles/{key}     upsert (params validated)
    DELETE /admin/soil-erosion-profiles/{key}     remove

Editing any profile wipes every forest's soil-loss GeoTIFF + rendered-map cache
(profiles are a small blast radius and the caches are cheap to rebuild).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.soil_erosion_profile import SoilErosionProfile
from app.models.user import User
from app.services.operational_plan.soil_erosion_config import (
    SoilErosionParams,
    _deep_merge,
)
from app.utils.auth import require_super_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Soil Erosion Profiles"])


class ProfileIn(BaseModel):
    label_ne: str = Field(min_length=1, max_length=120)
    label_en: str = Field(min_length=1, max_length=120)
    physiography_hint: Optional[str] = Field(default=None, max_length=60)
    params: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    sort_order: int = 0


def _dump(p: SoilErosionProfile) -> dict[str, Any]:
    return {
        "key": p.key,
        "label_ne": p.label_ne,
        "label_en": p.label_en,
        "physiography_hint": p.physiography_hint,
        "params": p.params or {},
        "is_active": p.is_active,
        "sort_order": p.sort_order,
    }


def _invalidate_all() -> None:
    """A profile change can affect any forest that relies on it — wipe the whole
    soil-loss cache tree and the rendered-map caches."""
    import shutil
    from pathlib import Path

    try:
        shutil.rmtree(Path("uploads/soil_erosion_cache"), ignore_errors=True)
    except Exception:  # noqa: BLE001 -- best-effort
        logger.warning("soil-erosion cache wipe failed", exc_info=True)
    try:
        from app.services.management_plan_docx.plan_map_service import clear_map_cache

        clear_map_cache()  # all forests
    except Exception:  # noqa: BLE001 -- best-effort
        logger.warning("map cache wipe failed", exc_info=True)


@router.get("/admin/soil-erosion-profiles")
def list_profiles(
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    rows = (
        db.execute(
            select(SoilErosionProfile).order_by(
                SoilErosionProfile.sort_order, SoilErosionProfile.key
            )
        )
        .scalars()
        .all()
    )
    return [_dump(r) for r in rows]


@router.get("/admin/soil-erosion-profiles/{key}")
def get_profile(
    key: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    row = db.get(SoilErosionProfile, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _dump(row)


@router.put("/admin/soil-erosion-profiles/{key}")
def upsert_profile(
    key: str,
    body: ProfileIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    # the params patch must merge into a valid SoilErosionParams
    merged = _deep_merge(SoilErosionParams().model_dump(), body.params or {})
    try:
        SoilErosionParams(**merged)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=json.loads(e.json()))

    row = db.get(SoilErosionProfile, key)
    if row is None:
        row = SoilErosionProfile(key=key)
        db.add(row)
    row.label_ne = body.label_ne
    row.label_en = body.label_en
    row.physiography_hint = body.physiography_hint
    row.params = dict(body.params or {})
    row.is_active = body.is_active
    row.sort_order = body.sort_order
    db.commit()
    _invalidate_all()
    return _dump(row)


@router.delete("/admin/soil-erosion-profiles/{key}")
def delete_profile(
    key: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    row = db.get(SoilErosionProfile, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(row)
    db.commit()
    _invalidate_all()
    return {"deleted": key}
