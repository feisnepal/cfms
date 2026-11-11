"""Sustainable Forest Management — code-owned defaults + the parameter schema.

See ``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §3.1 and P0.

This module owns **only declaration**: the :class:`SfmParams` schema, the seed
:data:`DEFAULT_PARAMS`, the three-layer :func:`resolve_params` merge, and the
:func:`params_hash` cache key. The classification / yield maths live in the
sibling modules (``zone_classifier``, ``species_assemblage``,
``forest_type_classifier``, ``yield_regulation``) and read a *resolved*
``SfmParams`` — no rule touches a constant here directly.

**No guideline number lives here.** Felling percentages, cycles, silvicultural
systems and species groups are rows in ``sfm_forest_type_prescriptions``
(migration 082). ``SfmParams`` holds only thresholds and tuning knobs.

Parameter model (last layer wins)::

    DEFAULT_PARAMS                       code-owned seed (always complete)
      ▸ global profile                   sfm_profiles row (physiography-matched)
      ▸ per-forest override              calculation.result_data['sfm_params']

Mirrors ``operational_plan/soil_erosion_config.py`` (RUSLE P0) and
``hazard_vuln_config.py`` — same 3-layer shape, same SAVEPOINT-guarded profile
lookup, same ``params_hash`` recipe.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Bump when a DEFAULT_PARAMS value or the SfmParams shape changes in a way that
# alters output for an unchanged override. Salts params_hash → the
# result_data['sfm'] cache key, so a bump re-builds every forest's SFM block.
# 1→2 (2026-09-14): protection_slope_band's >45° Conservation rule extended
# from types 8/9/10/13 to all 14 types + new conservation_slope_band (31-45°,
# सि.नं. 12 only) — see orientation.py.
CONFIG_VERSION = 2

# result_data key holding the per-forest partial override (a subset of the
# SfmParams fields). Written by PATCH /calculations/{id}/sustainable-fm-params.
RESULT_DATA_KEY = "sfm_params"

# admin.ward.district spellings for the Inner-Terai gate (D1). Inner Terai is a
# label flag only — it never changes a prescription — so this list is advisory.
INNER_TERAI_DISTRICTS: list[str] = [
    "Udayapur",
    "Sindhuli",
    "Makawanpur",
    "Chitawan",
    "Nawalparasi_E",
    "Dang",
    "Surkhet",
]


# ─────────────────────────────────────────────────────────────────────────────
# Editable schema
# ─────────────────────────────────────────────────────────────────────────────
class SfmParams(BaseModel):
    """Every SFM tuning input as a parameter with a default. Frozen: a caller
    holds one resolved instance for the length of a build. ``extra='forbid'`` so
    an unknown key in a per-forest override is rejected, not silently kept.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # ── regeneration adequacy — picks branch (क) vs (ख) ─────────────────
    seedling_threshold: int = Field(5000, ge=0, le=100_000)  # विरुवा / ha
    sapling_threshold: int = Field(2000, ge=0, le=100_000)  # लाथ्रा / ha

    # ── crown density — the सि.नं. 6 (degraded) trigger is < 20 % ───────
    crown_density_default: int = Field(50, ge=0, le=100)
    # P10 — where a block has no measured `avg_crown_density_pct`, estimate it:
    #   "none"   → use crown_density_default (P1 behaviour, the default)
    #   "canopy" → % of the block's canopy_height5m.tif pixels ≥ 2 m
    #   "esa"    → tree-cover fraction from rasters.esa_world_cover (value 10)
    crown_density_estimate_source: Literal["none", "canopy", "esa"] = "none"

    # ── harvestable growing stock — advance growth is < this DBH ───────
    harvestable_dbh_min_cm: float = Field(40.0, gt=0.0, le=200.0)

    # ── sampling intensity floors (§16) — advisory ────────────────────
    sampling_intensity_pct: dict[str, float] = Field(
        default_factory=lambda: {
            "production": 2.0,
            "conservation": 1.0,
            "protection": 0.5,
        }
    )

    # ── riverine (सि.नं. 5) buffer around river84 ────────────────────
    riparian_buffer_m: float = Field(50.0, ge=0.0, le=1000.0)

    # ── slope banding — the guideline's own §15.2 zonation ───────────
    slope_regulation_table: str = "rasters.slope_regulation"
    # >45° → Conservation orientation + salvage-only, for EVERY forest type
    # (owner decision, 2026-09-14 — extends अनुसूची-१'s own named types
    # 8/9/10/13 into a general policy; never downgrades a type already
    # Protection-oriented). See orientation.py.
    protection_slope_band: int = Field(4, ge=1, le=4)
    # 31-45° resolves the orientation only for a type whose own अनुसूची-१
    # objective is self-contradictory in the source scan (सि.नं. 12 today —
    # AMBIGUOUS_ORIENTATION_TYPES in forest_type_classifier.py); an
    # unambiguous type's base orientation ignores this threshold.
    conservation_slope_band: int = Field(3, ge=1, le=4)

    # ── Inner Terai gate (D1) — label flag only ─────────────────────
    inner_terai_districts: list[str] = Field(
        default_factory=lambda: list(INNER_TERAI_DISTRICTS)
    )

    # ── mother-tree retention (shelterwood) ────────────────────────
    mother_tree_target_min: int = Field(15, ge=0, le=500)
    mother_tree_target_max: int = Field(25, ge=0, le=500)
    mean_mother_tree_vol_m3: float = Field(1.2, gt=0.0, le=50.0)

    # ── P11: slope-class vectorization sliver floor ───────────────
    slope_vector_sliver_m2: float = Field(1000.0, gt=0.0, le=1_000_000.0)

    _provenance: dict[str, str] = PrivateAttr(default_factory=dict)

    @property
    def has_override(self) -> bool:
        """True when any field came from a profile or a per-forest override."""
        return any(src != "default" for src in self._provenance.values())

    def intensity_for(self, stratum: str) -> float:
        """Sampling intensity % for ``production`` | ``conservation`` |
        ``protection``; falls back to the code default for an unknown key."""
        base = {"production": 2.0, "conservation": 1.0, "protection": 0.5}
        return float(self.sampling_intensity_pct.get(stratum, base.get(stratum, 1.0)))


