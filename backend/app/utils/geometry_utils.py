"""
Geometry utility functions for accurate area/perimeter/centroid calculations
"""
import logging
from typing import Tuple, Dict, Optional
from shapely.geometry import shape, mapping, Point as ShapelyPoint
from shapely.ops import transform
from pyproj import CRS, Transformer, Geod
from sqlalchemy import text
from sqlalchemy.orm import Session

# UTM zone selection is the SSOT in app.core.geo (single automatic source).
# Re-exported here so existing callers of this module keep working.
from app.core.geo import calculate_utm_epsg  # noqa: E402,F401
from app.core.constants import SQM_PER_HA

logger = logging.getLogger(__name__)


def calculate_area_geodesic(geometry_geojson: dict) -> Tuple[float, float]:
    """
    Calculate accurate geodesic area of a geometry using UTM projection.

    Args:
        geometry_geojson: GeoJSON geometry dict (must be in EPSG:4326)

    Returns:
        Tuple of (area_sqm, area_hectares)
    """
    from shapely.geometry import shape

    # Convert GeoJSON to Shapely geometry
    geom = shape(geometry_geojson)

    return calculate_area_geodesic_from_shapely(geom)


def calculate_area_geodesic_from_shapely(geom) -> Tuple[float, float]:
    """
    Calculate accurate geodesic area of a Shapely geometry using UTM projection.

    Automatically selects the correct UTM zone based on the geometry's location.
    Works globally for any coordinates.

    Args:
        geom: Shapely geometry in EPSG:4326 (WGS84)

    Returns:
        Tuple of (area_sqm, area_hectares)
    """
    # Get centroid to determine appropriate UTM zone
    centroid = geom.centroid

    # Calculate the correct UTM EPSG code for this location
    utm_epsg = calculate_utm_epsg(centroid.x, centroid.y)

    # Create transformer from WGS84 to UTM
    transformer = Transformer.from_crs(
        CRS.from_epsg(4326),  # WGS84
        CRS.from_epsg(utm_epsg),  # Automatically calculated UTM zone
        always_xy=True
    )

    # Transform geometry to UTM
    geom_utm = transform(transformer.transform, geom)

    # Calculate area in square meters
    area_sqm = geom_utm.area
    area_hectares = area_sqm / SQM_PER_HA

    return area_sqm, area_hectares


def calculate_area_from_wkb_postgis(db: Session, geometry_wkb) -> Tuple[float, float]:
    """
    Calculate accurate geodesic area using PostGIS ST_Area(geography).

    This method uses PostGIS's built-in geodesic calculations which are
    highly accurate for WGS84 coordinates.

    Args:
        db: Database session
        geometry_wkb: WKB geometry from PostGIS (in EPSG:4326)

    Returns:
        Tuple of (area_sqm, area_hectares)
    """
    # Use PostGIS geography type for accurate geodesic area calculation
    result = db.execute(
        text("SELECT ST_Area(ST_GeogFromWKB(:geom_wkb)) as area_sqm"),
        {"geom_wkb": bytes(geometry_wkb.data)}
    ).fetchone()

    area_sqm = result.area_sqm if result else 0.0
    area_hectares = area_sqm / SQM_PER_HA

    return area_sqm, area_hectares


def calculate_polygon_area_from_geom_column(db: Session, table_name: str, id_value: str, id_column: str = "id", geom_column: str = "geometry") -> Tuple[float, float]:
    """
    Calculate area directly from a PostGIS geometry column using geography cast.

    Args:
        db: Database session
        table_name: Table name (with schema if needed)
        id_value: ID value to filter
        id_column: Name of ID column (default: "id")
        geom_column: Name of geometry column (default: "geometry")

    Returns:
        Tuple of (area_sqm, area_hectares)
    """
    ALLOWED_GEOM_COLUMNS = {"geometry", "geom", "boundary_geom", "point_geometry"}
    if geom_column not in ALLOWED_GEOM_COLUMNS:
        raise ValueError(f"Invalid geometry column: {geom_column}")
    ALLOWED_ID_COLUMNS = {"id", "calculation_id"}
    if id_column not in ALLOWED_ID_COLUMNS:
        raise ValueError(f"Invalid ID column: {id_column}")
    ALLOWED_TABLE_PATTERNS = {"public.", "admin.", "landcover.", "ecology.", "infrastructure."}
    if not any(table_name.startswith(p) for p in ALLOWED_TABLE_PATTERNS):
        raise ValueError(f"Invalid table name: {table_name}")

    query = text(f"""
        SELECT ST_Area(geography({geom_column})) as area_sqm
        FROM {table_name}
        WHERE {id_column} = :id_val
    """)

    result = db.execute(query, {"id_val": id_value}).fetchone()

    area_sqm = result.area_sqm if result else 0.0
    area_hectares = area_sqm / SQM_PER_HA

    return area_sqm, area_hectares


