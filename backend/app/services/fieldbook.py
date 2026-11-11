"""
Fieldbook service for boundary vertex extraction and interpolation
"""
# business: CFMG — fieldbook point generation along transects
# constraint: azimuth 0-360°, distance in meters
# why: UTM projection for accurate distance/azimuth calculations
import math
from typing import List, Tuple, Optional, Dict, Any
from decimal import Decimal
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import text
from shapely import wkt
from shapely.geometry import Polygon, MultiPolygon
import logging

from app.models.calculation import Calculation
from app.models.fieldbook import Fieldbook
from app.models.forest_block import ForestBlock
from app.core.sub_area_kinds import is_strip_category, real_sub_areas
from app.models.forest_sub_area import ForestSubArea
from app.schemas.fieldbook import FieldbookGenerateResponse

logger = logging.getLogger(__name__)

# Dedup coordinate rounding (plan D4) -- ~11cm tolerance. This app's
# split/divide tools derive adjacent polygons from ST_Intersection/
# ST_Difference on the same source geometry, so shared edges are normally
# bit-identical; this absorbs float-precision drift without merging
# legitimately close (>= the interpolation distance apart, by design) points.
_DEDUP_ROUND_DP = 6


def calculate_azimuth(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """
    Calculate azimuth (bearing) from point 1 to point 2 in degrees.

    Args:
        lon1, lat1: Coordinates of first point (WGS84)
        lon2, lat2: Coordinates of second point (WGS84)

    Returns:
        Azimuth in degrees (0-360, where 0 is North)
    """
    # Convert to radians
    lon1_rad = math.radians(lon1)
    lat1_rad = math.radians(lat1)
    lon2_rad = math.radians(lon2)
    lat2_rad = math.radians(lat2)

    # Calculate difference
    dlon = lon2_rad - lon1_rad

    # Calculate azimuth
    x = math.sin(dlon) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - \
        math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)

    azimuth_rad = math.atan2(x, y)
    azimuth_deg = math.degrees(azimuth_rad)

    # Normalize to 0-360
    azimuth_deg = (azimuth_deg + 360) % 360

    return round(azimuth_deg, 2)


def calculate_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """
    Calculate distance between two points using Haversine formula.

    Args:
        lon1, lat1: Coordinates of first point (WGS84)
        lon2, lat2: Coordinates of second point (WGS84)

    Returns:
        Distance in meters
    """
    # Earth radius in meters
    R = 6371000.0

    # Convert to radians
    lon1_rad = math.radians(lon1)
    lat1_rad = math.radians(lat1)
    lon2_rad = math.radians(lon2)
    lat2_rad = math.radians(lat2)

    # Differences
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    # Haversine formula
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))

    distance = R * c
    return round(distance, 2)


def interpolate_point(lon1: float, lat1: float, lon2: float, lat2: float, fraction: float) -> Tuple[float, float]:
    """
    Interpolate a point along a great circle path between two points.

    Args:
        lon1, lat1: Start point (WGS84)
        lon2, lat2: End point (WGS84)
        fraction: Fraction of distance (0.0 to 1.0)

    Returns:
        Tuple of (longitude, latitude) of interpolated point
    """
    # Convert to radians
    lon1_rad = math.radians(lon1)
    lat1_rad = math.radians(lat1)
    lon2_rad = math.radians(lon2)
    lat2_rad = math.radians(lat2)

    # Calculate angular distance
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    d = 2 * math.asin(math.sqrt(a))

    # Interpolate
    a_val = math.sin((1-fraction) * d) / math.sin(d)
    b_val = math.sin(fraction * d) / math.sin(d)

    x = a_val * math.cos(lat1_rad) * math.cos(lon1_rad) + b_val * math.cos(lat2_rad) * math.cos(lon2_rad)
    y = a_val * math.cos(lat1_rad) * math.sin(lon1_rad) + b_val * math.cos(lat2_rad) * math.sin(lon2_rad)
    z = a_val * math.sin(lat1_rad) + b_val * math.sin(lat2_rad)

    lat_interp = math.atan2(z, math.sqrt(x**2 + y**2))
    lon_interp = math.atan2(y, x)

    return (math.degrees(lon_interp), math.degrees(lat_interp))