class SfmParamsPatch(BaseModel):
    """Sparse override — every field optional. The body of
    ``PATCH /calculations/{id}/sustainable-fm-params`` and the shape of a
    ``sfm_profiles.params`` blob. ``extra='forbid'`` so a typo'd key is a 422,
    not a silent no-op."""

    model_config = ConfigDict(extra="forbid")

    seedling_threshold: Optional[int] = Field(None, ge=0, le=100_000)
    sapling_threshold: Optional[int] = Field(None, ge=0, le=100_000)
    crown_density_default: Optional[int] = Field(None, ge=0, le=100)
    crown_density_estimate_source: Optional[Literal["none", "canopy", "esa"]] = None
    harvestable_dbh_min_cm: Optional[float] = Field(None, gt=0.0, le=200.0)
    sampling_intensity_pct: Optional[dict[str, float]] = None
    riparian_buffer_m: Optional[float] = Field(None, ge=0.0, le=1000.0)
    slope_regulation_table: Optional[str] = None
    protection_slope_band: Optional[int] = Field(None, ge=1, le=4)
    conservation_slope_band: Optional[int] = Field(None, ge=1, le=4)
    inner_terai_districts: Optional[list[str]] = None
    mother_tree_target_min: Optional[int] = Field(None, ge=0, le=500)
    mother_tree_target_max: Optional[int] = Field(None, ge=0, le=500)
    mean_mother_tree_vol_m3: Optional[float] = Field(None, gt=0.0, le=50.0)
    slope_vector_sliver_m2: Optional[float] = Field(None, gt=0.0, le=1_000_000.0)


