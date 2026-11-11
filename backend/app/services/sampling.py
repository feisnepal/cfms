"""
Sampling design service for forest inventory
Implements systematic, random, and stratified sampling algorithms

Phase 2: Enhanced with accessible forest filtering
Phase 3: Added Guideline-2061 support (Nepal DoF standard)
"""

# business: CFMG §X.Y — systematic sampling at 200m × 250m grid, stratified by block and land cover
import random
import math
from typing import List, Tuple, Optional, Dict, Union
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.services import optimistic_lock
from shapely import wkt
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.ops import unary_union
import logging

from app.core.sub_area_kinds import PROTECTION_SUB_AREA_CATEGORIES
import random

from app.models.calculation import Calculation
from app.models.sampling import SamplingDesign
from app.models.forest_block import ForestBlock
from app.services.forest_units import queries as forest_unit_queries
from app.schemas.sampling import SamplingGenerateResponse, BlockSamplingInfo
from app.services.tree_cover_analysis import (
    calculate_accessible_forest_area,
    extract_accessible_forest_mask,
    point_in_accessible_forest,
)

# NOTE: OPTIMIZED version uses raster pixel-centre extraction — ~50x faster than vector approach for large areas
from app.services.tree_cover_analysis_optimized import (
    extract_tree_cover_pixel_centers_FAST as extract_tree_cover_pixel_centers,
)

# Guideline-2061 support
from app.core.constants import SQM_PER_HA, METERS_PER_DEGREE_LAT, MMU_SLIVER_AREA_M2
from app.services.guideline_sampling import (
    get_sample_count_from_guideline,
    classify_block_by_majority_area,
    validate_guideline_parameters,
)
from app.services.sustainable_fm.stratum_spec import (
    STRATUM_FLOOR_PCT,
    STRATUM_PLOT_SQM,
    MIN_SAMPLES_PER_UNIT,
    classify_calc_units,
)

# UTM-projected geodesic area for grid-spacing derivation
from app.utils.geometry_utils import calculate_area_geodesic_from_shapely

logger = logging.getLogger(__name__)


# business: excluded areas (private land, settlements) subtracted before sampling grid placement
def get_excluded_areas_for_calculation(
    db: Session, calculation_id: UUID
) -> List[Polygon]:
    """
    Get excluded areas (private land) from calculation's sub-areas.

    Args:
        db: Database session
        calculation_id: Calculation ID

    Returns:
        List of Shapely Polygon geometries representing excluded areas
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation or not calculation.result_data:
        return []

    excluded_polygons = []
    sub_areas = calculation.result_data.get("sub_areas", [])

    for sub_area in sub_areas:
        if sub_area.get("is_excluded", False) or sub_area.get(
            "isExcluded", False
        ):  # Support both naming conventions
            try:
                from shapely.geometry import shape, GeometryCollection

                geom_data = sub_area["geometry"]

                # Handle GeometryCollection - extract only Polygon/MultiPolygon
                if geom_data.get("type") == "GeometryCollection":
                    geom_collection = shape(geom_data)

                    # Extract only polygonal geometries (filter out LineStrings, Points)
                    polygons = [
                        g
                        for g in geom_collection.geoms
                        if g.geom_type in ("Polygon", "MultiPolygon") and g.area > 0
                    ]

                    for poly in polygons:
                        if isinstance(poly, Polygon):
                            excluded_polygons.append(poly)
                        elif isinstance(poly, MultiPolygon):
                            excluded_polygons.extend(list(poly.geoms))
                else:
                    # Regular Polygon or MultiPolygon
                    geom = shape(geom_data)

                    # Skip zero-area geometries
                    if geom.area == 0:
                        logger.warning(
                            f"Excluded area '{sub_area.get('name', 'unnamed')}' has zero area. Skipping."
                        )
                        continue

                    if isinstance(geom, Polygon):
                        excluded_polygons.append(geom)
                    elif isinstance(geom, MultiPolygon):
                        excluded_polygons.extend(list(geom.geoms))

            except Exception as e:
                logger.warning(f"Failed to parse excluded area geometry: {e}")
                continue

    logger.info(
        f"Found {len(excluded_polygons)} excluded areas for calculation {calculation_id}"
    )
    return excluded_polygons


def point_in_excluded_area(
    lon: float, lat: float, excluded_areas: List[Polygon]
) -> bool:
    """
    Check if a point falls within any excluded area (private land).

    Args:
        lon: Longitude
        lat: Latitude
        excluded_areas: List of excluded area polygons

    Returns:
        True if point is in excluded area, False otherwise
    """
    if not excluded_areas:
        return False

    point = Point(lon, lat)
    for excluded_poly in excluded_areas:
        if excluded_poly.contains(point):
            return True
    return False


# constraint: UTM transform accurate for Nepal (zone 45N) area calculations
def get_polygon_bounds(geom_wkt: str) -> Tuple[float, float, float, float]:
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
    geom = wkt.loads(geom_wkt)
    if geom.is_empty:
        return 0.0
    _area_sqm, area_ha = calculate_area_geodesic_from_shapely(geom)
    return area_ha


# constraint: 50m inward buffer from boundary to avoid edge effects in sampling
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
        logger.warning(
            f"Buffer of {buffer_meters}m resulted in empty polygon - using original"
        )
        return polygon_wkt

    return buffered_wgs84.wkt


def validate_point_distance_from_boundary(
    points: List[Tuple[float, float]],
    boundary_wkt: str,
    min_distance_meters: float = 20.0,
) -> List[Tuple[float, float]]:
    """
    Validate that all points are at least min_distance_meters from the boundary edge.
    Filters out points that are too close to the boundary.

    Args:
        points: List of (lon, lat) tuples
        boundary_wkt: WKT of boundary polygon
        min_distance_meters: Minimum distance from boundary edge (default 20m = 2 pixels of tree cover)

    Returns:
        Filtered list of points that are safely inside the boundary
    """
    from shapely import wkt as shapely_wkt
    from shapely.ops import transform
    from pyproj import Transformer
    from shapely.geometry import Point

    if not points:
        return points

    # Load boundary
    boundary = shapely_wkt.loads(boundary_wkt)
    centroid = boundary.centroid

    # Determine UTM zone for Nepal
    utm_zone = 44 if centroid.x < 84.0 else 45
    utm_epsg = f"EPSG:326{utm_zone}"

    # Create transformers
    to_utm = Transformer.from_crs("EPSG:4326", utm_epsg, always_xy=True)

    # Transform boundary to UTM
    boundary_utm = transform(to_utm.transform, boundary)
    boundary_line_utm = boundary_utm.boundary

    # Filter points
    valid_points = []
    filtered_count = 0

    for lon, lat in points:
        # Transform point to UTM
        point_utm_coords = to_utm.transform(lon, lat)
        point_utm = Point(point_utm_coords)

        # Calculate distance to boundary edge
        distance = point_utm.distance(boundary_line_utm)

        if distance >= min_distance_meters:
            valid_points.append((lon, lat))
        else:
            filtered_count += 1

    if filtered_count > 0:
        logger.warning(
            f"Filtered {filtered_count} points that were < {min_distance_meters}m from boundary. "
            f"Kept {len(valid_points)} valid points."
        )

    return valid_points


# business: CFMG §X.Y — systematic sampling at 200m × 250m grid
# why: random start offset avoids bias in systematic sampling
def _even_pick(points: List[Tuple[float, float]], n: int) -> List[Tuple[float, float]]:
    """Select exactly `n` points evenly spread along a lattice-ordered list.

    Uses a fractional stride (`points[int(i * len/n)]`) so the selection spans the
    whole list — never a scan-order `[::k]` slice, which dropped trailing rows and
    produced bands of close points with gaps between them.
    """
    if n <= 0 or len(points) <= n:
        return list(points)
    step = len(points) / float(n)
    return [points[int(i * step)] for i in range(n)]


def _top_up_pixels(
    block_points: List[Tuple[float, float]],
    pixel_points: List[Tuple[float, float]],
    samples_for_block: int,
) -> List[Tuple[float, float]]:
    """Top up a tree-cover systematic block to the target count using UNCLAIMED
    tree pixels, spread evenly over the accessible area.

    Regression (user report "8,9,10,11,12 / 93,94,95 all very close together"):
    `pixel_points` arrives in raster-scan order, so slicing `[:needed]` picked
    physically adjacent ~10m pixels — those plots clustered and, because plot
    numbers are assigned in list order, got consecutive numbers that look like a
    blotch on the map instead of a systematic spread. We sort the unclaimed
    pixels spatially (lat then lon) and even-pick so the residual plots tile the
    area.
    """
    if samples_for_block <= len(block_points):
        return []
    seen = set(block_points)
    unclaimed = [p for p in pixel_points if p not in seen]
    needed = samples_for_block - len(block_points)
    return _even_pick(sorted(unclaimed, key=lambda p: (p[1], p[0])), needed)


def generate_systematic_grid(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    grid_spacing_meters: int,
    polygon_wkt: str,
    boundary_buffer_meters: float = 50.0,
    random_start: bool = False,
) -> List[Tuple[float, float]]:
    """
    Generate systematic grid of points within polygon.

    Enforces minimum distance from boundary to avoid edge effects.

    Args:
        min_lon, min_lat, max_lon, max_lat: Bounding box
        grid_spacing_meters: Grid spacing in meters
        polygon_wkt: WKT of polygon to constrain points
        boundary_buffer_meters: Minimum distance from boundary (default 50m)
        random_start: If True, offset the grid origin by a uniform random amount
            within one cell (0..spacing) on both axes. This is the standard
            systematic-sampling random start, which removes alignment bias while
            keeping locations on a fixed regular lattice.

    Returns:
        List of (lon, lat) tuples
    """
    # A zero or negative spacing never advances the lattice: the loops below would run forever (a sliver unit whose target spacing
    # rounds to 0 m did exactly that). Refuse it here as well as at the call site.
    if grid_spacing_meters is None or grid_spacing_meters <= 0:
        raise ValueError(f"grid_spacing_meters must be positive, got {grid_spacing_meters!r}")

    # Apply boundary buffer to keep points away from edge
    buffered_polygon_wkt = apply_boundary_buffer(polygon_wkt, boundary_buffer_meters)

    # Convert grid spacing to approximate degrees
    # At Nepal's latitude (~28°), 1 degree latitude ≈ 111 km
    # 1 degree longitude ≈ 111 km * cos(28°) ≈ 98 km
    meters_per_degree_lat = 111000.0
    meters_per_degree_lon = 98000.0

    spacing_lat = grid_spacing_meters / meters_per_degree_lat
    spacing_lon = grid_spacing_meters / meters_per_degree_lon

    # Random start offset within one cell — uniform on [0, spacing) per axis.
    start_lon = min_lon
    start_lat = min_lat
    if random_start:
        start_lon = min_lon + random.uniform(0.0, spacing_lon)
        start_lat = min_lat + random.uniform(0.0, spacing_lat)
        # Tiny polygons: a random start may fall beyond the far edge; clamp to the
        # cell midpoint so at least one lattice point is attempted.
        if start_lon > max_lon:
            start_lon = (min_lon + max_lon) / 2.0
        if start_lat > max_lat:
            start_lat = (min_lat + max_lat) / 2.0

    # Load buffered polygon for intersection testing
    polygon = wkt.loads(buffered_polygon_wkt)

    # Generate grid points
    points = []
    lat = start_lat
    while lat <= max_lat:
        lon = start_lon
        while lon <= max_lon:
            point = Point(lon, lat)
            if polygon.contains(point):
                points.append((lon, lat))
            lon += spacing_lon
        lat += spacing_lat

    logger.info(f"Generated {len(points)} systematic grid points")
    return points


# business: random sampling as alternative to systematic; supports min-distance constraint
def generate_random_points(
    polygon_wkt: str,
    num_points: int,
    min_distance_meters: Optional[int] = None,
    boundary_buffer_meters: float = 50.0,
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
                dist = math.sqrt((lon - existing_lon) ** 2 + (lat - existing_lat) ** 2)
                if dist < min_dist_deg:
                    too_close = True
                    break
            if too_close:
                continue

        points.append((lon, lat))

    logger.info(f"Generated {len(points)} random points in {attempts} attempts")
    return points


# business: stratified by block and land cover type — ensures coverage across heterogeneous areas
def generate_stratified_points(
    polygon_wkt: str,
    num_points: int,
    num_strata: int = 4,
    boundary_buffer_meters: float = 50.0,
) -> List[Tuple[float, float]]:
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
            stratum_box = Polygon(
                [
                    (stratum_minx, stratum_miny),
                    (stratum_maxx, stratum_miny),
                    (stratum_maxx, stratum_maxy),
                    (stratum_minx, stratum_maxy),
                    (stratum_minx, stratum_miny),
                ]
            )

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
                stratum_points = generate_random_points(
                    stratum_wkt, n_points, boundary_buffer_meters=0
                )
                points.extend(stratum_points)

            except Exception as e:
                logger.warning(f"Error processing stratum: {str(e)}")
                continue

    logger.info(f"Generated {len(points)} stratified random points")
    return points


def extract_blocks_from_calculation(
    db: Session, calculation_id: UUID
) -> List[Tuple[int, str, str, float]]:
    """
    Extract sampling units from a calculation.
    Returns compartments (from forest_blocks DB or result_data) or blocks,
    depending on which mode the forest uses.

    The workflow stores blocks/compartments in the ``forest_blocks`` table
    (DB-authoritative: workspace split/divide/MMU), while legacy upload-mode
    stores them under ``result_data['blocks']``/``result_data['compartments']``.
    DB rows are preferred because they reflect the current (post-split)
    geometry; an empty DB + empty result_data falls back to the whole boundary
    as a single unit.

    Args:
        db: Database session
        calculation_id: Calculation ID

    Returns:
        List of tuples: (number, geom_wkt, name, area_hectares)
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise ValueError(f"CALCULATION_NOT_FOUND: गणना {calculation_id} फेला परेन")

    result_data = calculation.result_data or {}

    def db_rows_to_units(rows):
        from geoalchemy2.shape import to_shape

        units = []
        for idx, row in enumerate(rows):
            label = "Compartment" if row.is_compartment else "Block"
            geom = to_shape(row.geometry)
            area_ha = (
                float(row.area_hectares)
                if row.area_hectares
                else geom.area / SQM_PER_HA
            )
            name = (
                row.compartment_code
                or row.block_name
                or row.name
                or f"{label} {idx + 1}"
            )
            units.append((idx + 1, geom.wkt, name, area_ha))
        return units

    def result_data_to_units(units_array, use_compartments):
        from shapely.geometry import shape

        units = []
        for idx, unit_data in enumerate(units_array):
            number = idx + 1
            name = (
                unit_data.get("compartment_code")
                or unit_data.get("compartment_name")
                or unit_data.get("block_name")
                or unit_data.get("name")
                or f'{"C" if use_compartments else "Block"} {number}'
            )

            geometry = (
                unit_data.get("geometry")
                or unit_data.get("block_geometry")
                or unit_data.get("polygon_geometry")
            )

            if not geometry:
                logger.warning(
                    f"{'C' if use_compartments else 'Block'} {name} has no geometry, skipping."
                )
                continue

            try:
                geom = shape(geometry)
                wkt = geom.wkt

                query = text(
                    f"""
                    SELECT
                        ST_Area(ST_Transform(ST_GeomFromText(:wkt, 4326),
                            CASE
                                WHEN ST_X(ST_Centroid(ST_GeomFromText(:wkt, 4326))) < 84.0 THEN 32644
                                ELSE 32645
                            END
                        )) / {SQM_PER_HA} as area_hectares
                """
                )
                result = db.execute(query, {"wkt": wkt}).fetchone()
                area_hectares = float(result.area_hectares) if result else 0.0

                units.append((number, wkt, name, area_hectares))

            except Exception as e:
                logger.error(
                    f"Failed to process {'compartment' if use_compartments else 'block'} {name}: {e}"
                )
                continue
        return units

    # Are the legacy ``result_data['blocks'/'compartments']`` arrays trustworthy?
    # They are only written by the upload path, and only describe the current
    # structure for a forest that was never edited in the workspace. Once the
    # forest_blocks table has rows — or once the user has deliberately cleared
    # its structure in the workspace (``blocks_cleared_by_user``) — the DB is
    # authoritative and a stale array left behind by a since-deleted division
    # must NOT be consulted (bug: sample plots generated against deleted
    # compartments, covering only the part of the forest that once had them).
    db_row_count = (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calculation_id)
        .count()
    )
    workspace_managed = db_row_count > 0 or bool(
        getattr(calculation, "blocks_cleared_by_user", False)
    )

    # 1) DB-stored units (workspace flow) - authoritative. The sampling set is the LEAF view (FS-1a.4): every
    #    unit that is not divided further, so the units tile the forest exactly once. It used to return every
    #    compartment row at every depth (C1 divided into SC1/SC2, C2 not -> C1 + C2 + SC1 + SC2 = about 150 % of
    #    the forest, plots planned twice over the divided ground) and, for blocks, only a zero depth
    #    (the top-level blocks). Migration 094 makes that "top level" a value the units module owns.
    leaf_rows = forest_unit_queries.unit_rows(
        db, calculation_id, forest_unit_queries.View.LEAF
    )
    if leaf_rows:
        units = db_rows_to_units(leaf_rows)
        logger.info(
            f"Extracted {len(units)} units (leaf view) from forest_blocks DB for calculation {calculation_id}"
        )
        return units

    compartments_array = result_data.get("compartments", [])
    blocks_array = result_data.get("blocks", [])

    if workspace_managed:
        # Workspace-mode forest whose blocks/compartments were all deleted — do
        # NOT fall back to stale result_data arrays; drop to the whole-boundary
        # unit so plots at least cover the forest, not a deleted subset.
        if compartments_array or blocks_array:
            logger.warning(
                "calc %s is workspace-managed but has no usable forest_blocks "
                "rows; ignoring stale result_data blocks/compartments and using "
                "the whole boundary",
                calculation_id,
            )
        compartments_array = blocks_array = []
    else:
        # 3) Upload-mode compartments from result_data
        if compartments_array:
            units = result_data_to_units(compartments_array, True)
            if units:
                logger.info(
                    f"Extracted {len(units)} compartments from result_data for calculation {calculation_id}"
                )
                return units

        # 4) Upload-mode blocks from result_data
        if blocks_array:
            units = result_data_to_units(blocks_array, False)
            if units:
                logger.info(
                    f"Extracted {len(units)} blocks from result_data for calculation {calculation_id}"
                )
                return units

    # 5) Whole-boundary fallback (no blocks or compartments anywhere)
    logger.warning(f"No blocks or compartments found for calculation {calculation_id}")
    query = text(
        f"""
        SELECT
            ST_AsText(boundary_geom) as block_wkt,
            ST_Area(ST_Transform(boundary_geom,
                CASE
                    WHEN ST_X(ST_Centroid(boundary_geom)) < 84.0 THEN 32644
                    ELSE 32645
                END
            )) / {SQM_PER_HA} as area_hectares
        FROM public.calculations
        WHERE id = :calc_id
    """
    )
    result = db.execute(query, {"calc_id": str(calculation_id)}).fetchone()
    if result:
        forest_name = calculation.forest_name or "Forest"
        label = "Compartment 1" if compartments_array else "Block 1"
        return [
            (
                1,
                result.block_wkt,
                f"{forest_name} - {label}",
                float(result.area_hectares),
            )
        ]
    return []


