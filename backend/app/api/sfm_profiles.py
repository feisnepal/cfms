"""Org-wide Sustainable-Forest-Management parameter presets — super-admin API (P7).

``sfm_profiles`` is the middle layer of the SFM parameter model (code default ▸
**profile** ▸ per-forest override). A forest with no per-forest override
auto-picks the profile whose ``physiography_hint`` matches its dominant
``admin.physiography`` zone (see ``sfm_config._load_global_profile``).

    GET    /admin/sfm-profiles           list all
    GET    /admin/sfm-profiles/{key}     one
    PUT    /admin/sfm-profiles/{key}     upsert (params validated as SfmParams)
    DELETE /admin/sfm-profiles/{key}     remove

Editing a profile invalidates every forest's ``result_data['sfm']`` cache
lazily via ``params_hash`` (the resolved params change → the next
``build_sfm`` rebuilds), so nothing needs an explicit cache wipe here — mirrors
``cba_rate_profiles``, not the GeoTIFF-heavy hazard profiles.
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
from app.models.sfm_profile import SfmProfile
from app.models.user import User
from app.services.sustainable_fm.sfm_config import (
    SfmParams,
    SfmParamsPatch,
    _deep_merge,
)
from app.utils.auth import require_super_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SFM Profiles"])


class ProfileIn(BaseModel):
    label_ne: str = Field(min_length=1, max_length=120)
    label_en: str = Field(min_length=1, max_length=120)
    physiography_hint: Optional[str] = Field(default=None, max_length=60)
    params: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    sort_order: int = 0


def _dump(p: SfmProfile) -> dict[str, Any]:
    return {
        "key": p.key,
        "label_ne": p.label_ne,
        "label_en": p.label_en,
        "physiography_hint": p.physiography_hint,
        "params": p.params or {},
        "is_active": p.is_active,
        "sort_order": p.sort_order,
    }


def _validate_params(params: dict[str, Any]) -> None:
    """The sparse patch must (a) be a valid ``SfmParamsPatch`` on its own and
    (b) still produce a valid ``SfmParams`` once merged onto the defaults."""
    try:
        SfmParamsPatch(**(params or {}))
        SfmParams(**_deep_merge(SfmParams().model_dump(), params or {}))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=json.loads(e.json()))


@router.get("/admin/sfm-profiles")
def list_profiles(
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    rows = (
        db.execute(select(SfmProfile).order_by(SfmProfile.sort_order, SfmProfile.key))
        .scalars()
        .all()
    )
    return [_dump(r) for r in rows]


@router.get("/admin/sfm-profiles/{key}")
def get_profile(
    key: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    row = db.get(SfmProfile, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _dump(row)


@router.put("/admin/sfm-profiles/{key}")
def upsert_profile(
    key: str,
    body: ProfileIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    _validate_params(body.params)
    row = db.get(SfmProfile, key)
    if row is None:
        row = SfmProfile(key=key)
        db.add(row)
    row.label_ne = body.label_ne
    row.label_en = body.label_en
    row.physiography_hint = body.physiography_hint
    row.params = dict(body.params or {})
    row.is_active = body.is_active
    row.sort_order = body.sort_order
    db.commit()
    return _dump(row)


@router.delete("/admin/sfm-profiles/{key}")
def delete_profile(
    key: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    row = db.get(SfmProfile, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(row)
    db.commit()
    return {"deleted": key}
