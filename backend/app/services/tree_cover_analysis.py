"""
Tree cover analysis functions for accessible forest area calculation and sampling.
# constraint: Hansen Global Forest Change v1.11 at 30m resolution — source for tree cover layers
# business: CFMG — tree cover threshold 30% per global definition for forest/non-forest classification
# NOTE: per-pixel classification — each pixel = 0.09 ha (30m × 30m)

Uses ESA WorldCover raster data to identify tree-covered areas.
Calculates slope from DEM raster using PostGIS ST_Slope() function.
"""

import logging
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.constants import SQM_PER_HA

logger = logging.getLogger(__name__)


def calculate_accessible_forest_area(
    db: Session,
    geometry_wkt: str,
    filter_tree_cover: bool = True,
    filter_slope: bool = False,
    max_slope_degrees: float = 45.0
) -> dict:
    """
    Calculate accessible forest area with flexible filtering.

    Uses:
        - ESA WorldCover for tree cover (pixel value = 10)
        - DEM to calculate slope on-the-fly using ST_Slope()

    Args:
        db: Database session
        geometry_wkt: WKT string of boundary polygon
        filter_tree_cover: If True, only count tree cover pixels (ESA = 10)
        filter_slope: If True, exclude steep slopes
        max_slope_degrees: Maximum slope threshold if filtering (default 45°)

    Returns:
        Dictionary with:
            - total_boundary_area_ha: Total boundary area
            - accessible_forest_area_ha: Tree cover + slope OK (effective sampling area)
            - inaccessible_steep_forest_ha: Tree cover but too steep
            - non_forest_area_ha: Non-forested areas
            - Percentages and pixel counts
    """
    try:
        if filter_tree_cover and filter_slope:
            # Full filtering: tree cover (ESA = 10) + slope ≤ threshold (from DEM)
            logger.info(
                f"Calculating accessible forest area: "
                f"tree cover + slope ≤{max_slope_degrees}°"
            )

            query = text(f"""
                WITH boundary AS (
                    SELECT ST_GeomFromText(:wkt, 4326) as geom
                ),
                -- Step 1: Clip ESA WorldCover raster to boundary
                clipped_rasters AS (
                    SELECT ST_Clip(rast, b.geom, 0.0, true) as clipped_rast
                    FROM rasters.esa_world_cover, boundary b
                    WHERE ST_Intersects(rast, b.geom)
                ),
                -- Step 2: Get pixel values and counts
                esa_pixels AS (
                    SELECT value, count
                    FROM (
                        SELECT (ST_ValueCount(clipped_rast, 1, true)).*
                        FROM clipped_rasters
                        WHERE clipped_rast IS NOT NULL
                    ) vc
                    WHERE value > 0
                ),
                -- Step 3: Extract tree pixel coordinates from original raster
                tree_pixel_coords AS (
                    SELECT
                        ST_X(ST_Centroid(geom)) as lon,
                        ST_Y(ST_Centroid(geom)) as lat,
                        geom
                    FROM (
                        SELECT (ST_PixelAsPolygons(
                            ST_Clip(rast, b.geom, 0.0, true), 1
                        )).*
                        FROM rasters.esa_world_cover, boundary b
                        WHERE ST_Intersects(rast, b.geom)
                    ) pixels
                    WHERE val = 10 AND ST_Within(ST_Centroid(geom), (SELECT geom FROM boundary))
                ),
                -- Step 4: Calculate slope for tree pixels
                tree_with_slope AS (
                    SELECT
                        t.geom,
                        ST_Value(
                            ST_Slope(d.rast, 1, '32BF'),
                            ST_Centroid(t.geom)
                        ) as slope_degrees
                    FROM tree_pixel_coords t
                    CROSS JOIN LATERAL (
                        SELECT rast
                        FROM rasters.dem
                        WHERE ST_Intersects(rast, t.geom)
                        LIMIT 1
                    ) d
                )
                SELECT
                    -- Accessible forest (tree + slope OK)
                    COUNT(*) FILTER (WHERE slope_degrees IS NOT NULL AND slope_degrees <= :max_slope) as accessible_pixels,
                    -- Steep forest (tree + too steep)
                    COUNT(*) FILTER (WHERE slope_degrees IS NOT NULL AND slope_degrees > :max_slope) as steep_pixels,
                    -- Total tree pixels
                    COUNT(*) as total_tree_pixels,
                    -- Non-forest pixels
                    COALESCE((SELECT SUM(count) FROM esa_pixels WHERE value != 10), 0) as non_forest_pixels,

                    -- Convert to hectares (10m x 10m = 100 m²)
                    COUNT(*) FILTER (WHERE slope_degrees IS NOT NULL AND slope_degrees <= :max_slope) * 100.0 / {SQM_PER_HA} as accessible_ha,
                    COUNT(*) FILTER (WHERE slope_degrees IS NOT NULL AND slope_degrees > :max_slope) * 100.0 / {SQM_PER_HA} as steep_ha,
                    COUNT(*) * 100.0 / {SQM_PER_HA} as tree_cover_ha,
                    COALESCE((SELECT SUM(count) FROM esa_pixels WHERE value != 10), 0) * 100.0 / {SQM_PER_HA} as non_forest_ha
                FROM tree_with_slope
            """)

            result = db.execute(query, {
                "wkt": geometry_wkt,
                "max_slope": max_slope_degrees
            }).first()

            if not result:
                logger.warning("No data found for geometry")
                return {
                    "total_boundary_area_ha": 0.0,
                    "accessible_forest_area_ha": 0.0,
                    "inaccessible_steep_forest_ha": 0.0,
                    "non_forest_area_ha": 0.0
                }

            total_area_ha = (
                (result.accessible_ha or 0) +
                (result.steep_ha or 0) +
                (result.non_forest_ha or 0)
            )

            accessible_pct = (result.accessible_ha / total_area_ha * 100) if total_area_ha > 0 else 0.0
            steep_pct = (result.steep_ha / total_area_ha * 100) if total_area_ha > 0 else 0.0
            non_forest_pct = (result.non_forest_ha / total_area_ha * 100) if total_area_ha > 0 else 0.0
            tree_cover_pct = (result.tree_cover_ha / total_area_ha * 100) if total_area_ha > 0 else 0.0

            return {
                "total_boundary_area_ha": round(total_area_ha, 4),
                "accessible_forest_area_ha": round(result.accessible_ha or 0, 4),
                "accessible_forest_percentage": round(accessible_pct, 2),
                "inaccessible_steep_forest_ha": round(result.steep_ha or 0, 4),
                "inaccessible_steep_percentage": round(steep_pct, 2),
                "non_forest_area_ha": round(result.non_forest_ha or 0, 4),
                "non_forest_percentage": round(non_forest_pct, 2),
                "total_tree_cover_ha": round(result.tree_cover_ha or 0, 4),
                "tree_cover_percentage": round(tree_cover_pct, 2),
                "accessible_pixels": result.accessible_pixels or 0,
                "steep_pixels": result.steep_pixels or 0,
                "total_tree_pixels": result.total_tree_pixels or 0,
                "non_forest_pixels": result.non_forest_pixels or 0,
                "filter_tree_cover": True,
                "filter_slope": True,
                "max_slope_degrees": max_slope_degrees
            }

        elif filter_tree_cover and not filter_slope:
            # Tree cover only, no slope filtering
            logger.info("Calculating forest area: tree cover only (no slope filter)")

            # NON-FOREST SUBTRACTION approach: the authoritative area comes from the
            # geometry (UTM), and the non-forest pixel count is subtracted from it.
            # Rationale: in forest units tree cover is the MAJORITY class, so edge
            # pixels counted in full (10m × 10m) over-estimate tree area noticeably;
            # non-forest is the small minority class, so its raw pixel area is a
            # stable measurement and the subtraction can never exceed the geometry.
            query = text(f"""
                WITH boundary AS (
                    SELECT ST_GeomFromText(:wkt, 4326) as geom
                ),
                boundary_area AS (
                    SELECT
                        ST_Area(ST_Transform(
                            geom,
                            CASE
                                WHEN ST_X(ST_Centroid(geom)) < 84.0 THEN 32644
                                ELSE 32645
                            END
                        )) / {SQM_PER_HA} as area_ha
                    FROM boundary
                ),
                clipped_rasters AS (
                    SELECT ST_Clip(rast, b.geom, 0.0, true) as clipped_rast
                    FROM rasters.esa_world_cover, boundary b
                    WHERE ST_Intersects(rast, b.geom)
                ),
                pixel_counts AS (
                    SELECT (ST_ValueCount(clipped_rast, 1, true)).*
                    FROM clipped_rasters
                    WHERE clipped_rast IS NOT NULL
                )
                SELECT
                    (SELECT area_ha FROM boundary_area) as total_boundary_area_ha,
                    SUM(count) FILTER (WHERE value = 10) as tree_pixels,
                    SUM(count) FILTER (WHERE value > 0 AND value != 10) as non_forest_pixels,
                    SUM(count) FILTER (WHERE value > 0) as total_pixels
                FROM pixel_counts
            """)

            result = db.execute(query, {"wkt": geometry_wkt}).first()

            if not result:
                return {
                    "total_boundary_area_ha": 0.0,
                    "accessible_forest_area_ha": 0.0,
                    "non_forest_area_ha": 0.0
                }

            # A fully-treed unit has NO non-forest pixels → SQL returns NULL for that
            # aggregate; coerce to 0 BEFORE any math or a None/Decimal TypeError
            # crashes the whole block (recorded as 0 accessible).
            total_area_ha = float(result.total_boundary_area_ha or 0)
            tree_pixels = int(result.tree_pixels or 0)
            non_forest_pixels = int(result.non_forest_pixels or 0)
            total_pixels = int(result.total_pixels or 0)

            non_forest_ha = non_forest_pixels * 100.0 / SQM_PER_HA
            non_forest_ha = min(non_forest_ha, total_area_ha)
            tree_ha = total_area_ha - non_forest_ha
            tree_pct = (tree_ha / total_area_ha * 100) if total_area_ha > 0 else 0.0
            non_forest_pct = (non_forest_ha / total_area_ha * 100) if total_area_ha > 0 else 0.0

            return {
                "total_boundary_area_ha": round(total_area_ha, 4),
                "accessible_forest_area_ha": round(tree_ha, 4),
                "accessible_forest_percentage": round(tree_pct, 2),
                "non_forest_area_ha": round(non_forest_ha, 4),
                "non_forest_percentage": round(non_forest_pct, 2),
                "total_tree_cover_ha": round(tree_ha, 4),
                "tree_cover_percentage": round(tree_pct, 2),
                "accessible_pixels": tree_pixels,
                "non_forest_pixels": non_forest_pixels,
                "filter_tree_cover": True,
                "filter_slope": False
            }

        else:
            # No filtering - just return total boundary area
            logger.info("Calculating total boundary area (no filters)")

            query = text(f"""
                SELECT
                    ST_Area(ST_Transform(
                        ST_GeomFromText(:wkt, 4326),
                        CASE
                            WHEN ST_X(ST_Centroid(ST_GeomFromText(:wkt, 4326))) < 84.0 THEN 32644
                            ELSE 32645
                        END
                    )) / {SQM_PER_HA} as area_ha
            """)

            result = db.execute(query, {"wkt": geometry_wkt}).first()

            total_area = result.area_ha if result else 0.0

            return {
                "total_boundary_area_ha": round(total_area, 4),
                "accessible_forest_area_ha": round(total_area, 4),
                "accessible_forest_percentage": 100.0,
                "filter_tree_cover": False,
                "filter_slope": False
            }

    except Exception as e:
        logger.error(f"Error calculating accessible forest area: {e}")
        return {
            "total_boundary_area_ha": 0.0,
            "accessible_forest_area_ha": 0.0,
            "inaccessible_steep_forest_ha": 0.0,
            "non_forest_area_ha": 0.0,
            "error": str(e)
        }