def area_basis_from_filter(filter_tree_cover: bool) -> str:
    """Map the filter flag onto the persisted sampling area basis (Phase D)."""
    return "tree_cover" if filter_tree_cover else "full_area"


@dataclass
class SamplingPreviewResult:
    """In-memory result of a sampling engine run in preview mode (rule F).

    Carries the computed summary (identical to the create response) plus the
    plot GeoJSON and area basis so the API can return a pre-create preview
    without writing any DB rows.
    """

    response: "SamplingGenerateResponse"
    points_geojson: dict
    area_basis: str


def _build_preview_points_geojson(points, block_assignments) -> dict:
    """GeoJSON FeatureCollection of plot locations for the pre-create preview (rule F).

    Mirrors the payload built by ``get_sampling_map_layers`` so the shared
    ``SamplingMapView`` renders identical numbered markers/labels to a
    persisted design. ``points`` and ``block_assignments`` are index-aligned
    (both appended per plot in the same order by the two create engines).
    """
    features = []
    for i, (lon, lat) in enumerate(points):
        assignment = block_assignments[i] if i < len(block_assignments) else None
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "plot_number": i + 1,
                    "plot_id": f"P{i+1}",
                    "block_name": (
                        assignment.get("block_name", f"Plot {i+1}")
                        if assignment
                        else f"Plot {i+1}"
                    ),
                    "zone_type": (
                        assignment.get("zone_type", "productive")
                        if assignment
                        else "productive"
                    ),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def low_tree_cover_coverage(blocks_info, threshold_percent: float = 20.0) -> list[str]:
    """Return unit names whose accessible tree-cover area is below the threshold.

    Warning helper (Phase D.2 — raster missing areas): when a unit has very few
    tree-covered pixels, a "tree cover" basis places almost no (or scattered)
    points there. Accepts BlockSamplingInfo objects or plain dicts.

    Raster pixel area can slightly overcount the authoritative polygon area, so
    the ratio is clamped to 100%% before comparing against the threshold.
    """
    low = []
    for b in blocks_info:
        if isinstance(b, dict):
            area = b.get("block_area_hectares") or 0
            accessible = b.get("accessible_forest_area_ha") or 0
            name = b.get("block_name")
        else:
            area = getattr(b, "block_area_hectares", None) or 0
            accessible = getattr(b, "accessible_forest_area_ha", None) or 0
            name = getattr(b, "block_name", None)
        try:
            area = float(area)
            accessible = float(accessible)
        except (TypeError, ValueError):
            continue
        if not name or area <= 0:
            continue
        coverage = min(accessible / area, 1.0)
        if coverage * 100 < threshold_percent:
            low.append(str(name))
    return low


# business: minimum 15 plots per block, 5% sampling intensity; per-block design with boundary buffer
# constraint: pole plots=100m², tree plots=500m² per CFMG
#: The usual highest sampling intensity for a polygon. It is a WARNING level, never a refusal (owner, 2026-10-08: intensity may be
#: raised; the user is told, not stopped). Only going BELOW the stratum's minimum is refused.
MAX_COUNT_INTENSITY_PCT = 5.0


def equivalent_intensity_pct(plots: int, area_ha: float, plot_size_sqm: float) -> float:
    """The intensity a number of plots amounts to for a polygon: plots x plot size / polygon area, in percent."""
    return (float(plots) * float(plot_size_sqm) / (float(area_ha) * SQM_PER_HA) * 100.0) if area_ha else 0.0


def _check_count_against_limits(name: str, stratum: str, plots: int, area_ha: float, plot_size_sqm: float, floor_pct: float) -> float:
    """Hold a typed plot count to the legal minimum, by its equivalent intensity. Returns that intensity.
    Any number of plots is allowed - fewer than the usual 5 included, and more than the usual 5 % ceiling too (the screen warns) -
    as long as it amounts to at least the stratum's minimum intensity (कार्यविधि §16). Raises ``ValueError`` naming the polygon."""
    import json

    pct = equivalent_intensity_pct(plots, area_ha, plot_size_sqm)
    if pct < floor_pct:
        raise ValueError(
            "SFM_INTENSITY_BELOW_FLOOR: "
            + json.dumps({"unit": name, "stratum": stratum, "floor": floor_pct, "value": round(pct, 2), "plots": plots})
        )
    return pct


def _user_excluded_block_info(
    block_number, block_name, block_area_ha, stratum, floor_pct, plot_size_sqm
):
    """BlockSamplingInfo for a unit the user set to 0% ("do not sample")."""
    return BlockSamplingInfo(
        block_number=block_number,
        block_name=block_name,
        block_area_hectares=Decimal(str(round(block_area_ha, 4))),
        samples_generated=0,
        minimum_enforced=False,
        user_excluded=True,
        actual_intensity_percent=Decimal("0"),
        stratum=stratum,
        floor_intensity_pct=Decimal(str(floor_pct)),
        plot_size_sqm=int(plot_size_sqm),
    )


def _refuse_if_every_unit_excluded(blocks_info):
    if blocks_info and all(b.user_excluded for b in blocks_info):
        raise ValueError(
            "Every unit is set to 0% intensity, so no sample plots would be "
            "created. Give at least one unit an intensity above 0."
        )


