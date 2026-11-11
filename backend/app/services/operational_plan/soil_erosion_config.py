"""RUSLE soil-loss — code-owned defaults + the user-editable parameter schema.

See ``RUSLE_SOIL_LOSS_IMPLEMENTATION_PLAN.md`` §0.1 and §2 (P0 / P0-lit).

This module owns **only declaration**: the ``SoilErosionParams`` schema, the
seed :data:`DEFAULT_PARAMS`, the three-layer :func:`resolve_params` merge, the
render-cache :func:`params_hash`, and the non-editable labels / citations. The
grid-aware factor maths (R, K, LS, C, P over a raster) live in
``soil_erosion.py`` and read a *resolved* ``SoilErosionParams`` — no factor
touches a module constant here directly.

Parameter model (last layer wins)::

    DEFAULT_PARAMS                       code-owned seed (always complete)
      ▸ global profile                   soil_erosion_profiles row  (P7 — stub here)
      ▸ per-forest override              calculation.result_data['soil_erosion_params']

Seed values are Nepal-calibrated: Koirala et al. (2019, *Geosciences* 9:147)
for K / C / P / LS, Arnoldus (1980, tropical) for R, with Chalise et al.
(2020) as the daily-data R benchmark. Full provenance in :data:`CITATIONS`.
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

# Bump when a DEFAULT_PARAMS value or an equation in soil_erosion.py changes in
# a way that alters output for an unchanged override. Part of params_hash → the
# render / GeoTIFF cache key, so a bump re-computes every forest's soil-loss map.
CONFIG_VERSION = 1

# result_data key holding the per-forest partial override (a subset of the
# SoilErosionParams fields). Written by PATCH /calculations/{id}/soil-erosion-params.
RESULT_DATA_KEY = "soil_erosion_params"


# ─────────────────────────────────────────────────────────────────────────────
# Editable schema
# ─────────────────────────────────────────────────────────────────────────────
class MFICoeffs(BaseModel):
    """R = a · MFI^b  (Arnoldus 1980, tropical: a=0.07969, b=1.847;
    Renard & Freimund 1994 for MFI ≤ 55: a=0.07397, b=1.847)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    a: float = Field(0.07969, gt=0.0, le=10.0)
    b: float = Field(1.847, gt=0.0, le=4.0)


