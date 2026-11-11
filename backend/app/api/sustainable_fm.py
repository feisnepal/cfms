"""Sustainable Forest Management (दिगो वन व्यवस्थापन) — analysis + params API (P3).

``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §5 P3.

    GET    /calculations/{id}/sustainable-fm/summary            forest-level roll-up
    GET    /calculations/{id}/sustainable-fm/blocks             per-block classification
    PATCH  /calculations/{id}/sustainable-fm/blocks/{name}      override type / crown / origin
    GET    /calculations/{id}/sustainable-fm/narration          NE / EN narration blocks
    GET/PATCH/DELETE /calculations/{id}/sustainable-fm-params   per-forest SfmParams override

Read endpoints build ``result_data['sfm']`` on first access (``get_sfm``) and
serve the cache after. All routes are owner-or-SUPER_ADMIN. Office analysis
config, not field capture — the module is ``EXEMPT`` in
``check_idempotency_coverage.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.services.sustainable_fm.sfm_config import (
    RESULT_DATA_KEY,
    SfmParams,
    SfmParamsPatch,
    _deep_merge,
    resolve_params,
)
from app.services.sustainable_fm.sfm_narration import all_blocks as narration_all
from app.services.sustainable_fm.sfm_service import (
    SFM_RESULT_KEY,
    SFM_USER_KEY,
    build_sfm,
    compare_variants,
    get_sfm,
)
from app.utils.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


def _owner_or_super(db: Session, calculation_id: str, user: User) -> Calculation:
    """Owner-or-SUPER_ADMIN gate (mirrors ``soil_erosion_params``)."""
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
    if calc.user_id != user.id and user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    return calc


def _set_block_working_circle(
    db: Session, calc: Calculation, block_name: str, target_wc: str
) -> bool:
    """Flip ``forest_blocks.working_circle`` for the named management unit.
    Returns True when a row changed (so the caller bumps the geometry clock)."""
    res = db.execute(
        text(
            "UPDATE forest_blocks SET working_circle = :wc "
            "WHERE calculation_id = :cid "
            "AND COALESCE(block_name, name) = :bn "
            "AND working_circle IS DISTINCT FROM :wc"
        ),
        {"wc": target_wc, "cid": str(calc.id), "bn": block_name},
    )
    return bool(res.rowcount)


def _audit_wc(
    db: Session, calc: Calculation, block_name: str, target_wc: str, meta: dict
) -> None:
    """Best-effort audit row for a working-circle accept/revert (P9). The insert
    runs in a SAVEPOINT so a missing / broken ``geometry_audits`` table rolls
    back just this, not the caller's transaction."""
    try:
        from app.services.audit_service import log_geometry_audit

        with db.begin_nested():
            log_geometry_audit(
                db,
                str(calc.id),
                "blocks",
                "UPDATE",
                block_name,
                None,
                None,
                metadata={"change": "working_circle", "to": target_wc, **meta},
            )
    except Exception:  # noqa: BLE001 -- an audit failure must not fail the accept
        logger.warning(
            "SFM working-circle audit failed for %s/%s",
            calc.id,
            block_name,
            exc_info=True,
        )


def _drop_sfm_map_cache(calc_id) -> None:
    """Forget the rendered maps of this forest. A cached map is keyed by the map's definition, not by the SFM data,
    so after a type / crown / origin override it would keep showing the old colours and the old "Type-N" labels."""
    try:
        from app.services.management_plan_docx.plan_map_service import clear_map_cache

        clear_map_cache(calculation_id=UUID(str(calc_id)))
    except Exception:  # noqa: BLE001 -- best-effort cache bust
        logger.warning("Map cache drop failed for %s", calc_id, exc_info=True)


def _drop_op_data_cache(db: Session, calc_id) -> None:
    try:
        from app.models.op_data_cache import OpDataCache

        db.query(OpDataCache).filter(
            OpDataCache.calculation_id == UUID(str(calc_id))
        ).delete()
        db.commit()
    except Exception:  # noqa: BLE001 -- best-effort cache bust
        logger.warning("OpDataCache drop failed for %s", calc_id, exc_info=True)
        db.rollback()


