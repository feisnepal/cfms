"""
Boundary Validation Service
Checks if tree coordinates fall within forest boundary polygon
"""
# business: CFMG — uploaded boundary must be valid polygon
# constraint: GeoJSON with SRID 4326 required
# why: validates before DB insert to avoid corrupt geometries

from typing import List, Tuple, Dict
from shapely import wkt
from shapely.geometry import Point, Polygon, MultiPolygon, GeometryCollection
from shapely.ops import unary_union
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
import logging

from app.models.calculation import Calculation

logger = logging.getLogger(__name__)


def check_points_in_boundary(
    points: List[Tuple[float, float, int]],  # [(lon, lat, row_number), ...]
    boundary_geom_wkt: str,
    tolerance_percent: float = 20.0
) -> Dict:
    """
    Check if tree points fall within boundary polygon

    Args:
        points: List of (longitude, latitude, row_number) tuples
        boundary_geom_wkt: WKT string of boundary polygon
        tolerance_percent: Maximum acceptable percentage of out-of-boundary points

    Returns:
        {
            'total_points': int,
            'out_of_boundary_count': int,
            'out_of_boundary_percentage': float,
            'within_tolerance': bool,
            'out_of_boundary_points': [
                {
                    'row_number': int,
                    'longitude': float,
                    'latitude': float,
                    'index': int  # Index in original points list
                },
                ...
            ]
        }
    """
    if not points:
        return {
            'total_points': 0,
            'out_of_boundary_count': 0,
            'out_of_boundary_percentage': 0.0,
            'within_tolerance': True,
            'out_of_boundary_points': []
        }

    try:
        # Parse boundary geometry
        boundary = wkt.loads(boundary_geom_wkt)

        # Handle GeometryCollection — extract only polygonal parts
        if isinstance(boundary, GeometryCollection):
            polygonal = [g for g in boundary.geoms
                         if g.geom_type in ('Polygon', 'MultiPolygon') and not g.is_empty]
            if not polygonal:
                raise ValueError("BOUNDARY_EMPTY: GeometryCollection मा कुनै वैध बहुभुज ज्यामिति छैन")
            if len(polygonal) == 1:
                boundary = polygonal[0]
            else:
                boundary = unary_union(polygonal)

        # Handle MultiPolygon (union all polygons)
        if isinstance(boundary, MultiPolygon):
            boundary = boundary.buffer(0)  # Fix any invalid geometries
        elif not isinstance(boundary, Polygon):
            raise ValueError(f"BOUNDARY_TYPE_INVALID: सीमा Polygon वा MultiPolygon हुनुपर्छ, पाइयो {type(boundary)}")

        total_points = len(points)
        out_of_boundary_points = []

        # Check each point
        for idx, (lon, lat, row_num) in enumerate(points):
            point = Point(lon, lat)

            # Check if point is within boundary
            if not boundary.contains(point):
                out_of_boundary_points.append({
                    'row_number': row_num,
                    'longitude': lon,
                    'latitude': lat,
                    'index': idx
                })

        out_of_boundary_count = len(out_of_boundary_points)
        out_of_boundary_percentage = (out_of_boundary_count / total_points * 100) if total_points > 0 else 0.0
        within_tolerance = out_of_boundary_percentage <= tolerance_percent

        result = {
            'total_points': total_points,
            'out_of_boundary_count': out_of_boundary_count,
            'out_of_boundary_percentage': round(out_of_boundary_percentage, 2),
            'within_tolerance': within_tolerance,
            'out_of_boundary_points': out_of_boundary_points
        }

        logger.info(
            f"Boundary check: {out_of_boundary_count}/{total_points} points outside "
            f"({out_of_boundary_percentage:.2f}%) - {'PASS' if within_tolerance else 'FAIL'}"
        )

        return result

    except Exception as e:
        logger.error(f"Error checking boundary: {str(e)}")
        raise ValueError(f"BOUNDARY_CHECK_FAILED: सीमा जाँच असफल: {str(e)}")


def get_boundary_from_calculation(
    db: Session,
    calculation_id: UUID
) -> str:
    """
    Get boundary geometry WKT from calculation

    Args:
        db: Database session
        calculation_id: UUID of calculation

    Returns:
        WKT string of boundary geometry
    """
    try:
        # Query calculation with geometry as WKT
        result = db.query(
            func.ST_AsText(Calculation.boundary_geom).label('wkt')
        ).filter(
            Calculation.id == calculation_id
        ).first()

        if not result:
            raise ValueError(f"Calculation {calculation_id} not found")

        if not result.wkt:
            raise ValueError(f"Calculation {calculation_id} has no boundary geometry")

        return result.wkt

    except Exception as e:
        logger.error(f"Error getting boundary: {str(e)}")
        raise


def validate_inventory_boundary(
    db: Session,
    calculation_id: UUID,
    tree_points: List[Tuple[float, float, int]],
    tolerance_percent: float = 20.0
) -> Dict:
    """
    Complete boundary validation for tree inventory

    Args:
        db: Database session
        calculation_id: UUID of calculation with boundary
        tree_points: List of (lon, lat, row_number) for trees
        tolerance_percent: Max acceptable out-of-boundary percentage

    Returns:
        Validation result dict with:
        - boundary check results
        - needs_correction: bool
        - error_message: str if validation fails
    """
    try:
        # Get boundary geometry
        boundary_wkt = get_boundary_from_calculation(db, calculation_id)

        # Check points
        check_result = check_points_in_boundary(
            tree_points,
            boundary_wkt,
            tolerance_percent
        )

        # Determine if correction is needed
        needs_correction = (
            check_result['out_of_boundary_count'] > 0 and
            check_result['within_tolerance']
        )

        # Build response
        result = {
            **check_result,
            'needs_correction': needs_correction,
            'boundary_wkt': boundary_wkt
        }

        if not check_result['within_tolerance']:
            result['error_message'] = (
                f"{check_result['out_of_boundary_percentage']}% of trees are outside the boundary. "
                f"This exceeds the {tolerance_percent}% tolerance. "
                f"Please check your data: verify coordinates, EPSG code, and boundary selection."
            )

        return result

    except Exception as e:
        logger.error(f"Boundary validation error: {str(e)}")
        return {
            'total_points': len(tree_points),
            'out_of_boundary_count': 0,
            'out_of_boundary_percentage': 0.0,
            'within_tolerance': False,
            'out_of_boundary_points': [],
            'needs_correction': False,
            'error_message': f"Boundary validation failed: {str(e)}"
        }
