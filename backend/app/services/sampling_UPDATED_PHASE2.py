"""
Sampling design service for forest inventory
Implements systematic, random, and stratified sampling algorithms
# NOTE: Phase 2 updated version of sampling.py — kept alongside original for migration
# business: CFMG §X.Y — updated sampling protocol with accessible forest filtering
# constraint: plot sizes per revised CFMG guidelines — Pole=100m², Tree=500m², Sapling=25m²

Phase 2: Enhanced with accessible forest filtering
"""
import random
import math
from typing import List, Tuple, Optional
from decimal import Decimal
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import text
from shapely import wkt
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.ops import unary_union
import logging

from app.core.constants import SQM_PER_HA
from app.models.calculation import Calculation
from app.models.sampling import SamplingDesign
from app.schemas.sampling import SamplingGenerateResponse, BlockSamplingInfo
from app.services.tree_cover_analysis import (
    calculate_accessible_forest_area,
    extract_accessible_forest_mask
)

logger = logging.getLogger(__name__)


def get_polygon_bounds(geom_wkt: str) -> Tuple[float, float, float, float]:
    # why: bounding box used to constrain grid generation — reduces search space
    """
    Get bounding box of polygon.

    Args:
        geom_wkt: WKT string of polygon

    Returns:
        Tuple of (min_lon, min_lat, max_lon, max_lat)
    """
    geom = wkt.loads(geom_wkt)
    bounds = geom.bounds  # (minx, miny, maxx, maxy)
    return bounds


def calculate_polygon_area_hectares(geom_wkt: str) -> float:
    """
    Calculate polygon area in hectares using UTM projection.

    Args:
        geom_wkt: WKT string of polygon

    Returns:
        Area in hectares
    """
    # This is a simplified calculation - actual implementation uses PostGIS
    geom = wkt.loads(geom_wkt)

    # Get centroid to determine UTM zone
    centroid = geom.centroid
    lon = centroid.x

    # Determine UTM SRID
    if lon < 84.0:
        utm_srid = 32644
    else:
        utm_srid = 32645

    # Area calculation will be done via PostGIS
    return 0.0  # Placeholder


def apply_boundary_buffer(polygon_wkt: str, buffer_meters: float = 50.0) -> str:
    """
    Apply inward buffer to polygon to keep sampling points away from boundary.

    Uses accurate UTM projection for Nepal.

    Args:
        polygon_wkt: WKT of polygon in EPSG:4326
        buffer_meters: Buffer distance in meters (negative = inward)

    Returns:
        WKT of buffered polygon in EPSG:4326
    """
    from shapely import wkt as shapely_wkt
    from shapely.ops import transform
    from pyproj import Transformer

    polygon = shapely_wkt.loads(polygon_wkt)
    centroid = polygon.centroid

    # Determine UTM zone for Nepal (44N or 45N)
    utm_zone = 44 if centroid.x < 84.0 else 45
    utm_epsg = f"EPSG:326{utm_zone}"

    # Create transformers
    to_utm = Transformer.from_crs("EPSG:4326", utm_epsg, always_xy=True)
    to_wgs84 = Transformer.from_crs(utm_epsg, "EPSG:4326", always_xy=True)

    # Transform to UTM, apply buffer, transform back
    polygon_utm = transform(to_utm.transform, polygon)
    buffered_utm = polygon_utm.buffer(-buffer_meters)  # Negative buffer = inward
    buffered_wgs84 = transform(to_wgs84.transform, buffered_utm)

    # Check if buffer resulted in empty geometry
    if buffered_wgs84.is_empty or buffered_wgs84.area == 0:
        logger.warning(f"Buffer of {buffer_meters}m resulted in empty polygon - using original")
        return polygon_wkt

    return buffered_wgs84.wkt