def extract_accessible_forest_mask(
    db: Session,
    geometry_wkt: str,
    filter_slope: bool = False,
    max_slope_degrees: float = 45.0,
    simplify_tolerance: float = 0.00001
) -> Optional[str]:
    # business: mask used to constrain sampling points to accessible forest only
    # constraint: ESA WorldCover pixel value 10 = tree cover (binary classification)
    """
    Extract accessible forest mask as polygon.

    Filters to tree cover (ESA = 10) first, then optionally filters by slope
    calculated from DEM using ST_Slope().

    Args:
        db: Database session
        geometry_wkt: WKT string of boundary polygon
        filter_slope: If True, exclude areas with slope > max_slope_degrees
        max_slope_degrees: Maximum slope threshold (default 45°)
        simplify_tolerance: Tolerance for polygon simplification (degrees, ~1m default)

    Returns:
        WKT of MultiPolygon/Polygon containing accessible forest areas, or None if no forest
    """
    try:
        if not filter_slope:
            # Simple case: just tree cover, no slope filtering
            logger.info("Extracting tree cover mask (no slope filter)...")

            query = text("""
                WITH tree_pixels AS (
                    SELECT (ST_DumpAsPolygons(
                        ST_Clip(rast, ST_GeomFromText(:wkt, 4326)), 1
                    )).*
                    FROM rasters.esa_world_cover
                    WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
                )
                SELECT
                    ST_AsText(
                        ST_SimplifyPreserveTopology(
                            ST_Union(geom),
                            :tolerance
                        )
                    ) as forest_wkt,
                    COUNT(*) as pixel_count
                FROM tree_pixels
                WHERE val = 10  -- Tree cover only
            """)

            result = db.execute(query, {
                "wkt": geometry_wkt,
                "tolerance": simplify_tolerance
            }).first()

            if not result or not result.forest_wkt:
                logger.warning("No tree cover found in boundary")
                return None

            logger.info(f"Tree cover mask extracted: {result.pixel_count} pixels")
            return result.forest_wkt

        else:
            # With slope filter: tree cover + slope calculated from DEM
            logger.info(f"Extracting accessible forest mask (tree cover + slope ≤{max_slope_degrees}°)...")

            query = text("""
                WITH tree_pixels AS (
                    -- Extract ESA WorldCover pixels
                    SELECT (ST_DumpAsPolygons(
                        ST_Clip(rast, ST_GeomFromText(:wkt, 4326)), 1
                    )).*
                    FROM rasters.esa_world_cover
                    WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
                ),
                tree_only AS (
                    -- FIRST: Filter to ONLY tree cover (value = 10)
                    SELECT geom
                    FROM tree_pixels
                    WHERE val = 10
                ),
                accessible_tree AS (
                    -- SECOND: Calculate slope from DEM and filter by threshold
                    SELECT t.geom
                    FROM tree_only t
                    CROSS JOIN LATERAL (
                        SELECT
                            ST_Value(
                                ST_Slope(rast, 1, '32BF'),  -- Calculate slope from DEM
                                ST_Centroid(t.geom)
                            ) as slope_degrees
                        FROM rasters.dem
                        WHERE ST_Intersects(rast, t.geom)
                        LIMIT 1
                    ) s
                    WHERE s.slope_degrees IS NOT NULL
                      AND s.slope_degrees <= :max_slope
                )
                SELECT
                    ST_AsText(
                        ST_SimplifyPreserveTopology(
                            ST_Union(geom),
                            :tolerance
                        )
                    ) as accessible_wkt,
                    COUNT(*) as pixel_count
                FROM accessible_tree
            """)

            result = db.execute(query, {
                "wkt": geometry_wkt,
                "max_slope": max_slope_degrees,
                "tolerance": simplify_tolerance
            }).first()

            if not result or not result.accessible_wkt:
                logger.warning(f"No accessible forest found (slope ≤{max_slope_degrees}°)")
                return None

            logger.info(
                f"Accessible forest mask extracted: {result.pixel_count} pixels "
                f"(tree cover + slope ≤{max_slope_degrees}°)"
            )

            return result.accessible_wkt

    except Exception as e:
        logger.error(f"Error extracting accessible forest mask: {e}")
        return None


