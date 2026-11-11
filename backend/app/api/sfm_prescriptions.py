"""The दिगो वन व्यवस्थापन कार्यविधि, २०७९ अनुसूची-१ as editable data — super-admin API (P7).

``sfm_forest_type_prescriptions`` holds the 14 forest-type rows the classifier
and the yield engine read. A super admin retunes a silvicultural system, a
felling cycle or a yield step here and the next ``build_sfm(force=True)`` picks
it up — the guideline stays data, never Python.

    GET /admin/sfm-prescriptions            list all 14
    GET /admin/sfm-prescriptions/{type_no}  one
    PUT /admin/sfm-prescriptions/{type_no}  upsert (branches validated)

``branches`` is validated per the model docstring: a known ``method`` and
``basis``, and non-overlapping ``yield_rules.steps`` (two steps that could both
match the same growing stock → 422).
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.sfm_prescription import SfmForestTypePrescription
from app.models.user import User
from app.utils.auth import require_super_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SFM Prescriptions"])

_METHODS = {
    "selection_felling_cycle",
    "shelterwood_periodic_block",
    "stem_count",
    "area_coupe",
}
_BASES = {"growing_stock_pct_ge40", "stem_count", "area_volume", "none"}


class StepIn(BaseModel):
    model_config = {"extra": "forbid"}

    gs_per_ha_min: Optional[float] = Field(None, ge=0.0)
    gs_per_ha_max: Optional[float] = Field(None, ge=0.0)
    pct: float = Field(ge=0.0, le=100.0)

    @model_validator(mode="after")
    def _min_below_max(self) -> "StepIn":
        if (
            self.gs_per_ha_min is not None
            and self.gs_per_ha_max is not None
            and self.gs_per_ha_min >= self.gs_per_ha_max
        ):
            raise ValueError("gs_per_ha_min must be < gs_per_ha_max")
        return self


class YieldRulesIn(BaseModel):
    model_config = {"extra": "forbid"}

    basis: str = "none"
    steps: list[StepIn] = Field(default_factory=list)
    target_stems_per_ha: Optional[list[float]] = None
    note_ne: str = ""
    note_en: str = ""

    @field_validator("basis")
    @classmethod
    def _known_basis(cls, v: str) -> str:
        if v not in _BASES:
            raise ValueError(f"basis must be one of {sorted(_BASES)}")
        return v

    @field_validator("steps", mode="before")
    @classmethod
    def _none_steps_to_list(cls, v):
        # the seed rows carry `steps: null` for stem-count / area-volume branches
        return v if v is not None else []

    @model_validator(mode="after")
    def _steps_do_not_overlap(self) -> "YieldRulesIn":
        intervals = [
            (
                s.gs_per_ha_min if s.gs_per_ha_min is not None else float("-inf"),
                s.gs_per_ha_max if s.gs_per_ha_max is not None else float("inf"),
            )
            for s in self.steps
        ]
        for i in range(len(intervals)):
            for j in range(i + 1, len(intervals)):
                lo_i, hi_i = intervals[i]
                lo_j, hi_j = intervals[j]
                if lo_i < hi_j and lo_j < hi_i:  # half-open [lo, hi) intersect
                    raise ValueError(
                        f"yield_rules.steps overlap: step {i} and step {j} "
                        "can both match the same growing stock"
                    )
        return self


class BranchIn(BaseModel):
    model_config = {"extra": "forbid"}

    method: str
    system_ne: str = ""
    system_en: str = ""
    felling_cycle_years: Optional[int] = Field(None, ge=1, le=50)
    regeneration_period_years: Optional[int] = Field(None, ge=1, le=50)
    rotation_years: Optional[Union[int, list[int]]] = None
    regen_method_ne: str = ""
    regen_method_en: str = ""
    mother_trees_per_ha: Optional[list[float]] = None
    yield_rules: YieldRulesIn = Field(default_factory=YieldRulesIn)
    note_ne: str = ""
    note_en: str = ""

    @field_validator("method")
    @classmethod
    def _known_method(cls, v: str) -> str:
        if v not in _METHODS:
            raise ValueError(f"method must be one of {sorted(_METHODS)}")
        return v


class PrescriptionIn(BaseModel):
    model_config = {"extra": "forbid"}

    name_ne: str = Field(min_length=1, max_length=200)
    name_en: str = Field(min_length=1, max_length=200)
    species_groups: list[str] = Field(default_factory=list)
    zone_triggers: list[str] = Field(default_factory=list)
    slope_band: Optional[int] = Field(None, ge=1, le=4)
    origin: Optional[str] = None
    orientation: str = Field(min_length=1, max_length=20)
    branches: dict[str, BranchIn]
    notes_ne: Optional[str] = None
    notes_en: Optional[str] = None
    is_active: bool = True
    sort_order: int = 0

    @field_validator("origin")
    @classmethod
    def _origin_value(cls, v: Optional[str]) -> Optional[str]:
        if v not in (None, "natural", "plantation"):
            raise ValueError("origin must be natural | plantation | null")
        return v

    @field_validator("branches")
    @classmethod
    def _non_empty_branches(cls, v: dict) -> dict:
        if not v:
            raise ValueError("branches must have at least one entry")
        return v


def _dump(p: SfmForestTypePrescription) -> dict[str, Any]:
    return {
        "type_no": p.type_no,
        "name_ne": p.name_ne,
        "name_en": p.name_en,
        "species_groups": list(p.species_groups or []),
        "zone_triggers": list(p.zone_triggers or []),
        "slope_band": p.slope_band,
        "origin": p.origin,
        "orientation": p.orientation,
        "branches": p.branches or {},
        "notes_ne": p.notes_ne,
        "notes_en": p.notes_en,
        "is_active": p.is_active,
        "sort_order": p.sort_order,
    }


@router.get("/admin/sfm-prescriptions")
def list_prescriptions(
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    rows = (
        db.query(SfmForestTypePrescription)
        .order_by(SfmForestTypePrescription.type_no)
        .all()
    )
    return [_dump(r) for r in rows]


@router.get("/admin/sfm-prescriptions/{type_no}")
def get_prescription(
    type_no: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    row = db.get(SfmForestTypePrescription, type_no)
    if row is None:
        raise HTTPException(status_code=404, detail="Prescription not found")
    return _dump(row)


@router.put("/admin/sfm-prescriptions/{type_no}")
def upsert_prescription(
    type_no: int,
    body: PrescriptionIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    if not 1 <= type_no <= 14:
        raise HTTPException(status_code=422, detail="type_no must be 1..14")
    row = db.get(SfmForestTypePrescription, type_no)
    if row is None:
        row = SfmForestTypePrescription(type_no=type_no)
        db.add(row)
    row.name_ne = body.name_ne
    row.name_en = body.name_en
    row.species_groups = list(body.species_groups)
    row.zone_triggers = list(body.zone_triggers)
    row.slope_band = body.slope_band
    row.origin = body.origin
    row.orientation = body.orientation
    row.branches = {
        k: v.model_dump(exclude_none=False) for k, v in body.branches.items()
    }
    row.notes_ne = body.notes_ne
    row.notes_en = body.notes_en
    row.is_active = body.is_active
    row.sort_order = body.sort_order
    db.commit()
    return _dump(row)
