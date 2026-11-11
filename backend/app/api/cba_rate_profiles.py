"""Org-wide CBA default rates — super-admin API (CBA_MODULE_PLAN.md P8).

The middle layer of the rate model: code ``FALLBACK_RATES`` ▸ **the ``global``
row here** ▸ per-scenario ``default_rates``. v1 is a single row (D4).

    GET /admin/cba-rates   → {rates, defaults}   (defaults = the code fallback)
    PUT /admin/cba-rates   body {rates: {...}}   → upsert the 'global' row
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.cba_rate_profile import CbaRateProfile
from app.models.user import User
from app.services.cost_benefit.repopulate import FALLBACK_RATES
from app.utils.auth import require_super_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["CBA Rate Profiles"])

_KEY = "global"
_ALLOWED = set(FALLBACK_RATES)


class RatesIn(BaseModel):
    # a null value clears the key so it falls through to FALLBACK_RATES
    rates: Dict[str, Optional[float]] = Field(default_factory=dict)


def _row(db: Session) -> CbaRateProfile:
    row = db.get(CbaRateProfile, _KEY)
    if row is None:
        row = CbaRateProfile(key=_KEY, label="Organisation default rates", rates={})
        db.add(row)
        db.flush()
    return row


@router.get("/admin/cba-rates")
def get_cba_rates(
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    row = _row(db)
    return {"rates": row.rates or {}, "defaults": FALLBACK_RATES}


@router.put("/admin/cba-rates")
def put_cba_rates(
    body: RatesIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    bad = set(body.rates) - _ALLOWED
    if bad:
        raise HTTPException(status_code=422, detail=f"unknown rate keys: {sorted(bad)}")
    for k, v in body.rates.items():
        if v is not None and (not isinstance(v, (int, float)) or v < 0):
            raise HTTPException(status_code=422, detail=f"{k}: rate must be ≥ 0")

    row = _row(db)
    # drop null / blank entries so they fall through to FALLBACK_RATES
    row.rates = {k: float(v) for k, v in body.rates.items() if v is not None}
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"rates": row.rates, "defaults": FALLBACK_RATES}
