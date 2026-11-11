"""
Geospatial utilities using ACTUAL vector ridge and river data.

This replaces the DEM-based ridge detection with proper vector layer queries.
"""
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


def find_nearest_ridge_vector(
    db: Session,
    longitude: float,
    latitude: float,
    search_radius_meters: float = 1000.0
) -> Optional[dict]:
    """
    Find nearest ridge line using vector ridge layer (river.ridge).

    Args:
        db: Database session
        longitude: Point longitude (EPSG:4326)
        latitude: Point latitude (EPSG:4326)
        search_radius_meters: Search radius in meters (default 1000m)

    Returns:
        Dictionary with ridge information, or None if no ridge found
    """
    try:
        query = text("""
            SELECT
                ridge_name,
                ST_Distance(
                    geom::geography,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                ) as distance_m,
                ST_X(ST_ClosestPoint(
                    geom,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                )) as closest_lon,
                ST_Y(ST_ClosestPoint(
                    geom,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                )) as closest_lat,
                "length meter" as ridge_length_m
            FROM river.ridge
            WHERE ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :radius
            )
            ORDER BY distance_m ASC
            LIMIT 1
        """)

        result = db.execute(query, {
            "lon": longitude,
            "lat": latitude,
            "radius": search_radius_meters
        }).first()

        if not result:
            return None

        # Import bearing calculation from geospatial.py
        from app.utils.geospatial import calculate_bearing

        # Calculate bearing and direction from point to ridge
        bearing_deg, direction = calculate_bearing(
            latitude, longitude,
            result.closest_lat, result.closest_lon
        )

        return {
            "feature_type": "ridge",
            "feature_name": result.ridge_name or "unnamed ridge",
            "distance_meters": float(result.distance_m),
            "bearing_degrees": bearing_deg,
            "direction": direction,
            "feature_longitude": float(result.closest_lon),
            "feature_latitude": float(result.closest_lat),
            "feature_length_m": int(result.ridge_length_m) if result.ridge_length_m else None
        }

    except Exception as e:
        logger.warning(f"Failed to find nearest ridge for ({longitude}, {latitude}): {str(e)}")
        return None


def find_nearest_river_vector(
    db: Session,
    longitude: float,
    latitude: float,
    search_radius_meters: float = 1000.0
) -> Optional[dict]:
    """
    Find nearest river line using vector river layer (river.river_line).

    Args:
        db: Database session
        longitude: Point longitude (EPSG:4326)
        latitude: Point latitude (EPSG:4326)
        search_radius_meters: Search radius in meters (default 1000m)

    Returns:
        Dictionary with river information, or None if no river found
    """
    try:
        query = text("""
            SELECT
                river_name,
                sub_river_system,
                ST_Distance(
                    geom::geography,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                ) as distance_m,
                ST_X(ST_ClosestPoint(
                    geom,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                )) as closest_lon,
                ST_Y(ST_ClosestPoint(
                    geom,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                )) as closest_lat,
                "length meter" as river_length_m
            FROM river.river_line
            WHERE ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :radius
            )
            ORDER BY distance_m ASC
            LIMIT 1
        """)

        result = db.execute(query, {
            "lon": longitude,
            "lat": latitude,
            "radius": search_radius_meters
        }).first()

        if not result:
            return None

        # Import bearing calculation from geospatial.py
        from app.utils.geospatial import calculate_bearing

        # Calculate bearing and direction from point to river
        bearing_deg, direction = calculate_bearing(
            latitude, longitude,
            result.closest_lat, result.closest_lon
        )

        # Determine display name
        if result.river_name and result.river_name.strip():
            feature_name = result.river_name.strip()
        else:
            feature_name = "unnamed stream"

        return {
            "feature_type": "river",
            "feature_name": feature_name,
            "sub_river_system": result.sub_river_system,
            "distance_meters": float(result.distance_m),
            "bearing_degrees": bearing_deg,
            "direction": direction,
            "feature_longitude": float(result.closest_lon),
            "feature_latitude": float(result.closest_lat),
            "feature_length_m": int(result.river_length_m) if result.river_length_m else None
        }

    except Exception as e:
        logger.warning(f"Failed to find nearest river for ({longitude}, {latitude}): {str(e)}")
        return None


def find_nearest_topographic_feature_vector(
    db: Session,
    longitude: float,
    latitude: float,
    search_radius_meters: float = 1000.0,
    prefer_rivers: bool = True,
    min_distance_threshold: float = 20.0
) -> Optional[dict]:
    """
    Find nearest topographic feature using VECTOR ridge and river layers.

    This is the CORRECT implementation using actual vector data instead of DEM analysis.

    Args:
        db: Database session
        longitude: Point longitude (EPSG:4326)
        latitude: Point latitude (EPSG:4326)
        search_radius_meters: Search radius in meters (default 1000m)
        prefer_rivers: Prefer rivers over ridges when both are close (default True)
        min_distance_threshold: Minimum distance to report (default 20m)

    Returns:
        Dictionary with feature information including NAME, or None if not found
    """
    # Query both ridge and river layers
    ridge_info = find_nearest_ridge_vector(db, longitude, latitude, search_radius_meters)
    river_info = find_nearest_river_vector(db, longitude, latitude, search_radius_meters)

    # Filter out features that are too close (point is ON the feature)
    if ridge_info and ridge_info["distance_meters"] < min_distance_threshold:
        ridge_info = None
    if river_info and river_info["distance_meters"] < min_distance_threshold:
        river_info = None

    # Return based on preference
    if ridge_info and river_info:
        ridge_dist = ridge_info["distance_meters"]
        river_dist = river_info["distance_meters"]

        # If prefer_rivers is True and river is within 100m of ridge distance,
        # choose river (rivers are better landmarks)
        if prefer_rivers and abs(ridge_dist - river_dist) < 100:
            return river_info
        # Otherwise, choose the closer one
        elif ridge_dist < river_dist:
            return ridge_info
        else:
            return river_info
    elif ridge_info:
        return ridge_info
    elif river_info:
        return river_info

    return None
