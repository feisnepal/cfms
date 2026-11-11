"""Where to do stem mapping (tree inventory) when shelterwood is the chosen system.

Owner rule (2026-10-12): under shelterwood, the stem mapping goes in the block / compartment with the MOST growing stock of trees of 40 cm DBH and
above. For every unit the field inventory is compared in three DBH ranges - 10 to 40 cm, 10 cm and above, 40 cm and above - and for each the
NUMBER of trees and the VOLUME are given separately, per hectare (the average of the unit's sample plots). The unit with the highest volume of trees
of 40 cm and above is marked as the suggestion.

Read-only: it reads the inventory summary and the SFM result and writes nothing.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dbh_classifier import DbhClassRegistry
from app.services.sustainable_fm.species_assemblage import _as_float, _norm_class_key

logger = logging.getLogger(__name__)

SHELTERWOOD_METHOD = "shelterwood_periodic_block"
# The key of the per-unit list inside the sustainable-FM result (not the legacy units cache that the unit-access ratchet watches).
SFM_UNITS_KEY = "blocks"
RANGES = ("from10_to40", "from10", "from40")
_COUNT_KEYS = ("count_per_ha", "count")
_VOLUME_KEYS = ("timber_m3_per_ha", "timber")


def class_bounds() -> Dict[str, tuple[float, Optional[float]]]:
    """``{normalised class key: (lower, upper or None)}`` from the same registry the field inventory writes with."""
    classes = DbhClassRegistry.get_system("guideline_2061")
    if hasattr(classes, "classes"):
        classes = classes.classes
    return {_norm_class_key(c.key): (float(c.lower or 0), None if c.upper is None else float(c.upper)) for c in classes}


def _first(d: Dict[str, Any], keys) -> Optional[float]:
    for k in keys:
        v = _as_float(d.get(k))
        if v is not None:
            return v
    return None


def ranges_from_breakdown(breakdown: Any, bounds: Optional[Dict[str, tuple]] = None) -> Optional[Dict[str, Dict[str, Optional[float]]]]:
    """Per-hectare trees and volume for 10-40 cm, 10 cm+ and 40 cm+, from a ``dbh_class_breakdown``; None when it cannot be read."""
    if not isinstance(breakdown, dict) or not breakdown:
        return None
    bounds = bounds or class_bounds()
    out = {r: {"count_per_ha": 0.0, "volume_m3_per_ha": 0.0} for r in RANGES}
    seen = False
    for key, value in breakdown.items():
        if not isinstance(value, dict):
            continue
        lo_hi = bounds.get(_norm_class_key(key))
        if lo_hi is None:
            continue
        lower, upper = lo_hi
        n = _first(value, _COUNT_KEYS) or 0.0
        v = _first(value, _VOLUME_KEYS) or 0.0
        seen = True
        if lower >= 10 and upper is not None and upper <= 40:
            out["from10_to40"]["count_per_ha"] += n
            out["from10_to40"]["volume_m3_per_ha"] += v
        if lower >= 10:
            out["from10"]["count_per_ha"] += n
            out["from10"]["volume_m3_per_ha"] += v
        if lower >= 40:
            out["from40"]["count_per_ha"] += n
            out["from40"]["volume_m3_per_ha"] += v
    if not seen:
        return None
    return {r: {"count_per_ha": round(m["count_per_ha"], 1), "volume_m3_per_ha": round(m["volume_m3_per_ha"], 2)} for r, m in out.items()}


def rank(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Highest volume of trees of 40 cm and above first (units with no figures last); mark the first one with any such volume."""
    def key(r):
        v = (r.get("ranges") or {}).get("from40", {}).get("volume_m3_per_ha")
        return (v is None, -(v or 0.0), r.get("block_name") or "")

    ordered = sorted(rows, key=key)
    for r in ordered:
        r["suggested"] = False
    for r in ordered:
        v = (r.get("ranges") or {}).get("from40", {}).get("volume_m3_per_ha")
        if v:
            r["suggested"] = True
            break
    return ordered


def _unit_figures(db: Session, calculation_id, block_name: str, bounds) -> tuple[Optional[dict], int, bool]:
    row = db.execute(
        text(
            "SELECT s.dbh_class_breakdown, s.total_sample_plots "
            "FROM field_inventory_block_summary s JOIN field_inventory_calculations fc ON fc.id = s.field_inventory_calculation_id "
            "WHERE fc.calculation_id = :cid AND s.block_name = :bk"
        ),
        {"cid": str(calculation_id), "bk": block_name},
    ).first()
    mapped = bool(
        db.execute(
            text(
                "SELECT 1 FROM inventory_trees it JOIN inventory_calculations ic ON ic.id = it.inventory_calculation_id "
                "WHERE ic.calculation_id = :cid AND it.block_name = :bk LIMIT 1"
            ),
            {"cid": str(calculation_id), "bk": block_name},
        ).first()
    )
    if row is None:
        return None, 0, mapped
    return ranges_from_breakdown(row.dbh_class_breakdown, bounds), int(row.total_sample_plots or 0), mapped


def build_suggestion(calc, db: Session, sfm: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``{applies, series, rows, suggested}``. ``applies`` is true when at least one felling series is managed by shelterwood; only the units of
    those series are ranked."""
    if sfm is None:
        from app.services.sustainable_fm.sfm_service import get_sfm

        sfm = get_sfm(calc, db)
    shelter_ids = {s.get("id") for s in (sfm.get("felling_series") or []) if s.get("method") == SHELTERWOOD_METHOD}
    if not shelter_ids:
        return {"applies": False, "series": [], "rows": [], "suggested": None}
    bounds = class_bounds()
    rows: List[Dict[str, Any]] = []
    for b in sfm.get(SFM_UNITS_KEY) or []:
        if b.get("felling_series_id") not in shelter_ids:
            continue
        name = b.get("block_name")
        ranges, plots, mapped = _unit_figures(db, calc.id, name, bounds)
        rows.append({"block_name": name, "area_ha": b.get("area_ha"), "plot_count": plots, "ranges": ranges, "stem_mapped": mapped, "has_inventory": ranges is not None})
    ordered = rank(rows)
    suggested = next((r["block_name"] for r in ordered if r["suggested"]), None)
    return {"applies": True, "series": sorted(str(i) for i in shelter_ids), "rows": ordered, "suggested": suggested}
