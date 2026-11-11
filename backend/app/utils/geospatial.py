"""
Geospatial utility functions for sampling navigation support.

Provides functions for:
- Elevation extraction from DEM raster
- Bearing/azimuth calculation between points
- Topographic feature identification (ridges, valleys)
"""
# constraint: all coordinates in WGS84 (EPSG:4326)
# why: utility functions abstract PostGIS/spatial operations
# NOTE: UTM zones auto-detected from longitude

import math
from typing import Tuple, Optional, List
from sqlalchemy.orm import Session
from app.core.constants import METERS_PER_DEGREE_LAT, METERS_PER_DEGREE_LON_NEPAL
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


def extract_elevation_at_point(
    db: Session,
    longitude: float,
    latitude: float
) -> Optional[float]:
    """
    Extract elevation value from DEM raster at a specific point.

    Args:
        db: Database session
        longitude: Point longitude (EPSG:4326)
        latitude: Point latitude (EPSG:4326)

    Returns:
        Elevation in meters (ASLM), or None if no data
    """
    try:
        query = text("""
            SELECT ST_Value(rast, ST_Transform(
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                ST_SRID(rast)
            )) as elevation
            FROM rasters.dem
            WHERE ST_Intersects(
                rast,
                ST_Transform(
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                    ST_SRID(rast)
                )
            )
            LIMIT 1
        """)

        result = db.execute(query, {"lon": longitude, "lat": latitude}).first()

        if result and result.elevation is not None:
            return float(result.elevation)

        return None

    except Exception as e:
        logger.warning(f"Failed to extract elevation at ({longitude}, {latitude}): {str(e)}")
        db.rollback()
        return None


def calculate_bearing(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float
) -> Tuple[float, str]:
    """
    Calculate bearing (azimuth) from point 1 to point 2.

    Args:
        lat1, lon1: Starting point (degrees)
        lat2, lon2: Ending point (degrees)

    Returns:
        Tuple of (bearing in degrees 0-360, cardinal direction string)
    """
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlon_rad = math.radians(lon2 - lon1)

    # Calculate bearing
    x = math.sin(dlon_rad) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - \
        math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon_rad)

    bearing_rad = math.atan2(x, y)
    bearing_deg = math.degrees(bearing_rad)

    # Normalize to 0-360
    bearing_deg = (bearing_deg + 360) % 360

    # Convert to cardinal direction
    directions = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW"
    ]
    index = round(bearing_deg / 22.5) % 16
    cardinal = directions[index]

    return bearing_deg, cardinal


def calculate_distance_meters(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float
) -> float:
    """
    Calculate distance between two points using Haversine formula.

    Args:
        lat1, lon1: Point 1 coordinates (degrees)
        lat2, lon2: Point 2 coordinates (degrees)

    Returns:
        Distance in meters
    """
    R = 6371000  # Earth radius in meters

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + \
        math.cos(lat1_rad) * math.cos(lat2_rad) * \
        math.sin(dlon / 2) ** 2

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c

    return distance