def generate_systematic_grid(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    grid_spacing_meters: int,
    polygon_wkt: str,
    boundary_buffer_meters: float = 50.0
) -> List[Tuple[float, float]]:
    # business: systematic grid is the CFMG default method — 200m × 250m spacing
    # constraint: boundary_buffer=50m avoids edge effects (roads, trails, canopy edge)
    """
    Generate systematic grid of points within polygon.

    Enforces minimum distance from boundary to avoid edge effects.

    Args:
        min_lon, min_lat, max_lon, max_lat: Bounding box
        grid_spacing_meters: Grid spacing in meters
        polygon_wkt: WKT of polygon to constrain points
        boundary_buffer_meters: Minimum distance from boundary (default 50m)

    Returns:
        List of (lon, lat) tuples
    """
    # Apply boundary buffer to keep points away from edge
    buffered_polygon_wkt = apply_boundary_buffer(polygon_wkt, boundary_buffer_meters)

    # Convert grid spacing to approximate degrees
    # At Nepal's latitude (~28°), 1 degree latitude ≈ 111 km
    # 1 degree longitude ≈ 111 km * cos(28°) ≈ 98 km
    meters_per_degree_lat = 111000.0
    meters_per_degree_lon = 98000.0

    spacing_lat = grid_spacing_meters / meters_per_degree_lat
    spacing_lon = grid_spacing_meters / meters_per_degree_lon

    # Load buffered polygon for intersection testing
    polygon = wkt.loads(buffered_polygon_wkt)

    # Generate grid points
    points = []
    lat = min_lat
    while lat <= max_lat:
        lon = min_lon
        while lon <= max_lon:
            point = Point(lon, lat)
            if polygon.contains(point):
                points.append((lon, lat))
            lon += spacing_lon
        lat += spacing_lat

    logger.info(f"Generated {len(points)} systematic grid points")
    return points


def generate_random_points(
    polygon_wkt: str,
    num_points: int,
    min_distance_meters: Optional[int] = None,
    boundary_buffer_meters: float = 50.0
) -> List[Tuple[float, float]]:
    """
    Generate random points within polygon.

    Enforces minimum distance from boundary to avoid edge effects.

    Args:
        polygon_wkt: WKT of polygon
        num_points: Number of points to generate
        min_distance_meters: Minimum distance between points (optional)
        boundary_buffer_meters: Minimum distance from boundary (default 50m)

    Returns:
        List of (lon, lat) tuples
    """
    # Apply boundary buffer to keep points away from edge
    buffered_polygon_wkt = apply_boundary_buffer(polygon_wkt, boundary_buffer_meters)
    polygon = wkt.loads(buffered_polygon_wkt)
    minx, miny, maxx, maxy = polygon.bounds

    points = []
    attempts = 0
    max_attempts = num_points * 100  # Prevent infinite loop

    while len(points) < num_points and attempts < max_attempts:
        attempts += 1

        # Generate random point in bounding box
        lon = random.uniform(minx, maxx)
        lat = random.uniform(miny, maxy)
        point = Point(lon, lat)

        # Check if point is within polygon
        if not polygon.contains(point):
            continue

        # Check minimum distance constraint
        if min_distance_meters and points:
            min_dist_deg = min_distance_meters / 111000.0  # Approximate
            too_close = False
            for existing_lon, existing_lat in points:
                dist = math.sqrt((lon - existing_lon)**2 + (lat - existing_lat)**2)
                if dist < min_dist_deg:
                    too_close = True
                    break
            if too_close:
                continue

        points.append((lon, lat))

    logger.info(f"Generated {len(points)} random points in {attempts} attempts")
    return points


