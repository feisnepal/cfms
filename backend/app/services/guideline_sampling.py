"""
Forest Inventory Guideline-2061 sampling lookup functions
# business: Guideline-2061 sampling protocol

This module provides functions for sampling design based on Nepal's
Department of Forest Inventory Guideline-2061, which specifies sample
counts based on block size, sampling intensity, and plot size.

Key Features:
- Lookup sample counts from guideline tables (0.5%, 1%, 0.1%)
- Classify blocks by majority area (productive vs protected)
- Detect protected zones in calculations
- Fallback to manual calculation for blocks exceeding table ranges
# constraint: 200m × 250m grid per guideline
# NOTE: kept as reference alongside sampling.py
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, Dict, List
import logging

from app.core.sub_area_kinds import PROTECTION_SUB_AREA_CATEGORIES
from shapely import wkt
from shapely.geometry import shape

logger = logging.getLogger(__name__)


def get_sample_count_from_guideline(
    db: Session,
    block_area_hectares: float,
    intensity_percent: float,
    plot_size_sqm: int
) -> int:
    """
    Lookup sample count from Forest Inventory Guideline-2061 tables.

    The guideline provides standardized sample counts based on:
    - Block area (hectares)
    - Sampling intensity (0.5%, 1%, or 0.1%)
    - Plot size (100, 200, 300, 400, 500 sqm for production; 25, 100 for protected)

    Args:
        db: Database session
        block_area_hectares: Block area in hectares
        intensity_percent: Sampling intensity (0.5, 1.0, or 0.1)
        plot_size_sqm: Plot size in square meters

    Returns:
        Number of samples as per guideline table

    Raises:
        ValueError: If parameters are invalid or block size exceeds table range
                   (caller should fall back to manual calculation)

    Examples:
        >>> # Standard production forest (50 ha, 0.5%, 500 sqm)
        >>> count = get_sample_count_from_guideline(db, 50.0, 0.5, 500)
        >>> # Returns: 10 samples (from guideline table)

        >>> # Protected area (15 ha, 0.1%, 100 sqm)
        >>> count = get_sample_count_from_guideline(db, 15.0, 0.1, 100)
        >>> # Returns: 3 samples (from protected area table)
    """
    # Determine which table to use based on intensity
    if intensity_percent == 0.5:
        table = "sample_size_half_percent_intensity"
    elif intensity_percent == 1.0:
        table = "sample_size_one_percent_intensity"
    elif intensity_percent == 0.1:
        table = "sample_intensity_point_one_percent_protected_area"
    else:
        raise ValueError(
            f"Invalid intensity: {intensity_percent}%. Must be 0.5, 1.0, or 0.1"
        )

    # Determine column name for plot size
    if intensity_percent == 0.1:
        # Protected area table has different column names (with spaces)
        if plot_size_sqm == 100:
            col = '"number_of_samples_if_sample size 100_sqm"'  # Note: space in name
        elif plot_size_sqm == 25:
            col = '"number_of_samples_if_sample size_25_sqm"'
        else:
            raise ValueError(
                f"Protected area sampling only supports 25 or 100 sqm plots. "
                f"Got: {plot_size_sqm} sqm"
            )
    else:
        # Production tables (0.5% and 1%)
        col_map = {
            100: '"number_of_samples_if_100 sqm_sample_size"',
            200: '"number_of_samples_if_200 sqm_sample_size"',
            300: '"number_of_samples_if_300sqm_sample_size"',
            400: '"number_of_samples_if_400sqm_sample_size"',
            500: '"number_of_samples_if_500sqm_sample_size"'
        }
        if plot_size_sqm not in col_map:
            raise ValueError(
                f"Invalid plot size for production forest: {plot_size_sqm} sqm. "
                f"Must be one of: {list(col_map.keys())}"
            )
        col = col_map[plot_size_sqm]

    # Query table with range check
    # Note: Table columns are VARCHAR, need to cast to numeric
    ALLOWED_TABLES = {"sample_size_half_percent_intensity", "sample_size_one_percent_intensity", "sample_intensity_point_one_percent_protected_area"}
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Invalid guideline table: {table}")

    ALLOWED_COLUMNS = {
        '"number_of_samples_if_sample size 100_sqm"',
        '"number_of_samples_if_sample size_25_sqm"',
        '"number_of_samples_if_100 sqm_sample_size"',
        '"number_of_samples_if_200 sqm_sample_size"',
        '"number_of_samples_if_300sqm_sample_size"',
        '"number_of_samples_if_400sqm_sample_size"',
        '"number_of_samples_if_500sqm_sample_size"'
    }
    if col not in ALLOWED_COLUMNS:
        raise ValueError(f"Invalid guideline column: {col}")

    query = text(f"""
        SELECT {col}::integer as sample_count
        FROM public.{table}
        WHERE forest_block_size_minimum_ha::numeric <= :block_area
          AND forest_block_size_maximum_ha::numeric >= :block_area
        LIMIT 1
    """)

    try:
        result = db.execute(query, {"block_area": block_area_hectares}).first()
    except Exception as e:
        logger.error(f"Database query failed for guideline lookup: {str(e)}")
        raise ValueError(f"Failed to query guideline table: {str(e)}")

    if not result:
        # Block size exceeds guideline table range
        # Caller should fall back to manual calculation
        raise ValueError(
            f"Block size {block_area_hectares} ha exceeds guideline table range "
            f"for {intensity_percent}% intensity. Use manual calculation fallback."
        )

    logger.info(
        f"Guideline-2061 lookup: {block_area_hectares} ha @ {intensity_percent}% "
        f"with {plot_size_sqm} sqm plots → {result.sample_count} samples"
    )

    return result.sample_count


def classify_block_by_majority_area(
    block_wkt: str,
    sub_areas: List[Dict]
) -> bool:
    """
    Determine if a block is majority protected area using >50% rule.

    Decision Rule (APPROVED):
    - If >50% of block area overlaps with protected sub-areas → Protected (0.1%)
    - If ≤50% of block area overlaps with protected sub-areas → Productive (0.5% or 1%)

    This handles blocks that span both productive and protected zones by
    classifying the entire block based on which category is dominant.

    Args:
        block_wkt: WKT string of block polygon
        sub_areas: List of sub-area dictionaries from calculation.result_data
                  Each dict must have: category, geometry, isExcluded (optional)

    Returns:
        True if block is majority protected (>50%), False otherwise

    Examples:
        >>> # Block with 60% protected overlap
        >>> is_protected = classify_block_by_majority_area(block_wkt, sub_areas)
        >>> # Returns: True (should sample at 0.1%)

        >>> # Block with 30% protected overlap
        >>> is_protected = classify_block_by_majority_area(block_wkt, sub_areas)
        >>> # Returns: False (should sample at 0.5% or 1%)
    """
    try:
        block_geom = wkt.loads(block_wkt)
    except Exception as e:
        logger.error(f"Failed to parse block WKT: {str(e)}")
        return False

    block_area = block_geom.area

    if block_area == 0:
        logger.warning("Block has zero area, classifying as productive")
        return False

    # Find all protected sub-areas (exclude areas marked as excluded)
    protected_sub_areas = [
        sa for sa in sub_areas
        if sa.get('category') in PROTECTION_SUB_AREA_CATEGORIES and not sa.get('isExcluded', False)
    ]

    if not protected_sub_areas:
        # No protected zones at all
        return False

    # Calculate total protected area within block
    protected_overlap_area = 0.0
    for sub_area in protected_sub_areas:
        try:
            geom_data = sub_area['geometry']

            # Handle GeometryCollection - extract only Polygon/MultiPolygon
            if geom_data.get('type') == 'GeometryCollection':
                from shapely.geometry import GeometryCollection
                geom_collection = shape(geom_data)

                # Extract only polygonal geometries (filter out LineStrings, Points)
                polygons = [g for g in geom_collection.geoms
                           if g.geom_type in ('Polygon', 'MultiPolygon') and g.area > 0]

                if not polygons:
                    logger.warning(
                        f"GeometryCollection for {sub_area.get('name', 'unnamed')} "
                        f"contains no valid polygons. Skipping."
                    )
                    continue

                # Merge all polygons into single geometry
                if len(polygons) == 1:
                    sub_area_geom = polygons[0]
                else:
                    from shapely.ops import unary_union
                    sub_area_geom = unary_union(polygons)
            else:
                # Regular Polygon or MultiPolygon
                sub_area_geom = shape(geom_data)

            # Skip zero-area geometries
            if sub_area_geom.area == 0:
                logger.warning(
                    f"Sub-area {sub_area.get('name', 'unnamed')} has zero area. Skipping."
                )
                continue

            # Calculate intersection with block
            intersection = block_geom.intersection(sub_area_geom)
            protected_overlap_area += intersection.area

        except Exception as e:
            logger.warning(
                f"Failed to calculate intersection for sub-area "
                f"{sub_area.get('name', 'unnamed')}: {str(e)}"
            )
            continue

    # Classify based on majority (>50% rule)
    protected_percentage = (protected_overlap_area / block_area) * 100
    is_protected = protected_percentage > 50.0

    logger.info(
        f"Block classification: area={block_area:.6f} sq degrees, "
        f"protected_overlap={protected_overlap_area:.6f} sq degrees "
        f"({protected_percentage:.1f}%) → {'PROTECTED' if is_protected else 'PRODUCTIVE'}"
    )

    return is_protected


def detect_protected_zones(calculation) -> Dict:
    """
    Detect if calculation has protected zones in sub-areas.

    Scans the calculation's sub-areas to find any marked as 'protected'
    category and not excluded. Provides summary statistics for UI display.

    Args:
        calculation: Calculation model instance with result_data

    Returns:
        Dictionary with:
        {
            "has_protected": bool - True if any protected zones exist,
            "protected_area_hectares": float - Total protected area,
            "protected_zone_names": list[str] - Names of protected zones,
            "protected_zone_count": int - Number of protected zones,
            "productive_area_hectares": float - Non-protected area,
            "total_area_hectares": float - Total forest area
        }

    Examples:
        >>> info = detect_protected_zones(calculation)
        >>> if info["has_protected"]:
        >>>     print(f"Found {info['protected_area_hectares']} ha protected")
        >>>     # Show protected zone sampling option to user
    """
    sub_areas = calculation.result_data.get('sub_areas', [])

    # Find protected zones (not excluded)
    protected_zones = [
        sa for sa in sub_areas
        if sa.get('category') in PROTECTION_SUB_AREA_CATEGORIES and not sa.get('isExcluded', False)
    ]

    # Calculate total protected area
    protected_area = sum(sa.get('area_hectares', 0) for sa in protected_zones)

    # Get protected zone names
    protected_names = [
        sa.get('name', 'Unnamed Protected Zone')
        for sa in protected_zones
    ]

    # Get total forest area
    total_area = calculation.result_data.get('total_area', 0)

    # Calculate productive area (non-protected)
    productive_area = max(0, total_area - protected_area)

    result = {
        "has_protected": len(protected_zones) > 0,
        "protected_area_hectares": round(protected_area, 4),
        "protected_zone_names": protected_names,
        "protected_zone_count": len(protected_zones),
        "productive_area_hectares": round(productive_area, 4),
        "total_area_hectares": round(total_area, 4)
    }

    logger.info(
        f"Protected zone detection: {result['protected_zone_count']} zones found, "
        f"{result['protected_area_hectares']} ha protected, "
        f"{result['productive_area_hectares']} ha productive"
    )

    return result


def validate_guideline_parameters(
    intensity_percent: float,
    plot_size_sqm: int,
    is_protected_sampling: bool = False
) -> None:
    """
    Validate that guideline parameters are compatible.

    Args:
        intensity_percent: Sampling intensity (0.5, 1.0, 2.0, or 0.1)
        plot_size_sqm: Plot size in square meters
        is_protected_sampling: True if sampling protected areas

    Raises:
        ValueError: If parameters are invalid or incompatible

    Examples:
        >>> # Valid production sampling
        >>> validate_guideline_parameters(0.5, 500, False)  # OK

        >>> # Invalid: protected area with wrong plot size
        >>> validate_guideline_parameters(0.1, 500, True)
        ValueError: Protected area sampling requires 25 or 100 sqm plots
    """
    # Validate intensity. 2.0% is SFM's कार्यविधि §16 Production-stratum
    # intensity (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md / SLOPE_COMPARTMENT_AND
    # _STRATIFIED_SAMPLING_PLAN.md Part B) - higher than the DoF-2061 defaults
    # this module otherwise validates.
    #
    # Owner report 2026-10-02: a per-block intensity override (e.g. 2.5%,
    # 1.7%, 3.2%) was rejected outright even though `get_sample_count_from_
    # guideline`'s own caller (sampling.py) already falls back to a manual
    # area/plot-size calculation for any intensity not in its lookup tables
    # -- the fixed DoF-2061 enum below only matched a table that IS looked
    # up, not what sample generation can actually accept. Production
    # intensity now accepts any decimal value up to 5% (plan's own stated
    # ceiling), produced via that same manual-calc fallback; the fixed
    # {0.5, 1.0, 2.0} values still also resolve via the guideline LOOKUP
    # TABLE when they match exactly (unaffected by this change). 0.1%
    # (protected-area) keeps its own fixed value -- a separate legal
    # requirement this report did not ask to change.
    if is_protected_sampling or intensity_percent == 0.1:
        if intensity_percent != 0.1:
            raise ValueError(
                f"Invalid intensity: {intensity_percent}%. "
                f"Protected area sampling requires 0.1%."
            )
    else:
        # Owner 2026-10-08: an intensity may be RAISED above the usual 5 % - the screen warns, the server does not refuse.
        # Only a value that is not above 0 is invalid (0 itself never reaches here: it means "do not sample this unit").
        if not intensity_percent > 0:
            raise ValueError(
                f"Invalid intensity: {intensity_percent}%. Must be greater than 0%."
            )

    # Validate plot size based on context
    if is_protected_sampling or intensity_percent == 0.1:
        # Protected area sampling
        valid_protected_sizes = [25, 100]
        if plot_size_sqm not in valid_protected_sizes:
            raise ValueError(
                f"Protected area sampling requires 25 or 100 sqm plots. "
                f"Got: {plot_size_sqm} sqm"
            )
    else:
        # Production forest sampling
        valid_production_sizes = [100, 200, 300, 400, 500]
        if plot_size_sqm not in valid_production_sizes:
            raise ValueError(
                f"Production forest sampling requires one of {valid_production_sizes} sqm plots. "
                f"Got: {plot_size_sqm} sqm"
            )

    # Validate intensity-plot size compatibility
    if intensity_percent == 0.1 and plot_size_sqm not in [25, 100]:
        raise ValueError(
            f"0.1% intensity (protected area) only supports 25 or 100 sqm plots. "
            f"Got: {plot_size_sqm} sqm"
        )

    if not is_protected_sampling and intensity_percent != 0.1 and plot_size_sqm == 25:
        raise ValueError(
            f"{intensity_percent}% intensity (production) does not support 25 sqm plots. "
            f"Use 100-500 sqm plots."
        )

    logger.debug(
        f"Guideline parameters validated: {intensity_percent}% intensity, "
        f"{plot_size_sqm} sqm plots, protected={is_protected_sampling}"
    )
