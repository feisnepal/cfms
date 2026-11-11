"""Map creation and geometry processing service.

Converts GeoJSON geometries to PostGIS-compatible WKT, validates
block boundaries against forest boundaries, calculates geodesic areas,
and manages the split/merge of forest blocks. Used during forest
boundary upload and block extraction.

Key functions:
    geojson_to_wkt() — GeoJSON → WKT with SRID
    validate_block_inside_boundary() — checks block containment

See also:
    app.api.forests — boundary upload endpoint
    app.utils.geometry_utils — low-level geometry helpers
"""

from typing import Dict, List, Any, Tuple
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from shapely.wkt import dumps as wkt_dumps
from geoalchemy2.shape import from_shape
import json
import logging
from ..utils.geometry_utils import calculate_area_geodesic_from_shapely
from .sub_area_service import enforce_within_and_disjoint

from app.core.dropped import report_dropped
from typing import Optional

logger = logging.getLogger(__name__)

# Geometry validation tolerance constants
TOLERANCE_DEGREES = 1e-8  # ~1mm at equator
AREA_RATIO_THRESHOLD = 0.9999  # 99.99% of block must be inside boundary


def geojson_to_wkt(geojson_geometry: Dict[str, Any]) -> str:
    """
    Convert GeoJSON geometry to WKT format for PostGIS storage

    Args:
        geojson_geometry: GeoJSON geometry dict (e.g., {"type": "Polygon", "coordinates": [...]})

    Returns:
        WKT string with SRID prefix
    """
    try:
        if not geojson_geometry:
            raise ValueError("GeoJSON geometry is None or empty")
        
        if not isinstance(geojson_geometry, dict):
            raise ValueError(f"GeoJSON geometry must be a dict, got {type(geojson_geometry)}")
        
        geom_type = geojson_geometry.get('type')
        if not geom_type:
            raise ValueError("GeoJSON geometry missing 'type' property")
        
        # Convert GeoJSON to Shapely geometry
        geom = shape(geojson_geometry)

        # Convert to WKT
        wkt = wkt_dumps(geom)

        # Add SRID prefix for PostGIS (WGS84 = 4326)
        return f'SRID=4326;{wkt}'
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to convert GeoJSON to WKT: {str(e)}")