def extract_tree_cover_pixel_centers(
    db: Session,
    geometry_wkt: str,
    filter_slope: bool = False,
    max_slope_degrees: float = 45.0,
    min_tree_cover_percent: float = 0.0
) -> list:
    # NOTE: pixel-center approach replaces old polygon-union method — more precise plot placement
    # constraint: ESA 10m cells — each cell center is one candidate plot location
    """
    Extract tree cover pixel centers as candidate sample plot locations.

    NEW APPROACH: Instead of creating polygons, work directly with pixel centers.
    Each 10m x 10m tree cover pixel can be a potential sample plot location.

    Args:
        db: Database session
        geometry_wkt: WKT string of boundary polygon
        filter_slope: If True, exclude pixels with slope > max_slope_degrees
        max_slope_degrees: Maximum slope threshold (default 45°)
        min_tree_cover_percent: Minimum tree cover percentage (currently not used - ESA is binary)

    Returns:
        List of tuples: [(lon, lat, slope_degrees), ...]
    """
    try:
        if not filter_slope:
            # Simple: Just extract tree cover pixel centers
            logger.info("Extracting tree cover pixel centers (no slope filter)...")

            query = text("""
                WITH tree_pixels AS (
                    -- Extract all ESA WorldCover pixels within boundary
                    SELECT (ST_DumpAsPolygons(
                        ST_Clip(rast, ST_GeomFromText(:wkt, 4326)), 1
                    )).*
                    FROM rasters.esa_world_cover
                    WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
                ),
                tree_centers AS (
                    -- Get pixel centers for tree cover only (value = 10)
                    SELECT
                        ST_X(ST_Centroid(geom)) as lon,
                        ST_Y(ST_Centroid(geom)) as lat
                    FROM tree_pixels
                    WHERE val = 10
                )
                SELECT lon, lat, NULL as slope_degrees
                FROM tree_centers
            """)

            results = db.execute(query, {"wkt": geometry_wkt}).fetchall()

            pixel_centers = [(row.lon, row.lat, row.slope_degrees) for row in results]
            logger.info(f"Extracted {len(pixel_centers)} tree cover pixel centers")
            return pixel_centers

        else:
            # With slope filter: tree cover + slope check
            logger.info(f"Extracting tree cover pixel centers (slope ≤{max_slope_degrees}°)...")

            query = text("""
                WITH tree_pixels AS (
                    -- Extract all ESA WorldCover pixels within boundary
                    SELECT (ST_DumpAsPolygons(
                        ST_Clip(rast, ST_GeomFromText(:wkt, 4326)), 1
                    )).*
                    FROM rasters.esa_world_cover
                    WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
                ),
                tree_only AS (
                    -- Filter to tree cover only (value = 10)
                    SELECT geom, val
                    FROM tree_pixels
                    WHERE val = 10
                ),
                tree_with_slope AS (
                    -- Calculate slope for each tree pixel
                    SELECT
                        ST_X(ST_Centroid(t.geom)) as lon,
                        ST_Y(ST_Centroid(t.geom)) as lat,
                        ST_Value(
                            ST_Slope(d.rast, 1, '32BF'),
                            ST_Centroid(t.geom)
                        ) as slope_degrees
                    FROM tree_only t
                    CROSS JOIN LATERAL (
                        SELECT rast
                        FROM rasters.dem
                        WHERE ST_Intersects(rast, t.geom)
                        LIMIT 1
                    ) d
                )
                SELECT lon, lat, slope_degrees
                FROM tree_with_slope
                WHERE slope_degrees IS NOT NULL
                  AND slope_degrees <= :max_slope
            """)

            results = db.execute(query, {
                "wkt": geometry_wkt,
                "max_slope": max_slope_degrees
            }).fetchall()

            pixel_centers = [(row.lon, row.lat, row.slope_degrees) for row in results]
            logger.info(
                f"Extracted {len(pixel_centers)} accessible tree pixel centers "
                f"(slope ≤{max_slope_degrees}°)"
            )
            return pixel_centers

    except Exception as e:
        logger.error(f"Error extracting tree pixel centers: {e}")
        return []