def generate_stratified_points(
    polygon_wkt: str,
    num_points: int,
    num_strata: int = 4,
    boundary_buffer_meters: float = 50.0
) -> List[Tuple[float, float]]:
    # business: stratified sampling used when blocks have heterogeneous land cover
    # constraint: grid-based strata (num_strata=4 default) — ensures spatial distribution
    """
    Generate stratified random points within polygon.
    Divides polygon into grid strata and samples from each.
    Enforces minimum distance from boundary to avoid edge effects.

    Args:
        polygon_wkt: WKT of polygon
        num_points: Total number of points to generate
        num_strata: Number of strata (grid cells) to divide polygon into
        boundary_buffer_meters: Minimum distance from boundary (default 50m)

    Returns:
        List of (lon, lat) tuples
    """
    # Apply boundary buffer to keep points away from edge
    buffered_polygon_wkt = apply_boundary_buffer(polygon_wkt, boundary_buffer_meters)
    polygon = wkt.loads(buffered_polygon_wkt)
    minx, miny, maxx, maxy = polygon.bounds

    # Calculate grid dimensions
    grid_size = int(math.sqrt(num_strata))
    dx = (maxx - minx) / grid_size
    dy = (maxy - miny) / grid_size

    # Points per stratum
    points_per_stratum = num_points // num_strata
    extra_points = num_points % num_strata

    points = []

    # Generate points for each stratum
    for i in range(grid_size):
        for j in range(grid_size):
            stratum_minx = minx + i * dx
            stratum_maxx = minx + (i + 1) * dx
            stratum_miny = miny + j * dy
            stratum_maxy = miny + (j + 1) * dy

            # Create stratum polygon
            stratum_box = Polygon([
                (stratum_minx, stratum_miny),
                (stratum_maxx, stratum_miny),
                (stratum_maxx, stratum_maxy),
                (stratum_minx, stratum_maxy),
                (stratum_minx, stratum_miny)
            ])

            # Intersect with original polygon
            try:
                stratum = polygon.intersection(stratum_box)
                if stratum.is_empty:
                    continue

                # Number of points for this stratum
                n_points = points_per_stratum
                if extra_points > 0:
                    n_points += 1
                    extra_points -= 1

                # Generate random points within stratum
                stratum_wkt = stratum.wkt
                # Already buffered at polygon level, so use 0 buffer for strata
                stratum_points = generate_random_points(stratum_wkt, n_points, boundary_buffer_meters=0)
                points.extend(stratum_points)

            except Exception as e:
                logger.warning(f"Error processing stratum: {str(e)}")
                continue

    logger.info(f"Generated {len(points)} stratified random points")
    return points


def extract_blocks_from_calculation(
    db: Session,
    calculation_id: UUID
) -> List[Tuple[int, str, str, float]]:
    """
    Extract individual blocks from calculation geometry.

    Args:
        db: Database session
        calculation_id: Calculation ID

    Returns:
        List of tuples: (block_number, block_geom_wkt, block_name, block_area_hectares)
    """
    query = text(f"""
        WITH blocks AS (
            SELECT
                (ST_Dump(boundary_geom)).path[1] as block_number,
                (ST_Dump(boundary_geom)).geom as block_geom,
                result_data->'blocks' as blocks_data
            FROM public.calculations
            WHERE id = :calc_id
        )
        SELECT
            block_number,
            ST_AsText(block_geom) as block_wkt,
            ST_Area(ST_Transform(block_geom,
                CASE
                    WHEN ST_X(ST_Centroid(block_geom)) < 84.0 THEN 32644
                    ELSE 32645
                END
            )) / {SQM_PER_HA} as area_hectares,
            blocks_data
        FROM blocks
        ORDER BY block_number
    """)

    results = db.execute(query, {"calc_id": str(calculation_id)}).fetchall()

    blocks = []
    for row in results:
        block_number = row.block_number
        block_wkt = row.block_wkt
        area_hectares = float(row.area_hectares)
        blocks_data = row.blocks_data if row.blocks_data else []

        # Get block name from result_data
        block_name = f"Block {block_number}"
        if blocks_data:
            for block in blocks_data:
                if block.get('block_index') == block_number - 1:  # 0-indexed in result_data
                    block_name = block.get('block_name', block_name)
                    break

        blocks.append((block_number, block_wkt, block_name, area_hectares))

    logger.info(f"Extracted {len(blocks)} blocks from calculation {calculation_id}")
    return blocks


