"""
Sub-area service — overlap detection, category validation, clip operations.
# business: CFMG — sub-areas are non-overlapping special-use zones within blocks
# constraint: no two sub-areas may overlap (FCFS — first created retains area)
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from ..core.constants import SQM_PER_HA
from ..core.sub_area_kinds import is_strip_category, real_sub_areas
from ..utils.geometry_utils import calculate_area_geodesic_from_shapely

logger = logging.getLogger(__name__)

_SUB_AREA_IMPORT_WARNINGS: Dict[str, Any] = {}

from shapely.geometry import LineString, Polygon, MultiPolygon, Point


def _metres_to_degrees(metres: float) -> float:
    """Approx conversion for small distances ~ metres to degrees longitude."""
    from ..services.file_processor import _metres_to_degrees as _f
    return _f(metres)


def convert_lines_to_multi_line(
    geometries: List[Any],
    tolerance_m: float = None,
) -> Tuple[List[Any], List[Any]]:
    """
    Snap near-closed LineStrings into closed rings.

    Delegates to the shared engine in `file_processor.convert_lines_to_multi_line`
    (single source of truth) so sub-areas and all other polygon-purpose layers
    share identical line handling.

    For each LineString whose endpoints are nearer than `tolerance_m`, snap the
    last coordinate onto the first to form a closed ring, then build a Polygon.
    Lines that are already exactly closed become Polygons.  Returns
    (remaining_lines, closed_polygons).
    """
    from ..services.file_processor import convert_lines_to_multi_line as _f
    return _f(geometries, tolerance_m)


def polygonise_sub_area_geometries(
    geometries: List[Any],
    attributes: List[Dict[str, Any]],
    snap_tolerance_m: Optional[float] = None,
) -> List[Tuple[Any, Dict[str, Any]]]:
    """
    Convert mixed input geometries (points / lines / polygons) into one polygon
    per sub-area, using Feature-to-Polygon with snap-to-close for lines.

    Thin wrapper over the shared `file_processor.feature_to_polygon` engine so the
    sub-areas path and every other polygon-purpose layer share identical logic.
    Adds sub-area-specific category auto-detection and caches the engine warnings.

    Returns a list of (shapely_Polygon, attrs) — one entry per resulting sub-area.

    Behaviour:
      - Polygons are preserved as-is (one feature).
      - Closed/near-closed lines are snapped closed (within snap_tolerance_m)
        and converted into Polygons (one feature each).
      - Remaining open lines and every polygon boundary are noded into one
        planar graph and polygonized (ArcGIS-style Feature-to-Polygon; one
        feature per resulting face — see file_processor._polygonize_edge_network).
      - Points name the surrounding polygons via point-in-polygon.
      - Category auto-detected per feature (falls back to `protected`).
    """
    if snap_tolerance_m is None:
        from ..core.constants import SUB_AREA_SNAP_TOLERANCE_M
        snap_tolerance_m = SUB_AREA_SNAP_TOLERANCE_M

    from ..services.file_processor import feature_to_polygon, PolygonizeConfig

    config = PolygonizeConfig(
        snap_tolerance_m=snap_tolerance_m,
        name_prefix="Sub-Area",
    )
    result, warnings = feature_to_polygon(geometries, attributes, config)

    # Sub-area-specific: auto-detect category for any feature lacking one.
    for geom, attrs in result:
        if "category" not in attrs:
            attrs["category"] = auto_detect_category(attrs)

    _cache_import_warnings(warnings)

    return result


def _last_import_warnings() -> Dict[str, Any]:
    """Last polygonise run's warnings (set by polygonise_sub_area_geometries)."""
    global _SUB_AREA_IMPORT_WARNINGS
    return dict(_SUB_AREA_IMPORT_WARNINGS)


def _cache_import_warnings(warnings: Dict[str, Any]) -> None:
    global _SUB_AREA_IMPORT_WARNINGS
    _SUB_AREA_IMPORT_WARNINGS = {k: v for k, v in warnings.items()}


