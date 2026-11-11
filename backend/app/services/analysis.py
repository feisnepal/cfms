"""
Forest boundary analysis service
Performs raster and vector analysis on uploaded forest boundaries
"""
import os
import time
import json
import logging
from typing import Dict, Any, Tuple, Optional, List
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from datetime import datetime
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from shapely import wkt as shapely_wkt
from app.core.config import settings

import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask

from ..models.calculation import Calculation
from ..core.constants import SQM_PER_HA
from .block_reconcile_service import reconcile_blocks_from_db, reconcile_compartments_from_db
from .analysis_polygon_source import PolygonSource
from app.core.forest_types import ESA_WORLD_COVER, get_esa_land_cover
from app.core.soil_fertility import assess_soil_fertility

logger = logging.getLogger(__name__)


def reset_txn(db: Session):
    """Reset database transaction after any error to prevent cascading failures"""
    try:
        db.commit()
    except Exception:
        logger.exception(
            "could not persist the analysis update - rolled back, so the "
            "change is lost"
        )
        db.rollback()


def get_excluded_sub_areas(existing_data: Dict) -> List[Dict]:
    """
    Get all sub-areas that are marked as excluded (private land)
    """
    sub_areas = existing_data.get('sub_areas', [])
    excluded = []
    for sa in sub_areas:
        if sa.get('isExcluded') or sa.get('is_excluded'):
            excluded.append(sa)
    return excluded


def create_block_working_geometry(block_geometry: Dict, excluded_sub_areas: List[Dict], utm_srid: int = None) -> Optional[Dict]:
    """
    Create a working geometry for a block by excluding private land areas.

    Args:
        block_geometry: Block geometry in GeoJSON format
        excluded_sub_areas: List of excluded sub-areas
        utm_srid: UTM projection zone (optional, not used in this function)

    Returns:
        Working geometry in GeoJSON format (with exclusions), or None if no exclusions
    """
    if not excluded_sub_areas:
        return block_geometry
    
    try:
        # Convert block geometry to shapely
        block_shapely = shape(block_geometry)
        if block_shapely.is_empty:
            return block_geometry
        
        # Collect excluded geometries that intersect with this block
        excluded_geometries = []
        for sa in excluded_sub_areas:
            sa_geom = sa.get('geometry')
            if sa_geom:
                try:
                    sa_shapely = shape(sa_geom)
                    # Only include if it intersects with block
                    if block_shapely.intersects(sa_shapely):
                        excluded_geometries.append(sa_shapely.intersection(block_shapely))
                except Exception as e:
                    logger.warning(f"Warning: Could not process excluded area: {e}")
                    continue
        
        if not excluded_geometries:
            return block_geometry
        
        # Union all excluded geometries
        excluded_union = unary_union(excluded_geometries)
        
        # Subtract from block geometry
        working_geometry = block_shapely.difference(excluded_union)
        
        if working_geometry.is_empty:
            return None
            
        # Return as GeoJSON
        return mapping(working_geometry)
        
    except Exception as e:
        logger.error(f"Error creating block working geometry: {e}")
        return block_geometry


def calculate_excluded_area_in_block(block_geometry: Dict, excluded_sub_areas: List[Dict], utm_srid: int = None) -> float:
    """
    Calculate the total excluded area within a block.

    Automatically calculates the appropriate UTM zone based on geometry location.

    Args:
        block_geometry: Block geometry in GeoJSON format
        excluded_sub_areas: List of excluded sub-areas
        utm_srid: UTM projection zone (optional, auto-calculated if not provided)

    Returns:
        Area in hectares
    """
    if not excluded_sub_areas:
        return 0.0

    try:
        block_shapely = shape(block_geometry)
        if block_shapely.is_empty:
            return 0.0

        # Auto-calculate UTM zone if not provided
        if utm_srid is None:
            centroid = block_shapely.centroid
            # Calculate UTM zone: zone = floor((longitude + 180) / 6) + 1
            zone = int((centroid.x + 180) / 6) + 1
            # Northern hemisphere: 32601-32660, Southern: 32701-32760
            utm_srid = 32600 + zone if centroid.y >= 0 else 32700 + zone

        total_excluded = 0.0
        for sa in excluded_sub_areas:
            sa_geom = sa.get('geometry')
            if sa_geom:
                try:
                    sa_shapely = shape(sa_geom)
                    intersection = block_shapely.intersection(sa_shapely)
                    if not intersection.is_empty:
                        # Calculate area in hectares using UTM projection
                        import pyproj
                        from shapely.ops import transform

                        project = pyproj.Transformer.from_crs(
                            "EPSG:4326",
                            f"EPSG:{utm_srid}",
                            always_xy=True
                        ).transform
                        intersection_utm = transform(project, intersection)
                        total_excluded += intersection_utm.area / SQM_PER_HA
                except Exception as e:
                    logger.warning(f"Warning: Could not calculate excluded area: {e}")
                    continue
        
        return round(total_excluded, 4)
        
    except Exception as e:
        logger.error(f"Error calculating excluded area in block: {e}")
        return 0.0


async def analyze_forest_boundary(calculation_id: UUID, db: Session, options: Optional[Dict[str, bool]] = None) -> Tuple[Dict[str, Any], int]:
    """
    Perform comprehensive analysis on forest boundary
    Now analyzes each block separately and adds analysis results to each block

    Args:
        calculation_id: UUID of calculation record
        db: Database session
        options: Dict of boolean flags to enable/disable specific analyses
                 If None, all analyses run (backward compatible)

    Returns:
        Tuple of (result_data dict, processing_time_seconds)
    """
    # Default options: run everything if not specified
    if options is None:
        options = {}

    # Helper function to check if analysis should run
    def should_run(analysis_name: str) -> bool:
        return options.get(analysis_name, True)  # Default True for backward compatibility
    # Per-block analysis enabled
    start_time = time.time()

    # Get calculation record
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise ValueError(f"Calculation {calculation_id} not found")

    results = {}

    # Get existing result_data with blocks
    # Permanent cure: forest_blocks is the single source of truth. Reconcile the
    # JSONB snapshot from the DB so analysis runs on the SAME blocks the
    # MapWorkspace shows (BA-3), not a stale drained copy. No-op for legacy
    # upload-mode calcs that have no forest_blocks rows (JSONB fallback stands).
    reconcile_blocks_from_db(db, calculation)
    # ...and the same for compartments: a workspace "divide into compartments"
    # only writes forest_blocks rows, so without this the analyser (which reads
    # result_data['compartments'] via PolygonSource) keeps running per BLOCK on
    # a forest the user divided into compartments.
    reconcile_compartments_from_db(db, calculation)
    existing_data = calculation.result_data or {}
    source = PolygonSource.for_result_data(existing_data)
    blocks = source.get_polygons()
    metadata_key = source.get_metadata_key()

    # FALLBACK: If no blocks/compartments exist, create default single block from boundary_geom
    if not blocks:
        logger.warning(f"No blocks found for calculation {calculation_id}, creating default single block")

        # Get boundary geometry as GeoJSON
        boundary_wkt = db.execute(
            text("SELECT ST_AsText(boundary_geom) FROM calculations WHERE id = :calc_id"),
            {"calc_id": str(calculation_id)}
        ).scalar()

        if not boundary_wkt:
            raise ValueError(f"Calculation {calculation_id} has no boundary geometry")

        # Calculate area in hectares (using UTM projection 32645 for Nepal)
        area_hectares = db.execute(
            text(f"SELECT ST_Area(ST_Transform(boundary_geom, 32645)) / {SQM_PER_HA} FROM calculations WHERE id = :calc_id"),
            {"calc_id": str(calculation_id)}
        ).scalar()

        # Get geometry as GeoJSON
        block_geojson = db.execute(
            text("SELECT ST_AsGeoJSON(boundary_geom) FROM calculations WHERE id = :calc_id"),
            {"calc_id": str(calculation_id)}
        ).scalar()

        # Create default block
        import json
        default_block = {
            'block_index': 0,
            'block_name': calculation.forest_name or 'Block 1',
            'area_hectares': float(area_hectares) if area_hectares else 0,
            'geometry': json.loads(block_geojson) if block_geojson else None
        }
        blocks = [default_block]

        # Save to result_data
        existing_data[metadata_key] = blocks
        existing_data['total_blocks'] = 1
        calculation.result_data = existing_data

        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(calculation, 'result_data')
        db.commit()
        logger.info(f"✓ Default {metadata_key} created for calculation {calculation_id}")

    # Get excluded sub-areas (private land) for exclusion from analysis
    excluded_sub_areas = get_excluded_sub_areas(existing_data)
    total_excluded_area = 0
    
    if excluded_sub_areas:
        logger.info(f"[EXCLUSION] Found {len(excluded_sub_areas)} excluded sub-areas (private land)")
        # Calculate total excluded area
        for sa in excluded_sub_areas:
            total_excluded_area += sa.get('area_hectares', 0)
        logger.info(f"[EXCLUSION] Total excluded area: {total_excluded_area:.4f} ha")

    # business: CFMG — calculation workflow states: each block transitions from 'pending' → 'analyzing' → 'completed'/'failed'
    # why: each analysis type (raster, vector, admin) runs independently for parallel execution within per-block scope
    analyzed_blocks = []
    for i, block in enumerate(blocks):
        block_name = block.get('block_name', f'Block {i+1}')
        logger.info(f"Analyzing block {i+1}/{len(blocks)}: {block_name}")

        
        # Get block geometry
        block_geometry = block.get('geometry')
        
        # Calculate excluded area within this block
        block_excluded_area = 0
        if excluded_sub_areas and block_geometry:
            block_excluded_area = calculate_excluded_area_in_block(block_geometry, excluded_sub_areas)
            logger.info(f"[EXCLUSION] Block '{block_name}' has {block_excluded_area:.4f} ha of private land")

        try:
            # Check if we have excluded areas to subtract
            # business: CFMG — block area calculation must exclude private land (sub-areas marked is_excluded)
            working_geometry = block_geometry
            if excluded_sub_areas and block_geometry:
                working_geometry = create_block_working_geometry(block_geometry, excluded_sub_areas)
                if working_geometry is None:
                    # Entire block is excluded (private land)
                    logger.info(f"[EXCLUSION] Block '{block_name}' is entirely private land - skipping analysis")
                    analyzed_block = {
                        **block,
                        "area_hectares": 0,
                        "excluded_area_hectares": block.get('area_hectares', 0),
                        "effective_area_hectares": 0,
                        "is_fully_excluded": True,
                        "analysis_skipped": "Block is entirely private land"
                    }
                    analyzed_blocks.append(analyzed_block)
                    continue
                elif working_geometry != block_geometry:
                    logger.info(f"[EXCLUSION] Block '{block_name}' - running analysis on working geometry (excluded {block_excluded_area:.4f} ha)")
            

            # H3.5 — DEBUG-only failure hook, so the fail-fast gate can be tested.
            #
            # A partial calculation cannot be produced by clicking: every ordinary
            # path yields units that analyse fine, which is exactly why the defect
            # survived -- the only way to see `completed` written over partial data
            # was to be unlucky in production, on a document with statutory
            # standing. `scripts/trigger_partial_calculation.py` drives this.
            #
            # It sits INSIDE the try on purpose. Outside it, the raise escapes the
            # loop and the whole analysis aborts -- a real failure, but not the one
            # H3.5 guards. The gate is about PARTIAL data: this block must fail, be
            # caught by the handler below, be tagged `analysis_error`, and the other
            # blocks must still analyse. Placing it outside produced exactly that
            # wrong result on the first run: FAILED, but zero tagged units.
            #
            # Guarded on settings.DEBUG, as the frontend's `?__crash=1` is guarded
            # on import.meta.env.DEV (H3.8). One string comparison per block on a
            # path that already does raster work, and it cannot fire where DEBUG is
            # false -- which the launch checklist requires.
            _forced = settings.DEBUG and os.getenv("CFMS_FORCE_BLOCK_FAILURE", "").strip()
            if _forced and _forced.lower() in ("*", str(block_name).strip().lower()):
                raise RuntimeError(
                    f"DEBUG failure hook: forced analysis failure for "
                    f"'{block_name}' (H3.5, CFMS_FORCE_BLOCK_FAILURE)"
                )

            block_analysis = await analyze_block_geometry(
                working_geometry,
                calculation_id,
                db,
                options
            )
            # Merge analysis results into block data
            analyzed_block = {**block, **block_analysis}
            
            # Add excluded area tracking to block
            analyzed_block['excluded_area_hectares'] = block_excluded_area
            original_area = block.get('area_hectares', 0)
            analyzed_block['original_area_hectares'] = original_area
            # Effective area = original - excluded
            analyzed_block['effective_area_hectares'] = round(original_area - block_excluded_area, 4)
            
            logger.info(f"Block {i+1} analysis completed successfully")

        except Exception as block_error:
            # business: CFMG — failed analyses reset to 'pending' state for retry without blocking other blocks
            logger.error(f"Error analyzing block {i+1}: {block_error}")
            db.rollback()  # Rollback failed block transaction

            # Commit to clear transaction state for next block
            try:
                db.commit()
                logger.info(f"Transaction reset after block {i+1} error")
            except Exception as commit_error:
                logger.warning(f"Warning: Could not commit after block error: {commit_error}")

            # Continue with minimal data for this block
            analyzed_block = {**block, "analysis_error": str(block_error)[:200]}

        analyzed_blocks.append(analyzed_block)

        # ALWAYS commit after each block to ensure clean transaction state for next block
        try:
            db.commit()
            logger.info(f"Block {i+1} transaction committed")
        except Exception as commit_error:
            logger.warning(f"Warning: Could not commit after block {i+1}: {commit_error}")
            db.rollback()

    # Store analyzed blocks/compartments
    results[metadata_key] = analyzed_blocks

    # Owner rule 2026-10-10: every unit at every level (sub-blocks / sub-compartments too) is analysed on its own
    # polygon and the values kept on the unit, so each layer's attribute table shows them. Never fails the run: a
    # unit that cannot be analysed keeps its error and counts as not analysed.
    try:
        from app.services.unit_analysis_service import run_unit_analysis

        unit_summary = await run_unit_analysis(db, calculation, options)
        logger.info("[UNIT_ANALYSIS] %s", unit_summary)
        # The stored per-unit values are the single source: the lists the OP placeholders read are written from them.
        from app.services.unit_analysis_service import mirror_into_result_data, raw_by_unit_id

        mirrored = mirror_into_result_data(analyzed_blocks, raw_by_unit_id(db, calculation.id))
        logger.info("[UNIT_ANALYSIS] mirrored %d unit(s) into %s", mirrored, metadata_key)
    except Exception:  # noqa: BLE001 -- logged; the top-level analysis result above stands
        logger.exception("[UNIT_ANALYSIS] per-unit analysis failed for %s", calculation_id)
        db.rollback()

    # Aggregate potential_species from all blocks to top level
    # why: tree_models.py, tree_distribution.py, all_tree_exports.py all expect
    #      result_data['potential_species'] at top level, but analysis stores it per-block
    all_species = {}
    for block in analyzed_blocks:
        block_species = block.get('potential_species', [])
        for sp in block_species:
            sci_name = sp.get('scientific_name')
            if sci_name and sci_name not in all_species:
                all_species[sci_name] = sp
    if all_species:
        results['potential_species'] = list(all_species.values())
        results['species_count'] = len(all_species)

    # CRITICAL FIX: Preserve map creation metadata that should NOT be lost during analysis
    # These fields are set during manual map creation and must persist through analysis
    metadata_fields_to_preserve = [
        'total_blocks',           # Total number of blocks
        'creation_method',        # 'manual_digitization' or 'file_upload'
        'gps_points',            # GPS points used for boundary creation
        'gps_points_count',      # Number of GPS points
        'sub_areas',             # Sub-areas (religious, private land, etc.)
        'sub_areas_count',       # Number of sub-areas
        'excluded_area_hectares', # Total excluded area
        'processing_info'        # Block splitting metadata
    ]

    preserved_count = 0
    for field in metadata_fields_to_preserve:
        if field in existing_data:
            results[field] = existing_data[field]
            preserved_count += 1

    if preserved_count > 0:
        logger.info(f"[OK] Preserved {preserved_count} metadata fields from map creation")
        if 'sub_areas' in results:
            logger.info(f"  - Preserved {results.get('sub_areas_count', len(results['sub_areas']))} sub-areas")

    # Commit block results to clear any transaction issues
    logger.info(f"Committing block analysis results...")
    try:
        db.commit()
        logger.info("Block analysis committed successfully")
    except Exception as commit_error:
        logger.warning(f"Warning: Could not commit block results: {commit_error}")
        db.rollback()

    # Also calculate whole-area statistics for summary
    # 1. Calculate area (using UTM projection for accuracy)
    logger.info("Starting whole-forest analysis...")
    area_data = calculate_area(calculation_id, db)
    results.update(area_data)

    # 1b. Calculate whole forest extent (bounding box)
    extent_query = text("""
        SELECT
            ST_YMax(ST_Envelope(boundary_geom)) as north,
            ST_YMin(ST_Envelope(boundary_geom)) as south,
            ST_XMax(ST_Envelope(boundary_geom)) as east,
            ST_XMin(ST_Envelope(boundary_geom)) as west
        FROM calculations WHERE id = :calc_id
    """)
    whole_extent = db.execute(extent_query, {"calc_id": str(calculation_id)}).first()
    if whole_extent:
        results["whole_forest_extent"] = {
            "N": round(float(whole_extent.north), 7),
            "S": round(float(whole_extent.south), 7),
            "E": round(float(whole_extent.east), 7),
            "W": round(float(whole_extent.west), 7)
        }

    # why: raster analysis (DEM, slope, aspect, etc.) runs independently from vector and admin for parallel execution
    # 2. Raster analysis on whole boundary (if enabled)
    if should_run('run_raster_analysis'):
        logger.info(f"[ANALYSIS] Starting raster analysis for calculation {calculation_id}")
        raster_results = await analyze_rasters(calculation_id, db)
        results.update(raster_results)
        logger.info(f"[ANALYSIS] Raster analysis complete for calculation {calculation_id}")
        reset_txn(db)

    # 3. Vector analysis (if enabled)
    # why: vector proximity analysis is independent of raster — can be skipped or run separately
    if should_run('run_proximity'):
        vector_results = await analyze_vectors(calculation_id, db)
        results.update(vector_results)
        reset_txn(db)

    # 3b. Get administrative location for whole forest
    whole_geom_query = text("""
        SELECT ST_AsText(boundary_geom) as wkt
        FROM public.calculations
        WHERE id = :calc_id
    """)
    whole_geom = db.execute(whole_geom_query, {"calc_id": str(calculation_id)}).first()
    logger.info(f"[ANALYSIS] whole_geom for calculation {calculation_id}: {whole_geom}")
    if whole_geom:
        whole_location = get_administrative_location(whole_geom.wkt, db)
        # Prefix keys with "whole_" to distinguish from block-level data
        results["whole_province"] = whole_location.get("province")
        results["whole_district"] = whole_location.get("district")
        results["whole_municipality"] = whole_location.get("municipality")
        results["whole_municipality_type"] = whole_location.get("municipality_type")
        results["whole_ward"] = whole_location.get("ward")
        results["whole_watershed"] = whole_location.get("watershed")
        results["whole_major_river_basin"] = whole_location.get("major_river_basin")
        # Nepali names (from admin.admin_nepal)
        results["whole_province_ne"] = whole_location.get("province_ne")
        results["whole_division_n"] = whole_location.get("division_n")
        results["whole_subdivis_n"] = whole_location.get("subdivis_n")
        results["whole_municipality_n"] = whole_location.get("municipality_n")
        results["whole_municipality_type_nep"] = whole_location.get("municipality_type_nep")
        results["whole_ward_ne"] = whole_location.get("ward_ne")
        results["whole_physiography_ne"] = whole_location.get("physiography_ne")
        results["whole_juridiction_ne"] = whole_location.get("juridiction_ne")

    # 3c. Geology analysis for whole forest
    if whole_geom:
        whole_geology = analyze_geology_geometry(whole_geom.wkt, db)
        results["whole_geology_percentages"] = whole_geology.get("geology_percentages")

    # 3d. Access information for whole forest
    if whole_geom:
        whole_access = calculate_access_info(whole_geom.wkt, db)
        results["whole_access_info"] = whole_access.get("access_info")

    # 3e. Nearby features for whole forest
    if whole_geom:
        logger.info("Analyzing nearby features for whole forest...")
        try:
            whole_features = analyze_nearby_features(whole_geom.wkt, db)
            logger.info(f"  Nearby features returned: {list(whole_features.keys())}")
            results["whole_features_north"] = whole_features.get("features_north")
            results["whole_features_east"] = whole_features.get("features_east")
            results["whole_features_south"] = whole_features.get("features_south")
            results["whole_features_west"] = whole_features.get("features_west")
            logger.info(f"  Features - N: {whole_features.get('features_north')}, E: {whole_features.get('features_east')}, S: {whole_features.get('features_south')}, W: {whole_features.get('features_west')}")
        except Exception as e:
            logger.error(f"  ERROR analyzing nearby features: {e}")
            import traceback
            traceback.print_exc()
            db.rollback()
            results["whole_features_north"] = None
            results["whole_features_east"] = None
            results["whole_features_south"] = None
            results["whole_features_west"] = None

    # 3f. Physiography for whole forest
    if whole_geom:
        logger.info("Analyzing whole forest physiography...")
        try:
            whole_physio = analyze_physiography_geometry(whole_geom.wkt, db)
            results["whole_physiography_percentages"] = whole_physio.get("physiography_percentages")
            logger.info(f"Whole forest physiography: {whole_physio.get('physiography_percentages')}")
        except Exception as e:
            logger.error(f"Error analyzing whole forest physiography: {e}")
            db.rollback()
            results["whole_physiography_percentages"] = None

    # 3g. Ecoregion for whole forest
    if whole_geom:
        logger.info("Analyzing whole forest ecoregion...")
        try:
            whole_ecoregion = analyze_ecoregion_geometry(whole_geom.wkt, db)
            results["whole_ecoregion_percentages"] = whole_ecoregion.get("ecoregion_percentages")
            logger.info(f"Whole forest ecoregion: {whole_ecoregion.get('ecoregion_percentages')}")
        except Exception as e:
            logger.error(f"Error analyzing whole forest ecoregion: {e}")
            db.rollback()
            results["whole_ecoregion_percentages"] = None

    # 3h. NASA Forest 2020 for whole forest
    if whole_geom:
        logger.info("Analyzing whole forest NASA forest 2020...")
        try:
            whole_nasa = analyze_nasa_forest_2020_geometry(whole_geom.wkt, db)
            results["whole_nasa_forest_2020_percentages"] = whole_nasa.get("nasa_forest_2020_percentages")
            results["whole_nasa_forest_2020_dominant"] = whole_nasa.get("nasa_forest_2020_dominant")
            logger.info(f"Whole forest NASA forest 2020: {whole_nasa.get('nasa_forest_2020_percentages')}")
        except Exception as e:
            logger.error(f"Error analyzing whole forest NASA forest 2020: {e}")
            db.rollback()
            results["whole_nasa_forest_2020_percentages"] = None
            results["whole_nasa_forest_2020_dominant"] = None

    # 3i. Landcover 1984 for whole forest (Historical baseline)
    if whole_geom and should_run('run_landcover_1984'):
        logger.info("Analyzing whole forest landcover 1984...")
        try:
            whole_lc1984 = analyze_landcover_1984_geometry(whole_geom.wkt, db)
            results["landcover_1984_dominant"] = whole_lc1984.get("landcover_1984_dominant")
            results["landcover_1984_percentages"] = whole_lc1984.get("landcover_1984_percentages")
            logger.info(f"Whole forest landcover 1984 dominant: {whole_lc1984.get('landcover_1984_dominant')}")
        except Exception as e:
            logger.error(f"Error analyzing whole forest landcover 1984: {e}")
            db.rollback()
            results["landcover_1984_dominant"] = None
            results["landcover_1984_percentages"] = None

    # 3j. Hansen 2000 for whole forest (Forest classification)
    if whole_geom and should_run('run_hansen2000'):
        logger.info("Analyzing whole forest hansen 2000...")
        try:
            whole_hansen2000 = analyze_hansen2000_geometry(whole_geom.wkt, db)
            results["hansen2000_dominant"] = whole_hansen2000.get("hansen2000_dominant")
            results["hansen2000_percentages"] = whole_hansen2000.get("hansen2000_percentages")
            logger.info(f"Whole forest hansen 2000 dominant: {whole_hansen2000.get('hansen2000_dominant')}")
        except Exception as e:
            logger.error(f"Error analyzing whole forest hansen 2000: {e}")
            db.rollback()
            results["hansen2000_dominant"] = None
            results["hansen2000_percentages"] = None

    # 3k. Temperature for whole forest
    if whole_geom and should_run('run_temperature'):
        logger.info("Analyzing whole forest temperature...")
        try:
            whole_temp = analyze_temperature_geometry(whole_geom.wkt, db)
            results["temperature_mean_c"] = whole_temp.get("temperature_mean_c")
            results["temperature_min_c"] = whole_temp.get("temperature_min_c")
            results["temperature_max_c"] = whole_temp.get("temperature_max_c")  # NEW: Store max for dynamic legend
            logger.info(f"Whole forest temperature: {whole_temp.get('temperature_mean_c')}C (mean), {whole_temp.get('temperature_min_c')}C - {whole_temp.get('temperature_max_c')}C (range)")
        except Exception as e:
            logger.error(f"Error analyzing whole forest temperature: {e}")
            db.rollback()
            results["temperature_mean_c"] = None
            results["temperature_min_c"] = None
            results["temperature_max_c"] = None

    # 3l. Precipitation for whole forest
    if whole_geom and should_run('run_precipitation'):
        logger.info("Analyzing whole forest precipitation...")
        try:
            whole_precip = analyze_precipitation_geometry(whole_geom.wkt, db)
            results["precipitation_mean_mm"] = whole_precip.get("precipitation_mean_mm")
            results["precipitation_min_mm"] = whole_precip.get("precipitation_min_mm")  # NEW: Store min/max for dynamic legend
            results["precipitation_max_mm"] = whole_precip.get("precipitation_max_mm")
            logger.info(f"Whole forest precipitation: {whole_precip.get('precipitation_mean_mm')} mm/year (mean), {whole_precip.get('precipitation_min_mm')} - {whole_precip.get('precipitation_max_mm')} mm (range)")
        except Exception as e:
            logger.error(f"Error analyzing whole forest precipitation: {e}")
            db.rollback()
            results["precipitation_mean_mm"] = None
            results["precipitation_min_mm"] = None
            results["precipitation_max_mm"] = None

    # 3m. Min Temperature (Coldest Month) for whole forest
    if whole_geom and should_run('run_temperature'):
        logger.info("Analyzing whole forest min temperature (coldest month)...")
        try:
            whole_min_temp = analyze_min_temp_coldest_geometry(whole_geom.wkt, db)
            results["min_temp_coldest_mean_c"] = whole_min_temp.get("min_temp_coldest_mean_c")
            results["min_temp_coldest_min_c"] = whole_min_temp.get("min_temp_coldest_min_c")
            results["min_temp_coldest_max_c"] = whole_min_temp.get("min_temp_coldest_max_c")
            logger.info(f"Whole forest min temp (coldest month): {whole_min_temp.get('min_temp_coldest_mean_c')}C (mean), {whole_min_temp.get('min_temp_coldest_min_c')}C - {whole_min_temp.get('min_temp_coldest_max_c')}C (range)")
        except Exception as e:
            logger.error(f"Error analyzing whole forest min temp coldest: {e}")
            db.rollback()
            results["min_temp_coldest_mean_c"] = None
            results["min_temp_coldest_min_c"] = None
            results["min_temp_coldest_max_c"] = None

    # 3n. Soil texture distribution (USDA 12-class %) for whole forest — ND-3
    if whole_geom:
        logger.info("Analyzing whole forest soil texture distribution...")
        try:
            soil_zonal = analyze_soil_texture_zonal(whole_geom.wkt, db)
            if soil_zonal:
                results["soil_percentages"] = soil_zonal["soil_percentages"]
                results["soil_dominant_type"] = soil_zonal["soil_dominant_type"]
                logger.info(f"Whole forest soil texture: {soil_zonal['soil_percentages']}")
        except Exception as e:
            logger.error(f"Error analyzing whole forest soil texture distribution: {e}")
            db.rollback()

    # 4. Administrative boundaries
    admin_results = await analyze_admin_boundaries(calculation_id, db)
    results.update(admin_results)

    processing_time = int(time.time() - start_time)

    # Commit all analysis results to ensure clean transaction state
    logger.info("Committing final analysis results...")
    try:
        db.commit()
        logger.info("Analysis transaction committed successfully")
    except Exception as commit_error:
        logger.warning(f"Warning: Could not commit analysis: {commit_error}")
        db.rollback()

    # Block geometry/identity and per-block analysis values just changed. The
    # pre-rendered map PNGs under uploads/maps_cache/<calc_id>/ are keyed by
    # calc_id + spec_hash + dpi only, so without this a re-analysis keeps
    # serving the old images (e.g. a stale compartment-wise map). Best-effort.
    try:
        from app.services.management_plan_docx.plan_map_service import clear_map_cache

        clear_map_cache(calculation_id=calculation_id)
    except Exception:  # noqa: BLE001 -- a cache-clear failure must not fail analysis
        logger.warning(
            "Could not clear rendered-map cache for calc %s", calculation_id, exc_info=True
        )

    # The RUSLE soil-loss grid (uploads/soil_erosion_cache/<calc_id>/) is keyed
    # by calc geometry + params; boundary/block edits change it. Best-effort.
    try:
        from app.services.operational_plan.soil_erosion import clear_cache as _se_clear

        _se_clear(calculation_id)
    except Exception:  # noqa: BLE001 -- a cache-clear failure must not fail analysis
        logger.warning(
            "Could not clear soil-erosion cache for calc %s", calculation_id, exc_info=True
        )

    # The LSI / FS hazard grids (uploads/hazard_vuln_cache/<calc_id>/) are also
    # keyed by calc geometry + params. Best-effort.
    try:
        from app.services.operational_plan.landslide_susceptibility import (
            clear_cache as _hv_clear,
        )

        _hv_clear(calculation_id)
    except Exception:  # noqa: BLE001 -- a cache-clear failure must not fail analysis
        logger.warning(
            "Could not clear hazard-vuln cache for calc %s", calculation_id, exc_info=True
        )

    # result_data['sfm'] (Sustainable FM classification) is derived from the
    # blocks + inventory that just changed. Drop it so the next get_sfm rebuilds.
    try:
        from app.services.sustainable_fm.sfm_service import invalidate_sfm

        invalidate_sfm(calculation_id, db)
    except Exception:  # noqa: BLE001 -- an invalidation failure must not fail analysis
        logger.warning(
            "Could not invalidate SFM block for calc %s", calculation_id, exc_info=True
        )

    return results, processing_time