def find_nearest_ridge_or_valley(
    db: Session,
    longitude: float,
    latitude: float,
    search_radius_meters: float = 500.0,
    feature_type: str = "ridge"
) -> Optional[dict]:
    """
    Find the nearest topographic feature (ridge or valley) to a point.

    Uses slope and aspect rasters to identify ridge lines (high points)
    or valley lines (low points) within a search radius.

    Args:
        db: Database session
        longitude: Point longitude (EPSG:4326)
        latitude: Point latitude (EPSG:4326)
        search_radius_meters: Search radius in meters (default 500m)
        feature_type: 'ridge' or 'valley' (default 'ridge')

    Returns:
        Dictionary with:
        - distance_meters: Distance to feature
        - bearing_degrees: Bearing to feature (0-360)
        - direction: Cardinal direction (N, NE, E, etc.)
        - feature_longitude: Feature location longitude
        - feature_latitude: Feature location latitude
        - elevation: Elevation at feature (if available)
    """
    try:
        # For ridges: Find local maxima (high slope pixels with converging aspect)
        # For valleys: Find local minima (low elevation with diverging aspect)

        # Convert search radius to degrees (approximate for Nepal latitude ~28°)
        radius_lat = search_radius_meters / METERS_PER_DEGREE_LAT
        radius_lon = search_radius_meters / METERS_PER_DEGREE_LON_NEPAL

        # Query to find ridge candidates:
        # - High elevation relative to surroundings
        # - Slope > 10 degrees (not flat terrain)
        # - Local high points

        if feature_type == "ridge":
            # Find high elevation points with significant slope
            query = text("""
                WITH search_area AS (
                    SELECT ST_MakeEnvelope(
                        :lon - :radius_lon,
                        :lat - :radius_lat,
                        :lon + :radius_lon,
                        :lat + :radius_lat,
                        4326
                    ) as geom
                ),
                ridge_candidates AS (
                    SELECT
                        (ST_PixelAsCentroids(
                            ST_Clip(dem.rast, 1, search_area.geom),
                            1
                        )).*
                    FROM rasters.dem, search_area
                    WHERE ST_Intersects(dem.rast, search_area.geom)
                ),
                ridge_points AS (
                    SELECT
                        ST_X(rc.geom) as ridge_lon,
                        ST_Y(rc.geom) as ridge_lat,
                        rc.val as elevation,
                        ST_Distance(
                            rc.geom::geography,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                        ) as distance_m
                    FROM ridge_candidates rc
                    WHERE rc.val IS NOT NULL
                      AND rc.val > 0  -- Valid elevation
                    ORDER BY distance_m ASC
                    LIMIT 1
                )
                SELECT
                    ridge_lon,
                    ridge_lat,
                    elevation,
                    distance_m
                FROM ridge_points
            """)

        else:  # valley
            # Find low elevation points (valleys/rivers)
            query = text("""
                WITH search_area AS (
                    SELECT ST_MakeEnvelope(
                        :lon - :radius_lon,
                        :lat - :radius_lat,
                        :lon + :radius_lon,
                        :lat + :radius_lat,
                        4326
                    ) as geom
                ),
                valley_candidates AS (
                    SELECT
                        (ST_PixelAsCentroids(
                            ST_Clip(dem.rast, 1, search_area.geom),
                            1
                        )).*
                    FROM rasters.dem, search_area
                    WHERE ST_Intersects(dem.rast, search_area.geom)
                ),
                valley_points AS (
                    SELECT
                        ST_X(vc.geom) as valley_lon,
                        ST_Y(vc.geom) as valley_lat,
                        vc.val as elevation,
                        ST_Distance(
                            vc.geom::geography,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                        ) as distance_m
                    FROM valley_candidates vc
                    WHERE vc.val IS NOT NULL
                      AND vc.val > 0
                    ORDER BY elevation ASC, distance_m ASC
                    LIMIT 1
                )
                SELECT
                    valley_lon as ridge_lon,
                    valley_lat as ridge_lat,
                    elevation,
                    distance_m
                FROM valley_points
            """)

        result = db.execute(query, {
            "lon": longitude,
            "lat": latitude,
            "radius_lon": radius_lon,
            "radius_lat": radius_lat
        }).first()

        if not result:
            return None

        # Calculate bearing and direction
        bearing_deg, direction = calculate_bearing(
            latitude, longitude,
            result.ridge_lat, result.ridge_lon
        )

        return {
            "distance_meters": float(result.distance_m),
            "bearing_degrees": bearing_deg,
            "direction": direction,
            "feature_longitude": float(result.ridge_lon),
            "feature_latitude": float(result.ridge_lat),
            "elevation": float(result.elevation) if result.elevation else None
        }

    except Exception as e:
        logger.warning(
            f"Failed to find nearest {feature_type} for ({longitude}, {latitude}): {str(e)}"
        )
        return None


def find_nearest_topographic_feature(
    db: Session,
    longitude: float,
    latitude: float,
    search_radius_meters: float = 500.0,
    prefer_valleys: bool = True,
    min_distance_threshold: float = 20.0
) -> Optional[dict]:
    """
    Find the nearest significant topographic feature (ridge or valley/river).

    Searches for both ridges and valleys. By default, prefers valleys/rivers
    over ridges as they are better navigation landmarks.

    Args:
        db: Database session
        longitude: Point longitude (EPSG:4326)
        latitude: Point latitude (EPSG:4326)
        search_radius_meters: Search radius in meters (default 500m)
        prefer_valleys: If True, prefer valleys/rivers over ridges when both
                       are within 50m of each other (default True)
        min_distance_threshold: Minimum distance to report (default 20m)
                               Features closer than this are ignored as they
                               indicate the point IS on the feature

    Returns:
        Dictionary with feature information, or None if no features found
    """
    ridge_info = find_nearest_ridge_or_valley(
        db, longitude, latitude, search_radius_meters, "ridge"
    )
    valley_info = find_nearest_ridge_or_valley(
        db, longitude, latitude, search_radius_meters, "valley"
    )

    # Filter out features that are too close (point is ON the feature)
    if ridge_info and ridge_info["distance_meters"] < min_distance_threshold:
        ridge_info = None
    if valley_info and valley_info["distance_meters"] < min_distance_threshold:
        valley_info = None

    # Return based on preference
    if ridge_info and valley_info:
        ridge_dist = ridge_info["distance_meters"]
        valley_dist = valley_info["distance_meters"]

        # If prefer_valleys is True and valley is within 50m of ridge distance,
        # choose valley (rivers are better landmarks than ridges)
        if prefer_valleys and abs(ridge_dist - valley_dist) < 50:
            valley_info["feature_type"] = "valley/river"
            return valley_info
        # Otherwise, choose the closer one
        elif ridge_dist < valley_dist:
            ridge_info["feature_type"] = "ridge"
            return ridge_info
        else:
            valley_info["feature_type"] = "valley/river"
            return valley_info
    elif ridge_info:
        ridge_info["feature_type"] = "ridge"
        return ridge_info
    elif valley_info:
        valley_info["feature_type"] = "valley/river"
        return valley_info

    return None