class AnnualRegCoeffs(BaseModel):
    """R = a · P + b  (P = mean annual rainfall, mm). Morgan (1985) form as
    used by Koirala et al. (2019) for Nepal: a=0.35, b=38.5. Cross-check only —
    under-predicts badly for monsoon Nepal (see CITATIONS['r_benchmark'])."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    a: float = Field(0.35, ge=0.0, le=50.0)
    b: float = Field(38.5, ge=-500.0, le=500.0)


class SoilErosionParams(BaseModel):
    """Every RUSLE input as a parameter with a default. Frozen: callers hold a
    resolved instance for the length of one compute. ``extra='forbid'`` so an
    unknown key in a per-forest override is rejected rather than silently kept.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # ── R — rainfall erosivity ──────────────────────────────────────────
    r_method: Literal["mfi", "annual_regression"] = "mfi"
    mfi_arnoldus_coeffs: MFICoeffs = Field(default_factory=MFICoeffs)
    # climate."world climate" carries 4 quarterly precip totals, not 12 months.
    #   even_split   — p_month = p_quarter / 3  (under-estimates MFI ⇒ conservative R)
    #   seasonal_fit — sinusoid on the 4 quarters anchored on wettest/driest month (P5+)
    mfi_from_quarters: Literal["even_split", "seasonal_fit"] = "even_split"
    annual_reg_coeffs: AnnualRegCoeffs = Field(default_factory=AnnualRegCoeffs)

    # ── K — soil erodibility ────────────────────────────────────────────
    #   williams  — EPIC (Sharpley & Williams 1990); needs sand/silt/clay/OC only
    #   wischmeier — nomograph; needs a texture→structure + texture→permeability class
    k_method: Literal["williams", "wischmeier"] = "williams"
    # SI K is clamped to this band — Koirala's Nepal K range is 0.014–0.023;
    # the wider bound guards against degenerate soil rows.
    k_floor: float = Field(0.0, ge=0.0, le=0.1)
    k_ceiling: float = Field(0.07, gt=0.0, le=0.2)

    # ── LS — slope length & steepness ───────────────────────────────────
    #   moore_burch  — McCool (1987) S × classic USLE L, capped length, NO flow
    #                  accumulation (v1 — plan D1)
    #   desmet_govers — Desmet & Govers (1996) L from D8 flow accumulation (P6)
    #                   via soil_erosion_d8.py; captures convergent hollows
    ls_method: Literal["moore_burch", "desmet_govers"] = "moore_burch"
    slope_length_cap_m: float = Field(122.0, ge=10.0, le=305.0)
    # LS is clamped to this — the classic capped-length L is naturally bounded,
    # but Desmet–Govers spikes in channel-head cells where RUSLE is not valid.
    # 60 keeps LS inside Koirala's national 2.5–59.5 envelope while preserving
    # the convergence signal on hillslopes.
    ls_cap: float = Field(60.0, gt=0.0, le=500.0)
    # USLE L exponent m by slope band (%). Keys are fixed; edit the values.
    ls_m_exponent_by_slope: dict[str, float] = Field(
        default_factory=lambda: {"lt1": 0.2, "1to3": 0.3, "3to5": 0.4, "gt5": 0.5}
    )

    # ── C — cover management ────────────────────────────────────────────
    # ESA WorldCover class → C. Koirala Table 2 (Forest/Shrub 0.03, Grass 0.01,
    # Agri 0.21, Barren 0.45, Water/Snow/Built 0.00) mapped onto ESA codes.
    c_by_esa_class: dict[int, float] = Field(
        default_factory=lambda: {
            10: 0.03,  # tree cover
            20: 0.03,  # shrubland
            30: 0.01,  # grassland
            40: 0.21,  # cropland
            50: 0.00,  # built-up
            60: 0.45,  # bare / sparse vegetation
            70: 0.00,  # snow & ice
            80: 0.00,  # permanent water
            90: 0.01,  # herbaceous wetland
            95: 0.03,  # mangroves
            100: 0.01,  # moss & lichen
        }
    )
    c_default: float = Field(0.20, ge=0.0, le=1.0)  # unknown ESA code
    # Modulate the forest/shrub C by canopy density (our enhancement — not in
    # Koirala): C scales linearly from ×canopy_c_min_multiplier at a closed
    # canopy (height ≥ canopy_closed_height_m, from canopy_height5m.tif) to ×1.0
    # at an open canopy (≤ canopy_open_height_m).
    canopy_modifier_enabled: bool = True
    canopy_modifier_classes: list[int] = Field(default_factory=lambda: [10, 20])
    canopy_c_min_multiplier: float = Field(0.03, gt=0.0, le=1.0)
    canopy_closed_height_m: float = Field(15.0, gt=0.0, le=60.0)
    canopy_open_height_m: float = Field(3.0, ge=0.0, le=30.0)
    # P6b — multiply C on cells that lost forest within the last
    # c_disturbance_recent_years (Hansen rasters.nepal_lossyear). 1.0 = off.
    c_disturbance_bump: float = Field(1.0, ge=1.0, le=5.0)
    c_disturbance_recent_years: int = Field(5, ge=1, le=25)

    # ── P — support practice ────────────────────────────────────────────
    # Applied to cropland only (terraced ≈ contouring in Nepal mid-hills);
    # every other land cover gets p_default. Shin (1999) / Koirala Table 3:
    # ordered (slope_upper_pct, P) bands — last band is the catch-all.
    p_cropland_esa_classes: list[int] = Field(default_factory=lambda: [40])
    p_cropland_slope_bands: list[tuple[float, float]] = Field(
        default_factory=lambda: [
            (7.0, 0.55),
            (11.3, 0.60),
            (17.6, 0.80),
            (26.8, 0.95),
            (999.0, 1.00),
        ]
    )
    p_default: float = Field(1.0, gt=0.0, le=1.0)

    # ── P6c — Sediment Delivery Ratio (InVEST-style connectivity SDR) ────
    # gross RUSLE A × SDR = sediment delivered to the stream network. Off by
    # default; `sdr_field` in soil_erosion_sdr.py. InVEST defaults for max/IC0/k.
    sdr_enabled: bool = False
    sdr_max: float = Field(0.8, gt=0.0, le=1.0)
    sdr_ic0: float = Field(0.5, ge=-5.0, le=5.0)
    sdr_k: float = Field(2.0, gt=0.0, le=10.0)
    # D8 contributing-cell count above which a cell is treated as a channel
    # (in addition to any rasterised river84 pixel).
    sdr_channel_accum_cells: int = Field(500, ge=1, le=1_000_000)
    # floor on the cover-management weighting factor W (= C) so 1/(W·S) is finite
    sdr_w_floor: float = Field(0.005, gt=0.0, le=0.5)

    # ── severity classification (the printed map + the tables) ──────────
    # N breaks → N+1 classes. Nepal / DoSWC scheme.
    severity_breaks: list[float] = Field(
        default_factory=lambda: [5.0, 10.0, 20.0, 40.0, 80.0]
    )
    tolerable_soil_loss: float = Field(
        10.0, gt=0.0, le=100.0
    )  # t ha⁻¹ yr⁻¹, hill soils

    # provenance is populated by resolve_params (key → "default"|"profile"|"forest");
    # excluded from model_dump so it never enters params_hash.
    _provenance: dict[str, str] = PrivateAttr(default_factory=dict)

    # ── cross-field checks ─────────────────────────────────────────────
    @model_validator(mode="after")
    def _check(self) -> "SoilErosionParams":
        if self.k_ceiling <= self.k_floor:
            raise ValueError("k_ceiling must exceed k_floor")
        if self.canopy_open_height_m >= self.canopy_closed_height_m:
            raise ValueError(
                "canopy_open_height_m must be below canopy_closed_height_m"
            )

        b = self.severity_breaks
        if len(b) < 1:
            raise ValueError("severity_breaks must have at least one break")
        if any(x <= 0 for x in b):
            raise ValueError("severity_breaks must be positive")
        if any(b[i] >= b[i + 1] for i in range(len(b) - 1)):
            raise ValueError("severity_breaks must be strictly increasing")

        for code, cval in self.c_by_esa_class.items():
            if not (0.0 <= cval <= 1.0):
                raise ValueError(f"c_by_esa_class[{code}] out of [0, 1]")

        bands = self.p_cropland_slope_bands
        if not bands:
            raise ValueError("p_cropland_slope_bands must not be empty")
        for i, (up, p) in enumerate(bands):
            if not (0.0 < p <= 1.0):
                raise ValueError(f"p_cropland_slope_bands[{i}] P out of (0, 1]")
            if i and up <= bands[i - 1][0]:
                raise ValueError("p_cropland_slope_bands upper edges must increase")

        for key in ("lt1", "1to3", "3to5", "gt5"):
            if key not in self.ls_m_exponent_by_slope:
                raise ValueError(f"ls_m_exponent_by_slope missing key {key!r}")
        if any(v <= 0 for v in self.ls_m_exponent_by_slope.values()):
            raise ValueError("ls_m_exponent_by_slope values must be positive")

        return self

    # ── severity helpers (pure, stdlib only) ───────────────────────────
    def severity_class(self, value: float) -> int:
        """0-based class index for a soil-loss value (t ha⁻¹ yr⁻¹). NaN / None
        → -1 (caller renders as No-data)."""
        if value is None or value != value:  # NaN
            return -1
        idx = 0
        for brk in self.severity_breaks:
            if value < brk:
                return idx
            idx += 1
        return idx  # last (open-ended) class

    def severity_label(self, idx: int, lang: str = "ne") -> str:
        if idx < 0:
            return NO_DATA_LABEL_NE if lang == "ne" else NO_DATA_LABEL_EN
        labels = SEVERITY_LABELS_NE if lang == "ne" else SEVERITY_LABELS_EN
        return labels[idx] if 0 <= idx < len(labels) else str(idx)

    def is_customised(self) -> bool:
        """True when any value came from a profile or a per-forest override."""
        return any(src != "default" for src in self._provenance.values())