def create_sampling_design(
    db: Session,
    calculation_id: UUID,
    sampling_type: str,
    sampling_intensity_percent: Optional[Decimal] = None,
    min_samples_per_block: int = 5,
    min_samples_small_blocks: int = 2,
    boundary_buffer_meters: float = 50.0,

    # NEW: Accessible forest filtering parameters
    filter_tree_cover: bool = True,
    filter_slope: bool = False,
    max_slope_degrees: float = 45.0,

    intensity_per_hectare: Optional[Decimal] = None,
    grid_spacing_meters: Optional[int] = None,
    min_distance_meters: Optional[int] = None,
    plot_shape: str = "circular",
    plot_radius_meters: Optional[Decimal] = None,
    plot_length_meters: Optional[Decimal] = None,
    plot_width_meters: Optional[Decimal] = None,
    notes: Optional[str] = None,
    block_overrides: Optional[dict] = None
) -> SamplingGenerateResponse:
    # business: main sampling orchestrator — chooses algorithm based on sampling_type
    # constraint: filter_tree_cover defaults True — all Phase 2 designs start with tree cover filter
    # NOTE: accessible forest filtering is Phase 2 enhancement over Phase 1 (original sampling.py)
    """
    Create sampling design and generate sampling points PER BLOCK.

    NEW: Supports flexible filtering for accessible forest areas.

    Uses sampling intensity percentage and enforces minimum samples per block.

    Args:
        db: Database session
        calculation_id: Calculation ID
        sampling_type: 'systematic', 'random', or 'stratified'
        sampling_intensity_percent: Percentage of block area to sample (default 0.5%)
        min_samples_per_block: Minimum samples for blocks >= 1 ha (default 5)
        min_samples_small_blocks: Minimum samples for blocks < 1 ha (default 2)
        boundary_buffer_meters: Minimum distance from boundary (default 50m)

        filter_tree_cover: If True, exclude non-forest areas (default True)
        filter_slope: If True, exclude steep slopes (default False)
        max_slope_degrees: Maximum slope threshold in degrees (default 45.0)

        intensity_per_hectare: [DEPRECATED] Use sampling_intensity_percent
        grid_spacing_meters: [DEPRECATED] Calculated automatically
        min_distance_meters: Minimum distance between points
        plot_shape: 'circular', 'square', or 'rectangular'
        plot_radius_meters: Plot radius (for circular, default 12.62m)
        plot_length_meters: Plot length (for rectangular)
        plot_width_meters: Plot width (for rectangular)
        notes: Design notes

    Returns:
        SamplingGenerateResponse with per-block summary statistics
    """
    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise ValueError(f"Calculation {calculation_id} not found")

    # Use sampling_intensity_percent if provided, otherwise fallback to old intensity_per_hectare
    if sampling_intensity_percent is None and intensity_per_hectare is not None:
        # Convert old intensity_per_hectare to percentage (rough estimate)
        sampling_intensity_percent = Decimal("0.5")
        logger.warning("Using default 0.5% intensity - intensity_per_hectare is deprecated")
    elif sampling_intensity_percent is None:
        sampling_intensity_percent = Decimal("0.5")  # Default

    # Calculate plot area
    plot_area_sqm = None
    if plot_shape == "circular" and plot_radius_meters:
        plot_area_sqm = math.pi * float(plot_radius_meters) ** 2
    elif plot_shape == "circular":
        # Default circular plot: radius 12.6156m = 500m²
        plot_area_sqm = math.pi * (12.6156 ** 2)
        plot_radius_meters = Decimal("12.6156")
    elif plot_shape in ["square", "rectangular"] and plot_length_meters and plot_width_meters:
        plot_area_sqm = float(plot_length_meters) * float(plot_width_meters)
    else:
        raise ValueError("Plot shape and dimensions must be specified")

    plot_area_hectares = plot_area_sqm / SQM_PER_HA

    logger.info(
        f"Generating {sampling_type} sampling with {float(sampling_intensity_percent)}% intensity, "
        f"plot size {plot_area_sqm:.2f}m², min samples: {min_samples_per_block} (large blocks), "
        f"{min_samples_small_blocks} (small blocks < 1ha)"
    )

    # Log filter settings
    if filter_tree_cover or filter_slope:
        filter_desc = []
        if filter_tree_cover:
            filter_desc.append("tree cover only")
        if filter_slope:
            filter_desc.append(f"slope ≤{max_slope_degrees}°")
        logger.info(f"  Accessible forest filtering: {', '.join(filter_desc)}")

    # Build default parameters dictionary
    default_parameters = {
        "sampling_type": sampling_type,
        "sampling_intensity_percent": float(sampling_intensity_percent),
        "min_samples_per_block": min_samples_per_block,
        "min_samples_small_blocks": min_samples_small_blocks,
        "boundary_buffer_meters": boundary_buffer_meters,
        "min_distance_meters": min_distance_meters,

        # NEW: Accessible forest filter settings
        "filter_tree_cover": filter_tree_cover,
        "filter_slope": filter_slope,
        "max_slope_degrees": max_slope_degrees
    }

    # Extract blocks from calculation
    blocks = extract_blocks_from_calculation(db, calculation_id)

    # Generate sampling points PER BLOCK
    all_points = []
    block_assignments = []
    blocks_info = []
    total_forest_area = 0.0

    for block_number, block_wkt, block_name, block_area_ha in blocks:
        total_forest_area += block_area_ha

        # Apply block-specific overrides if they exist
        block_sampling_type = sampling_type
        block_intensity_percent = sampling_intensity_percent
        block_min_samples_per_block = min_samples_per_block
        block_min_samples_small_blocks = min_samples_small_blocks
        block_boundary_buffer = boundary_buffer_meters
        block_min_distance = min_distance_meters

        if block_overrides and block_name in block_overrides:
            override = block_overrides[block_name]
            block_sampling_type = override.get("sampling_type", sampling_type)
            block_intensity_percent = Decimal(str(override.get("sampling_intensity_percent", sampling_intensity_percent)))
            block_min_samples_per_block = override.get("min_samples_per_block", min_samples_per_block)
            block_boundary_buffer = override.get("boundary_buffer_meters", boundary_buffer_meters)
            block_min_distance = override.get("min_distance_meters", min_distance_meters)

            logger.info(f"  Applying overrides for {block_name}: {override}")

        # NEW: Calculate accessible forest area for this block
        accessible_area_info = None
        effective_block_area = block_area_ha  # Default to total area

        if filter_tree_cover or filter_slope:
            accessible_area_info = calculate_accessible_forest_area(
                db=db,
                geometry_wkt=block_wkt,
                filter_tree_cover=filter_tree_cover,
                filter_slope=filter_slope,
                max_slope_degrees=max_slope_degrees
            )

            # Use accessible forest area instead of total block area
            effective_block_area = accessible_area_info.get("accessible_forest_area_ha", block_area_ha)

            logger.info(
                f"  {block_name}: Total {block_area_ha:.2f} ha → "
                f"Accessible {effective_block_area:.2f} ha "
                f"({accessible_area_info.get('accessible_forest_percentage', 100):.1f}%)"
            )

            if filter_tree_cover:
                logger.info(f"    - Filtered to tree cover only")
            if filter_slope:
                logger.info(f"    - Excluded slopes >{max_slope_degrees}°")
                if accessible_area_info.get('inaccessible_steep_forest_ha', 0) > 0:
                    logger.info(
                        f"    - Inaccessible steep forest: "
                        f"{accessible_area_info['inaccessible_steep_forest_ha']:.2f} ha"
                    )

        # Determine minimum samples for this block
        if block_area_ha < 1.0:
            min_samples = block_min_samples_small_blocks
        else:
            min_samples = block_min_samples_per_block

        # Calculate samples based on intensity (use EFFECTIVE area)
        sample_area_hectares = effective_block_area * (float(block_intensity_percent) / 100.0)
        samples_from_intensity = int(sample_area_hectares / plot_area_hectares)

        # Apply minimum
        samples_for_block = max(min_samples, samples_from_intensity)
        minimum_enforced = samples_for_block == min_samples

        logger.info(
            f"  {block_name} ({block_area_ha:.2f} ha, {effective_block_area:.2f} ha accessible): "
            f"{samples_from_intensity} from intensity → {samples_for_block} samples "
            f"(minimum {'enforced' if minimum_enforced else 'not needed'})"
        )

        # NEW: Extract accessible forest mask if filtering is enabled
        sampling_polygon_wkt = block_wkt  # Default to full block

        if filter_tree_cover or filter_slope:
            accessible_mask_wkt = extract_accessible_forest_mask(
                db=db,
                geometry_wkt=block_wkt,
                filter_slope=filter_slope,
                max_slope_degrees=max_slope_degrees
            )

            if accessible_mask_wkt:
                sampling_polygon_wkt = accessible_mask_wkt
                logger.info(f"    - Using accessible forest mask for point generation")
            else:
                logger.warning(
                    f"  {block_name}: No accessible forest found with current filters. "
                    f"Using full boundary."
                )

        # Generate points for this block (using accessible mask if available)
        if block_sampling_type == "systematic":
            # Calculate grid spacing to get desired number of samples
            block_area_sqm = effective_block_area * SQM_PER_HA  # Use effective area
            spacing_meters = math.sqrt(block_area_sqm / samples_for_block)

            bounds = get_polygon_bounds(sampling_polygon_wkt)  # Use accessible mask
            block_points = generate_systematic_grid(
                bounds[0], bounds[1], bounds[2], bounds[3],
                int(spacing_meters),
                sampling_polygon_wkt,  # Use accessible mask
                block_boundary_buffer
            )

            # If we got fewer points than needed, adjust spacing and retry
            if len(block_points) < samples_for_block:
                spacing_meters = spacing_meters * 0.8  # Reduce spacing by 20%
                block_points = generate_systematic_grid(
                    bounds[0], bounds[1], bounds[2], bounds[3],
                    int(spacing_meters),
                    sampling_polygon_wkt,  # Use accessible mask
                    block_boundary_buffer
                )

        elif block_sampling_type == "random":
            block_points = generate_random_points(
                sampling_polygon_wkt,  # Use accessible mask
                samples_for_block,
                block_min_distance,
                block_boundary_buffer
            )

        elif block_sampling_type == "stratified":
            block_points = generate_stratified_points(
                sampling_polygon_wkt,  # Use accessible mask
                samples_for_block,
                num_strata=max(4, samples_for_block // 2),
                boundary_buffer_meters=block_boundary_buffer
            )

        else:
            raise ValueError(f"Invalid sampling_type: {block_sampling_type}")

        # Store points with block assignment
        for point in block_points:
            all_points.append(point)
            block_assignments.append({
                'point_index': len(all_points) - 1,
                'block_number': block_number,
                'block_name': block_name
            })

        # Calculate actual intensity for this block (based on effective area)
        actual_intensity_pct = Decimal(str((len(block_points) * plot_area_hectares / effective_block_area) * 100)) if effective_block_area > 0 else Decimal("0")

        # Store block info with accessible area information
        block_info_dict = {
            "block_number": block_number,
            "block_name": block_name,
            "block_area_hectares": Decimal(str(round(block_area_ha, 4))),
            "samples_generated": len(block_points),
            "minimum_enforced": minimum_enforced,
            "actual_intensity_percent": actual_intensity_pct
        }

        # Add accessible area information if filtering was applied
        if accessible_area_info:
            block_info_dict["accessible_forest_area_ha"] = Decimal(
                str(round(accessible_area_info.get("accessible_forest_area_ha", 0), 4))
            )
            block_info_dict["accessible_forest_percentage"] = Decimal(
                str(round(accessible_area_info.get("accessible_forest_percentage", 0), 2))
            )
            if filter_slope:
                block_info_dict["inaccessible_steep_forest_ha"] = Decimal(
                    str(round(accessible_area_info.get("inaccessible_steep_forest_ha", 0), 4))
                )
                block_info_dict["non_forest_area_ha"] = Decimal(
                    str(round(accessible_area_info.get("non_forest_area_ha", 0), 4))
                )

        blocks_info.append(BlockSamplingInfo(**block_info_dict))

    points = all_points
    logger.info(f"Generated total {len(points)} sampling points across {len(blocks)} blocks")

    if not points:
        raise ValueError("No sampling points generated - check polygon and parameters")

    # Create MultiPoint geometry WKT
    points_wkt = "MULTIPOINT(" + ", ".join([f"{lon} {lat}" for lon, lat in points]) + ")"

    # Create sampling design record
    sampling_design = SamplingDesign(
        calculation_id=calculation_id,
        sampling_type=sampling_type,
        intensity_per_hectare=Decimal(str(len(points) / total_forest_area)),  # Calculated
        grid_spacing_meters=None,  # Not used with intensity-based approach
        min_distance_meters=min_distance_meters,
        plot_shape=plot_shape,
        plot_radius_meters=plot_radius_meters,
        plot_length_meters=plot_length_meters,
        plot_width_meters=plot_width_meters,
        total_points=len(points),
        notes=notes
    )

    db.add(sampling_design)
    db.flush()  # Get ID

    # Save default parameters and block overrides
    import json
    if default_parameters:
        update_defaults_query = text("""
            UPDATE public.sampling_designs
            SET default_parameters = CAST(:params AS jsonb)
            WHERE id = :design_id
        """)
        db.execute(update_defaults_query, {
            "params": json.dumps(default_parameters),
            "design_id": str(sampling_design.id)
        })

    if block_overrides:
        # Convert block_overrides to JSON-serializable format
        serializable_overrides = {}
        for block_name, override_params in block_overrides.items():
            # If override_params is a Pydantic model, convert to dict
            if hasattr(override_params, 'model_dump'):
                serializable_overrides[block_name] = override_params.model_dump(exclude_none=True)
            elif hasattr(override_params, 'dict'):
                serializable_overrides[block_name] = override_params.dict(exclude_none=True)
            else:
                serializable_overrides[block_name] = override_params

        update_overrides_query = text("""
            UPDATE public.sampling_designs
            SET block_overrides = CAST(:overrides AS jsonb)
            WHERE id = :design_id
        """)
        db.execute(update_overrides_query, {
            "overrides": json.dumps(serializable_overrides),
            "design_id": str(sampling_design.id)
        })

    # Update geometry using PostGIS
    update_geom_query = text("""
        UPDATE public.sampling_designs
        SET points_geometry = ST_GeomFromText(:points_wkt, 4326)
        WHERE id = :design_id
    """)
    db.execute(update_geom_query, {
        "points_wkt": points_wkt,
        "design_id": str(sampling_design.id)
    })

    # Save block assignments directly (we already calculated them)
    import json
    update_assignments_query = text("""
        UPDATE public.sampling_designs
        SET points_block_assignment = CAST(:assignments AS jsonb)
        WHERE id = :design_id
    """)
    db.execute(update_assignments_query, {
        "assignments": json.dumps(block_assignments),
        "design_id": str(sampling_design.id)
    })

    db.commit()

    # Calculate statistics
    actual_intensity = Decimal(str(len(points) / total_forest_area))
    total_sampled_area_sqm = plot_area_sqm * len(points)
    total_sampled_area_hectares = Decimal(str(total_sampled_area_sqm / SQM_PER_HA))
    sampling_percentage = Decimal(str((total_sampled_area_sqm / (total_forest_area * SQM_PER_HA)) * 100))

    return SamplingGenerateResponse(
        sampling_design_id=sampling_design.id,
        calculation_id=calculation_id,
        sampling_type=sampling_type,
        total_points=len(points),
        total_blocks=len(blocks),
        forest_area_hectares=Decimal(str(round(total_forest_area, 4))),
        requested_intensity_percent=sampling_intensity_percent,
        actual_intensity_per_hectare=actual_intensity,
        plot_area_sqm=Decimal(str(round(plot_area_sqm, 2))),
        total_sampled_area_hectares=total_sampled_area_hectares,
        sampling_percentage=sampling_percentage,
        blocks_info=blocks_info
    )


def get_sampling_points_geojson(db: Session, design_id: UUID) -> dict:
    """
    Get sampling points as GeoJSON.

    Args:
        db: Database session
        design_id: Sampling design ID

    Returns:
        GeoJSON FeatureCollection
    """
    query = text("""
        SELECT
            ST_AsGeoJSON(points_geometry) as geojson,
            sampling_type,
            total_points
        FROM public.sampling_designs
        WHERE id = :design_id
    """)

    result = db.execute(query, {"design_id": str(design_id)}).first()

    if not result:
        raise ValueError(f"Sampling design {design_id} not found")

    import json
    geojson_data = json.loads(result.geojson)

    # Convert to FeatureCollection with individual points
    features = []
    if geojson_data['type'] == 'MultiPoint':
        for i, coord in enumerate(geojson_data['coordinates'], 1):
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": coord
                },
                "properties": {
                    "plot_number": i,
                    "sampling_type": result.sampling_type
                }
            }
            features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features
    }


