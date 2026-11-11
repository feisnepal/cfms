"""
Geometry utility functions for compartment splitting
"""
from shapely.geometry import shape, mapping, Polygon, Point
from geoalchemy2.shape import to_shape, from_shape
from typing import Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)


def geojson_to_polygon(geojson: Dict[str, Any]) -> Polygon:
    """Convert GeoJSON to Shapely Polygon"""
    try:
        return shape(geojson)
    except Exception as e:
        logger.error(f"Failed to convert GeoJSON to Polygon: {e}")
        raise ValueError(f"Invalid GeoJSON: {e}")


def polygon_to_geojson(polygon: Polygon) -> Dict[str, Any]:
    """Convert Shapely Polygon to GeoJSON"""
    try:
        return mapping(polygon)
    except Exception as e:
        logger.error(f"Failed to convert Polygon to GeoJSON: {e}")
        raise ValueError(f"Invalid Polygon: {e}")


def postgis_to_shapely(geometry):
    """Convert PostGIS geometry to Shapely"""
    try:
        return to_shape(geometry)
    except Exception as e:
        logger.error(f"Failed to convert PostGIS to Shapely: {e}")
        raise ValueError(f"Invalid PostGIS geometry: {e}")


def shapely_to_postgis(polygon: Polygon, srid: int = 4326):
    """Convert Shapely to PostGIS geometry"""
    try:
        return from_shape(polygon, srid=srid)
    except Exception as e:
        logger.error(f"Failed to convert Shapely to PostGIS: {e}")
        raise ValueError(f"Invalid Shapely polygon: {e}")


def calculate_area_sqm(polygon: Polygon, approximate: bool = True) -> float:
    """
    Calculate area in square meters using geodesic calculations.
    Uses coordinate-based approximation adjusted for latitude.

    Args:
        polygon: Shapely polygon in WGS84 (EPSG:4326)
        approximate: If True, use improved lat/lon approximation with latitude correction

    Returns:
        Area in square meters
    """
    if not polygon.is_valid or polygon.is_empty:
        return 0.0
    
    # Get centroid latitude for scaling correction
    centroid = polygon.centroid
    lat = centroid.y
    
    # Improved approximation: 1 degree ≈ 111km at equator
    # At higher latitudes, longitudinal degrees are shorter
    # lat角的 cos scales the longitudinal dimension
    import math
    lat_rad = math.radians(lat)
    km_per_deg_lon = 111.32 * math.cos(lat_rad)
    km_per_deg_lat = 110.574  # Roughly constant
    
    # Convert to meters
    m_per_deg_lon = km_per_deg_lon * 1000
    m_per_deg_lat = km_per_deg_lat * 1000
    
    # Get bounds to estimate scale
    bounds = polygon.bounds
    minx, miny, maxx, maxy = bounds
    
    # Calculate area using shoelace formula with proper scaling
    coords = list(polygon.exterior.coords)
    area_deg2 = 0.0
    
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        area_deg2 += (x1 * y2 - x2 * y1)
    
    area_deg2 = abs(area_deg2) / 2.0
    
    # Scale factor based on latitude (average of corner latitudes would be more accurate)
    avg_lat = (miny + maxy) / 2
    avg_lat_rad = math.radians(avg_lat)
    scale_factor = math.cos(avg_lat_rad)
    
    # Convert to square meters
    # Area in degrees² * (m/deg_lon) * (m/deg_lat)
    area_sqm = area_deg2 * m_per_deg_lon * m_per_deg_lat
    
    return max(0, area_sqm)


def calculate_perimeter_m(polygon: Polygon, approximate: bool = True) -> float:
    """
    Calculate perimeter in meters using geodesic calculations.

    Args:
        polygon: Shapely polygon in WGS84 (EPSG:4326)
        approximate: If True, use improved approximation

    Returns:
        Perimeter in meters
    """
    if not polygon.is_valid or polygon.is_empty:
        return 0.0
    
    import math
    
    # Calculate perimeter by summing haversine distances for each segment
    coords = list(polygon.exterior.coords)
    perimeter = 0.0
    
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        
        # Haversine formula for geodesic distance
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        
        # Earth radius in meters
        R = 6371000
        perimeter += R * c
    
    return perimeter


def extract_coordinates_from_point(location) -> Tuple[float, float]:
    """
    Extract (lon, lat) from PostGIS point

    Args:
        location: PostGIS Geography POINT

    Returns:
        Tuple of (longitude, latitude)
    """
    try:
        point = to_shape(location)
        return (point.x, point.y)
    except Exception as e:
        logger.error(f"Failed to extract coordinates: {e}")
        return (0.0, 0.0)


def point_to_geojson(location) -> Dict[str, float]:
    """
    Convert PostGIS point to GeoJSON-like dict

    Returns:
        Dict with 'lon' and 'lat' keys
    """
    lon, lat = extract_coordinates_from_point(location)
    return {"lon": lon, "lat": lat}


def validate_polygon(polygon: Polygon) -> bool:
    """
    Validate polygon geometry

    Args:
        polygon: Shapely polygon to validate

    Returns:
        True if valid, False otherwise
    """
    if polygon is None:
        return False

    if not polygon.is_valid:
        logger.warning(f"Invalid polygon: {polygon}")
        return False

    if polygon.is_empty:
        logger.warning("Polygon is empty")
        return False

    if polygon.area <= 0:
        logger.warning(f"Polygon has zero or negative area: {polygon.area}")
        return False

    return True


def get_polygon_bounds(polygon: Polygon) -> Dict[str, float]:
    """
    Get bounding box of polygon

    Returns:
        Dict with minx, miny, maxx, maxy
    """
    minx, miny, maxx, maxy = polygon.bounds
    return {
        "minx": minx,
        "miny": miny,
        "maxx": maxx,
        "maxy": maxy,
        "width": maxx - minx,
        "height": maxy - miny
    }


def get_polygon_centroid(polygon: Polygon) -> Tuple[float, float]:
    """
    Get centroid of polygon

    Returns:
        Tuple of (x, y) coordinates
    """
    centroid = polygon.centroid
    return (centroid.x, centroid.y)
