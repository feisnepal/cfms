"""Landslide hazard + household vulnerability — code-owned defaults and the
user-editable parameter schema.

See ``HOUSEHOLD_VULNERABILITY_ANALYSIS_PLAN.md`` §0.1 and §2 (P0 / P0-lit).

This module owns **only declaration**: the nested ``HazardVulnParams`` schema
(``LandslideParams`` + ``FactorOfSafetyParams`` + ``HouseholdVulnParams``), the
seed :data:`DEFAULT_PARAMS`, the three-layer :func:`resolve_params` merge, the
render-cache :func:`params_hash`, and the non-editable labels / citations. The
grid-aware maths (LSI weighted overlay, infinite-slope FS, the household score)
lives in ``landslide_susceptibility.py`` / ``slope_stability.py`` /
``household_vulnerability.py`` and reads a *resolved* ``HazardVulnParams`` — no
kernel touches a module constant here directly.

Parameter model (last layer wins)::

    DEFAULT_PARAMS                       code-owned seed (always complete)
      ▸ global profile                   hazard_vuln_profiles row   (P8 — stub here)
      ▸ per-forest override              calculation.result_data['hazard_vuln_params']

Because there is **no landslide inventory** in ``cf_db``, the LSI is a
transparent expert-weighted / AHP index — relative susceptibility, not
probability — and the FS map is a monsoon scenario with one assumed parameter
(regolith depth). Both caveats are printed in the plan. Full provenance for
every seed value is in :data:`CITATIONS`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Bump when a DEFAULT_PARAMS value or a kernel equation changes in a way that
# alters output for an unchanged override. Part of params_hash → the GeoTIFF /
# render cache key, so a bump re-computes every forest's hazard + HH surfaces.
CONFIG_VERSION = 2  # +household_coord_source (P10 building-footprint fallback)

# result_data key holding the per-forest partial override (a subset of the
# HazardVulnParams tree). Written by PATCH /calculations/{id}/hazard-vuln-params.
RESULT_DATA_KEY = "hazard_vuln_params"

# Canonical LSI factor order — the keys of LandslideParams.weights, the rows /
# columns of ahp_matrix, and the band order of the LSI factor GeoTIFF.
LSI_FACTORS: tuple[str, ...] = (
    "slope",
    "lithology",
    "curvature_twi",
    "dist_drainage",
    "dist_road",
    "landcover",
    "landcover_change",
    "aspect",
    "rainfall",
    "soil_texture",
)

# The household composite dimensions and the hazard sub-inputs.
HH_DIMENSIONS: tuple[str, ...] = (
    "hazard_exposure",
    "economic",
    "social",
    "forest_dependence",
    "demographic",
)
HH_HAZARD_INPUTS: tuple[str, ...] = (
    "lsi_class",
    "fs_class",
    "soil_loss",
    "dist_high_lsi_m",
    "dist_drainage_m",
)
_TLU_KEYS: tuple[str, ...] = ("cow_ox", "buffalo", "goat_sheep")


def _weights_to_ahp(weights: dict[str, float]) -> list[list[float]]:
    """A perfectly consistent (CR = 0) reciprocal matrix seed, m[i][j] =
    w[i]/w[j] in LSI_FACTORS order. The user perturbs it; the LSI engine's AHP
    path recovers weights from the principal eigenvector / geometric mean."""
    w = [max(weights[f], 1e-6) for f in LSI_FACTORS]
    return [[round(w[i] / w[j], 6) for j in range(len(w))] for i in range(len(w))]


# ─────────────────────────────────────────────────────────────────────────────
# Editable schema — Landslide Susceptibility Index
# ─────────────────────────────────────────────────────────────────────────────
class LandslideParams(BaseModel):
    """Weighted multi-criteria LSI (research §3.1). Every factor is reclassed to
    a 1–5 rating; weights come from :attr:`weights` (``weighted_overlay``) or the
    principal eigenvector of :attr:`ahp_matrix` (``ahp``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["weighted_overlay", "ahp"] = "weighted_overlay"

    # Σ wᵢ = 1 after the engine normalises; keys are fixed (LSI_FACTORS).
    # Bands are HKH / Nepal landslide-susceptibility practice (see
    # CITATIONS['lsi_weights']); slope + lithology dominate on Chure terrain.
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "slope": 0.28,
            "lithology": 0.20,
            "curvature_twi": 0.12,
            "dist_drainage": 0.10,
            "dist_road": 0.08,
            "landcover": 0.08,
            "landcover_change": 0.05,
            "aspect": 0.03,
            "rainfall": 0.04,
            "soil_texture": 0.02,
        }
    )
    # 10×10 Saaty reciprocal matrix, LSI_FACTORS order. Seeded exactly-consistent
    # from `weights`; used only when method == "ahp". Annex prints it + the CR.
    ahp_matrix: list[list[float]] = Field(
        default_factory=lambda: _weights_to_ahp(
            {
                "slope": 0.28,
                "lithology": 0.20,
                "curvature_twi": 0.12,
                "dist_drainage": 0.10,
                "dist_road": 0.08,
                "landcover": 0.08,
                "landcover_change": 0.05,
                "aspect": 0.03,
                "rainfall": 0.04,
                "soil_texture": 0.02,
            }
        )
    )

    # ── per-factor rating rules (each → 1..5) ───────────────────────────
    # slope angle (degrees): < b0 → 1, … , ≥ b3 → 5
    slope_rating_breaks_deg: list[float] = Field(
        default_factory=lambda: [10.0, 20.0, 30.0, 40.0]
    )
    # substring (case-insensitive) of geology.geology."geology class" → rating.
    # Empty by default; the engine applies `lithology_default_rating` for any
    # unit not matched, and a built-in fallback rule (Siwalik mudstone/shale → 5,
    # sandstone → 4, hard crystalline rock → 2, alluvium/colluvium → 3).
    lithology_ratings: dict[str, int] = Field(default_factory=dict)
    lithology_default_rating: int = Field(3, ge=1, le=5)
    # distance to drainage / road (m): < b0 → 5 (closest, worst), … , ≥ b3 → 1
    dist_drainage_breaks_m: list[float] = Field(
        default_factory=lambda: [50.0, 100.0, 200.0, 400.0]
    )
    dist_road_breaks_m: list[float] = Field(
        default_factory=lambda: [50.0, 100.0, 200.0, 500.0]
    )
    # ESA WorldCover class → rating (forest low, bare high)
    landcover_ratings: dict[int, int] = Field(
        default_factory=lambda: {
            10: 1,  # tree cover
            20: 3,  # shrubland
            30: 3,  # grassland
            40: 4,  # cropland
            50: 1,  # built-up
            60: 5,  # bare / sparse
            70: 1,  # snow & ice
            80: 1,  # water
            90: 3,  # herbaceous wetland
            95: 2,  # mangroves
            100: 3,  # moss & lichen
        }
    )
    landcover_default_rating: int = Field(3, ge=1, le=5)
    # +rating where landcover_1984 was forest and ESA is now non-forest
    landcover_change_bump: int = Field(1, ge=0, le=3)
    # TWI above this percentile (of the AOI) is treated as wet-convergent → +1
    twi_high_percentile: float = Field(85.0, ge=50.0, le=99.0)
    twi_bump: int = Field(1, ge=0, le=3)
    # aspect codes 1..8 = N,NE,E,SE,S,SW,W,NW; monsoon-facing get +bump
    aspect_monsoon_codes: list[int] = Field(default_factory=lambda: [3, 4, 5])
    aspect_monsoon_bump: float = Field(0.5, ge=0.0, le=2.0)
    # annual precipitation (mm): < b0 → 1, … , ≥ b3 → 5
    rainfall_rating_breaks_mm: list[float] = Field(
        default_factory=lambda: [1200.0, 1800.0, 2400.0, 3000.0]
    )
    # soil_texture_class substring → rating (silt-rich / low-cohesion → higher)
    soil_texture_ratings: dict[str, int] = Field(
        default_factory=lambda: {
            "sand": 2,
            "loamy sand": 2,
            "sandy loam": 3,
            "loam": 3,
            "silt loam": 4,
            "silt": 4,
            "clay loam": 3,
            "silty clay": 4,
            "clay": 3,
        }
    )
    soil_texture_default_rating: int = Field(3, ge=1, le=5)

    # ── seismic predisposition (point catalogue → crude surface) ────────
    # OFF by default: hazards.earthquakes is a point catalogue, so this is
    # epicentral density / max felt MMI, NOT probabilistic ground motion. The
    # annex says so when it is enabled.
    seismic_enabled: bool = False
    seismic_radius_km: float = Field(25.0, gt=0.0, le=200.0)
    seismic_min_magnitude: float = Field(4.0, ge=0.0, le=9.0)
    seismic_weight: float = Field(0.05, ge=0.0, le=0.5)

    # ── classification of the LSI score → classes ──────────────────────
    class_method: Literal["quantile", "equal", "fixed"] = "quantile"
    n_classes: int = Field(5, ge=3, le=9)
    # used only when class_method == "fixed" (on the 1..5 weighted-mean scale)
    class_breaks_fixed: list[float] = Field(
        default_factory=lambda: [1.8, 2.6, 3.4, 4.2]
    )
    # the "landslide-prone area" polygon = LSI class ≥ this (1-based)
    prone_class_min: int = Field(4, ge=1, le=9)

    @model_validator(mode="after")
    def _check(self) -> "LandslideParams":
        if set(self.weights) != set(LSI_FACTORS):
            raise ValueError(f"weights keys must be exactly {sorted(LSI_FACTORS)}")
        if any(v <= 0 for v in self.weights.values()):
            raise ValueError("weights values must be positive")

        n = len(LSI_FACTORS)
        m = self.ahp_matrix
        if len(m) != n or any(len(row) != n for row in m):
            raise ValueError(f"ahp_matrix must be {n}×{n}")
        for i in range(n):
            if abs(m[i][i] - 1.0) > 1e-6:
                raise ValueError("ahp_matrix diagonal must be 1")
            for j in range(n):
                if m[i][j] <= 0:
                    raise ValueError("ahp_matrix entries must be positive")
                if abs(m[i][j] * m[j][i] - 1.0) > 1e-3:
                    raise ValueError(
                        f"ahp_matrix[{i}][{j}] and [{j}][{i}] are not reciprocal"
                    )

        for name, breaks, lo, hi, need in (
            ("slope_rating_breaks_deg", self.slope_rating_breaks_deg, 0.0, 90.0, 4),
            ("dist_drainage_breaks_m", self.dist_drainage_breaks_m, 0.0, 1e5, 4),
            ("dist_road_breaks_m", self.dist_road_breaks_m, 0.0, 1e5, 4),
            ("rainfall_rating_breaks_mm", self.rainfall_rating_breaks_mm, 0.0, 1e5, 4),
        ):
            if len(breaks) != need:
                raise ValueError(f"{name} must have exactly {need} breaks")
            if any(not (lo <= x <= hi) for x in breaks):
                raise ValueError(f"{name} out of range")
            if any(breaks[i] >= breaks[i + 1] for i in range(len(breaks) - 1)):
                raise ValueError(f"{name} must be strictly increasing")

        for name, ratings in (
            ("lithology_ratings", self.lithology_ratings),
            ("landcover_ratings", self.landcover_ratings),
            ("soil_texture_ratings", self.soil_texture_ratings),
        ):
            if any(not (1 <= r <= 5) for r in ratings.values()):
                raise ValueError(f"{name} values must be in 1..5")

        if self.class_method == "fixed":
            cb = self.class_breaks_fixed
            if len(cb) != self.n_classes - 1:
                raise ValueError("class_breaks_fixed must have n_classes-1 entries")
            if any(cb[i] >= cb[i + 1] for i in range(len(cb) - 1)):
                raise ValueError("class_breaks_fixed must be strictly increasing")
        if self.prone_class_min > self.n_classes:
            raise ValueError("prone_class_min cannot exceed n_classes")
        return self

    # ── pure helpers ──────────────────────────────────────────────────
    def lsi_class_label(self, idx: int, lang: str = "ne") -> str:
        if idx < 0:
            return NO_DATA_LABEL_NE if lang == "ne" else NO_DATA_LABEL_EN
        labels = LSI_CLASS_LABELS_NE if lang == "ne" else LSI_CLASS_LABELS_EN
        return labels[idx] if 0 <= idx < len(labels) else str(idx + 1)