# ─────────────────────────────────────────────────────────────────────────────
# Seed
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_PARAMS = SfmParams()
DEFAULT_PARAMS._provenance = {k: "default" for k in SfmParams.model_fields}


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
    """The org-wide ``sfm_profiles`` layer: the forest's dominant
    ``admin.physiography`` zone → the ``params`` patch of the profile whose
    ``physiography_hint`` matches. ``None`` when the table is absent (migration
    083 not applied), no zone intersects, or no profile matches.

    A missing ``admin.physiography`` / ``sfm_profiles`` table (test DB,
    pre-migration) raises and would poison the request transaction — the whole
    lookup runs inside a SAVEPOINT so a failure rolls back just this.
    """
    from sqlalchemy import text

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
                    "SELECT params FROM sfm_profiles "
                    "WHERE is_active AND physiography_hint = :z "
                    "ORDER BY sort_order LIMIT 1"
                ),
                {"z": zone},
            ).first()
        params = (row[0] if row else None) or None
        return params if isinstance(params, dict) and params else None
    except (
        Exception
    ):  # noqa: BLE001 -- sfm_profiles / admin.physiography optional → skip the layer
        logger.debug(
            "sfm_profiles layer skipped for calc %s", calculation_id, exc_info=True
        )
        return None


def _load_forest_override(
    db: Session, calculation_id: UUID
) -> Optional[dict[str, Any]]:
    """The per-forest partial override from ``calculation.result_data``."""
    from app.models.calculation import Calculation

    row = (
        db.query(Calculation.result_data)
        .filter(Calculation.id == calculation_id)
        .first()
    )
    rd = (row[0] if row else None) or {}
    ov = rd.get(RESULT_DATA_KEY)
    return ov if isinstance(ov, dict) and ov else None


def _provenance_of(applied: list[tuple[str, dict[str, Any]]]) -> dict[str, str]:
    """Per-field: the name of the last layer that set it."""
    prov = {k: "default" for k in SfmParams.model_fields}
    for name, layer in applied:
        for key in layer or {}:
            if key in prov:
                prov[key] = name
    return prov


def resolve_params(db: Session, calculation_id: UUID) -> SfmParams:
    """Merge ``DEFAULT_PARAMS ▸ global profile ▸ per-forest override``, validate,
    and stamp ``_provenance``.

    A validation failure in a layer is not fatal: it is reported (rate-limited)
    and that layer is dropped, so a bad override can never break the SFM build —
    the API is where an override is *rejected* (422) before it is stored.
    """
    from app.core.dropped import report_dropped

    base = DEFAULT_PARAMS.model_dump()
    layers = [
        ("profile", _load_global_profile(db, calculation_id)),
        ("forest", _load_forest_override(db, calculation_id)),
    ]

    merged = base
    applied: list[tuple[str, dict[str, Any]]] = []
    for name, layer in layers:
        if not layer:
            continue
        candidate = _deep_merge(merged, layer)
        try:
            SfmParams(**candidate)
        except Exception:  # noqa: BLE001 -- a bad layer is dropped, not fatal
            report_dropped(
                logger,
                f"sfm {name} params override (calc {calculation_id})",
                "layer ignored; falling back to the layer below",
            )
            continue
        merged = candidate
        applied.append((name, layer))

    params = SfmParams(**merged)
    params._provenance = _provenance_of(applied)
    return params


def params_hash(params: SfmParams) -> str:
    """Short stable digest of ``CONFIG_VERSION`` + the resolved params, for the
    ``result_data['sfm']`` cache key. ``_provenance`` is a PrivateAttr and is not
    in ``model_dump`` — two forests with the same numbers share a cache entry."""
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
    "INNER_TERAI_DISTRICTS",
    "SfmParams",
    "SfmParamsPatch",
    "DEFAULT_PARAMS",
    "resolve_params",
    "params_hash",
]