async def analyze_block_geometry(geojson_geometry: Dict, calculation_id: UUID, db: Session, options: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    """
    Analyze a single block's geometry

    Args:
        geojson_geometry: Block geometry in GeoJSON format
        calculation_id: UUID of parent calculation (for context)
        db: Database session
        options: Dict of boolean flags to enable/disable specific analyses

    Returns:
        Dict with analysis results for this block
    """
    # Default options: run everything if not specified
    if options is None:
        options = {}

    # Helper function to check if analysis should run
    def should_run(analysis_name: str) -> bool:
        # First check if raster analysis is globally disabled
        if analysis_name != 'run_raster_analysis' and not options.get('run_raster_analysis', True):
            return False
        return options.get(analysis_name, True)  # Default True for backward compatibility
    import json

    # Convert GeoJSON to WKT for PostGIS
    geojson_str = json.dumps(geojson_geometry)

    try:
        # Create a temporary geometry from GeoJSON
        geom_query = text("""
            SELECT ST_AsText(ST_MakeValid(ST_GeomFromGeoJSON(:geojson))) as wkt
        """)
        wkt_result = db.execute(geom_query, {"geojson": geojson_str}).first()
        block_wkt = wkt_result.wkt
    except Exception as e:
        logger.error(f"Error converting GeoJSON to WKT: {e}")
        logger.info(f"GeoJSON string (first 500 chars): {geojson_str[:500]}")
        # CRITICAL: Rollback the failed transaction before raising
        db.rollback()
        raise ValueError(f"Invalid geometry format: {str(e)}")

    block_results = {}
    failed_steps: List[str] = []

    def _heal(step_name: str) -> None:
        """A failed statement aborts the transaction and every later step would fail with it. The analysers swallow their
        own SQL errors, so detect the aborted state here, roll back (everything is read-only) and remember which step it was."""
        try:
            db.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 -- the aborted transaction IS the signal; rolled back and recorded below
            db.rollback()
            failed_steps.append(step_name)

    def _step(fn, *args):
        _heal(f"before:{fn.__name__}")
        out = fn(*args)
        _heal(fn.__name__)
        return out

    # Store WKT for future reanalysis
    block_results['wkt'] = block_wkt

    # business: CFMG — block-level analysis iterates sub-analyzers in dependency order (elevation → slope → aspect → canopy → biomass → type → species)
    # Calculate bounding box extent for this block
    extent_query = text("""
        SELECT
            ST_YMax(ST_Envelope(ST_GeomFromText(:wkt, 4326))) as north,
            ST_YMin(ST_Envelope(ST_GeomFromText(:wkt, 4326))) as south,
            ST_XMax(ST_Envelope(ST_GeomFromText(:wkt, 4326))) as east,
            ST_XMin(ST_Envelope(ST_GeomFromText(:wkt, 4326))) as west
    """)
    extent_result = db.execute(extent_query, {"wkt": block_wkt}).first()
    if extent_result:
        block_results["extent"] = {
            "N": round(float(extent_result.north), 7),
            "S": round(float(extent_result.south), 7),
            "E": round(float(extent_result.east), 7),
            "W": round(float(extent_result.west), 7)
        }

    # Run raster analyses conditionally based on options
    # 1. DEM - Elevation
    if should_run('run_elevation'):
        dem_results = _step(analyze_dem_geometry, block_wkt, db)
        block_results.update(dem_results)

    # 2. Slope
    if should_run('run_slope'):
        slope_results = _step(analyze_slope_geometry, block_wkt, db)
        block_results.update(slope_results)

    # 3. Aspect
    if should_run('run_aspect'):
        aspect_results = _step(analyze_aspect_geometry, block_wkt, db)
        block_results.update(aspect_results)

    # 4. Canopy Height
    if should_run('run_canopy'):
        canopy_results = _step(analyze_canopy_height_geometry, block_wkt, db)
        block_results.update(canopy_results)

    # 5. AGB (Biomass)
    if should_run('run_biomass'):
        agb_results = _step(analyze_agb_geometry, block_wkt, db)
        block_results.update(agb_results)

    # 6. Forest Health
    if should_run('run_forest_health'):
        health_results = _step(analyze_forest_health_geometry, block_wkt, db)
        block_results.update(health_results)

    # 7. Forest Type
    if should_run('run_forest_type'):
        forest_type_results = _step(analyze_forest_type_geometry, block_wkt, db)
        block_results.update(forest_type_results)

        # 7.1 Potential Tree Species (based on forest type)
        if forest_type_results.get('forest_type_percentages'):
            species_results = analyze_potential_tree_species(
                forest_type_results['forest_type_percentages'],
                db
            )
            block_results.update(species_results)

    # 7A. Historical Land Cover (1984 - Vector)
    if should_run('run_landcover_1984'):
        landcover_1984_results = _step(analyze_landcover_1984_geometry, block_wkt, db)
        block_results.update(landcover_1984_results)

    # 7B. Hansen 2000 Forest Classification (Raster)
    if should_run('run_hansen2000'):
        hansen2000_results = _step(analyze_hansen2000_geometry, block_wkt, db)
        block_results.update(hansen2000_results)

    # 8. Land Cover (ESA WorldCover - Current)
    if should_run('run_landcover'):
        landcover_results = _step(analyze_landcover_geometry, block_wkt, db)
        block_results.update(landcover_results)

    # 9. Forest Loss
    if should_run('run_forest_loss'):
        loss_results = _step(analyze_forest_loss_geometry, block_wkt, db)
        block_results.update(loss_results)

    # 10. Forest Gain
    if should_run('run_forest_gain'):
        gain_results = _step(analyze_forest_gain_geometry, block_wkt, db)
        block_results.update(gain_results)

    # 11. Fire Loss
    if should_run('run_fire_loss'):
        fire_results = _step(analyze_fire_loss_geometry, block_wkt, db)
        block_results.update(fire_results)

    # 12. Temperature
    if should_run('run_temperature'):
        temp_results = _step(analyze_temperature_geometry, block_wkt, db)
        block_results.update(temp_results)

    # 13. Precipitation
    if should_run('run_precipitation'):
        precip_results = _step(analyze_precipitation_geometry, block_wkt, db)
        block_results.update(precip_results)

    # 13b. Min Temperature (Coldest Month)
    if should_run('run_temperature'):
        min_temp_results = _step(analyze_min_temp_coldest_geometry, block_wkt, db)
        block_results.update(min_temp_results)

    # 14. Soil Texture
    if should_run('run_soil'):
        soil_results = _step(analyze_soil_geometry, block_wkt, db)
        block_results.update(soil_results)

    # 15. Administrative Location (Province, District, Municipality, Ward, Watershed)
    location_results = _step(get_administrative_location, block_wkt, db)
    block_results.update(location_results)

    # 16. Geology Analysis
    geology_results = _step(analyze_geology_geometry, block_wkt, db)
    block_results.update(geology_results)

    # 17. Access Information
    access_results = _step(calculate_access_info, block_wkt, db)
    block_results.update(access_results)

    # 18. (removed 2026-10-10, owner: per-unit nearby features are not needed; the whole-forest boundary features stay.)

    # 19. Physiography Analysis
    logger.info("  Analyzing physiography...")
    try:
        physio_results = _step(analyze_physiography_geometry, block_wkt, db)
        block_results.update(physio_results)
        logger.info(f"  Physiography analysis complete: {list(physio_results.keys())}")
    except Exception as e:
        logger.error(f"  ERROR in physiography analysis: {e}")
        block_results.update({'physiography_percentages': None})

    # 20. Ecoregion Analysis
    logger.info("  Analyzing ecoregion...")
    try:
        ecoregion_results = _step(analyze_ecoregion_geometry, block_wkt, db)
        block_results.update(ecoregion_results)
        logger.info(f"  Ecoregion analysis complete: {list(ecoregion_results.keys())}")
    except Exception as e:
        logger.error(f"  ERROR in ecoregion analysis: {e}")
        block_results.update({'ecoregion_percentages': None})

    # 21. NASA Forest 2020 Classification
    logger.info("  Analyzing NASA forest 2020...")
    try:
        nasa_forest_results = _step(analyze_nasa_forest_2020_geometry, block_wkt, db)
        block_results.update(nasa_forest_results)
        logger.info(f"  NASA forest 2020 analysis complete: {list(nasa_forest_results.keys())}")
    except Exception as e:
        logger.error(f"  ERROR in NASA forest 2020 analysis: {e}")
        block_results.update({
            'nasa_forest_2020_percentages': None,
            'nasa_forest_2020_dominant': None
        })

    if failed_steps:
        block_results['analysis_failed_steps'] = sorted({s.replace('before:', '') for s in failed_steps})
    return block_results


def calculate_area(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """
    Calculate area using appropriate UTM projection

    Returns total area, excluded area (private land), and effective forest area
    """
    # Get geometry centroid to determine UTM zone
    # business: CFMG requires geodesic area for official records — using UTM projection for accuracy
    # constraint: Nepal spans UTM zones 44 and 45, split at longitude 84°E
    query = text("""
        SELECT
            ST_X(ST_Centroid(boundary_geom)) as lon,
            ST_Y(ST_Centroid(boundary_geom)) as lat
        FROM public.calculations
        WHERE id = :calc_id
    """)

    result = db.execute(query, {"calc_id": str(calculation_id)}).first()
    lon = result.lon

    # Determine UTM zone (32644 for western Nepal, 32645 for eastern)
    utm_srid = 32645 if lon > 84 else 32644

    # Calculate total boundary area in UTM projection
    area_query = text(f"""
        SELECT
            ST_Area(ST_Transform(boundary_geom, {utm_srid})) as area_sqm,
            ST_Area(ST_Transform(boundary_geom, {utm_srid})) / {SQM_PER_HA} as area_hectares
        FROM public.calculations
        WHERE id = :calc_id
    """)

    area_result = db.execute(area_query, {"calc_id": str(calculation_id)}).first()
    total_area_hectares = round(area_result.area_hectares, 4)

    # Get excluded area from result_data (private land)
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    excluded_area_hectares = 0
    if calculation and calculation.result_data:
        excluded_area_hectares = calculation.result_data.get("excluded_area_hectares", 0)

    # Calculate effective forest area (total - excluded)
    effective_area_hectares = round(total_area_hectares - excluded_area_hectares, 4)

    # NOTE: results in hectares, rounded to 2 decimal places for CFMG compliance
    return {
        "area_sqm": round(area_result.area_sqm, 2),
        "area_hectares": total_area_hectares,  # Total boundary area
        "excluded_area_hectares": round(excluded_area_hectares, 4),  # Private land area
        "effective_area_hectares": effective_area_hectares,  # Actual forest area
        "utm_zone": utm_srid
    }


async def analyze_rasters(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """
    Analyze all 16 raster datasets from rasters schema

    Performs zonal statistics for each raster layer
    """
    results = {}

    # 1. DEM - Elevation statistics
    dem_results = analyze_dem(calculation_id, db)
    results.update(dem_results)
    reset_txn(db)

    # 2. Slope - Classification percentages
    slope_results = analyze_slope(calculation_id, db)
    results.update(slope_results)
    reset_txn(db)

    # 3. Aspect - Directional percentages
    aspect_results = analyze_aspect(calculation_id, db)
    results.update(aspect_results)
    reset_txn(db)

    # 4. Canopy Height - Forest structure
    canopy_results = analyze_canopy_height(calculation_id, db)
    results.update(canopy_results)
    reset_txn(db)

    # 5. Above-ground Biomass (AGB)
    agb_results = analyze_agb(calculation_id, db)
    results.update(agb_results)
    reset_txn(db)

    # 6. Forest Health
    health_results = analyze_forest_health(calculation_id, db)
    results.update(health_results)
    reset_txn(db)

    # 7. Forest Type
    forest_type_results = analyze_forest_type(calculation_id, db)
    results.update(forest_type_results)
    reset_txn(db)

    # 7.1 Potential Tree Species (based on forest type)
    if forest_type_results.get('forest_type_percentages'):
        species_results = analyze_potential_tree_species(
            forest_type_results['forest_type_percentages'],
            db
        )
        results.update(species_results)
    reset_txn(db)

    # 8. ESA WorldCover - Land cover
    esa_results = analyze_esa_worldcover(calculation_id, db)
    results.update(esa_results)
    reset_txn(db)

    # 9. Climate - Temperature and Precipitation
    climate_results = analyze_climate(calculation_id, db)
    results.update(climate_results)
    reset_txn(db)

    # 10. Forest Loss and Gain
    change_results = analyze_forest_change(calculation_id, db)
    results.update(change_results)
    reset_txn(db)

    # 11. Soil properties (RE-ENABLED with optimizations)
    soil_results = analyze_soil(calculation_id, db)
    results.update(soil_results)
    reset_txn(db)

    return results


def analyze_dem(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """Analyze DEM raster - min, max, mean elevation

    DEM NoData value is -32768 but not registered in PostGIS metadata.
    We must explicitly exclude it by filtering pixel values.
    """
    # constraint: NASA SRTM 30m DEM — Void-filled, 1 arc-second global elevation data
    try:
        query = text("""
            WITH clipped_raster AS (
                SELECT ST_Clip(rast, boundary_geom) as rast
                FROM rasters.dem, public.calculations
                WHERE calculations.id = :calc_id
                  AND ST_Intersects(rast, boundary_geom)
                LIMIT 1
            ),
            pixel_values AS (
                SELECT (ST_PixelAsPolygons(rast)).val as elevation
                FROM clipped_raster
            )
            SELECT
                MIN(elevation) as elevation_min,
                MAX(elevation) as elevation_max,
                AVG(elevation) as elevation_mean
            FROM pixel_values
            WHERE elevation > -32000  -- Exclude NoData values (-32768)
              AND elevation >= 0       -- Nepal minimum elevation
              AND elevation <= 9000    -- Nepal maximum elevation (Mt. Everest 8848m + margin)
        """)

        result = db.execute(query, {"calc_id": str(calculation_id)}).first()

        if result and result.elevation_mean is not None:
            return {
                "elevation_min_m": round(result.elevation_min, 1) if result.elevation_min else None,
                "elevation_max_m": round(result.elevation_max, 1) if result.elevation_max else None,
                "elevation_mean_m": round(result.elevation_mean, 1) if result.elevation_mean else None,
            }
    except Exception as e:
        logger.error(f"Error analyzing DEM: {e}")

    return {"elevation_min_m": None, "elevation_max_m": None, "elevation_mean_m": None}


def analyze_slope(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """
    Analyze slope raster - categorical codes (0-4)
    Returns percentages, dominant class, and min/max codes for dynamic legend generation

    Slope classes from raster:
    0 = No data / Water (excluded from analysis)
    1 = <19° (Gentle)
    2 = 19-31° (Moderate)
    3 = 31-45° (Steep)
    4 = >45° (Very Steep)
    (the अनुसूची-१ bands; core/constants.SLOPE_CLASS_BANDS is the single definition)
    """
    try:
        # raster codes 1-4: 1=gentle (<19°), 2=moderate (19-31°), 3=steep (31-45°), 4=very steep (>45°)
        # Mapping from raster categorical codes to class names
        slope_map = {
            1: "gentle",
            2: "moderate",
            3: "steep",
            4: "very_steep"
        }

        query = text("""
            SELECT
                (pvc).value as slope_code,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, boundary_geom)) as pvc
                FROM rasters.slope_regulation, public.calculations
                WHERE calculations.id = :calc_id
                  AND ST_Intersects(rast, boundary_geom)
            ) as subquery
            WHERE (pvc).value IS NOT NULL
              AND (pvc).value > 0
              AND (pvc).value <= 4
            GROUP BY slope_code
        """)

        results = db.execute(query, {"calc_id": str(calculation_id)}).fetchall()

        if not results:
            return {
                "slope_dominant_class": None,
                "slope_percentages": {},
                "slope_min_code": None,
                "slope_max_code": None
            }

        total_pixels = sum(r.pixel_count for r in results)
        slope_percentages = {}
        dominant_class = None
        max_percentage = 0

        # Track which slope codes are present
        slope_codes_present = []

        for r in results:
            code = int(r.slope_code)
            if code in slope_map:
                percentage = (r.pixel_count / total_pixels * 100) if total_pixels > 0 else 0
                class_name = slope_map[code]
                slope_percentages[class_name] = round(percentage, 2)
                slope_codes_present.append(code)

                if percentage > max_percentage:
                    max_percentage = percentage
                    dominant_class = class_name

        # Calculate min/max slope codes for dynamic legend filtering
        slope_min_code = min(slope_codes_present) if slope_codes_present else None
        slope_max_code = max(slope_codes_present) if slope_codes_present else None

        return {
            "slope_dominant_class": dominant_class,
            "slope_percentages": slope_percentages,
            "slope_min_code": slope_min_code,  # NEW: For dynamic legend
            "slope_max_code": slope_max_code   # NEW: For dynamic legend
        }
    except Exception as e:
        logger.error(f"Error analyzing slope: {e}")

    return {
        "slope_dominant_class": None,
        "slope_percentages": {},
        "slope_min_code": None,
        "slope_max_code": None
    }


def analyze_aspect(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """Analyze aspect raster - categorical codes (1-8)

    Aspect classes from raster:
    0 = No data (excluded from analysis)
    1 = N (337.5° - 22.5°)
    2 = NE (22.5° - 67.5°)
    3 = E (67.5° - 112.5°)
    4 = SE (112.5° - 157.5°)
    5 = S (157.5° - 202.5°)
    6 = SW (202.5° - 247.5°)
    7 = W (247.5° - 292.5°)
    8 = NW (292.5° - 337.5°)
    """
    try:
        # constraint: 8-direction aspect bins at 45° intervals (N, NE, E, SE, S, SW, W, NW)
        # Mapping from raster categorical codes to direction names
        aspect_map = {
            1: "N",
            2: "NE",
            3: "E",
            4: "SE",
            5: "S",
            6: "SW",
            7: "W",
            8: "NW"
        }

        query = text("""
            SELECT
                (pvc).value as aspect_code,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, boundary_geom)) as pvc
                FROM rasters.aspect, public.calculations
                WHERE calculations.id = :calc_id
                  AND ST_Intersects(rast, boundary_geom)
            ) as subquery
            WHERE (pvc).value IS NOT NULL AND (pvc).value BETWEEN 1 AND 8
            GROUP BY aspect_code
        """)

        results = db.execute(query, {"calc_id": str(calculation_id)}).fetchall()

        if not results:
            return {"aspect_dominant": None, "aspect_percentages": {}}

        total_pixels = sum(r.pixel_count for r in results)
        aspect_percentages = {}
        dominant_aspect = None
        max_percentage = 0

        for r in results:
            code = int(r.aspect_code)
            if code in aspect_map:
                percentage = (r.pixel_count / total_pixels * 100) if total_pixels > 0 else 0
                direction = aspect_map[code]
                aspect_percentages[direction] = round(percentage, 2)

                # Track dominant aspect
                if percentage > max_percentage:
                    max_percentage = percentage
                    dominant_aspect = direction

        return {
            "aspect_dominant": dominant_aspect,
            "aspect_percentages": aspect_percentages
        }
    except Exception as e:
        logger.error(f"Error analyzing aspect: {e}")

    return {"aspect_dominant": None, "aspect_percentages": {}}


CANOPY_TIF_PATH = r"D:\forest_management\canopy_height5m.tif"

def _canopy_from_rasterio(geometry_geojson: dict) -> Dict[str, Any]:
    """Analyze canopy height using rasterio directly from TIF file.
    Classifies pixels into: non_forest (1m), regeneration (2-5m),
    pole_trees (6-15m), tree (>15m).
    Value 0 = source NoData (uint8 raster) — excluded from analysis."""
    # constraint: canopy height classes follow CFMG forest structure classification thresholds
    try:
        with rasterio.open(CANOPY_TIF_PATH) as src:
            out_image, _ = rio_mask(src, [geometry_geojson], crop=True)
            data = out_image[0]
            if hasattr(data, 'mask'):
                valid = data.compressed()
            else:
                valid = data.flatten()
            valid = valid[(valid > 0) & (valid <= 50)]

            if len(valid) == 0:
                return {"canopy_dominant_class": None, "canopy_percentages": {}, "canopy_mean_m": None, "canopy_min_m": None, "canopy_max_m": None}

            non_forest = int((valid == 1).sum())
            bush = int(((valid >= 2) & (valid <= 5)).sum())
            pole = int(((valid >= 6) & (valid <= 15)).sum())
            tree = int((valid > 15).sum())
            total = len(valid)

            percentages = {}
            if non_forest > 0: percentages['non_forest'] = round(non_forest / total * 100, 2)
            if bush > 0: percentages['regeneration'] = round(bush / total * 100, 2)
            if pole > 0: percentages['pole_trees'] = round(pole / total * 100, 2)
            if tree > 0: percentages['tree'] = round(tree / total * 100, 2)

            dominant = max(percentages, key=percentages.get) if percentages else None
            canopy_mean = round(float(valid.mean()), 1) if len(valid) > 0 else 0
            canopy_min = round(float(valid.min()), 1) if len(valid) > 0 else 0
            canopy_max = round(float(valid.max()), 1) if len(valid) > 0 else 0

            return {
                "canopy_dominant_class": dominant,
                "canopy_percentages": percentages,
                "canopy_mean_m": canopy_mean,
                "canopy_min_m": canopy_min,
                "canopy_max_m": canopy_max
            }
    except Exception as e:
        logger.error(f"Error in _canopy_from_rasterio: {e}")
        return {"canopy_dominant_class": None, "canopy_percentages": {}, "canopy_mean_m": None, "canopy_min_m": None, "canopy_max_m": None}


def analyze_canopy_height(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """Analyze canopy height raster - reads directly from TIF file via rasterio"""
    try:
        geojson_query = text("""
            SELECT ST_AsGeoJSON(boundary_geom) as geojson
            FROM public.calculations
            WHERE id = :calc_id
        """)
        row = db.execute(geojson_query, {"calc_id": str(calculation_id)}).first()
        if not row or not row.geojson:
            return {"canopy_dominant_class": None, "canopy_percentages": {}, "canopy_mean_m": None, "canopy_min_m": None, "canopy_max_m": None}

        geometry = json.loads(row.geojson)
        return _canopy_from_rasterio(geometry)
    except Exception as e:
        logger.error(f"Error analyzing canopy height: {e}")
        return {"canopy_dominant_class": None, "canopy_percentages": {}, "canopy_mean_m": None, "canopy_min_m": None, "canopy_max_m": None}


def analyze_agb(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """
    Analyze above-ground biomass for whole forest
    Returns mean, min, max, total, and carbon stock for dynamic legend generation
    """
    try:
        query = text("""
            SELECT
                (stats).mean as agb_mean,
                (stats).min as agb_min,
                (stats).max as agb_max,
                (stats).sum as agb_total
            FROM (
                SELECT ST_SummaryStats(
                    ST_Clip(rast, 1, boundary_geom)
                ) as stats
                FROM rasters.agb_2022_nepal, public.calculations
                WHERE calculations.id = :calc_id
                  AND ST_Intersects(rast, boundary_geom)
                LIMIT 1
            ) as subquery
        """)

        result = db.execute(query, {"calc_id": str(calculation_id)}).first()

        if result and result.agb_mean and result.agb_mean > 0:
            # Convert AGB to carbon (carbon is approximately 50% of AGB)
            # business: IPCC 2006 Guidelines — carbon fraction of dry biomass = 0.47 (using 0.5 as conservative estimate)
            carbon_stock = result.agb_total * 0.5 if result.agb_total and result.agb_total > 0 else 0

            return {
                "agb_mean_mg_ha": round(result.agb_mean, 2) if result.agb_mean > 0 else 0,
                "agb_min_mg_ha": round(result.agb_min, 2) if result.agb_min and result.agb_min > 0 else 0,
                "agb_max_mg_ha": round(result.agb_max, 2) if result.agb_max and result.agb_max > 0 else 0,
                "agb_total_mg": round(result.agb_total, 2) if result.agb_total and result.agb_total > 0 else 0,
                "carbon_stock_mg": round(carbon_stock, 2) if carbon_stock > 0 else 0
            }
    except Exception as e:
        logger.error(f"Error analyzing AGB: {e}")

    return {
        "agb_mean_mg_ha": None,
        "agb_min_mg_ha": None,
        "agb_max_mg_ha": None,
        "agb_total_mg": None,
        "carbon_stock_mg": None
    }


def analyze_forest_health(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """Analyze forest health classes - categorical codes (1-5)

    Forest health classes (Sentinel-2 NDVI):
    1 = Stressed (NDVI < 0.2)
    2 = Poor (NDVI 0.2 - 0.4)
    3 = Moderate (NDVI 0.4 - 0.6)
    4 = Healthy (NDVI 0.6 - 0.8)
    5 = Excellent (NDVI > 0.8)
    """
    # constraint: Sentinel-2 NDVI-based forest health classification — 5-class system from Sentinel Hub
    try:
        # Correct mapping from table comments
        health_labels = {
            1: "stressed",
            2: "poor",
            3: "moderate",
            4: "healthy",
            5: "excellent"
        }

        query = text("""
            SELECT
                (pvc).value as health_class,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, boundary_geom)) as pvc
                FROM rasters.nepal_forest_health, public.calculations
                WHERE calculations.id = :calc_id
                  AND ST_Intersects(rast, boundary_geom)
            ) as subquery
            WHERE (pvc).value IS NOT NULL AND (pvc).value BETWEEN 1 AND 5
            GROUP BY health_class
        """)

        results = db.execute(query, {"calc_id": str(calculation_id)}).fetchall()

        if not results:
            return {"forest_health_dominant": None, "forest_health_percentages": {}}

        total_pixels = sum(r.pixel_count for r in results)
        health_percentages = {}
        dominant_class = None
        max_percentage = 0

        for r in results:
            percentage = (r.pixel_count / total_pixels * 100) if total_pixels > 0 else 0
            class_label = health_labels.get(int(r.health_class), "unknown")
            health_percentages[class_label] = round(percentage, 2)

            if percentage > max_percentage:
                max_percentage = percentage
                dominant_class = class_label

        return {
            "forest_health_dominant": dominant_class,
            "forest_health_percentages": health_percentages
        }
    except Exception as e:
        logger.error(f"Error analyzing forest health: {e}")

    return {"forest_health_dominant": None, "forest_health_percentages": {}}


def analyze_forest_type(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """Analyze forest type distribution - categorical codes (1-26)

    Forest type classes (FRTC, Kathmandu):
    1 = Shorea robusta Forest
    2 = Alnus nepalensis Forest
    3 = Schima-Castanopsis Forest
    4 = Quercus semecarpifolia Forest
    5 = Larix/Abies spectabilis Forest
    6 = Pinus wallichiana-Tsuga dumosa Forest
    7 = Plantation (Pinus-Eucalyptus) Forest
    8 = Ficus-Other Tropical Riverine Forest
    9 = Tropical Mixed Broadleaved Forest
    10 = Quercus-Pinus Forest
    11 = Abies spectabilis Forest
    12 = Pinus roxburghii-Mixed Broadleaved Forest
    13 = Pinus wallichiana Forest
    14 = Warm Temperate Mixed Broadleaved Forest
    15 = Upper Temperate Quercus Forest
    16 = Rhododendron arboreum Forest
    17 = Temperate Rhododendron Mixed Broadleaved Forest
    18 = Dalbergia sissoo-Senegelia catechu Forest
    19 = Terminalia-Tropical Mixed Broadleaved Forest
    20 = Temperate Mixed Broadleaved Forest
    21 = Tropical Deciduous Indigenous Riverine Forest
    22 = Tropical Riverine Forest
    23 = Lower Temperate Mixed robusta Forest
    24 = Pinus roxburghii-Shorea robusta Forest
    25 = Lower Temperate Pinus roxburghii-Quercus Forest
    26 = Data Not Available
    """
    try:
        # business: CFMG forest type classification based on crown cover % — dense >70%, moderate 40-70%, open 10-40%
        # why: raster pixel values map to forest_types.pixel_value; LEFT JOIN ensures
        #      code 26 (no DB entry) falls back to "Data Not Available"
        query = text("""
            SELECT
                (pvc).value as forest_type_code,
                COALESCE(ft.forest_type_name, 'Data Not Available') as forest_type_name,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, boundary_geom)) as pvc
                FROM rasters.forest_type, public.calculations
                WHERE calculations.id = :calc_id
                  AND ST_Intersects(rast, boundary_geom)
            ) as subquery
            LEFT JOIN forest_types ft ON ft.pixel_value = (pvc).value
            WHERE (pvc).value IS NOT NULL AND (pvc).value BETWEEN 1 AND 26
            GROUP BY forest_type_code, forest_type_name
            ORDER BY pixel_count DESC
        """)

        results = db.execute(query, {"calc_id": str(calculation_id)}).fetchall()

        if not results:
            return {"forest_type_dominant": None, "forest_type_percentages": {}}

        total_pixels = sum(r.pixel_count for r in results)
        forest_type_percentages = {}
        dominant_type = None
        max_percentage = 0

        for r in results:
            code = int(r.forest_type_code)
            type_name = r.forest_type_name
            percentage = (r.pixel_count / total_pixels * 100) if total_pixels > 0 else 0
            forest_type_percentages[type_name] = round(percentage, 2)

            # Find dominant (excluding "Data Not Available" if possible)
            if type_name != 'Data Not Available' and percentage > max_percentage:
                max_percentage = percentage
                dominant_type = type_name
            elif type_name == 'Data Not Available' and dominant_type is None:
                dominant_type = type_name

        return {
            "forest_type_dominant": dominant_type,
            "forest_type_percentages": forest_type_percentages
        }
    except Exception as e:
        logger.error(f"Error analyzing forest type: {e}")

    return {"forest_type_dominant": None, "forest_type_percentages": {}}


def analyze_esa_worldcover(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """Analyze ESA WorldCover land cover - categorical codes

    Land cover classes (ESA/WorldCover/v200):
    10 = Tree cover
    20 = Shrubland
    30 = Grassland
    40 = Cropland
    50 = Built-up
    60 = Bare/sparse vegetation
    70 = Snow and ice
    80 = Permanent water bodies
    90 = Herbaceous wetland
    95 = Mangroves
    100 = Moss and lichen
"""
    # constraint: ESA WorldCover 2020 10m resolution — global land cover at 10m
    try:
        # SSOT: app/core/forest_types.py → ESA_WORLD_COVER
        query = text("""
            SELECT
                (pvc).value as landcover_code,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, boundary_geom)) as pvc
                FROM rasters.esa_world_cover, public.calculations
                WHERE calculations.id = :calc_id
                  AND ST_Intersects(rast, boundary_geom)
            ) as subquery
            WHERE (pvc).value IS NOT NULL AND (pvc).value > 0
            GROUP BY landcover_code
            ORDER BY pixel_count DESC
        """)

        results = db.execute(query, {"calc_id": str(calculation_id)}).fetchall()

        if not results:
            return {"landcover_dominant": None, "landcover_percentages": {}}

        total_pixels = sum(r.pixel_count for r in results)
        landcover_percentages = {}
        dominant_cover = None
        max_percentage = 0

        for r in results:
            code = int(r.landcover_code)
            if code in ESA_WORLD_COVER:
                percentage = (r.pixel_count / total_pixels * 100) if total_pixels > 0 else 0
                cover_name = ESA_WORLD_COVER[code].name_en
                landcover_percentages[cover_name] = round(percentage, 2)

                if percentage > max_percentage:
                    max_percentage = percentage
                    dominant_cover = cover_name

        return {
            "landcover_dominant": dominant_cover,
            "landcover_percentages": landcover_percentages
        }

    except Exception as e:
        logger.error(f"Error analyzing ESA WorldCover: {e}")
    except Exception as e:
        logger.error(f"Error analyzing ESA WorldCover: {e}")

    return {"landcover_dominant": None, "landcover_percentages": {}}


def analyze_climate(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """Analyze climate data (temperature and precipitation)

    WorldClim data:
    - annual_mean_temperature: Bio01, scale = 0.1, unit = deg C
    - min_temp_coldest_month: Bio06, scale = 0.1, unit = deg C
    - annual_precipitation: Bio12, unit = mm
    """
    # constraint: CHELSA bioclimatic data 1km resolution — WorldClim v2.1 at 30 arc-seconds
    try:
        # Temperature analysis (annual mean and min)
        temp_query = text("""
            SELECT
                (amt_stats).mean * 0.1 as temp_mean_c,
                (mint_stats).mean * 0.1 as temp_min_c
            FROM (
                SELECT
                    ST_SummaryStats(ST_Clip(amt.rast, calc.boundary_geom), 1, true) as amt_stats,
                    ST_SummaryStats(ST_Clip(mint.rast, calc.boundary_geom), 1, true) as mint_stats
                FROM rasters.annual_mean_temperature amt,
                     rasters.min_temp_coldest_month mint,
                     public.calculations calc
                WHERE calc.id = :calc_id
                  AND ST_Intersects(amt.rast, calc.boundary_geom)
                  AND ST_Intersects(mint.rast, calc.boundary_geom)
                LIMIT 1
            ) as subquery
        """)

        temp_result = db.execute(temp_query, {"calc_id": str(calculation_id)}).first()

        # Precipitation analysis
        precip_query = text("""
            SELECT
                (stats).mean as precip_mean_mm
            FROM (
                SELECT ST_SummaryStats(
                    ST_Clip(rast, boundary_geom),
                    1,
                    true
                ) as stats
                FROM rasters.annual_precipitation, public.calculations
                WHERE calculations.id = :calc_id
                  AND ST_Intersects(rast, boundary_geom)
                LIMIT 1
            ) as subquery
        """)

        precip_result = db.execute(precip_query, {"calc_id": str(calculation_id)}).first()

        # Filter out invalid values (None, NaN, Infinity)
        temp_mean = None
        temp_min = None
        precip_mean = None

        if temp_result and temp_result.temp_mean_c is not None:
            import math
            if not math.isinf(temp_result.temp_mean_c) and not math.isnan(temp_result.temp_mean_c):
                temp_mean = round(temp_result.temp_mean_c, 1)

        if temp_result and temp_result.temp_min_c is not None:
            import math
            if not math.isinf(temp_result.temp_min_c) and not math.isnan(temp_result.temp_min_c):
                temp_min = round(temp_result.temp_min_c, 1)

        if precip_result and precip_result.precip_mean_mm is not None:
            import math
            if not math.isinf(precip_result.precip_mean_mm) and not math.isnan(precip_result.precip_mean_mm):
                precip_mean = round(precip_result.precip_mean_mm, 1)

        return {
            "temperature_mean_c": temp_mean,
            "temperature_min_c": temp_min,
            "precipitation_mean_mm": precip_mean
        }
    except Exception as e:
        logger.error(f"Error analyzing climate: {e}")

    return {
        "temperature_mean_c": None,
        "temperature_min_c": None,
        "precipitation_mean_mm": None
    }


def analyze_forest_change(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """Analyze forest loss and gain (Hansen Global Forest Change)

    nepal_lossyear: 0 = no loss, 1-24 = year of loss (2001-2024)
    nepal_gain: 0 = no gain, 1 = forest gain (2000-2012)
    forest_loss_fire: 0 = no fire loss, 1-24 = year of fire loss (2001-2024)
    """
    # constraint: Hansen Global Forest Change v1.11 dataset — 30m resolution
    # constraint: tree cover threshold 30% per Hansen forest definition
    try:
        # Get area calculation for converting pixels to hectares
        area_query = text(f"""
            SELECT ST_Area(ST_Transform(boundary_geom, 32645)) / {SQM_PER_HA} as area_hectares
            FROM public.calculations
            WHERE id = :calc_id
        """)
        area_result = db.execute(area_query, {"calc_id": str(calculation_id)}).first()
        total_area_ha = area_result.area_hectares if area_result else 0

        # Forest loss by year
        loss_query = text("""
            SELECT
                (pvc).value as loss_year_code,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, boundary_geom)) as pvc
                FROM rasters.nepal_lossyear, public.calculations
                WHERE calculations.id = :calc_id
                  AND ST_Intersects(rast, boundary_geom)
            ) as subquery
            WHERE (pvc).value IS NOT NULL AND (pvc).value > 0
            GROUP BY loss_year_code
            ORDER BY loss_year_code
        """)

        loss_results = db.execute(loss_query, {"calc_id": str(calculation_id)}).fetchall()

        # Forest gain
        gain_query = text("""
            SELECT
                SUM((pvc).count) as gain_pixels
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, boundary_geom)) as pvc
                FROM rasters.nepal_gain, public.calculations
                WHERE calculations.id = :calc_id
                  AND ST_Intersects(rast, boundary_geom)
            ) as subquery
            WHERE (pvc).value = 1
        """)

        gain_result = db.execute(gain_query, {"calc_id": str(calculation_id)}).first()

        # Forest loss from fire
        fire_query = text("""
            SELECT
                (pvc).value as fire_year_code,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, boundary_geom)) as pvc
                FROM rasters.forest_loss_fire, public.calculations
                WHERE calculations.id = :calc_id
                  AND ST_Intersects(rast, boundary_geom)
            ) as subquery
            WHERE (pvc).value IS NOT NULL AND (pvc).value > 0
            GROUP BY fire_year_code
        """)

        fire_results = db.execute(fire_query, {"calc_id": str(calculation_id)}).fetchall()

        # Calculate total pixels and percentages
        total_loss_pixels = sum(r.pixel_count for r in loss_results) if loss_results else 0
        gain_pixels = gain_result.gain_pixels if gain_result and gain_result.gain_pixels else 0
        total_fire_pixels = sum(r.pixel_count for r in fire_results) if fire_results else 0

        # Estimate hectares (30m pixel = 900 sqm = 0.09 ha)
        # NOTE: 30m resolution Hansen pixel — each pixel = 900 m² = 0.09 ha
        pixel_area_ha = 0.09
        loss_hectares = total_loss_pixels * pixel_area_ha
        gain_hectares = gain_pixels * pixel_area_ha
        fire_loss_hectares = total_fire_pixels * pixel_area_ha

        # Build year-by-year loss data
        forest_loss_by_year = {}
        for r in loss_results:
            year = 2000 + int(r.loss_year_code)
            forest_loss_by_year[str(year)] = round(r.pixel_count * pixel_area_ha, 2)

        # Build year-by-year fire loss data
        fire_loss_by_year = {}
        for r in fire_results:
            year = 2000 + int(r.fire_year_code)
            fire_loss_by_year[str(year)] = round(r.pixel_count * pixel_area_ha, 2)

        return {
            "forest_loss_hectares": round(loss_hectares, 2) if loss_hectares > 0 else 0,
            "forest_gain_hectares": round(gain_hectares, 2) if gain_hectares > 0 else 0,
            "fire_loss_hectares": round(fire_loss_hectares, 2) if fire_loss_hectares > 0 else 0,
            "forest_loss_by_year": forest_loss_by_year,
            "fire_loss_by_year": fire_loss_by_year
        }
    except Exception as e:
        logger.error(f"Error analyzing forest change: {e}")

    return {
        "forest_loss_hectares": 0,
        "forest_gain_hectares": 0,
        "fire_loss_hectares": 0,
        "forest_loss_by_year": {},
        "fire_loss_by_year": {}
    }


def classify_usda_texture(clay_pct: float, sand_pct: float, silt_pct: float) -> str:
    """
    Classify soil texture using USDA 12-class system
    Based on clay, sand, and silt percentages
    """
    # constraint: USDA soil texture triangle standard — 12 texture classes based on clay/sand/silt ratios
    if clay_pct >= 40:
        if sand_pct >= 45:
            return "Sandy Clay"
        elif silt_pct >= 40:
            return "Silty Clay"
        else:
            return "Clay"
    elif clay_pct >= 27:
        if sand_pct >= 20 and sand_pct < 45:
            return "Clay Loam"
        elif sand_pct >= 45:
            return "Sandy Clay Loam"
        else:
            return "Silty Clay Loam"
    elif clay_pct >= 7:
        if sand_pct >= 52:
            if sand_pct >= 80:
                return "Loamy Sand"
            else:
                return "Sandy Loam"
        elif silt_pct >= 50:
            return "Silt Loam"
        elif silt_pct >= 80:
            return "Silt"
        else:
            return "Loam"
    else:  # clay < 7%
        if sand_pct >= 85:
            return "Sand"
        else:
            return "Loamy Sand"


def soc_dg_kg_from_raster(raw: Optional[float]) -> Optional[float]:
    """The stored SoilGrids SOC value -> dg/kg. Like pH, bulk density and CEC, the soilgrids_isric raster holds SOC at one tenth of
    the SoilGrids unit (raw ~30 means 304 dg/kg = 3 %): MULTIPLY by 10. It used to be divided by 10, which made every soil carbon
    stock ~100x too small (0.5 t/ha instead of ~100 t/ha) and understated the SOC part of the fertility score. Cross-check: with the
    stored nitrogen (~0.36 %), 3 % SOC gives a C:N of ~8, in the normal 8-15 range for forest soil; 0.03 % would give 0.1."""
    return raw * 10 if raw else None


def calculate_carbon_stock(soc_dg_kg: float, bulk_density_cg_cm3: float, depth_cm: float = 30) -> float:
    """
    Calculate soil organic carbon stock in topsoil

    Formula: Carbon Stock (t/ha) = SOC (%) × Bulk Density (g/cm³) × Depth (cm) × 10

    Args:
        soc_dg_kg: Soil organic carbon in dg/kg (from SoilGrids)
        bulk_density_cg_cm3: Bulk density in cg/cm³ (from SoilGrids)
        depth_cm: Soil depth in cm (default 30cm for topsoil)

    Returns:
        Carbon stock in tonnes per hectare
    """
    # business: IPCC 2006 Guidelines — CF = 0.47, default depth = 30 cm for topsoil carbon accounting
    # constraint: IPCC default bulk density of 1.3 g/cm³ when not measured in field
    if not soc_dg_kg or not bulk_density_cg_cm3:
        return None

    # Convert units
    soc_percent = soc_dg_kg / 1000  # dg/kg -> % is /100 (1 dg/kg = 0.01%); the extra /10 here is undone by the x10 in the formula below
    bulk_density_g_cm3 = bulk_density_cg_cm3 / 100  # cg/cm³ to g/cm³

    # Calculate carbon stock
    carbon_stock = soc_percent * bulk_density_g_cm3 * depth_cm * 10

    return round(carbon_stock, 2)


def assess_fertility(ph: float, soc_dg_kg: float, nitrogen_cg_kg: float, cec_mmol_kg: float, compaction_g_cm3: float = None, moisture_pct: float = None) -> dict:
    """Assess soil fertility using the centralized SSOT scoring engine.

    Replaces ~67 lines of inline threshold logic with a single SSOT call.
    Returns dict with keys: fertility_class, fertility_score, limiting_factors.
    """
    result = assess_soil_fertility(
        ph=ph if ph else 6.0,
        soc=soc_dg_kg / 100.0 if soc_dg_kg else 0.0,  # dg/kg -> % (the scoring engine's unit); /1000 understated SOC tenfold
        nitrogen=nitrogen_cg_kg / 1000.0 if nitrogen_cg_kg else 0.0,
        cec=cec_mmol_kg if cec_mmol_kg else 0.0,
        compaction=compaction_g_cm3 if compaction_g_cm3 else 1.5,
        moisture=moisture_pct if moisture_pct else 15.0,
    )
    return {
        "fertility_class": result.fertility_class.value,
        "fertility_score": result.total_score,
        "limiting_factors": [
            ps.name for ps in result.parameter_scores if ps.score <= 5
        ] or ["None identified"],
    }


def assess_compaction(bulk_density_cg_cm3: float) -> dict:
    """
    Assess soil compaction based on bulk density

    Returns:
        dict with compaction_status and compaction_alert
    """
    if not bulk_density_cg_cm3:
        return {"compaction_status": "Unknown", "compaction_alert": None}

    bulk_density_g_cm3 = bulk_density_cg_cm3 / 100

    if bulk_density_g_cm3 < 1.3:
        return {
            "compaction_status": "Not compacted",
            "compaction_alert": None
        }
    elif bulk_density_g_cm3 < 1.6:
        return {
            "compaction_status": "Slight compaction",
            "compaction_alert": "Monitor compaction levels, especially in high-traffic areas"
        }
    elif bulk_density_g_cm3 < 1.8:
        return {
            "compaction_status": "Moderate compaction",
            "compaction_alert": "Compaction may limit root growth. Consider soil amendments or reduced machinery use"
        }
    else:
        return {
            "compaction_status": "Severe compaction",
            "compaction_alert": "CRITICAL: Severe compaction detected. Root penetration severely limited. Intervention required"
        }


# ---------------------------------------------------------------------------
# Soil fertility bands
# ---------------------------------------------------------------------------
# One row per band, holding the DISPLAY label and the prose together, so the two
# cannot drift apart.
#
# The class and the prose used to come from two vocabularies that did not match. The
# producer (`app/core/soil_fertility.py::FertilityClass`) emits lowercase values -
# high / good / moderate / low / very_low - while the interpretation below compared
# against a different capitalised set: "Very High" / "High" / "Medium" / "Low" / else.
# All five of the producer's values therefore missed all four comparisons and fell to
# the `else`, which was written as if it meant "Very Low".
#
# On b67f9e1c that produced `class: "high"` beside "Poor soil fertility. Significant
# limitations for tree growth." - the soil described as poor while classified as high.
# It is the P1 failure family again: a value that looked fine and was not.
#
# The two sets differ in case AND in naming - the producer says `good` where the UI
# says "High", and `moderate` where it says "Medium" - so this is a translation, not a
# case fix. The five bands line up in order:
#
#     high (>=80)  good (60-79)  moderate (40-59)  low (20-39)  very_low (<20)
#     Very High    High          Medium           Low          Very Low
#
# The UI vocabulary is accepted as an alias too, so data already stored is
# re-interpreted correctly rather than reported as unrecognised.
# The producer's tokens are the ONLY values ever written to `class`, so they are the
# only ones resolved here. The UI's display labels are deliberately NOT accepted as
# input: the two vocabularies collide - the producer's `high` is the TOP band, while
# the UI's "High" is the SECOND one - so "High" can only mean one of them, and
# accepting it would silently re-map data. Anything unrecognised is now reported as
# unrecognised rather than guessed.
_FERTILITY_BANDS: Dict[str, Dict[str, Any]] = {
    "high": {
        "label": "Very High",
        "description": "Excellent soil fertility. Optimal conditions for tree growth.",
        "expected_growth": "Fast growth rates, 1.5-2.5 meters/year for fast-growing species",
        "recommendation": "Suitable for high-value timber species: Teak, Rosewood, Mahogany. Good for fruit orchards",
    },
    "good": {
        "label": "High",
        "description": "Good soil fertility. Supports healthy forest growth.",
        "expected_growth": "Good growth rates, 1.0-1.5 meters/year",
        "recommendation": "Suitable for most commercial species. Minor fertilization may boost growth",
    },
    "moderate": {
        "label": "Medium",
        "description": "Moderate fertility. Adequate for most native species.",
        "expected_growth": "Moderate growth, 0.5-1.0 meters/year",
        "recommendation": "Choose hardy species adapted to local conditions. Add compost for improved growth",
    },
    "low": {
        "label": "Low",
        "description": "Limited fertility. Trees will grow slowly without amendments.",
        "expected_growth": "Slow growth, 0.3-0.5 meters/year",
        "recommendation": "Select nutrient-efficient species. Apply organic amendments. Plant nitrogen-fixing trees",
    },
    "very_low": {
        "label": "Very Low",
        "description": "Poor soil fertility. Significant limitations for tree growth.",
        "expected_growth": "Very slow growth, < 0.3 meters/year",
        "recommendation": "Extensive soil improvement needed. Plant pioneer species first: Alnus, Acacia. Build soil gradually through organic matter",
    },
}


def _normalise_fertility_class(value: Any) -> str:
    """Fold a fertility class to a comparable token.

    Lower-cases, turns spaces and hyphens into underscores, and collapses runs of
    them, so ``"  HIGH  "``, ``"Very-High"`` and ``"very__low"`` all reduce to a
    single token rather than depending on incidental whitespace.
    """
    if value is None:
        return ""
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _resolve_fertility_band(value: Any) -> Optional[Dict[str, Any]]:
    """Resolve a producer fertility class to its band row, or ``None`` if unrecognised.

    Returning ``None`` rather than a default is the point: the old ``else`` branch
    silently asserted "Very Low", which is how an unrecognised vocabulary became a
    confident wrong answer instead of a visible gap.
    """
    return _FERTILITY_BANDS.get(_normalise_fertility_class(value))


def generate_soil_interpretations(soil_data: dict) -> dict:
    """
    Generate forester-friendly interpretations of soil properties

    Returns:
        dict with interpretations and recommendations for forest management
    """
    interpretations = {}

    # Soil Texture Interpretation
    texture = soil_data.get('soil_texture')
    clay_pct = soil_data.get('soil_properties', {}).get('clay_pct', 0)
    sand_pct = soil_data.get('soil_properties', {}).get('sand_pct', 0)
    silt_pct = soil_data.get('soil_properties', {}).get('silt_pct', 0)

    if texture:
        texture_info = {
            "name": texture,
            "description": "",
            "water_retention": "",
            "drainage": "",
            "workability": "",
            "suitable_species": []
        }

        # Texture-specific descriptions
        if "Sand" in texture or "Loamy Sand" in texture:
            texture_info["description"] = "Coarse-textured soil with large particle size. Feels gritty when rubbed between fingers."
            texture_info["water_retention"] = "Low - water drains quickly, requires frequent irrigation in dry seasons"
            texture_info["drainage"] = "Excellent - no waterlogging risk"
            texture_info["workability"] = "Easy to work year-round, not sticky when wet"
            texture_info["suitable_species"] = ["Pinus species (Pine)", "Shorea robusta (Sal) - with irrigation", "Dalbergia sissoo (Sissoo)"]
            texture_info["management_note"] = "Add organic matter (compost, mulch) to improve water and nutrient retention"

        elif "Silt" in texture and "Clay" not in texture:
            texture_info["description"] = "Smooth, silky soil that holds moisture well. Feels smooth like flour when dry."
            texture_info["water_retention"] = "Good - holds water well for tree roots"
            texture_info["drainage"] = "Moderate - may become waterlogged in heavy rain"
            texture_info["workability"] = "Moderate - can be slippery when wet, forms crust when dry"
            texture_info["suitable_species"] = ["Shorea robusta (Sal)", "Terminalia species (Asna/Saj)", "Adina cordifolia (Karma)", "Alnus nepalensis (Utis)"]
            texture_info["management_note"] = "Good for most tree species. Avoid heavy machinery when soil is wet to prevent compaction"

        elif "Clay" in texture:
            texture_info["description"] = "Fine-textured soil that feels sticky when wet. Can form hard clods when dry."
            texture_info["water_retention"] = "Excellent - holds water and nutrients very well"
            texture_info["drainage"] = "Poor - prone to waterlogging during monsoon"
            texture_info["workability"] = "Difficult - sticky when wet, hard when dry. Work only at optimal moisture"
            texture_info["suitable_species"] = ["Tectona grandis (Teak)", "Dalbergia latifolia (Rosewood)", "Bombax ceiba (Simal)", "Ficus species"]
            texture_info["management_note"] = "Avoid working when wet. Consider drainage ditches if waterlogging occurs. Excellent for bamboo cultivation"

        elif "Loam" in texture:
            texture_info["description"] = "Ideal balanced mixture of sand, silt, and clay. Feels crumbly and slightly sticky."
            texture_info["water_retention"] = "Excellent - balanced water holding capacity"
            texture_info["drainage"] = "Good - drains well but retains enough moisture"
            texture_info["workability"] = "Excellent - easy to work, best agricultural soil"
            texture_info["suitable_species"] = ["Most tree species thrive", "Shorea robusta (Sal)", "Schima wallichii (Chilaune)", "Castanopsis species", "Fruit trees"]
            texture_info["management_note"] = "Ideal soil for forestry. Most species will establish well. Maintain organic matter through mulching"

        interpretations["texture_interpretation"] = texture_info

    # pH Interpretation
    ph = soil_data.get('soil_properties', {}).get('ph_h2o')
    if ph:
        ph_info = {
            "value": ph,
            "category": "",
            "description": "",
            "nutrient_availability": "",
            "recommendation": ""
        }

        if ph < 5.0:
            ph_info["category"] = "Strongly Acidic"
            ph_info["description"] = "Very acidic soil. Limits availability of calcium, magnesium, and phosphorus."
            ph_info["nutrient_availability"] = "Poor - aluminum and manganese may become toxic to plants"
            ph_info["recommendation"] = "Apply lime (Chun) 2-4 tons/hectare to raise pH. Choose acid-tolerant species like Schima wallichii (Chilaune), Rhododendron species"
        elif ph < 5.5:
            ph_info["category"] = "Moderately Acidic"
            ph_info["description"] = "Slightly acidic. Common in Nepal's mid-hills. Many forest species adapted to this."
            ph_info["nutrient_availability"] = "Fair - most nutrients available but phosphorus may be limited"
            ph_info["recommendation"] = "Suitable for most hill species. Apply lime if planning fruit orchards. Add phosphorus fertilizer"
        elif ph <= 7.0:
            ph_info["category"] = "Optimal (Slightly Acidic to Neutral)"
            ph_info["description"] = "Ideal pH range for most forest species. Maximum nutrient availability."
            ph_info["nutrient_availability"] = "Excellent - all essential nutrients readily available"
            ph_info["recommendation"] = "No pH adjustment needed. Maintain through organic matter addition. Ideal for diverse plantations"
        elif ph <= 7.8:
            ph_info["category"] = "Slightly Alkaline"
            ph_info["description"] = "Mildly alkaline. Common in some Terai areas."
            ph_info["nutrient_availability"] = "Good, but iron, manganese, zinc may become less available"
            ph_info["recommendation"] = "Monitor for micronutrient deficiencies (yellowing leaves). Apply sulfur or organic matter to lower pH if needed"
        else:
            ph_info["category"] = "Strongly Alkaline"
            ph_info["description"] = "High pH limits nutrient availability."
            ph_info["nutrient_availability"] = "Poor - iron, manganese, zinc unavailable causing yellowing (chlorosis)"
            ph_info["recommendation"] = "Apply sulfur 500-1000 kg/hectare to reduce pH. Choose alkaline-tolerant species. Add iron chelates for existing trees"

        interpretations["ph_interpretation"] = ph_info

    # Nitrogen Interpretation
    nitrogen = soil_data.get('soil_properties', {}).get('nitrogen_cg_kg')
    if nitrogen:
        nitrogen_pct = nitrogen / 1000
        nitrogen_info = {
            "value_cg_kg": nitrogen,
            "value_percent": round(nitrogen_pct, 3),
            "category": "",
            "description": "",
            "recommendation": ""
        }

        if nitrogen_pct < 0.05:
            nitrogen_info["category"] = "Very Low"
            nitrogen_info["description"] = "Deficient nitrogen. Trees will show stunted growth and pale/yellowish leaves."
            nitrogen_info["recommendation"] = "Plant nitrogen-fixing species: Alnus nepalensis (Utis), Acacia species, Dalbergia sissoo. Apply urea 50-100 kg/hectare for plantations"
        elif nitrogen_pct < 0.10:
            nitrogen_info["category"] = "Low"
            nitrogen_info["description"] = "Below optimal. Slower tree growth expected."
            nitrogen_info["recommendation"] = "Include nitrogen-fixing species in mixed plantations. Apply compost or manure 5-10 tons/hectare"
        elif nitrogen_pct < 0.20:
            nitrogen_info["category"] = "Adequate"
            nitrogen_info["description"] = "Sufficient for moderate tree growth. Typical for forest soils."
            nitrogen_info["recommendation"] = "Maintain through leaf litter decomposition. Avoid removing forest floor organic matter"
        else:
            nitrogen_info["category"] = "High"
            nitrogen_info["description"] = "Excellent nitrogen level. Supports vigorous tree growth."
            nitrogen_info["recommendation"] = "No nitrogen fertilization needed. Good for fast-growing species like Eucalyptus, Poplar, Paulownia"

        interpretations["nitrogen_interpretation"] = nitrogen_info

    # Carbon Stock Interpretation
    carbon_stock = soil_data.get('carbon_stock_t_ha')
    if carbon_stock:
        carbon_info = {
            "value": carbon_stock,
            "category": "",
            "description": "",
            "climate_benefit": "",
            "recommendation": ""
        }

        if carbon_stock < 20:
            carbon_info["category"] = "Low"
            carbon_info["description"] = "Low soil organic matter. Poor soil structure and fertility."
            carbon_info["climate_benefit"] = "Limited carbon sequestration potential"
            carbon_info["recommendation"] = "Increase organic matter: retain leaf litter, add compost, plant cover crops, practice agroforestry. Avoid burning forest residues"
        elif carbon_stock < 40:
            carbon_info["category"] = "Moderate"
            carbon_info["description"] = "Moderate organic matter. Typical for managed forests."
            carbon_info["climate_benefit"] = "Moderate carbon storage - contributes to climate mitigation"
            carbon_info["recommendation"] = "Maintain by preventing erosion, retaining forest floor, minimizing soil disturbance"
        else:
            carbon_info["category"] = "High"
            carbon_info["description"] = "High organic matter. Excellent soil health and fertility."
            carbon_info["climate_benefit"] = "Significant carbon storage - valuable for carbon credit programs (REDD+)"
            carbon_info["recommendation"] = "Protect this valuable carbon stock. Avoid soil disturbance, erosion, or degradation. Potential for carbon credit enrollment"

        interpretations["carbon_interpretation"] = carbon_info

    # Fertility Class Interpretation
    #
    # Resolve the class ONCE through _resolve_fertility_band and take both the label
    # and the prose from that one row, so they cannot disagree. The old code compared
    # the raw producer value against a differently-named vocabulary, so every value
    # fell to the `else` and was described as "Very Low" - see _FERTILITY_BANDS.
    fertility = soil_data.get('fertility_class')
    if fertility:
        band = _resolve_fertility_band(fertility)
        fertility_info = {
            # The DISPLAY label, which is what the analysis UI compares against
            # ("Very High" / "High" / "Medium" / "Low"). Emitting the raw producer
            # value here is what made the badge and the colours fall through.
            "class": band["label"] if band else fertility,
            "score": soil_data.get('fertility_score', 0),
            "description": band["description"] if band else "",
            "expected_growth": band["expected_growth"] if band else "",
            "recommendation": band["recommendation"] if band else "",
            # The canonical machine value, preserved so nothing is lost by the
            # translation, plus whether it was recognised at all.
            "class_key": _normalise_fertility_class(fertility),
            "recognised": band is not None,
        }
        if band is None:
            # An unrecognised vocabulary is reported AS unrecognised. The old `else`
            # stated "Very Low" with full confidence, which is how a mis-mapped class
            # became a confident wrong answer rather than a visible gap.
            fertility_info["description"] = (
                f"Unrecognised soil fertility class {fertility!r}. No interpretation "
                "available - the class vocabulary does not match the analysis bands."
            )
            logger.warning(
                "[analysis] unrecognised fertility_class %r; reporting it as "
                "unrecognised rather than assuming 'Very Low'",
                fertility,
            )

        interpretations["fertility_interpretation"] = fertility_info

    return interpretations


def analyze_soil(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """Analyze soil properties (ISRIC SoilGrids) with enhanced analysis

    Phase 1 Enhanced Features:
    1. USDA 12-class texture classification
    2. Soil carbon stock calculation
    3. Fertility assessment
    4. Compaction alert

    8 bands from soilgrids_isric:
    Band 1 = clay_g_kg (Clay content in g/kg)
    Band 2 = sand_g_kg (Sand content in g/kg)
    Band 3 = silt_g_kg (Silt content in g/kg)
    Band 4 = ph_h2o (Soil pH in H2O)
    Band 5 = soc_dg_kg (Soil organic carbon in dg/kg)
    Band 6 = nitrogen_cg_kg (Nitrogen content in cg/kg)
    Band 7 = bdod_cg_cm3 (Bulk density in cg/cm3)
    Band 8 = cec_mmol_kg (Cation exchange capacity in mmol/kg)

    OPTIMIZED VERSION - Now enabled with band-by-band processing
    """
    # constraint: SoilGrids 250m resolution v2.0 — ISRIC global soil data
    try:
        logger.info("Starting whole-forest soil analysis...")

        # Get WKT for whole forest
        wkt_query = text("""
            SELECT ST_AsText(boundary_geom) as wkt
            FROM calculations
            WHERE id = :calc_id
        """)
        wkt_result = db.execute(wkt_query, {"calc_id": str(calculation_id)}).first()

        if not wkt_result:
            logger.info("  No boundary geometry found")
            return {
                "soil_texture": None,
                "soil_texture_system": "USDA 12-class",
                "carbon_stock_t_ha": None,
                "fertility_class": None,
                "fertility_score": None,
                "limiting_factors": ["No boundary data"],
                "compaction_status": None,
                "compaction_alert": None,
                "soil_properties": {}
            }

        # Use the geometry-based analysis (already optimized)
        return analyze_soil_geometry(wkt_result.wkt, db)

    except Exception as e:
        logger.error(f"Error in whole-forest soil analysis: {e}")
        return {
            "soil_texture": None,
            "soil_texture_system": "USDA 12-class",
            "carbon_stock_t_ha": None,
            "fertility_class": None,
            "fertility_score": None,
            "limiting_factors": [f"Error: {str(e)[:100]}"],
            "compaction_status": None,
            "compaction_alert": None,
            "soil_properties": {}
        }


async def analyze_vectors(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """
    Analyze vector datasets - proximity and intersection analysis
    """
    results = {}

    # Placeholder for vector analysis
    results["buildings_within_1km"] = 0
    results["nearest_settlement"] = None
    results["nearest_road"] = None

    return results




def get_administrative_location(geometry_wkt: str, db: Session) -> Dict[str, Any]:
    """
    Get administrative location by intersecting geometry centroid with admin boundaries

    Args:
        geometry_wkt: WKT string of geometry
        db: Database session

    Returns:
        Dict with: province, district, municipality, ward, watershed, major_river_basin
                   plus Nepali names: province_ne, division_n, subdivis_n,
                   municipality_n, municipality_type_nep, ward_ne,
                   physiography_ne, juridiction_ne
    """
    location = {}

    # Query admin.admin_nepal for Nepali names (single spatial query, all fields)
    admin_query = text("""
        SELECT province_ne, division_n, subdivis_n,
               palika_n, type_nep, ward_ne,
               physiography_ne, juridiction_ne
        FROM admin.admin_nepal
        WHERE ST_Contains(geom, ST_Centroid(ST_GeomFromText(:wkt, 4326)))
        LIMIT 1
    """)
    admin_row = db.execute(admin_query, {"wkt": geometry_wkt}).first()
    if admin_row:
        location["province_ne"] = admin_row[0]
        location["division_n"] = admin_row[1]
        location["subdivis_n"] = admin_row[2]
        location["municipality_n"] = admin_row[3]
        location["municipality_type_nep"] = admin_row[4]
        location["ward_ne"] = admin_row[5]
        location["physiography_ne"] = admin_row[6]
        location["juridiction_ne"] = admin_row[7]

    # Query for province (English)
    province_query = text("""
        SELECT p.province
        FROM admin.province p
        WHERE ST_Intersects(
            p.shape,
            ST_Centroid(ST_GeomFromText(:wkt, 4326))
        )
        LIMIT 1
    """)
    province_result = db.execute(province_query, {"wkt": geometry_wkt}).first()
    location["province"] = province_result.province if province_result else None

    # Query for municipality (includes district and municipality type)
    municipality_query = text("""
        SELECT INITCAP(m.district) as district, m.gapa_napa as municipality, m.type_gn as municipality_type
        FROM admin.municipality m
        WHERE ST_Intersects(
            m.geom,
            ST_Centroid(ST_GeomFromText(:wkt, 4326))
        )
        LIMIT 1
    """)
    municipality_result = db.execute(municipality_query, {"wkt": geometry_wkt}).first()
    if municipality_result:
        location["district"] = municipality_result.district
        location["municipality"] = municipality_result.municipality
        location["municipality_type"] = municipality_result.municipality_type
    else:
        location["district"] = None
        location["municipality"] = None
        location["municipality_type"] = None

    # Query for ward
    ward_query = text("""
        SELECT w.ward
        FROM admin.ward w
        WHERE ST_Intersects(
            w.geom,
            ST_Centroid(ST_GeomFromText(:wkt, 4326))
        )
        LIMIT 1
    """)
    ward_result = db.execute(ward_query, {"wkt": geometry_wkt}).first()
    location["ward"] = str(ward_result.ward) if ward_result else None

    # Query for watershed
    watershed_query = text("""
        SELECT w."watershed name" as watershed_name, w."major river basin" as major_river_basin
        FROM admin."watershed_Nepal" w
        WHERE ST_Intersects(
            w.geom,
            ST_Centroid(ST_GeomFromText(:wkt, 4326))
        )
        LIMIT 1
    """)
    watershed_result = db.execute(watershed_query, {"wkt": geometry_wkt}).first()
    if watershed_result:
        location["watershed"] = watershed_result.watershed_name
        location["major_river_basin"] = watershed_result.major_river_basin
    else:
        location["watershed"] = None
        location["major_river_basin"] = None

    return location




def analyze_geology_geometry(geometry_wkt: str, db: Session) -> Dict[str, Any]:
    """
    Analyze geology classes that intersect with the geometry
    Returns percentage coverage for each geology class

    Args:
        geometry_wkt: WKT string of geometry
        db: Database session

    Returns:
        Dict with geology_percentages: {class_name: percentage}
    """
    # constraint: Nepal geology 1:500k scale — DMG (Department of Mines and Geology) geological map
    geology_query = text("""
        WITH input_geom AS (
            SELECT ST_GeomFromText(:wkt, 4326) as geom
        ),
        total_area AS (
            SELECT ST_Area(ST_Transform(geom, 32645)) as area
            FROM input_geom
        ),
        geology_intersections AS (
            SELECT
                g."geology class" as geology_class,
                ST_Area(
                    ST_Transform(
                        ST_Intersection(g.geom, i.geom),
                        32645
                    )
                ) as intersection_area
            FROM geology.geology g, input_geom i
            WHERE ST_Intersects(g.geom, i.geom)
            AND g."geology class" IS NOT NULL
            AND g."geology class" != 'No Data'
        )
        SELECT
            geology_class,
            (intersection_area / (SELECT area FROM total_area)) * 100 as percentage
        FROM geology_intersections
        WHERE intersection_area > 0
        ORDER BY percentage DESC
    """)

    try:
        result = db.execute(geology_query, {"wkt": geometry_wkt})
        geology_data = {}

        for row in result:
            if row.geology_class and row.percentage:
                geology_data[row.geology_class] = round(float(row.percentage), 2)

        return {
            "geology_percentages": geology_data if geology_data else None
        }
    except Exception as e:
        logger.error(f"Geology analysis error: {e}")
        return {"geology_percentages": None}


def calculate_access_info(geometry_wkt: str, db: Session) -> Dict[str, Any]:
    """
    Calculate access information: distance and direction to nearest district headquarters

    Args:
        geometry_wkt: WKT string of geometry
        db: Database session

    Returns:
        Dict with access_info: "Location Direction (degrees°) distance km"
    """
    # business: CFMG requires forest accessibility assessment — nearest district HQ in km and direction
    access_query = text("""
        WITH input_geom AS (
            SELECT
                ST_GeomFromText(:wkt, 4326) as geom,
                ST_Centroid(ST_GeomFromText(:wkt, 4326)) as centroid
        ),
        nearest_hq AS (
            SELECT
                dh."head quarter" as name,
                ST_Distance(
                    ST_Transform(i.centroid, 32645),
                    ST_Transform(dh.geom, 32645)
                ) / 1000.0 as distance_km,
                degrees(
                    ST_Azimuth(
                        i.centroid,
                        dh.geom
                    )
                ) as azimuth_degrees
            FROM admin."district Headquarter" dh, input_geom i
            WHERE dh."head quarter" IS NOT NULL
            ORDER BY ST_Distance(i.centroid, dh.geom)
            LIMIT 1
        )
        SELECT
            name,
            distance_km,
            azimuth_degrees,
            CASE
                WHEN azimuth_degrees >= 337.5 OR azimuth_degrees < 22.5 THEN 'North'
                WHEN azimuth_degrees >= 22.5 AND azimuth_degrees < 67.5 THEN 'Northeast'
                WHEN azimuth_degrees >= 67.5 AND azimuth_degrees < 112.5 THEN 'East'
                WHEN azimuth_degrees >= 112.5 AND azimuth_degrees < 157.5 THEN 'Southeast'
                WHEN azimuth_degrees >= 157.5 AND azimuth_degrees < 202.5 THEN 'South'
                WHEN azimuth_degrees >= 202.5 AND azimuth_degrees < 247.5 THEN 'Southwest'
                WHEN azimuth_degrees >= 247.5 AND azimuth_degrees < 292.5 THEN 'West'
                ELSE 'Northwest'
            END as direction
        FROM nearest_hq
    """)

    try:
        result = db.execute(access_query, {"wkt": geometry_wkt}).first()

        if result and result.name:
            access_str = f"{result.name} {result.direction} ({int(result.azimuth_degrees)}°) {result.distance_km:.1f} km"
            return {"access_info": access_str}
        else:
            return {"access_info": None}
    except Exception as e:
        logger.error(f"Access calculation error: {e}")
        return {"access_info": None}


def analyze_nearby_features(geometry_wkt: str, db: Session) -> Dict[str, Any]:
    """
    Find natural and infrastructure features within 100m of boundary
    Reports features by direction: North, East, South, West

    NEW IMPLEMENTATION: Uses PostgreSQL function for efficiency and reliability
    Single database call returns all 4 directions at once

    Args:
        geometry_wkt: WKT string of geometry
        db: Database session

    Returns:
        Dict with features_north, features_east, features_south, features_west
    """
    # business: CFMG — 100m buffer zone for boundary feature inventory (roads, settlements, water bodies)

    logger.info("  Calling PostgreSQL analyze_nearby_features function...")

    # Use savepoint for transaction isolation (based on E:\CF_application working implementation)
    savepoint = db.begin_nested()

    try:
        # Call PostgreSQL function - returns all 4 directions in single query
        query = text("""
            SELECT analyze_nearby_features(:wkt)
        """)

        result = db.execute(query, {"wkt": geometry_wkt}).scalar()

        # Commit savepoint (keeps outer transaction intact)
        savepoint.commit()

        # Convert JSONB result to Python dict
        if result:
            # result is already a dict from JSONB
            result_dict = {
                'features_north': result.get('features_north'),
                'features_east': result.get('features_east'),
                'features_south': result.get('features_south'),
                'features_west': result.get('features_west')
            }

            # Debug logging
            logger.info(f"  PostgreSQL function returned all 4 directions:")
            for direction in ['north', 'east', 'south', 'west']:
                key = f'features_{direction}'
                val = result_dict.get(key)
                val_preview = val[:50] if val else None
                logger.info(f"    {key}: {val_preview}")

            return result_dict
        else:
            # Function returned NULL
            logger.warning("  WARNING: PostgreSQL function returned NULL")
            return {
                'features_north': None,
                'features_east': None,
                'features_south': None,
                'features_west': None
            }

    except Exception as e:
        # Rollback savepoint only (preserves outer transaction)
        savepoint.rollback()
        logger.error(f"  ERROR calling PostgreSQL function: {e}")
        import traceback
        traceback.print_exc()

        # Return empty result on error
        return {
            'features_north': None,
            'features_east': None,
            'features_south': None,
            'features_west': None
        }


async def analyze_admin_boundaries(calculation_id: UUID, db: Session) -> Dict[str, Any]:
    """
    Analyze administrative boundaries - province, municipality, ward
    """
    return {
        "province": None,
        "municipality": None,
        "ward": None
    }


# ============================================================================
# GEOMETRY-BASED ANALYSIS FUNCTIONS (for individual blocks)
# ============================================================================

def analyze_dem_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """Analyze DEM raster for a specific geometry (WKT)

    DEM contains 16-bit signed integer values in meters.
    NoData value is -32768 but PostGIS doesn't know this (NoData=NULL in raster metadata).
    We must explicitly exclude -32768 values by filtering in the query.
    """
    try:
        # Use ST_PixelAsPolygons to get all pixel values, then filter and aggregate
        query = text("""
            WITH clipped_raster AS (
                SELECT ST_Clip(rast, ST_GeomFromText(:wkt, 4326)) as rast
                FROM rasters.dem
                WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
                LIMIT 1
            ),
            pixel_values AS (
                SELECT (ST_PixelAsPolygons(rast)).val as elevation
                FROM clipped_raster
            )
            SELECT
                MIN(elevation) as elevation_min,
                MAX(elevation) as elevation_max,
                AVG(elevation) as elevation_mean
            FROM pixel_values
            WHERE elevation > -32000  -- Exclude NoData values (-32768)
              AND elevation >= 0       -- Nepal minimum elevation
              AND elevation <= 9000    -- Nepal maximum elevation (Mt. Everest 8848m + margin)
        """)

        result = db.execute(query, {"wkt": wkt}).first()

        if result and result.elevation_mean is not None:
            return {
                "elevation_min_m": round(result.elevation_min, 1) if result.elevation_min else None,
                "elevation_max_m": round(result.elevation_max, 1) if result.elevation_max else None,
                "elevation_mean_m": round(result.elevation_mean, 1) if result.elevation_mean else None
            }
    except Exception as e:
        logger.error(f"Error analyzing DEM: {e}")

    return {"elevation_min_m": None, "elevation_max_m": None, "elevation_mean_m": None}


def analyze_slope_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """
    Analyze slope for a specific geometry
    Returns percentages, dominant class, and min/max codes for dynamic legend generation

    Slope raster contains categorical codes (8-bit unsigned):
    0 = No data / Water (excluded)
    1 = Gentle (<19°)
    2 = Moderate (19-31°)
    3 = Steep (31-45°)
    4 = Very Steep (>45°)
    """
    try:
    # Mapping from raster values to class names (excluding 0)
        slope_map = {
            1: "gentle",
            2: "moderate",
            3: "steep",
            4: "very_steep"
        }

        query = text("""
            SELECT
                (pvc).value as slope_code,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) as pvc
                FROM rasters.slope_regulation
                WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
            ) as subquery
            WHERE (pvc).value IS NOT NULL
              AND (pvc).value > 0
              AND (pvc).value <= 4
            GROUP BY slope_code
        """)

        results = db.execute(query, {"wkt": wkt}).fetchall()

        if results:
            total_pixels = sum(r.pixel_count for r in results)
            percentages = {}
            slope_codes_present = []

            for r in results:
                code = int(r.slope_code)
                if code in slope_map:
                    percentages[slope_map[code]] = round((r.pixel_count / total_pixels) * 100, 2)
                    slope_codes_present.append(code)

            if percentages:
                dominant = max(percentages.items(), key=lambda x: x[1])[0]

                # Calculate min/max slope codes for dynamic legend filtering
                slope_min_code = min(slope_codes_present) if slope_codes_present else None
                slope_max_code = max(slope_codes_present) if slope_codes_present else None

                return {
                    "slope_dominant_class": dominant,
                    "slope_percentages": percentages,
                    "slope_min_code": slope_min_code,  # NEW: For dynamic legend
                    "slope_max_code": slope_max_code   # NEW: For dynamic legend
                }
    except Exception as e:
        logger.error(f"Error analyzing slope: {e}")

    return {
        "slope_dominant_class": None,
        "slope_percentages": {},
        "slope_min_code": None,
        "slope_max_code": None
    }


def analyze_aspect_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """Analyze aspect for a specific geometry

    Aspect raster contains categorical codes (8-bit unsigned):
    0 = No data (excluded from analysis), 1 = N, 2 = NE, 3 = E, 4 = SE, 5 = S, 6 = SW, 7 = W, 8 = NW
    """
    try:
        # Mapping from raster values to direction names
        aspect_map = {
            1: "N",
            2: "NE",
            3: "E",
            4: "SE",
            5: "S",
            6: "SW",
            7: "W",
            8: "NW"
        }

        query = text("""
            SELECT
                (pvc).value as aspect_code,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) as pvc
                FROM rasters.aspect
                WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
            ) as subquery
            WHERE (pvc).value IS NOT NULL AND (pvc).value BETWEEN 1 AND 8
            GROUP BY aspect_code
        """)

        results = db.execute(query, {"wkt": wkt}).fetchall()

        if results:
            total_pixels = sum(r.pixel_count for r in results)
            percentages = {}
            for r in results:
                code = int(r.aspect_code)
                if code in aspect_map:
                    percentages[aspect_map[code]] = round((r.pixel_count / total_pixels) * 100, 2)

            if percentages:
                # Find dominant aspect
                dominant = max(percentages.items(), key=lambda x: x[1])[0]

                return {
                    "aspect_dominant": dominant,
                    "aspect_percentages": percentages
                }
    except Exception as e:
        logger.error(f"Error analyzing aspect: {e}")

    return {"aspect_dominant": None, "aspect_percentages": {}}


def analyze_canopy_height_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """Analyze canopy height for a specific geometry using rasterio from TIF file"""
    try:
        geom = shapely_wkt.loads(wkt)
        geojson = mapping(geom)
        return _canopy_from_rasterio(geojson)
    except Exception as e:
        logger.error(f"Error analyzing canopy height geometry: {e}")
        return {"canopy_mean_m": None, "canopy_dominant_class": None, "canopy_percentages": {}, "canopy_min_m": None, "canopy_max_m": None}


def analyze_agb_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """
    Analyze above-ground biomass for a specific geometry
    Returns mean, min, max, total, and carbon stock for dynamic legend generation

    AGB raster (16-bit unsigned) has 2 bands:
    Band 1 = AGB estimate in Mg/ha, Band 2 = standard deviation
    """
    try:
        query = text("""
            SELECT
                (stats).mean as agb_mean,
                (stats).min as agb_min,
                (stats).max as agb_max,
                (stats).sum as agb_total
            FROM (
                SELECT ST_SummaryStats(
                    ST_Clip(rast, 1, ST_GeomFromText(:wkt, 4326)),
                    1,  -- band 1
                    true  -- exclude nodata
                ) as stats
                FROM rasters.agb_2022_nepal
                WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
                LIMIT 1
            ) as subquery
        """)

        result = db.execute(query, {"wkt": wkt}).first()

        if result and result.agb_total:
            return {
                "agb_mean_mg_ha": round(result.agb_mean, 2) if result.agb_mean else None,
                "agb_min_mg_ha": round(result.agb_min, 2) if result.agb_min else None,
                "agb_max_mg_ha": round(result.agb_max, 2) if result.agb_max else None,
                "agb_total_mg": round(result.agb_total, 2) if result.agb_total else None,
                "carbon_stock_mg": round(result.agb_total * 0.5, 2) if result.agb_total else None
            }
    except Exception as e:
        logger.error(f"Error analyzing AGB: {e}")

    return {
        "agb_mean_mg_ha": None,
        "agb_min_mg_ha": None,
        "agb_max_mg_ha": None,
        "agb_total_mg": None,
        "carbon_stock_mg": None
    }


def analyze_forest_health_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """Analyze forest health for a specific geometry

    Forest health classes (8-bit unsigned):
    1=Stressed, 2=Poor, 3=Moderate, 4=Healthy, 5=Excellent
    """
    try:
        # Correct mapping according to table comment - capitalized to match frontend legend
        health_map = {
            1: "Stressed",
            2: "Poor",
            3: "Moderate",
            4: "Healthy",
            5: "Excellent"
        }

        query = text("""
            SELECT
                (pvc).value as health_class,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) as pvc
                FROM rasters.nepal_forest_health
                WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
            ) as subquery
            WHERE (pvc).value IS NOT NULL AND (pvc).value BETWEEN 1 AND 5
            GROUP BY health_class
        """)

        results = db.execute(query, {"wkt": wkt}).fetchall()

        if results:
            total_pixels = sum(r.pixel_count for r in results)
            percentages = {}
            for r in results:
                class_val = int(r.health_class)
                if class_val in health_map:
                    percentages[health_map[class_val]] = round((r.pixel_count / total_pixels) * 100, 2)

            if percentages:
                dominant = max(percentages.items(), key=lambda x: x[1])[0]
                return {
                    "forest_health_dominant": dominant,
                    "forest_health_percentages": percentages
                }
    except Exception as e:
        logger.error(f"Error analyzing forest health: {e}")

    return {"forest_health_dominant": None, "forest_health_percentages": {}}


def analyze_forest_type_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """Analyze forest type for a specific geometry (WKT)"""
    try:
        # why: raster pixel values map to forest_types.pixel_value; LEFT JOIN ensures
        #      codes without a DB entry fall back to "Data Not Available"
        query = text("""
            SELECT
                (pvc).value as forest_type_code,
                COALESCE(ft.forest_type_name, 'Data Not Available') as forest_type_name,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) as pvc
                FROM rasters.forest_type WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
            ) as subquery
            LEFT JOIN forest_types ft ON ft.pixel_value = (pvc).value
            WHERE (pvc).value IS NOT NULL AND (pvc).value BETWEEN 1 AND 26
            GROUP BY forest_type_code, forest_type_name
            ORDER BY pixel_count DESC
        """)
        results = db.execute(query, {"wkt": wkt}).fetchall()
        if not results:
            return {"forest_type_dominant": None, "forest_type_percentages": {}}
        total_pixels = sum(r.pixel_count for r in results)
        forest_type_percentages = {}
        dominant_type = None
        max_percentage = 0
        for r in results:
            type_name = r.forest_type_name
            percentage = (r.pixel_count / total_pixels * 100) if total_pixels > 0 else 0
            forest_type_percentages[type_name] = round(percentage, 2)
            if type_name != 'Data Not Available' and percentage > max_percentage:
                max_percentage = percentage
                dominant_type = type_name
            elif type_name == 'Data Not Available' and dominant_type is None:
                dominant_type = type_name
        return {"forest_type_dominant": dominant_type, "forest_type_percentages": forest_type_percentages}
    except Exception as e:
        logger.error(f"Error analyzing forest type for geometry: {e}")
    return {"forest_type_dominant": None, "forest_type_percentages": {}}


def analyze_landcover_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """Analyze ESA WorldCover land cover for a specific geometry (WKT)

ESA WorldCover classes:
     0 = No data (excluded from analysis)
     10-100 = Valid land cover classes
     """
    try:
        # SSOT: app/core/forest_types.py → ESA_WORLD_COVER
        query = text("""
            SELECT (pvc).value as landcover_code, SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) as pvc
                FROM rasters.esa_world_cover WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
            ) as subquery
            WHERE (pvc).value IS NOT NULL AND (pvc).value > 0
            GROUP BY landcover_code ORDER BY pixel_count DESC
        """)
        results = db.execute(query, {"wkt": wkt}).fetchall()
        if not results:
            return {"landcover_dominant": None, "landcover_percentages": {}}
        total_pixels = sum(r.pixel_count for r in results)
        landcover_percentages = {}
        dominant_cover = None
        max_percentage = 0
        for r in results:
            code = int(r.landcover_code)
            if code in ESA_WORLD_COVER:
                percentage = (r.pixel_count / total_pixels * 100) if total_pixels > 0 else 0
                cover_name = ESA_WORLD_COVER[code].name_en
                landcover_percentages[cover_name] = round(percentage, 2)
                if percentage > max_percentage:
                    max_percentage = percentage
                    dominant_cover = cover_name
        return {"landcover_dominant": dominant_cover, "landcover_percentages": landcover_percentages}
    except Exception as e:
        logger.error(f"Error analyzing land cover for geometry: {e}")
    return {"landcover_dominant": None, "landcover_percentages": {}}


def analyze_forest_loss_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """Analyze Hansen forest loss (2001-2023) for a specific geometry"""
    try:
        query = text("""
            SELECT (pvc).value as loss_year, SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) as pvc
                FROM rasters.nepal_lossyear WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
            ) as subquery
            WHERE (pvc).value IS NOT NULL AND (pvc).value BETWEEN 1 AND 23
            GROUP BY loss_year ORDER BY loss_year
        """)
        results = db.execute(query, {"wkt": wkt}).fetchall()
        if not results:
            return {"forest_loss_hectares": 0, "forest_loss_by_year": {}}
        pixel_area_ha = 0.0009
        loss_by_year = {}
        total_loss_pixels = 0
        for r in results:
            year_code = int(r.loss_year)
            actual_year = 2000 + year_code
            loss_ha = r.pixel_count * pixel_area_ha
            loss_by_year[str(actual_year)] = round(loss_ha, 4)
            total_loss_pixels += r.pixel_count
        total_loss_ha = total_loss_pixels * pixel_area_ha
        return {"forest_loss_hectares": round(total_loss_ha, 4), "forest_loss_by_year": loss_by_year}
    except Exception as e:
        logger.error(f"Error analyzing forest loss for geometry: {e}")
    return {"forest_loss_hectares": None, "forest_loss_by_year": {}}


def analyze_forest_gain_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """Analyze Hansen forest gain (2000-2012) for a specific geometry"""
    try:
        query = text("""
            SELECT SUM((pvc).count) as gain_pixels
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) as pvc
                FROM rasters.nepal_gain WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
            ) as subquery
            WHERE (pvc).value = 1
        """)
        result = db.execute(query, {"wkt": wkt}).first()
        if result and result.gain_pixels:
            pixel_area_ha = 0.0009
            gain_ha = result.gain_pixels * pixel_area_ha
            return {"forest_gain_hectares": round(gain_ha, 4)}
    except Exception as e:
        logger.error(f"Error analyzing forest gain for geometry: {e}")
    return {"forest_gain_hectares": None}


def analyze_fire_loss_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """Analyze fire-related forest loss for a specific geometry"""
    try:
        query = text("""
            SELECT (pvc).value as fire_year, SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) as pvc
                FROM rasters.forest_loss_fire WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
            ) as subquery
            WHERE (pvc).value IS NOT NULL AND (pvc).value BETWEEN 1 AND 23
            GROUP BY fire_year ORDER BY fire_year
        """)
        results = db.execute(query, {"wkt": wkt}).fetchall()
        if not results:
            return {"fire_loss_hectares": 0, "fire_loss_by_year": {}}
        pixel_area_ha = 0.0009
        fire_by_year = {}
        total_fire_pixels = 0
        for r in results:
            year_code = int(r.fire_year)
            actual_year = 2000 + year_code
            fire_ha = r.pixel_count * pixel_area_ha
            fire_by_year[str(actual_year)] = round(fire_ha, 4)
            total_fire_pixels += r.pixel_count
        total_fire_ha = total_fire_pixels * pixel_area_ha
        return {"fire_loss_hectares": round(total_fire_ha, 4), "fire_loss_by_year": fire_by_year}
    except Exception as e:
        logger.error(f"Error analyzing fire loss for geometry: {e}")
    return {"fire_loss_hectares": None, "fire_loss_by_year": {}}


def analyze_temperature_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """
    Analyze temperature data for a specific geometry
    Returns mean, min, and max temperature values for dynamic legend generation
    """
    try:
        # Get mean, min, and max temperature in a single query
        query = text("""
            WITH clipped AS (
                SELECT ST_Clip(rast, ST_GeomFromText(:wkt, 4326)) as rast
                FROM rasters.annual_mean_temperature WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
                LIMIT 1
            ), pixel_values AS (
                SELECT (ST_PixelAsPolygons(rast)).val as temp FROM clipped
            )
            SELECT
                AVG(temp) as temp_mean,
                MIN(temp) as temp_min,
                MAX(temp) as temp_max
            FROM pixel_values
            WHERE temp IS NOT NULL AND temp > -100 AND temp < 100
        """)
        result = db.execute(query, {"wkt": wkt}).first()

        temp_mean = None
        temp_min = None
        temp_max = None

        if result:
            if result.temp_mean is not None:
                temp_mean = round(result.temp_mean, 2)
            if result.temp_min is not None:
                temp_min = round(result.temp_min, 2)
            if result.temp_max is not None:
                temp_max = round(result.temp_max, 2)

        return {
            "temperature_mean_c": temp_mean,
            "temperature_min_c": temp_min,
            "temperature_max_c": temp_max
        }
    except Exception as e:
        logger.error(f"Error analyzing temperature for geometry: {e}")
    return {
        "temperature_mean_c": None,
        "temperature_min_c": None,
        "temperature_max_c": None
    }


def analyze_min_temp_coldest_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """
    Analyze minimum temperature of coldest month for a specific geometry
    Returns mean, min, and max values for dynamic legend generation
    """
    try:
        # Get mean, min, and max min temperature in a single query
        query = text("""
            WITH clipped AS (
                SELECT ST_Clip(rast, ST_GeomFromText(:wkt, 4326)) as rast
                FROM rasters.min_temp_coldest_month WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
                LIMIT 1
            ), pixel_values AS (
                SELECT (ST_PixelAsPolygons(rast)).val as temp FROM clipped
            )
            SELECT
                AVG(temp) as temp_mean,
                MIN(temp) as temp_min,
                MAX(temp) as temp_max
            FROM pixel_values
            WHERE temp IS NOT NULL AND temp > -100 AND temp < 100
        """)
        result = db.execute(query, {"wkt": wkt}).first()

        temp_mean = None
        temp_min = None
        temp_max = None

        if result:
            if result.temp_mean is not None:
                temp_mean = round(result.temp_mean, 2)
            if result.temp_min is not None:
                temp_min = round(result.temp_min, 2)
            if result.temp_max is not None:
                temp_max = round(result.temp_max, 2)

        return {
            "min_temp_coldest_mean_c": temp_mean,
            "min_temp_coldest_min_c": temp_min,
            "min_temp_coldest_max_c": temp_max
        }
    except Exception as e:
        logger.error(f"Error analyzing min temp coldest month for geometry: {e}")
    return {
        "min_temp_coldest_mean_c": None,
        "min_temp_coldest_min_c": None,
        "min_temp_coldest_max_c": None
    }


def analyze_precipitation_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """
    Analyze precipitation data for a specific geometry
    Returns mean, min, and max precipitation values for dynamic legend generation
    """
    try:
        query = text("""
            WITH clipped AS (
                SELECT ST_Clip(rast, ST_GeomFromText(:wkt, 4326)) as rast
                FROM rasters.annual_precipitation WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
                LIMIT 1
            ), pixel_values AS (
                SELECT (ST_PixelAsPolygons(rast)).val as precip FROM clipped
            )
            SELECT
                AVG(precip) as precip_mean,
                MIN(precip) as precip_min,
                MAX(precip) as precip_max
            FROM pixel_values
            WHERE precip IS NOT NULL AND precip >= 0
        """)
        result = db.execute(query, {"wkt": wkt}).first()

        precip_mean = None
        precip_min = None
        precip_max = None

        if result:
            if result.precip_mean is not None:
                precip_mean = round(result.precip_mean, 1)
            if result.precip_min is not None:
                precip_min = round(result.precip_min, 1)
            if result.precip_max is not None:
                precip_max = round(result.precip_max, 1)

        return {
            "precipitation_mean_mm": precip_mean,
            "precipitation_min_mm": precip_min,
            "precipitation_max_mm": precip_max
        }
    except Exception as e:
        logger.error(f"Error analyzing precipitation for geometry: {e}")
    return {
        "precipitation_mean_mm": None,
        "precipitation_min_mm": None,
        "precipitation_max_mm": None
    }


def analyze_soil_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """Analyze soil properties for a specific geometry (WKT) with enhanced analysis

    OPTIMIZED VERSION - Queries each band individually to prevent crashes

    Features:
    1. USDA 12-class texture classification
    2. Soil carbon stock calculation
    3. Fertility assessment
    4. Compaction alert

    8 bands from soilgrids_isric (ISRIC SoilGrids 250m):
    Band 1 = clay_g_kg, Band 2 = sand_g_kg, Band 3 = silt_g_kg, Band 4 = ph_h2o
    Band 5 = soc_dg_kg, Band 6 = nitrogen_cg_kg, Band 7 = bdod_cg_cm3, Band 8 = cec_mmol_kg
    """
    # constraint: SoilGrids 250m resolution v2.0 — ISRIC global soil data
    try:
        logger.info(f"  Starting soil analysis (lightweight centroid sampling)...")

        # CRITICAL FIX: Use ST_Value at centroid instead of ST_Clip
        # ST_Clip on float rasters causes PostgreSQL to crash with large forests
        # Centroid sampling is 1000x faster and safe for all forest sizes

        # Get all 8 bands in a single lightweight query at the centroid
        centroid_query = text("""
            SELECT
                ST_Value(rast, 1, ST_Centroid(ST_GeomFromText(:wkt, 4326))) as clay,
                ST_Value(rast, 2, ST_Centroid(ST_GeomFromText(:wkt, 4326))) as sand,
                ST_Value(rast, 3, ST_Centroid(ST_GeomFromText(:wkt, 4326))) as silt,
                ST_Value(rast, 4, ST_Centroid(ST_GeomFromText(:wkt, 4326))) as ph,
                ST_Value(rast, 5, ST_Centroid(ST_GeomFromText(:wkt, 4326))) as soc,
                ST_Value(rast, 6, ST_Centroid(ST_GeomFromText(:wkt, 4326))) as nitrogen,
                ST_Value(rast, 7, ST_Centroid(ST_GeomFromText(:wkt, 4326))) as bdod,
                ST_Value(rast, 8, ST_Centroid(ST_GeomFromText(:wkt, 4326))) as cec
            FROM rasters.soilgrids_isric
            WHERE ST_Intersects(rast, ST_Centroid(ST_GeomFromText(:wkt, 4326)))
            LIMIT 1
        """)

        result = db.execute(centroid_query, {"wkt": wkt}).first()

        if result:
            clay_mean = result.clay
            sand_mean = result.sand
            silt_mean = result.silt
            ph_mean = result.ph
            soc_mean = result.soc
            nitrogen_mean = result.nitrogen
            bdod_mean = result.bdod
            cec_mean = result.cec
        else:
            clay_mean = sand_mean = silt_mean = None
            ph_mean = soc_mean = nitrogen_mean = None
            bdod_mean = cec_mean = None

        logger.info(f"  Soil data retrieved: clay={clay_mean}, sand={sand_mean}, silt={silt_mean}")

        if clay_mean or sand_mean or silt_mean:
            # FIX: Raster stores values in irregular units - normalize to percentages
            # Raw values: clay ~2, sand ~36, silt ~42 (sum ~80)
            # Need to normalize to 100% for texture classification
            clay_raw = clay_mean if clay_mean else 0
            sand_raw = sand_mean if sand_mean else 0
            silt_raw = silt_mean if silt_mean else 0
            total = clay_raw + sand_raw + silt_raw

            if total > 0:
                # Normalize to 100%
                clay_pct = (clay_raw / total) * 100
                sand_pct = (sand_raw / total) * 100
                silt_pct = (silt_raw / total) * 100
            else:
                clay_pct = sand_pct = silt_pct = 0

            # USDA 12-class texture classification
            soil_texture = classify_usda_texture(clay_pct, sand_pct, silt_pct)

            # FIX: Scale other parameters to match expected units
            # Based on actual raster values analysis:
            ph_scaled = (ph_mean * 10) if ph_mean else None  # 0.57 → 5.7
            soc_scaled = soc_dg_kg_from_raster(soc_mean)
            bdod_scaled = (bdod_mean * 10) if bdod_mean else None  # 12.6 → 126 cg/cm³
            cec_scaled = (cec_mean * 10) if cec_mean else None  # 15.9 → 159 mmol/kg

            # Calculate carbon stock
            carbon_stock = calculate_carbon_stock(soc_scaled, bdod_scaled)

            # Assess fertility
            fertility_data = assess_fertility(ph_scaled, soc_scaled, nitrogen_mean, cec_scaled)

            # Assess compaction
            compaction_data = assess_compaction(bdod_scaled)

            logger.info(f"  Soil analysis complete: texture={soil_texture}, fertility={fertility_data['fertility_class']}")

            # Build basic soil data
            soil_result = {
                "soil_texture": soil_texture,
                "soil_texture_system": "USDA 12-class",
                "carbon_stock_t_ha": carbon_stock,
                "fertility_class": fertility_data["fertility_class"],
                "fertility_score": fertility_data["fertility_score"],
                "limiting_factors": fertility_data["limiting_factors"],
                "compaction_status": compaction_data["compaction_status"],
                "compaction_alert": compaction_data["compaction_alert"],
                "soil_properties": {
                    "clay_pct": round(clay_pct, 1),
                    "sand_pct": round(sand_pct, 1),
                    "silt_pct": round(silt_pct, 1),
                    "ph_h2o": round(ph_scaled, 2) if ph_scaled else None,
                    "soc_dg_kg": round(soc_scaled, 1) if soc_scaled else None,
                    "nitrogen_cg_kg": round(nitrogen_mean, 1) if nitrogen_mean else None,
                    "bulk_density_cg_cm3": round(bdod_scaled, 1) if bdod_scaled else None,
                    "cec_mmol_kg": round(cec_scaled, 1) if cec_scaled else None
                }
            }

            # Generate forester-friendly interpretations
            interpretations = generate_soil_interpretations(soil_result)
            soil_result["interpretations"] = interpretations

            return soil_result
    except Exception as e:
        logger.error(f"  ERROR in soil analysis: {e}")
        db.rollback()  # Rollback on error

    # Return empty result if no data or error
    return {
        "soil_texture": None,
        "soil_texture_system": "USDA 12-class",
        "carbon_stock_t_ha": None,
        "fertility_class": None,
        "fertility_score": None,
        "limiting_factors": ["No soil data available"],
        "compaction_status": None,
        "compaction_alert": None,
        "soil_properties": {}
    }


def analyze_soil_texture_zonal(wkt: str, db: Session) -> Dict[str, Any]:
    """Area-weighted USDA soil-texture % distribution over a geometry (ND-3).

    Clips soilgrids bands 1-3 (clay/sand/silt) to *wkt*, normalizes each valid
    pixel to percentages and classifies it with the same USDA rules
    (classify_usda_texture) that analyze_soil_geometry uses at the centroid,
    weighting every pixel by its clipped polygon area.

    Returns {"soil_percentages": {class: pct}, "soil_dominant_type": class},
    or {} when there is no coverage / the query fails — the caller then leaves
    the keys out of result_data and the plan keeps its honest "no data" marker.
    """
    # constraint: SoilGrids 250m v2.0 — bands 1/2/3 = clay/sand/silt (raw units,
    # normalized to sum 100 per pixel, same as the centroid path)
    try:
        rows = db.execute(
            text(
                """
                WITH clipped AS (
                    SELECT s.rid, ST_Clip(s.rast, ST_GeomFromText(:wkt, 4326), true) AS rast
                    FROM rasters.soilgrids_isric s
                    WHERE ST_Intersects(s.rast, ST_GeomFromText(:wkt, 4326))
                ),
                b1 AS (SELECT rid, x, y, val, geom FROM clipped, LATERAL ST_PixelAsPolygons(rast, 1)),
                b2 AS (SELECT rid, x, y, val FROM clipped, LATERAL ST_PixelAsPolygons(rast, 2)),
                b3 AS (SELECT rid, x, y, val FROM clipped, LATERAL ST_PixelAsPolygons(rast, 3))
                SELECT b1.val AS clay, b2.val AS sand, b3.val AS silt, ST_Area(b1.geom) AS w
                FROM b1
                JOIN b2 ON b2.rid = b1.rid AND b2.x = b1.x AND b2.y = b1.y
                JOIN b3 ON b3.rid = b1.rid AND b3.x = b1.x AND b3.y = b1.y
                WHERE b1.val >= 0 AND b1.val < 1e38
                  AND b2.val >= 0 AND b2.val < 1e38
                  AND b3.val >= 0 AND b3.val < 1e38
                """
            ),
            {"wkt": wkt},
        ).fetchall()
    except Exception as e:  # noqa: BLE001 — no coverage must not abort the analysis
        logger.debug(f"soil texture zonal query failed: {e}", exc_info=True)
        db.rollback()
        return {}

    weights: Dict[str, float] = {}
    for clay_v, sand_v, silt_v, area_v in rows:
        try:
            clay, sand, silt = float(clay_v), float(sand_v), float(silt_v)
        except (TypeError, ValueError):
            continue
        total = clay + sand + silt
        if not (total > 0):  # also rejects NaN (NaN > 0 is False)
            continue
        cls = classify_usda_texture(clay / total * 100.0, sand / total * 100.0, silt / total * 100.0)
        try:
            area = float(area_v or 0.0)
        except (TypeError, ValueError):
            area = 0.0
        weights[cls] = weights.get(cls, 0.0) + (area if area > 0 else 1.0)

    if not weights:
        return {}
    total_w = sum(weights.values())
    if not (total_w > 0):
        return {}
    percentages = {
        k: round(100.0 * v / total_w, 2)
        for k, v in sorted(weights.items(), key=lambda kv: -kv[1])
    }
    return {"soil_percentages": percentages, "soil_dominant_type": max(weights, key=weights.get)}


def analyze_physiography_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """
    Analyze physiographic zones that intersect with geometry
    Returns percentage coverage for each zone (sum = 100%)
    Uses UTM projection for accurate area calculation

    Args:
        wkt: WKT string of geometry
        db: Database session

    Returns:
        Dict with physiography_percentages: {zone_name: percentage}
    """
    # constraint: Nepal physiography 1:500k scale — LRMP (Land Resource Mapping Project) classification
    try:
        # Determine UTM zone from centroid longitude
        centroid_query = text("""
            SELECT ST_X(ST_Centroid(ST_GeomFromText(:wkt, 4326))) as lon
        """)
        centroid_result = db.execute(centroid_query, {"wkt": wkt}).first()
        utm_srid = 32645 if centroid_result.lon > 84 else 32644

        # Calculate intersection areas in UTM projection
        query = text(f"""
            WITH input_geom AS (
                SELECT ST_GeomFromText(:wkt, 4326) as geom
            ),
            total_area AS (
                SELECT ST_Area(ST_Transform(geom, {utm_srid})) as area
                FROM input_geom
            ),
            intersections AS (
                SELECT
                    p."physiography Zone" as zone_name,
                    ST_Area(
                        ST_Transform(
                            ST_Intersection(p.geom, i.geom),
                            {utm_srid}
                        )
                    ) as intersection_area
                FROM admin.physiography p, input_geom i
                WHERE ST_Intersects(p.geom, i.geom)
                AND p."physiography Zone" IS NOT NULL
            )
            SELECT
                zone_name,
                (intersection_area / (SELECT area FROM total_area)) * 100 as percentage
            FROM intersections
            WHERE intersection_area > 0
            ORDER BY percentage DESC
        """)

        results = db.execute(query, {"wkt": wkt}).fetchall()

        if results:
            percentages = {}
            for r in results:
                percentages[r.zone_name] = round(float(r.percentage), 2)

            return {"physiography_percentages": percentages}
    except Exception as e:
        logger.error(f"Error analyzing physiography: {e}")
        import traceback
        traceback.print_exc()

    return {"physiography_percentages": None}


def analyze_ecoregion_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """
    Analyze ecoregions that intersect with geometry
    Returns percentage coverage for each ecoregion (sum = 100%)
    Uses UTM projection for accurate area calculation

    Args:
        wkt: WKT string of geometry
        db: Database session

    Returns:
        Dict with ecoregion_percentages: {eco_name: percentage}
    """
    # constraint: WWF Terrestrial Ecoregions of the World — Nepal ecoregion boundaries
    try:
        # Determine UTM zone from centroid longitude
        centroid_query = text("""
            SELECT ST_X(ST_Centroid(ST_GeomFromText(:wkt, 4326))) as lon
        """)
        centroid_result = db.execute(centroid_query, {"wkt": wkt}).first()
        utm_srid = 32645 if centroid_result.lon > 84 else 32644

        # Calculate intersection areas in UTM projection
        query = text(f"""
            WITH input_geom AS (
                SELECT ST_GeomFromText(:wkt, 4326) as geom
            ),
            total_area AS (
                SELECT ST_Area(ST_Transform(geom, {utm_srid})) as area
                FROM input_geom
            ),
            intersections AS (
                SELECT
                    e.eco_name as ecoregion_name,
                    ST_Area(
                        ST_Transform(
                            ST_Intersection(e.geom, i.geom),
                            {utm_srid}
                        )
                    ) as intersection_area
                FROM ecology.ecoregion e, input_geom i
                WHERE ST_Intersects(e.geom, i.geom)
                AND e.eco_name IS NOT NULL
            )
            SELECT
                ecoregion_name,
                (intersection_area / (SELECT area FROM total_area)) * 100 as percentage
            FROM intersections
            WHERE intersection_area > 0
            ORDER BY percentage DESC
        """)

        results = db.execute(query, {"wkt": wkt}).fetchall()

        if results:
            percentages = {}
            for r in results:
                percentages[r.ecoregion_name] = round(float(r.percentage), 2)

            return {"ecoregion_percentages": percentages}
    except Exception as e:
        logger.error(f"Error analyzing ecoregion: {e}")
        import traceback
        traceback.print_exc()

    return {"ecoregion_percentages": None}


def analyze_nasa_forest_2020_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """
    Analyze NASA forest 2020 classification
    Returns pixel count and percentage for each forest type (sum = 100%)

    Forest types:
    0 = no data (excluded from analysis)
    1 = primary_forest
    2 = young_secondary_forest
    3 = old_secondary_forest
    # constraint: NASA GEDI global forest classification 30m resolution

    Args:
        wkt: WKT string of geometry
        db: Database session

    Returns:
        Dict with nasa_forest_2020_percentages and nasa_forest_2020_dominant
    """
    try:
        forest_type_map = {
            1: "Primary Forest",
            2: "Young Secondary Forest",
            3: "Old Secondary Forest"
        }

        query = text("""
            SELECT
                (pvc).value as forest_class,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) as pvc
                FROM rasters.nasa_forest_2020
                WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
            ) as subquery
            WHERE (pvc).value IS NOT NULL AND (pvc).value BETWEEN 1 AND 3
            GROUP BY forest_class
        """)

        results = db.execute(query, {"wkt": wkt}).fetchall()

        if results:
            total_pixels = sum(r.pixel_count for r in results)
            percentages = {}
            dominant = None
            max_pct = 0

            for r in results:
                class_code = int(r.forest_class)
                if class_code in forest_type_map:
                    pct = (r.pixel_count / total_pixels * 100) if total_pixels > 0 else 0
                    class_name = forest_type_map[class_code]
                    percentages[class_name] = round(pct, 2)

                    if pct > max_pct:
                        max_pct = pct
                        dominant = class_name

            return {
                "nasa_forest_2020_percentages": percentages,
                "nasa_forest_2020_dominant": dominant
            }
    except Exception as e:
        logger.error(f"Error analyzing NASA forest 2020: {e}")
        import traceback
        traceback.print_exc()

    return {
        "nasa_forest_2020_percentages": None,
        "nasa_forest_2020_dominant": None
    }


def analyze_landcover_1984_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """
    Analyze 1984 landcover using vector polygon intersection

    This analyzes historical land cover from 1984 vector data (landcover schema)
    Uses spatial intersection to calculate area of each landcover type within boundary

    Returns:
        landcover_1984_dominant: Most common landcover type by area
        landcover_1984_percentages: Percentage breakdown by landcover type
    """
    try:
        from app.core.landcover_1984 import normalize_lc1984

        # One row per class (grouped + summed), area via ::geography — the old
        # query returned one row per polygon and the dict build kept only the
        # last polygon of each class, so a forest read back as ~0 %.
        query = text("""
            WITH b AS (SELECT ST_GeomFromText(:wkt, 4326) AS g)
            SELECT lc.landuse_yr1984 AS landcover_type,
                   SUM(ST_Area(ST_Intersection(lc.geom, b.g)::geography)) AS m2
            FROM landcover.landcover_1984 lc, b
            WHERE ST_Intersects(lc.geom, b.g)
            GROUP BY lc.landuse_yr1984
        """)
        results = db.execute(query, {"wkt": wkt}).fetchall()
        if not results:
            return {"landcover_1984_dominant": None, "landcover_1984_percentages": {}}

        by_canon: Dict[str, float] = {}
        for r in results:
            canon = normalize_lc1984(r.landcover_type)
            if canon and (r.m2 or 0) > 0:
                by_canon[canon] = by_canon.get(canon, 0.0) + float(r.m2)

        total = sum(by_canon.values())
        if total <= 0:
            return {"landcover_1984_dominant": None, "landcover_1984_percentages": {}}

        landcover_percentages = {
            c: round(v / total * 100.0, 2)
            for c, v in sorted(by_canon.items(), key=lambda kv: kv[1], reverse=True)
        }
        dominant_type = next(iter(landcover_percentages), None)

        return {
            "landcover_1984_dominant": dominant_type,
            "landcover_1984_percentages": landcover_percentages,
        }

    except Exception as e:
        logger.error(f"Error analyzing landcover 1984 for geometry: {e}")
        import traceback
        traceback.print_exc()

    return {"landcover_1984_dominant": None, "landcover_1984_percentages": {}}


def analyze_hansen2000_geometry(wkt: str, db: Session) -> Dict[str, Any]:
    """
    Analyze Hansen 2000 forest classification (raster)

    Hansen 2000 Classified Forest Data from rasters.hansen2000_classified
    Legend:
        0 = Non forest
        1 = Bush/Shrub
        2 = Poor forest
        3 = Moderate forest
        4 = Good forest
    # constraint: Hansen Global Forest Change v1.11 — tree cover threshold 30% for forest definition

    Returns:
        hansen2000_dominant: Most common forest class by pixel count
        hansen2000_percentages: Percentage breakdown by forest class
    """
    try:
        forest_class_map = {
            0: "Non forest",
            1: "Bush/Shrub",
            2: "Poor forest",
            3: "Moderate forest",
            4: "Good forest"
        }

        query = text("""
            SELECT
                (pvc).value as forest_class,
                SUM((pvc).count) as pixel_count
            FROM (
                SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) as pvc
                FROM rasters.hansen2000_classified
                WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
            ) as subquery
            WHERE (pvc).value IS NOT NULL AND (pvc).value BETWEEN 0 AND 4
            GROUP BY forest_class
            ORDER BY pixel_count DESC
        """)

        results = db.execute(query, {"wkt": wkt}).fetchall()

        if not results:
            return {"hansen2000_dominant": None, "hansen2000_percentages": {}}

        total_pixels = sum(r.pixel_count for r in results)
        percentages = {}
        dominant_class = None
        max_percentage = 0

        for r in results:
            class_code = int(r.forest_class)
            if class_code in forest_class_map:
                percentage = (r.pixel_count / total_pixels * 100) if total_pixels > 0 else 0
                class_name = forest_class_map[class_code]
                percentages[class_name] = round(percentage, 2)

                if percentage > max_percentage:
                    max_percentage = percentage
                    dominant_class = class_name

        return {
            "hansen2000_dominant": dominant_class,
            "hansen2000_percentages": percentages
        }

    except Exception as e:
        logger.error(f"Error analyzing Hansen 2000 for geometry: {e}")
        import traceback
        traceback.print_exc()

    return {"hansen2000_dominant": None, "hansen2000_percentages": {}}


def analyze_potential_tree_species(forest_type_percentages: Dict[str, float], db: Session) -> Dict[str, Any]:
    """
    Analyze potential tree species based on forest type distribution

    Uses forest_type → species associations to suggest likely species for a block/forest
    Orders species by:
    1. Availability rank (Dominant > Co-dominant > Associate > Occasional)
    2. Economic value (high-value timber species prioritized)
    3. Frequency in the forest type

    # business: CFMG §4.2 — species suitability determined by forest type and elevation zone

    Args:
        forest_type_percentages: Dict of {forest_type_name: percentage}
        db: Database session

    Returns:
        {
            "potential_species": [
                {
                    "scientific_name": str,
                    "local_name": str,
                    "role": str (Dominant/Co-dominant/Associate/Occasional),
                    "availability_rank": int (1-4),
                    "forest_types": [str] (which forest types this species is found in),
                    "combined_score": float (for ranking),
                    "economic_value": str (High/Medium/Low)
                }
            ],
            "species_count": int
        }
    """
    try:
        if not forest_type_percentages:
            return {"potential_species": [], "species_count": 0}

        # Define high-value timber species in Nepal
        HIGH_VALUE_SPECIES = {
            'Shorea robusta', 'Dalbergia sissoo', 'Tectona grandis', 'Acacia catechu',
            'Cedrus deodara', 'Pinus roxburghii', 'Alnus nepalensis', 'Juglans regia',
            'Cedrela toona', 'Michelia champaca'
        }

        MEDIUM_VALUE_SPECIES = {
            'Schima wallichii', 'Castanopsis indica', 'Terminalia spp', 'Albizia spp',
            'Bombax ceiba', 'Adina cardifolia', 'Lagerstroemia parviflora'
        }

        # Get forest type names and normalize them
        # Database has " Forest" suffix, but analysis may not
        forest_type_names = []
        for ft_name in forest_type_percentages.keys():
            # Add " Forest" suffix if not already present
            if not ft_name.endswith(" Forest") and not ft_name.endswith(" forest"):
                forest_type_names.append(ft_name + " Forest")
            else:
                forest_type_names.append(ft_name)

        query = text("""
            SELECT
                ft.forest_type_name,
                tsc.scientific_name,
                tsc.local_name,
                fsa.availability_rank,
                fsa.role,
                fsa.frequency_percent,
                fsa.canopy_coverage_percent,
                tsc.growth_rate,
                tsc.min_altitude_m,
                tsc.max_altitude_m,
                tsc.main_uses,
                tsc.nitrogen_fixing,
                tsc.rarity_status,
                tsc.family,
                tsc.economic_value as stored_economic_value,
                tsc.is_tree_species
            FROM forest_species_association fsa
            JOIN forest_types ft ON fsa.forest_type_id = ft.id
            JOIN tree_species_coefficients tsc ON fsa.species_id = tsc.id
            WHERE ft.forest_type_name = ANY(:forest_types)
            ORDER BY fsa.availability_rank, fsa.frequency_percent DESC NULLS LAST
        """)

        results = db.execute(query, {"forest_types": forest_type_names}).fetchall()

        results = db.execute(query, {"forest_types": forest_type_names}).fetchall()

        if not results:
            return {"potential_species": [], "species_count": 0}

        # Aggregate species data across all forest types
        species_data = {}

        for r in results:
            scientific_name = r.scientific_name

            if scientific_name not in species_data:
                # Determine economic value
                if any(scientific_name.startswith(hvs.split()[0]) for hvs in HIGH_VALUE_SPECIES):
                    economic_value = "High"
                    value_score = 3
                elif any(scientific_name.startswith(mvs.split()[0]) for mvs in MEDIUM_VALUE_SPECIES):
                    economic_value = "Medium"
                    value_score = 2
                else:
                    economic_value = "Low"
                    value_score = 1

                species_data[scientific_name] = {
                    "scientific_name": scientific_name,
                    "local_name": r.local_name or "Unknown",
                    "role": r.role,
                    "availability_rank": r.availability_rank,
                    "economic_value": r.stored_economic_value or economic_value,
                    "forest_types": [r.forest_type_name],
                    "frequency_percent": r.frequency_percent or 0,
                    "value_score": value_score,
                    "growth_rate": r.growth_rate,
                    "min_altitude_m": r.min_altitude_m,
                    "max_altitude_m": r.max_altitude_m,
                    "main_uses": r.main_uses,
                    "nitrogen_fixing": r.nitrogen_fixing or False,
                    "rarity_status": r.rarity_status or "Common",
                    "family": r.family,
                    "is_tree_species": r.is_tree_species if hasattr(r, 'is_tree_species') else True
                }
            else:
                # Species appears in multiple forest types - update
                if r.forest_type_name not in species_data[scientific_name]["forest_types"]:
                    species_data[scientific_name]["forest_types"].append(r.forest_type_name)

                # Use the best (lowest) availability rank
                if r.availability_rank < species_data[scientific_name]["availability_rank"]:
                    species_data[scientific_name]["availability_rank"] = r.availability_rank
                    species_data[scientific_name]["role"] = r.role

        # Calculate combined score for sorting
        # Lower score = higher priority
        # Score = availability_rank * 10 - value_score * 3 - (frequency_percent/10)
        for species in species_data.values():
            species["combined_score"] = (
                species["availability_rank"] * 10  # Lower rank = better (10-40)
                - species["value_score"] * 3  # Higher value = better (-9 to -3)
                - (species["frequency_percent"] / 10)  # Higher frequency = better (-10 to 0)
            )

        # Sort by combined score (lower is better)
        sorted_species = sorted(species_data.values(), key=lambda x: x["combined_score"])

        # Remove internal scoring fields from output
        for species in sorted_species:
            del species["value_score"]
            del species["combined_score"]
            del species["frequency_percent"]

        return {
            "potential_species": sorted_species,
            "species_count": len(sorted_species)
        }

    except Exception as e:
        logger.error(f"Error analyzing potential tree species: {e}")
        import traceback
        traceback.print_exc()
        return {"potential_species": [], "species_count": 0}