def point_in_accessible_forest(
    db: Session,
    lon: float,
    lat: float,
    filter_slope: bool = False,
    max_slope_degrees: float = 45.0
) -> bool:
    """
    Check if a point is within accessible forest area.

    Args:
        db: Database session
        lon: Longitude
        lat: Latitude
        filter_slope: If True, also check slope from DEM
        max_slope_degrees: Maximum slope threshold

    Returns:
        True if point is in accessible forest, False otherwise
    """
    try:
        if not filter_slope:
            # Just check tree cover
            query = text("""
                SELECT ST_Value(rast, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) as landcover
                FROM rasters.esa_world_cover
                WHERE ST_Intersects(rast, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                LIMIT 1
            """)

            result = db.execute(query, {"lon": lon, "lat": lat}).first()
            return result and result.landcover == 10  # Tree cover

        else:
            # Check tree cover AND slope
            query = text("""
                WITH point_geom AS (
                    SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) as geom
                )
                SELECT
                    (SELECT ST_Value(rast, p.geom)
                     FROM rasters.esa_world_cover, point_geom p
                     WHERE ST_Intersects(rast, p.geom)
                     LIMIT 1) as landcover,
                    (SELECT ST_Value(ST_Slope(rast, 1, '32BF'), p.geom)
                     FROM rasters.dem, point_geom p
                     WHERE ST_Intersects(rast, p.geom)
                     LIMIT 1) as slope_degrees
            """)

            result = db.execute(query, {"lon": lon, "lat": lat}).first()

            if not result:
                return False

            is_tree_cover = result.landcover == 10
            slope_ok = result.slope_degrees is not None and result.slope_degrees <= max_slope_degrees

            return is_tree_cover and slope_ok

    except Exception as e:
        logger.error(f"Error checking point in accessible forest: {e}")
        return False


