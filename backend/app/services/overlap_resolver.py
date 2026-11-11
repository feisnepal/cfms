"""
Boundary overlap resolution — **clip only** (2026-08-28 rework).

A proposed forest boundary is clipped against the union of every already-registered
adjoining forest: ``proposed.difference(union(neighbours))``.  Existing boundaries
are ground truth and are never modified (FCFS).  No vertex snapping, no gap
closure, no gap analysis — a strip left between the clipped boundary and a
neighbour is the user's to close with the vertex editor.

The whole computation runs in the proposed boundary's local UTM zone so every
area is true m² (bare shapely ``.area`` on lon/lat is square degrees); the
clipped geometry is projected back to EPSG:4326 before return.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

from shapely import ops
from shapely.geometry import MultiPolygon, Polygon, mapping, shape  # noqa: F401
from shapely.validation import make_valid

from ..core.constants import SQM_PER_HA

logger = logging.getLogger(__name__)

#: Polygon fragments below this (m²) after a clip are numerical dust, not land.
_DEGENERATE_M2 = 1.0


def _env_float(key: str, default: float) -> float:
    return float(os.environ.get(key, str(default)))


@dataclass
class ResolutionParams:
    # A boundary that loses more than this % to the clip is bounced back to the
    # user rather than saved as a sliver.
    reject_threshold_pct: float = field(
        default_factory=lambda: _env_float("BOUNDARY_REJECT_THRESHOLD_PCT", 80.0)
    )
    # Below this it also bounces back — too little forest left to register.
    min_forest_ha: float = field(
        default_factory=lambda: _env_float("BOUNDARY_MIN_FOREST_HA", 0.5)
    )
    # Above this % removed the UI asks for an explicit confirmation.
    confirmation_threshold_pct: float = field(
        default_factory=lambda: _env_float("BOUNDARY_CONFIRM_THRESHOLD_PCT", 40.0)
    )
    visibility_radius_m: float = field(
        default_factory=lambda: _env_float("BOUNDARY_VISIBILITY_RADIUS_M", 200.0)
    )


@dataclass
class ResolutionResult:
    status: str  # "no_overlap" | "acceptable" | "reject"
    resolved: Optional[Polygon] = None  # 4326 Polygon | MultiPolygon
    orig_area_ha: float = 0.0
    resolved_area_ha: float = 0.0
    removed_ha: float = 0.0
    removed_pct: float = 0.0
    requires_confirmation: bool = False
    overlapping_forests: List[dict] = field(default_factory=list)
    reason: Optional[str] = None


def _clip(proposed, existing_union):
    """``proposed − existing_union``, keeping ALL surviving polygon pieces.

    Only sub-``_DEGENERATE_M2`` dust is dropped; a neighbour that splits the
    boundary in two yields a MultiPolygon and both parts are kept.
    """
    clipped = proposed.difference(existing_union)
    if clipped.is_empty:
        return None
    if clipped.geom_type == "GeometryCollection":
        clipped = MultiPolygon(
            [g for g in clipped.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        )
    if clipped.geom_type == "MultiPolygon":
        keep = [p for p in clipped.geoms if p.area > _DEGENERATE_M2]
        if not keep:
            return None
        clipped = keep[0] if len(keep) == 1 else MultiPolygon(keep)
    if clipped.is_empty or clipped.area <= _DEGENERATE_M2:
        return None
    if not clipped.is_valid:
        clipped = make_valid(clipped)
    return clipped


def resolve_overlap(
    proposed_geom: dict,
    existing_forests: list,
    params: Optional[ResolutionParams] = None,
) -> ResolutionResult:
    """Clip ``proposed_geom`` against every forest in ``existing_forests``.

    ``existing_forests`` — SQLAlchemy rows carrying ``.boundary_geom`` (or
    ``.geometry``).  Returns a :class:`ResolutionResult` whose ``resolved`` is
    the clipped boundary in EPSG:4326 (``None`` only when nothing survives).
    """
    if params is None:
        params = ResolutionParams()

    poly = shape(proposed_geom)
    if not poly.is_valid:
        poly = make_valid(poly)
    if poly.geom_type not in ("Polygon", "MultiPolygon"):
        return ResolutionResult(
            status="reject", reason=f"Unsupported geometry type: {poly.geom_type}"
        )

    # --- project to the local UTM zone (metres) --------------------------------
    from pyproj import Transformer
    from shapely.ops import transform as _shp_transform

    from ..core.geo import calculate_utm_epsg

    _c = poly.centroid
    _epsg = calculate_utm_epsg(_c.x, _c.y)
    _to_m = Transformer.from_crs(4326, _epsg, always_xy=True).transform
    _to_deg = Transformer.from_crs(_epsg, 4326, always_xy=True).transform

    def _proj(fn, g):
        gp = _shp_transform(fn, g)
        return gp if gp.is_valid else make_valid(gp)

    poly_m = _proj(_to_m, poly)

    existing_geoms = []
    forest_infos = []
    for f in existing_forests:
        geom = getattr(f, "boundary_geom", None) or getattr(f, "geometry", None)
        if geom is None:
            continue
        try:
            eg = shape(geom) if hasattr(geom, "__geo_interface__") else None
            if eg is None:
                from geoalchemy2.shape import to_shape as _to_shape

                eg = _to_shape(geom)
            if not eg.is_valid:
                eg = make_valid(eg)
            existing_geoms.append(_proj(_to_m, eg))
            forest_infos.append(f)
        except Exception as e:  # noqa: BLE001 -- one bad neighbour must not sink the clip
            logger.warning("Skipping forest %s: %s", getattr(f, "id", "?"), e)

    orig_area_ha = poly_m.area / SQM_PER_HA

    if not existing_geoms:
        return ResolutionResult(
            status="no_overlap",
            resolved=poly,
            orig_area_ha=orig_area_ha,
            resolved_area_ha=orig_area_ha,
        )

    existing_union = ops.unary_union(existing_geoms)
    if not existing_union.is_valid:
        existing_union = make_valid(existing_union)

    clipped = _clip(poly_m, existing_union)

    # Per-forest overlap (for the preview list / audit)
    overlapping = []
    for fi, eg in zip(forest_infos, existing_geoms):
        try:
            inter = poly_m.intersection(eg)
            overlap_ha = inter.area / SQM_PER_HA if not inter.is_empty else 0.0
        except Exception:  # noqa: BLE001 -- unmeasurable ≠ zero, but we can only report a number
            logger.exception("overlap area could not be measured for %s", getattr(fi, "id", "?"))
            overlap_ha = 0.0
        overlapping.append(
            {
                "id": str(getattr(fi, "id", "")),
                "name": str(getattr(fi, "forest_name", getattr(fi, "name", "")) or ""),
                "name_np": str(getattr(fi, "name_np", "") or ""),
                "overlap_ha": round(overlap_ha, 4),
                "forest_area_ha": round(eg.area / SQM_PER_HA, 4),
            }
        )

    if clipped is None:
        return ResolutionResult(
            status="reject",
            reason="all_fragments_too_small",
            orig_area_ha=orig_area_ha,
            resolved_area_ha=0.0,
            removed_ha=orig_area_ha,
            removed_pct=100.0,
            overlapping_forests=overlapping,
        )

    resolved_area_ha = clipped.area / SQM_PER_HA
    removed_ha = orig_area_ha - resolved_area_ha
    removed_pct = (removed_ha / orig_area_ha) * 100 if orig_area_ha > 0 else 0.0
    resolved_ll = _proj(_to_deg, clipped)

    if removed_pct > params.reject_threshold_pct:
        reason = "overlap_too_large"
    elif resolved_area_ha < params.min_forest_ha:
        reason = "remaining_too_small"
    else:
        reason = None

    return ResolutionResult(
        status="reject" if reason else "acceptable",
        reason=reason,
        resolved=resolved_ll,
        orig_area_ha=orig_area_ha,
        resolved_area_ha=resolved_area_ha,
        removed_ha=removed_ha,
        removed_pct=removed_pct,
        requires_confirmation=removed_pct > params.confirmation_threshold_pct,
        overlapping_forests=overlapping,
    )


def clip_boundary_against_forests(proposed_geom: dict, existing_forests: list) -> dict:
    """Convenience for the write path: return the clipped 4326 geometry as GeoJSON.

    Raises ``ValueError`` when nothing survives the clip (fully inside existing
    forest land). Used by ``persist_boundary`` so import, edit and extend all
    clip identically.
    """
    res = resolve_overlap(proposed_geom, existing_forests)
    if res.resolved is None:
        raise ValueError("boundary is entirely within existing forest land")
    return mapping(res.resolved)