def create_sampling_design(
    db: Session,
    calculation_id: UUID,
    sampling_type: str,
    sampling_intensity_percent: Optional[Decimal] = None,
    min_samples_per_block: int = 5,
    min_samples_small_blocks: int = 2,
    exempt_sub_mmu_units: bool = True,
    boundary_buffer_meters: float = 50.0,
    # कार्यविधि §16's flat 5-plot-per-unit floor may only ever be RAISED by
    # min_samples_per_block, never lowered -- unless the caller explicitly
    # opts out, PER STRATUM (owner request, 2026-09-15: "let user choose
    # whether to enforce or not; default checked"; refined 2026-09-15: "user
    # should get a chance for each zone -- production, conservation, and
    # protection"). False for a given stratum restores the caller's own
    # min_samples_per_block as that stratum's true floor, with no guideline
    # minimum layered on top; the other strata are unaffected.
    enforce_min_samples_production: bool = True,
    enforce_min_samples_conservation: bool = True,
    enforce_min_samples_protection: bool = True,
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
    block_overrides: Optional[dict] = None,
    preview: bool = False,
) -> Union[SamplingGenerateResponse, SamplingPreviewResult]:
    """
    Create sampling design and generate sampling points PER BLOCK.

    NEW: Supports flexible filtering for accessible forest areas.

    Uses sampling intensity percentage and enforces minimum samples per block.

    Args:
        db: Database session
        calculation_id: Calculation ID
        sampling_type: 'systematic', 'random', or 'stratified'
        sampling_intensity_percent: Percentage of block area to sample (default 0.5%)
        min_samples_per_block: Minimum samples for every unit (default 5). May only raise
            the कार्यविधि §16 flat 5-plot floor, never lower it.
        min_samples_small_blocks: [LEGACY, ignored for sample-count math] the old <1 ha
            exception no longer applies — every classified unit gets the flat 5-plot
            floor via min_samples_per_block regardless of area. Kept for API/response
            compatibility (still echoed in default_parameters).
        exempt_sub_mmu_units: P8 8.1 - when True (default), a unit below the
            absolute MMU is EXEMPT from the flat 5-plot floor, because it is not a
            management unit and cannot hold the plots. It then receives 0 plots and
            is reported as ``mmu_exempt``. This removes the *minimum* only:
            ``samples_from_intensity`` still applies, so a high enough intensity
            still places plots. Opt a unit in with an explicit per-block
            ``min_samples_per_block`` override. Set False to keep the floor for
            every unit regardless of size.
        enforce_min_samples_production/_conservation/_protection: When True
            (default, each independently), the कार्यविधि §16 flat 5-plot floor
            applies on top of min_samples_per_block for units classified into
            that stratum. When False for a given stratum, the floor is
            skipped entirely for units of that stratum only and
            min_samples_per_block alone governs them — an explicit
            per-stratum opt-out, not a silent lowering.
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
        preview: If True, compute the layout without writing any DB rows
            (rule F — pre-create preview). Returns a SamplingPreviewResult
            instead of a SamplingGenerateResponse.

    Returns:
        SamplingGenerateResponse with per-block summary statistics, or
        SamplingPreviewResult when ``preview=True``.
    """
    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise ValueError(f"CALCULATION_NOT_FOUND: गणना {calculation_id} फेला परेन")

    # Use sampling_intensity_percent if provided, otherwise fallback to old intensity_per_hectare
    if sampling_intensity_percent is None and intensity_per_hectare is not None:
        # Convert old intensity_per_hectare to percentage (rough estimate)
        sampling_intensity_percent = Decimal("0.5")
        logger.warning(
            "Using default 0.5% intensity - intensity_per_hectare is deprecated"
        )
    elif sampling_intensity_percent is None:
        sampling_intensity_percent = Decimal("0.5")  # Default

    # Calculate plot area
    plot_area_sqm = None
    if plot_shape == "circular" and plot_radius_meters:
        plot_area_sqm = math.pi * float(plot_radius_meters) ** 2
    elif plot_shape == "circular":
        # Default circular plot: radius 12.6156m = 500m²
        plot_area_sqm = math.pi * (12.6156**2)
        plot_radius_meters = Decimal("12.6156")
    elif (
        plot_shape in ["square", "rectangular"]
        and plot_length_meters
        and plot_width_meters
    ):
        plot_area_sqm = float(plot_length_meters) * float(plot_width_meters)
    else:
        raise ValueError("PLOT_SHAPE_REQUIRED: प्लटको आकार र आयामहरू उल्लेख गर्नुपर्छ")

    # NOTE: plot_area_sqm above is the caller-requested/default plot size, used
    # only for validation, fallback response reporting, and the DB record's
    # declared plot geometry. Actual per-unit sample-count math uses each
    # unit's stratum-enforced plot size (कार्यविधि §16) computed inside the loop.

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
        "exempt_sub_mmu_units": bool(exempt_sub_mmu_units),
        "enforce_min_samples_production": enforce_min_samples_production,
        "enforce_min_samples_conservation": enforce_min_samples_conservation,
        "enforce_min_samples_protection": enforce_min_samples_protection,
        "boundary_buffer_meters": boundary_buffer_meters,
        "min_distance_meters": min_distance_meters,
        # NEW: Accessible forest filter settings
        "filter_tree_cover": filter_tree_cover,
        "filter_slope": filter_slope,
        "max_slope_degrees": max_slope_degrees,
        # Sampling area basis (Phase D): tree_cover | full_area
        "area_basis": area_basis_from_filter(filter_tree_cover),
    }

    # Extract blocks from calculation
    blocks = extract_blocks_from_calculation(db, calculation_id)

    # Get excluded areas (private land) - these areas should NOT have any sample plots
    excluded_areas = get_excluded_areas_for_calculation(db, calculation_id)
    if excluded_areas:
        logger.info(
            f"Found {len(excluded_areas)} excluded areas (private land) - no plots will be placed here"
        )

    # SFM stratum classification per unit (कार्यविधि §16): production / conservation / protection.
    # Enforced for EVERY sampling design (manual/intensity engine included), regardless of whether
    # SFM classification was explicitly requested — the floors are unconditional.
    unit_strata = classify_calc_units(db, calculation_id, blocks)

    # Per-stratum enforce_min_samples lookup (D2, 2026-09-15).
    enforce_min_samples_by_stratum = {
        "production": enforce_min_samples_production,
        "conservation": enforce_min_samples_conservation,
        "protection": enforce_min_samples_protection,
    }

    # Generate sampling points PER BLOCK
    all_points = []
    block_assignments = []
    blocks_info = []
    total_forest_area = 0.0
    summary_sampled_area_sqm = 0.0
    response_plot_size_sqm = (
        None  # Summary plot size = first sampled block's stratum plot size
    )

    for block_number, block_wkt, block_name, block_area_ha in blocks:
        total_forest_area += block_area_ha

        # Apply block-specific overrides if they exist
        block_sampling_type = sampling_type
        block_intensity_percent = sampling_intensity_percent
        block_min_samples_per_block = min_samples_per_block
        block_boundary_buffer = boundary_buffer_meters
        block_min_distance = min_distance_meters

        if block_overrides and block_name in block_overrides:
            override = block_overrides[block_name]
            block_sampling_type = override.get("sampling_type", sampling_type)
            block_intensity_percent = Decimal(
                str(
                    override.get(
                        "sampling_intensity_percent", sampling_intensity_percent
                    )
                )
            )
            block_min_samples_per_block = override.get(
                "min_samples_per_block", min_samples_per_block
            )
            block_boundary_buffer = override.get(
                "boundary_buffer_meters", boundary_buffer_meters
            )
            block_min_distance = override.get(
                "min_distance_meters", min_distance_meters
            )

            logger.info(f"  Applying overrides for {block_name}: {override}")

        # SFM stratum floor enforcement (कार्यविधि §16): users may override by
        # EXCEEDING the floor but never fall below it → 400 naming this unit.
        stratum = unit_strata.get(block_name, "production")
        floor_pct = STRATUM_FLOOR_PCT[stratum]
        # 0% = the user chose not to sample this unit. The one value allowed
        # below the floor; recorded, never a failure.
        explicit_plots = ((block_overrides or {}).get(block_name) or {}).get("sample_count")
        explicit_plots = int(explicit_plots) if explicit_plots is not None else None
        if (explicit_plots is None and float(block_intensity_percent) == 0) or explicit_plots == 0:
            logger.info(f"  {block_name}: 0% intensity - unit excluded from sampling")
            blocks_info.append(
                _user_excluded_block_info(
                    block_number, block_name, block_area_ha, stratum, floor_pct,
                    STRATUM_PLOT_SQM[stratum],
                )
            )
            continue
        if explicit_plots is not None:
            _check_count_against_limits(block_name, stratum, explicit_plots, block_area_ha, STRATUM_PLOT_SQM[stratum], floor_pct)
        elif float(block_intensity_percent) < floor_pct:
            import json

            raise ValueError(
                "SFM_INTENSITY_BELOW_FLOOR: "
                + json.dumps(
                    {
                        "unit": block_name,
                        "stratum": stratum,
                        "floor": floor_pct,
                        "value": float(block_intensity_percent),
                    }
                )
            )

        # Per-stratum plot size for this unit (कार्यविधि §16: 500 m² production/
        # conservation, 100 m² protection) — overrides the caller's global plot
        # size choice, same enforcement as the Guideline-2061 engine.
        block_plot_size_sqm = STRATUM_PLOT_SQM[stratum]
        block_plot_area_hectares = block_plot_size_sqm / SQM_PER_HA

        # NEW: Calculate accessible forest area for this block
        accessible_area_info = None
        effective_block_area = block_area_ha  # Default to total area

        if filter_tree_cover or filter_slope:
            # NOTE: Slope filtering DISABLED - too slow and causes server hang
            accessible_area_info = calculate_accessible_forest_area(
                db=db,
                geometry_wkt=block_wkt,
                filter_tree_cover=filter_tree_cover,
                filter_slope=False,  # ALWAYS False - slope filtering disabled
                max_slope_degrees=max_slope_degrees,
            )

            # Use accessible forest area instead of total block area
            effective_block_area = accessible_area_info.get(
                "accessible_forest_area_ha", block_area_ha
            )

            logger.info(
                f"  {block_name}: Total {block_area_ha:.2f} ha → "
                f"Accessible {effective_block_area:.2f} ha "
                f"({accessible_area_info.get('accessible_forest_percentage', 100):.1f}%)"
            )

            if filter_tree_cover:
                logger.info(f"    - Filtered to tree cover only")
            if filter_slope:
                logger.info(f"    - Excluded slopes >{max_slope_degrees}°")
                if accessible_area_info.get("inaccessible_steep_forest_ha", 0) > 0:
                    logger.info(
                        f"    - Inaccessible steep forest: "
                        f"{accessible_area_info['inaccessible_steep_forest_ha']:.2f} ha"
                    )

        # P8 §8.1 — a sub-MMU unit is EXEMPT from the per-unit minimum.
        #
        # The floor above is a flat 5 plots for every classified unit regardless of
        # area (कार्यविधि §16), and `min_samples_small_blocks` is [LEGACY, ignored for
        # sample-count math]. For a sub-1 ha unit that floor cannot be honoured: a
        # production plot is 500 m², so five need 0.25 ha, and a 50 m inward buffer on
        # a 178 m² sliver leaves no interior at all - at which point
        # `apply_boundary_buffer` falls back to the ORIGINAL polygon and plots land on
        # the boundary, defeating the buffer's purpose. Forcing them would also force a
        # `dbh_class_breakdown` for the sliver, from which the growing-stock reader
        # derives a gs≥40 ratio computed on boundary-clustered plots.
        #
        # Rationale, not a loosening: a sub-MMU unit is **not a management unit**, so
        # the per-unit minimum does not apply to it. The alternative is a forest
        # carrying knowingly invalid plots.
        #
        # This removes the *minimum* only - `samples_from_intensity` still applies
        # below, so a user who asks for an intensity high enough to place plots in
        # this unit still gets them. Opting a unit in is done through the existing
        # per-block override: an explicit `min_samples_per_block` for that unit is
        # taken as the owner asking for it to be sampled.
        mmu_ha = MMU_SLIVER_AREA_M2 / SQM_PER_HA
        unit_override = (block_overrides or {}).get(block_name) or {}
        # Opting a unit IN is explicit. Two ways, and both are deliberate requests:
        # a per-block ``min_samples_per_block`` override, or a global minimum raised
        # above the guideline floor - asking for more than 5 is never accidental,
        # and silently ignoring it on a sub-MMU unit would be a surprise. The
        # default 5 does NOT opt in, because that is just the floor arriving by
        # default rather than a decision about this unit.
        unit_opted_in = "min_samples_per_block" in unit_override or (
            block_min_samples_per_block > MIN_SAMPLES_PER_UNIT
        )
        mmu_exempt = (
            bool(exempt_sub_mmu_units)
            and float(block_area_ha) < mmu_ha
            and not unit_opted_in
        )

        # Minimum samples for this block (कार्यविधि §16: flat 5-plot floor for
        # every classified unit — the old <1 ha → 2-plot exception no longer
        # applies; a caller-requested min_samples_per_block may only raise it,
        # unless this unit's stratum opted out of the guideline floor
        # entirely, in which case its own min_samples_per_block is used as-is).
        if mmu_exempt:
            min_samples = 0
        else:
            min_samples = (
                max(block_min_samples_per_block, MIN_SAMPLES_PER_UNIT)
                if enforce_min_samples_by_stratum.get(stratum, True)
                else block_min_samples_per_block
            )

        # Calculate samples based on intensity (use EFFECTIVE area and this
        # unit's stratum plot size)
        sample_area_hectares = float(effective_block_area) * (
            float(block_intensity_percent) / 100.0
        )
        samples_from_intensity = int(
            sample_area_hectares / float(block_plot_area_hectares)
        )

        # Apply minimum
        samples_for_block = max(min_samples, samples_from_intensity)
        # An exempt unit is never "minimum enforced" - nothing was enforced on it.
        minimum_enforced = (not mmu_exempt) and samples_for_block == min_samples
        if explicit_plots is not None:
            # the user's own number: no minimum was applied to it, and a unit below the MMU is sampled because they asked for it
            samples_for_block, samples_from_intensity, minimum_enforced, mmu_exempt = explicit_plots, explicit_plots, False, False

        if mmu_exempt:
            logger.warning(
                f"[P8] {block_name}: {block_area_ha:.4f} ha is below the {mmu_ha:g} ha MMU - "
                f"exempt from the {MIN_SAMPLES_PER_UNIT}-plot per-unit minimum "
                f"(karavyavidhi 16), 0 plots placed. Too small to hold "
                f"{MIN_SAMPLES_PER_UNIT} x {block_plot_size_sqm:g} m2 plots. Set an explicit "
                f"min_samples_per_block for this unit to sample it anyway."
            )

        logger.info(
            f"  {block_name} ({block_area_ha:.2f} ha, {effective_block_area:.2f} ha accessible): "
            f"{samples_from_intensity} from intensity → {samples_for_block} samples "
            f"(minimum {'enforced' if minimum_enforced else 'not needed'})"
        )

        # NEW PIXEL-BASED APPROACH: Extract tree cover pixel centers as candidate locations
        candidate_pixels = []

        if filter_tree_cover or filter_slope:
            # Extract tree cover pixel centers
            # NOTE: Slope filtering DISABLED - too slow and causes server hang
            # Always extract tree cover only, regardless of filter_slope setting
            if filter_slope:
                logger.warning(
                    f"    ⚠️ Slope filtering requested but DISABLED (too slow). "
                    f"Sampling from all tree cover pixels instead."
                )

            logger.info(
                f"    - Extracting tree cover pixel centers (no slope filter)..."
            )

            candidate_pixels = extract_tree_cover_pixel_centers(
                db=db,
                geometry_wkt=block_wkt,
                filter_slope=False,  # ALWAYS False - slope filtering disabled
                max_slope_degrees=max_slope_degrees,
                min_distance_from_boundary_meters=20.0,  # 2 pixels (10m each) from edge
            )

            if not candidate_pixels:
                logger.warning(
                    f"  {block_name}: No accessible tree pixels found. "
                    f"Try: (1) Disable slope filter, (2) Increase max slope, or (3) Disable tree cover filter."
                )
                # Fall back to full boundary sampling
                candidate_pixels = None

            else:
                logger.info(
                    f"    - Found {len(candidate_pixels)} candidate tree pixels"
                )

        # Track grid spacing for this block (for reporting)
        block_grid_spacing_meters = None

        # Generate points for this block
        #
        # P8 §8.1 - an exempt unit wants no plots, so it must not enter EITHER
        # generation path. Note this guard sits here rather than on the filter
        # branch above: `candidate_pixels` drives the pixel path, and when it is
        # empty the `else` below falls through to the polygon path, which derives a
        # grid spacing from the polygon's own area. Guarding only the filter branch
        # would let that fall-through run, and a sub-MMU unit is exactly the geometry
        # where the spacing computation can come back degenerate - an earlier
        # attempt at this change did precisely that and still placed plots.
        if samples_for_block <= 0:
            block_points = []
            logger.info(
                "    - No samples requested for this unit; skipping point generation"
            )
        elif candidate_pixels:
            # PIXEL-BASED SAMPLING: Sample from tree cover pixel centers
            # Convert pixel centers to (lon, lat) tuples for compatibility
            pixel_points = [(lon, lat) for lon, lat, slope in candidate_pixels]

            # Filter out points in excluded areas (private land)
            if excluded_areas:
                original_count = len(pixel_points)
                pixel_points = [
                    (lon, lat)
                    for lon, lat in pixel_points
                    if not point_in_excluded_area(lon, lat, excluded_areas)
                ]
                filtered_count = original_count - len(pixel_points)
                if filtered_count > 0:
                    logger.info(
                        f"    - Filtered out {filtered_count} pixels in excluded areas (private land). "
                        f"{len(pixel_points)} candidate pixels remaining"
                    )

            if block_sampling_type == "systematic":
                # Systematic sampling: lay a TRUE grid over the block at a spacing
                # derived from the accessible (tree-cover) area, with a random start
                # offset, then snap each grid point to the nearest UNCLAIMED tree
                # pixel within a bounded snap radius. The bounded radius + one-pixel
                # claim stop grid points from collapsing onto the same few pixels in
                # patchy cover — the cause of the short point-to-point distances the
                # user reported. Non-forest holes simply drop their grid points.
                spacing_meters = math.sqrt(
                    float(effective_block_area)
                    * SQM_PER_HA
                    / float(max(1, samples_for_block))
                )
                block_grid_spacing_meters = (
                    spacing_meters  # nominal spacing for reporting
                )

                bounds = get_polygon_bounds(block_wkt)

                # Snap radius: keep perturbations small relative to the lattice cell
                # (≈1/3 of spacing, floor 30m) so plots stay evenly spread.
                snap_radius_m = max(30.0, spacing_meters * 0.35)
                snap_radius_lon = snap_radius_m / 98000.0
                snap_radius_lat = snap_radius_m / 111000.0

                def _snap_grid_to_pixels(grid_pts, pixel_pts):
                    """Snap grid points to the nearest unclaimed tree pixel within
                    the snap radius. Returns (snapped_list, used_pixel_set)."""
                    # Spatial hash keyed by cell = snap radius: a pixel within radius
                    # of a grid point is at most one bucket away in each axis.
                    bucket = {}
                    for tx, ty in pixel_pts:
                        bucket.setdefault(
                            (
                                math.floor(tx / snap_radius_lon),
                                math.floor(ty / snap_radius_lat),
                            ),
                            [],
                        ).append((tx, ty))

                    used = set()
                    selected = []
                    for gx, gy in grid_pts:
                        cx = math.floor(gx / snap_radius_lon)
                        cy = math.floor(gy / snap_radius_lat)
                        best = None
                        best_d2 = None
                        for dx in (-1, 0, 1):
                            for dy in (-1, 0, 1):
                                for tx, ty in bucket.get((cx + dx, cy + dy), ()):
                                    if (tx, ty) in used:
                                        continue
                                    dlon = tx - gx
                                    dlat = ty - gy
                                    if (
                                        abs(dlon) > snap_radius_lon
                                        or abs(dlat) > snap_radius_lat
                                    ):
                                        continue
                                    d2 = dlon * dlon + dlat * dlat
                                    if best_d2 is None or d2 < best_d2:
                                        best_d2 = d2
                                        best = (tx, ty)
                        if best is not None:
                            used.add(best)
                            selected.append(best)
                    return selected, used

                # Iterate: re-scale the lattice 2-D (count ∝ area / spacing²) so the
                # in-polygon count converges to the target — a proper 2-D thinning,
                # not a scan-order [::step] slice that bands/clusters points.
                trial_spacing = spacing_meters
                min_spacing = 25.0
                snapped = []
                used = set()
                for _ in range(5):
                    grid_points = generate_systematic_grid(
                        bounds[0],
                        bounds[1],
                        bounds[2],
                        bounds[3],
                        int(trial_spacing),
                        block_wkt,
                        0.0,
                        random_start=True,
                    )
                    if not grid_points:
                        break
                    snapped, used = _snap_grid_to_pixels(grid_points, pixel_points)
                    if not snapped:
                        trial_spacing *= 0.8
                        continue
                    if len(snapped) == samples_for_block:
                        break
                    next_spacing = trial_spacing * math.sqrt(
                        len(snapped) / float(max(1, samples_for_block))
                    )
                    if next_spacing < min_spacing or next_spacing > spacing_meters * 3:
                        break
                    trial_spacing = next_spacing

                # Residual overshoot (lattice parity): even-pick across the whole
                # lattice — never a scan-order band, which clustered plots in the
                # old code — so the surviving set stays a regular, even grid.
                if len(snapped) > samples_for_block:
                    block_points = _even_pick(snapped, samples_for_block)
                else:
                    block_points = snapped

                if len(block_points) < samples_for_block and pixel_points:
                    # Top-up from still-unclaimed pixels when tree cover is sparse.
                    # Never take scan-order adjacency: pixel_points are in raster
                    # scan order, so [::1] grabs physically adjacent 10m pixels —
                    # those plots cluster and get consecutive plot numbers (the
                    # "8,9,10,11,12 / 93,94,95 all close together" report). Even-
                    # pick across the spatially-sorted unclaimed set instead, so
                    # residual plots stay spread over the whole accessible area.
                    block_points = list(block_points) + list(
                        _top_up_pixels(block_points, pixel_points, samples_for_block)
                    )

                logger.info(
                    f"    - Systematic (grid→tree-snap): {len(block_points)}/{len(pixel_points)} pixels, "
                    f"spacing ~{spacing_meters:.1f}m (snap radius {snap_radius_m:.0f}m)"
                )

            elif block_sampling_type == "random":
                # Random sampling from pixel centers
                if len(pixel_points) <= samples_for_block:
                    block_points = pixel_points
                else:
                    import random as rand

                    block_points = rand.sample(pixel_points, samples_for_block)

                logger.info(
                    f"    - Random sampling: selected {len(block_points)}/{len(pixel_points)} pixels"
                )

            elif block_sampling_type == "stratified":
                # Stratified sampling from pixel centers
                # Divide pixels into strata based on spatial distribution
                if len(pixel_points) <= samples_for_block:
                    block_points = pixel_points
                else:
                    # Simple stratified: divide pixels into groups by lat/lon
                    # Sort by latitude, then take evenly spaced samples
                    sorted_pixels = sorted(pixel_points, key=lambda p: (p[1], p[0]))
                    step = max(1, len(sorted_pixels) // samples_for_block)
                    block_points = sorted_pixels[::step][:samples_for_block]

                logger.info(
                    f"    - Stratified sampling: selected {len(block_points)}/{len(pixel_points)} pixels"
                )

            else:
                raise ValueError(
                    f"SAMPLING_TYPE_INVALID: अमान्य नमूना प्रकार: {block_sampling_type}"
                )

        else:
            # POLYGON-BASED SAMPLING: Fall back to original approach (no filtering)
            logger.info(
                f"    - Using full boundary for sampling (no tree cover filter)"
            )

            # Apply boundary buffer ONCE here (not in the generation functions)
            sampling_polygon_wkt = apply_boundary_buffer(
                block_wkt, block_boundary_buffer
            )

            if block_sampling_type == "systematic":
                # Spacing derived from the ACTUAL (buffered) polygon area, not the
                # bounding box, so the in-polygon grid count lands ≈ the target. The
                # grid uses a random start offset (unbiased SYS). If the count still
                # deviates (irregular/elongated shapes), the lattice is re-scaled
                # 2-D (count ∝ area / spacing²) — a proper grid thinning that keeps
                # plots evenly spread — instead of the old scan-order [::step] slice,
                # which produced bands of close points with gaps between them.
                poly_area_ha = calculate_polygon_area_hectares(sampling_polygon_wkt)
                poly_area_sqm = max(float(poly_area_ha) * SQM_PER_HA, 1.0)
                spacing_meters = math.sqrt(
                    poly_area_sqm / float(max(1, samples_for_block))
                )

                bounds = get_polygon_bounds(sampling_polygon_wkt)
                min_spacing = 25.0  # Do not densify below ~25m
                # int() of a spacing under 1 m is 0, and a zero spacing never advances the lattice (an endless loop for a sliver unit).
                # Only that is clamped here: a normal small unit may still be sampled tighter than min_spacing, as before.
                trial_spacing = max(1.0, spacing_meters)
                candidate_points = []
                # Densify from below until we have AT LEAST the target count.
                for _ in range(6):
                    candidate_points = generate_systematic_grid(
                        bounds[0],
                        bounds[1],
                        bounds[2],
                        bounds[3],
                        int(trial_spacing),
                        sampling_polygon_wkt,
                        0.0,  # Buffer already applied above - don't apply again!
                        random_start=True,
                    )
                    if not candidate_points:
                        trial_spacing = max(min_spacing, trial_spacing * 0.8)
                        continue
                    if len(candidate_points) >= samples_for_block:
                        break
                    next_spacing = trial_spacing * math.sqrt(
                        len(candidate_points) / float(max(1, samples_for_block))
                    )
                    trial_spacing = max(next_spacing, min_spacing)
                    if trial_spacing <= min_spacing:
                        break
                grid_spacing_meters = trial_spacing

                # Residual overshoot (lattice parity): even-pick across the whole
                # lattice — never a scan-order band, which clustered plots in the
                # old code — so the surviving set stays a regular, even grid.
                if len(candidate_points) > samples_for_block:
                    block_points = _even_pick(candidate_points, samples_for_block)
                else:
                    block_points = candidate_points
                block_grid_spacing_meters = (
                    spacing_meters  # Report the requested (nominal) spacing
                )

                logger.info(
                    f"    - Systematic (polygon grid): {len(block_points)}/{len(candidate_points)} grid points, "
                    f"spacing ~{spacing_meters:.1f}m (final {grid_spacing_meters:.1f}m)"
                )

            elif block_sampling_type == "random":
                block_points = generate_random_points(
                    sampling_polygon_wkt,
                    samples_for_block,
                    block_min_distance,
                    0.0,  # Buffer already applied above - don't apply again!
                )

            elif block_sampling_type == "stratified":
                block_points = generate_stratified_points(
                    sampling_polygon_wkt,
                    samples_for_block,
                    num_strata=max(4, samples_for_block // 2),
                    boundary_buffer_meters=0.0,  # Buffer already applied above - don't apply again!
                )

            else:
                raise ValueError(
                    f"SAMPLING_TYPE_INVALID: अमान्य नमूना प्रकार: {block_sampling_type}"
                )

            # Filter out points in excluded areas (private land)
            if excluded_areas and block_points:
                original_count = len(block_points)
                block_points = [
                    (lon, lat)
                    for lon, lat in block_points
                    if not point_in_excluded_area(lon, lat, excluded_areas)
                ]
                filtered_count = original_count - len(block_points)
                if filtered_count > 0:
                    logger.info(
                        f"    - Filtered out {filtered_count} points in excluded areas (private land). "
                        f"{len(block_points)} points remaining"
                    )

        # Store points with block assignment
        for point in block_points:
            all_points.append(point)
            block_assignments.append(
                {
                    "point_index": len(all_points) - 1,
                    "block_number": block_number,
                    "block_name": block_name,
                    "zone_type": "productive",  # Default zone type for basic sampling
                }
            )

        if len(block_points) > 0 and response_plot_size_sqm is None:
            response_plot_size_sqm = block_plot_size_sqm

        summary_sampled_area_sqm += len(block_points) * block_plot_size_sqm

        # Calculate actual intensity for this block (based on effective area
        # and this unit's stratum plot size)
        # Convert all to float to avoid Decimal/float mixing errors
        actual_intensity_pct = (
            Decimal(
                str(
                    (
                        len(block_points)
                        * block_plot_area_hectares
                        / float(effective_block_area)
                    )
                    * 100
                )
            )
            if effective_block_area > 0
            else Decimal("0")
        )

        # Store block info with accessible area information
        block_info_dict = {
            "block_number": block_number,
            "block_name": block_name,
            "block_area_hectares": Decimal(str(round(block_area_ha, 4))),
            "samples_generated": len(block_points),            "minimum_enforced": minimum_enforced,
            "mmu_exempt": mmu_exempt,
            "mmu_exempt_reason": (
                f"below the {mmu_ha:g} ha MMU: too small to hold "
                f"{MIN_SAMPLES_PER_UNIT} x {block_plot_size_sqm:g} m2 plots"
                if mmu_exempt
                else None
            ),
            "sampling_method": block_sampling_type,  # honest 'systematic'|'random'|'stratified'
            "actual_intensity_percent": actual_intensity_pct,
            "grid_spacing_meters": (
                Decimal(str(round(block_grid_spacing_meters, 1)))
                if block_grid_spacing_meters
                else None
            ),
            "stratum": stratum,
            "floor_intensity_pct": Decimal(str(floor_pct)),
            "plot_size_sqm": int(block_plot_size_sqm),
        }

        # Add accessible area information
        if accessible_area_info:
            # Filtering was applied - use calculated values
            block_info_dict["accessible_forest_area_ha"] = Decimal(
                str(round(accessible_area_info.get("accessible_forest_area_ha", 0), 4))
            )
            block_info_dict["accessible_forest_percentage"] = Decimal(
                str(
                    round(
                        accessible_area_info.get("accessible_forest_percentage", 0), 2
                    )
                )
            )
            if filter_slope:
                block_info_dict["inaccessible_steep_forest_ha"] = Decimal(
                    str(
                        round(
                            accessible_area_info.get("inaccessible_steep_forest_ha", 0),
                            4,
                        )
                    )
                )
                block_info_dict["non_forest_area_ha"] = Decimal(
                    str(round(accessible_area_info.get("non_forest_area_ha", 0), 4))
                )
        else:
            # No filtering applied - entire block area is accessible
            block_info_dict["accessible_forest_area_ha"] = Decimal(
                str(round(block_area_ha, 4))
            )
            block_info_dict["accessible_forest_percentage"] = Decimal("100.00")

        blocks_info.append(BlockSamplingInfo(**block_info_dict))

    _refuse_if_every_unit_excluded(blocks_info)

    points = all_points
    logger.info(
        f"Generated total {len(points)} sampling points across {len(blocks)} blocks"
    )

    # DIAGNOSTIC: Log detailed information if no points were generated
    if not points:
        logger.error(
            f"❌ NO POINTS GENERATED - Diagnostics:\n"
            f"  - Total blocks: {len(blocks)}\n"
            f"  - Sampling intensity: {float(sampling_intensity_percent)}%\n"
            f"  - Min samples per block: {min_samples_per_block}\n"
            f"  - Filter tree cover: {filter_tree_cover}\n"
            f"  - Filter slope: {filter_slope}\n"
            f"  - Boundary buffer: {boundary_buffer_meters}m\n"
            f"  - Block details: {[(name, f'{area:.2f} ha') for _, _, name, area in blocks]}"
        )

    if not points:
        if filter_slope or filter_tree_cover:
            filter_description = []
            if filter_tree_cover:
                filter_description.append("tree cover pixels")
            if filter_slope:
                filter_description.append(f"slope ≤ {max_slope_degrees}°")

            raise ValueError(
                f"NO_ACCESSIBLE_FOREST: फिल्टरसँग मेल खाने वन पिक्सेलहरू फेला परेनन्: {' AND '.join(filter_description)}. "
                f"\n\nसम्भावित कारणहरू:"
                f"\n  • सीमाभित्र वन आवरण पत्ता लागेन (ESA WorldCover डेटा जाँच गर्नुहोस्)"
                f"\n  • सबै ढलान {max_slope_degrees}° सीमा भन्दा बढी छ"
                f"\n  • सीमा धेरै सानो छ वा डेटा कभरेज बाहिर छ"
                f"\n\nसमाधानहरू:"
                f"\n  1. सबै वन आवरण नमूना गर्न ढलान फिल्टर असक्षम गर्नुहोस्"
                f"\n  2. अधिकतम ढलान सीमा 60° वा 90° मा बढाउनुहोस्"
                f"\n  3. सम्पूर्ण सीमा नमूना गर्न वन आवरण फिल्टर असक्षम गर्नुहोस्"
                f"\n  4. सीमा वन क्षेत्रसँग ओभरल्याप हुन्छ कि जाँच गर्नुहोस्"
            )
        else:
            raise ValueError(
                "NO_POINTS_GENERATED: नमूना बिन्दुहरू जनरेट भएनन्। सबैभन्दा सामान्य कारण सबै एकाइ न्यूनतम आकारभन्दा सानो भएर MMU-मा छुटे हुनु हो (कुनै एकाइ पनि बिन्दुयोग्य छैन)। पहिले एकाइ-आकार समीक्षा जाँच गर्नुहोस्, त्यसपछि बहुभुज र परिमितिहरू।"
            )

    # Calculate statistics (convert to float to avoid Decimal/float mixing errors).
    # Sampled area is weighted by each unit's stratum plot size (कार्यविधि §16),
    # not a single global plot size — units may span production/conservation/
    # protection strata with different enforced plot areas (500/500/100 m²).
    actual_intensity = Decimal(str(len(points) / float(total_forest_area)))
    total_sampled_area_sqm = summary_sampled_area_sqm
    total_sampled_area_hectares = Decimal(str(total_sampled_area_sqm / SQM_PER_HA))
    sampling_percentage = Decimal(
        str((total_sampled_area_sqm / (float(total_forest_area) * SQM_PER_HA)) * 100)
    )

    if preview:
        # Rule F: computed layout only — no DB rows are written. The summary is
        # identical to the create response; plot locations are returned as
        # GeoJSON so the shared SamplingMapView renders the exact preview.
        preview_token = uuid4()
        preview_response = SamplingGenerateResponse(
            sampling_design_id=preview_token,
            calculation_id=calculation_id,
            sampling_type=sampling_type,
            total_points=len(points),
            total_blocks=len(blocks),
            forest_area_hectares=Decimal(str(round(total_forest_area, 4))),
            requested_intensity_percent=sampling_intensity_percent,
            actual_intensity_per_hectare=actual_intensity,
            plot_area_sqm=Decimal(
                str(round(response_plot_size_sqm or plot_area_sqm, 2))
            ),  # Report first sampled unit's stratum plot size
            total_sampled_area_hectares=total_sampled_area_hectares,
            sampling_percentage=sampling_percentage,
            blocks_info=blocks_info,
        )
        return SamplingPreviewResult(
            response=preview_response,
            points_geojson=_build_preview_points_geojson(points, block_assignments),
            area_basis=area_basis_from_filter(filter_tree_cover),
        )

    # Create MultiPoint geometry WKT
    points_wkt = (
        "MULTIPOINT(" + ", ".join([f"{lon} {lat}" for lon, lat in points]) + ")"
    )

    # Create sampling design record
    sampling_design = SamplingDesign(
        calculation_id=calculation_id,
        sampling_type=sampling_type,
        intensity_per_hectare=Decimal(
            str(len(points) / float(total_forest_area))
        ),  # Calculated (convert to float to avoid type errors)
        grid_spacing_meters=None,  # Not used with intensity-based approach
        min_distance_meters=min_distance_meters,
        plot_shape=plot_shape,
        plot_radius_meters=plot_radius_meters,
        plot_length_meters=plot_length_meters,
        plot_width_meters=plot_width_meters,
        total_points=len(points),
        notes=notes,
    )

    db.add(sampling_design)
    db.flush()  # Get ID

    # Save default parameters and block overrides
    import json

    if default_parameters:
        update_defaults_query = text(
            """
            UPDATE public.sampling_designs
            SET default_parameters = CAST(:params AS jsonb)
            WHERE id = :design_id
        """
        )
        db.execute(
            update_defaults_query,
            {
                "params": json.dumps(default_parameters),
                "design_id": str(sampling_design.id),
            },
        )

    if block_overrides:
        # Convert block_overrides to JSON-serializable format
        serializable_overrides = {}
        for block_name, override_params in block_overrides.items():
            # If override_params is a Pydantic model, convert to dict
            if hasattr(override_params, "model_dump"):
                serializable_overrides[block_name] = override_params.model_dump(
                    exclude_none=True
                )
            elif hasattr(override_params, "dict"):
                serializable_overrides[block_name] = override_params.dict(
                    exclude_none=True
                )
            else:
                serializable_overrides[block_name] = override_params

        update_overrides_query = text(
            """
            UPDATE public.sampling_designs
            SET block_overrides = CAST(:overrides AS jsonb)
            WHERE id = :design_id
        """
        )
        db.execute(
            update_overrides_query,
            {
                "overrides": json.dumps(serializable_overrides),
                "design_id": str(sampling_design.id),
            },
        )

    # Update geometry using PostGIS
    update_geom_query = text(
        """
        UPDATE public.sampling_designs
        SET points_geometry = ST_GeomFromText(:points_wkt, 4326)
        WHERE id = :design_id
    """
    )
    db.execute(
        update_geom_query,
        {"points_wkt": points_wkt, "design_id": str(sampling_design.id)},
    )

    # Save block assignments directly (we already calculated them)
    update_assignments_query = text(
        """
        UPDATE public.sampling_designs
        SET points_block_assignment = CAST(:assignments AS jsonb)
        WHERE id = :design_id
    """
    )
    db.execute(
        update_assignments_query,
        {
            "assignments": json.dumps(block_assignments),
            "design_id": str(sampling_design.id),
        },
    )

    db.commit()

    response = SamplingGenerateResponse(
        sampling_design_id=sampling_design.id,
        calculation_id=calculation_id,
        sampling_type=sampling_type,
        total_points=len(points),
        total_blocks=len(blocks),
        forest_area_hectares=Decimal(str(round(total_forest_area, 4))),
        requested_intensity_percent=sampling_intensity_percent,
        actual_intensity_per_hectare=actual_intensity,
        plot_area_sqm=Decimal(
            str(round(response_plot_size_sqm or plot_area_sqm, 2))
        ),  # Report first sampled unit's stratum plot size
        total_sampled_area_hectares=total_sampled_area_hectares,
        sampling_percentage=sampling_percentage,
        blocks_info=blocks_info,
    )

    # Persist computed data so it loads instantly on page revisit
    # H8.2 / S2-63: derived output, not somebody's concurrent edit, so the
    # version is declared rather than bumped -- bumping would give a client
    # holding the current version a 409 because someone else merely read or
    # regenerated this. See optimistic_lock.record_derived_write.
    optimistic_lock.record_derived_write(
        db,
        "sampling",
        sampling_design.id,
        "sampling generation result",
    )
    sampling_design.result_data = response.model_dump(mode="json")
    db.add(sampling_design)

    return response


def get_sampling_points_geojson(db: Session, design_id: UUID) -> dict:
    """
    Get sampling points as GeoJSON with complete field data.
    Includes: plot_number, block, coordinates, elevation, UTM, distance from boundary

    Args:
        db: Database session
        design_id: Sampling design ID

    Returns:
        GeoJSON FeatureCollection with complete properties
    """
    # Get sampling design
    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()
    if not design:
        raise ValueError(f"SAMPLING_DESIGN_NOT_FOUND: नमूना डिजाइन {design_id} फेला परेन")

    query = text(
        """
        SELECT
            ST_AsText(points_geometry) as wkt,
            points_block_assignment
        FROM public.sampling_designs
        WHERE id = :design_id
    """
    )

    result = db.execute(query, {"design_id": str(design_id)}).first()

    if not result or not result.wkt:
        raise ValueError(
            f"SAMPLING_DESIGN_EMPTY: नमूना डिजाइन {design_id} फेला परेन वा बिन्दुहरू छैनन्"
        )

    # Parse MultiPoint geometry
    from shapely import wkt as shapely_wkt

    multipoint = shapely_wkt.loads(result.wkt)
    block_assignment = result.points_block_assignment or []

    # Get calculation boundary for distance calculation
    calc = db.query(Calculation).filter(Calculation.id == design.calculation_id).first()
    calc = db.query(Calculation).filter(Calculation.id == design.calculation_id).first()
    boundary_wkt = None
    if calc:
        boundary_query = text(
            """
            SELECT ST_AsText(boundary_geom) as wkt
            FROM public.calculations
            WHERE id = :calc_id
        """
        )
        boundary_result = db.execute(
            boundary_query, {"calc_id": str(design.calculation_id)}
        ).first()
        if boundary_result:
            boundary_wkt = boundary_result.wkt

    # Import required modules for calculations
    from app.utils.geospatial import extract_elevation_at_point
    from pyproj import Transformer

    # Convert to FeatureCollection with individual points and complete data
    features = []
    for i, point in enumerate(multipoint.geoms):
        lon, lat = point.x, point.y

        # Find block assignment for this point
        block_info = next(
            (b for b in block_assignment if b.get("point_index") == i), None
        )
        block_number = block_info.get("block_number", "") if block_info else ""
        block_name = block_info.get("block_name", "") if block_info else ""
        zone_type = (
            block_info.get("zone_type", "productve") if block_info else "productive"
        )

        # Calculate UTM coordinates
        utm_zone = 44 if lon < 84 else 45  # Nepal is in zones 44N and 45N
        transformer = Transformer.from_crs(
            f"EPSG:4326", f"EPSG:326{utm_zone}", always_xy=True
        )
        utm_easting, utm_northing = transformer.transform(lon, lat)

        # Extract elevation (ASLM - Above Sea Level Meter)
        elevation_m = extract_elevation_at_point(db, lon, lat)

        # Calculate distance from boundary (if available)
        distance_from_boundary = None
        if boundary_wkt:
            try:
                boundary_geom = shapely_wkt.loads(boundary_wkt)
                distance_from_boundary = (
                    point.distance(boundary_geom.boundary) * METERS_PER_DEGREE_LAT
                )  # Convert degrees to meters (approximate)
            except Exception:
                logger.warning(
                    "distance-from-boundary unavailable - the column is left empty "
                    "for this point",
                    exc_info=True,
                )

        feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "plot_number": i + 1,
                "block_number": block_number,
                "block_name": block_name,
                "zone_type": zone_type,  # 'productive' or 'protected'
                "longitude": float(f"{lon:.7f}"),
                "latitude": float(f"{lat:.7f}"),
                "elevation_m": int(elevation_m) if elevation_m else None,
                "utm_easting": float(f"{utm_easting:.2f}"),
                "utm_northing": float(f"{utm_northing:.2f}"),
                "utm_zone": f"{utm_zone}N",
                "distance_from_boundary_m": (
                    float(f"{distance_from_boundary:.2f}")
                    if distance_from_boundary
                    else None
                ),
                "sampling_type": design.sampling_type,
            },
        }
        features.append(feature)

    return {"type": "FeatureCollection", "features": features}