def calculate_block_tree_cover_areas(
    db: Session,
    blocks: list
) -> list:
    # business: ratio-based approach ensures consistency between GIS area and pixel-based tree cover
    # why: pixel-counting alone can misalign with authoritative geometry area — ratio fixes that
    """
    Calculate tree cover areas for multiple blocks using ratio-based approach.

    This ensures consistency between geometry-based area and pixel-based tree cover:
    1. Get authoritative boundary area from PostGIS geometry
    2. Count total pixels within boundary
    3. Count tree pixels (ESA value=10) within boundary
    4. Calculate tree coverage ratio = tree_pixels / total_pixels
    5. Effective area = boundary_area × ratio

    Args:
        db: Database session
        blocks: List of block dictionaries with 'geometry' (WKT) and 'block_name'

    Returns:
        List of dictionaries with tree cover statistics for each block:
        {
            'block_name': str,
            'total_area_ha': float,  # From geometry (authoritative)
            'tree_pixels': int,
            'total_pixels': int,
            'tree_cover_ratio': float,  # 0.0 to 1.0
            'effective_area_ha': float,  # total_area × ratio
            'tree_cover_percentage': float  # For display
        }
    """
    results = []

    for block in blocks:
        try:
            block_name = block.get('block_name', 'Unknown')
            geometry_wkt = block.get('geometry')

            if not geometry_wkt:
                logger.warning(f"Block {block_name} has no geometry, skipping")
                results.append({
                    'block_name': block_name,
                    'total_area_ha': 0.0,
                    'tree_pixels': 0,
                    'total_pixels': 0,
                    'tree_cover_ratio': 0.0,
                    'effective_area_ha': 0.0,
                    'tree_cover_percentage': 0.0,
                    'error': 'No geometry'
                })
                continue

            logger.info(f"Calculating tree cover for block: {block_name}")

            # Execute SQL query to calculate all values
            query = text(f"""
                WITH boundary AS (
                    SELECT ST_GeomFromText(:wkt, 4326) as geom
                ),
                -- Get authoritative boundary area from geometry
                boundary_area AS (
                    SELECT
                        ST_Area(ST_Transform(
                            geom,
                            CASE
                                WHEN ST_X(ST_Centroid(geom)) < 84.0 THEN 32644
                                ELSE 32645
                            END
                        )) / {SQM_PER_HA} as area_ha
                    FROM boundary
                ),
                -- Clip ESA WorldCover raster to boundary
                clipped_rasters AS (
                    SELECT ST_Clip(rast, b.geom, 0.0, true) as clipped_rast
                    FROM rasters.esa_world_cover, boundary b
                    WHERE ST_Intersects(rast, b.geom)
                ),
                -- Count all pixels by value
                pixel_counts AS (
                    SELECT (ST_ValueCount(clipped_rast, 1, true)).*
                    FROM clipped_rasters
                    WHERE clipped_rast IS NOT NULL
                )
                SELECT
                    -- Authoritative area from geometry
                    (SELECT area_ha FROM boundary_area) as total_area_ha,
                    -- Pixel counts
                    SUM(count) FILTER (WHERE value = 10) as tree_pixels,
                    SUM(count) FILTER (WHERE value > 0) as total_pixels,
                    -- Tree cover ratio
                    CASE
                        WHEN SUM(count) FILTER (WHERE value > 0) > 0 THEN
                            CAST(SUM(count) FILTER (WHERE value = 10) AS FLOAT) /
                            CAST(SUM(count) FILTER (WHERE value > 0) AS FLOAT)
                        ELSE 0.0
                    END as tree_cover_ratio
                FROM pixel_counts
            """)

            result = db.execute(query, {"wkt": geometry_wkt}).first()

            if not result:
                logger.warning(f"No raster data found for block {block_name}")
                results.append({
                    'block_name': block_name,
                    'total_area_ha': 0.0,
                    'tree_pixels': 0,
                    'total_pixels': 0,
                    'tree_cover_ratio': 0.0,
                    'effective_area_ha': 0.0,
                    'tree_cover_percentage': 0.0,
                    'error': 'No raster data'
                })
                continue

            # Extract values
            total_area_ha = float(result.total_area_ha or 0)
            tree_pixels = int(result.tree_pixels or 0)
            total_pixels = int(result.total_pixels or 0)
            tree_cover_ratio = float(result.tree_cover_ratio or 0)

            # Calculate effective area using ratio
            effective_area_ha = total_area_ha * tree_cover_ratio
            tree_cover_percentage = tree_cover_ratio * 100.0

            block_result = {
                'block_name': block_name,
                'total_area_ha': round(total_area_ha, 4),
                'tree_pixels': tree_pixels,
                'total_pixels': total_pixels,
                'tree_cover_ratio': round(tree_cover_ratio, 4),
                'effective_area_ha': round(effective_area_ha, 4),
                'tree_cover_percentage': round(tree_cover_percentage, 2)
            }

            results.append(block_result)

            logger.info(
                f"Block {block_name}: "
                f"Total={total_area_ha:.2f}ha, "
                f"Effective={effective_area_ha:.2f}ha "
                f"({tree_cover_percentage:.1f}% tree cover)"
            )

        except Exception as e:
            logger.error(f"Error calculating tree cover for block {block_name}: {e}")
            results.append({
                'block_name': block.get('block_name', 'Unknown'),
                'total_area_ha': 0.0,
                'tree_pixels': 0,
                'total_pixels': 0,
                'tree_cover_ratio': 0.0,
                'effective_area_ha': 0.0,
                'tree_cover_percentage': 0.0,
                'error': str(e)
            })

    return results


