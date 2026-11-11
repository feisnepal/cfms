"""
Geometry sanitization for digitized features (Gap 6.2).

Applied at the head of every digitize write path (bulk upsert, finalize job,
legacy PATCH) BEFORE the import validation chain. Kills three attack/robustness
classes:

1. Coordinate-count DoS — hard cap on total vertices (5000, same as
   `WORKSPACE_IMPORT_MAX_VERTICES`).
2. Out-of-bounds coordinates — every coord must be inside the calculation
   boundary bbox expanded by ±10 km (`WORKSPACE_IMPORT_10KM_BUFFER_M`).
3. False precision — floats truncated to 6 decimal places (~0.1 m at equator)
   for EPSG:4326, preventing float-noise in stored GeoJSON.

The import validators (`file_processor.py:400-510`) are unchanged and run after
this module. This is a defence-in-depth gate, not a replacement for them.
"""
import json
import logging
from typing import Any, Dict, List, Sequence, Tuple

from ..core.constants import (
    WORKSPACE_IMPORT_MAX_VERTICES,
    WORKSPACE_IMPORT_10KM_BUFFER_M,
)

logger = logging.getLogger(__name__)

MAX_VERTICES = WORKSPACE_IMPORT_MAX_VERTICES
PRECISION = 6  # decimal places for EPSG:4326


class GeometrySanitizationError(ValueError):
    """Raised when a geometry fails sanitization."""


def extract_coordinates(geometry: Dict[str, Any]) -> List[Tuple[float, float]]:
    """Flatten a GeoJSON geometry into its [lon, lat] coordinate list.

    Supports Point / MultiPoint / LineString / MultiLineString /
    Polygon / MultiPolygon (and GeometryCollection via recursion).
    Coordinates are the first two elements of each position array.
    """
    coords: List[Tuple[float, float]] = []
    _extract(geometry, coords)
    return coords


def _extract(geometry: Dict[str, Any], out: List[Tuple[float, float]]) -> None:
    gtype = (geometry or {}).get("type")
    gcoords = (geometry or {}).get("coordinates")
    if gtype == "Point":
        out.append((gcoords[0], gcoords[1]))
    elif gtype in ("MultiPoint", "LineString"):
        for c in gcoords:
            out.append((c[0], c[1]))
    elif gtype in ("MultiLineString", "Polygon"):
        for part in gcoords:
            for c in part:
                out.append((c[0], c[1]))
    elif gtype == "MultiPolygon":
        for polygon in gcoords:
            for ring in polygon:
                for c in ring:
                    out.append((c[0], c[1]))
    elif gtype == "GeometryCollection":
        for sub in (geometry or {}).get("geometries", []):
            _extract(sub, out)


def _count_vertices(geometry: Dict[str, Any]) -> int:
    return len(extract_coordinates(geometry))


def _bbox_contains(bbox: Sequence[float], lon: float, lat: float, buffer_m: int) -> bool:
    """True if (lon, lat) is within bbox expanded by buffer_m.

    bbox = [min_lon, min_lat, max_lon, max_lat]. Buffer is converted from metres
    to degrees at the bbox centre latitude (≈111,320 m/deg lat; cos(lat) for lon).
    This is an approximate pre-filter — the authoritative 10 km check remains
    `validate_layer_distance()` (ST_DWithin) at finalize.
    """
    if not bbox or len(bbox) < 4:
        return True  # no boundary → skip bounds gate (validate_layer_distance covers)
    min_lon, min_lat, max_lon, max_lat = bbox
    center_lat = (min_lat + max_lat) / 2.0
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = m_per_deg_lat * max(0.2, abs(cosd(center_lat)))
    dlat = buffer_m / m_per_deg_lat
    dlon = buffer_m / m_per_deg_lon
    return (
        min_lon - dlon <= lon <= max_lon + dlon
        and min_lat - dlat <= lat <= max_lat + dlat
    )


def cosd(deg: float) -> float:
    import math
    return math.cos(math.radians(deg))


def _truncate(geometry: Dict[str, Any], precision: int) -> Dict[str, Any]:
    """Return a deep copy of geometry with coordinates truncated to `precision` dp."""
    import copy
    clone = copy.deepcopy(geometry)

    def _trunc_positions(pos):
        if isinstance(pos, list):
            return [_trunc_positions(p) for p in pos]
        if isinstance(pos, (int, float)):
            return round(pos, precision)
        return pos

    if isinstance(clone.get("coordinates"), list):
        clone["coordinates"] = _trunc_positions(clone["coordinates"])
    return clone