# constraint: UTM zone 45N transform for accurate hectare calculation in Nepal
def calculate_geometry_area_hectares(geom):
    """
    Calculate geometry area in hectares using proper UTM projection.

    Args:
        geom: Shapely geometry in EPSG:4326

    Returns:
        Area in hectares
    """
    from shapely.ops import transform
    from pyproj import Transformer

    if geom is None or geom.is_empty:
        return 0.0

    # Get centroid to determine UTM zone
    centroid = geom.centroid
    lon = centroid.x

    # Determine UTM zone for Nepal (44N or 45N)
    utm_zone = 44 if lon < 84.0 else 45
    utm_epsg = f"EPSG:326{utm_zone}"

    # Transform to UTM
    to_utm = Transformer.from_crs("EPSG:4326", utm_epsg, always_xy=True)
    geom_utm = transform(to_utm.transform, geom)

    # Area in square meters, convert to hectares
    return geom_utm.area / SQM_PER_HA


# business: separate productive vs protected zone net areas for Guideline-2061 compliant sampling design
def calculate_zone_net_areas(
    block_wkt: str,
    sub_areas: List[Dict],
    excluded_areas: List[Polygon],
    calculate_protected_separately: bool = True,
) -> Dict:
    """
    Calculate net productive and protected areas after private land deduction.

    Args:
        block_wkt: WKT string of block polygon
        sub_areas: List of sub-area dictionaries
        excluded_areas: List of excluded (private land) polygons
        calculate_protected_separately: If True, calculate protected as separate zone.
                                        If False, treat protected as excluded area.

    Returns:
        Dictionary with:
        {
            "productive_area_ha": float - Net productive forest area
            "protected_area_ha": float - Net protected zone area
            "private_land_area_ha": float - Total private land in block
            "block_geometry": Polygon - Block geometry object
            "productive_geometry": Polygon/MultiPolygon - Productive zone geometry
            "protected_geometry": Polygon/MultiPolygon - Protected zone geometry (or None)
        }
    """
    from shapely.ops import unary_union
    from shapely.geometry import GeometryCollection, shape

    # Parse block geometry
    block_geom = wkt.loads(block_wkt)

    # Calculate area properly using UTM projection
    block_area_ha = calculate_geometry_area_hectares(block_geom)

    # Extract protected zone geometries from sub-areas (only if calculating separately)
    protected_geoms = []
    if calculate_protected_separately:
        for sa in sub_areas:
            if sa.get("category") in PROTECTION_SUB_AREA_CATEGORIES and not sa.get("isExcluded", False):
                try:
                    geom_data = sa["geometry"]

                    # Handle GeometryCollection
                    if geom_data.get("type") == "GeometryCollection":
                        geom_collection = shape(geom_data)
                        polygons = [
                            g
                            for g in geom_collection.geoms
                            if g.geom_type in ("Polygon", "MultiPolygon")
                            and not g.is_empty
                        ]
                        if polygons:
                            geom = (
                                unary_union(polygons)
                                if len(polygons) > 1
                                else polygons[0]
                            )
                            protected_geoms.append(geom)
                    else:
                        geom = shape(geom_data)
                        if not geom.is_empty:
                            protected_geoms.append(geom)
                except Exception as e:
                    logger.warning(
                        f"Failed to parse protected zone in area calculation: {e}"
                    )

    # Combine all protected zones within this block
    if protected_geoms:
        protected_union = unary_union(protected_geoms)
        protected_in_block = block_geom.intersection(protected_union)
    else:
        protected_in_block = None

    # Combine all excluded areas (private land)
    if excluded_areas:
        excluded_union = unary_union(excluded_areas)
        excluded_in_block = block_geom.intersection(excluded_union)
    else:
        excluded_in_block = None

    # Calculate areas using proper UTM projection
    protected_area_ha = (
        calculate_geometry_area_hectares(protected_in_block)
        if protected_in_block
        else 0.0
    )
    private_land_area_ha = (
        calculate_geometry_area_hectares(excluded_in_block)
        if excluded_in_block
        else 0.0
    )

    # Calculate net productive area (block - protected - private land)
    productive_geom = block_geom
    if protected_in_block and not protected_in_block.is_empty:
        productive_geom = productive_geom.difference(protected_in_block)
    if excluded_in_block and not excluded_in_block.is_empty:
        productive_geom = productive_geom.difference(excluded_in_block)

    productive_area_ha = (
        calculate_geometry_area_hectares(productive_geom)
        if productive_geom and not productive_geom.is_empty
        else 0.0
    )

    # Calculate net protected area (protected - private land)
    protected_net_geom = None
    if protected_in_block and not protected_in_block.is_empty:
        protected_net_geom = protected_in_block
        if excluded_in_block and not excluded_in_block.is_empty:
            protected_net_geom = protected_net_geom.difference(excluded_in_block)

    protected_net_area_ha = (
        calculate_geometry_area_hectares(protected_net_geom)
        if protected_net_geom
        else 0.0
    )

    # Debug logging
    logger.warning(
        f"DEBUG Area Calculation (FIXED WITH UTM):\n"
        f"  Block total: {block_area_ha:.4f} ha\n"
        f"  Protected overlap: {protected_area_ha:.4f} ha\n"
        f"  Private land: {private_land_area_ha:.4f} ha\n"
        f"  Productive (net): {productive_area_ha:.4f} ha\n"
        f"  Protected (net): {protected_net_area_ha:.4f} ha"
    )

    return {
        "productive_area_ha": productive_area_ha,
        "protected_area_ha": protected_net_area_ha,
        "private_land_area_ha": private_land_area_ha,
        "block_geometry": block_geom,
        "productive_geometry": (
            productive_geom
            if productive_geom and not productive_geom.is_empty
            else None
        ),
        "protected_geometry": (
            protected_net_geom
            if protected_net_geom and not protected_net_geom.is_empty
            else None
        ),
    }


