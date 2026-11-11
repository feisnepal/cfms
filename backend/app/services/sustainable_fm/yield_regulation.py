"""Growing-stock yield regulation, per felling series (P3).

``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §3.6 / §5 P3.

The felling series is a **type-homogeneous stratum** of the production working
circle, not one management block (अनुसूची-12; §3.2 of the कार्यविधि). Production
blocks are grouped by ``effective_type_no``; each group is one series with its
own ``N`` / ``C`` / ``R`` and one annual harvest figure. The forest total is the
sum. Only trees ≥ 40 cm DBH (``gs_ge40_*``) count.

    selection  : annual_harvest_g = (GS40_g / N_g) * pct_g/100 * C_g   (== GS40_g * pct_g/100)
    shelterwood: annual_harvest_g = (GS40_g / N_g - mother_g) / R_g
    stem_count : target residual stems/ha (no volume)
    area_coupe : GS40_g / N_g   (crude volume read on one coupe)
    protection : 0  (salvage only)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.services.sustainable_fm.forest_type_classifier import PROTECTION_TYPES
from app.services.sustainable_fm.prescription import pick_branch
from app.services.sustainable_fm.sfm_config import SfmParams

logger = logging.getLogger(__name__)

try:  # optional — the >50 % protected-overlap rule
    from app.services.guideline_sampling import classify_block_by_majority_area
except Exception:  # noqa: BLE001 -- keep working if the helper moves
    classify_block_by_majority_area = None  # type: ignore[assignment]


def match_step(steps: Optional[list[dict[str, Any]]], gsha: float) -> Optional[float]:
    """First step where ``(min is None or gsha >= min) and (max is None or
    gsha < max)``. ``None`` when there are no steps."""
    for s in steps or []:
        mn = s.get("gs_per_ha_min")
        mx = s.get("gs_per_ha_max")
        if (mn is None or gsha >= mn) and (mx is None or gsha < mx):
            return float(s["pct"])
    return float(steps[-1]["pct"]) if steps else None


def _working_circle_by_block(calc_id, db: Session) -> dict[str, str]:
    rows = db.execute(
        text(
            "SELECT COALESCE(block_name, name) AS bn, "
            "COALESCE(working_circle, 'production') AS wc "
            "FROM forest_blocks WHERE calculation_id = :cid"
        ),
        {"cid": str(calc_id)},
    ).fetchall()
    return {r.bn: r.wc for r in rows}


def _wkt_by_block(calc_id, db: Session) -> dict[str, str]:
    rows = db.execute(
        text(
            "SELECT COALESCE(block_name, name) AS bn, ST_AsText(geometry) AS wkt "
            "FROM forest_blocks WHERE calculation_id = :cid"
        ),
        {"cid": str(calc_id)},
    ).fetchall()
    return {r.bn: r.wkt for r in rows}


def _is_majority_protected(block_name: str, wkt_by: dict, sub_areas: list) -> bool:
    if not sub_areas or classify_block_by_majority_area is None:
        return False
    wkt = wkt_by.get(block_name)
    if not wkt:
        return False
    try:
        return bool(classify_block_by_majority_area(wkt, sub_areas))
    except Exception:  # noqa: BLE001 -- a classifier hiccup must not drop the block
        logger.debug(
            "majority-protected check failed for %s", block_name, exc_info=True
        )
        return False


def _band(block: dict) -> Optional[int]:
    z = block.get("_zone") or {}
    return z.get("slope_band")


def build_series(
    blocks: list[dict[str, Any]],
    prescriptions: dict,
    calc: Calculation,
    db: Session,
    params: SfmParams,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Returns ``(felling_series, forest_summary_partial)``. ``blocks`` are the
    assembled ``result_data['sfm']['blocks']`` dicts, each carrying a private
    ``_zone`` (``zone_by_block[...]``) for the band-4 check."""
    sub_areas = (calc.result_data or {}).get("sub_areas", []) or []
    wc_by = _working_circle_by_block(calc.id, db)
    wkt_by = _wkt_by_block(calc.id, db)

    protection_area = 0.0
    prod_by_type: dict[int, list[dict]] = {}
    prot_types: set[int] = set()

    for b in blocks:
        t = b["effective_type_no"]
        area = float(b.get("area_ha") or 0.0)
        name = b["block_name"]
        band = _band(b)
        is_prot = (
            t in PROTECTION_TYPES
            or wc_by.get(name) == "protection"
            or _is_majority_protected(name, wkt_by, sub_areas)
            # >45° is salvage-only for EVERY type now (owner decision,
            # 2026-09-14 -- orientation.py extends the same threshold from
            # types 8/9/10/13 to a general policy; mirrored here so a block
            # labelled Conservation by that rule isn't still full-harvested).
            # The band-3 सि.नं.12-only nudge in orientation.py is a label
            # resolution only -- it does not exclude from the felling series.
            or band == params.protection_slope_band
        )
        if is_prot:
            protection_area += area
            prot_types.add(t)
        else:
            prod_by_type.setdefault(t, []).append(b)

    series: list[dict[str, Any]] = []
    total_harvest = 0.0

    for t, group in sorted(prod_by_type.items()):
        row = prescriptions.get(t)
        branch = pick_branch(group, params)
        b = _branch(row, branch)
        area_g = sum(float(x.get("area_ha") or 0.0) for x in group) or 0.0
        gs_vals = [(x.get("inputs") or {}).get("gs_ge40_m3") for x in group]
        have_gs = any(v is not None for v in gs_vals)
        gs40_g = sum(v for v in gs_vals if v is not None)
        gsha_g = (gs40_g / area_g) if area_g > 0 else 0.0
        method = b.get("method")
        yr = b.get("yield_rules") or {}
        pct_g = (
            match_step(yr.get("steps"), gsha_g)
            if yr.get("basis") == "growing_stock_pct_ge40"
            else None
        )

        row_d = _series_row(
            t, branch, method, b, area_g, gs40_g, gsha_g, pct_g, have_gs, group, params
        )
        series.append(row_d)
        if row_d["annual_harvest_m3"] is not None:
            total_harvest += row_d["annual_harvest_m3"]

    for t in sorted(prot_types):
        row = prescriptions.get(t)
        b = _branch(row, "default")
        series.append(
            {
                "id": t,
                "type_no": t,
                "branch": "default",
                "method": (b.get("method") if b else "area_coupe"),
                "C": None,
                "R": None,
                "N": None,
                "area_ha": 0.0,  # area sits in protection_area, not a series
                "annual_felling_area_ha": None,
                "gs_ge40_m3_per_ha": None,
                "gs_ge40_m3": None,
                "pct": None,
                "annual_harvest_m3": 0.0,
                "note_ne": "संरक्षणमुखी — कुनै नियमित कटान होइन (सल्भेज मात्र)।",
                "note_en": "Protection stratum — no regular harvest (salvage only).",
            }
        )

    production_area = sum(
        float(b.get("area_ha") or 0.0) for grp in prod_by_type.values() for b in grp
    )
    type_area: dict[str, float] = {}
    for b in blocks:
        type_area[str(b["effective_type_no"])] = type_area.get(
            str(b["effective_type_no"]), 0.0
        ) + float(b.get("area_ha") or 0.0)
    dominant = int(max(type_area, key=lambda k: type_area[k])) if type_area else None

    summary = {
        "dominant_type_no": dominant,
        "type_area_breakdown": {k: round(v, 4) for k, v in type_area.items()},
        "production_area_ha": round(production_area, 4),
        "protection_area_ha": round(protection_area, 4),
        "total_annual_harvest_m3": round(total_harvest, 4),
        "sampling_plan": [],  # sfm_service fills from sampling_defaults
    }
    return series, summary