def convert_to_utm(lon: float, lat: float) -> Tuple[float, float, int]:
    """
    Convert WGS84 coordinates to UTM.

    Nepal uses UTM zones 44N and 45N.
    Zone 44N: 78°E to 84°E
    Zone 45N: 84°E to 90°E

    Args:
        lon, lat: WGS84 coordinates

    Returns:
        Tuple of (easting, northing, utm_zone)
    """
    # Determine UTM zone for Nepal
    if lon < 84.0:
        utm_zone = 44
        srid = 32644
    else:
        utm_zone = 45
        srid = 32645

    return (0.0, 0.0, utm_zone)  # Placeholder - will use PostGIS for actual conversion


def _polygon_rings(geom) -> List[List[Tuple[float, float]]]:
    """Exterior-ring vertices for a shapely `Polygon` or `MultiPolygon`, one
    ring per part -- NEVER concatenated into a single fake ring (plan D11).

    A multi-part unit (only reachable via the legacy `result_data` fallback --
    `ForestBlock`/`ForestSubArea` DB rows are guarded single-`Polygon`-only,
    see `utils/single_part_geometry.py::ensure_single_polygon`) used to have
    every part's coordinates flattened into one list and walked as one ring,
    fabricating a bogus edge across the gap between disconnected parts. Each
    part now gets its own independent closed ring.

    Interior rings (holes) are not walked (plan D12) -- a hole tied to a
    tracked sub-area is already covered by that sub-area's own ring plus the
    dedup pass in `generate_fieldbook_points`; an untracked hole is a
    pre-existing, non-regressive gap.
    """
    rings: List[List[Tuple[float, float]]] = []
    if isinstance(geom, Polygon):
        coords = list(geom.exterior.coords)[:-1]
        if len(coords) >= 3:
            rings.append([(float(c[0]), float(c[1])) for c in coords])
    elif isinstance(geom, MultiPolygon):
        for part in geom.geoms:
            coords = list(part.exterior.coords)[:-1]
            if len(coords) >= 3:
                rings.append([(float(c[0]), float(c[1])) for c in coords])
    return rings