# ─────────────────────────────────────────────────────────────────────────────
# Editable schema — infinite-slope Factor of Safety
# ─────────────────────────────────────────────────────────────────────────────
class FactorOfSafetyParams(BaseModel):
    """Infinite-slope FS run as a saturated-monsoon scenario (research §3.2).
    ``z`` (regolith depth) is the one genuinely assumed parameter — reported as
    a scenario, never as a probability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True

    #   constant      — z = depth_constant_m everywhere
    #   slope_linear  — z = z0 − k·slope°, clamped to [depth_min_m, depth_max_m]
    #                   (regolith thins on steep ground; Saulnier et al. 1997)
    soil_depth_model: Literal["constant", "slope_linear"] = "slope_linear"
    depth_constant_m: float = Field(1.5, gt=0.0, le=10.0)
    depth_slope_z0_m: float = Field(2.5, gt=0.0, le=10.0)
    depth_slope_k: float = Field(0.03, ge=0.0, le=0.5)
    depth_min_m: float = Field(0.5, gt=0.0, le=10.0)
    depth_max_m: float = Field(3.0, gt=0.0, le=20.0)

    # effective cohesion c′ (kPa) by soil_texture_class substring + a default
    cohesion_by_texture_kpa: dict[str, float] = Field(
        default_factory=lambda: {
            "sand": 1.0,
            "loamy sand": 2.0,
            "sandy loam": 3.0,
            "loam": 5.0,
            "silt loam": 6.0,
            "silt": 6.0,
            "clay loam": 8.0,
            "silty clay": 9.0,
            "clay": 10.0,
        }
    )
    cohesion_default_kpa: float = Field(5.0, ge=0.0, le=100.0)
    # effective friction angle φ′ (degrees) by texture substring + a default
    friction_by_texture_deg: dict[str, float] = Field(
        default_factory=lambda: {
            "sand": 33.0,
            "loamy sand": 32.0,
            "sandy loam": 31.0,
            "loam": 30.0,
            "silt loam": 28.0,
            "silt": 27.0,
            "clay loam": 26.0,
            "silty clay": 24.0,
            "clay": 23.0,
        }
    )
    friction_default_deg: float = Field(30.0, gt=0.0, lt=60.0)
    # root reinforcement added to c′ (kPa) by ESA WorldCover class
    root_cohesion_by_esa_class: dict[int, float] = Field(
        default_factory=lambda: {10: 3.0, 20: 1.5, 30: 0.5, 40: 0.2}
    )

    unit_weight_source: Literal["bulk_density", "constant"] = "bulk_density"
    gamma_default_kn_m3: float = Field(18.0, gt=5.0, le=30.0)
    gamma_w_kn_m3: float = Field(9.81, gt=0.0, le=15.0)

    # wet-season pore-pressure ratio m = h_w / z  (0 dry .. 1 fully saturated)
    saturation_ratio_m: float = Field(0.7, ge=0.0, le=1.0)
    # scale m across the AOI TWI percentile range (hollows wetter than noses)
    saturation_twi_varied: bool = True
    saturation_twi_low: float = Field(0.4, ge=0.0, le=1.0)
    saturation_twi_high: float = Field(1.0, ge=0.0, le=1.0)

    # FS → classes:  < b0 unstable, b0..b1 marginal, ≥ b1 stable
    fs_class_breaks: list[float] = Field(default_factory=lambda: [1.0, 1.5])
    instability_index: Literal["inv_fs", "sinmap_si"] = "inv_fs"

    @model_validator(mode="after")
    def _check(self) -> "FactorOfSafetyParams":
        if self.depth_min_m >= self.depth_max_m:
            raise ValueError("depth_min_m must be below depth_max_m")
        if not (self.depth_min_m <= self.depth_constant_m <= self.depth_max_m):
            raise ValueError(
                "depth_constant_m must be within [depth_min_m, depth_max_m]"
            )
        if self.saturation_twi_low > self.saturation_twi_high:
            raise ValueError("saturation_twi_low must not exceed saturation_twi_high")

        for name, table in (
            ("cohesion_by_texture_kpa", self.cohesion_by_texture_kpa),
            ("friction_by_texture_deg", self.friction_by_texture_deg),
        ):
            if any(v < 0 for v in table.values()):
                raise ValueError(f"{name} values must be non-negative")
        if any(v >= 60 for v in self.friction_by_texture_deg.values()):
            raise ValueError("friction_by_texture_deg values must be below 60°")
        if any(v < 0 for v in self.root_cohesion_by_esa_class.values()):
            raise ValueError("root_cohesion_by_esa_class values must be non-negative")

        b = self.fs_class_breaks
        if len(b) != 2:
            raise ValueError("fs_class_breaks must have exactly 2 breaks")
        if b[0] <= 0 or b[0] >= b[1]:
            raise ValueError("fs_class_breaks must be positive and increasing")
        return self

    def fs_class_label(self, idx: int, lang: str = "ne") -> str:
        if idx < 0:
            return NO_DATA_LABEL_NE if lang == "ne" else NO_DATA_LABEL_EN
        labels = FS_CLASS_LABELS_NE if lang == "ne" else FS_CLASS_LABELS_EN
        return labels[idx] if 0 <= idx < len(labels) else str(idx)


# ─────────────────────────────────────────────────────────────────────────────
# Editable schema — household vulnerability composite
# ─────────────────────────────────────────────────────────────────────────────
class HouseholdVulnParams(BaseModel):
    """Composite = Σ dimension_weights · normalised(dimension) over the geocoded
    ``household_information`` rows (research §4). Output stays at tole aggregate
    / house_no + score — never surname + caste + coordinates together."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "hazard_exposure": 0.35,
            "economic": 0.25,
            "social": 0.15,
            "forest_dependence": 0.15,
            "demographic": 0.10,
        }
    )
    normalisation: Literal["minmax", "quantile"] = "minmax"

    # NOTE (2026-10-05): the analysis now always uses building footprints, whatever this says, while
    # constants.HOUSEHOLD_SURVEY_COORDINATES_IN_VULNERABILITY is False.
    # Where each household's point comes from for sampling the hazard grids
    # (P10). "auto" = the survey lat/lon when it is real, else a building
    # footprint centroid in the household's settlement (from
    # ``user_group_buildings``); "survey" forces the survey coords even when
    # they are a placeholder; "building_footprint" forces the footprint path.
    household_coord_source: Literal["auto", "survey", "building_footprint"] = "building_footprint"

    # ── hazard-exposure sub-dimension ────────────────────────────────
    hazard_inputs: list[str] = Field(default_factory=lambda: list(HH_HAZARD_INPUTS))
    hazard_input_weights: dict[str, float] = Field(
        default_factory=lambda: {k: 1.0 for k in HH_HAZARD_INPUTS}
    )

    # ── economic sub-dimension ──────────────────────────────────────
    prosperity_rank: dict[str, float] = Field(
        default_factory=lambda: {
            "अति विपन्न": 1.0,
            "विपन्न": 0.66,
            "मध्यम": 0.33,
            "सम्पन्न": 0.0,
        }
    )
    prosperity_weight: float = Field(0.6, ge=0.0, le=1.0)
    land_per_capita_weight: float = Field(0.4, ge=0.0, le=1.0)
    # land per person (ropani): ≤ b0 → 1.0 (worst), ≥ b2 → 0.0
    land_per_capita_ropani_breaks: list[float] = Field(
        default_factory=lambda: [2.0, 5.0, 10.0]
    )
    kaththa_to_ropani: float = Field(0.6656, gt=0.0, le=5.0)

    # ── social sub-dimension ────────────────────────────────────────
    # case-insensitive substring match against caste_classification_en
    marginalised_castes: list[str] = Field(
        default_factory=lambda: [
            "dalit",
            "janajati",
            "adibasi",
            "endangered",
            "highly marginalized",
        ]
    )
    marginalised_weight: float = Field(0.7, ge=0.0, le=1.0)
    other_group_weight: float = Field(0.3, ge=0.0, le=1.0)

    # ── forest-dependence sub-dimension ─────────────────────────────
    forest_dependence_occupation_weight: float = Field(0.4, ge=0.0, le=1.0)
    forest_dependence_demand_weight: float = Field(0.35, ge=0.0, le=1.0)
    forest_dependence_livestock_weight: float = Field(0.25, ge=0.0, le=1.0)
    # Tropical Livestock Units for grazing pressure (Jahnke 1982 / FAO)
    tlu_weights: dict[str, float] = Field(
        default_factory=lambda: {"cow_ox": 0.7, "buffalo": 0.8, "goat_sheep": 0.1}
    )

    # ── demographic-sensitivity sub-dimension ───────────────────────
    demographic_female_headed_weight: float = Field(0.45, ge=0.0, le=1.0)
    demographic_female_ratio_weight: float = Field(0.25, ge=0.0, le=1.0)
    demographic_hh_size_weight: float = Field(0.30, ge=0.0, le=1.0)
    # household size: ≤ b0 → 0.0, ≥ b2 → 1.0 (larger → more sensitive)
    hh_size_breaks: list[float] = Field(default_factory=lambda: [3.0, 6.0, 9.0])

    # ── priority selection + roll-up ───────────────────────────────
    top_n: int = Field(15, ge=1, le=1000)
    top_fraction: float = Field(0.15, gt=0.0, le=1.0)
    settlement_key: Literal["address_tole", "nearest_settlement"] = "address_tole"
    building_fragility_breaks_sqm: list[float] = Field(
        default_factory=lambda: [30.0, 80.0, 150.0]
    )
    runout_buffer_m: float = Field(100.0, ge=0.0, le=2000.0)

    @model_validator(mode="after")
    def _check(self) -> "HouseholdVulnParams":
        if set(self.dimension_weights) != set(HH_DIMENSIONS):
            raise ValueError(
                f"dimension_weights keys must be exactly {sorted(HH_DIMENSIONS)}"
            )
        if any(v < 0 for v in self.dimension_weights.values()):
            raise ValueError("dimension_weights values must be non-negative")
        if sum(self.dimension_weights.values()) <= 0:
            raise ValueError("dimension_weights must not all be zero")

        if not self.hazard_inputs:
            raise ValueError("hazard_inputs must not be empty")
        unknown = set(self.hazard_inputs) - set(HH_HAZARD_INPUTS)
        if unknown:
            raise ValueError(f"hazard_inputs has unknown keys: {sorted(unknown)}")
        if any(
            self.hazard_input_weights.get(k, 0.0) < 0 for k in self.hazard_input_weights
        ):
            raise ValueError("hazard_input_weights values must be non-negative")

        if any(not (0.0 <= v <= 1.0) for v in self.prosperity_rank.values()):
            raise ValueError("prosperity_rank values must be in [0, 1]")

        for name, breaks in (
            ("land_per_capita_ropani_breaks", self.land_per_capita_ropani_breaks),
            ("hh_size_breaks", self.hh_size_breaks),
            ("building_fragility_breaks_sqm", self.building_fragility_breaks_sqm),
        ):
            if len(breaks) != 3:
                raise ValueError(f"{name} must have exactly 3 breaks")
            if any(x < 0 for x in breaks):
                raise ValueError(f"{name} must be non-negative")
            if any(breaks[i] >= breaks[i + 1] for i in range(len(breaks) - 1)):
                raise ValueError(f"{name} must be strictly increasing")

        if set(self.tlu_weights) != set(_TLU_KEYS):
            raise ValueError(f"tlu_weights keys must be exactly {sorted(_TLU_KEYS)}")
        if any(v < 0 for v in self.tlu_weights.values()):
            raise ValueError("tlu_weights values must be non-negative")
        return self


