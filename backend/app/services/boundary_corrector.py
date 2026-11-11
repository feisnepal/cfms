"""
Boundary Correction Service
Snaps out-of-boundary points to nearest location on polygon boundary
"""
# why: self-intersection repair using Shapely buffer(0)
# constraint: tolerance 1e-8 degrees (~1mm at equator)
# NOTE: corrections shown as preview before apply

from typing import List, Tuple, Dict
from shapely import wkt
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.ops import nearest_points
import pandas as pd
import math
import logging

logger = logging.getLogger(__name__)


def haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """
    Calculate distance between two points in meters using Haversine formula

    Args:
        lon1, lat1: First point (longitude, latitude)
        lon2, lat2: Second point (longitude, latitude)

    Returns:
        Distance in meters
    """
    # Earth radius in meters
    R = 6371000

    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    # Haversine formula
    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) *
         math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c
    return distance


def snap_point_to_polygon(
    lon: float,
    lat: float,
    polygon_wkt: str
) -> Tuple[float, float, float]:
    """
    Snap a point to the nearest location on polygon boundary

    Args:
        lon: Longitude of point
        lat: Latitude of point
        polygon_wkt: WKT string of boundary polygon

    Returns:
        Tuple of (corrected_lon, corrected_lat, distance_meters)
    """
    try:
        # Create point
        point = Point(lon, lat)

        # Parse polygon
        polygon = wkt.loads(polygon_wkt)

        # Handle MultiPolygon
        if isinstance(polygon, MultiPolygon):
            polygon = polygon.buffer(0)  # Union into single polygon

        # Get polygon boundary (exterior ring)
        boundary = polygon.boundary

        # Find nearest point on boundary
        nearest_geom = nearest_points(point, boundary)[1]

        corrected_lon = nearest_geom.x
        corrected_lat = nearest_geom.y

        # Calculate distance moved
        distance_meters = haversine_distance(lon, lat, corrected_lon, corrected_lat)

        logger.debug(
            f"Snapped point ({lon:.6f}, {lat:.6f}) -> "
            f"({corrected_lon:.6f}, {corrected_lat:.6f}), "
            f"moved {distance_meters:.2f}m"
        )

        return (corrected_lon, corrected_lat, distance_meters)

    except Exception as e:
        logger.error(f"Error snapping point: {str(e)}")
        raise ValueError(f"SNAP_FAILED: सीमा मा बिन्दु स्नेप गर्न असफल: {str(e)}")


def generate_correction_preview(
    df: pd.DataFrame,
    boundary_wkt: str,
    out_of_boundary_points: List[Dict],
    coord_x_col: str,
    coord_y_col: str,
    species_col: str = 'Species'
) -> Dict:
    """
    Generate preview of proposed corrections for out-of-boundary points

    Args:
        df: DataFrame with tree data
        boundary_wkt: WKT string of boundary
        out_of_boundary_points: List of out-of-boundary point info
        coord_x_col: Name of X coordinate column
        coord_y_col: Name of Y coordinate column
        species_col: Name of species column

    Returns:
        {
            'corrections': [
                {
                    'row_number': int,
                    'species': str,
                    'original_x': float,
                    'original_y': float,
                    'corrected_x': float,
                    'corrected_y': float,
                    'distance_moved_meters': float
                },
                ...
            ],
            'summary': {
                'total_corrections': int,
                'max_distance': float,
                'min_distance': float,
                'avg_distance': float
            }
        }
    """
    corrections = []
    distances = []

    for point_info in out_of_boundary_points:
        row_number = point_info['row_number']
        original_x = point_info['longitude']
        original_y = point_info['latitude']
        index = point_info['index']

        # Get species from dataframe
        species = df.iloc[index][species_col] if species_col in df.columns else 'Unknown'

        # Snap point to boundary
        try:
            corrected_x, corrected_y, distance = snap_point_to_polygon(
                original_x,
                original_y,
                boundary_wkt
            )

            correction = {
                'row_number': row_number,
                'species': str(species),
                'original_x': float(original_x),
                'original_y': float(original_y),
                'corrected_x': float(corrected_x),
                'corrected_y': float(corrected_y),
                'distance_moved_meters': round(distance, 2)
            }

            corrections.append(correction)
            distances.append(distance)

        except Exception as e:
            logger.error(f"Failed to correct row {row_number}: {str(e)}")
            continue

    # Calculate summary statistics
    summary = {
        'total_corrections': len(corrections),
        'max_distance': round(max(distances), 2) if distances else 0.0,
        'min_distance': round(min(distances), 2) if distances else 0.0,
        'avg_distance': round(sum(distances) / len(distances), 2) if distances else 0.0
    }

    logger.info(
        f"Generated {len(corrections)} corrections: "
        f"avg={summary['avg_distance']:.2f}m, "
        f"max={summary['max_distance']:.2f}m"
    )

    return {
        'corrections': corrections,
        'summary': summary
    }


def apply_corrections_to_dataframe(
    df: pd.DataFrame,
    corrections: List[Dict],
    coord_x_col: str,
    coord_y_col: str
) -> pd.DataFrame:
    """
    Apply boundary corrections to DataFrame

    Args:
        df: Original DataFrame
        corrections: List of correction dicts
        coord_x_col: Name of X coordinate column
        coord_y_col: Name of Y coordinate column

    Returns:
        Modified DataFrame with corrected coordinates
    """
    df_corrected = df.copy()

    # Create mapping of row_number to correction
    corrections_map = {c['row_number']: c for c in corrections}

    # Apply corrections
    for idx, row in df_corrected.iterrows():
        # Assuming df has a column that maps to row_number (1-indexed)
        # If your CSV has row numbers starting at 1, use idx + 1
        row_num = idx + 1  # Adjust if needed

        if row_num in corrections_map:
            correction = corrections_map[row_num]
            df_corrected.at[idx, coord_x_col] = correction['corrected_x']
            df_corrected.at[idx, coord_y_col] = correction['corrected_y']

            logger.debug(f"Applied correction to row {row_num}")

    return df_corrected


def validate_corrections(
    corrections: List[Dict],
    max_distance_meters: float = 50.0
) -> Dict:
    """
    Validate that corrections are reasonable

    Args:
        corrections: List of corrections
        max_distance_meters: Maximum acceptable distance to move a point

    Returns:
        {
            'valid': bool,
            'warnings': List[str]
        }
    """
    warnings = []

    for correction in corrections:
        distance = correction['distance_moved_meters']

        if distance > max_distance_meters:
            warnings.append(
                f"CORRECTION_DISTANCE_EXCEEDED: पंक्ति {correction['row_number']} ({correction['species']}): "
                f"ठूलो सुधार दूरी: {distance:.1f}मि"
            )

    return {
        'valid': len(warnings) == 0,
        'warnings': warnings
    }