# business: Guideline-2061 implements Nepal DoF standard; sample counts from lookup tables, not intensity %
# constraint: pole plots=100m², tree plots=500m² per CFMG; productive 0.5%/1%, protected 0.1%
def create_sampling_design_guideline_2061(
    db: Session,
    calculation_id: UUID,
    productive_intensity: float,  # 0.5, 1.0 or 2.0
    sample_protected_zone: bool,
    plot_size_sqm: int,
    plot_shape: str = "circular",
    filter_tree_cover: bool = True,
    filter_slope: bool = False,
    max_slope_degrees: float = 45.0,
    boundary_buffer_meters: float = 50.0,
    notes: Optional[str] = None,
    preview: bool = False,
    per_block_intensity: Optional[Dict[str, float]] = None,
    # an explicit number of plots per polygon (the user typed it or accepted the suggestion); replaces the intensity arithmetic
    per_block_plots: Optional[Dict[str, int]] = None,
    # कार्यविधि §16's flat 5-plot-per-unit floor -- see create_sampling_design's
    # matching parameters, per stratum (D2, 2026-09-15). The productive-zone
    # floor is keyed by the BLOCK's own stratum (production/conservation/
    # protection); the protected-zone 0.1% sub-sampling is always a
    # "protection" stratum sample regardless of the parent block's stratum,
    # so it is always governed by enforce_min_samples_protection.
    enforce_min_samples_production: bool = True,
    enforce_min_samples_conservation: bool = True,
    enforce_min_samples_protection: bool = True,
) -> Union[SamplingGenerateResponse, SamplingPreviewResult]:
    """
    Create sampling design using Forest Inventory Guideline-2061.

    This implements Nepal's Department of Forest standard sampling methodology
    where sample counts are determined by lookup tables based on block size,
    rather than calculated from intensity percentages.

    Key differences from manual sampling:
    1. Sample counts determined by guideline tables (not intensity %)
    2. Different intensities for productive (0.5% or 1%) vs protected (0.1%) zones
    3. Supports mixed sampling (productive + protected in same forest)
    4. Systematic sampling only (as per guideline)
    5. Falls back to manual calculation if block exceeds table range

    Block Classification:
    - Blocks are classified as productive or protected based on >50% overlap rule
    - Protected blocks sampled at 0.1% (if sample_protected_zone=True)
    - Productive blocks sampled at 0.5% or 1% (user choice)

    Args:
        db: Database session
        calculation_id: Calculation ID
        productive_intensity: 0.5 or 1.0 (for productive blocks)
        sample_protected_zone: If True, sample protected areas at 0.1%
        plot_size_sqm: Plot size (100-500 for production, 25-100 for protected)
        plot_shape: 'circular' or 'square'
        filter_tree_cover: Exclude non-forest areas (recommended)
        filter_slope: Exclude steep slopes (optional, slow)
        max_slope_degrees: Maximum slope threshold
        boundary_buffer_meters: Minimum distance from boundary
        notes: Design notes
        preview: If True, compute the layout without writing any DB rows
            (rule F — pre-create preview). Returns a SamplingPreviewResult.
        per_block_intensity: Optional block_name -> intensity_pct map overriding
            productive_intensity for the named blocks (e.g. SFM's Production/
            Conservation/Protection classification, कार्यविधि §16). A block not
            in the map still uses productive_intensity. Every distinct value is
            validated the same way productive_intensity itself is (400 on an
            invalid value, naming the offending block).

    Returns:
        SamplingGenerateResponse with per-block summary, or SamplingPreviewResult
        when ``preview=True``.

    Raises:
        ValueError: If parameters are invalid or calculation not found
    """
    import math  # Import at function start for NaN checks
    import json

    logger.info(
        f"Creating Guideline-2061 sampling design: "
        f"productive={productive_intensity}%, protected={'Yes' if sample_protected_zone else 'No'}, "
        f"plot_size={plot_size_sqm}sqm"
        + (
            f", per_block_intensity={per_block_intensity}"
            if per_block_intensity
            else ""
        )
    )

    # Validate every distinct per-block intensity up front (before any GIS
    # work) — a bad value should 400 naming the block, not surface as a
    # confusing failure deep in the per-block loop.
    if per_block_intensity:
        for _bn, _pct in per_block_intensity.items():
            if _pct == 0:  # 0 = exclude this unit; nothing to validate
                continue
            try:
                validate_guideline_parameters(
                    intensity_percent=_pct,
                    plot_size_sqm=plot_size_sqm,
                    is_protected_sampling=False,
                )
            except ValueError as _e:
                raise ValueError(f"per_block_intensity['{_bn}']: {_e}")

    # Validate guideline parameters for productive zones only
    # (Protected zones always use 100 sqm, so no need to validate user's choice)
    validate_guideline_parameters(
        intensity_percent=productive_intensity,
        plot_size_sqm=plot_size_sqm,
        is_protected_sampling=False,  # Validating production params
    )

    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise ValueError(f"CALCULATION_NOT_FOUND: गणना {calculation_id} फेला परेन")

    # Calculate plot dimensions for PRODUCTIVE zones
    productive_plot_size_sqm = plot_size_sqm
    productive_plot_area_hectares = productive_plot_size_sqm / SQM_PER_HA

    # For PROTECTED zones, always use 100 sqm (standard for protected areas)
    protected_plot_size_sqm = 100
    protected_plot_area_hectares = protected_plot_size_sqm / SQM_PER_HA

    if plot_shape == "circular":
        productive_plot_radius = math.sqrt(productive_plot_size_sqm / math.pi)
        protected_plot_radius = math.sqrt(protected_plot_size_sqm / math.pi)
    else:
        productive_plot_radius = None
        protected_plot_radius = None

    logger.info(
        f"Plot configuration:\n"
        f"  Productive zones: {productive_plot_size_sqm} sqm\n"
        f"  Protected zones: {protected_plot_size_sqm} sqm (standard for protected areas)"
    )

    # Extract blocks from calculation
    blocks = extract_blocks_from_calculation(db, calculation_id)

    # Get excluded areas (private land)
    excluded_areas = get_excluded_areas_for_calculation(db, calculation_id)
    if excluded_areas:
        logger.info(f"Found {len(excluded_areas)} excluded areas (private land)")

    # Get sub-areas for block classification
    sub_areas = calculation.result_data.get("sub_areas", [])

    # SFM stratum classification per unit (कार्यविधि §16): production / conservation / protection
    unit_strata = classify_calc_units(db, calculation_id, blocks)

    # Per-stratum enforce_min_samples lookup (D2, 2026-09-15).
    enforce_min_samples_by_stratum = {
        "production": enforce_min_samples_production,
        "conservation": enforce_min_samples_conservation,
        "protection": enforce_min_samples_protection,
    }

    # Protected zone geometries (if NOT sampling them, add to excluded areas)
    if not sample_protected_zone:
        protected_geometries = []
        for sa in sub_areas:
            if sa.get("category") in PROTECTION_SUB_AREA_CATEGORIES and not sa.get("isExcluded", False):
                from shapely.geometry import shape, GeometryCollection

                try:
                    geom_data = sa["geometry"]

                    # Handle GeometryCollection - extract only Polygon/MultiPolygon
                    if geom_data.get("type") == "GeometryCollection":
                        geom_collection = shape(geom_data)

                        # Extract only polygonal geometries
                        polygons = [
                            g
                            for g in geom_collection.geoms
                            if g.geom_type in ("Polygon", "MultiPolygon") and g.area > 0
                        ]

                        if polygons:
                            from shapely.ops import unary_union

                            geom = (
                                unary_union(polygons)
                                if len(polygons) > 1
                                else polygons[0]
                            )
                            protected_geometries.append(geom)
                    else:
                        # Regular Polygon or MultiPolygon
                        geom = shape(geom_data)

                        # Skip zero-area geometries
                        if geom.area > 0:
                            protected_geometries.append(geom)

                except Exception as e:
                    logger.warning(f"Failed to parse protected zone geometry: {e}")

        if protected_geometries:
            # Add protected zones to excluded areas so they're treated as off-limits
            excluded_areas.extend(protected_geometries)
            logger.warning(
                f"Protected zones will be excluded from sampling "
                f"({len(protected_geometries)} zones added to excluded areas)"
            )

    # Generate sampling points PER BLOCK with SEPARATE ZONE SAMPLING
    all_points = []
    block_assignments = []
    blocks_info = []
    total_forest_area = 0.0
    summary_sampled_area_sqm = 0.0
    response_plot_size_sqm = (
        None  # Summary plot size = first sampled block's stratum plot size
    )

    for block_number, block_wkt, block_name, block_area_ha in blocks:
        total_forest_area += block_area_ha

        # Per-compartment stratified intensity (SFM Production/Conservation/
        # Protection classification, कार्यविधि §16) overrides the global
        # productive_intensity for named blocks only; everything else keeps
        # today's single global value.
        this_block_intensity = (
            per_block_intensity.get(block_name, productive_intensity)
            if per_block_intensity
            else productive_intensity
        )

        # SFM stratum floor enforcement (कार्यविधि §16): users may override by
        # EXCEEDING the floor but never fall below it → 400 naming this unit.
        stratum = unit_strata.get(block_name, "production")
        floor_pct = STRATUM_FLOOR_PCT[stratum]
        # 0% = the user chose not to sample this unit (allowed below the floor).
        explicit_plots = (per_block_plots or {}).get(block_name)
        explicit_plots = int(explicit_plots) if explicit_plots is not None else None
        if (explicit_plots is None and this_block_intensity == 0) or explicit_plots == 0:
            logger.info(f"{block_name}: 0% intensity - unit excluded from sampling")
            blocks_info.append(
                _user_excluded_block_info(
                    block_number, block_name, block_area_ha, stratum, floor_pct,
                    STRATUM_PLOT_SQM[stratum],
                )
            )
            continue
        if explicit_plots is not None:
            _check_count_against_limits(block_name, stratum, explicit_plots, block_area_ha, STRATUM_PLOT_SQM[stratum], floor_pct)
        elif this_block_intensity < floor_pct:
            raise ValueError(
                "SFM_INTENSITY_BELOW_FLOOR: "
                + json.dumps(
                    {
                        "unit": block_name,
                        "stratum": stratum,
                        "floor": floor_pct,
                        "value": this_block_intensity,
                    }
                )
            )

        logger.warning(
            f"\n{'='*60}\n"
            f"Processing: {block_name} ({block_area_ha:.2f} ha total)\n"
            f"{'='*60}"
        )

        # ENHANCED DIAGNOSTICS
        logger.warning(f"DEBUG: sample_protected_zone = {sample_protected_zone}")
        logger.warning(f"DEBUG: Number of sub_areas = {len(sub_areas)}")
        logger.warning(f"DEBUG: Number of excluded_areas = {len(excluded_areas)}")

        # Calculate net areas for productive and protected zones (after private land deduction)
        try:
            zone_areas = calculate_zone_net_areas(
                block_wkt,
                sub_areas,
                excluded_areas,
                calculate_protected_separately=sample_protected_zone,
            )
            logger.warning(f"DEBUG: zone_areas keys = {list(zone_areas.keys())}")
        except Exception as e:
            logger.error(f"ERROR calculating areas for {block_name}: {e}")
            import traceback

            logger.error(traceback.format_exc())
            # Fallback: use entire block as productive
            zone_areas = {
                "productive_area_ha": block_area_ha,
                "protected_area_ha": 0.0,
                "private_land_area_ha": 0.0,
                "block_geometry": wkt.loads(block_wkt),
                "productive_geometry": wkt.loads(block_wkt),
                "protected_geometry": None,
            }

        productive_area_ha = zone_areas["productive_area_ha"]
        protected_area_ha = zone_areas["protected_area_ha"]
        private_land_ha = zone_areas["private_land_area_ha"]
        productive_geom = zone_areas.get("productive_geometry")
        protected_geom = zone_areas.get("protected_geometry")

        logger.warning(
            f"Area Breakdown:\n"
            f"  Total: {block_area_ha:.4f} ha\n"
            f"  Productive (net): {productive_area_ha:.4f} ha\n"
            f"  Protected (net): {protected_area_ha:.4f} ha\n"
            f"  Private Land: {private_land_ha:.4f} ha\n"
            f"  Productive geometry: {'EMPTY' if not productive_geom or productive_geom.is_empty else 'OK'}\n"
            f"  Protected geometry: {'EMPTY' if not protected_geom or (hasattr(protected_geom, 'is_empty') and protected_geom.is_empty) else 'OK' if protected_geom else 'None'}"
        )

        # Determine which zones to sample
        sample_productive = productive_area_ha > 0.01  # At least 0.01 ha (100 sqm)
        sample_protected_this_block = sample_protected_zone and protected_area_ha > 0.01

        # Per-stratum plot size for this unit's productive zone (कार्यविधि §16:
        # 500 m² production/conservation, 100 m² protection). Protected zones
        # always use the standard 100 m² below.
        block_plot_size_sqm = STRATUM_PLOT_SQM[stratum]
        block_plot_area_hectares = block_plot_size_sqm / SQM_PER_HA

        logger.warning(
            f"DEBUG: sample_productive = {sample_productive} (area: {productive_area_ha:.4f} ha)"
        )
        logger.warning(
            f"DEBUG: sample_protected_this_block = {sample_protected_this_block} (area: {protected_area_ha:.4f} ha)"
        )

        if not sample_productive and not sample_protected_this_block:
            logger.warning(f"⚠ No sampleable area in {block_name} - SKIPPING BLOCK!")
            logger.warning(
                f"   Reason: productive_area_ha={productive_area_ha:.4f}, protected_area_ha={protected_area_ha:.4f}, sample_protected_zone={sample_protected_zone}"
            )
            continue

        # PRODUCTIVE ZONE SAMPLING
        productive_samples = []
        productive_sample_count = 0
        productive_spacing = None
        productive_sampling_method = (
            "systematic"  # Default, will be updated if random used
        )
        productive_min_enforced = False

        # The productive zone IS this block's own classified stratum
        # (production/conservation/protection) -- enforce per that stratum.
        enforce_productive_min = enforce_min_samples_by_stratum.get(stratum, True)

        if sample_productive:
            logger.info(
                f"\n--- Productive Zone ({productive_area_ha:.4f} ha at {this_block_intensity}%) ---"
            )

            try:
                productive_sample_count = get_sample_count_from_guideline(
                    db=db,
                    block_area_hectares=productive_area_ha,
                    intensity_percent=this_block_intensity,
                    plot_size_sqm=block_plot_size_sqm,
                )
                if enforce_productive_min:
                    productive_min_enforced = (
                        productive_sample_count < MIN_SAMPLES_PER_UNIT
                    )
                    productive_sample_count = max(
                        MIN_SAMPLES_PER_UNIT, productive_sample_count
                    )
                logger.info(
                    f"✓ Guideline table: {productive_sample_count} samples ({block_plot_size_sqm} sqm plots)"
                )
            except ValueError:
                # Fallback to manual calculation
                sample_area_ha = productive_area_ha * (this_block_intensity / 100.0)
                productive_sample_count = int(sample_area_ha / block_plot_area_hectares)
                if enforce_productive_min:
                    productive_min_enforced = (
                        productive_sample_count < MIN_SAMPLES_PER_UNIT
                    )
                    productive_sample_count = max(
                        MIN_SAMPLES_PER_UNIT, productive_sample_count
                    )
                logger.info(
                    f"✓ Manual calc: {productive_sample_count} samples ({block_plot_size_sqm} sqm plots)"
                )

            if explicit_plots is not None:
                # the user's own number for this polygon: used as it is, no minimum applied
                productive_sample_count = explicit_plots
                productive_min_enforced = False

            logger.warning(
                f"DEBUG: Checking productive sample generation: count={productive_sample_count}, geometry={'OK' if zone_areas.get('productive_geometry') else 'NONE/EMPTY'}"
            )

            if productive_sample_count > 0 and zone_areas["productive_geometry"]:
                # Generate samples in productive zone only
                productive_wkt = zone_areas["productive_geometry"].wkt
                productive_buffered = apply_boundary_buffer(
                    productive_wkt, boundary_buffer_meters
                )
                productive_sampling_method = "systematic"

                logger.warning(
                    f"DEBUG: productive_buffered WKT length = {len(productive_buffered)}"
                )

                # Try systematic grid with current buffer first
                effective_area_sqm = productive_area_ha * SQM_PER_HA
                systematic_success = False

                for iteration in range(5):
                    spacing = math.sqrt(
                        effective_area_sqm / float(productive_sample_count)
                    )
                    bounds = get_polygon_bounds(productive_buffered)
                    candidates = generate_systematic_grid(
                        bounds[0],
                        bounds[1],
                        bounds[2],
                        bounds[3],
                        int(spacing),
                        productive_buffered,
                        0.0,  # No additional buffer - already buffered
                    )

                    logger.warning(
                        f"DEBUG: Iteration {iteration}: spacing={spacing:.1f}m, candidates={len(candidates)}, target={productive_sample_count}"
                    )

                    if len(candidates) >= productive_sample_count:
                        productive_samples = candidates[:productive_sample_count]
                        productive_spacing = spacing
                        systematic_success = True
                        logger.info(
                            f"  Generated {len(productive_samples)} productive samples (systematic)"
                        )
                        break
                    effective_area_sqm *= 0.9

                # Fallback 1: Try smaller buffer (15m)
                if not systematic_success and productive_sample_count > 0:
                    logger.warning(
                        f"  ⚠ Systematic failed with {boundary_buffer_meters}m buffer, trying 15m buffer..."
                    )
                    productive_buffered_15m = apply_boundary_buffer(
                        productive_wkt, 15.0
                    )
                    effective_area_sqm = productive_area_ha * SQM_PER_HA

                    for iteration in range(5):
                        spacing = math.sqrt(
                            effective_area_sqm / float(productive_sample_count)
                        )
                        bounds = get_polygon_bounds(productive_buffered_15m)
                        candidates = generate_systematic_grid(
                            bounds[0],
                            bounds[1],
                            bounds[2],
                            bounds[3],
                            int(spacing),
                            productive_buffered_15m,
                            0.0,
                        )

                        if len(candidates) >= productive_sample_count:
                            productive_samples = candidates[:productive_sample_count]
                            productive_spacing = spacing
                            systematic_success = True
                            logger.info(
                                f"  Generated {len(productive_samples)} productive samples (systematic, 15m buffer)"
                            )
                            break
                        effective_area_sqm *= 0.9

                # Fallback 2: Random sampling
                if not systematic_success and productive_sample_count > 0:
                    logger.warning(
                        f"  ⚠ Systematic failed, falling back to random sampling..."
                    )
                    min_distance = int(
                        math.sqrt(effective_area_sqm / productive_sample_count)
                    )
                    # Too wide a spacing in a small polygon leaves fewer plots than were asked for (3 requested, 1 placed). Relax the
                    # spacing step by step - never below one plot's width, so plots do not overlap - until the requested number fits.
                    plot_width_m = int(2 * math.sqrt(block_plot_size_sqm / math.pi)) + 1
                    productive_samples = []
                    for _relax in (1.0, 0.75, 0.5, 0.35):
                        _got = generate_random_points(
                            productive_buffered,
                            productive_sample_count,
                            min_distance_meters=max(int(min_distance * _relax), plot_width_m),
                            boundary_buffer_meters=0.0,  # Already buffered
                        )
                        if len(_got) > len(productive_samples):
                            productive_samples = _got
                        if len(productive_samples) >= productive_sample_count:
                            break
                    if len(productive_samples) > 0:
                        productive_sampling_method = "random"
                        logger.info(
                            f"  Generated {len(productive_samples)} productive samples (random)"
                        )
                    else:
                        logger.warning(
                            "  ⚠ Failed to generate productive samples (random also failed)"
                        )

        # PROTECTED ZONE SAMPLING
        protected_samples = []
        protected_sample_count = 0
        protected_spacing = None
        protected_sampling_method = (
            "systematic"  # Default, will be updated if random used
        )
        protected_min_enforced = False

        if sample_protected_this_block:
            logger.info(
                f"\n--- Protected Zone ({protected_area_ha:.4f} ha at 0.1%) ---"
            )

            try:
                protected_sample_count = get_sample_count_from_guideline(
                    db=db,
                    block_area_hectares=protected_area_ha,
                    intensity_percent=0.1,
                    plot_size_sqm=protected_plot_size_sqm,
                )
                # The protected-zone sub-sample is always a "protection"
                # stratum sample, regardless of the parent block's own stratum.
                if enforce_min_samples_by_stratum["protection"]:
                    protected_min_enforced = (
                        protected_sample_count < MIN_SAMPLES_PER_UNIT
                    )
                    protected_sample_count = max(
                        MIN_SAMPLES_PER_UNIT, protected_sample_count
                    )
                logger.info(
                    f"✓ Guideline table: {protected_sample_count} samples ({protected_plot_size_sqm} sqm plots)"
                )
            except ValueError:
                # Fallback to manual calculation
                sample_area_ha = protected_area_ha * 0.001  # 0.1%
                protected_sample_count = int(
                    sample_area_ha / protected_plot_area_hectares
                )
                if enforce_min_samples_by_stratum["protection"]:
                    protected_min_enforced = (
                        protected_sample_count < MIN_SAMPLES_PER_UNIT
                    )
                    protected_sample_count = max(
                        MIN_SAMPLES_PER_UNIT, protected_sample_count
                    )
                logger.info(
                    f"✓ Manual calc: {protected_sample_count} samples ({protected_plot_size_sqm} sqm plots)"
                )

            if protected_sample_count > 0 and zone_areas["protected_geometry"]:
                # Generate samples in protected zone only
                protected_wkt = zone_areas["protected_geometry"].wkt
                protected_buffered = apply_boundary_buffer(
                    protected_wkt, boundary_buffer_meters
                )
                protected_sampling_method = "systematic"

                # Try systematic grid with current buffer first
                effective_area_sqm = protected_area_ha * SQM_PER_HA
                systematic_success = False

                for iteration in range(5):
                    spacing = math.sqrt(
                        effective_area_sqm / float(protected_sample_count)
                    )
                    bounds = get_polygon_bounds(protected_buffered)
                    candidates = generate_systematic_grid(
                        bounds[0],
                        bounds[1],
                        bounds[2],
                        bounds[3],
                        int(spacing),
                        protected_buffered,
                        0.0,  # No additional buffer - already buffered
                    )

                    if len(candidates) >= protected_sample_count:
                        protected_samples = candidates[:protected_sample_count]
                        protected_spacing = spacing
                        systematic_success = True
                        logger.info(
                            f"  Generated {len(protected_samples)} protected samples (systematic)"
                        )
                        break
                    effective_area_sqm *= 0.9

                # Fallback 1: Try smaller buffer (15m)
                if not systematic_success and protected_sample_count > 0:
                    logger.warning(
                        f"  ⚠ Systematic failed with {boundary_buffer_meters}m buffer, trying 15m buffer..."
                    )
                    protected_buffered_15m = apply_boundary_buffer(protected_wkt, 15.0)
                    effective_area_sqm = protected_area_ha * SQM_PER_HA

                    for iteration in range(5):
                        spacing = math.sqrt(
                            effective_area_sqm / float(protected_sample_count)
                        )
                        bounds = get_polygon_bounds(protected_buffered_15m)
                        candidates = generate_systematic_grid(
                            bounds[0],
                            bounds[1],
                            bounds[2],
                            bounds[3],
                            int(spacing),
                            protected_buffered_15m,
                            0.0,
                        )

                        if len(candidates) >= protected_sample_count:
                            protected_samples = candidates[:protected_sample_count]
                            protected_spacing = spacing
                            systematic_success = True
                            logger.info(
                                f"  Generated {len(protected_samples)} protected samples (systematic, 15m buffer)"
                            )
                            break
                        effective_area_sqm *= 0.9

                # Fallback 2: Random sampling
                if not systematic_success and protected_sample_count > 0:
                    logger.warning(
                        f"  ⚠ Systematic failed for protected zone, falling back to random sampling..."
                    )
                    min_distance = int(
                        math.sqrt(effective_area_sqm / protected_sample_count)
                    )
                    protected_samples = generate_random_points(
                        protected_buffered,
                        protected_sample_count,
                        min_distance_meters=min_distance,
                        boundary_buffer_meters=0.0,  # Already buffered
                    )
                    if len(protected_samples) > 0:
                        protected_sampling_method = "random"
                        logger.info(
                            f"  Generated {len(protected_samples)} protected samples (random)"
                        )
                    else:
                        logger.warning(
                            "  ⚠ Failed to generate protected samples (random also failed)"
                        )

        # Combine samples from both zones
        block_points = productive_samples + protected_samples
        total_samples = len(block_points)

        if total_samples > 0 and response_plot_size_sqm is None:
            response_plot_size_sqm = block_plot_size_sqm

        summary_sampled_area_sqm += (
            len(productive_samples) * block_plot_size_sqm
            + len(protected_samples) * protected_plot_size_sqm
        )

        logger.info(
            f"\n✓ Total for {block_name}: {total_samples} samples "
            f"({len(productive_samples)} productive + {len(protected_samples)} protected)"
        )

        # NO POST-FILTERING NEEDED
        # Samples already generated in correct zones with private land excluded

        # Store points with block assignment and zone type
        for i, point in enumerate(block_points):
            all_points.append(point)
            # Determine zone type and sampling method for this sample
            if i < len(productive_samples):
                zone_type = "productive"
                sampling_method = productive_sampling_method
            else:
                zone_type = "protected"
                sampling_method = protected_sampling_method

            block_assignments.append(
                {
                    "point_index": len(all_points) - 1,
                    "block_number": block_number,
                    "block_name": block_name,
                    "zone_type": zone_type,
                    "sampling_method": sampling_method,
                }
            )

        # Calculate net accessible area (productive + protected, excluding private land)
        accessible_area_ha = productive_area_ha + protected_area_ha

        # Calculate overall actual intensity (weighted by plot sizes)
        total_sampled_area_ha = (
            len(productive_samples) * block_plot_area_hectares
            + len(protected_samples) * protected_plot_area_hectares
        )

        # Safe intensity calculation with NaN protection
        if accessible_area_ha > 0 and total_sampled_area_ha > 0:
            intensity_value = (total_sampled_area_ha / accessible_area_ha) * 100
            # Check for NaN/inf before converting to Decimal
            if math.isnan(intensity_value) or math.isinf(intensity_value):
                actual_intensity_pct = Decimal("0")
            else:
                actual_intensity_pct = Decimal(str(intensity_value))
        else:
            actual_intensity_pct = Decimal("0")

        # Determine block protection status for reporting
        # "Mixed" if both zones present, otherwise "Yes" or "No"
        if protected_area_ha > 0 and productive_area_ha > 0:
            is_protected_status = "Mixed"
        elif protected_area_ha > 0:
            is_protected_status = "Yes"
        else:
            is_protected_status = "No"

        # Calculate average grid spacing (weighted by sample count)
        if total_samples > 0:
            if len(productive_samples) > 0 and len(protected_samples) > 0:
                # Mixed - report productive spacing (dominant)
                avg_spacing = (
                    productive_spacing if productive_spacing else protected_spacing
                )
            elif len(productive_samples) > 0:
                avg_spacing = productive_spacing
            else:
                avg_spacing = protected_spacing
        else:
            avg_spacing = None

        # Safe accessible percentage calculation
        if block_area_ha > 0 and accessible_area_ha >= 0:
            accessible_pct_value = (accessible_area_ha / block_area_ha) * 100
            if math.isnan(accessible_pct_value) or math.isinf(accessible_pct_value):
                accessible_forest_percentage = Decimal("0")
            else:
                accessible_forest_percentage = Decimal(
                    str(round(accessible_pct_value, 2))
                )
        else:
            accessible_forest_percentage = Decimal("0")

        # Determine overall sampling method for this block
        # If either zone used random, report random for the block
        if protected_area_ha > 0:
            # Both zones exist
            if (
                productive_sampling_method == "random"
                or protected_sampling_method == "random"
            ):
                block_sampling_method = "random"
            else:
                block_sampling_method = "systematic"
        else:
            # Only productive zone
            block_sampling_method = productive_sampling_method

        # Store block info with detailed zone breakdown
        block_info_dict = {
            "block_number": block_number,
            "block_name": block_name,
            "block_area_hectares": Decimal(str(round(block_area_ha, 4))),
            "samples_generated": total_samples,
            "minimum_enforced": productive_min_enforced or protected_min_enforced,
            "actual_intensity_percent": actual_intensity_pct,
            "grid_spacing_meters": (
                Decimal(str(round(avg_spacing, 1))) if avg_spacing else None
            ),
            "stratum": stratum,
            "floor_intensity_pct": Decimal(str(floor_pct)),
            "plot_size_sqm": int(block_plot_size_sqm),
            "accessible_forest_area_ha": Decimal(str(round(accessible_area_ha, 4))),
            "accessible_forest_percentage": accessible_forest_percentage,
            "samples_from_guideline": productive_sample_count + protected_sample_count,
            "is_protected": is_protected_status,
            "sampling_method": block_sampling_method,
            "guideline_fallback_used": False,
            # Protected zone details
            "protected_area_ha": (
                Decimal(str(round(protected_area_ha, 4)))
                if protected_area_ha > 0
                else None
            ),
            "protected_samples_count": (
                len(protected_samples) if protected_area_ha > 0 else None
            ),
            "protected_sampling_method": (
                protected_sampling_method if protected_area_ha > 0 else None
            ),
            "protected_grid_spacing_meters": (
                Decimal(str(round(protected_spacing, 1)))
                if protected_spacing and protected_area_ha > 0
                else None
            ),
            "protected_intensity_percent": None,  # Calculate below if protected samples exist
            # Productive zone details
            "productive_area_ha": (
                Decimal(str(round(productive_area_ha, 4)))
                if productive_area_ha > 0
                else None
            ),
            "productive_samples_count": (
                len(productive_samples) if productive_area_ha > 0 else None
            ),
            "productive_sampling_method": (
                productive_sampling_method if productive_area_ha > 0 else None
            ),
        }

        # Calculate protected intensity if samples were generated
        if protected_area_ha > 0 and len(protected_samples) > 0:
            protected_sampled_area_ha = (
                len(protected_samples) * protected_plot_area_hectares
            )
            if protected_area_ha > 0:
                protected_intensity = (
                    protected_sampled_area_ha / protected_area_ha
                ) * 100
                block_info_dict["protected_intensity_percent"] = Decimal(
                    str(round(protected_intensity, 4))
                )

        blocks_info.append(BlockSamplingInfo(**block_info_dict))

        logger.info(f"{'='*60}\n")

    _refuse_if_every_unit_excluded(blocks_info)

    points = all_points
    logger.info(
        f"\n{'='*60}\n"
        f"SUMMARY: Generated {len(points)} total samples across {len(blocks)} blocks\n"
        f"{'='*60}\n"
    )

    if not points:
        raise ValueError(
            "NO_POINTS_GENERATED: नमूना बिन्दुहरू जनरेट भएनन्। सबै ब्लकहरू संरक्षित छन् र "
            "sample_protected_zone=False छ कि जाँच गर्नुहोस्, वा फिल्टरहरू धेरै प्रतिबन्धित छन् कि जाँच गर्नुहोस्।"
        )

    # Calculate total sampled area (weighted by per-block stratum plot sizes)
    total_sampled_area_hectares = Decimal(str(summary_sampled_area_sqm / SQM_PER_HA))

    # Safe percentage calculations with NaN protection
    if total_forest_area > 0:
        actual_intensity_val = len(points) / float(total_forest_area)
        sampling_pct_val = (
            summary_sampled_area_sqm / (float(total_forest_area) * SQM_PER_HA)
        ) * 100

        if math.isnan(actual_intensity_val) or math.isinf(actual_intensity_val):
            actual_intensity = Decimal("0")
        else:
            actual_intensity = Decimal(str(actual_intensity_val))

        if math.isnan(sampling_pct_val) or math.isinf(sampling_pct_val):
            sampling_percentage = Decimal("0")
        else:
            sampling_percentage = Decimal(str(sampling_pct_val))
    else:
        actual_intensity = Decimal("0")
        sampling_percentage = Decimal("0")

    if preview:
        # Rule F: computed layout only — no DB rows are written.
        preview_token = uuid4()
        preview_response = SamplingGenerateResponse(
            sampling_design_id=preview_token,
            calculation_id=calculation_id,
            sampling_type="systematic",
            total_points=len(points),
            total_blocks=len(blocks),
            forest_area_hectares=Decimal(str(round(total_forest_area, 4))),
            requested_intensity_percent=Decimal(str(productive_intensity)),
            actual_intensity_per_hectare=actual_intensity,
            plot_area_sqm=Decimal(
                str(round(response_plot_size_sqm or productive_plot_size_sqm, 2))
            ),  # Report productive plot size
            total_sampled_area_hectares=total_sampled_area_hectares,
            sampling_percentage=sampling_percentage,
            blocks_info=blocks_info,
        )
        return SamplingPreviewResult(
            response=preview_response,
            points_geojson=_build_preview_points_geojson(points, block_assignments),
            area_basis=area_basis_from_filter(filter_tree_cover),
        )

    # Create MultiPoint geometry WKT
    points_wkt = (
        "MULTIPOINT(" + ", ".join([f"{lon} {lat}" for lon, lat in points]) + ")"
    )

    # Calculate plot dimensions for database record
    # Use the productive plot size as the "default" for the design record
    if plot_shape == "circular":
        plot_radius_meters = math.sqrt(plot_size_sqm / math.pi)
        plot_side_meters = None
    else:  # square
        plot_radius_meters = None
        plot_side_meters = math.sqrt(plot_size_sqm)

    # Create sampling design record
    sampling_design = SamplingDesign(
        calculation_id=calculation_id,
        sampling_type="systematic",  # Guideline-2061 uses systematic only
        intensity_per_hectare=Decimal(str(len(points) / float(total_forest_area))),
        grid_spacing_meters=None,
        min_distance_meters=None,
        plot_shape=plot_shape,
        plot_radius_meters=(
            Decimal(str(plot_radius_meters)) if plot_radius_meters else None
        ),
        plot_length_meters=Decimal(str(plot_side_meters)) if plot_side_meters else None,
        plot_width_meters=Decimal(str(plot_side_meters)) if plot_side_meters else None,
        total_points=len(points),
        notes=notes,
    )

    db.add(sampling_design)
    db.flush()  # Get ID

    # Save guideline-specific parameters
    import json

    guideline_parameters = {
        "sampling_method": "guideline_2061",
        "productive_intensity": productive_intensity,
        "sample_protected_zone": sample_protected_zone,
        "plot_size_sqm": plot_size_sqm,
        "enforce_min_samples_production": enforce_min_samples_production,
        "enforce_min_samples_conservation": enforce_min_samples_conservation,
        "enforce_min_samples_protection": enforce_min_samples_protection,
        "boundary_buffer_meters": boundary_buffer_meters,
        "filter_tree_cover": filter_tree_cover,
        "filter_slope": filter_slope,
        "max_slope_degrees": max_slope_degrees,
        "area_basis": area_basis_from_filter(filter_tree_cover),
    }

    update_params_query = text(
        """
        UPDATE public.sampling_designs
        SET default_parameters = CAST(:params AS jsonb)
        WHERE id = :design_id
    """
    )
    db.execute(
        update_params_query,
        {
            "params": json.dumps(guideline_parameters),
            "design_id": str(sampling_design.id),
        },
    )

    # Update geometry using PostGIS
    update_geom_query = text(
        """
        UPDATE public.sampling_designs
        SET points_geometry = ST_GeomFromText(:points_wkt, 4326)
        WHERE id = :design_id
    """
    )
    db.execute(
        update_geom_query,
        {"points_wkt": points_wkt, "design_id": str(sampling_design.id)},
    )

    # Save block assignments
    update_assignments_query = text(
        """
        UPDATE public.sampling_designs
        SET points_block_assignment = CAST(:assignments AS jsonb)
        WHERE id = :design_id
    """
    )
    db.execute(
        update_assignments_query,
        {
            "assignments": json.dumps(block_assignments),
            "design_id": str(sampling_design.id),
        },
    )

    db.commit()

    response = SamplingGenerateResponse(
        sampling_design_id=sampling_design.id,
        calculation_id=calculation_id,
        sampling_type="systematic",
        total_points=len(points),
        total_blocks=len(blocks),
        forest_area_hectares=Decimal(str(round(total_forest_area, 4))),
        requested_intensity_percent=Decimal(str(productive_intensity)),
        actual_intensity_per_hectare=actual_intensity,
        plot_area_sqm=Decimal(
            str(round(response_plot_size_sqm or productive_plot_size_sqm, 2))
        ),  # Report productive plot size
        total_sampled_area_hectares=total_sampled_area_hectares,
        sampling_percentage=sampling_percentage,
        blocks_info=blocks_info,
    )

    # Persist computed data so it loads instantly on page revisit
    # H8.2 / S2-63: derived output, not somebody's concurrent edit, so the
    # version is declared rather than bumped -- bumping would give a client
    # holding the current version a 409 because someone else merely read or
    # regenerated this. See optimistic_lock.record_derived_write.
    optimistic_lock.record_derived_write(
        db,
        "sampling",
        sampling_design.id,
        "sampling generation result",
    )
    sampling_design.result_data = response.model_dump(mode="json")
    db.add(sampling_design)

    return response