def extract_subarea_boundaries(
    db: Session, calculation: Calculation
) -> List[Tuple[List[List[Tuple[float, float]]], str, bool, str]]:
    """
    Extract sub-area boundaries -- DB `forest_sub_areas` rows first (kept for
    forward-compatibility), else `calculation.result_data['sub_areas']`.

    Unlike blocks/compartments, sub-areas have **no DB-authoritative write
    path** in this app: `POST .../sub-areas` (`add_sub_area` in
    `api/forests.py`, the endpoint the Map Workspace actually calls) reads
    and writes `result_data['sub_areas']` exclusively -- `ForestSubArea(...)`
    is never constructed anywhere in the codebase, so `forest_sub_areas` is
    effectively always empty. `result_data['sub_areas']` IS the live,
    continuously-updated source (its own delete route keeps it in sync,
    unconditionally, on every deletion), so it must always be consulted here
    -- gating it behind a `forest_blocks`-based "workspace_managed" flag (an
    earlier version of this function did, mirroring the blocks precedent in
    `sampling.py::extract_blocks_from_calculation`) was wrong: almost every
    real forest has workspace-managed blocks, so that gate silently dropped
    every sub-area, always. See `fieldbook_implementation_plan.md` for the
    incident writeup.

    Args:
        db: Database session
        calculation: Calculation object (for its id + result_data)

    Returns:
        List of tuples: (rings, sub_area_name, is_excluded, category)
        - rings: one or more closed vertex rings (>1 only for a legacy
          MultiPolygon sub-area, plan D11)
        - sub_area_name: name of the sub-area
        - is_excluded: True if this is private/excluded land
        - category: the sub-area's category (e.g. "religious", "plantation")
    """
    from geoalchemy2.shape import to_shape

    calculation_id = calculation.id

    db_subareas = db.query(ForestSubArea).filter(
        ForestSubArea.calculation_id == calculation_id
    ).all()

    if db_subareas:
        results = []
        for sa in db_subareas:
            if is_strip_category(sa.category):
                continue
            geom = to_shape(sa.geometry)
            rings = _polygon_rings(geom)
            if not rings:
                logger.warning(f"Sub-area '{sa.name}' has no usable rings, skipping")
                continue
            results.append((rings, sa.name, bool(sa.is_excluded), sa.category or ''))
        logger.info(
            f"Extracted {len(results)} sub-area boundaries from forest_sub_areas "
            f"DB for calculation {calculation_id}"
        )
        return results

    if not calculation.result_data or 'sub_areas' not in calculation.result_data:
        logger.info("No sub-areas found in calculation result_data")
        return []

    # the zones only: a fire line is derived FROM the field book's lines, so its outline must never go back into them
    sub_areas = real_sub_areas(calculation.result_data['sub_areas'])
    logger.info(f"Extracting boundaries for {len(sub_areas)} sub-areas from result_data")

    from shapely.geometry import shape

    results = []
    for sub_area in sub_areas:
        try:
            name = sub_area.get('name', 'Unknown Sub-area')
            category = sub_area.get('category', '')
            geometry_data = sub_area.get('geometry')

            if not geometry_data:
                logger.warning(f"Sub-area '{name}' has no geometry, skipping")
                continue

            geom = shape(geometry_data)
            rings = _polygon_rings(geom)
            if not rings:
                logger.warning(f"Sub-area '{name}' has no usable rings, skipping")
                continue

            # add_sub_area (api/forests.py) stamps both isExcluded/is_excluded
            # from `category == "private_land"` -- read the real flag when
            # present, fall back to that same rule for an older snapshot.
            is_excluded = bool(
                sub_area.get('is_excluded', sub_area.get('isExcluded', (category or '').lower() == 'private_land'))
            )
            results.append((rings, name, is_excluded, category or ''))
            logger.info(f"  [OK] Extracted {sum(len(r) for r in rings)} vertices from '{name}' (category={category}, excluded={is_excluded})")

        except Exception as e:
            logger.error(f"Error extracting sub-area boundary: {str(e)}")
            continue

    return results