# Aliases accepted when auto-detecting a category column on import.
CATEGORY_ALIASES = ("category", "purpose", "type", "वर्ग", "प्रकार", "sub_area_type")

# Normalise common Nepali / English category values into enum keys.
CATEGORY_VALUE_ALIASES = {
    "protected": "protected",
    "संरक्षित": "protected",
    "plantation": "plantation",
    "सिमी": "plantation",
    "बृक्षारोपण": "plantation",
    "pro-poor": "pro-poor",
    "garbas": "pro-poor",
    "religious": "religious",
    "religious area": "religious",
    "biodiversity": "biodiversity",
    "tourist": "tourist",
    "office": "office",
    "private": "private_land",
    "private_land": "private_land",
    "private land": "private_land",
    "private sector": "private_land",
    "agroforestry": "agroforestry",
    "algal": "agroforestry",
    "tree_strata": "tree_strata",
    "tree strata": "tree_strata",
    "water_hole": "water_hole",
    "water hole": "water_hole",
    "wildlife_corridor": "wildlife_corridor",
    "wildlife corridor": "wildlife_corridor",
    "wildlife": "wildlife_corridor",
    "encroached": "encroached",
    "encroachment": "encroached",
}
# Fall back to the enum's own exact keys (e.g. from subAreaCategories).
try:
    from ..schemas.forest import SubAreaCategory
    _ENUM_KEYS = set(SubAreaCategory.valid_categories())
except Exception:  # pragma: no cover
    logging.getLogger(__name__).error(
        "sub-area category enum unavailable at import - category "
        "validation is disabled for this process", exc_info=True,
    )
    _ENUM_KEYS = set()


def auto_detect_category(props: Dict[str, Any]) -> str:
    """
    Read a category value from an imported feature's properties (D5/R3).

    Scans known alias columns for a recognisable value and maps it onto the
    official SubAreaCategory enum keys.  Unmatched/missing -> 'protected'.
    """
    for key, value in list(props.items()):
        key_l = str(key).strip().lower()
        if key_l not in CATEGORY_ALIASES:
            continue
        value_s = str(value).strip().lower() if value is not None else ""
        if not value_s:
            continue
        direct = CATEGORY_VALUE_ALIASES.get(value_s)
        if direct:
            return direct
        if value_s in _ENUM_KEYS:
            return value_s
        break
    return "protected"


VALID_CATEGORIES = frozenset({
    "road", "stream", "river", "degraded", "plantation",
    "settlement", "agriculture", "water_body", "cliff",
    "wetland", "grassland", "shrubland", "conservation", "other",
})


def has_forest_extent(db, calculation) -> bool:
    """True when the forest has a boundary **or** any block / compartment.

    A sub-area is clipped to (boundary ∪ blocks) and represents a zone *within*
    the forest, so it cannot be drawn or imported before that extent exists.
    Blocks/compartments count because a boundary is derivable from them (and the
    clip region already unions them in).
    """
    if getattr(calculation, "boundary_geom", None) is not None:
        return True
    try:
        from app.models.forest_block import ForestBlock

        if (
            db.query(ForestBlock.id)
            .filter(ForestBlock.calculation_id == calculation.id)
            .first()
            is not None
        ):
            return True
    except Exception:  # noqa: BLE001 -- defensive: fall back to result_data below
        logger.exception("has_forest_extent: block lookup failed; using result_data")
    rd = calculation.result_data or {}
    return bool(rd.get("blocks") or rd.get("compartments"))


#: Below this (in degrees², ~0.0001 m²) a "polygon" is floating-point residue from
#: an intersection/difference, not an area anybody recorded.
MIN_POLYGON_AREA_DEG2 = 1e-12

#: Tolerance (degrees, ~0.1 mm) for the final containment / overlap checks.
_GEOM_TOL_DEG = 1e-9

#: More than this fraction lost counts as "trimmed" (same 0.1 % as clip_to_region).
_TRIM_REL_TOL = 0.001


