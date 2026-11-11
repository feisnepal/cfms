"""Run the polygon analysis for EVERY unit of a forest and keep the answer on the unit (owner rule 2026-10-10).

"Run analysis" used to analyse only the top-level blocks/compartments and park the numbers in ``result_data``. The sub-layers
(sub-blocks, sub-compartments) therefore had nothing in their attribute tables. Here every real unit (any level) is analysed
on its own polygon -- private land taken out, as for the top level -- and its values are stored in ``unit_analysis`` as flat
``an_*`` keys. A parent's numbers are computed on the parent's polygon, never summed from its children.

``analysis_status`` is the one answer to "has the analysis been run on the CURRENT units?" (used by the export gate).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Keys that are bookkeeping or too large for a table cell; everything else the analyser returns is kept.
_SKIP_KEYS = {"wkt", "extent", "potential_species", "soil_properties"}
_MAX_DIST_ITEMS = 6

# Units that count as "real structure": not a trial layer awaiting a decision (same filter the OP reads).
_REAL_UNITS_FROM = """
    FROM forest_blocks b
    LEFT JOIN raster_layers l ON l.id = b.raster_layer_id
"""
_REAL_UNITS_WHERE = """
   WHERE b.calculation_id = :c
     AND (b.raster_layer_id IS NULL OR l.promoted_as IS NOT NULL)
"""


def _fmt_dist(d: Dict[str, Any]) -> str:
    """``{"Forest": 71.2, "Shrub": 3}`` -> ``"Forest 71.2%; Shrub 3%"`` (largest first)."""
    items = []
    for k, v in d.items():
        try:
            items.append((str(k), float(v)))
        except (TypeError, ValueError):
            continue
    items.sort(key=lambda kv: -kv[1])
    shown = [f"{k} {v:g}%" for k, v in items[:_MAX_DIST_ITEMS] if v]
    if len(items) > _MAX_DIST_ITEMS:
        shown.append("...")
    return "; ".join(shown)


def flatten(raw: Dict[str, Any]) -> Dict[str, Any]:
    """The analyser's dict -> ``{"an_<key>": scalar | string}``. Nothing is dropped except ``_SKIP_KEYS`` and empty values."""
    out: Dict[str, Any] = {}
    for key, v in raw.items():
        if key in _SKIP_KEYS or v is None or v == "":
            continue
        if isinstance(v, bool):
            out[f"an_{key}"] = v
        elif isinstance(v, float):
            out[f"an_{key}"] = round(v, 2)
        elif isinstance(v, (int, str)):
            out[f"an_{key}"] = v
        elif isinstance(v, dict):
            s = _fmt_dist(v)
            if s:
                out[f"an_{key}"] = s
        elif isinstance(v, (list, tuple)):
            if v and all(isinstance(x, str) for x in v):
                # a list of names (e.g. the soil's limiting factors) reads as text, not as a count
                out[f"an_{key}"] = "; ".join(x for x in v if x)
            else:
                out[f"an_{key}_count"] = len(v)
    return out


