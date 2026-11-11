"""Hazard & Erosion context — a thin read aggregator for the dedicated
calculation-shell page (HAZARD_EROSION_CONTEXT_PLAN.md, P0).

Everything below is assembled from surfaces that already exist — the RUSLE
(`get_soil_erosion_data`) and landslide-hazard / household-vulnerability
(`get_hazard_vuln_data`) collectors, `prereq_check`, and the thematic-map
registry. No compute here.

    GET  /calculations/{id}/hazard-erosion/summary               header + prereqs + key numbers + map list
    GET  /calculations/{id}/hazard-erosion/tables                the Devanagari-keyed data tables (PII-safe)
    GET  /calculations/{id}/hazard-erosion/narration             methodology / findings / prescription (NE+EN)
    POST /calculations/{id}/hazard-erosion/recompute             drop the GeoTIFF + map + op-data caches
    POST /calculations/{id}/hazard-erosion/insert-op-subsections append seed ३.८/३.९ to the calc's OP tree
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import get_db
from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.services.operational_plan import prereq_check, plan_live
from app.utils.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Hazard & Erosion"])

# the data layers the page depends on, in display order
_PREREQ_TAGS = (
    "raster_zonal",
    "soil_data",
    "geology",
    "household_data",
    "user_group_extent",
)

# thematic-spec key prefixes that belong to this page
_MAP_PREFIXES = ("soil__", "hazard__", "hh__")

# HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P3/P6 — every non-map variable the
# page surfaces, grouped and ordered as it reads on screen. The `variables`
# endpoint serves this to the in-context reference; the P6 coverage test
# asserts each key is registered. Map keys are derived from the thematic
# registry at request time (same source as `summary`).
HAZARD_VARIABLE_GROUPS = (
    (
        "numbers",
        "मुख्य अङ्कहरू",
        "Headline numbers",
        (
            "hazard_erosion_mean_t_ha",
            "hazard_erosion_total_t_yr",
            "hazard_erosion_area_ha",
            "hazard_erosion_tolerable_limit",
            "hazard_erosion_pct_above_tolerable",
            "hazard_erosion_dominant_factor",
            "hazard_erosion_customised",
            "hazard_erosion_sdr_enabled",
            "hazard_erosion_sdr_mean",
            "hazard_erosion_basin_sdr",
            "hazard_erosion_delivered_t_yr",
            "hazard_erosion_ug_mean_t_ha",
            "hazard_erosion_ug_minus_cf_mean_t_ha",
            "hazard_landslide_prone_area_ha",
            "hazard_landslide_prone_area_pct",
            "hazard_landslide_high_units",
            "hazard_landslide_class_method",
            "hazard_landslide_ahp_cr",
            "hazard_landslide_customised",
            "hazard_slope_fs_enabled",
            "hazard_slope_unstable_area_ha",
            "hazard_slope_unstable_pct",
            "hazard_slope_marginal_pct",
            "hazard_slope_marginal_area_ha",
            "hazard_slope_depth_mean_m",
            "hazard_slope_scenario_note",
            "hazard_household_count",
            "hazard_household_priority_count",
            "hazard_household_mean_score",
            "hazard_household_max_score",
            "hazard_household_layer_informative",
            "hazard_household_coord_source",
        ),
    ),
    (
        "tables",
        "तालिकाहरू",
        "Tables",
        (
            "hazard_erosion_by_unit_table",
            "hazard_erosion_aoi_comparison_table",
            "hazard_landslide_area_by_class_table",
            "hazard_landslide_by_unit_table",
            "hazard_slope_by_unit_table",
            "hazard_landslide_aoi_comparison_table",
            "hazard_household_priority_table",
            "hazard_household_settlement_rollup_table",
            "hazard_household_driver_counts_table",
        ),
    ),
    (
        "charts",
        "चार्टहरू",
        "Charts",
        (
            "chart:hazard_landslide_area_by_class",
            "chart:hazard_slope_class_split",
            "chart:hazard_household_driver_split",
            "chart:hazard_erosion_aoi_comparison",
        ),
    ),
    (
        "narration",
        "विवरण",
        "Narrative",
        (
            "hazard_erosion_full_narration",
            "hazard_erosion_methodology_narration",
            "hazard_erosion_findings_narration",
            "hazard_erosion_prescription_narration",
            "hazard_erosion_assumptions",
            "hazard_methodology_narration",
            "hazard_findings_narration",
            "hazard_prescription_narration",
            "hazard_assumptions",
        ),
    ),
)


def _require_calc_access(
    db: Session, calculation_id: str, current_user: User
) -> Calculation:
    """Owner-or-SUPER_ADMIN gate (mirrors soil_erosion_params)."""
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


def _physiography_zone(db: Session, calc_id: UUID) -> str | None:
    """The forest's dominant ``admin.physiography`` zone (largest boundary∩zone
    area). ``None`` when the table is absent or nothing intersects."""
    try:
        with db.begin_nested():
            return db.execute(
                text(
                    'SELECT p."physiography Zone" '
                    "FROM admin.physiography p, public.calculations c "
                    "WHERE c.id = :cid AND ST_Intersects(p.geom, c.boundary_geom) "
                    "ORDER BY ST_Area(ST_Intersection(p.geom, c.boundary_geom)) DESC "
                    "LIMIT 1"
                ),
                {"cid": str(calc_id)},
            ).scalar()
    except Exception:  # noqa: BLE001 -- table missing / DB hiccup
        return None


def _prereq(db: Session, calc_id: UUID, tag: str) -> dict[str, Any]:
    r = prereq_check.check(db, calc_id, [tag])
    return {
        "tag": tag,
        "status": r.status,  # available 🟢 | partial 🟡 | unavailable 🔴
        "met": r.met,
        "reason_ne": r.reason_ne,
        "reason_en": r.reason_en,
        "hint_ne": r.hint_ne,
        "hint_en": r.hint_en,
    }


def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


@router.get("/calculations/{calculation_id}/hazard-erosion/summary")
def hazard_erosion_summary(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Header (zone + prereq pills), the key soil / hazard numbers, and which of
    the ~23 maps will actually render for this forest. Never raises on a data
    gap — every sub-block degrades to ``available: False``."""
    calc = _require_calc_access(db, calculation_id, current_user)
    calc_uuid = calc.id

    from app.services.operational_plan.data_collector import (
        get_hazard_vuln_data,
        get_soil_erosion_data,
    )
    from app.services.operational_plan.thematic_map_spec import (
        BUILTIN_THEMEMAP_SPECS,
    )

    prereqs = [_prereq(db, calc_uuid, t) for t in _PREREQ_TAGS]
    by_tag = {p["tag"]: p for p in prereqs}
    has_ug = bool(by_tag["user_group_extent"]["met"])

    try:
        se = get_soil_erosion_data(db, str(calc_uuid))
    except Exception:  # noqa: BLE001
        logger.warning("hazard-erosion: soil block failed", exc_info=True)
        se = {"soil_loss_available": False}
    try:
        hv = get_hazard_vuln_data(db, str(calc_uuid))
    except Exception:  # noqa: BLE001
        logger.warning("hazard-erosion: hazard block failed", exc_info=True)
        hv = {"hazard_vuln_available": False}

    soil = {
        "available": bool(se.get("soil_loss_available")),
        "mean_t_ha": _num(se.get("soil_loss_mean_t_ha")),
        "total_t_yr": _num(se.get("soil_loss_total_t_yr")),
        "pct_above_tolerable": _num(se.get("soil_loss_pct_above_tolerable")),
        "dominant_factor": se.get("soil_loss_dominant_factor"),
        "customised": bool(se.get("soil_loss_customised")),
        "sdr_enabled": bool(se.get("soil_loss_sdr_enabled")),
    }
    hazard = {
        "available": bool(hv.get("hazard_vuln_available")),
        "lsi_prone_pct": _num(hv.get("lsi_prone_area_pct")),
        "lsi_prone_ha": _num(hv.get("lsi_prone_area_ha")),
        "lsi_high_units": hv.get("lsi_high_units_str"),
        "fs_enabled": bool(hv.get("fs_enabled")),
        "fs_unstable_pct": _num(hv.get("fs_unstable_pct")),
        "fs_marginal_pct": _num(hv.get("fs_marginal_pct")),
        "hh_count": int(hv.get("hh_count") or 0),
        "hh_priority_count": int(hv.get("hh_priority_count") or 0),
        "hh_mean_score": _num(hv.get("hh_mean_score")),
        "hazard_layer_informative": bool(hv.get("hh_hazard_layer_informative")),
        "hh_coord_source": hv.get("hh_coord_source", "survey"),
        "customised": bool(hv.get("lsi_customised")),
    }

    maps = []
    for key, spec in BUILTIN_THEMEMAP_SPECS.items():
        if not key.startswith(_MAP_PREFIXES):
            continue
        r = prereq_check.check_spec(db, calc_uuid, spec)
        maps.append(
            {
                "key": spec.token,  # e.g. "thememap:hazard__landslide_susceptibility"
                "label_ne": spec.label_ne,
                "label_en": spec.label_en,
                "section": spec.section,
                "is_factor_band": "__factor_" in key or "__lsi_factor_" in key,
                "is_user_group": key.endswith("__user_group"),
                "available": r.met,
                "reason_ne": r.reason_ne,
            }
        )
    maps.sort(key=lambda m: (m["is_factor_band"], m["key"]))

    return {
        "calculation_id": str(calc_uuid),
        "forest_name": calc.forest_name,
        "physiography_zone": _physiography_zone(db, calc_uuid),
        "has_user_group": has_ug,
        "prereqs": prereqs,
        "soil": soil,
        "hazard": hazard,
        "maps": maps,
    }