def polygonal_part(geom: Any) -> Optional[Any]:
    """The polygon part(s) of ``geom`` -- or None when there is none.

    ``intersection`` / ``difference`` do not always return a polygon. A polygon
    that overlaps the forest AND touches it elsewhere along an edge gives a
    ``GeometryCollection`` (polygon + line); one that only touches gives a line
    or a point. Checking ``is_empty`` alone let those through, so a sub-area
    could be stored as a ``Point`` with area 0, or carry a stray line. Only
    polygon area is a sub-area, so everything else is dropped here.
    """
    if geom is None or geom.is_empty:
        return None

    def _polys(g: Any) -> List[Any]:
        t = g.geom_type
        if t == "Polygon":
            return [g]
        if t in ("MultiPolygon", "GeometryCollection"):
            return [p for sub in g.geoms for p in _polys(sub)]
        return []

    parts = [p for p in _polys(geom) if not p.is_empty and p.area > MIN_POLYGON_AREA_DEG2]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def _legacy_unit_shapes(calculation) -> List[Any]:
    """Block / compartment geometries kept in ``result_data`` (forests that predate the
    ``forest_blocks`` table). Unreadable ones are logged, not silently skipped."""
    out: List[Any] = []
    rd = calculation.result_data or {}
    for key in ("blocks", "compartments"):
        for unit in rd.get(key) or []:
            gj = unit.get("geometry") if isinstance(unit, dict) else None
            if not gj:
                continue
            try:
                out.append(shape(gj))
            except Exception:  # noqa: BLE001 -- logged; the unit just can't widen the extent
                logger.exception("forest_extent_geometry: unreadable legacy %s geometry", key)
    return out


def forest_extent_geometry(db, calculation) -> Optional[Any]:
    """The ground a sub-area must lie within, as a shapely geometry.

    The forest boundary when there is one; otherwise the union of the forest's
    blocks / compartments (the boundary is derived from them, and
    ``has_forest_extent`` accepts them as the extent). ``None`` when there is no
    forest yet -- the caller then keeps the sub-area *pending* (see
    :func:`place_sub_area`) instead of storing one it cannot check.
    """
    from geoalchemy2.shape import to_shape

    boundary = getattr(calculation, "boundary_geom", None)
    if boundary is not None:
        try:
            shp = to_shape(boundary)
            if not shp.is_empty:
                return shp
        except Exception:  # noqa: BLE001 -- logged; falls through to the blocks
            logger.exception("forest_extent_geometry: boundary unreadable for %s", calculation.id)

    shapes: List[Any] = []
    try:
        from app.models.forest_block import ForestBlock

        rows = db.query(ForestBlock.geometry).filter(ForestBlock.calculation_id == calculation.id).all()
        shapes = [to_shape(r[0]) for r in rows if r[0] is not None]
    except Exception:  # noqa: BLE001 -- logged; fall back to result_data below
        logger.exception("forest_extent_geometry: block lookup failed for %s", calculation.id)
    if not shapes:
        shapes = _legacy_unit_shapes(calculation)
    shapes = [g for g in shapes if not g.is_empty]
    return unary_union(shapes) if shapes else None