def calculate_block_area_details(
    db: Session,
    blocks: List[Dict],
    sub_areas: List[Dict]
) -> List[Dict]:
    # business: Table 5 is the CFMG-mandated block-wise area breakdown for OP documents
    # constraint: effective geometry = block − protected − private (via Shapely ST_Difference)
    """
    Calculate Table 5 area details for all blocks.
    Uses exact GIS approach: builds effective geometry by subtracting
    protected and private land sub-areas from block geometry, then
    queries ESA WorldCover tree cover on the remaining area directly.

    For each block:
    1. Tree/Other cover via proportional ESA pixels on full block
    2. Protected/Private area from sub-area blockBreakdown (for display)
    3. Effective geometry = Block − Protected − Private (Shapely ST_Difference)
    4. Effective tree cover = ESA tree pixels on effective geometry

    Args:
        db: Database session
        blocks: List of block dicts from result_data['blocks']
        sub_areas: List of sub-area dicts from result_data['sub_areas']

    Returns:
        List of dicts with keys:
            block_name, total_area_ha, tree_cover_area_ha,
            other_landcover_area_ha, protected_area_ha,
            private_land_area_ha, effective_area_ha
    """
    from app.core.sub_area_kinds import PROTECTION_SUB_AREA_CATEGORIES, zones_and_protection

    # Table 5 is about the zones and the protection areas: a fire line is an overlay and changes no area figure, but a river bank
    # takes its ground out of production (owner, 2026-10-19), so it is a protected area here
    sub_areas = zones_and_protection(sub_areas)
    from shapely.geometry import shape as shapely_shape
    from shapely.ops import unary_union
    import pyproj
    from shapely.ops import transform

    results = []

    # Sub-area -> unit assignment is normally by stored block label. In
    # compartment mode the analysed units are renamed (C1..Cn) while the
    # sub-areas still carry the parent block's name, so no label ever matches
    # and Protected/Private collapse to 0 on every row. Detect that mismatch
    # up front and fall back to pure geometric assignment (each unit only ever
    # receives its own intersecting slice, so a non-overlapping partition
    # cannot double-count). When labels DO line up, this stays False and the
    # original name logic runs unchanged.
    def _sa_unit_labels(sa: Dict) -> set:
        labels = {item.get('blockName') for item in (sa.get('blockBreakdown') or [])}
        labels |= {sa.get('blockName'), sa.get('block_name')}
        return {label for label in labels if label}

    _unit_names = {b.get('block_name') for b in blocks if b.get('block_name')}
    _assign_by_geometry = bool(sub_areas) and not any(
        _sa_unit_labels(sa) & _unit_names for sa in sub_areas
    )
    if _assign_by_geometry:
        logger.info(
            "calculate_block_area_details: sub-area block labels do not match the "
            "analysed units (compartment mode?) - assigning sub-areas by geometry"
        )

    for block in blocks:
        try:
            block_name = block.get('block_name', 'Unknown')
            total_area_ha = float(block.get('area_hectares', 0))

            # Get block geometry
            block_geom = block.get('geometry_wkt') or block.get('geometry')
            if not block_geom:
                logger.warning(f"Block {block_name} has no geometry, skipping")
                results.append({
                    'block_name': block_name, 'total_area_ha': total_area_ha,
                    'tree_cover_area_ha': 0.0, 'other_landcover_area_ha': 0.0,
                    'protected_area_ha': 0.0, 'private_land_area_ha': 0.0,
                    'effective_area_ha': 0.0, 'official_area_ha': 0.0,
                    'error': 'No geometry'
                })
                continue

            # Convert to Shapely shape and WKT
            if isinstance(block_geom, dict):
                block_shape = shapely_shape(block_geom)
            elif isinstance(block_geom, str):
                from shapely.wkt import loads as wkt_loads
                block_shape = wkt_loads(block_geom)
            else:
                logger.warning(f"Block {block_name} has invalid geometry type")
                results.append({
                    'block_name': block_name, 'total_area_ha': total_area_ha,
                    'tree_cover_area_ha': 0.0, 'other_landcover_area_ha': 0.0,
                    'protected_area_ha': 0.0, 'private_land_area_ha': 0.0,
                    'effective_area_ha': 0.0, 'official_area_ha': 0.0,
                    'error': 'Invalid geometry type'
                })
                continue

            geometry_wkt = block_shape.wkt

            # ---------------------------------------------------------------
            # Query 1: ESA WorldCover on FULL block (tree cover + other)
            # ---------------------------------------------------------------
            query = text("""
                WITH boundary AS (
                    SELECT ST_GeomFromText(:wkt, 4326) as geom
                ),
                clipped_rasters AS (
                    SELECT ST_Clip(rast, b.geom, 0.0, true) as clipped_rast
                    FROM rasters.esa_world_cover, boundary b
                    WHERE ST_Intersects(rast, b.geom)
                ),
                pixel_counts AS (
                    SELECT (ST_ValueCount(clipped_rast, 1, true)).*
                    FROM clipped_rasters
                    WHERE clipped_rast IS NOT NULL
                )
                SELECT
                    SUM(count) FILTER (WHERE value = 10) as tree_pixels,
                    SUM(count) FILTER (WHERE value > 0) as total_pixels
                FROM pixel_counts
            """)

            result = db.execute(query, {"wkt": geometry_wkt}).first()

            total_pixels = int(result.total_pixels or 0) if result else 0
            tree_pixels = int(result.tree_pixels or 0) if result else 0

            if total_pixels > 0 and total_area_ha > 0:
                tree_cover_ratio = tree_pixels / total_pixels
                tree_cover_area_ha = total_area_ha * tree_cover_ratio
                other_landcover_area_ha = total_area_ha * (1 - tree_cover_ratio)
            else:
                tree_cover_area_ha = 0.0
                other_landcover_area_ha = 0.0

            # ---------------------------------------------------------------
            # Build effective geometry: Block − (Protected ∪ Private)
            # ---------------------------------------------------------------
            protected_area_ha = 0.0
            private_land_area_ha = 0.0
            excluded_shapes = []
            protected_utm_shapes = []   # unioned below: a river bank over a protected zone counts once

            for sa in sub_areas:
                sa_category = sa.get('category', '')
                block_breakdown = sa.get('blockBreakdown', [])

                # Determine if this sub-area belongs to this block. In
                # geometry-assignment mode the real filter is the non-empty
                # intersection test below, so let every sub-area through here.
                if _assign_by_geometry:
                    belongs = True
                elif block_breakdown and len(block_breakdown) > 0:
                    entry = next((item for item in block_breakdown if item.get('blockName') == block_name), None)
                    belongs = entry is not None
                else:
                    belongs = (sa.get('blockName') == block_name or sa.get('block_name') == block_name)

                if not belongs:
                    continue

                # Build intersection geometry for exact area and subtraction
                sa_geom = sa.get('geometry')
                if not sa_geom or not isinstance(sa_geom, dict):
                    continue
                try:
                    sa_shape = shapely_shape(sa_geom)
                    intersection = sa_shape.intersection(block_shape)
                    if intersection.is_empty:
                        continue

                    excluded_shapes.append(intersection)

                    # Calculate accurate intersection area using UTM projection
                    centroid = intersection.centroid
                    utm_srid = 32644 if centroid.x < 84 else 32645
                    project = pyproj.Transformer.from_crs(
                        "EPSG:4326", f"EPSG:{utm_srid}", always_xy=True
                    ).transform
                    intersection_utm = transform(project, intersection)
                    intersection_area_ha = abs(intersection_utm.area) / SQM_PER_HA

                    if sa_category in PROTECTION_SUB_AREA_CATEGORIES:
                        protected_utm_shapes.append(intersection_utm)
                    elif sa_category == 'private_land':
                        private_land_area_ha += intersection_area_ha
                except Exception as e:
                    logger.warning(f"Error intersecting sub-area {sa.get('name')} with block {block_name}: {e}")
                    continue

            if protected_utm_shapes:
                protected_area_ha = abs(unary_union(protected_utm_shapes).area) / SQM_PER_HA

            # ---------------------------------------------------------------
            # Query 2: ESA WorldCover on EFFECTIVE geometry
            # ---------------------------------------------------------------
            if excluded_shapes:
                excluded_union = unary_union(excluded_shapes)
                effective_shape = block_shape.difference(excluded_union)
            else:
                effective_shape = block_shape

            if effective_shape.is_empty:
                effective_area_ha = 0.0
            else:
                effective_wkt = effective_shape.wkt

                # Get accurate effective geometry area via UTM projection
                try:
                    centroid = effective_shape.centroid
                    utm_srid = 32644 if centroid.x < 84 else 32645
                    project = pyproj.Transformer.from_crs(
                        "EPSG:4326", f"EPSG:{utm_srid}", always_xy=True
                    ).transform
                    eff_utm = transform(project, effective_shape)
                    effective_geom_area_ha = abs(eff_utm.area) / SQM_PER_HA
                except Exception:
                    # The fallback subtracts the exclusions from the gross area instead of
                    # measuring the remaining shape, which double-counts anywhere the
                    # excluded areas overlap each other.
                    logger.exception(
                        "effective area could not be measured in UTM - falling back to "
                        "subtraction, which double-counts overlapping exclusions"
                    )
                    effective_geom_area_ha = total_area_ha - protected_area_ha - private_land_area_ha

                eff_query = text("""
                    WITH boundary AS (
                        SELECT ST_GeomFromText(:wkt, 4326) as geom
                    ),
                    clipped_rasters AS (
                        SELECT ST_Clip(rast, b.geom, 0.0, true) as clipped_rast
                        FROM rasters.esa_world_cover, boundary b
                        WHERE ST_Intersects(rast, b.geom)
                    ),
                    pixel_counts AS (
                        SELECT (ST_ValueCount(clipped_rast, 1, true)).*
                        FROM clipped_rasters
                        WHERE clipped_rast IS NOT NULL
                    )
                    SELECT
                        SUM(count) FILTER (WHERE value = 10) as tree_pixels,
                        SUM(count) FILTER (WHERE value > 0) as total_pixels
                    FROM pixel_counts
                """)

                eff_result = db.execute(eff_query, {"wkt": effective_wkt}).first()
                eff_total_pixels = int(eff_result.total_pixels or 0) if eff_result else 0
                eff_tree_pixels = int(eff_result.tree_pixels or 0) if eff_result else 0

                if eff_total_pixels > 0 and effective_geom_area_ha > 0:
                    eff_ratio = eff_tree_pixels / eff_total_pixels
                    effective_area_ha = effective_geom_area_ha * eff_ratio
                else:
                    effective_area_ha = 0.0

            block_result = {
                'block_name': block_name,
                'total_area_ha': round(total_area_ha, 4),
                'tree_cover_area_ha': round(tree_cover_area_ha, 4),
                'other_landcover_area_ha': round(other_landcover_area_ha, 4),
                'protected_area_ha': round(protected_area_ha, 4),
                'private_land_area_ha': round(private_land_area_ha, 4),
                'effective_area_ha': round(effective_area_ha, 4),
                'official_area_ha': round(total_area_ha - private_land_area_ha, 4)
            }

            results.append(block_result)

            logger.info(
                f"Block {block_name}: Total={total_area_ha:.2f}ha, "
                f"Tree={tree_cover_area_ha:.2f}ha, Other={other_landcover_area_ha:.2f}ha, "
                f"Protected={protected_area_ha:.2f}ha, Private={private_land_area_ha:.2f}ha, "
                f"Effective={effective_area_ha:.2f}ha"
            )

        except Exception as e:
            logger.error(f"Error calculating block area details for {block.get('block_name', 'Unknown')}: {e}")
            results.append({
                'block_name': block.get('block_name', 'Unknown'),
                'total_area_ha': float(block.get('area_hectares', 0)),
                'tree_cover_area_ha': 0.0,
                'other_landcover_area_ha': 0.0,
                'protected_area_ha': 0.0,
                'private_land_area_ha': 0.0,
                'effective_area_ha': 0.0,
                'official_area_ha': 0.0,
                'error': str(e)
            })

    return results