@router.get("/calculations/{calculation_id}/hazard-erosion/variables")
def hazard_erosion_variables(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every OP variable the Hazard & Erosion page surfaces, grouped and ordered
    as it reads on screen (numbers ▸ maps ▸ tables ▸ charts ▸ narrative). Feeds
    the in-context variable reference — the client fetches
    ``variable-catalog?keys=`` for the resolved values / previews.
    HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P3."""
    calc = _require_calc_access(db, calculation_id, current_user)

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

    groups = [
        {
            "id": gid,
            "label_ne": ne,
            "label_en": en,
            "variables": [_vrow(k) for k in keys],
        }
        for gid, ne, en, keys in HAZARD_VARIABLE_GROUPS
    ]

    # maps — same derivation as `summary`
    map_rows = []
    for key, spec in BUILTIN_THEMEMAP_SPECS.items():
        if not key.startswith(_MAP_PREFIXES):
            continue
        map_rows.append(
            {
                "key": spec.token,
                "label_ne": spec.label_ne,
                "label_en": spec.label_en,
                "is_factor_band": "__factor_" in key or "__lsi_factor_" in key,
                "is_user_group": key.endswith("__user_group"),
            }
        )
    map_rows.sort(key=lambda m: (m["is_factor_band"], m["key"]))
    groups.insert(
        1,
        {"id": "maps", "label_ne": "नक्साहरू", "label_en": "Maps", "variables": map_rows},
    )

    return {"calculation_id": str(calc.id), "groups": groups}


# Devanagari-keyed list-of-dict tables surfaced by the context page. Every one
# is already PII-trimmed by the collectors (household rows carry house_no + tole
# + score only — never surname, caste or coordinates).
_TABLE_KEYS = (
    ("soil_loss_by_unit", "soil"),
    ("soil_loss_aoi_comparison", "soil"),
    ("lsi_area_by_class", "hazard"),
    ("lsi_by_unit", "hazard"),
    ("fs_by_unit", "hazard"),
    ("hazard_aoi_comparison", "hazard"),
    ("hh_priority_table", "hazard"),
    ("hh_settlement_rollup_table", "hazard"),
    ("hh_driver_counts", "hazard"),
)

# key names that must never appear in a table payload (defence-in-depth — the
# collectors already strip these, the endpoint test re-asserts it)
_FORBIDDEN_KEY_SUBSTR = (
    "surname",
    "caste",
    "latitude",
    "longitude",
    "household_head",
    "_lat",
    "_lon",
)


@router.get("/calculations/{calculation_id}/hazard-erosion/tables")
def hazard_erosion_tables(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The tables behind the context page — RUSLE per-unit + AOI comparison,
    LSI by class / by unit, FS by unit, the landslide AOI comparison, and the
    PII-safe household priority / settlement roll-up / driver-count tables.
    Never raises on a data gap — a missing block yields ``[]``."""
    calc = _require_calc_access(db, calculation_id, current_user)
    calc_uuid = calc.id

    from app.services.operational_plan.data_collector import (
        get_hazard_vuln_data,
        get_soil_erosion_data,
    )

    try:
        se = get_soil_erosion_data(db, str(calc_uuid))
    except Exception:  # noqa: BLE001
        logger.warning("hazard-erosion tables: soil block failed", exc_info=True)
        se = {}
    try:
        hv = get_hazard_vuln_data(db, str(calc_uuid))
    except Exception:  # noqa: BLE001
        logger.warning("hazard-erosion tables: hazard block failed", exc_info=True)
        hv = {}

    src = {"soil": se, "hazard": hv}
    tables: dict[str, Any] = {}
    for key, block in _TABLE_KEYS:
        rows = src[block].get(key)
        rows = rows if isinstance(rows, list) else []
        # defence-in-depth: drop any forbidden column that somehow leaked
        clean = [
            {
                k: v
                for k, v in row.items()
                if not any(bad in str(k).lower() for bad in _FORBIDDEN_KEY_SUBSTR)
            }
            for row in rows
            if isinstance(row, dict)
        ]
        tables[key] = clean

    return {
        "calculation_id": str(calc_uuid),
        "fs_enabled": bool(hv.get("fs_enabled")),
        "hh_available": bool(hv.get("hh_available")),
        "has_user_group": bool(se.get("soil_loss_has_user_group")),
        **tables,
    }


@router.post(
    "/calculations/{calculation_id}/hazard-erosion/recompute",
    status_code=status.HTTP_202_ACCEPTED,
)
def hazard_erosion_recompute(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Drop the RUSLE + LSI/FS GeoTIFF caches, the rendered-map PNG cache and the
    ``op_data_cache`` row so the next ``summary`` / map request re-computes."""
    calc = _require_calc_access(db, calculation_id, current_user)
    calc_uuid = calc.id
    cleared: list[str] = []

    try:
        from app.services.operational_plan.soil_erosion import clear_cache as _se_clear

        _se_clear(calc_uuid)
        cleared.append("soil_erosion")
    except Exception:  # noqa: BLE001 -- best-effort
        logger.warning("hazard-erosion recompute: soil clear failed", exc_info=True)

    try:
        from app.services.operational_plan.landslide_susceptibility import (
            clear_cache as _hv_clear,
        )

        _hv_clear(calc_uuid)  # shared dir → clears FS too
        cleared.append("hazard_vuln")
    except Exception:  # noqa: BLE001 -- best-effort
        logger.warning("hazard-erosion recompute: hazard clear failed", exc_info=True)

    try:
        from app.services.management_plan_docx.plan_map_service import clear_map_cache

        clear_map_cache(calculation_id=calc_uuid)
        cleared.append("map_cache")
    except Exception:  # noqa: BLE001 -- best-effort
        logger.warning(
            "hazard-erosion recompute: map cache clear failed", exc_info=True
        )

    try:
        from app.models.op_data_cache import OpDataCache

        n = (
            db.query(OpDataCache)
            .filter(OpDataCache.calculation_id == calc_uuid)
            .delete()
        )
        db.commit()
        if n:
            cleared.append("op_data_cache")
    except Exception:  # noqa: BLE001 -- best-effort
        db.rollback()
        logger.warning(
            "hazard-erosion recompute: op_data_cache clear failed", exc_info=True
        )

    return {"status": "recompute queued", "cleared": cleared}


# ── narration ────────────────────────────────────────────────────────────────

_NARRATION_KEYS = {
    "soil": {
        "methodology": "soil_loss_methodology_narration",
        "findings": "soil_loss_findings_narration",
        "prescription": "soil_loss_prescription_narration",
        "assumptions": "soil_loss_assumptions",
    },
    "hazard": {
        "methodology": "hazard_methodology_narration",
        "findings": "hazard_findings_narration",
        "prescription": "hazard_prescription_narration",
        "assumptions": "hazard_assumptions",
    },
}


@router.get("/calculations/{calculation_id}/hazard-erosion/narration")
def hazard_erosion_narration(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The adaptive methodology / findings / prescription prose + the caveat
    (assumptions) lists, in **both** languages so the client toggles without a
    re-fetch. Sourced from the RUSLE and landslide/household collectors — no
    compute here."""
    calc = _require_calc_access(db, calculation_id, current_user)
    calc_uuid = calc.id

    from app.services.operational_plan.data_collector import (
        get_hazard_vuln_data,
        get_soil_erosion_data,
    )

    try:
        se = get_soil_erosion_data(db, str(calc_uuid))
    except Exception:  # noqa: BLE001
        logger.warning("hazard-erosion narration: soil block failed", exc_info=True)
        se = {}
    try:
        hv = get_hazard_vuln_data(db, str(calc_uuid))
    except Exception:  # noqa: BLE001
        logger.warning("hazard-erosion narration: hazard block failed", exc_info=True)
        hv = {}

    src = {"soil": se, "hazard": hv}

    def _block(name: str) -> dict[str, Any]:
        d = src[name]
        keys = _NARRATION_KEYS[name]
        out: dict[str, Any] = {}
        for label, base in keys.items():
            if label == "assumptions":
                out["assumptions_ne"] = list(d.get(base) or [])
                out["assumptions_en"] = list(d.get(f"{base}_en") or [])
            else:
                out[f"{label}_ne"] = d.get(base) or ""
                out[f"{label}_en"] = d.get(f"{base}_en") or ""
        return out

    return {
        "calculation_id": str(calc_uuid),
        "soil_available": bool(se.get("soil_loss_available")),
        "hazard_available": bool(hv.get("hazard_vuln_available")),
        "soil": _block("soil"),
        "hazard": _block("hazard"),
    }


# ── insert the seed ३.८ / ३.९ subsections into the calc's OP tree ─────────────

# match the seed-tree subsections by their English title (stable across locales)
_SOIL_SUBSECTION_EN = "Soil Loss & Erosion Risk"
_HAZARD_SUBSECTION_EN = "Slope Instability, Landslide Hazard & Household Vulnerability"
_INSERT_ANCHORS_EN = ("Protection Working Circle", "Annual Production")


def _reassign_ids(node) -> None:
    from uuid import uuid4

    node.id = str(uuid4())
    for child in node.children:
        _reassign_ids(child)


def _find_insert_parent(tree):
    """The section the two subsections should hang under — Section ३ (वन
    मौज्दात). Prefer the section already holding the Protection Working Circle /
    Annual Production / *Growing Stock* subsections; then a top-level section
    numbered 3; then the first top-level section; else ``None`` (append to root).
    """
    from app.services.operational_plan.tree_models import TreeOperations

    for node in TreeOperations.flatten(tree):
        if node.type != "section":
            continue
        child_titles = [c.title_en or "" for c in node.children]
        if any(a in child_titles for a in _INSERT_ANCHORS_EN) or any(
            "Growing Stock" in c for c in child_titles
        ):
            return node

    for node in tree:
        if node.type == "section" and str(node.number or "").strip().rstrip(".") in (
            "3",
            "३",
        ):
            return node

    for node in tree:
        if node.type == "section":
            return node
    return None


@router.post("/calculations/{calculation_id}/hazard-erosion/insert-op-subsections")
def hazard_erosion_insert_op_subsections(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Append the seed-tree subsections **३.८ माटो क्षय** and **३.९ पहिरो /
    घरधुरी जोखिम** to this forest's Operational-Plan document tree, then resolve
    their ``{{tokens}}``. Idempotent — a subsection already present (matched by
    English title) is skipped. 409 when there is no OP yet, or when the plan is
    already approved."""
    calc = _require_calc_access(db, calculation_id, current_user)

    from app.models.operational_plan import OperationalPlan
    from app.services.operational_plan.auto_numbering import recompute_numbers
    from app.services.operational_plan.seed_data import get_default_seed_tree
    from app.services.operational_plan.tree_models import TreeNode, TreeOperations
    from app.services.operational_plan.variable_resolver import VariableResolver

    plan = db.execute(
        select(OperationalPlan).where(OperationalPlan.calculation_id == calc.id)
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "NO_OP",
                "message": "Create the Operational Plan for this forest first.",
            },
        )
    if (plan.status or "").lower() == "approved":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PLAN_APPROVED",
                "message": "The Operational Plan is approved and can no longer be edited.",
            },
        )

    sections = dict(plan.sections or {})
    tree = [TreeNode.from_dict(n) for n in (sections.get("tree") or [])]

    present = {n.title_en for n in TreeOperations.flatten(tree)}
    want = [
        en for en in (_SOIL_SUBSECTION_EN, _HAZARD_SUBSECTION_EN) if en not in present
    ]
    if not want:
        return {
            "status": "already_present",
            "inserted": [],
            "plan_id": str(plan.id),
        }

    seed_by_en = {
        n.title_en: n for n in TreeOperations.flatten(get_default_seed_tree())
    }
    parent = _find_insert_parent(tree)
    fresh_nodes = []
    for en in want:
        src_node = seed_by_en.get(en)
        if src_node is None:  # seed tree changed shape — nothing to copy
            continue
        node = TreeNode.from_dict(src_node.to_dict())
        _reassign_ids(node)
        (parent.children if parent is not None else tree).append(node)
        fresh_nodes.append(node)

    if not fresh_nodes:
        return {
            "status": "already_present",
            "inserted": [],
            "plan_id": str(plan.id),
        }

    lang = (plan.plan_metadata or {}).get("language", "NP") or "NP"
    recompute_numbers(tree, language=lang)

    try:
        resolver = VariableResolver(db, calc.id, plan)
        for node in fresh_nodes:
            plan_live.populate_node(node, resolver.resolve_node_content)
    except Exception:  # noqa: BLE001 -- tokens stay literal, still a valid tree
        logger.warning(
            "insert-op-subsections: variable resolve failed for %s",
            calc.id,
            exc_info=True,
        )

    sections["tree"] = [n.to_dict() for n in tree]
    plan.sections = sections
    flag_modified(plan, "sections")
    from datetime import datetime, timezone

    plan.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "status": "inserted",
        "inserted": [n.title_en for n in fresh_nodes],
        "plan_id": str(plan.id),
    }