def generate_fieldbook_points(
    db: Session,
    calculation_id: UUID,
    interpolation_distance: float = 50.0,
    extract_elevation: bool = True,
    calculate_reference: bool = False
) -> FieldbookGenerateResponse:
    """
    Generate the field book: the forest's OUTER boundary first, then every internal boundary.

    1. Units: the leaf blocks / compartments (``sampling.extract_blocks_from_calculation``); sub-areas via
       ``extract_subarea_boundaries``; the outer ring from ``calculation.boundary_geom``.
    2. ``fieldbook_sequence.build_sequence`` does the geometry: outer ring clockwise from the north-west-most
       vertex (``O1``, ``O2``, ...), then each internal edge ONCE in a walkable order (``I1``, ``I2``, ...).
       Every point records the units it separates (``adjacent_units``), whether it is a junction, and a
       remark such as ``outer: ब्लक १, ब्लक २`` or ``internal (junction of 3): A, B, C``.
    3. Save, then fill UTM and elevation in bulk.

    Note: Topographic features (ridges/rivers) are calculated during EXPORT, not generation.
    See export_fieldbook_csv() and export_fieldbook_excel() in services/export.py

    Args:
        db: Database session
        calculation_id: ID of calculation
        interpolation_distance: Distance between interpolated points (meters); 0 = vertices only
        extract_elevation: Whether to extract elevation from DEM
        calculate_reference: DEPRECATED - References now calculated during export automatically

    Returns:
        FieldbookGenerateResponse with summary statistics
    """
    from geoalchemy2.shape import to_shape
    from shapely.geometry import MultiPolygon as _MultiPolygon, Polygon as _Polygon

    from app.services.fieldbook_sequence import SubAreaIn, UnitIn, build_sequence
    from app.services.sampling import extract_blocks_from_calculation

    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise ValueError(f"Calculation {calculation_id} not found")

    # Clear existing fieldbook points
    db.query(Fieldbook).filter(Fieldbook.calculation_id == calculation_id).delete()
    db.commit()

    raw_units = extract_blocks_from_calculation(db, calculation_id)
    if not raw_units:
        raise ValueError("No blocks, compartments, or boundary geometry found for this calculation")

    # unit_type for response transparency (plan P4): the forest's stream (FS-1a.13 - the units module, not a
    # direct read of is_compartment).
    from app.services.forest_units.mode import forest_stream
    from app.services.forest_units.model import Stream

    unit_type = (
        "compartment" if forest_stream(db, calculation_id) is Stream.COMPARTMENT else "block"
    )
    unit_count = len(raw_units)
    logger.info(f"Sourced {unit_count} {unit_type}(s) for calculation {calculation_id}")

    units = []
    for unit_number, geom_wkt, unit_name, _area_ha in raw_units:
        try:
            units.append(UnitIn(unit_number, unit_name, wkt.loads(geom_wkt)))
        except Exception as e:
            logger.warning(f"Unit '{unit_name}' has unparsable geometry, skipping: {e}")

    subareas = []
    for rings, sub_area_name, is_excluded, sub_area_category in extract_subarea_boundaries(db, calculation):
        polys = [_Polygon(r) for r in rings if len(r) >= 3]
        if not polys:
            continue
        geom = polys[0] if len(polys) == 1 else _MultiPolygon(polys)
        subareas.append(SubAreaIn(sub_area_name, geom, bool(is_excluded), sub_area_category or ""))

    forest = to_shape(calculation.boundary_geom) if calculation.boundary_geom is not None else None

    sequence = build_sequence(forest, units, subareas, spacing=interpolation_distance)
    fieldbook_points = sequence.points
    total_perimeter = sequence.perimeter_m

    for p in fieldbook_points:
        _, _, p['utm_zone'] = convert_to_utm(p['x'], p['y'])

    vertex_count = sum(1 for p in fieldbook_points if p['point_type'] == 'vertex')
    interpolated_count = sum(1 for p in fieldbook_points if p['point_type'] == 'interpolated')
    outer_count = sum(1 for p in fieldbook_points if p['boundary_class'] == 'outer')
    junction_count = sum(1 for p in fieldbook_points if p['is_junction'])

    logger.info(
        f"Generated {len(fieldbook_points)} fieldbook points "
        f"({outer_count} outer + {len(fieldbook_points) - outer_count} internal; "
        f"{vertex_count} vertices + {interpolated_count} interpolated; {junction_count} junctions)"
    )

    def _dec(v):
        return Decimal(str(v)) if v is not None else None

    # Bulk insert to database
    if fieldbook_points:
        fieldbook_objects = []
        for point in fieldbook_points:
            fieldbook_objects.append(Fieldbook(
                calculation_id=calculation_id,
                point_number=point['point_number'],
                point_label=point['point_label'],
                point_type=point['point_type'],
                boundary_class=point['boundary_class'],
                junction_degree=point['junction_degree'],
                is_junction=point['is_junction'],
                adjacent_units=point['adjacent_units'],
                next_point_label=point['next_point_label'],
                line_id=point['line_id'],
                lines=point['lines'],
                longitude=Decimal(str(point['x'])),
                latitude=Decimal(str(point['y'])),
                azimuth_to_next=_dec(point['azimuth_to_next']),
                distance_to_next=_dec(point['distance_to_next']),
                utm_zone=point['utm_zone'],
                block_number=point.get('block_number'),
                block_name=point.get('block_name'),
                sub_area_name=point.get('sub_area_name'),
                is_excluded=point.get('is_excluded'),
                sub_area_category=point.get('sub_area_category'),
                remarks=point.get('remarks'),
            ))

        logger.info(f"[SAVE] Saving {len(fieldbook_objects)} fieldbook points to database...")
        db.bulk_save_objects(fieldbook_objects)
        db.flush()
        db.commit()
        logger.info(f"[OK] Database commit successful - {len(fieldbook_objects)} points saved")

        # Update with PostGIS-calculated UTM and elevation
        if extract_elevation:
            update_utm_and_elevation(db, calculation_id, calculate_reference=calculate_reference)

        logger.info("Fieldbook generation complete.")

    # Calculate summary statistics
    elevation_stats = get_elevation_stats(db, calculation_id) if extract_elevation else None

    return FieldbookGenerateResponse(
        calculation_id=calculation_id,
        total_vertices=vertex_count,
        interpolated_points=interpolated_count,
        total_points=len(fieldbook_points),
        total_perimeter_meters=Decimal(str(round(total_perimeter, 2))),
        avg_elevation_meters=elevation_stats['avg'] if elevation_stats else None,
        min_elevation_meters=elevation_stats['min'] if elevation_stats else None,
        max_elevation_meters=elevation_stats['max'] if elevation_stats else None,
        unit_type=unit_type,
        unit_count=unit_count,
        outer_points=outer_count,
        internal_points=len(fieldbook_points) - outer_count,
        junction_points=junction_count,
    )