# business: spatial intersection assigns each sampling point to its containing block for per-block reporting
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
    calc_query = text(
        """
        SELECT
            ST_GeometryType(boundary_geom) as geom_type,
            ST_NumGeometries(boundary_geom) as num_blocks,
            result_data->'blocks' as blocks_data
        FROM public.calculations
        WHERE id = :calc_id
    """
    )
    result = db.execute(calc_query, {"calc_id": str(calculation_id)}).first()

    if not result:
        return

    is_multipolygon = result.geom_type == "ST_MultiPolygon"
    blocks_data = result.blocks_data if result.blocks_data else []

    # Extract block names from result_data
    block_names_map = {}
    if blocks_data:
        for block in blocks_data:
            block_index = block.get("block_index")
            block_name = block.get("block_name")
            if block_index is not None and block_name:
                # ST_Dump uses 1-based indexing, but block_index is 0-based
                block_names_map[block_index + 1] = block_name

    if not is_multipolygon:
        # Single polygon - get block name from result_data or use default
        block_name = block_names_map.get(1, "Block 1")

        # Create simple assignment array using SQL
        update_query = text(
            """
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
        """
        )
        result = db.execute(
            update_query, {"design_id": str(design_id), "block_name": block_name}
        ).first()
        num_points = result.num_points if result else 0
        logger.info(f"Assigned all {num_points} sampling points to '{block_name}'")
        return

    # Multi-polygon - use spatial intersection in a single UPDATE query
    # Use JSONB parameter instead of dynamic CASE expression to avoid f-string SQL
    import json

    block_names_json = (
        json.dumps({str(k): v for k, v in block_names_map.items()})
        if block_names_map
        else "{}"
    )

    update_query = text(
        """
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
                        'block_name', COALESCE(
                            (:block_names::jsonb)->>(pol.block_number::text),
                            'Block ' || pol.block_number
                        )
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
    """
    )

    _sd_exec_params = {
        "calc_id": str(calculation_id),
        "design_id": str(design_id),
        "block_names": block_names_json,
    }
    db.execute(update_query, _sd_exec_params)
    logger.info(
        f"Assigned sampling points to blocks using spatial intersection with user-defined names"
    )