def enforce_within_and_disjoint(
    geom: Any,
    extent: Any,
    existing_union: Optional[Any],
) -> Tuple[Optional[Any], Optional[str], Dict[str, bool]]:
    """Clip ``geom`` to ``extent`` and subtract ``existing_union``; verify the result.

    Returns ``(polygon, None, info)`` or ``(None, reason, info)``. ``reason`` is one of
    ``"outside_forest"`` (nothing of it lies inside), ``"covered"`` (all of it is
    already sub-area) or ``"invariant"`` (the verified result still breaks a rule
    -- refused rather than stored). ``info`` says what was cut: ``clipped``
    (by the forest) and ``overlapped`` (by other sub-areas).

    The two rules, both absolute: a sub-area lies inside the forest, and no two
    sub-areas overlap (first created keeps the ground).
    """
    info = {"clipped": False, "overlapped": False}
    if not geom.is_valid:
        from shapely import make_valid

        geom = make_valid(geom)
    original = geom.area

    clipped = polygonal_part(geom.intersection(extent))
    if clipped is None:
        return None, "outside_forest", info
    info["clipped"] = clipped.area < original * (1 - _TRIM_REL_TOL)

    result = clipped
    if existing_union is not None and not existing_union.is_empty:
        result = polygonal_part(clipped.difference(existing_union))
        if result is None:
            info["overlapped"] = True
            return None, "covered", info
        info["overlapped"] = result.area < clipped.area * (1 - _TRIM_REL_TOL)

    # Verify, do not assume: the checks above are the algorithm, these are the rule.
    if not result.is_valid:
        from shapely import make_valid

        result = polygonal_part(make_valid(result))
        if result is None:
            return None, "invariant", info
    if result.difference(extent.buffer(_GEOM_TOL_DEG)).area > MIN_POLYGON_AREA_DEG2:
        return None, "invariant", info
    if existing_union is not None and result.intersection(existing_union).area > MIN_POLYGON_AREA_DEG2:
        return None, "invariant", info
    return result, None, info


class SubAreaPlacementError(Exception):
    """A sub-area cannot be placed. ``reason``: outside_forest | covered | invariant."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


#: What each refusal says, in one place, for every handler that places a sub-area.
PLACEMENT_MESSAGES = {
    "outside_forest": "Sub-area is outside the forest boundary",
    "covered": "Sub-area is entirely within existing sub-areas",
    "invariant": "Sub-area could not be placed inside the forest without overlapping another sub-area",
}


@dataclass(frozen=True)
class Placement:
    """Where a sub-area really goes, and what it took to get it there."""

    geometry: Any
    #: no forest yet -- clipped to the boundary the moment one goes live
    pending_boundary_clip: bool = False
    #: the forest boundary / blocks cut part of it away
    clipped_to_forest: bool = False
    #: other sub-areas already held part of the ground
    overlap_removed: bool = False


def _others_union(calculation, exclude_id: Optional[str]) -> Optional[Any]:
    """Union of the sub-areas already on record (except ``exclude_id``, an edited one).

    Strips (fire line) are overlays, never obstacles: a zone may be drawn across one and keeps all its ground.
    """
    shapes = [
        shape(sa["geometry"])
        for sa in real_sub_areas((calculation.result_data or {}).get("sub_areas", []))
        if sa.get("geometry") and (exclude_id is None or str(sa.get("id")) != str(exclude_id))
    ]
    return unary_union(shapes) if shapes else None


def place_sub_area(
    db, calculation, geom: Any, exclude_id: Optional[str] = None, category: Optional[str] = None
) -> Placement:
    """Decide where a sub-area really goes. THE placement rule, for every writer.

    Both rules are absolute: a sub-area lies inside the forest, and no two
    sub-areas overlap (first created keeps the ground; an *edited* sub-area gives
    way to the others -- pass its id as ``exclude_id`` so it does not collide with
    its own old shape).

    - The forest is its boundary, or -- until there is one -- its blocks. The
      geometry is clipped to it, and the result is verified.
    - With NO forest yet there is nothing to clip to. The sub-area is still made
      disjoint from the others, and ``pending_boundary_clip`` is True so that the
      moment a boundary goes live it is clipped to it (see
      ``persist_boundary`` / ``reclip_sub_areas_to_boundary``).

    A strip (``category`` = fire line) is an overlay: it must lie inside the forest but may overlap any zone, so the
    no-overlap rule is not applied to it (and a strip is never an obstacle to a zone, see ``_others_union``).

    Raises :class:`SubAreaPlacementError` when nothing valid is left.
    """
    others = None if is_strip_category(category) else _others_union(calculation, exclude_id)
    extent = forest_extent_geometry(db, calculation)

    if extent is None:
        if not geom.is_valid:
            from shapely import make_valid

            geom = make_valid(geom)
        placed = polygonal_part(geom.difference(others) if others is not None else geom)
        if placed is None:
            raise SubAreaPlacementError("covered")
        overlapped = others is not None and placed.area < geom.area * (1 - _TRIM_REL_TOL)
        return Placement(placed, pending_boundary_clip=True, overlap_removed=overlapped)

    placed, refusal, info = enforce_within_and_disjoint(geom, extent, others)
    if refusal is not None:
        raise SubAreaPlacementError(refusal)
    return Placement(
        placed,
        pending_boundary_clip=False,
        clipped_to_forest=info["clipped"],
        overlap_removed=info["overlapped"],
    )


def place_sub_area_geometry(db, calculation, geom: Any) -> Tuple[Any, bool]:
    """``place_sub_area`` as ``(polygon, pending_boundary_clip)`` (the create endpoints)."""
    p = place_sub_area(db, calculation, geom)
    return p.geometry, p.pending_boundary_clip


def validate_category(category: str) -> None:
    """Raise ValueError if category is not in the valid 14-category set."""
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"Invalid sub-area category '{category}'. "
            f"Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
        )


def detect_overlap(
    new_geometry: Dict[str, Any],
    existing_sub_areas: List[Dict[str, Any]],
    exclude_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Check a candidate geometry against existing sub-areas for overlap.

    Strips are overlays and never conflict: they are skipped among the existing sub-areas. A caller checking a strip candidate
    should not call this at all (``is_strip_category``). The only caller today is the unmounted ``api/geometry.py``.

    Returns a list of overlap conflict dicts, each with:
      - sub_area_id: str
      - sub_area_name: str
      - category: str
      - overlap_area_ha: float
      - overlap_percentage: float  (of the candidate)
    """
    new_shape = shape(new_geometry)
    conflicts = []

    for sa in real_sub_areas(existing_sub_areas):
        if exclude_id and sa.get("id") == exclude_id:
            continue
        sa_geom = sa.get("geometry")
        if not sa_geom:
            continue
        try:
            existing_shape = shape(sa_geom)
            if new_shape.intersects(existing_shape):
                inter = new_shape.intersection(existing_shape)
                overlap_area_ha = inter.area / SQM_PER_HA
                new_area = new_shape.area
                pct = (inter.area / new_area * 100) if new_area > 0 else 0
                conflicts.append({
                    "sub_area_id": sa.get("id"),
                    "sub_area_name": sa.get("name", "Unnamed"),
                    "category": sa.get("category", "other"),
                    "overlap_area_ha": round(overlap_area_ha, 4),
                    "overlap_percentage": round(pct, 1),
                })
        except Exception as e:
            logger.warning(f"Overlap check failed for sub-area {sa.get('id')}: {e}")

    return conflicts