# ─────────────────────────────────────────────────────────────────────────────
# Top-level container
# ─────────────────────────────────────────────────────────────────────────────
class HazardVulnParams(BaseModel):
    """The three parameter groups behind one ``params_hash``, one profile row,
    one API. Frozen; callers hold a resolved instance for one compute."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    landslide: LandslideParams = Field(default_factory=LandslideParams)
    factor_of_safety: FactorOfSafetyParams = Field(default_factory=FactorOfSafetyParams)
    household: HouseholdVulnParams = Field(default_factory=HouseholdVulnParams)

    # key → "default" | "profile" | "forest"; excluded from model_dump so it
    # never enters params_hash.
    _provenance: dict[str, str] = PrivateAttr(default_factory=dict)

    def is_customised(self) -> bool:
        """True when any group came from a profile or a per-forest override."""
        return any(src != "default" for src in self._provenance.values())


# ─────────────────────────────────────────────────────────────────────────────
# Non-editable — labels, palette keys, citations
# ─────────────────────────────────────────────────────────────────────────────
NO_DATA_LABEL_NE = "कुनै तथ्याङ्क छैन"
NO_DATA_LABEL_EN = "No data"

# 5 LSI classes (Very Low → Very High). If n_classes is overridden the extra
# labels are unused / fall back to the numeric class.
LSI_CLASS_LABELS_NE = [
    "अति न्यून",
    "न्यून",
    "मध्यम",
    "उच्च",
    "अति उच्च",
]
LSI_CLASS_LABELS_EN = [
    "Very low",
    "Low",
    "Moderate",
    "High",
    "Very high",
]
# 3 FS classes (index 0 = unstable … 2 = stable)
FS_CLASS_LABELS_NE = ["अस्थिर", "सीमान्त", "स्थिर"]
FS_CLASS_LABELS_EN = ["Unstable", "Marginal", "Stable"]

# semantic_palettes keys (added to core/semantic_palettes.py + its frontend
# mirror in P4).
LSI_PALETTE_KEY = "landslide_susceptibility"  # green → yellow → red
FS_PALETTE_KEY = "slope_stability"  # red (unstable) → grey (stable)
HH_VULN_PALETTE_KEY = "household_vulnerability"  # graduated purples

FS_EQUATION = "FS = [c' + (γ − m·γ_w)·z·cos²β·tanφ'] / [γ·z·sinβ·cosβ]"

CITATIONS: dict[str, str] = {
    "vulnerability_framework": (
        "Wisner, B., Blaikie, P., Cannon, T., Davis, I. (2004). At Risk: "
        "Natural Hazards, People's Vulnerability and Disasters, 2nd ed. "
        "Routledge. — risk = hazard × exposure × vulnerability."
    ),
    "lsi_ahp": (
        "Saaty, T.L. (1980). The Analytic Hierarchy Process. McGraw-Hill. — "
        "pairwise-comparison weighting; consistency ratio CR < 0.10."
    ),
    "lsi_weights": (
        "Devkota, K.C., Regmi, A.D., Pourghasemi, H.R., Yoshida, K., Pradhan, "
        "B., Ryu, I.C., Dhital, M.R., Althuwaynee, O.F. (2013). Landslide "
        "susceptibility mapping using certainty factor, index of entropy and "
        "logistic regression models in GIS and their comparison at "
        "Mugling–Narayanghat road section, Nepal Himalaya. Natural Hazards "
        "65:135–165. — factor set and relative importance for the Nepal "
        "Siwalik / Middle Mountains."
    ),
    "lsi_no_inventory": (
        "No historical landslide inventory is available in cf_db, so the LSI "
        "is a transparent expert-weighted index — relative susceptibility, not "
        "probability, and unvalidated against mapped failures (research §3.4)."
    ),
    "infinite_slope": (
        "Hammond, C., Hall, D., Miller, S., Swetik, P. (1992). Level I "
        "Stability Analysis (LISA) Documentation for Version 2.0. USDA Forest "
        "Service GTR INT-285. — the infinite-slope Factor of Safety."
    ),
    "sinmap": (
        "Pack, R.T., Tarboton, D.G., Goodwin, C.N. (1998). The SINMAP approach "
        "to terrain stability mapping. 8th Congress of the IAEG, Vancouver. — "
        "topographic-wetness-driven stability index."
    ),
    "root_cohesion": (
        "Sidle, R.C. & Ochiai, H. (2006). Landslides: Processes, Prediction, "
        "and Land Use. AGU Water Resources Monograph 18. — root-reinforcement "
        "cohesion by vegetation type."
    ),
    "soil_depth": (
        "Saulnier, G.-M., Beven, K., Obled, C. (1997). Including spatially "
        "variable effective soil depths in TOPMODEL. J. Hydrology "
        "202:158–172. — the slope-dependent regolith-depth relation "
        "(the one assumed FS parameter)."
    ),
    "twi": (
        "Beven, K.J. & Kirkby, M.J. (1979). A physically based, variable "
        "contributing area model of basin hydrology. Hydrol. Sci. Bull. "
        "24:43–69. — TWI = ln(a / tanβ)."
    ),
    "sovi": (
        "Cutter, S.L., Boruff, B.J., Shirley, W.L. (2003). Social "
        "vulnerability to environmental hazards. Social Science Quarterly "
        "84(2):242–261. — the additive normalised social-vulnerability "
        "index this household composite adapts to the CFUG survey fields."
    ),
    "tlu": (
        "Jahnke, H.E. (1982). Livestock Production Systems and Livestock "
        "Development in Tropical Africa. Kieler Wissenschaftsverlag Vauk. — "
        "Tropical Livestock Unit coefficients (cattle 0.7, buffalo 0.8, "
        "sheep/goat 0.1)."
    ),
    "chure_fragility": (
        "President Chure–Tarai Madhesh Conservation Development Board (2017). "
        "Master Plan for the Conservation of the Chure Region, Nepal. — Chure "
        "physiography is inherently fragile (weak Siwalik lithology, steep "
        "slopes)."
    ),
    "landslide_hazard_nepal": (
        "Petley, D.N., Hearn, G.J., Hart, A., Rosser, N.J., Dunning, S.A., "
        "Oven, K., Mitchell, W.A. (2007). Trends in landslide occurrence in "
        "Nepal. Natural Hazards 43:23–44. — monsoon rainfall as the dominant "
        "landslide trigger."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Seed
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_PARAMS = HazardVulnParams()
DEFAULT_PARAMS._provenance = {k: "default" for k in HazardVulnParams.model_fields}


# ─────────────────────────────────────────────────────────────────────────────
# Resolution + cache key
# ─────────────────────────────────────────────────────────────────────────────
def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``over`` into a copy of ``base`` (dict values merged,
    everything else replaced). Lists are replaced wholesale, not concatenated."""
    out = dict(base)
    for key, val in (over or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _load_global_profile(db: Session, calculation_id: UUID) -> Optional[dict[str, Any]]:
    """The org-wide ``hazard_vuln_profiles`` layer (P8): the forest's dominant
    ``admin.physiography`` zone → the ``params`` patch of the profile whose
    ``physiography_hint`` matches. ``None`` when the table is absent (migration
    078 not applied), no zone intersects, or no profile matches."""
    from sqlalchemy import text

    # A missing admin.physiography / hazard_vuln_profiles table (test DB,
    # pre-migration) raises and would poison the request transaction — run the
    # whole lookup inside a SAVEPOINT so a failure rolls back just this.
    try:
        with db.begin_nested():
            zone = db.execute(
                text(
                    'SELECT p."physiography Zone" '
                    "FROM admin.physiography p, public.calculations c "
                    "WHERE c.id = :cid AND ST_Intersects(p.geom, c.boundary_geom) "
                    "ORDER BY ST_Area(ST_Intersection(p.geom, c.boundary_geom)) DESC "
                    "LIMIT 1"
                ),
                {"cid": str(calculation_id)},
            ).scalar()
            if not zone:
                return None
            row = db.execute(
                text(
                    "SELECT params FROM hazard_vuln_profiles "
                    "WHERE is_active AND physiography_hint = :z "
                    "ORDER BY sort_order LIMIT 1"
                ),
                {"z": zone},
            ).first()
        params = (row[0] if row else None) or None
        return params if isinstance(params, dict) and params else None
    except Exception:  # noqa: BLE001 -- table missing / DB hiccup → skip the layer
        return None


def _load_forest_override(
    db: Session, calculation_id: UUID
) -> Optional[dict[str, Any]]:
    """The per-forest partial override from ``calculation.result_data``."""
    from app.models.calculation import Calculation

    calc = (
        db.query(Calculation.result_data)
        .filter(Calculation.id == calculation_id)
        .first()
    )
    rd = (calc[0] if calc else None) or {}
    ov = rd.get(RESULT_DATA_KEY)
    return ov if isinstance(ov, dict) and ov else None


def _provenance_of(layers: list[tuple[str, dict[str, Any]]]) -> dict[str, str]:
    """Per-top-level-group (landslide / factor_of_safety / household): the name
    of the last layer that touched it."""
    prov = {k: "default" for k in HazardVulnParams.model_fields}
    for name, layer in layers:
        for key in layer or {}:
            if key in prov:
                prov[key] = name
    return prov


def resolve_params(db: Session, calculation_id: UUID) -> HazardVulnParams:
    """Merge ``DEFAULT_PARAMS ▸ global profile ▸ per-forest override``, validate,
    and stamp ``_provenance``.

    A validation failure in a layer is not fatal: it is logged (rate-limited)
    and that layer is dropped, so a bad override can never break the hazard /
    household maps — the API is where an override is *rejected* (422) before it
    is stored.
    """
    from app.core.dropped import report_dropped

    base = DEFAULT_PARAMS.model_dump()
    profile = _load_global_profile(db, calculation_id)
    forest = _load_forest_override(db, calculation_id)

    applied: list[tuple[str, dict[str, Any]]] = [("default", base)]
    merged = base
    for name, layer in (("profile", profile), ("forest", forest)):
        if not layer:
            continue
        candidate = _deep_merge(merged, layer)
        try:
            HazardVulnParams(**candidate)
        except Exception:  # noqa: BLE001 -- a bad layer is dropped, not fatal
            report_dropped(
                logger,
                f"hazard_vuln {name} params override (calc {calculation_id})",
                "layer ignored; falling back to the layer below",
            )
            continue
        merged = candidate
        applied.append((name, layer))

    params = HazardVulnParams(**merged)
    params._provenance = _provenance_of(applied)
    return params


def params_hash(params: HazardVulnParams) -> str:
    """Short stable digest of ``CONFIG_VERSION`` + the resolved params, for the
    GeoTIFF / render cache key. ``_provenance`` is a PrivateAttr and is not in
    ``model_dump`` — two forests with the same numbers share a cache entry."""
    blob = json.dumps(
        {"v": CONFIG_VERSION, "p": params.model_dump()},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


__all__ = [
    "CONFIG_VERSION",
    "RESULT_DATA_KEY",
    "LSI_FACTORS",
    "HH_DIMENSIONS",
    "HH_HAZARD_INPUTS",
    "LandslideParams",
    "FactorOfSafetyParams",
    "HouseholdVulnParams",
    "HazardVulnParams",
    "DEFAULT_PARAMS",
    "resolve_params",
    "params_hash",
    "LSI_CLASS_LABELS_NE",
    "LSI_CLASS_LABELS_EN",
    "FS_CLASS_LABELS_NE",
    "FS_CLASS_LABELS_EN",
    "LSI_PALETTE_KEY",
    "FS_PALETTE_KEY",
    "HH_VULN_PALETTE_KEY",
    "NO_DATA_LABEL_NE",
    "NO_DATA_LABEL_EN",
    "FS_EQUATION",
    "CITATIONS",
]