# ─────────────────────────────────────────────────────────────────────────────
# Non-editable — labels, palette key, citations
# ─────────────────────────────────────────────────────────────────────────────
NO_DATA_LABEL_NE = "कुनै तथ्याङ्क छैन"
NO_DATA_LABEL_EN = "No data"

# 6 classes for the default 5 breaks [5, 10, 20, 40, 80]. If severity_breaks is
# shortened by an override the extra labels are simply unused; if lengthened,
# severity_label falls back to the numeric index.
SEVERITY_LABELS_NE = [
    "न्यून",  # < 5
    "मध्यम",  # 5–10
    "उच्च",  # 10–20
    "धेरै उच्च",  # 20–40
    "गम्भीर",  # 40–80
    "अति गम्भीर",  # > 80
]
SEVERITY_LABELS_EN = [
    "Slight",
    "Moderate",
    "High",
    "Very high",
    "Severe",
    "Very severe",
]

# semantic_palettes key for the classed surface (yellow → orange → red →
# dark-red). Added to core/semantic_palettes.py + its frontend mirror in P2.
SEVERITY_PALETTE_KEY = "soil_loss"

R_UNITS = "MJ mm ha⁻¹ h⁻¹ yr⁻¹"
K_UNITS = "t h MJ⁻¹ mm⁻¹"
A_UNITS = "t ha⁻¹ yr⁻¹"