def assign_blocks_to_sampling(db: Session, design_id: UUID, calculation_id: UUID):
    """
    Assign block numbers to sampling points using spatial intersection.

    Uses user-defined block names from result_data.blocks[].block_name if available.
    For multi-polygon geometries, this determines which block each sampling point falls within.
    Results are stored in the points_block_assignment JSONB column as an array.

    Args:
        db: Database session
        design_id: Sampling design ID
        calculation_id: Calculation ID
    """
    # Check if this is a multi-polygon and get block names
    calc_query = text("""
        SELECT
            ST_GeometryType(boundary_geom) as geom_type,
            ST_NumGeometries(boundary_geom) as num_blocks,
            result_data->'blocks' as blocks_data
        FROM public.calculations
        WHERE id = :calc_id
    """)
    result = db.execute(calc_query, {"calc_id": str(calculation_id)}).first()

    if not result:
        return

    is_multipolygon = result.geom_type == 'ST_MultiPolygon'
    blocks_data = result.blocks_data if result.blocks_data else []

    # Extract block names from result_data
    block_names_map = {}
    if blocks_data:
        for block in blocks_data:
            block_index = block.get('block_index')
            block_name = block.get('block_name')
            if block_index is not None and block_name:
                # ST_Dump uses 1-based indexing, but block_index is 0-based
                block_names_map[block_index + 1] = block_name

    if not is_multipolygon:
        # Single polygon - get block name from result_data or use default
        block_name = block_names_map.get(1, 'Block 1')

        # Create simple assignment array using SQL
        update_query = text("""
            WITH point_indices AS (
                SELECT generate_series(0, ST_NumGeometries(points_geometry) - 1) as point_index
                FROM public.sampling_designs
                WHERE id = :design_id
            )
            UPDATE public.sampling_designs
            SET points_block_assignment = (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'point_index', point_index,
                        'block_number', 1,
                        'block_name', :block_name
                    )
                )
                FROM point_indices
            )
            WHERE id = :design_id
            RETURNING jsonb_array_length(points_block_assignment) as num_points
        """)
        result = db.execute(update_query, {
            "design_id": str(design_id),
            "block_name": block_name
        }).first()
        num_points = result.num_points if result else 0
        logger.info(f"Assigned all {num_points} sampling points to '{block_name}'")
        return

    # Multi-polygon - use spatial intersection in a single UPDATE query
    # Build CASE statement for block names
    import json

    if block_names_map:
        block_name_cases = []
        for block_num, block_name in block_names_map.items():
            # Escape single quotes in block name
            escaped_name = block_name.replace("'", "''")
            block_name_cases.append(f"WHEN {block_num} THEN '{escaped_name}'")
        block_name_expression = f"CASE pol.block_number {' '.join(block_name_cases)} ELSE 'Block ' || pol.block_number END"
    else:
        block_name_expression = "'Block ' || pol.block_number"

    update_query = text(f"""
        UPDATE public.sampling_designs sd
        SET points_block_assignment = (
            WITH polygon_parts AS (
                SELECT
                    (ST_Dump(boundary_geom)).path[1] as block_number,
                    (ST_Dump(boundary_geom)).geom as block_geom
                FROM public.calculations
                WHERE id = :calc_id
            ),
            point_parts AS (
                SELECT
                    (ST_DumpPoints(sd.points_geometry)).path[1] - 1 as point_index,
                    (ST_DumpPoints(sd.points_geometry)).geom as point_geom
            )
            SELECT
                jsonb_agg(
                    jsonb_build_object(
                        'point_index', pp.point_index,
                        'block_number', pol.block_number,
                        'block_name', {block_name_expression}
                    )
                    ORDER BY pp.point_index
                )
            FROM point_parts pp
            CROSS JOIN LATERAL (
                SELECT block_number
                FROM polygon_parts
                WHERE ST_Intersects(pp.point_geom, block_geom)
                LIMIT 1
            ) pol
        )
        WHERE sd.id = :design_id
    """)

    db.execute(update_query, {
        "calc_id": str(calculation_id),
        "design_id": str(design_id)
    })
    logger.info(f"Assigned sampling points to blocks using spatial intersection with user-defined names")