def _branch(row, branch: str) -> dict[str, Any]:
    if row is None:
        return {}
    br = row.branches or {}
    return br.get(branch) or br.get("default") or next(iter(br.values()), {})


def _series_row(
    t, branch, method, b, area_g, gs40_g, gsha_g, pct_g, have_gs, group, params
) -> dict[str, Any]:
    yr = b.get("yield_rules") or {}
    C = b.get("felling_cycle_years")
    R = b.get("regeneration_period_years")
    N: Optional[int] = None
    harvest: Optional[float] = None
    note_ne = yr.get("note_ne", "")
    note_en = yr.get("note_en", "")

    if not have_gs:
        note_ne = "सूचक मात्र — इन्भेन्ट्री पर्खँदै।"
        note_en = "Indicative — pending inventory."
    elif method == "selection_felling_cycle" and C:
        N = C
        harvest = gs40_g * (pct_g or 0.0) / 100.0
    elif method == "shelterwood_periodic_block" and R:
        N = R
        mtree_vals = [(x.get("inputs") or {}).get("mother_trees_per_ha") for x in group]
        mtree_known = [v for v in mtree_vals if v is not None]
        mtree_ha = (
            sum(mtree_known) / len(mtree_known)
            if mtree_known
            else (params.mother_tree_target_min + params.mother_tree_target_max) / 2.0
        )
        mother_g = mtree_ha * (area_g / N) * params.mean_mother_tree_vol_m3
        harvest = max(0.0, (gs40_g / N - mother_g) / R)
    elif method == "stem_count":
        harvest = None
    elif method == "area_coupe":
        N = C or 10
        harvest = (gs40_g / N) if gs40_g else None

    return {
        "id": t,
        "type_no": t,
        "branch": branch,
        "method": method,
        "C": C,
        "R": R,
        "N": N,
        "area_ha": round(area_g, 4),
        "annual_felling_area_ha": round(area_g / N, 4) if N else None,
        "gs_ge40_m3_per_ha": round(gsha_g, 4) if have_gs else None,
        "gs_ge40_m3": round(gs40_g, 4) if have_gs else None,
        "pct": pct_g,
        "annual_harvest_m3": round(harvest, 4) if harvest is not None else None,
        "note_ne": note_ne,
        "note_en": note_en,
    }


__all__ = ["match_step", "build_series"]
