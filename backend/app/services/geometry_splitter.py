from __future__ import annotations

import logging
import math
from typing import Dict, List, Tuple, Optional

try:
    import pyproj
except ImportError:
    pyproj = None

from shapely.geometry import LineString, Point, Polygon, MultiPolygon, MultiLineString, box
from shapely.ops import split, nearest_points, substring
from shapely import affinity

logger = logging.getLogger(__name__)

MIN_PIECE_AREA_SQ_DEG = 0.000001
MIN_CUT_LENGTH_DEG = 0.00001
LINE_EXTENSION_DEG = 0.01
MAX_SPLIT_PIECES = 20
UTM_ZONE_WIDTH = 6


class SplitValidationError(Exception):
    pass


class DegenerateSplitError(SplitValidationError):
    pass


def split_polygon_with_line(
    polygon: Polygon,
    cut_line: LineString,
) -> List[Polygon]:
    if polygon.geom_type not in ("Polygon", "MultiPolygon"):
        raise SplitValidationError(
            f"split.requires_polygon: got {polygon.geom_type}"
        )

    if cut_line.geom_type != "LineString":
        raise SplitValidationError(
            f"split.cut_must_be_linestring: got {cut_line.geom_type}"
        )

    if cut_line.length < MIN_CUT_LENGTH_DEG:
        raise SplitValidationError("split.cut_line_too_short")

    if polygon.geom_type == "MultiPolygon":
        all_pieces: List[Polygon] = []
        for geom in polygon.geoms:
            pieces = split_polygon_with_line(geom, cut_line)
            all_pieces.extend(pieces)
        return all_pieces

    if not polygon.intersects(cut_line):
        extended = _extend_line(cut_line, LINE_EXTENSION_DEG)
        if not polygon.intersects(extended):
            raise SplitValidationError("split.line_does_not_intersect")
        cut_line = extended

    boundary = polygon.boundary
    intersection = boundary.intersection(cut_line)

    if intersection.is_empty:
        raise SplitValidationError("split.intersection_not_spanning")

    intersection_count = _count_intersection_points(intersection)
    if intersection_count < 2:
        extended = _extend_line(cut_line, LINE_EXTENSION_DEG * 3)
        extended_intersection = boundary.intersection(extended)
        extended_count = _count_intersection_points(extended_intersection)
        if extended_count < 2:
            raise SplitValidationError("split.intersection_not_spanning")
        cut_line = extended

    try:
        split_result = split(polygon, cut_line)
    except Exception as e:
        logger.debug("Primary split failed (%s), trying buffer fallback", e)
        split_result = _split_with_buffer(polygon, cut_line)

    pieces = _collect_pieces(split_result)

    if len(pieces) < 2:
        raise SplitValidationError("split.no_split_possible")

    if len(pieces) > MAX_SPLIT_PIECES:
        raise SplitValidationError(
            f"split.too_many_pieces: {len(pieces)} > {MAX_SPLIT_PIECES}"
        )

    validated = []
    for piece in pieces:
        if not piece.is_valid:
            piece = piece.buffer(0)
        if piece.is_empty or piece.area < MIN_PIECE_AREA_SQ_DEG:
            continue
        validated.append(piece)

    if len(validated) < 2:
        raise DegenerateSplitError("split.result_degenerate")

    validated.sort(key=lambda p: p.area, reverse=True)

    return validated


def _extend_line(line: LineString, extension_distance: float) -> LineString:
    coords = list(line.coords)

    if len(coords) < 2:
        return line

    start = Point(coords[0])
    next_point = Point(coords[1])
    start_angle = _angle_between(start, next_point) + math.pi
    extended_start = _point_at_distance(start, start_angle, extension_distance)

    end = Point(coords[-1])
    prev_point = Point(coords[-2])
    end_angle = _angle_between(prev_point, end)
    extended_end = _point_at_distance(end, end_angle, extension_distance)

    new_coords = [(extended_start.x, extended_start.y)] + coords + [(extended_end.x, extended_end.y)]

    return LineString(new_coords)


def _angle_between(from_point: Point, to_point: Point) -> float:
    dx = to_point.x - from_point.x
    dy = to_point.y - from_point.y
    return math.atan2(dy, dx)


def _point_at_distance(origin: Point, angle_rad: float, distance: float) -> Point:
    return Point(
        origin.x + distance * math.cos(angle_rad),
        origin.y + distance * math.sin(angle_rad),
    )