def process_map_creation_data(
    outer_boundary: Dict[str, Any],
    blocks: List[Dict[str, Any]],
    gps_points: List[Dict[str, Any]] = None,
    sub_areas: List[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Process map creation data and prepare for database storage

    Args:
        outer_boundary: GeoJSON geometry of outer boundary
        blocks: List of block definitions with geometries
        gps_points: Optional list of GPS points used
        sub_areas: Optional list of sub-area definitions

    Returns:
        Tuple of (WKT geometry string, metadata dict)
    """
    try:
        # Convert outer boundary to WKT
        boundary_wkt = geojson_to_wkt(outer_boundary)

        # Prepare metadata structure
        metadata = {
            "creation_method": "map_creation",
            "total_blocks": len(blocks),
            "blocks": [],
        }

        # Process blocks
        for block in blocks:
            block_geom = shape(block["geometry"])
            block_data = {
                "block_id": block["id"],
                "block_name": block["name"],
                "area_hectares": block["area"],
                "geometry": block["geometry"],  # Store as GeoJSON
                "centroid": {
                    "lon": block_geom.centroid.x,
                    "lat": block_geom.centroid.y,
                },
            }
            metadata["blocks"].append(block_data)

        # Store GPS points metadata if provided
        if gps_points:
            metadata["gps_points"] = gps_points
            metadata["gps_points_count"] = len(gps_points)

        # Store sub-areas metadata if provided
        if sub_areas:
            # Convert outer boundary to shapely for clipping
            outer_geom = shape(outer_boundary)
            
            metadata["sub_areas"] = []
            excluded_area_total = 0
            # The wizard's sub-areas are placed one after another: each must lie
            # inside the outer boundary AND give way to those already kept.
            kept_union = None
            for sub_area in sub_areas:
                is_excluded = sub_area.get("isExcluded", False) or sub_area.get("is_excluded", False)
                
                # Clip sub-area to boundary
                sub_geom = shape(sub_area["geometry"])
                logger.info(f"[map_creation] Sub-area {sub_area.get('name')} original geometry type: {sub_geom.geom_type}")
                logger.info(f"[map_creation] Sub-area {sub_area.get('name')} original area: {sub_geom.area}")
                
                # Inside the boundary, polygon only, never overlapping a sub-area already kept
                # (the raw intersection can be a line / point / collection, and the wizard
                # used to let two sub-areas overlap each other).
                sub_area_geom, _refusal, _info = enforce_within_and_disjoint(sub_geom, outer_geom, kept_union)
                if sub_area_geom is None:
                    logger.warning(
                        f"Sub-area {sub_area.get('name', 'unknown')} skipped ({_refusal}): "
                        "nothing of it lies inside the boundary and clear of the other sub-areas"
                    )
                    continue
                kept_union = sub_area_geom if kept_union is None else unary_union([kept_union, sub_area_geom])

                # Calculate area using proper UTM projection (geodesic calculation)
                sub_area_area_sqm, sub_area_area_ha = calculate_area_geodesic_from_shapely(sub_area_geom)

                logger.info(f"[map_creation] Sub-area {sub_area.get('name')} clipped area: {sub_area_area_ha} ha")
                
                sub_area_data = {
                    "id": sub_area["id"],
                    "name": sub_area["name"],
                    "category": sub_area["category"],
                    "area_hectares": round(sub_area_area_ha, 4),
                    "area_sqm": round(sub_area_area_sqm, 4),
                    "block_id": sub_area.get("blockId"),
                    "block_name": sub_area.get("blockName"),
                    "blockBreakdown": sub_area.get("blockBreakdown"),  # Preserve cross-block breakdown
                    "geometry": mapping(sub_area_geom),  # Store clipped geometry
                    "is_excluded": is_excluded,
                }
                metadata["sub_areas"].append(sub_area_data)

                # Track excluded area
                if is_excluded:
                    excluded_area_total += sub_area_area_ha

            metadata["sub_areas_count"] = len(sub_areas)
            metadata["excluded_area_hectares"] = excluded_area_total

        return boundary_wkt, metadata

    except Exception as e:
        raise ValueError(f"Failed to process map creation data: {str(e)}")


def validate_map_creation_data(
    outer_boundary: Dict[str, Any],
    blocks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Validate map creation data before processing

    Args:
        outer_boundary: GeoJSON geometry of outer boundary
        blocks: List of block definitions

    Returns:
        Validation result dict with 'valid' boolean and optional 'errors' list
    """
    errors = []

    try:
        # Validate outer boundary
        outer_geom = shape(outer_boundary)
        if not outer_geom.is_valid:
            errors.append("Outer boundary geometry is invalid")

        if outer_geom.area == 0:
            errors.append("Outer boundary has zero area")

        # Validate blocks
        if len(blocks) == 0:
            errors.append("At least one block is required")

        for i, block in enumerate(blocks):
            try:
                block_geom = shape(block["geometry"])

                if not block_geom.is_valid:
                    errors.append(f"Block '{block['name']}' has invalid geometry")

                if block_geom.area == 0:
                    errors.append(f"Block '{block['name']}' has zero area")

                # Check if block is within outer boundary with tolerance
                # Use multi-layer validation to handle floating-point precision issues
                is_valid = False
                validation_method = ""

                # Method 1: Strict containment (fastest)
                if block_geom.within(outer_geom):
                    is_valid = True
                    validation_method = "strict_within"
                else:
                    # Method 2: Area ratio comparison (handles microscopic overflow)
                    try:
                        intersection = block_geom.intersection(outer_geom)
                        if block_geom.area > 0:
                            area_ratio = intersection.area / block_geom.area
                            if area_ratio >= AREA_RATIO_THRESHOLD:
                                is_valid = True
                                validation_method = f"area_ratio ({area_ratio:.6f})"
                                logger.info(f"Block '{block['name']}' passed via area ratio: {area_ratio:.6f}")
                    except Exception as e:
                        logger.warning(f"Area ratio check failed for '{block['name']}': {e}")

                    # Method 3: Buffered tolerance check (last resort)
                    if not is_valid:
                        try:
                            # Create a slightly expanded outer boundary
                            buffered_outer = outer_geom.buffer(TOLERANCE_DEGREES)
                            if block_geom.within(buffered_outer):
                                # Double-check it's not significantly outside
                                outside_part = block_geom.difference(outer_geom)
                                if outside_part.area < 1e-6:  # Less than ~0.01 m²
                                    is_valid = True
                                    validation_method = "tolerance_buffer"
                                    logger.info(f"Block '{block['name']}' passed via buffer tolerance")
                        except Exception as e:
                            logger.warning(f"Buffer tolerance check failed for '{block['name']}': {e}")

                if not is_valid:
                    # Calculate how far outside it is for debugging
                    try:
                        outside_part = block_geom.difference(outer_geom)
                        outside_area = outside_part.area if hasattr(outside_part, 'area') else 0
                        logger.error(
                            f"Block '{block['name']}' validation failed - "
                            f"Area outside: {outside_area:.10f} sq degrees, "
                            f"Block area: {block_geom.area:.10f} sq degrees"
                        )
                    except Exception:
                        logger.warning(
                            "could not measure how far block %s falls outside the boundary",
                            block.get('name'), exc_info=True,
                        )
                    errors.append(f"Block '{block['name']}' extends outside outer boundary")

            except Exception as e:
                logger.exception(
                    "block %s could not be validated - it is reported as invalid",
                    block.get('name'),
                )
                errors.append(f"Error validating block {i+1}: {str(e)}")

        # Check for block overlaps
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                try:
                    geom1 = shape(blocks[i]["geometry"])
                    geom2 = shape(blocks[j]["geometry"])

                    if geom1.intersects(geom2):
                        intersection = geom1.intersection(geom2)
                        if intersection.area > 0.0001:  # Tolerance
                            errors.append(
                                f"Blocks '{blocks[i]['name']}' and '{blocks[j]['name']}' overlap"
                            )
                except Exception:
                    report_dropped(
                        logger, "overlap test",
                        "the pair is reported as not overlapping, so a real overlap can "
                        "pass validation",
                    )

        return {
            "valid": len(errors) == 0,
            "errors": errors if errors else None,
        }

    except Exception as e:
        logger.exception("map validation raised - reporting the map invalid")
        return {
            "valid": False,
            "errors": [f"Validation failed: {str(e)}"],
        }


def process_as_compartments(
    blocks: List[Dict[str, Any]],
    forest_name: str,
    compartment_code_column: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Process uploaded polygons as compartments instead of blocks.

    Creates a result_data structure with:
        - compartments: list of compartment dicts with GeoJSON geometries
        - blocks: reference list with a single parent block (union of all compartments)
        - sampling_unit: 'compartment'
        - total_compartments: count

    The parent block geometry is computed as ST_Union at DB-insert time.
    """
    compartments = []
    total_area = 0.0

    for index, block in enumerate(blocks):
        geom = shape(block["geometry"])
        area_ha = block.get("area", 0) or block.get("area_hectares", 0)
        if not area_ha:
            area_sqm, area_ha = calculate_area_geodesic_from_shapely(geom)

        compartment = {
            "block_index": index,
            "block_name": block["name"],
            "block_id": block.get("id", f"comp-{index}"),
            "area_hectares": round(area_ha, 4),
            "geometry": block["geometry"],
            "is_compartment": True,
            "division_level": 1,
            "compartment_code": (
                block.get(compartment_code_column, block["name"])
                if compartment_code_column
                else block["name"]
            ),
            "centroid": {
                "lon": geom.centroid.x,
                "lat": geom.centroid.y,
            },
        }
        compartments.append(compartment)
        total_area += area_ha

    return {
        "total_compartments": len(compartments),
        "compartments": compartments,
        "total_blocks": 1,
        "blocks": [
            {
                "block_index": 0,
                "block_name": forest_name or "Forest",
                "area_hectares": round(total_area, 4),
                "is_virtual_parent": True,
            }
        ],
        "sampling_unit": "compartment",
        "area_hectares": round(total_area, 4),
    }


def prepare_block_analysis_data(
    blocks: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Prepare block data in the format expected by the analysis service

    Args:
        blocks: List of block definitions from map creation

    Returns:
        List of block data dicts ready for analysis
    """
    prepared_blocks = []

    for index, block in enumerate(blocks):
        try:
            geom = shape(block["geometry"])

            prepared_block = {
                "block_index": index,
                "block_name": block["name"],
                "block_id": block["id"],
                "area_hectares": block["area"],
                "geometry": block["geometry"],  # GeoJSON
                "centroid": {
                    "lon": geom.centroid.x,
                    "lat": geom.centroid.y,
                },
            }

            prepared_blocks.append(prepared_block)

        except Exception as e:
            raise ValueError(f"Failed to prepare block '{block['name']}': {str(e)}")

    return prepared_blocks