# ─────────────────────────────────────────────────────────────────────────────
# Analysis
# ─────────────────────────────────────────────────────────────────────────────
_VARIANT_ALIASES = {"baseline": "baseline", "user": "user", "sfm": "baseline", "sfm_user": "user"}


def _resolve_variant(variant: str) -> str:
    """Validate the ``?variant=`` param — defaults handled by the endpoint
    signature, unknown values → 422 (SV-1.5)."""
    v = _VARIANT_ALIASES.get((variant or "baseline").strip().lower())
    if v is None:
        raise HTTPException(
            status_code=422, detail="variant must be 'baseline' or 'user'"
        )
    return v


def _sfm_for(calc, db, variant: str) -> dict:
    return build_sfm(calc, db, variant=_resolve_variant(variant))


@router.get("/sustainable-fm/forest-types")
def list_forest_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The 14 अनुसूची-१ forest types, readable by any signed-in user.

    This is reference data the SFM tab shows inline (tooltip on every "Type N" and the reference
    panel), so a user can decide without leaving the page. Editing stays super-admin only
    (`/admin/sfm-prescriptions`). Active types only, in type order."""
    from app.api.sfm_prescriptions import _dump
    from app.models.sfm_prescription import SfmForestTypePrescription

    rows = (
        db.query(SfmForestTypePrescription)
        .filter(SfmForestTypePrescription.is_active.is_(True))
        .order_by(SfmForestTypePrescription.type_no)
        .all()
    )
    return [_dump(r) for r in rows]


@router.get("/calculations/{calculation_id}/sustainable-fm/block-types")
def get_block_types(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """``{block_name: {type_no, proposed_type_no, overridden, orientation, confidence, needs_review, reasons_*}}``
    for the workspace map's labels and hover cards.

    Reads the CACHED classification only and never builds it: opening the map must not trigger a heavy SFM build
    for a forest nobody has classified yet (it then simply returns ``{}``). `type_no` is the effective type, so a
    user's override is what the map shows."""
    calc = _owner_or_super(db, calculation_id, current_user)
    sfm = ((calc.result_data or {}).get(SFM_RESULT_KEY) or {})
    out: dict[str, dict] = {}
    zones = sfm.get("zone_by_block") or {}
    for b in sfm.get("blocks") or []:
        name = (b.get("block_name") or "").strip()
        if not name:
            continue
        eff = b.get("effective_type_no")  # None: non-forest, or no sample plots
        out[name] = {
            "area_ha": b.get("area_ha"),
            "gs_ge40_m3_per_ha": (b.get("inputs") or {}).get("gs_ge40_m3_per_ha"),
            "slope_band": (zones.get(name) or {}).get("slope_band"),
            "state": b.get("state") or "classified",
            "land_class": b.get("land_class") or "forest",
            "plot_count": b.get("plot_count") or 0,
            "type_no": eff,
            "proposed_type_no": b.get("proposed_type_no"),
            "overridden": b.get("override_type_no") is not None,
            "orientation": b.get("orientation"),
            "confidence": b.get("confidence"),
            "needs_review": bool(b.get("needs_review")),
            "reasons_ne": b.get("reasons_ne"),
            "reasons_en": b.get("reasons_en"),
        }
    # SFM classifies the leaf stands; a divided parent shows the summary of its sub-units (largest area wins).
    from ..services import unit_rollup

    return unit_rollup.rollup_sfm_types(unit_rollup.unit_tree(db, calc.id), out)