def sanitize_geometry(geojson: Dict[str, Any], calc_bbox: Sequence[float] | None = None) -> Dict[str, Any]:
    """Sanitize a GeoJSON geometry before it enters the validation chain.

    Args:
        geojson: GeoJSON geometry dict (Point/LineString/Polygon/Multi*).
        calc_bbox: Optional [min_lon, min_lat, max_lon, max_lat] of the
            calculation boundary; used for the ±10 km bounds check. When None,
            the bounds check is skipped (authoritative check is the 10 km
            ST_DWithin validator at finalize).

    Returns:
        A NEW dict — coordinates truncated to 6 dp, validated for count + bounds.

    Raises:
        GeometrySanitizationError: vertex cap exceeded, or a coordinate is
            outside the boundary bbox (+10 km).
    """
    if not isinstance(geojson, dict) or not geojson.get("type"):
        raise GeometrySanitizationError("Geometry must be a GeoJSON geometry object")

    gtype = geojson.get("type")
    if gtype == "GeometryCollection":
        cleaned = dict(geojson)
        cleaned["geometries"] = [
            sanitize_geometry(g, calc_bbox) for g in geojson.get("geometries", [])
        ]
        return cleaned

    if gtype not in ("Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"):
        raise GeometrySanitizationError(f"Unsupported geometry type: {gtype}")

    coords = extract_coordinates(geojson)
    if len(coords) > MAX_VERTICES:
        raise GeometrySanitizationError(
            f"Vertex limit exceeded: {len(coords)} (max: {MAX_VERTICES})"
        )

    for lon, lat in coords:
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            raise GeometrySanitizationError("Coordinates must be numeric")
        if lon < -180 or lon > 180 or lat < -90 or lat > 90:
            raise GeometrySanitizationError(f"Coordinate out of range: ({lon}, {lat})")
        if calc_bbox and not _bbox_contains(calc_bbox, lon, lat, WORKSPACE_IMPORT_10KM_BUFFER_M):
            raise GeometrySanitizationError(
                f"Coordinate ({lon}, {lat}) is outside the project area (±10 km)"
            )

    return _truncate(geojson, PRECISION)


def truncate_precision(geojson: Dict[str, Any], precision: int = PRECISION) -> Dict[str, Any]:
    """Truncate coordinates to `precision` decimal places (deep copy)."""
    return _truncate(geojson, precision)


# ---------------------------------------------------------------------------
# H2.15 / S2-56 — counting positions in an arbitrary request body
# ---------------------------------------------------------------------------
# `extract_coordinates` above needs a well-formed GeoJSON geometry with a known
# `type`. The ingress guard cannot assume either: it sees whatever JSON a
# caller posted, at whatever nesting, under whatever field name, and a hostile
# body is precisely the one that will not declare an honest `type`. So the
# counter below is structural — it finds every `coordinates` value wherever it
# sits and counts the position arrays inside it, without believing anything the
# payload says about itself.

# A GeoJSON geometry serialized into a string field rather than an object —
# `yearly_activities.geometry` is typed `str` and holds exactly this. Without
# the string branch that route would be the one hole left in the guard.
_MAX_EMBEDDED_JSON_CHARS = 8 * 1024 * 1024

# Depth is bounded so a body of nothing but open brackets cannot turn the walk
# into the denial of service it is meant to prevent.
_MAX_WALK_DEPTH = 200


def _count_positions_in_coordinates(value: Any, budget: int) -> int:
    """Count position arrays in one `coordinates` value. Stops at `budget`."""
    total = 0
    stack: List[Tuple[Any, int]] = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if not isinstance(node, list) or not node or depth > _MAX_WALK_DEPTH:
            continue
        head = node[0]
        # `isinstance(True, int)` is True, so bools are excluded explicitly —
        # `[true, false]` is not a coordinate pair.
        if isinstance(head, (int, float)) and not isinstance(head, bool):
            total += 1
            if total >= budget:
                return total
            continue
        for child in node:
            if isinstance(child, list):
                stack.append((child, depth + 1))
    return total


def count_positions(body: Any, budget: int) -> Tuple[int, int]:
    """Walk a decoded JSON body for geometry.

    Returns `(total_positions, largest_single_geometry)`. The walk stops once
    `total_positions` reaches `budget`, so a body engineered to be expensive to
    count costs no more than a body at the limit.
    """
    total = 0
    largest = 0
    stack: List[Tuple[Any, int]] = [(body, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > _MAX_WALK_DEPTH:
            continue
        if isinstance(node, dict):
            if "coordinates" in node:
                # This dict is a geometry. Count it whole and do not descend —
                # its coordinates are the only positions it holds.
                n = _count_positions_in_coordinates(
                    node["coordinates"], max(1, budget - total)
                )
                total += n
                largest = max(largest, n)
                if total >= budget:
                    return total, largest
                continue
            for child in node.values():
                stack.append((child, depth + 1))
        elif isinstance(node, list):
            for child in node:
                stack.append((child, depth + 1))
        elif isinstance(node, str):
            if (
                len(node) <= _MAX_EMBEDDED_JSON_CHARS
                and "coordinates" in node
                and node.lstrip()[:1] in ("{", "[")
            ):
                try:
                    stack.append((json.loads(node), depth + 1))
                except (ValueError, RecursionError):
                    continue
    return total, largest