CITATIONS: dict[str, str] = {
    "rusle": (
        "Renard, K.G., Foster, G.R., Weesies, G.A., McCool, D.K., Yoder, D.C. "
        "(1997). Predicting Soil Erosion by Water: RUSLE. USDA Agriculture "
        "Handbook 703."
    ),
    "r_mfi": (
        "Arnoldus, H.M.J. (1980). An approximation of the rainfall factor in "
        "the Universal Soil Loss Equation. In: De Boodt & Gabriels (eds), "
        "Assessment of Erosion. Wiley. — tropical form R = 0.07969·MFI^1.847."
    ),
    "r_mfi_alt": (
        "Renard, K.G. & Freimund, J.R. (1994). Using monthly precipitation "
        "data to estimate the R-factor in the revised USLE. J. Hydrology "
        "157:287–306. — a = 0.07397 for MFI ≤ 55."
    ),
    "r_regression": (
        "Morgan, R.P.C. (1985). Soil Erosion and Conservation. Soil "
        "Conservation Society of America. — R = 0.35·P + 38.5, as applied to "
        "Nepal by Koirala et al. (2019)."
    ),
    "r_benchmark": (
        "Chalise, D., Kumar, L., Kristiansen, P. (2020). Assessment of "
        "rainfall erosivity (R-factor) during 1986–2015 across Nepal. Environ. "
        "Monit. Assess. 192:329. — daily-data national mean R ≈ 9435; the "
        "annual-precip regression under-predicts monsoon Nepal ~5–10×."
    ),
    "k_williams": (
        "Sharpley, A.N. & Williams, J.R. (1990). EPIC — Erosion/Productivity "
        "Impact Calculator: 1. Model Documentation. USDA Tech. Bull. 1768."
    ),
    "ls": (
        "McCool, D.K., Brown, L.C., Foster, G.R., Mutchler, C.K., Meyer, L.D. "
        "(1987). Revised slope steepness factor for USLE. Trans. ASAE "
        "30:1387–1396. L = (λ/22.13)^m."
    ),
    "ls_desmet_govers": (
        "Desmet, P.J.J. & Govers, G. (1996). A GIS procedure for automatically "
        "calculating the USLE LS factor on topographically complex landscape "
        "units. J. Soil Water Conserv. 51:427–433. (P6)"
    ),
    "c": (
        "Panagos, P. et al. (2015). Estimating the soil erosion "
        "cover-management factor at the European scale. Land Use Policy "
        "48:38–50. — C-by-land-cover values as applied to Nepal by Koirala et "
        "al. (2019), Table 2."
    ),
    "p": (
        "Shin, G.J. (1999). The Analysis of Soil Erosion Analysis in Watershed "
        "Using GIS. PhD thesis, Kangwon National University. — slope-based "
        "contouring/terracing P table (Koirala et al. 2019, Table 3)."
    ),
    "nepal_rusle": (
        "Koirala, P., Thapa, S., Neupane, B., Pradhan, S.M. (2019). Estimation "
        "of Soil Erosion in Nepal Using a RUSLE Modeling and Geospatial Tool. "
        "Geosciences 9(4):147. — the Nepal-calibrated parameter set this "
        "module seeds from."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Seed
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_PARAMS = SoilErosionParams()
DEFAULT_PARAMS._provenance = {k: "default" for k in SoilErosionParams.model_fields}


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
    """The org-wide ``soil_erosion_profiles`` layer (P7): the forest's dominant
    ``admin.physiography`` zone → the ``params`` patch of the profile whose
    ``physiography_hint`` matches. ``None`` when the table is absent (migration
    077 not applied), no zone intersects, or no profile matches."""
    from sqlalchemy import text

    # A missing admin.physiography / soil_erosion_profiles table (test DB,
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
                    "SELECT params FROM soil_erosion_profiles "
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


def _provenance_of(
    merged: dict[str, Any], layers: list[tuple[str, dict[str, Any]]]
) -> dict[str, str]:
    """Per-top-level-field: the name of the last layer that set it."""
    prov = {k: "default" for k in SoilErosionParams.model_fields}
    for name, layer in layers:
        for key in layer or {}:
            if key in prov:
                prov[key] = name
    return prov


def resolve_params(db: Session, calculation_id: UUID) -> SoilErosionParams:
    """Merge ``DEFAULT_PARAMS ▸ global profile ▸ per-forest override``, validate,
    and stamp ``_provenance``.

    A validation failure in a layer is not fatal: it is logged (rate-limited)
    and that layer is dropped, so a bad override can never break the soil-loss
    map — the API is where an override is *rejected* (422) before it is stored.
    """
    from app.core.dropped import report_dropped

    base = DEFAULT_PARAMS.model_dump()
    profile = _load_global_profile(db, calculation_id)
    forest = _load_forest_override(db, calculation_id)

    applied: list[tuple[str, dict[str, Any]]] = []
    merged = base
    for name, layer in (("profile", profile), ("forest", forest)):
        if not layer:
            continue
        candidate = _deep_merge(merged, layer)
        try:
            SoilErosionParams(**candidate)
        except Exception:  # noqa: BLE001 -- a bad layer is dropped, not fatal
            report_dropped(
                logger,
                f"soil_erosion {name} params override (calc {calculation_id})",
                "layer ignored; falling back to the layer below",
            )
            continue
        merged = candidate
        applied.append((name, layer))

    params = SoilErosionParams(**merged)
    params._provenance = _provenance_of(merged, applied)
    return params


def params_hash(params: SoilErosionParams) -> str:
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
    "MFICoeffs",
    "AnnualRegCoeffs",
    "SoilErosionParams",
    "DEFAULT_PARAMS",
    "resolve_params",
    "params_hash",
    "SEVERITY_LABELS_NE",
    "SEVERITY_LABELS_EN",
    "SEVERITY_PALETTE_KEY",
    "NO_DATA_LABEL_NE",
    "NO_DATA_LABEL_EN",
    "R_UNITS",
    "K_UNITS",
    "A_UNITS",
    "CITATIONS",
]