def update_utm_and_elevation(db: Session, calculation_id: UUID, calculate_reference: bool = False):
    """
    Update fieldbook points with UTM coordinates and elevation using PostGIS.

    Note: Topographic features are now calculated during EXPORT using optimized algorithm.
    The calculate_reference parameter is deprecated and ignored.

    Args:
        db: Database session
        calculation_id: Calculation ID
        calculate_reference: DEPRECATED - Ignored (features calculated during export)
    """
    # Update UTM coordinates using PostGIS
    utm_update_query = text("""
        UPDATE public.fieldbook
        SET
            point_geometry = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326),
            easting_utm = CASE
                WHEN longitude < 84.0 THEN ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(longitude, latitude), 4326), 32644))
                ELSE ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(longitude, latitude), 4326), 32645))
            END,
            northing_utm = CASE
                WHEN longitude < 84.0 THEN ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(longitude, latitude), 4326), 32644))
                ELSE ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(longitude, latitude), 4326), 32645))
            END,
            utm_zone = CASE
                WHEN longitude < 84.0 THEN 44
                ELSE 45
            END
        WHERE calculation_id = :calc_id
    """)
    db.execute(utm_update_query, {"calc_id": str(calculation_id)})

    # Extract elevation from DEM
    elevation_update_query = text("""
        UPDATE public.fieldbook fb
        SET elevation = (
            SELECT ST_Value(rast, fb.point_geometry)
            FROM rasters.dem
            WHERE ST_Intersects(rast, fb.point_geometry)
            LIMIT 1
        )
        WHERE fb.calculation_id = :calc_id
        AND fb.point_geometry IS NOT NULL
    """)
    db.execute(elevation_update_query, {"calc_id": str(calculation_id)})

    # Reference calculation is SKIPPED during generation for performance
    # Instead, topographic features (ridges/rivers) are calculated during EXPORT
    # using the optimized pre-clipping algorithm (20-100x faster!)
    # See export_fieldbook_csv() and export_fieldbook_excel() in services/export.py
    if calculate_reference:
        logger.info(f"Note: Reference calculation during generation is deprecated. "
                   f"Topographic features (ridges/rivers) are now calculated automatically "
                   f"during export using the optimized algorithm (much faster!).")

    db.commit()

    logger.info(f"Updated UTM coordinates and elevation for fieldbook {calculation_id}. "
               f"Topographic features will be calculated during export (optimized algorithm).")


def get_elevation_stats(db: Session, calculation_id: UUID) -> Optional[dict]:
    """
    Get elevation statistics for fieldbook points.

    Args:
        db: Database session
        calculation_id: Calculation ID

    Returns:
        Dict with min, max, avg elevation
    """
    stats_query = text("""
        SELECT
            MIN(elevation) as min_elevation,
            MAX(elevation) as max_elevation,
            AVG(elevation) as avg_elevation
        FROM public.fieldbook
        WHERE calculation_id = :calc_id
        AND elevation IS NOT NULL
    """)

    result = db.execute(stats_query, {"calc_id": str(calculation_id)}).first()

    if result and result.avg_elevation:
        return {
            'min': Decimal(str(round(float(result.min_elevation), 2))),
            'max': Decimal(str(round(float(result.max_elevation), 2))),
            'avg': Decimal(str(round(float(result.avg_elevation), 2))),
        }

    return None