def clip_to_region(
    geometry: Dict[str, Any],
    region_geometries: List[Any],
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    Clip a sub-area geometry to the union of a region (forest boundary ∪ blocks).

    Returns (clipped_geojson, was_clipped):
      - clipped_geojson: the intersection geometry as GeoJSON (None when the
        intersection is empty — feature fully outside the region).
      - was_clipped: True when the geometry was materially reduced (>0.1%).
    """
    if not region_geometries:
        return geometry, False
    try:
        from shapely.ops import unary_union
        def _as_shp(g):
            if g is None:
                return None
            # geoalchemy2 WKB refs (e.g. Calculation.boundary_geom) -> shapely
            if hasattr(g, "srid") and hasattr(g, "data"):
                from geoalchemy2.shape import to_shape
                return to_shape(g)
            return shape(g) if isinstance(g, (dict, str)) else g
        region = unary_union([_as_shp(g) for g in region_geometries if g is not None])
    except Exception:
        # Returning unchanged means the sub-area is NOT clipped to the
        # boundary, so it can be stored extending past the forest.
        logger.exception(
            "clip region could not be built - the geometry is stored "
            "unclipped and may extend past the forest boundary"
        )
        return geometry, False
    if region.is_empty:
        return geometry, False

    geom_shape = shape(geometry)
    clipped = region.intersection(geom_shape)
    if clipped.is_empty or (getattr(clipped, "area", 0) or 0) <= 1e-9:
        return None, True
    if clipped.area < geom_shape.area * 0.999:
        return mapping(clipped), True
    return geometry, False


def clip_against_existing(
    new_geometry: Dict[str, Any],
    existing_sub_areas: List[Dict[str, Any]],
    exclude_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], float, float]:
    """
    Clip new_geometry against all existing sub-areas (FCFS).

    Returns (clipped_geojson, original_area_ha, clipped_area_ha).
    Raises ValueError if result is empty.
    """
    new_shape = shape(new_geometry)
    original_area_ha = new_shape.area / SQM_PER_HA

    other_shapes = []
    for sa in existing_sub_areas:
        if exclude_id and sa.get("id") == exclude_id:
            continue
        sa_geom = sa.get("geometry")
        if sa_geom:
            try:
                other_shapes.append(shape(sa_geom))
            except Exception as e:
                logger.warning(f"Skipping invalid sub-area geometry {sa.get('id')}: {e}")

    if other_shapes:
        union = unary_union(other_shapes)
        clipped = new_shape.difference(union)
        if clipped.is_empty:
            raise ValueError("Sub-area is entirely within existing sub-areas")
        new_shape = clipped

    clipped_area_ha = new_shape.area / SQM_PER_HA
    return mapping(new_shape), round(original_area_ha, 4), round(clipped_area_ha, 4)


def compute_block_breakdown(
    geometry: Dict[str, Any],
    blocks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Compute area breakdown of a geometry across blocks.

    Returns list of { blockId, blockName, area, percentage }.
    """
    geom_shape = shape(geometry)
    geom_area = geom_shape.area
    breakdown = []

    for block in blocks:
        block_geom = block.get("geometry")
        if not block_geom:
            continue
        try:
            block_shape = shape(block_geom)
            inter = geom_shape.intersection(block_shape)
            if not inter.is_empty:
                area = inter.area / SQM_PER_HA
                pct = (inter.area / geom_area * 100) if geom_area > 0 else 0
                breakdown.append({
                    "blockId": block.get("block_id") or block.get("id"),
                    "blockName": block.get("block_name") or block.get("name"),
                    "area": round(area, 4),
                    "percentage": round(pct, 1),
                })
        except Exception as e:
            logger.warning(f"Block breakdown error for {block.get('block_name')}: {e}")

    breakdown.sort(key=lambda x: x["area"], reverse=True)
    return breakdown


def build_sub_area_dict(
    geometry: Dict[str, Any],
    name: str,
    category: str,
    area_ha: float,
    block_id: Optional[str] = None,
    block_name: Optional[str] = None,
    block_breakdown: Optional[List[Dict[str, Any]]] = None,
    is_excluded: bool = False,
) -> Dict[str, Any]:
    """Build a standardised sub-area dict for storage in result_data."""
    return {
        "id": str(uuid4()),
        "name": name,
        "category": category,
        "geometry": geometry,
        "area_sqm": round(area_ha * SQM_PER_HA, 4),
        "area_hectares": round(area_ha, 4),
        "blockId": block_id,
        "blockName": block_name,
        "blockBreakdown": block_breakdown or [],
        "isExcluded": is_excluded,
        "is_excluded": is_excluded,
        # Category colour is the fallback; `style` (P3) is the per-feature
        # override the map/table writes and reads first (A6 fix).
        "fill_color": _category_fill_color(category),
        "style": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _category_fill_color(category: str) -> str:
    """Return a fill color hex for the given sub-area category."""
    palette = {
        "road": "#8B4513",
        "stream": "#4169E1",
        "river": "#00008B",
        "degraded": "#FF4500",
        "plantation": "#90EE90",
        "settlement": "#808080",
        "agriculture": "#FFD700",
        "water_body": "#00CED1",
        "cliff": "#555555",
        "wetland": "#008080",
        "grassland": "#32CD32",
        "shrubland": "#6B8E23",
        "conservation": "#800080",
        "other": "#D3D3D3",
    }
    return palette.get(category, "#D3D3D3")
