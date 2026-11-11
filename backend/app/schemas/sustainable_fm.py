"""Response / request schemas for the Sustainable Forest Management API.

The API itself lands in P3 (`app/api/sustainable_fm.py`); these shapes are
declared in P0 so the analysis modules and the API can share them. Shapes track
``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §3.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SfmZone = Literal["LOWLAND_SAL", "HILL", "TEMPERATE", "HIGH_MOUNTAIN"]
FellingMethod = Literal[
    "selection_felling_cycle",
    "shelterwood_periodic_block",
    "stem_count",
    "area_coupe",
]


# ── per-block ───────────────────────────────────────────────────────────────
class SfmSpeciesShare(BaseModel):
    scientific: str
    local: Optional[str] = None
    genus: str
    group: str
    share_pct: float


class SfmZoneInfo(BaseModel):
    sfm_zone: SfmZone
    inner_terai: bool
    dom_phys: str
    slope_band: int
    slope_band_area_pct: dict[str, float]  # {"1":..,"2":..,"3":..,"4":..}


class SfmBlockRow(BaseModel):
    block_name: str
    area_ha: float
    zone: SfmZoneInfo
    dominant_species: list[SfmSpeciesShare] = Field(default_factory=list)
    dominant_group: Optional[str] = None
    regen_adequate: Optional[bool] = None
    growing_stock_m3_per_ha: Optional[float] = None
    gs_ge40_m3_per_ha: Optional[float] = None
    gs_ge40_m3: Optional[float] = None
    crown_density_pct: int
    origin: Literal["natural", "plantation"]
    source: Literal["stem_mapping", "field_inventory", "prior"]

    # None for a block that is not forest land, or has no sample plots (see block_status.py)
    proposed_type_no: Optional[int] = None
    estimate_type_no: Optional[int] = None
    state: Literal["classified", "provisional", "inventory_missing", "non_forest"] = "classified"
    plot_count: int = 0
    land_class: str = "forest"
    land_class_source: Literal["esa", "user"] = "esa"
    land_class_suggestion: str = "forest"
    override_land_class: Optional[str] = None
    confidence: float
    needs_review: bool
    reasons_ne: str
    reasons_en: str
    override_type_no: Optional[int] = None
    effective_type_no: Optional[int] = None

    prescription: Optional[dict[str, Any]] = None
    orientation: Optional[str] = None
    working_circle_proposal: Optional[dict[str, Any]] = None
    felling_series_id: Optional[int] = None


class SfmBlocksResponse(BaseModel):
    blocks: list[SfmBlockRow]
    source: Literal["stem_mapping", "field_inventory", "prior", "mixed"]
    generated_at: Optional[str] = None


# ── per felling series ─────────────────────────────────────────────────────
class SfmFellingSeriesRow(BaseModel):
    id: int
    type_no: int
    branch: Literal["adequate", "inadequate", "default"]
    method: FellingMethod
    C: Optional[int] = None  # felling cycle, years
    R: Optional[int] = None  # regeneration period, years
    N: Optional[int] = None  # felling areas / periodic blocks
    area_ha: float
    annual_felling_area_ha: Optional[float] = None
    gs_ge40_m3_per_ha: Optional[float] = None
    gs_ge40_m3: Optional[float] = None
    pct: Optional[float] = None
    annual_harvest_m3: Optional[float] = None
    note_ne: Optional[str] = None
    note_en: Optional[str] = None


class SfmForestSummary(BaseModel):
    dominant_type_no: Optional[int] = None
    type_area_breakdown: dict[str, float] = Field(default_factory=dict)
    production_area_ha: float = 0.0
    protection_area_ha: float = 0.0
    total_annual_harvest_m3: float = 0.0
    sampling_plan: list[dict[str, Any]] = Field(default_factory=list)


class SfmSummaryResponse(BaseModel):
    forest_summary: SfmForestSummary
    felling_series: list[SfmFellingSeriesRow] = Field(default_factory=list)
    source: Literal["stem_mapping", "field_inventory", "prior", "mixed"]
    generated_at: Optional[str] = None


# ── mutations ─────────────────────────────────────────────────────────────
class SfmBlockPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    override_type_no: Optional[int] = Field(None, ge=1, le=14)
    crown_density_pct: Optional[int] = Field(None, ge=0, le=100)
    origin: Optional[Literal["natural", "plantation"]] = None
    accept_working_circle: Optional[bool] = None


class SfmParamsGetResponse(BaseModel):
    params: dict[str, Any]
    provenance: dict[str, str]


# ── admin ─────────────────────────────────────────────────────────────────
class SfmPrescriptionRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type_no: int
    name_ne: str
    name_en: str
    species_groups: list[str]
    zone_triggers: list[str]
    slope_band: Optional[int] = None
    origin: Optional[str] = None
    orientation: str
    branches: dict[str, Any]
    notes_ne: Optional[str] = None
    notes_en: Optional[str] = None
    is_active: bool
    sort_order: int


class SfmProfileRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label_ne: str
    label_en: str
    physiography_hint: Optional[str] = None
    params: dict[str, Any]
    is_active: bool
    sort_order: int