@router.get("/calculations/{calculation_id}/sustainable-fm/summary")
def get_summary(
    calculation_id: str,
    variant: str = "baseline",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _owner_or_super(db, calculation_id, current_user)
    sfm = _sfm_for(calc, db, variant)
    return {
        "forest_summary": sfm.get("forest_summary", {}),
        "felling_series": sfm.get("felling_series", []),
        "source": sfm.get("source"),
        "generated_at": sfm.get("generated_at"),
    }


@router.get("/calculations/{calculation_id}/sustainable-fm/blocks")
def get_blocks(
    calculation_id: str,
    variant: str = "baseline",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _owner_or_super(db, calculation_id, current_user)
    sfm = _sfm_for(calc, db, variant)
    return {
        "blocks": sfm.get("blocks", []),
        "zone_by_block": sfm.get("zone_by_block", {}),
        "source": sfm.get("source"),
        "generated_at": sfm.get("generated_at"),
    }


@router.get("/calculations/{calculation_id}/sustainable-fm/stem-mapping-suggestion")
def get_stem_mapping_suggestion(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Where to do stem mapping under shelterwood: the units of the shelterwood series ranked by growing stock of trees of 40 cm and above,
    with trees and volume per hectare for 10-40 cm, 10 cm+ and 40 cm+. ``applies`` is false when no series is managed by shelterwood."""
    from app.services.sustainable_fm.stem_mapping_suggestion import build_suggestion

    calc = _owner_or_super(db, calculation_id, current_user)
    return build_suggestion(calc, db)


@router.get("/calculations/{calculation_id}/sustainable-fm/map-legend/{spec_key}")
def get_map_legend(
    calculation_id: str,
    spec_key: str,
    variant: str = "baseline",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The dynamic legend of one SFM map (``sfm__forest_type`` / ``sfm__orientation`` / ``sfm__gs_vs_threshold``): only the classes this
    forest has, with the units and hectares each covers, coloured exactly as the map is. Stored result only; never builds it."""
    from app.services.sustainable_fm import map_legend

    calc = _owner_or_super(db, calculation_id, current_user)
    if spec_key not in map_legend.SFM_MAP_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown SFM map: {spec_key}")
    return map_legend.build_legend(db, calc.id, spec_key, _resolve_variant(variant))


@router.get("/calculations/{calculation_id}/sustainable-fm/narration")
def get_narration(
    calculation_id: str,
    variant: str = "baseline",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _owner_or_super(db, calculation_id, current_user)
    sfm = _sfm_for(calc, db, variant)
    return sfm.get("narration") or narration_all(sfm)


@router.get("/calculations/{calculation_id}/sustainable-fm/compare")
def get_compare(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Both variants + a per-block / forest-level diff (SV-1.5)."""
    calc = _owner_or_super(db, calculation_id, current_user)
    baseline = build_sfm(calc, db)
    user = build_sfm(calc, db, variant="user")
    return compare_variants(baseline, user)


# ─────────────────────────────────────────────────────────────────────────────
# Variable reference (P8) — the ordered manifest of every {{sfm_*}} the tab
# surfaces; SSOT for the coverage gate and the /templates/sfm-variables page.
# numbers ▸ (maps inserted at index 1) ▸ tables ▸ narrative
# ─────────────────────────────────────────────────────────────────────────────
SFM_VARIABLE_GROUPS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "numbers",
        "मुख्य अङ्कहरू",
        "Headline numbers",
        (
            "sfm_dominant_type_ne",
            "sfm_dominant_type_en",
            "sfm_total_annual_harvest_m3",
            "sfm_production_area_ha",
            "sfm_protection_area_ha",
            "sfm_plan_regime_note",
            "sfm_sampling_intensity_note",
            "sfm_felling_series_note",
        ),
    ),
    (
        "tables",
        "तालिकाहरू",
        "Tables",
        (
            "sfm_block_prescription_table",
            "sfm_type_area_table",
            "sfm_yield_table",
            "sfm_working_circle_table",
            "sfm_sampling_plan_table",
        ),
    ),
    (
        "narrative",
        "व्याख्या",
        "Narrative",
        (
            "sfm_methodology",
            "sfm_findings",
            "sfm_prescription",
        ),
    ),
)

_SFM_MAP_PREFIX = "sfm__"


@router.get("/calculations/{calculation_id}/sustainable-fm/variables")
def get_variables(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every OP variable the Sustainable Forest Management tab surfaces, grouped
    and ordered as it reads on screen (numbers ▸ maps ▸ tables ▸ narrative). The
    client fetches ``variable-catalog?keys=`` for the resolved values / previews
    and the P5 map-preview endpoint for the map thumbnails."""
    calc = _owner_or_super(db, calculation_id, current_user)

    from app.services.operational_plan.thematic_map_spec import (
        BUILTIN_THEMEMAP_SPECS,
    )
    from app.services.operational_plan.variable_enrichment import SUB_GROUPS
    from app.services.operational_plan.variable_registry import get_variable

    def _vrow(key: str) -> dict[str, Any]:
        v = get_variable(key)
        return {
            "key": key,
            "label_ne": v.label_ne if v else key,
            "label_en": v.label_en if v else key,
            "var_type": v.var_type if v else "string",
            "sub_group": SUB_GROUPS.get(key, ""),
            "registered": v is not None,
        }

    groups: list[dict[str, Any]] = [
        {
            "id": gid,
            "label_ne": ne,
            "label_en": en,
            "variables": [_vrow(k) for k in keys],
        }
        for gid, ne, en, keys in SFM_VARIABLE_GROUPS
    ]

    map_rows = [
        {
            "key": spec.token,
            "label_ne": spec.label_ne,
            "label_en": spec.label_en,
        }
        for key, spec in BUILTIN_THEMEMAP_SPECS.items()
        if key.startswith(_SFM_MAP_PREFIX)
    ]
    map_rows.sort(key=lambda m: m["key"])
    groups.insert(
        1,
        {
            "id": "maps",
            "label_ne": "नक्साहरू",
            "label_en": "Maps",
            "variables": map_rows,
        },
    )
    return {"calculation_id": str(calc.id), "groups": groups}


# ─────────────────────────────────────────────────────────────────────────────
# Slope-class helper overlay + assisted protection digitizing (P11, follow-on)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/calculations/{calculation_id}/sustainable-fm/slope-class-polygons")
def slope_class_polygons(
    calculation_id: str,
    refresh: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A GeoJSON FeatureCollection of the 4 slope bands inside the forest
    (< 19° / 19–31° / 31–45° / > 45°), simplified + sliver-cleaned — a read-only
    digitizing aid, not a persisted workspace layer. Cached under
    ``result_data['sfm']['slope_class_polygons']`` (dropped with the rest of
    ``sfm`` on re-analysis)."""
    calc = _owner_or_super(db, calculation_id, current_user)

    from app.services.sustainable_fm.sfm_config import resolve_params as _rp
    from app.services.sustainable_fm.slope_vectorize import (
        slope_class_polygons as _svp,
    )

    rd = calc.result_data or {}
    cached = (
        ((rd.get("sfm") or {}).get("slope_class_polygons")) if not refresh else None
    )
    if isinstance(cached, dict) and cached.get("type") == "FeatureCollection":
        return cached

    fc = _svp(calc, db, _rp(db, calc.id))
    # stash it on the sfm block if one exists (SQLAlchemy-safe), best-effort
    try:
        if isinstance(rd.get("sfm"), dict):
            new_rd = dict(rd)
            new_sfm = dict(new_rd["sfm"])
            new_sfm["slope_class_polygons"] = fc
            new_rd["sfm"] = new_sfm
            calc.result_data = new_rd
            db.add(calc)
            db.commit()
    except Exception:  # noqa: BLE001 -- caching is best-effort
        logger.warning("slope-class-polygons cache write failed", exc_info=True)
        db.rollback()
    return fc


@router.post("/calculations/{calculation_id}/sustainable-fm/draft-protection-subarea")
def draft_protection_subarea(
    calculation_id: str,
    body: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Union of the slope bands ≥ ``min_band`` (default 3, i.e. ≥ 31°) clipped
    to the forest → an **editable draft** ``category='protected'`` polygon (NOT
    persisted). The frontend loads it into the geoman editor; the user trims it
    against the §23.2 exclusion checklist and saves through the normal sub-area
    path (which stamps ``slope_profile``)."""
    calc = _owner_or_super(db, calculation_id, current_user)
    min_band = 3
    if isinstance(body, dict) and body.get("min_band") is not None:
        v = body["min_band"]
        if not isinstance(v, int) or not 1 <= v <= 4:
            raise HTTPException(status_code=422, detail="min_band must be 1..4")
        min_band = v

    from app.services.sustainable_fm.sfm_config import resolve_params as _rp
    from app.services.sustainable_fm.slope_vectorize import (
        draft_protection_polygon,
        slope_profile,
    )

    params = _rp(db, calc.id)
    geom = draft_protection_polygon(calc, db, params, min_band)
    if geom is None:
        raise HTTPException(
            status_code=404,
            detail="No slope band ≥ the requested class inside this forest "
            "(or slope_regulation does not cover it).",
        )
    from shapely.geometry import shape

    prof = slope_profile(shape(geom).wkt, db, params)
    return {
        "min_band": min_band,
        "category": "protected",
        "polygon": geom,
        "slope_profile": prof,
        "hint_ne": (
            "यो केवल सुरुवाती मस्यौदा हो। दफा २३.२ को बहिष्करण सूची (पानीका मुहान, "
            "नदी किनारा, भू-क्षय/पहिरो वरिपरि, चुरे संवेदनशील क्षेत्र, अति भिरालो, "
            "जैविक/सांस्कृतिक महत्त्वका रुख, अनुसन्धान क्षेत्र) अनुसार हातैले सम्पादन गर्नुहोस्।"
        ),
        "hint_en": (
            "A starting draft only — hand-edit it against the §23.2 exclusion "
            "checklist (water sources, river banks, erosion/landslide surrounds, "
            "Chure sensitive areas, very steep ground, biodiversity/cultural "
            "trees, research plots) before saving."
        ),
    }


@router.post("/calculations/{calculation_id}/sustainable-fm/slope-profile")
def get_slope_profile(
    calculation_id: str,
    body: dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """``{dominant_band, area_pct_by_band}`` for a supplied GeoJSON geometry —
    the frontend calls this after a ``protected`` sub-area is saved and merges
    the result into ``result_data.sub_areas[i].slope_profile``."""
    calc = _owner_or_super(db, calculation_id, current_user)
    geom = (body or {}).get("geometry") or body
    if not isinstance(geom, dict) or not geom.get("coordinates"):
        raise HTTPException(status_code=422, detail="geometry (GeoJSON) required")

    from shapely.geometry import shape

    from app.services.sustainable_fm.sfm_config import resolve_params as _rp
    from app.services.sustainable_fm.slope_vectorize import slope_profile

    try:
        wkt = shape(geom).wkt
    except Exception:  # noqa: BLE001 -- bad geometry
        raise HTTPException(status_code=422, detail="invalid GeoJSON geometry")
    return slope_profile(wkt, db, _rp(db, calc.id))


_ALLOWED_BLOCK_KEYS = {
    "override_type_no",
    "crown_density_pct",
    "origin",
    "accept_working_circle",
    "land_class",
}


@router.patch("/calculations/{calculation_id}/sustainable-fm/blocks/{block_name}")
def patch_block(
    calculation_id: str,
    block_name: str,
    body: dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _owner_or_super(db, calculation_id, current_user)
    if not isinstance(body, dict) or not body:
        raise HTTPException(status_code=422, detail="Body must be a non-empty object")
    unknown = set(body) - _ALLOWED_BLOCK_KEYS
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown keys: {sorted(unknown)}")
    if "override_type_no" in body and body["override_type_no"] is not None:
        v = body["override_type_no"]
        if not isinstance(v, int) or not 1 <= v <= 14:
            raise HTTPException(
                status_code=422, detail="override_type_no must be 1..14"
            )
    if "crown_density_pct" in body and body["crown_density_pct"] is not None:
        v = body["crown_density_pct"]
        if not isinstance(v, int) or not 0 <= v <= 100:
            raise HTTPException(
                status_code=422, detail="crown_density_pct must be 0..100"
            )
    if body.get("origin") not in (None, "natural", "plantation"):
        raise HTTPException(status_code=422, detail="origin must be natural|plantation")
    from app.services.sustainable_fm.block_status import LAND_CLASSES

    if body.get("land_class") is not None and body["land_class"] not in LAND_CLASSES:
        raise HTTPException(status_code=422, detail=f"land_class must be one of {list(LAND_CLASSES)}")

    sfm = get_sfm(calc, db)
    blocks = sfm.get("blocks", [])
    target = next((b for b in blocks if b.get("block_name") == block_name), None)
    if target is None:
        raise HTTPException(
            status_code=404, detail="block not found in SFM classification"
        )

    # write the override onto the block, SQLAlchemy-safe
    new_block = dict(target)
    if "override_type_no" in body:
        new_block["override_type_no"] = body["override_type_no"]
    if "crown_density_pct" in body:
        new_block["override_crown_density_pct"] = body["crown_density_pct"]
    if "origin" in body:
        new_block["override_origin"] = body["origin"]
    if "land_class" in body:
        # null = back to ESA's suggestion; the next rebuild reads this and re-derives state, type and series
        new_block["override_land_class"] = body["land_class"]
    if "accept_working_circle" in body:
        accept = bool(body["accept_working_circle"])
        new_block["wc_accept"] = accept
        # P9 — actually move the management block into / out of the protection
        # working circle. Reversible: a later `accept_working_circle: false`
        # (or any override that re-yields) sets it back to production.
        target_wc = "protection" if accept else "production"
        if _set_block_working_circle(db, calc, block_name, target_wc):
            from app.services.geometry_edit_service import bump_geometry_version

            bump_geometry_version(calc)
            prop = new_block.get("working_circle_proposal") or {}
            new_block["wc_justification_ne"] = prop.get("justification_ne")
            new_block["wc_justification_en"] = prop.get("justification_en")
            _audit_wc(
                db,
                calc,
                block_name,
                target_wc,
                {
                    "justification_ne": prop.get("justification_ne"),
                    "justification_en": prop.get("justification_en"),
                    "user_id": str(current_user.id),
                },
            )

    new_sfm = dict(sfm)
    new_sfm["blocks"] = [
        new_block if b.get("block_name") == block_name else b for b in blocks
    ]
    new_rd = dict(calc.result_data or {})
    new_rd[SFM_RESULT_KEY] = new_sfm
    # SV-1.4 — if a user variant was already built, it would now be stale: it
    # carries its overrides from the baseline block (single-sourced there), so
    # drop it and let the next `variant=user` build recompute from this patch.
    new_rd.pop(SFM_USER_KEY, None)
    calc.result_data = new_rd
    db.add(calc)
    db.commit()

    rebuilt = build_sfm(calc, db, force=True)
    _drop_op_data_cache(db, calc.id)
    _drop_sfm_map_cache(calc.id)
    out = next(
        (b for b in rebuilt["blocks"] if b.get("block_name") == block_name), None
    )
    series = next(
        (
            s
            for s in rebuilt["felling_series"]
            if out and s["type_no"] == out.get("effective_type_no")
        ),
        None,
    )
    return {
        "block": out,
        "felling_series": series,
        "forest_summary": rebuilt["forest_summary"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Per-forest params
# ─────────────────────────────────────────────────────────────────────────────
def _params_payload(db: Session, calc_id: UUID) -> dict[str, Any]:
    params = resolve_params(db, calc_id)
    return {
        "params": params.model_dump(),
        "provenance": dict(params._provenance),
        "customised": params.has_override,
    }


@router.get("/calculations/{calculation_id}/sustainable-fm-params")
def get_params(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _owner_or_super(db, calculation_id, current_user)
    return _params_payload(db, calc.id)


@router.patch("/calculations/{calculation_id}/sustainable-fm-params")
def patch_params(
    calculation_id: str,
    partial: dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _owner_or_super(db, calculation_id, current_user)
    if not isinstance(partial, dict) or not partial:
        raise HTTPException(status_code=422, detail="Body must be a non-empty object")
    try:
        SfmParamsPatch(**partial)  # reject unknown / out-of-range keys early
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=json.loads(e.json()))

    rd = dict(calc.result_data or {})
    current = dict(rd.get(RESULT_DATA_KEY) or {})
    new_override = _deep_merge(current, partial)
    merged_full = _deep_merge(SfmParams().model_dump(), new_override)
    try:
        SfmParams(**merged_full)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=json.loads(e.json()))

    rd[RESULT_DATA_KEY] = new_override
    rd.pop("sfm", None)  # params changed → next get_sfm rebuilds
    calc.result_data = rd
    db.add(calc)
    db.commit()
    _drop_op_data_cache(db, calc.id)
    return _params_payload(db, calc.id)


@router.delete("/calculations/{calculation_id}/sustainable-fm-params")
def delete_params(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = _owner_or_super(db, calculation_id, current_user)
    rd = dict(calc.result_data or {})
    if RESULT_DATA_KEY in rd or "sfm" in rd:
        rd.pop(RESULT_DATA_KEY, None)
        rd.pop("sfm", None)
        calc.result_data = rd
        db.add(calc)
        db.commit()
        _drop_op_data_cache(db, calc.id)
    return _params_payload(db, calc.id)