def _buffer_width_in_degrees(polygon: Polygon, width_meters: float = 0.1) -> float:
    centroid = polygon.centroid
    utm_zone = int(math.floor((centroid.x + 180) / 6)) + 1
    if centroid.y < 0:
        epsg_code = 32700 + utm_zone
    else:
        epsg_code = 32600 + utm_zone

    if pyproj is None:
        return width_meters / 111320.0

    try:
        proj_wgs = pyproj.CRS.from_epsg(4326)
        proj_utm = pyproj.CRS.from_epsg(epsg_code)
        transformer = pyproj.Transformer.from_crs(
            proj_wgs, proj_utm, always_xy=True
        )
        cx_utm, cy_utm = transformer.transform(centroid.x, centroid.y)
        cx2_utm, cy2_utm = cx_utm + 1.0, cy_utm
        inv_transformer = pyproj.Transformer.from_crs(
            proj_utm, proj_wgs, always_xy=True
        )
        cx2_wgs, _ = inv_transformer.transform(cx2_utm, cy2_utm)
        deg_per_m = abs(cx2_wgs - centroid.x)
        return width_meters * deg_per_m
    except Exception:
        logger.warning(
            "UTM conversion failed - falling back to a fixed 111,320 m per "
            "degree, which is up to 12%% off in longitude at this latitude",
            exc_info=True,
        )
        return width_meters / 111320.0


def _split_with_buffer(polygon: Polygon, line: LineString) -> List[Polygon]:
    buffer_width = _buffer_width_in_degrees(polygon, 0.1)
    cut_buffer = line.buffer(buffer_width)
    remaining = polygon.difference(cut_buffer)
    pieces = _collect_pieces(remaining)

    if len(pieces) < 2:
        cut_buffer = line.buffer(buffer_width * 5)
        remaining = polygon.difference(cut_buffer)
        pieces = _collect_pieces(remaining)

    return pieces


def validate_split_pieces(pieces: List[Polygon]) -> Dict:
    result: Dict = {
        "valid": False,
        "error": None,
        "piece_count": len(pieces),
        "areas_ha": [],
        "total_area_ha": 0.0,
    }

    if len(pieces) < 2:
        result["error"] = "split.result_insufficient_pieces"
        return result

    areas = []
    for i, piece in enumerate(pieces):
        if not piece.is_valid:
            result["error"] = f"split.piece_{i}_invalid_geometry"
            return result

        area_ha = piece.area / 10000
        if area_ha < 0.001:
            result["error"] = f"split.result_too_small: piece {i} is {area_ha:.6f} ha"
            return result

        areas.append(area_ha)

    result["valid"] = True
    result["areas_ha"] = areas
    result["total_area_ha"] = sum(areas)

    return result


def _count_intersection_points(intersection) -> int:
    if intersection.geom_type == "Point":
        return 1
    elif intersection.geom_type == "MultiPoint":
        return len(intersection.geoms)
    elif intersection.geom_type == "GeometryCollection":
        count = 0
        for geom in intersection.geoms:
            count += _count_intersection_points(geom)
        return count
    return 0


def _collect_pieces(geom) -> List[Polygon]:
    pieces: List[Polygon] = []

    if geom is None or geom.is_empty:
        return pieces

    if geom.geom_type == "Polygon":
        pieces.append(geom)
    elif geom.geom_type == "MultiPolygon":
        pieces.extend(geom.geoms)
    elif geom.geom_type == "GeometryCollection":
        for g in geom.geoms:
            pieces.extend(_collect_pieces(g))

    return pieces


def _compute_utm_zone(longitude: float) -> int:
    return int(math.floor((longitude + 180) / UTM_ZONE_WIDTH) % 60) + 1


def execute_split(
    polygon_geojson: Dict,
    cut_line_geojson: Dict,
) -> Dict:
    from shapely.geometry import shape, mapping

    polygon = shape(polygon_geojson)
    cut_line = shape(cut_line_geojson)

    try:
        pieces = split_polygon_with_line(polygon, cut_line)
    except (SplitValidationError, DegenerateSplitError) as e:
        return {
            "success": False,
            "pieces": [],
            "error": str(e),
            "piece_count": 0,
        }

    validation = validate_split_pieces(pieces)
    if not validation["valid"]:
        return {
            "success": False,
            "pieces": [],
            "error": validation["error"],
            "piece_count": 0,
        }

    features = []
    for i, piece in enumerate(pieces):
        features.append({
            "type": "Feature",
            "geometry": mapping(piece),
            "properties": {
                "id": f"piece_{i}",
                "area_hectares": round(piece.area / 10000, 4),
                "piece_index": i,
            },
        })

    return {
        "success": True,
        "pieces": features,
        "piece_count": len(features),
        "areas_ha": validation["areas_ha"],
        "total_area_ha": validation["total_area_ha"],
    }