# ---------------------------------------------------------------------------
# Geometry computation system — single source of truth for derived properties
# ---------------------------------------------------------------------------
# These keys are computed from geometry and are NEVER user-editable.
# Every geometry create/update endpoint:
#   1. Strips these keys from incoming payload (they cannot be set by client)
#   2. Calls compute_geometry_properties() and merges result
GEO_COMPUTED_PREFIX = 'geo_'
GEO_COMPUTED_KEYS = frozenset({
    'geo_area_ha',
    'geo_perimeter_km',
    'geo_length_km',
    'geo_centroid_lat',
    'geo_centroid_lng',
    'geo_bbox_ymin',
    'geo_bbox_ymax',
    'geo_bbox_xmin',
    'geo_bbox_xmax',
})


def strip_geo_fields(payload: dict) -> dict:
    """Remove all geo_* computed fields from an incoming payload.

    This ensures the client can never set these values — they are
    always derived from geometry on the server.
    """
    return {k: v for k, v in payload.items() if k not in GEO_COMPUTED_KEYS}


def compute_geometry_properties(geom) -> Dict[str, Optional[float]]:
    """Compute all derived geometry properties from a Shapely geometry.

    Uses pyproj.Geod for accurate geodesic measurements (not degree-based).
    Handles Polygon, MultiPolygon, LineString, MultiLineString, Point.

    Args:
        geom: Shapely geometry in EPSG:4326 (WGS84)

    Returns:
        Dict with keys:
            geo_area_ha       — area in hectares (Polygon/MultiPolygon only)
            geo_perimeter_km  — perimeter in km (Polygon/MultiPolygon only)
            geo_length_km     — length in km (LineString/MultiLineString only)
            geo_centroid_lat  — centroid latitude
            geo_centroid_lng  — centroid longitude
    """
    result: Dict[str, Optional[float]] = {
        'geo_area_ha': None,
        'geo_perimeter_km': None,
        'geo_length_km': None,
        'geo_centroid_lat': None,
        'geo_centroid_lng': None,
        'geo_bbox_ymin': None,
        'geo_bbox_ymax': None,
        'geo_bbox_xmin': None,
        'geo_bbox_xmax': None,
    }

    if geom is None or geom.is_empty:
        return result

    geom_type = geom.geom_type

    # Centroid (all geometry types)
    try:
        centroid = geom.centroid
        result['geo_centroid_lat'] = round(centroid.y, 6)
        result['geo_centroid_lng'] = round(centroid.x, 6)
    except Exception:
        logger.warning(
            "centroid failed for a %s - geo_centroid_lat/lng are omitted",
            getattr(geom, 'geom_type', '?'), exc_info=True,
        )

    # Bounding box (all geometry types)
    try:
        bounds = geom.bounds  # (minx, miny, maxx, maxy)
        result['geo_bbox_xmin'] = round(bounds[0], 6)
        result['geo_bbox_ymin'] = round(bounds[1], 6)
        result['geo_bbox_xmax'] = round(bounds[2], 6)
        result['geo_bbox_ymax'] = round(bounds[3], 6)
    except Exception:
        logger.warning(
            "bounds failed for a %s - the geo_bbox_* fields are omitted",
            getattr(geom, 'geom_type', '?'), exc_info=True,
        )

    # Use Geod for geodesic measurements
    geod = Geod(ellps='WGS84')

    if geom_type in ('Polygon', 'MultiPolygon'):
        try:
            area_sqm, perimeter_m = geod.geometry_area_perimeter(geom)
            result['geo_area_ha'] = round(abs(area_sqm) / SQM_PER_HA, 2)
            result['geo_perimeter_km'] = round(abs(perimeter_m) / 1000, 2)
        except Exception:
            # These two are THE derived area and perimeter. Omitting them shows the
            # feature as having no area, which reads as zero rather than unknown.
            logger.error(
                "geodesic area/perimeter failed for a %s - geo_area_ha and "
                "geo_perimeter_km are omitted, so the feature shows no area",
                getattr(geom, 'geom_type', '?'), exc_info=True,
            )

    elif geom_type in ('LineString', 'MultiLineString'):
        try:
            length_m = geod.geometry_length(geom)
            result['geo_length_km'] = round(abs(length_m) / 1000, 2)
        except Exception:
            logger.error(
                "geodesic length failed for a %s - geo_length_km is omitted",
                getattr(geom, 'geom_type', '?'), exc_info=True,
            )

    # Point has no area/perimeter/length — only centroid and bbox (set above)

    return result
