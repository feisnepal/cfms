"""Feature geometry editing engine (Phase E-1) — shared validated pipeline.

Single source of truth for all feature geometry mutations in the map workspace
(vertex move/add/del, cut line, cut polygon, divide-equal-area, copy boundary,
delete guard).  Every stage is composable: it returns ``(geometry, warnings[])``
so stages are independently testable and the frontend gets stage-specific
feedback (CLIPPED_TO_BOUNDARY, SLIVER_REMOVED, TOPOLOGY_REJECTED, ...).

Architecture notes (IMPLEMENTATION_PLAN_FEATURE_EDITING.md):
  - R1  clip: block/compartment/sub-compartment/sub-areas edits that spill past
        the forest boundary are clipped to it (auto-clip + toast).
  - R2  divide: equal-area division only for
        {boundary, blocks, compartments, sub_compartments}.  Boundary division
        emits pieces stored as *blocks* (never multiple boundary records).
  - R6  no-gap/no-overlap: shared-vertex moves checked against neighbours via a
        spatial grid index (featureId → cells), NOT object identity — workspace
        layers are rebuilt from GeoJSON on every refresh (audit-fix #4).
  - review-fix #7: the shared-edge index is cached per (layer_type, geometryVersion)
        key for the request lifetime and invalidated on version bump.
  - review-fix #9: vertex-drag validation budgets ≤200ms p95 for ≤10k vertices;
        the bbox pre-filter runs before the grid build.
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
    mapping,
    shape as to_shapely,
)
from shapely.ops import split as shapely_split, unary_union
from shapely.validation import make_valid
from shapely.affinity import rotate as shapely_rotate

from ..core.constants import (
    DIVIDE_AREA_TOLERANCE_REL,
    MAX_EDGE_TOLERANCE_M,
    MIN_SLIVER_AREA_M2,
    MMU_HOLE_FILL_AREA_M2,
    SQM_PER_HA,
)
from ..utils.geometry_utils import calculate_area_geodesic_from_shapely
from ..services.file_processor import _metres_to_degrees

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Warnings protocol (mirrored in the editing router responses)
# ---------------------------------------------------------------------------
W_CLIPPED_TO_BOUNDARY = "CLIPPED_TO_BOUNDARY"
W_SLIVER_REMOVED = "SLIVER_REMOVED"
W_TOPOLOGY_REJECTED = "TOPOLOGY_REJECTED"
W_SELF_INTERSECTION_FIXED = "SELF_INTERSECTION_FIXED"
W_DIVIDE_TOLERANCE_EXCEEDED = "DIVIDE_TOLERANCE_EXCEEDED"
# exclude_geom (private land / protection units) split the parent into
# disconnected lobes; only the largest was divided.
W_DIVIDE_EXCLUSION_DISCONNECTED = "DIVIDE_EXCLUSION_DISCONNECTED"
# By-area division (area per piece): the fixing LAST piece (= the remainder)
# came out below the caller's minimum piece area, so it is kept as-is (it is the
# remainder by design) but the caller is warned.
W_DIVIDE_REMAINDER_SMALL = "DIVIDE_REMAINDER_SMALL"
W_HOLES_FILLED = "HOLES_FILLED"
# A merge whose plain union came out disconnected, but every selected feature
# genuinely touches another at ~zero distance (a single corner/point, not a
# real gap) -- fused with a tiny buffer round-trip instead of being rejected
# (user report, 2026-09-12). See editing.py::_union_geometries.
W_POINT_TOUCH_GLUED = "POINT_TOUCH_GLUED"

# Layers that may be divided into equal-area pieces (R2).
# FS-4a.5: sub_blocks joined the four structural layers — a leaf sub-block can
# self-divide in place exactly like blocks/compartment/sub-compartments.
DIVIDE_ALLOWED_LAYERS = frozenset({
    "boundary", "blocks", "sub_blocks", "compartments", "sub_compartments",
})

# Hard ceiling on how many pieces a single equal-area division may produce
# (user report, 2026-09-13: nothing capped `count`/`rows*cols`/`island_counts`,
# so an accidentally-huge entry — e.g. a typo, or `rows=cols=20` for the grid
# method's own UI max, giving 400 pieces — could hang the request on the
# per-piece shapely division/tolerance-check loop). Enforced at the single
# choke point every divide path funnels through (`divide_equal_area` /
# `divide_multipolygon_equal_area`), so it applies uniformly to boundary,
# blocks, compartments, sub-compartments, self-divide, and multi-island.
MAX_DIVIDE_PIECES = 20

# By-area divide (`divide_equal_area_by_area`): the remaining area may sit this
# far ABOVE the target before we decide it is still worth cutting another full
# piece. Each cut-position binary search is accurate to target*1e-3
# (`_find_equal_area_cut`) and that error ACCUMULATES over successive cuts
# (worst case ~19 full pieces × 0.1% ≈ 1.9%), so without a slop a mathematically
# clean split (total == k*target) drifts a couple of tenths of a percent and the
# loop cuts one piece too many, leaving a spurious sliver. Within this band the
# leftover IS the last piece (the remainder).
BY_AREA_STOP_REL = 0.02


def _check_divide_piece_cap(requested: int) -> None:
    if requested > MAX_DIVIDE_PIECES:
        # `MAX_PIECES:` prefix → resolve_service_detail() maps it to the
        # bilingual `editing.divide_too_many_pieces` template ({count},{max}).
        raise ValueError(
            f"MAX_PIECES: Cannot divide into {requested} pieces — the maximum is "
            f"{MAX_DIVIDE_PIECES} per division."
        )

# Layers whose edits are clipped against the forest boundary (R1).
# Rule (user 2026-08-10): blocks/compartments/sub_compartments/sub_areas can
# structurally NEVER exist outside the forest boundary, so their edits are ALWAYS
# clipped. Imported layers and all OTHER layers are NOT clipped — they may
# legally extend beyond the boundary.
CLIP_TO_BOUNDARY_LAYERS = frozenset({
    "blocks", "compartments", "sub_compartments", "sub_areas",
})


@dataclass
class GeometryEditResult:
    """Result of a validated geometry edit (kept shape for undo/refresh)."""
    geometry: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)
    removed_area_sqm: float = 0.0
    clipped: bool = False


# ---------------------------------------------------------------------------
# Geometry coercion
# ---------------------------------------------------------------------------

def as_shapely(g: Any):
    """Coerce WKB (geoalchemy2) / GeoJSON / WKT / Shapely into Shapely."""
    if g is None:
        return None
    if hasattr(g, "srid") and hasattr(g, "data"):  # geoalchemy2 WKB element
        from geoalchemy2.shape import to_shape
        return to_shape(g)
    if isinstance(g, (dict, str)):
        return to_shapely(g)
    return g


def area_sqm(geom: Any) -> float:
    """Geodesic area in m² for a Shapely geometry (degrees input)."""
    if geom is None or geom.is_empty:
        return 0.0
    try:
        sqm, _ = calculate_area_geodesic_from_shapely(geom)
        return float(sqm or 0.0)
    except Exception:
        # The fallback treats a degree as a fixed 111,320 m in BOTH axes. At
        # Nepal's latitudes a degree of longitude is about 12% shorter than
        # that, so the approximation overstates area by roughly the same.
        logger.warning(
            "geodesic area failed - falling back to a planar approximation "
            "that overstates area at Nepal's latitudes", exc_info=True,
        )
        try:
            return float(geom.area * (111_320.0 ** 2))
        except Exception:
            # POSTPONED 2026-08-25 (H3.4). This raised; it is back to returning
            # 0.0 at the user's request until H3.4 is retested. Re-enable with:
            #   raise ValueError(
            #       "The area of this geometry could not be computed by any "
            #       "method."
            #   )
            #
            # Why it is worth re-enabling: 0.0 is not a measurement, and callers
            # act on it destructively. `area_sqm(part) < min_area_sqm` DISCARDS
            # the part as a sliver; `area_sqm(remaining) / steps_left` makes the
            # equal-area target 0. The empty and None cases return 0.0 at the top
            # of this function, where zero is a fact rather than a guess — only
            # the impossible case reaches here. The log line below is what makes
            # that visible in the meantime.
            logger.error(
                "area could not be computed by any method for a %s - returning "
                "0.0, which is a fabricated value, not a measurement. Any block "
                "sized or split from it is wrong.",
                type(geom).__name__, exc_info=True,
            )
            return 0.0


# ---------------------------------------------------------------------------
# Stage 1 — sanitize
# ---------------------------------------------------------------------------

#: Layers whose geometry is legitimately a MultiPolygon of adjacent pieces, so a
#: cut's edge-sharing halves must NOT be collapsed back together. The user-group
#: extent is one stored row holding one MultiPolygon and is edited per island, so
#: splitting an island in two is a normal operation there - and the collapse it
#: used to suffer silently reverted every cut while returning 200 OK (P6 review,
#: 2026-09-28). Keyed by layer type so the structural layers, which rely on
#: ``make_valid`` to heal bow-ties and self-intersections, are untouched.
MULTIPART_LAYERS: frozenset = frozenset({"user_group"})


def _parts_only_touch(geom: Any) -> bool:
    """Do a MultiPolygon's parts share edges without overlapping in area?

    Edge-sharing members are what makes a MultiPolygon ``is_valid`` False, but
    they are not evidence of a self-intersection: cutting a polygon in two yields
    exactly that, and the two halves are the user's intent, not a defect to heal.
    Real self-intersection shows up as overlapping *area*, which is what this
    measures - summing the parts and comparing against their union.
    """
    if geom is None or geom.geom_type != "MultiPolygon":
        return False
    parts = list(geom.geoms)
    if len(parts) < 2:
        return False
    total = sum(p.area for p in parts)
    if total <= 0:
        return False
    try:
        union_area = unary_union(parts).area
    except Exception:  # noqa: BLE001 -- GEOS topological failure on the union; the caller heals
        return False
    return abs(total - union_area) <= 1e-9 * total


def sanitize_geometry(
    geom: Any, protect_geom: Any = None, preserve_touching_parts: bool = False
) -> Tuple[Any, List[str]]:
    """``make_valid`` a geometry, fixing self-intersections / bow-ties.

    Returns (sanitized_shapely, warnings[]).  Colour/dim carry-over: keeps
    the largest polygon part when make_valid emits a GeometryCollection.
    Also fills small interior holes (artifact voids from base.mmu) — UNLESS
    a hole materially overlaps ``protect_geom`` (G1, FS-4a.12: private land
    ∪ protection working-circle units), in which case the hole is genuine
    excluded ground, not an artifact, and is kept regardless of size.

    ``preserve_touching_parts`` keeps a MultiPolygon whose members merely share
    an edge instead of unioning it back into one piece. Without it, ``make_valid``
    turns a cut into a no-op: the pair is invalid, GEOS unions it, and the result
    is the polygon the user started with. Only layers in :data:`MULTIPART_LAYERS`
    pass it, and only genuinely-overlapping parts are still healed.
    """
    warnings: List[str] = []
    if isinstance(geom, (dict, str)):
        geom = to_shapely(geom)
    if geom is None or geom.is_empty:
        return geom, warnings
    if not geom.is_valid and not (preserve_touching_parts and _parts_only_touch(geom)):
        fixed = make_valid(geom)
        if isinstance(fixed, (Polygon, MultiPolygon, LineString, MultiLineString, Point)):
            geom = fixed
        elif hasattr(fixed, "geoms"):
            polys = [p for p in fixed.geoms if isinstance(p, (Polygon, MultiPolygon))]
            if polys:
                geom = max(polys, key=lambda p: p.area)
            else:
                lines = [l for l in fixed.geoms if isinstance(l, (LineString, MultiLineString))]
                geom = max(lines, key=lambda l: l.length) if lines else fixed
        else:
            geom = fixed
        warnings.append(W_SELF_INTERSECTION_FIXED)
    # Fill small artifact holes (base.mmu voids) — consistent with auto-block pipeline.
    geom, hole_warnings = _fill_holes(geom, protect_geom=protect_geom)
    warnings.extend(hole_warnings)
    return geom, warnings


#: Below this fraction of a hole's own area overlapping ``protect_geom``, the
#: overlap is treated as geometric noise (e.g. a hairline sliver from an
#: earlier make_valid pass) rather than a real excluded parcel sitting in
#: that hole.
_HOLE_PROTECT_OVERLAP_FRACTION: float = 0.5


def _hole_is_protected(hole_poly: Any, protect_geom: Any) -> bool:
    """Does ``hole_poly`` materially coincide with excluded ground (G1)?"""
    if protect_geom is None or protect_geom.is_empty:
        return False
    try:
        inter = hole_poly.intersection(protect_geom)
    except Exception:  # noqa: BLE001 -- an unreadable protect_geom must not crash hole-fill
        logger.warning("[hole-fill] protect_geom overlap check failed", exc_info=True)
        return False
    if inter is None or inter.is_empty:
        return False
    hole_area = area_sqm(hole_poly)
    if hole_area <= 0:
        return False
    return (area_sqm(inter) / hole_area) >= _HOLE_PROTECT_OVERLAP_FRACTION


def _fill_holes(
    geom: Any, hole_fill_area_m2: Optional[float] = None, protect_geom: Any = None
) -> Tuple[Any, List[str]]:
    """Fill interior holes (voids) smaller than ``hole_fill_area_m2`` —
    unless the hole is protected ground (G1: ``_hole_is_protected``), which
    is kept no matter how small.

    Returns (filled_shapely, warnings[]).  Applies to Polygon/MultiPolygon;
    other geometry types are returned unchanged.
    """
    warnings: List[str] = []
    if hole_fill_area_m2 is None:
        hole_fill_area_m2 = MMU_HOLE_FILL_AREA_M2

    if geom is None or geom.is_empty:
        return geom, warnings

    if isinstance(geom, Polygon):
        if geom.interiors:
            kept_interiors = []
            for interior in geom.interiors:
                hole_poly = Polygon(interior)
                if area_sqm(hole_poly) >= hole_fill_area_m2 or _hole_is_protected(
                    hole_poly, protect_geom
                ):
                    kept_interiors.append(interior)
            if len(kept_interiors) != len(geom.interiors):
                warnings.append(W_HOLES_FILLED)
            if kept_interiors:
                return Polygon(geom.exterior, kept_interiors), warnings
            else:
                return Polygon(geom.exterior), warnings
        return geom, warnings

    if isinstance(geom, MultiPolygon):
        new_parts = []
        any_filled = False
        for part in geom.geoms:
            if isinstance(part, Polygon) and part.interiors:
                kept_interiors = []
                for interior in part.interiors:
                    hole_poly = Polygon(interior)
                    if area_sqm(hole_poly) >= hole_fill_area_m2 or _hole_is_protected(
                        hole_poly, protect_geom
                    ):
                        kept_interiors.append(interior)
                if len(kept_interiors) != len(part.interiors):
                    any_filled = True
                if kept_interiors:
                    new_parts.append(Polygon(part.exterior, kept_interiors))
                else:
                    new_parts.append(Polygon(part.exterior))
            else:
                new_parts.append(part)
        if any_filled:
            warnings.append(W_HOLES_FILLED)
        return MultiPolygon(new_parts) if len(new_parts) > 1 else new_parts[0], warnings

    return geom, warnings


# ---------------------------------------------------------------------------
# Stage 2 — clip to forest boundary (R1)
# ---------------------------------------------------------------------------

def clip_to_region(
    geometry: Any,
    region_shapely: Any,
) -> Tuple[Optional[Any], bool, float]:
    """Clip ``geometry`` to ``region_shapely``.

    Returns (clipped_shapely_or_None, was_clipped, removed_area_sqm).
    ``None`` is returned when the intersection is empty (feature fully outside).
    ``was_clipped`` is True only when material content (>0.1%) was removed,
    driving the frontend "Clipped to boundary" toast (R1).
    """
    if region_shapely is None:
        return as_shapely(geometry), False, 0.0
    geom = as_shapely(geometry)
    if geom is None or geom.is_empty:
        return geom, False, 0.0
    try:
        clipped = region_shapely.intersection(geom)
    except Exception as e:
        logger.warning(f"[clip_to_region] intersection failed: {e}")
        return geom, False, 0.0
    if clipped.is_empty or (getattr(clipped, "area", 0) or 0) <= 1e-9:
        return None, True, area_sqm(geom)
    before = area_sqm(geom)
    after = area_sqm(clipped)
    removed = max(0.0, before - after)
    if before > 0 and (before - after) / before <= 0.001:
        return clipped, False, 0.0
    return clipped, True, removed


def boundary_region(calculation: Any):
    """Union of forest boundary (+ blocks) as one Shapely region (R1)."""
    from shapely.ops import unary_union
    parts = []
    boundary = getattr(calculation, "boundary_geom", None)
    if boundary is not None:
        try:
            parts.append(as_shapely(boundary))
        except Exception:
            logger.exception(
                "boundary part unreadable - it is left out of the union, which is "
                "then smaller than the real geometry"
            )
    if not parts:
        return None
    try:
        return unary_union([p for p in parts if p is not None and not p.is_empty])
    except Exception:
        # Returning parts[0] silently DISCARDS every other part, so a
        # multi-part boundary collapses to one piece of itself.
        logger.exception(
            "union of %d parts failed - falling back to the first part alone, "
            "discarding the rest", len(parts),
        )
        return parts[0]


def clip_to_forest_boundary(
    geometry: Any,
    calculation: Any,
) -> Tuple[Optional[Any], bool, float]:
    """R1: clip geometry to the union of the stored boundary.

    Generalises sub_area_service.clip_to_region to take the calculation so
    blocks/compartments/sub_compartments/sub_areas edits respect the shell.
    """
    region = boundary_region(calculation)
    if region is None:
        return as_shapely(geometry), False, 0.0
    return clip_to_region(geometry, region)


# ---------------------------------------------------------------------------
# Stage 3 — overlap detection (no-overlap rule)
# ---------------------------------------------------------------------------

def check_overlap(
    geometry: Any,
    others: List[Any],
    min_area_sqm: float = MIN_SLIVER_AREA_M2 * 0.05,
) -> List[str]:
    """Return warnings[] when ``geometry`` *materially* overlaps ``others``.

    Shared boundaries (adjacent) are the domain of the shared-edge index; a
    small epsilon keeps clean shared edges from being rejected.
    """
    geom = as_shapely(geometry)
    if geom is None or geom.is_empty:
        return []
    warnings: List[str] = []
    for other in others:
        o = as_shapely(other)
        if o is None or o.is_empty or not isinstance(o, (Polygon, MultiPolygon)):
            continue
        try:
            if not geom.intersects(o):
                continue
            inter_area = area_sqm(geom.intersection(o))
            if inter_area > min_area_sqm:
                warnings.append(W_TOPOLOGY_REJECTED)
                return warnings
        except Exception as e:
            logger.warning(f"[overlap] check failed: {e}")
            continue
    return warnings


# ---------------------------------------------------------------------------
# Stage 4 — shared-edge integrity (R6) with a spatial grid index
# ---------------------------------------------------------------------------

class SpatialHashIndex:
    """Grid index (featureId → cells) for neighbour lookup.

    Works on data (feature ids + bounding boxes), NOT object identity, because
    workspace layers are rebuilt from GeoJSON on every refresh (audit-fix #4).
    Built lazily per (layer_type, cfg) and cached for the request lifetime
    (review-fix #7); invalidated by the router whenever geometry_version bumps.
    """

    cell_deg = _metres_to_degrees(MAX_EDGE_TOLERANCE_M)

    def __init__(self, cells_deg: float = cell_deg):
        self.cells_deg = cells_deg
        self._cells: Dict[Tuple[int, int], Set[str]] = {}
        self._by_id: Dict[str, Any] = {}

    def insert(self, feature_id: str, geom: Any) -> None:
        g = as_shapely(geom)
        if g is None or g.is_empty:
            self._by_id[str(feature_id)] = g
            return
        self._by_id[str(feature_id)] = g
        for cell in self._cells_of(g):
            self._cells.setdefault(cell, set()).add(str(feature_id))

    def _cells_of(self, geom: Any):
        try:
            minx, miny, maxx, maxy = geom.bounds
        except Exception:
            logger.exception(
                "geometry bounds unreadable - no division lines can be proposed "
                "for it"
            )
            return []
        step = self.cells_deg
        if step <= 0:
            step = 1e-9
        cells = []
        for ix in range(int(minx / step), int(maxx / step) + 1):
            for iy in range(int(miny / step), int(maxy / step) + 1):
                cells.append((ix, iy))
        return cells

    def neighbor_candidates(self, geom: Any, exclude_id: Optional[str] = None) -> List[Any]:
        """Return neighbour geometries whose grid cell overlaps ``geometry``.

        This is the *candidate* set (bbox pre-filter).  The caller then runs the
        precise distance/area check against only these, so large layers never do
        a full scan per edit (perf budget, review-fix #9).
        """
        g = as_shapely(geom)
        if g is None or g.is_empty:
            return []
        cand_ids: Set[str] = set()
        for cell in self._cells_of(g):
            for fid in self._cells.get(cell, ()):
                if exclude_id is not None and str(fid) == str(exclude_id):
                    continue
                cand_ids.add(str(fid))
        return [self._by_id[fid] for fid in sorted(cand_ids) if self._by_id.get(fid) is not None]


def check_shared_edge_integrity(
    geometry: Any,
    neighbours: List[Any],
) -> Tuple[bool, List[str]]:
    """No-gap/no-overlap for adjacent polygons on shared-vertex moves (R6).

    Validates against a bounded candidate set (from SpatialHashIndex) rather
    than a full-layer scan.  Returns (is_valid, warnings[]).
    """
    geom = as_shapely(geometry)
    if geom is None or geom.is_empty:
        return True, []
    tol_deg = _metres_to_degrees(MAX_EDGE_TOLERANCE_M)
    for neighbor in neighbours:
        if neighbor is None:
            continue
        try:
            if not geom.intersects(neighbor):
                if geom.distance(neighbor) > tol_deg:
                    return False, [W_TOPOLOGY_REJECTED]
                continue
            inter_area = area_sqm(geom.intersection(neighbor))
            if inter_area > MIN_SLIVER_AREA_M2 * 0.05:
                return False, [W_TOPOLOGY_REJECTED]
        except Exception as e:
            logger.debug(f"[shared-edge] neighbour check skipped: {e}")
            continue
    return True, []


# ---------------------------------------------------------------------------
# Stage 5 — orchestrator
# ---------------------------------------------------------------------------

def validate_geometry_edit(
    geometry: Dict[str, Any],
    layer_type: str,
    calculation: Any,
    existing_features: List[Dict[str, Any]],
    feature_id: Optional[str] = None,
    index: Optional[SpatialHashIndex] = None,
) -> GeometryEditResult:
    """sanitize → clip → overlap → shared-edge.  Returns final GeoJSON."""

    geom, warnings = sanitize_geometry(
        geometry, preserve_touching_parts=layer_type in MULTIPART_LAYERS
    )

    # R1 clip
    clipped = geom
    removed = 0.0
    clipped_flag = False
    if layer_type in CLIP_TO_BOUNDARY_LAYERS:
        clips, was_clipped, removed = clip_to_forest_boundary(geom, calculation)
        if was_clipped:
            warnings.append(W_CLIPPED_TO_BOUNDARY)
            clipped_flag = True
        if clips is None:
            # Structural layers (blocks/compartments/sub_compartments/sub_areas)
            # cannot exist outside the forest boundary: an edit that intersects
            # nothing inside the boundary is REJECTED rather than stored as-is.
            clipped_flag = True
            return GeometryEditResult(
                geometry=mapping(geom),
                warnings=list(dict.fromkeys([*warnings, W_TOPOLOGY_REJECTED])),
                clipped=clipped_flag,
                removed_area_sqm=removed,
            )
        if clips is not None:
            clipped = clips

    # overlap against other same-layer features
    others = [
        f.get("geometry") for f in existing_features
        if str(f.get("id")) != str(feature_id) and f.get("geometry") is not None
    ]
    overlap_w = check_overlap(clipped, others)
    warnings.extend(overlap_w)

    # shared-edge movement (R6) via the bounded candidate set
    if index is not None:
        neighbours = index.neighbor_candidates(clipped, exclude_id=feature_id)
    else:
        neighbours = [
            as_shapely(f.get("geometry")) for f in existing_features
            if str(f.get("id")) != str(feature_id) and f.get("geometry") is not None
        ]
    valid, se_w = check_shared_edge_integrity(clipped, neighbours)
    warnings.extend(se_w)

    return GeometryEditResult(
        geometry=mapping(clipped),
        warnings=list(dict.fromkeys(warnings)),
        clipped=clipped_flag,
        removed_area_sqm=removed,
    )


# ---------------------------------------------------------------------------
# Stage 6 — cut_line / cut_polygon
# ---------------------------------------------------------------------------

def _extend_cut_line_ends(poly: Any, line: LineString) -> LineString:
    """Extend both ends of a (possibly multi-point / zig-zag) cut line so the
    line reliably pierces the polygon's bounding box from edge to edge.

    Multi-point cuts must preserve every interior vertex exactly as drawn; only
    the first and last segments are extrapolated outward along their own
    direction (mirrors the legacy MapSplitDrawer ``extendCutLine``).
    """
    minx, miny, maxx, maxy = poly.bounds
    pad = max(maxx - minx, maxy - miny) * 2.0 + 1e-6
    coords = list(line.coords)
    out: List[tuple] = []
    n = len(coords)
    if n == 1:
        return line
    p0, p1 = coords[0], coords[1]
    dx, dy = p0[0] - p1[0], p0[1] - p1[1]
    mag = (dx * dx + dy * dy) ** 0.5
    if mag > 1e-12:
        out.append((p0[0] + dx / mag * pad, p0[1] + dy / mag * pad))
    else:
        out.append((p0[0] + pad, p0[1]))
    out.extend(coords[1:-1])
    pn, pm = coords[-1], coords[-2]
    dx, dy = pn[0] - pm[0], pn[1] - pm[1]
    mag = (dx * dx + dy * dy) ** 0.5
    if mag > 1e-12:
        out.append((pn[0] + dx / mag * pad, pn[1] + dy / mag * pad))
    else:
        out.append((pn[0] + pad, pn[1]))
    return LineString(out)


def cut_polygon(polygon: Any, cut_line_geom: Any, min_area_sqm: float = MIN_SLIVER_AREA_M2) -> Tuple[List[Any], List[str]]:
    """Split a polygon with a LineString; drop slivers below ``min_area_sqm``.

    The cut line is end-extended beyond the polygon's bounding box so that
    multi-point / zig-zag cuts drawn wholly inside the polygon still split it
    cleanly from edge to edge.  Shapely ``split`` can emit GeometryCollection
    artifacts — post-process each part (make_valid) and discard pieces that
    are too small to matter.
    """
    poly, warnings = sanitize_geometry(polygon)
    line = as_shapely(cut_line_geom)
    if not isinstance(line, LineString) or line.is_empty:
        raise ValueError("cut_line must be a non-empty LineString")
    if isinstance(line, LineString) and len(line.coords) >= 2:
        line = _extend_cut_line_ends(poly, line)
    try:
        result = shapely_split(poly, line)
    except Exception as e:
        raise ValueError(f"Split failed: {e}") from e
    pieces: List[Any] = []
    sliver_count = 0
    for part in getattr(result, "geoms", [result]):
        part, _w = sanitize_geometry(part)
        if isinstance(part, MultiPolygon):
            for sub in part.geoms:
                if area_sqm(sub) < min_area_sqm:
                    sliver_count += 1
                else:
                    pieces.append(sub)
        elif isinstance(part, Polygon):
            if area_sqm(part) < min_area_sqm:
                sliver_count += 1
            else:
                pieces.append(part)
    warnings = [W_SLIVER_REMOVED] if sliver_count else []
    return pieces, warnings


def cut_line(geometry: Any, split_point) -> Tuple[List[Any], List[str]]:
    """Split a LineString / Polyline at a split point.

    The point is snapped to the closest point on the line when slightly off.
    Returns (pieces, warnings[]).
    """
    geom = as_shapely(geometry)
    if not isinstance(geom, (LineString, MultiLineString)):
        raise ValueError("cut-line requires a LineString geometry")
    if isinstance(geom, MultiLineString):
        if len(geom.geoms) != 1:
            raise ValueError("cut-line requires a single LineString for multi-part lines")
        geom = geom.geoms[0]
    p = as_shapely(split_point)
    if isinstance(p, LineString):
        # caller passed a cutting polyline — use its midpoint-ish? keep first point
        p = Point(p.coords[0])
    if not isinstance(p, Point):
        p = Point(*p) if isinstance(split_point, (tuple, list)) else Point(split_point)
    if geom.distance(p) > 1e-9:
        if geom.is_empty:
            raise ValueError("line is empty — cannot cut")
        p = geom.interpolate(geom.project(p))
    try:
        result = shapely_split(geom, p)
    except Exception as e:
        raise ValueError(f"cut-line split failed: {e}") from e
    parts: List[Any] = [
        g for g in getattr(result, "geoms", [result])
        if isinstance(g, (LineString, MultiLineString)) and not g.is_empty
    ]
    flat: List[Any] = []
    for part in parts:
        if isinstance(part, MultiLineString):
            flat.extend(list(part.geoms))
        else:
            flat.append(part)
    return flat, [W_SLIVER_REMOVED] if len(flat) < 2 else []


# ---------------------------------------------------------------------------
# Stage 7 — equal-area division (D3), generic strips + grid
# ---------------------------------------------------------------------------

def _make_cut_pad_line(bounds: Tuple[float, float, float, float], pos: float, direction: str) -> LineString:
    minx, miny, maxx, maxy = bounds
    pad = (maxx - minx + maxy - miny) * 0.5 + 1e-6
    if direction in ("vertical", "E-W"):
        return LineString([(pos, miny - pad), (pos, maxy + pad)])
    return LineString([(minx - pad, pos), (maxx + pad, pos)])


def _find_equal_area_cut(polygon: Any, target_sqm: float, direction: str) -> Optional[float]:
    """Binary-search the cut coordinate that isolates ``target_sqm`` on one side."""
    minx, miny, maxx, maxy = polygon.bounds
    lo, hi = (minx, maxx) if direction in ("vertical", "E-W") else (miny, maxy)
    if hi - lo < 1e-10:
        return None
    tolerance = max(target_sqm * 1e-3, 1e-6)
    best = None
    for _ in range(48):
        mid = (lo + hi) / 2
        side = _equal_area_side(polygon, mid, direction)
        if side is None:
            return best
        diff = side - target_sqm
        if abs(diff) <= tolerance:
            return mid
        best = mid
        if diff > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _equal_area_side(geom: Any, pos: float, direction: str) -> Optional[float]:
    cut = _make_cut_pad_line(geom.bounds, pos, direction)
    try:
        res = shapely_split(geom, cut)
        total = 0.0
        for g in getattr(res, "geoms", [geom]):
            if isinstance(g, MultiPolygon):
                gs = list(g.geoms)
            else:
                gs = [g]
            for gg in gs:
                if not isinstance(gg, Polygon) or gg.is_empty:
                    continue
                if direction in ("vertical", "E-W"):
                    if gg.centroid.x <= pos:
                        total += area_sqm(gg)
                else:
                    if gg.centroid.y <= pos:
                        total += area_sqm(gg)
        return total
    except Exception:
        logger.exception(
            "trial split at %s failed - this position is treated as having no "
            "area, which biases the equal-area search away from it", pos,
        )
        return None


def equal_area_strips(
    polygon: Any,
    n: int,
    direction: str = "vertical",
    direction_angle: Optional[float] = None,
    protect_geom: Any = None,
) -> List[Polygon]:
    """Split polygon into ``n`` equal-area strips (generalised from CompartmentSplitter).

    ``direction_angle`` (degrees, legacy convention: 0=N-S, 90=E-W) rotates the
    polygon to that orientation, splits into vertical strips in rotated space and
    rotates the pieces back — so arbitrary split angles are supported.

    ``protect_geom`` (G1, FS-4a.12) — this function re-sanitizes its OWN input
    (``divide_equal_area`` already sanitized once, but ``equal_area_strips``/
    ``equal_area_grid`` are also called directly elsewhere) — without
    threading ``protect_geom`` here too, a private-land hole that survived
    the CALLER's sanitize step would be silently re-filled by THIS one,
    right before the actual cut. Found by test, not by inspection: a
    forest-boundary-minus-private-land polygon divided by
    ``divide_equal_area(..., protect_geom=...)`` still re-absorbed the hole,
    because only the outer sanitize call had been fixed.
    """
    geom = as_shapely(polygon)
    geom, _ = sanitize_geometry(geom, protect_geom=protect_geom)
    if n <= 0:
        raise ValueError("n must be at least 1")
    if n == 1:
        return [geom]
    if direction_angle is not None:
        centroid = geom.centroid
        rotated = shapely_rotate(geom, -direction_angle, origin=centroid, use_radians=False)
        rotated_protect = (
            shapely_rotate(as_shapely(protect_geom), -direction_angle, origin=centroid, use_radians=False)
            if protect_geom is not None
            else None
        )
        rotated_pieces = equal_area_strips(rotated, n, "vertical", protect_geom=rotated_protect)
        return [
            shapely_rotate(p, direction_angle, origin=centroid, use_radians=False)
            for p in rotated_pieces
        ]
    remaining = geom
    parts: List[Polygon] = []
    for i in range(n - 1):
        steps_left = n - i
        target = area_sqm(remaining) / steps_left
        pos = _find_equal_area_cut(remaining, target, direction)
        if pos is None:
            parts.append(remaining)
            break
        cut = _make_cut_pad_line(remaining.bounds, pos, direction)
        try:
            res = shapely_split(remaining, cut)
            gs = [
                g for g in getattr(res, "geoms", [])
                if isinstance(g, Polygon) and not g.is_empty and g.area > 0
            ]
        except Exception as e:
            logger.warning(f"[equal-area] split failed at iter {i}: {e}")
            parts.append(remaining)
            break
        if len(gs) < 2:
            parts.append(remaining)
            break
        gs.sort(
            key=lambda c: (c.centroid.x, c.centroid.y)
            if direction in ("vertical", "E-W")
            else (c.centroid.y, c.centroid.x)
        )
        parts.append(gs[0])
        rest = unary_union(gs[1:])
        if isinstance(rest, MultiPolygon):
            rest = max(rest.geoms, key=lambda p: p.area)
        remaining = rest
    parts.append(remaining)
    return [p for p in parts if p is not None and not p.is_empty]


def equal_area_grid(
    polygon: Any, rows: int, cols: int, protect_geom: Any = None
) -> List[Polygon]:
    """Split polygon into rows × cols **equal-area** cells.

    Unlike legacy cell-clipping (which yields wildly unequal cells on irregular
    shapes and fails the ±5% tolerance), this first divides the polygon into
    ``rows`` equal-area horizontal strips, then divides each strip into ``cols``
    equal-area vertical sub-strips — so every cell has area total/(rows*cols)
    within the same tolerance as the strips algorithm.

    ``protect_geom`` (G1, FS-4a.12) — see :func:`equal_area_strips`.
    """
    if rows < 1 or cols < 1:
        raise ValueError("rows and cols must be >= 1")
    geom = as_shapely(polygon)
    geom, _ = sanitize_geometry(geom, protect_geom=protect_geom)
    if rows * cols == 1:
        return [geom]
    cells: List[Polygon] = []
    for strip in equal_area_strips(geom, rows, "horizontal", protect_geom=protect_geom):
        cells.extend(equal_area_strips(strip, cols, "vertical", protect_geom=protect_geom))
    cells.sort(key=lambda c: (c.centroid.y, c.centroid.x))
    return cells


def divide_equal_area(
    polygon: Any,
    layer_type: str = "blocks",
    method: str = "strips",
    n: int = 2,
    direction: str = "vertical",
    rows: int = 2,
    cols: int = 2,
    min_area_sqm: float = MIN_SLIVER_AREA_M2,
    direction_angle: Optional[float] = None,
    exclude_geom: Any = None,
    protect_geom: Any = None,
) -> Tuple[List[Polygon], List[str]]:
    """Equal-area division (R2 / D3).

    Returns (pieces, warnings[]).  Raises ValueError when the layer is not in
    DIVIDE_ALLOWED_LAYERS or when method is unknown.  When any produced piece
    deviates > DIVIDE_AREA_TOLERANCE_REL from the target, fails gracefully by
    returning ([], [W_DIVIDE_TOLERANCE_EXCEEDED]) so the router never persists
    a wildly uneven split (D3).

    ``exclude_geom`` (PROTECTION_WORKING_CIRCLE_PLAN.md P2) — union of private
    land + protection working-circle units. It is punched out of ``polygon``
    before dividing, so "equal area" means equal *net manageable* area and the
    exclusions become permanent holes. If it disconnects the parent, only the
    largest lobe is divided and ``W_DIVIDE_EXCLUSION_DISCONNECTED`` is returned.
    A produced piece below ``min_area_sqm`` is merged into its nearest kept
    neighbour rather than dropped.

    ``protect_geom`` (G1, FS-4a.12) — the SAME private-land/protection union,
    passed separately because ``polygon`` itself can ALREADY carry a
    private-land-shaped hole (a root divide's ``polygon`` is P3a-1's
    ``forest_area_geom``, boundary-minus-private-land, D8) — this stops the
    sanitize step below from silently "hole-filling" (re-absorbing) that
    excluded land just because the parcel is smaller than the MMU artifact
    threshold. When omitted, ``exclude_geom`` itself is used (it is at least
    the protection-unit half of the union, and costs nothing extra to pass).
    """
    if layer_type not in DIVIDE_ALLOWED_LAYERS:
        raise ValueError(f"Divide-equal-area is not allowed for layer '{layer_type}' (R2)")

    _protect = as_shapely(protect_geom) if protect_geom is not None else as_shapely(exclude_geom)
    geom = as_shapely(polygon)
    geom, _ = sanitize_geometry(geom, protect_geom=_protect)
    if geom is None or geom.is_empty or not isinstance(geom, Polygon):
        raise ValueError("divide-equal-area requires a Polygon geometry")

    warnings: List[str] = []
    if exclude_geom is not None:
        ex = as_shapely(exclude_geom)
        if ex is not None and not ex.is_empty:
            net = geom.difference(ex)
            if net.is_empty:
                raise ValueError(
                    "nothing left to divide after excluding private land / protection units"
                )
            if isinstance(net, MultiPolygon):
                net = max(net.geoms, key=lambda p: p.area)
                warnings.append(W_DIVIDE_EXCLUSION_DISCONNECTED)
            if not isinstance(net, Polygon) or net.is_empty:
                raise ValueError("net geometry after exclusion is not divisible")
            geom = net  # a Polygon, possibly with holes — .area is net of holes

    total_area = area_sqm(geom)  # already net (geodesic area discounts holes)
    if method == "strips":
        _check_divide_piece_cap(int(n or 0))
        pieces = equal_area_strips(geom, n, direction, direction_angle=direction_angle, protect_geom=_protect)
        target = total_area / n
    elif method == "grid":
        _check_divide_piece_cap(max(1, int(rows or 0)) * max(1, int(cols or 0)))
        pieces = equal_area_grid(geom, rows, cols, protect_geom=_protect)
        target = total_area / max(1, rows * cols)
    else:
        raise ValueError(f"unknown divide method: {method}")

    keep = [p for p in pieces if area_sqm(p) >= min_area_sqm]
    dropped = [p for p in pieces if area_sqm(p) < min_area_sqm and not p.is_empty]
    if dropped and keep:
        for d in dropped:
            j = min(range(len(keep)), key=lambda k: keep[k].distance(d))
            merged = unary_union([keep[j], d])
            if isinstance(merged, Polygon) and not merged.is_empty:
                keep[j] = merged

    if any(abs(area_sqm(p) - target) / max(target, 1.0) > DIVIDE_AREA_TOLERANCE_REL for p in keep):
        logger.warning(
            f"[divide_equal_area] {len(keep)} pieces violate ±{DIVIDE_AREA_TOLERANCE_REL:.1%} tolerance — rejecting"
        )
        return [], [W_DIVIDE_TOLERANCE_EXCEEDED]
    return keep, warnings


def divide_multipolygon_equal_area(
    multipolygon: Any,
    counts: Sequence[int],
    layer_type: str = "compartments",
    method: str = "strips",
    direction: str = "vertical",
    rows: int = 2,
    cols: int = 2,
    min_area_sqm: float = MIN_SLIVER_AREA_M2,
    direction_angle: Optional[float] = None,
    exclude_geom: Any = None,
    protect_geom: Any = None,
) -> Tuple[List[Polygon], List[str]]:
    """Equal-area division of a **multi-island** parent (MULTI_ISLAND_DIVIDE_PLAN.md).

    A compartment never spans two detached parcels, so each polygon part is
    divided on its own by :func:`divide_equal_area` into ``counts[i]`` pieces
    and the results are concatenated **in part order**. ``counts`` must have one
    entry per part; an entry ``<= 1`` still round-trips the part through
    ``divide_equal_area`` (n is floored at 1) so ``exclude_geom`` is honoured
    even for an undivided island.

    ``protect_geom`` (G1, FS-4a.12) — see :func:`divide_equal_area`; threaded
    through both the outer sanitize step and every per-island call below.

    If any part fails the ±tolerance check, the whole division is rejected
    (``[], [W_DIVIDE_TOLERANCE_EXCEEDED]``) — same contract as the single-Polygon
    path; the caller adjusts the per-island counts. Other warnings are collected
    across parts, de-duplicated, order preserved.
    """
    _protect = as_shapely(protect_geom) if protect_geom is not None else as_shapely(exclude_geom)
    geom = as_shapely(multipolygon)
    geom, _ = sanitize_geometry(geom, protect_geom=_protect)
    if geom is None or geom.is_empty:
        raise ValueError("divide-multipolygon-equal-area requires a non-empty geometry")

    parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    parts = [p for p in parts if isinstance(p, Polygon) and not p.is_empty]
    if not parts:
        raise ValueError("divide-multipolygon-equal-area found no polygon parts")
    if len(counts) != len(parts):
        raise ValueError(
            f"counts has {len(counts)} entries but the boundary has {len(parts)} parts"
        )

    # Total across every island, not just per-part — `divide_equal_area`'s own
    # cap check below only sees one island's share at a time, which could
    # each individually be under the ceiling while the sum (what actually
    # gets persisted/rendered) is not. The grid method applies the same
    # rows x cols to every part regardless of `counts` (see divide_equal_area
    # above), so its true total is len(parts) * rows * cols.
    total_requested = (
        len(parts) * max(1, int(rows or 0)) * max(1, int(cols or 0))
        if method == "grid"
        else sum(max(1, int(c)) for c in counts)
    )
    _check_divide_piece_cap(total_requested)

    all_pieces: List[Polygon] = []
    warnings: List[str] = []
    for part, c in zip(parts, counts):
        sub, w = divide_equal_area(
            part,
            layer_type=layer_type,
            method=method,
            n=max(1, int(c)),
            direction=direction,
            rows=rows,
            cols=cols,
            min_area_sqm=min_area_sqm,
            direction_angle=direction_angle,
            exclude_geom=exclude_geom,
            protect_geom=_protect,
        )
        if W_DIVIDE_TOLERANCE_EXCEEDED in w:
            return [], [W_DIVIDE_TOLERANCE_EXCEEDED]
        all_pieces.extend(sub)
        for x in w:
            if x not in warnings:
                warnings.append(x)

    if len(all_pieces) < 2:
        return [], [W_DIVIDE_TOLERANCE_EXCEEDED]
    return all_pieces, warnings


def divide_equal_area_by_area(
    polygon: Any,
    target_sqm: float,
    layer_type: str = "blocks",
    direction: str = "vertical",
    min_area_sqm: float = MIN_SLIVER_AREA_M2,
    direction_angle: Optional[float] = None,
    exclude_geom: Any = None,
    protect_geom: Any = None,
) -> Tuple[List[Polygon], List[str]]:
    """Equal-area division by a **per-piece target area** (user 2026-09-13).

    Instead of the caller choosing the piece *count*, they choose the area each
    piece should have. The first pieces each come out at ~``target_sqm``; the
    LAST piece is whatever is left over — the **remainder** — which is smaller
    than the target by design (and is therefore exempt from the ±5% tolerance
    check that :func:`divide_equal_area` applies to every piece).

    Returns ``(pieces, warnings)``. Raises ValueError with an i18n-prefixed
    message when ``target_sqm`` is not positive, the geometry is not a Polygon,
    ``target_sqm >=`` total area, ``target_sqm < min_area_sqm``, fewer than 2
    pieces result, or the resulting piece count exceeds MAX_DIVIDE_PIECES.
    A remainder below ``min_area_sqm`` is kept (it is the requested remainder)
    and signalled with ``W_DIVIDE_REMAINDER_SMALL``.

    ``protect_geom`` (G1, FS-4a.12) — see :func:`divide_equal_area`; same
    "don't hole-fill excluded ground" guard, defaults to ``exclude_geom``.
    """
    if target_sqm <= 0:
        raise ValueError("per-piece area must be positive")
    if layer_type not in DIVIDE_ALLOWED_LAYERS:
        raise ValueError(f"Divide-equal-area is not allowed for layer '{layer_type}' (R2)")

    geom = as_shapely(polygon)
    geom, _ = sanitize_geometry(
        geom, protect_geom=as_shapely(protect_geom) if protect_geom is not None else as_shapely(exclude_geom)
    )
    if geom is None or geom.is_empty or not isinstance(geom, Polygon):
        raise ValueError("divide-equal-area-by-area requires a Polygon geometry")

    warnings: List[str] = []
    if exclude_geom is not None:
        ex = as_shapely(exclude_geom)
        if ex is not None and not ex.is_empty:
            net = geom.difference(ex)
            if net.is_empty:
                raise ValueError(
                    "nothing left to divide after excluding private land / protection units"
                )
            if isinstance(net, MultiPolygon):
                net = max(net.geoms, key=lambda p: p.area)
                warnings.append(W_DIVIDE_EXCLUSION_DISCONNECTED)
            if not isinstance(net, Polygon) or net.is_empty:
                raise ValueError("net geometry after exclusion is not divisible")
            geom = net

    total_area = area_sqm(geom)
    if total_area <= 0:
        raise ValueError("divide-equal-area-by-area: parent has no measurable area")
    if target_sqm >= total_area:
        raise ValueError(
            "PIECE_AREA_TOO_LARGE: per-piece area must be smaller than the total area"
        )
    if target_sqm < min_area_sqm:
        raise ValueError(
            f"PIECE_AREA_TOO_SMALL: per-piece area below the minimum of "
            f"{min_area_sqm / SQM_PER_HA:.2f} ha"
        )

    full_count = int(total_area // target_sqm)
    remainder_area = total_area - full_count * target_sqm
    n_pieces = full_count + (1 if remainder_area > 1e-6 else 0)
    if n_pieces < 2:
        raise ValueError(
            "PIECE_AREA_SPLIT_FAILED: this piece area leaves fewer than 2 pieces"
        )
    _check_divide_piece_cap(n_pieces)

    if direction_angle is not None:
        centroid = geom.centroid
        rotated = shapely_rotate(geom, -direction_angle, origin=centroid, use_radians=False)
        rotated_pieces, _rotated_warnings = divide_equal_area_by_area(
            rotated,
            target_sqm,
            layer_type=layer_type,
            direction="vertical",
            min_area_sqm=min_area_sqm,
            direction_angle=None,
            exclude_geom=exclude_geom,
            protect_geom=protect_geom,
        )
        # `warnings` (this frame) already carries W_DIVIDE_EXCLUSION_DISCONNECTED
        # if the exclusion disconnected the parent; the recursive call's warnings
        # are a subset of it.
        pieces = [
            shapely_rotate(p, direction_angle, origin=centroid, use_radians=False)
            for p in rotated_pieces
        ]
        return pieces, warnings

    remaining = geom
    pieces: List[Polygon] = []
    # Cut at most `full_count` full pieces, but STOP as soon as what is left is
    # already ~target or smaller — otherwise the cut-by-cut geodesic drift would
    # over-cut a clean division (total == k*target) and leave a sliver as a
    # spurious last piece.
    for _ in range(full_count):
        if area_sqm(remaining) <= target_sqm * (1.0 + BY_AREA_STOP_REL):
            break
        pos = _find_equal_area_cut(remaining, target_sqm, direction)
        if pos is None:
            break
        cut = _make_cut_pad_line(remaining.bounds, pos, direction)
        try:
            res = shapely_split(remaining, cut)
            gs = [
                g for g in getattr(res, "geoms", [])
                if isinstance(g, Polygon) and not g.is_empty and g.area > 0
            ]
        except Exception as e:
            logger.warning(f"[equal-area-by-area] split failed at iter: {e}")
            break
        if len(gs) < 2:
            break
        gs.sort(
            key=lambda c: (c.centroid.x, c.centroid.y)
            if direction in ("vertical", "E-W")
            else (c.centroid.y, c.centroid.x)
        )
        pieces.append(gs[0])
        rest = unary_union(gs[1:])
        if isinstance(rest, MultiPolygon):
            rest = max(rest.geoms, key=lambda p: p.area)
        remaining = rest

    if remaining is not None and not remaining.is_empty:
        pieces.append(remaining)  # the remainder — always kept as the last piece

    if len(pieces) < 2:
        raise ValueError(
            "PIECE_AREA_SPLIT_FAILED: this piece area leaves fewer than 2 pieces"
        )

    # The ±5% tolerance applies to the FULL pieces only — the last piece is the
    # remainder by design, so it cannot be compared to the target.
    for p in pieces[:-1]:
        if abs(area_sqm(p) - target_sqm) / target_sqm > DIVIDE_AREA_TOLERANCE_REL:
            logger.warning(
                f"[divide_equal_area_by_area] a piece violates ±{DIVIDE_AREA_TOLERANCE_REL:.1%} tolerance — rejecting"
            )
            return [], [W_DIVIDE_TOLERANCE_EXCEEDED]
    if area_sqm(pieces[-1]) < min_area_sqm:
        warnings.append(W_DIVIDE_REMAINDER_SMALL)
    return pieces, warnings


def divide_multipolygon_equal_area_by_area(
    multipolygon: Any,
    target_sqm: float,
    layer_type: str = "compartments",
    direction: str = "vertical",
    min_area_sqm: float = MIN_SLIVER_AREA_M2,
    direction_angle: Optional[float] = None,
    exclude_geom: Any = None,
    protect_geom: Any = None,
) -> Tuple[List[Polygon], List[str]]:
    """By-area division of a **multi-island** parent.

    Each parcel is divided on its own by :func:`divide_equal_area_by_area`
    (so every parcel keeps its own last-piece remainder — a compartment never
    spans two detached parcels). The total piece count is capped before any
    division work runs, so per-parcel shares cannot sum past MAX_DIVIDE_PIECES.

    If any part fails the ±tolerance check, the whole division is rejected
    (``[], [W_DIVIDE_TOLERANCE_EXCEEDED]``) — same contract as the count-based
    multi path.

    ``protect_geom`` (G1, FS-4a.12) — see :func:`divide_equal_area`.
    """
    _protect = as_shapely(protect_geom) if protect_geom is not None else as_shapely(exclude_geom)
    geom = as_shapely(multipolygon)
    geom, _ = sanitize_geometry(geom, protect_geom=_protect)
    if geom is None or geom.is_empty:
        raise ValueError("divide-multipolygon-equal-area-by-area requires a non-empty geometry")

    parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    parts = [p for p in parts if isinstance(p, Polygon) and not p.is_empty]
    if not parts:
        raise ValueError("divide-multipolygon-equal-area-by-area found no polygon parts")

    per_part: List[int] = []
    total_requested = 0
    for p in parts:
        tot = area_sqm(p)
        full = int(tot // target_sqm)
        rem = tot - full * target_sqm
        n = full + (1 if rem > 1e-6 else 0)
        per_part.append(max(1, n))
        total_requested += max(1, n)
    _check_divide_piece_cap(total_requested)

    all_pieces: List[Polygon] = []
    warnings: List[str] = []
    for part, n in zip(parts, per_part):
        if n < 2:
            pieces = [part]  # parcel too small for one full piece → kept whole
            w: List[str] = []
            if area_sqm(part) < min_area_sqm:
                w.append(W_DIVIDE_REMAINDER_SMALL)
        else:
            pieces, w = divide_equal_area_by_area(
                part,
                target_sqm,
                layer_type=layer_type,
                direction=direction,
                min_area_sqm=min_area_sqm,
                direction_angle=direction_angle,
                exclude_geom=exclude_geom,
                protect_geom=_protect,
            )
        if W_DIVIDE_TOLERANCE_EXCEEDED in w:
            return [], [W_DIVIDE_TOLERANCE_EXCEEDED]
        all_pieces.extend(pieces)
        for x in w:
            if x not in warnings:
                warnings.append(x)

    if len(all_pieces) < 2:
        return [], [W_DIVIDE_TOLERANCE_EXCEEDED]
    return all_pieces, warnings


def divide_boundary_into_blocks(
    boundary_geom: Any,
    method: str = "strips",
    n: int = 2,
    direction: str = "vertical",
    rows: int = 2,
    cols: int = 2,
) -> Tuple[List[Polygon], List[str]]:
    """Boundary divide → pieces to be stored as blocks (user-confirmed R2).

    The boundary record itself is never replaced by many; callers persist the
    returned pieces via the block storage path.
    """
    return divide_equal_area(
        boundary_geom,
        method=method,
        n=n,
        direction=direction,
        rows=rows,
        cols=cols,
        layer_type="boundary",
    )


# ---------------------------------------------------------------------------
# copy_boundary_to_block (D4)
# ---------------------------------------------------------------------------

def clone_boundary_to_block_spec(calculation: Any, name: str = "Boundary Copy") -> Optional[Tuple[Any, dict]]:
    """Compute the geometry + attrs of the boundary copy (persist in router).

    Returns (shapely_geometry, attrs) or None when the calculation has no boundary.
    """
    boundary = getattr(calculation, "boundary_geom", None)
    if boundary is None:
        return None
    geom = as_shapely(boundary)
    geom, _ = sanitize_geometry(geom)
    sqm = area_sqm(geom)
    return geom, {
        "name": name,
        "area_sqm": float(sqm),
        "area_hectares": round(sqm / SQM_PER_HA, 4),
    }


def next_block_index(db, calculation_id) -> int:
    from sqlalchemy import func
    from ..models.forest_block import ForestBlock
    pid = db.query(func.max(ForestBlock.index)).filter(
        ForestBlock.calculation_id == calculation_id
    ).scalar()
    return int(pid or -1) + 1


def bump_geometry_version(calculation) -> None:
    """Bump the optimistic-lock clock (U02/A.5); invalidates spatial cache key."""
    calculation.geometry_version = (getattr(calculation, "geometry_version", 0) or 0) + 1


# ---------------------------------------------------------------------------
# delete guard (R4 + R5 independence)
# ---------------------------------------------------------------------------

def check_delete_guard(
    db,
    calculation,
    layer_type: str,
    feature_id: str,
) -> Dict[str, Any]:
    """Returns { layer_type, feature_id, blocked, reasons: [{type, count}] }.

    R4: a block/compartment with raw inventories (tree/sample/field) is blocked.
    R5: a compartment with child sub-compartments is blocked (independence —
    parent delete does NOT cascade to children).
    """
    from ..models.forest_block import ForestBlock
    from ..models.inventory import InventoryTree
    from ..models.field_inventory import FieldInventorySamplePlot, FieldInventoryCalculation

    if layer_type not in {"blocks", "compartments", "sub_compartments", "sub_areas"}:
        # lines/points have no FK dependents in R4/R5 semantics
        return {
            "layer_type": layer_type,
            "feature_id": feature_id,
            "blocked": False,
            "reasons": [],
        }

    reasons: List[Dict[str, Any]] = []
    blocked = False

    if layer_type in {"blocks", "compartments", "sub_compartments"}:
        # R5: child compartments / sub-compartments guard (independent delete)
        children = _guard_count(db, lambda: db.query(ForestBlock).filter(
            ForestBlock.parent_block_id == feature_id,
        ).count())
        if children:
            blocked = True
            reasons.append({"type": "child_compartments", "count": children})

        # R4: tree inventory rows linked by FK block_id
        trees = _guard_count(db, lambda: db.query(InventoryTree).filter(
            InventoryTree.block_id == feature_id
        ).count())
        if trees:
            blocked = True
            reasons.append({"type": "tree_inventory", "count": trees})

        # R4: sample plots authored under this block name
        block = db.query(ForestBlock).filter(
            ForestBlock.id == feature_id,
            ForestBlock.calculation_id == calculation.id,
        ).first()
        if block is not None:
            # Owner report 2026-10-03: `block_name` is a bare string with no FK
            # back to a forest/calculation, and block auto-numbering
            # ("blocks-1", "blocks-2", ...) repeats across different forests --
            # without scoping to THIS calculation, deleting a block in forest A
            # was blocked by an unrelated forest B's field-inventory rows that
            # merely happened to share the same generic name.
            plots = _guard_count(db, lambda: db.query(FieldInventorySamplePlot).join(
                FieldInventoryCalculation,
                FieldInventorySamplePlot.field_inventory_calculation_id == FieldInventoryCalculation.id,
            ).filter(
                FieldInventoryCalculation.calculation_id == calculation.id,
                FieldInventorySamplePlot.block_name == block.name,
            ).count())
            if plots:
                blocked = True
                reasons.append({"type": "sample_plots", "count": plots})

    if layer_type == "sub_areas":
        from ..models.yearly_activities import ProposedYearlyActivity
        refs = _guard_count(db, lambda: db.query(ProposedYearlyActivity).filter(
            ProposedYearlyActivity.sub_area_id == feature_id,
        ).count())
        if refs:
            blocked = True
            reasons.append({"type": "yearly_activities", "count": refs})

    return {
        "layer_type": layer_type,
        "feature_id": feature_id,
        "blocked": blocked,
        "reasons": reasons,
    }


def _guard_count(db, counter) -> int:
    """Count rows defensively — the check is informational (R4/R5 guidance).

    The test harness's create_all can skip tables whose GiST/Geography index is
    double-registered (e.g. ``inventory_trees``), and some deployments may not
    have built a dependent module yet.  Missing table → 0 is the safe answer
    for the guard (never 500 a delete-guard probe).
    """
    try:
        return int(counter() or 0)
    except Exception as e:
        logger.debug(f"[delete-guard] no count (table/relation missing or error): {e}")
        try:
            db.rollback()  # reset aborted transaction so subsequent guards still run
        except Exception:
            logger.warning(
                "rollback failed while resetting an aborted transaction - the "
                "guards that follow will probably fail too", exc_info=True,
            )
        return 0


def is_editing_allowed(calculation) -> bool:
    """Map-state guard for the editing router (E1.3).

    False when structure_locked is set; False when the lifecycle status is not
    a state that tolerates geometry writes.  ``force=true`` (server-internal /
    admin) bypasses only the lifecycle claim, NOT the DB structure lock.
    """
    if getattr(calculation, "structure_locked", False):
        return False
    state = str(getattr(calculation, "map_lifecycle_status", "draft"))
    return state in {"draft", "failed", "submitted"}