async def run_unit_analysis(db: Session, calc, options: Optional[Dict[str, bool]] = None) -> Dict[str, int]:
    """Analyse every real unit and (re)write its ``unit_analysis`` row. A unit that fails keeps its error and the others go on."""
    from app.models.unit_analysis import UnitAnalysis
    from app.utils.json_utils import sanitize_for_json
    from app.services.analysis import (
        analyze_block_geometry,
        create_block_working_geometry,
        get_excluded_sub_areas,
    )

    rows = db.execute(
        text("SELECT b.id::text, ST_AsGeoJSON(b.geometry) " + _REAL_UNITS_FROM + _REAL_UNITS_WHERE + " AND b.geometry IS NOT NULL"),
        {"c": str(calc.id)},
    ).fetchall()
    excluded = get_excluded_sub_areas(calc.result_data or {})
    done = failed = 0
    for block_id, geojson in rows:
        values: Dict[str, Any] = {}
        raw: Dict[str, Any] = {}
        error: Optional[str] = None
        try:
            geometry = json.loads(geojson)
            working = create_block_working_geometry(geometry, excluded) if excluded else geometry
            if working is None:
                error = "Unit is entirely private land"
            else:
                raw = await analyze_block_geometry(working, calc.id, db, options)
                failed_steps = raw.pop("analysis_failed_steps", None)
                values = flatten(raw)
                raw = sanitize_for_json(raw)
                if failed_steps:
                    # Partial results are kept for the table, but the unit does NOT count as analysed.
                    error = "Analysis steps failed: " + ", ".join(failed_steps)
        except Exception as exc:  # noqa: BLE001 -- recorded on the unit's row and logged; the other units still run
            logger.exception("unit_analysis: unit %s failed", block_id)
            db.rollback()
            error = str(exc)[:300]
        # An analyser that swallowed a SQL error can leave the transaction aborted; the values are already in memory.
        db.rollback()
        row = db.query(UnitAnalysis).filter(UnitAnalysis.block_id == UUID(block_id)).first()
        if row is None:
            row = UnitAnalysis(calculation_id=calc.id, block_id=UUID(block_id))
            db.add(row)
        row.values = values
        row.raw = raw
        row.error = error
        row.computed_at = datetime.now(timezone.utc)
        db.commit()
        failed += 1 if error else 0
        done += 0 if error else 1
    return {"units": len(rows), "done": done, "failed": failed}


def analysis_status(db: Session, calc_id: UUID) -> Dict[str, Any]:
    """``{ready, units, analysed, missing, stale}``. Ready = every real unit has an error-free row and the forest is not flagged
    as changed since (``structure_stale['analysis']``)."""
    row = db.execute(
        text(
            "SELECT count(*), count(*) FILTER (WHERE u.id IS NOT NULL AND u.error IS NULL) "
            + _REAL_UNITS_FROM
            + " LEFT JOIN unit_analysis u ON u.block_id = b.id "
            + _REAL_UNITS_WHERE
        ),
        {"c": str(calc_id)},
    ).first()
    total, analysed = int(row[0] or 0), int(row[1] or 0)
    rd = db.execute(text("SELECT result_data FROM calculations WHERE id = :c"), {"c": str(calc_id)}).scalar() or {}
    stale = bool((rd.get("structure_stale") or {}).get("analysis"))
    return {
        "ready": total > 0 and analysed == total and not stale,
        "units": total, "analysed": analysed, "missing": total - analysed, "stale": stale,
    }


def units_payload(db: Session, calc_id: UUID) -> Dict[str, Any]:
    """``{state, units: {unit_id: {an_*: value}}, columns: [an_* keys present]}`` for the attribute table. Stored data only."""
    from app.models.unit_analysis import UnitAnalysis

    rows: List[UnitAnalysis] = db.query(UnitAnalysis).filter(UnitAnalysis.calculation_id == calc_id).all()
    if not rows:
        return {"state": "not_computed", "units": {}, "columns": []}
    units = {str(r.block_id): dict(r.values or {}) for r in rows}
    columns = sorted({k for v in units.values() for k in v})
    return {"state": "ready", "units": units, "columns": columns}


def raw_by_unit_id(db: Session, calc_id: UUID) -> Dict[str, Dict[str, Any]]:
    """``{unit_id: the analyser's full result}`` for every unit that has one -- the values the Operational Plan placeholders read."""
    from app.models.unit_analysis import UnitAnalysis

    rows = db.query(UnitAnalysis.block_id, UnitAnalysis.raw).filter(UnitAnalysis.calculation_id == calc_id).all()
    return {str(bid): dict(raw) for bid, raw in rows if raw}


def mirror_into_result_data(units: List[Dict[str, Any]], raw: Dict[str, Dict[str, Any]]) -> int:
    """Write each unit's stored analysis onto its entry in the ``result_data`` unit list (matched by id), so everything that still
    reads that list -- the OP placeholders and tables -- sees exactly what the attribute tables show. Returns how many entries."""
    n = 0
    for entry in units:
        r = raw.get(str(entry.get("id") or entry.get("block_id") or ""))
        if r:
            entry.update(r)
            n += 1
    return n
