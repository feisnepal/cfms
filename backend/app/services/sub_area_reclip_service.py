"""Sub-area re-clip after a boundary reshape (VR-6 / plan D6).

Sub-areas are cut-outs measured *inside* the forest boundary — their combined
area is subtracted from the productive area in every report.  When the boundary
moves inward, any sub-area sticking out past the new edge is counting land the
forest no longer contains, so the excluded-area figures overstate and the
productive figures understate.

Nothing was repairing that.  The audit found the legacy clipping code
(`blocks.py`, `forests.py`, and the dead `clip_sub_areas_to_blocks`) never runs
on the single-authority edit path, so a boundary edit left sub-areas exactly as
they were.

This module re-clips them to the new boundary and keeps the two stores in step:
``calc.result_data["sub_areas"]`` (what the API and reports read) and the
``ForestSubArea`` rows (what spatial queries read).  Both are updated, because
the last time two stores each held a copy of the same fact, only one of them
was being maintained.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from geoalchemy2.shape import from_shape
from shapely.geometry import mapping, shape as to_shapely
from sqlalchemy.orm import attributes

from ..core.constants import SQM_PER_HA
from ..core.sub_area_kinds import is_strip
from ..models.forest_sub_area import ForestSubArea
from ..utils.geometry_utils import calculate_area_geodesic_from_shapely

logger = logging.getLogger(__name__)

#: A clipped remnant smaller than this is dropped rather than kept as a sliver.
#: One square metre: below anything a forester would record, above the area a
#: floating-point intersection can invent along a shared edge.
MIN_KEPT_AREA_M2 = 1.0

W_SUB_AREAS_CLIPPED = "SUB_AREAS_CLIPPED"


def _as_shape(geom: Any):
    if geom is None:
        return None
    if hasattr(geom, "srid") and hasattr(geom, "data"):  # a geoalchemy2 WKB element
        from geoalchemy2.shape import to_shape

        return to_shape(geom)
    try:
        return to_shapely(geom) if isinstance(geom, dict) else geom
    except Exception:
        logger.exception(
            "geometry unreadable - the sub-area is skipped by the re-clip, "
            "so it may still extend past the new boundary"
        )
        return None


PENDING_FLAG = "pending_boundary_clip"


def _settled(sa: Dict[str, Any]) -> Dict[str, Any]:
    """The sub-area with its "pending boundary clip" marker removed (it has now been clipped)."""
    if PENDING_FLAG not in sa:
        return sa
    out = dict(sa)
    out.pop(PENDING_FLAG, None)
    return out


def reclip_sub_areas_to_boundary(
    db,
    calc,
    boundary_geom: Any,
) -> Dict[str, Any]:
    """Clip every sub-area to ``boundary_geom``; return what changed.

    Returns ``{"clipped": [names], "dropped": [names], "unchanged": n}``.
    Callers surface ``clipped``/``dropped`` to the user — silently shrinking
    someone's recorded sub-area is exactly the kind of change that must be
    reported rather than assumed acceptable.
    """
    result: Dict[str, Any] = {"clipped": [], "dropped": [], "unchanged": 0}

    boundary = _as_shape(boundary_geom)
    if boundary is None or boundary.is_empty:
        return result

    rd = dict(calc.result_data or {})
    sub_areas: List[Dict[str, Any]] = list(rd.get("sub_areas") or [])
    if not sub_areas:
        return result

    kept: List[Dict[str, Any]] = []
    dropped_ids: List[str] = []
    # Sub-areas recorded before any boundary existed carry a marker; this run is
    # what settles them, so it must be persisted even when nothing needed cutting.
    had_pending = any(sa.get(PENDING_FLAG) for sa in sub_areas)

    for sa in sub_areas:
        if is_strip(sa):
            # a fire line is cut to the forest AREA (boundary minus private land) by fire_line_service, which also knows an
            # edited strip from a generated one; clipping it here too would make every generated strip look edited
            kept.append(sa)
            result["unchanged"] += 1
            continue
        geom = _as_shape(sa.get("geometry"))
        name = sa.get("name") or sa.get("category") or str(sa.get("id"))
        if geom is None or geom.is_empty:
            kept.append(_settled(sa))
            result["unchanged"] += 1
            continue

        try:
            inside = geom.intersection(boundary)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[sub-area re-clip] intersection failed for %s: %s", name, exc)
            kept.append(sa)  # left pending: it could not be checked, so it must not be called settled
            result["unchanged"] += 1
            continue

        if inside.is_empty:
            dropped_ids.append(str(sa.get("id")))
            result["dropped"].append(name)
            continue

        sqm, ha = calculate_area_geodesic_from_shapely(inside)
        if sqm < MIN_KEPT_AREA_M2:
            dropped_ids.append(str(sa.get("id")))
            result["dropped"].append(name)
            continue

        # `geom.equals(inside)` would call a re-clip that only removed float
        # noise a change; compare areas instead, at the same 1 m² resolution
        # used to drop slivers.
        old_sqm, _old_ha = calculate_area_geodesic_from_shapely(geom)
        if abs(old_sqm - sqm) < MIN_KEPT_AREA_M2:
            kept.append(_settled(sa))
            result["unchanged"] += 1
            continue

        updated = dict(_settled(sa))
        updated["geometry"] = mapping(inside)
        updated["area_sqm"] = round(sqm, 2)
        updated["area_hectares"] = round(ha, 4)
        # Legacy readers use `area_ha`; keep the alias in step or the two
        # disagree about the same sub-area.
        if "area_ha" in sa:
            updated["area_ha"] = round(ha, 4)
        kept.append(updated)
        result["clipped"].append(name)
        _sync_row(db, calc, str(sa.get("id")), inside, sqm)

    if not result["clipped"] and not result["dropped"] and not had_pending:
        return result

    rd["sub_areas"] = kept
    _recompute_excluded_metrics(rd)
    calc.result_data = rd
    attributes.flag_modified(calc, "result_data")

    for sub_id in dropped_ids:
        row = db.query(ForestSubArea).filter(
            ForestSubArea.calculation_id == calc.id,
            ForestSubArea.id == sub_id,
        ).first()
        if row is not None:
            db.delete(row)
    if dropped_ids:
        # A dropped sub-area must not leave plan lines pointing at nothing: they stay in the plan as forest-wide lines
        # (the user's numbers are not thrown away because a boundary moved).
        from .sub_area_plan import release_sub_areas

        released = release_sub_areas(db, calc.id, dropped_ids, "keep")
        result["plan_lines_kept"] = released["kept"] + released["deleted"]
    # Flush so the row store and result_data are consistent for anything that
    # reads before the caller commits.  Not optional: sessions configured with
    # autoflush=False (the test session, among others) would otherwise still
    # see a sub-area this function has just dropped.
    db.flush()

    logger.info(
        "[sub-area re-clip] calc=%s clipped=%d dropped=%d unchanged=%d",
        calc.id, len(result["clipped"]), len(result["dropped"]), result["unchanged"],
    )
    return result


def _sync_row(db, calc, sub_id: str, geom_shp, sqm: float) -> None:
    """Keep the ForestSubArea row in step with result_data."""
    row = db.query(ForestSubArea).filter(
        ForestSubArea.calculation_id == calc.id,
        ForestSubArea.id == sub_id,
    ).first()
    if row is not None:
        row.geometry = from_shape(geom_shp, srid=4326)
        row.area_hectares = round(sqm / SQM_PER_HA, 4)


def _recompute_excluded_metrics(rd: Dict[str, Any]) -> None:
    """Refresh the derived excluded-area figures after a re-clip.

    Imported lazily: `forests.py` imports this module's package at startup, and
    a module-level import here would close the cycle.
    """
    from ..api.forests import calculate_block_excluded_areas, calculate_total_excluded_area

    sub_areas = rd.get("sub_areas") or []
    try:
        rd["total_excluded_area"] = calculate_total_excluded_area(sub_areas)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[sub-area re-clip] total excluded recompute failed: %s", exc)
    blocks = rd.get("blocks") or []
    if blocks:
        try:
            rd["block_excluded_areas"] = calculate_block_excluded_areas(blocks, sub_areas)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[sub-area re-clip] per-block excluded recompute failed: %s", exc)


def reclip_after_boundary_write(db, calc, boundary: Any) -> Dict[str, Any]:
    """Clip every sub-area to a boundary that has JUST been written.

    For the writers that set ``calculation.boundary_geom`` directly instead of going
    through ``persist_boundary`` (which does this itself): the whole point of the
    rule "a sub-area lies inside the forest" is that it holds whichever route the
    boundary took to get there. Call it after the boundary is assigned and before
    the commit; ``boundary`` is a shapely geometry (or GeoJSON dict). Returns
    ``{clipped, dropped, unchanged}`` -- surface it to the user, because silently
    shrinking or removing a recorded sub-area must never be a side effect nobody sees.
    """
    result = reclip_sub_areas_to_boundary(db, calc, boundary)
    if result["clipped"] or result["dropped"]:
        logger.warning(
            "[sub-area re-clip] boundary write for %s clipped %s and dropped %s",
            getattr(calc, "id", "?"), result["clipped"], result["dropped"],
        )
    return result


__all__ = [
    "reclip_after_boundary_write",
    "PENDING_FLAG",
    "MIN_KEPT_AREA_M2",
    "W_SUB_AREAS_CLIPPED",
    "reclip_sub_areas_to_boundary",
]
