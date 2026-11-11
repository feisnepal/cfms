"""
Compartment management API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from uuid import UUID
from shapely.geometry import mapping
import logging
import os
import json
import tempfile
from pathlib import Path
from datetime import datetime

from ..core.database import get_db
from ..core.constants import SQM_PER_HA
from ..core.exceptions import i18n_error, i18n_success, resolve_service_detail
from ..utils.auth import get_current_user
from ..utils.audit import append_audit_entry
from ..models.user import User
from ..models.calculation import Calculation
from ..models.forest_block import ForestBlock, child_inherit_kwargs
from ..models.compartment import CompartmentSplitHistory
from ..models.inventory import InventoryTree
from ..models.sampling import SamplingDesign
from ..schemas.compartment import (
    SplitPreviewRequest,
    SplitPreviewResponse,
    ExecuteSplitRequest,
    ExecuteSplitResponse,
    SplitDirection,
    AvailableBlock,
    TreeReassignmentRequest,
    TreeReassignmentResponse,
    CompartmentPreview,
    SplitValidation
)
from ..services.compartment_splitter import CompartmentSplitter, COMPARTMENT_COLORS
from ..services.tree_reassignment import (
    get_trees_needing_assignment,
    auto_assign_trees_by_location,
    manual_assign_trees
)
from app.core.dbh_classifier import DbhClassRegistry
from ..services.geometry_utils import (
    postgis_to_shapely,
    shapely_to_postgis,
    polygon_to_geojson,
    calculate_area_sqm,
    calculate_perimeter_m
)
from ..services.forest_units.model import (
    DEPTH_STEP,
    DEPTH_SUB,
    DEPTH_TOP_COMPARTMENT,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# (column in the file, key in the feature's properties, type to coerce to)
#
# Kept exactly as fiona wrote them. These are DBF-era 10-character names and
# GPKG has no such limit, but anything already consuming these exports reads
# THESE names, so renaming them would break consumers for tidiness.
GPKG_FIELDS = [
    ("id", "id", str),
    ("block_name", "block_name", str),
    ("parent_bl", "parent_block_name", str),
    ("is_compart", "is_compartment", int),
    ("comp_code", "compartment_code", str),
    ("area_sqm", "area_sqm", float),
    ("area_ha", "area_hectares", float),
    ("perimeter_m", "perimeter_m", float),
    ("tree_count", "tree_count", int),
    ("mother_tr", "mother_tree", int),
    ("felling_tr", "felling_tree", int),
    ("regen", "regeneration", int),
    ("sapling", "sapling", int),
    ("small_pol", "small_pole", int),
    ("large_pol", "large_pole", int),
    ("small_tr", "small_tree", int),
    ("medium_tr", "medium_tree", int),
    ("large_tr", "large_tree", int),
    ("vlarge_tr", "very_large_tree", int),
    ("index", "index", int),
    ("created_at", "created_at", str),
]


def write_blocks_gpkg(features, filepath) -> None:
    """Write block features to a GeoPackage using pyogrio.

    A module-level function rather than inline in the endpoint so it can be
    tested. The endpoint wraps this call in `except Exception` and falls back
    to GeoJSON, which means a failure here does NOT surface as an error -- the
    caller still gets 200, just a different file format. That is precisely the
    branch a bad refactor would hide in, so the behaviour needs a test that
    does not go through the fallback.
    """
    import geopandas as gpd
    from shapely.geometry import shape

    records = []
    geometries = []
    for feature in features:
        props = feature["properties"]
        row = {}
        for column, key, cast in GPKG_FIELDS:
            value = props.get(key)
            # Coerce explicitly. fiona enforced these types through its schema;
            # pandas would otherwise infer, and one None in an integer column
            # silently turns the whole column into floats -- so `tree_count`
            # would come back as 12.0 rather than 12.
            if value is None:
                row[column] = "" if cast is str else cast(0)
            else:
                row[column] = cast(value)
        records.append(row)
        geometries.append(shape(feature["geometry"]))

    gdf = gpd.GeoDataFrame(records, geometry=geometries, crs="EPSG:4326")
    gdf.to_file(filepath, driver="GPKG", engine="pyogrio")


def _recheck_dimension_after_delete(
    db: Session,
    calculation_id: UUID,
    current_user: User,
) -> None:
    """After deleting compartments, check if any remain. If none, clear
    result_data['compartments'] and update the dimension back to 'block'.
    """
    remaining = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calculation_id,
        ForestBlock.is_compartment == True
    ).count()

    if remaining == 0:
        calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        if calc and calc.result_data:
            result_data = dict(calc.result_data)
            if 'compartments' in result_data:
                del result_data['compartments']
                result_data = append_audit_entry(
                    result_data,
                    current_user.id,
                    current_user.email or current_user.username or 'unknown',
                    'dimension_revert',
                    'compartment',
                    'block',
                    'compartment_delete',
                    calculation_id,
                )
                calc.result_data = result_data
                try:
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(calc, 'result_data')
                except ImportError:
                    pass


# business: CFMG — compartments split by natural boundaries, species composition, and density
@router.get("/available-blocks/{calculation_id}", response_model=List[AvailableBlock])
def get_available_blocks(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all forest blocks available for splitting

    Args:
        calculation_id: Calculation UUID
        db: Database session
        current_user: Authenticated user

    Returns:
        List of forest blocks with metadata
    """
    try:
        from app.models.inventory import InventoryCalculation
        
        # Get total trees in calculation (through inventory_calculation) - only user's trees linked to this calculation
        total_trees_in_calc = db.query(InventoryTree).join(
            InventoryCalculation, InventoryCalculation.id == InventoryTree.inventory_calculation_id
        ).filter(
            InventoryCalculation.calculation_id == calculation_id,
            InventoryCalculation.user_id == current_user.id
        ).count()
        
        # Get parent blocks (not compartments)
        blocks = db.query(ForestBlock).filter(
            ForestBlock.calculation_id == calculation_id,
            (ForestBlock.is_compartment == False) | (ForestBlock.is_compartment.is_(None))
        ).all()
        logger.info(f"Compartment API: {len(blocks)} parent blocks after filtering")

        result = []
        for block in blocks:
            # Count trees in this block (direct assignment)
            tree_count = db.query(InventoryTree).filter(
                InventoryTree.block_id == block.id
            ).count()

            # Check if block already has compartments
            compartment_count = db.query(ForestBlock).filter(
                ForestBlock.parent_block_id == block.id,
                ForestBlock.is_compartment == True
            ).count()

            has_compartments = compartment_count > 0

            # Convert geometry to GeoJSON
            block_geom = postgis_to_shapely(block.geometry)
            geojson = polygon_to_geojson(block_geom)

            # Calculate area using PostGIS
            area_result = db.execute(
                text("SELECT ST_Area(geography(geometry)) as area FROM forest_blocks WHERE id = :block_id"),
                {"block_id": str(block.id)}
            ).scalar()
            area_sqm = float(area_result) if area_result else (block.area_sqm or 0)

            result.append({
                "id": block.id,
                "name": block.name,
                "area_sqm": area_sqm,
                "area_hectares": float(block.area_hectares or 0),
                "geometry": geojson,
                "has_compartments": has_compartments,
                "tree_count": tree_count,
                "total_trees_in_calculation": total_trees_in_calc,
                "compartment_count": compartment_count
            })

        return result

    except Exception as e:
        logger.error(f"Failed to get available blocks: {e}")
        raise i18n_error(500, "compartments.failed_get_divisions", error=str(e))


# why: single optimized SQL query with CTE to avoid N+1 on map display
@router.get("/calculation/{calculation_id}/all-blocks")
def get_all_blocks_for_map(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all forest blocks and compartments for map display

    Args:
        calculation_id: Calculation UUID
        db: Database session
        current_user: Authenticated user

    Returns:
        List of all forest blocks with metadata
    """
    try:
        # Single optimized query with all aggregations to avoid N+1
        blocks_query = text("""
            WITH 
                block_stats AS (
                    SELECT 
                        fb.id,
                        fb.name,
                        fb.is_compartment,
                        fb.parent_block_id,
                        fb.compartment_code,
                        fb.area_hectares,
                        fb.index,
                        fb.area_sqm,
                        fb.color,
                        COALESCE(fb.area_sqm, ST_Area(geography(fb.geometry))) as calculated_area,
                        pb.name as parent_block_name,
                        COUNT(it.id)::int as tree_count,
                        COUNT(DISTINCT CASE WHEN fb2.id IS NOT NULL THEN fb2.id END)::int as compartment_count,
                        CASE WHEN EXISTS (SELECT 1 FROM forest_blocks fb3 WHERE fb3.parent_block_id = fb.id AND fb3.is_compartment = true) THEN true ELSE false END as has_compartments
                    FROM forest_blocks fb
                    LEFT JOIN forest_blocks pb ON fb.parent_block_id = pb.id
                    LEFT JOIN inventory_trees it ON it.block_id = fb.id
                    LEFT JOIN forest_blocks fb2 ON fb2.parent_block_id = fb.id AND fb2.is_compartment = true
                    WHERE fb.calculation_id = :calc_id
                    GROUP BY fb.id, fb.name, fb.is_compartment, fb.parent_block_id, 
                             fb.compartment_code, fb.area_hectares, fb.index, fb.area_sqm, fb.color, pb.name
                )
            SELECT 
                bs.*,
                ST_AsGeoJSON(fb.geometry) as geojson
            FROM block_stats bs
            JOIN forest_blocks fb ON fb.id = bs.id
            ORDER BY bs.index
        """)
        
        result = db.execute(blocks_query, {"calc_id": str(calculation_id)}).fetchall()
        
        blocks_list = []
        for row in result:
            blocks_list.append({
                "id": row.id,
                "name": row.name,
                "area_sqm": float(row.calculated_area) if row.calculated_area else (row.area_sqm or 0),
                "area_hectares": float(row.area_hectares or 0),
                "geometry": json.loads(row.geojson) if row.geojson else None,
                "has_compartments": row.has_compartments,
                "tree_count": row.tree_count,
                "compartment_count": row.compartment_count,
                "is_compartment": row.is_compartment,
                "parent_block_name": row.parent_block_name,
                "compartment_code": row.compartment_code,
                "color": row.color,
                "index": row.index
            })
        
        return blocks_list

    except Exception as e:
        logger.error(f"Failed to get all blocks: {e}")
        raise i18n_error(500, "compartments.failed_get_divisions", error=str(e))


@router.get("/calculation/{calculation_id}/export-gpkg")
def export_blocks_gpkg(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Export all forest blocks and compartments to GPKG format

    Args:
        calculation_id: Calculation UUID
        db: Database session
        current_user: Authenticated user

    Returns:
        GPKG file download
    """
    try:
        from shapely.geometry import shape
        from geoalchemy2.shape import to_shape
        
        # Get all blocks (both parent blocks and compartments)
        all_blocks = db.query(ForestBlock).filter(
            ForestBlock.calculation_id == calculation_id
        ).all()

        if not all_blocks:
            raise i18n_error(404, "compartments.no_divisions_for_calculation")

        from app.utils.file_export import build_disposition

        # Get forest name for filename
        from app.models.calculation import Calculation
        calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        forest_name = calculation.forest_name if calculation else None

        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        _, disposition = build_disposition(forest_name, "Compartment", "Spatial", "gpkg")
        filename = _.replace(" ", "_")  # use the filename from build_disposition
        filepath = os.path.join(temp_dir, filename)

        # Prepare features
        features = []
        for block in all_blocks:
            try:
                # Convert geometry to shapely object
                geom_obj = to_shape(block.geometry)
                
                area_result = db.execute(
                    text("SELECT ST_Area(geography(geometry)) as area FROM forest_blocks WHERE id = :block_id"),
                    {"block_id": str(block.id)}
                ).scalar()
                
                perimeter_result = db.execute(
                    text("SELECT ST_Perimeter(geography(geometry)) as perimeter FROM forest_blocks WHERE id = :block_id"),
                    {"block_id": str(block.id)}
                ).scalar()
                
                block_geom = db.execute(
                    text("SELECT geometry FROM forest_blocks WHERE id = :block_id"),
                    {"block_id": str(block.id)}
                ).scalar()

                tree_count = 0
                dbh_classes = {}
                mother_trees_count = 0
                felling_trees_count = 0
                if block_geom:
                    counts = db.execute(text("""
                        SELECT
                            COUNT(*) as total,
                            COUNT(*) FILTER (WHERE dia_cm < 4) as regeneration,
                            COUNT(*) FILTER (WHERE dia_cm >= 4 AND dia_cm < 10) as sapling,
                            COUNT(*) FILTER (WHERE dia_cm >= 10 AND dia_cm < 20) as small_pole,
                            COUNT(*) FILTER (WHERE dia_cm >= 20 AND dia_cm < 30) as large_pole,
                            COUNT(*) FILTER (WHERE dia_cm >= 30 AND dia_cm < 40) as small_tree,
                            COUNT(*) FILTER (WHERE dia_cm >= 40 AND dia_cm < 50) as medium_tree,
                            COUNT(*) FILTER (WHERE dia_cm >= 50 AND dia_cm < 60) as large_tree,
                            COUNT(*) FILTER (WHERE dia_cm >= 60) as very_large_tree,
                            COUNT(*) FILTER (WHERE remark = 'Mother Tree') as mother_trees,
                            COUNT(*) FILTER (WHERE remark = 'Felling Tree') as felling_trees
                        FROM inventory_trees t
                        JOIN inventory_calculations ic ON ic.id = t.inventory_calculation_id
                        WHERE ST_Intersects(t.location, :block_geom)
                          AND ic.calculation_id = :calc_id
                    """), {"block_geom": block_geom, "calc_id": str(calculation_id)}).first()

                    if counts:
                        tree_count = counts.total or 0
                        dbh_classes = {
                            'Regeneration': counts.regeneration or 0,
                            'Sapling': counts.sapling or 0,
                            'Small_pole': counts.small_pole or 0,
                            'Large_pole': counts.large_pole or 0,
                            'Small_tree': counts.small_tree or 0,
                            'Medium_tree': counts.medium_tree or 0,
                            'Large_tree': counts.large_tree or 0,
                            'Very_large_tree': counts.very_large_tree or 0,
                        }
                        mother_trees_count = counts.mother_trees or 0
                        felling_trees_count = counts.felling_trees or 0

                parent_name = None
                if block.parent_block_id:
                    parent_block = db.query(ForestBlock).filter(
                        ForestBlock.id == block.parent_block_id
                    ).first()
                    if parent_block:
                        parent_name = parent_block.name

                feature = {
                    "type": "Feature",
                    "geometry": mapping(geom_obj),
                    "properties": {
                        "id": str(block.id),
                        "block_name": block.name,
                        "parent_block_name": parent_name or "",
                        "is_compartment": 1 if block.is_compartment else 0,
                        "compartment_code": block.compartment_code or "",
                        "area_sqm": float(area_result) if area_result else (block.area_sqm or 0),
                        "area_hectares": float(block.area_hectares or 0),
                        "perimeter_m": float(perimeter_result) if perimeter_result else 0,
                        "tree_count": tree_count,
                        "mother_tree": mother_trees_count,
                        "felling_tree": felling_trees_count,
                        "regeneration": dbh_classes.get('Regeneration', 0),
                        "sapling": dbh_classes.get('Sapling', 0),
                        "small_pole": dbh_classes.get('Small_pole', 0),
                        "large_pole": dbh_classes.get('Large_pole', 0),
                        "small_tree": dbh_classes.get('Small_tree', 0),
                        "medium_tree": dbh_classes.get('Medium_tree', 0),
                        "large_tree": dbh_classes.get('Large_tree', 0),
                        "very_large_tree": dbh_classes.get('Very_large_tree', 0),
                        "index": block.index or 0,
                        "created_at": block.created_at.isoformat() if block.created_at else ""
                    }
                }
                features.append(feature)
            except Exception as geom_err:
                logger.error(f"Failed to process block {block.id}: {geom_err}")
                logger.exception("Failed to process block geometry")
                continue

        if not features:
            raise i18n_error(500, "compartments.failed_process_areas")

        # H2.12 / security-scan: written with pyogrio, not fiona.
        #
        # fiona 1.9.5 carried a CRITICAL (CVE-2023-45853, bundled MiniZip) and a
        # HIGH, and Trivy fails the build on both. This was its ONLY use in the
        # codebase, and `pyogrio` -- geopandas' default engine -- was already a
        # dependency doing the same job through the same GDAL. So fiona is gone
        # from requirements.in entirely rather than bumped: that removes the
        # finding permanently instead of chasing the next advisory, and drops a
        # compiled dependency the project did not need.
        #
        # Bumping was the riskier option, which is not obvious. `from_epsg` is
        # deprecated, and if it disappeared in 1.10 this code would have fallen
        # into the `except Exception` below -- still answering 200, but handing
        # the user a GeoJSON named .geojson instead of the GPKG they asked for.
        # The test added alongside this (test_compartment_gpkg_export.py) asserts
        # the bytes really are a GeoPackage, so that failure mode is now visible.
        #
        # The short field names are kept exactly as fiona wrote them. They are
        # DBF-era 10-character names and GPKG has no such limit, but anything
        # already consuming these exports reads THESE names.
        try:
            write_blocks_gpkg(features, filepath)
            logger.info(f"Exported {len(features)} blocks to GPKG: {filepath}")
            
        except ImportError as e:
            # Kept as a real fallback: an export that degrades beats one that
            # 500s. But it is logged at ERROR with a traceback, because the
            # caller asked for a GeoPackage and is getting something else --
            # the filename changes to .geojson, which is the only signal they
            # get. Silence here is what would have hidden a fiona API break.
            logger.error(
                "GPKG engine unavailable (%s) - falling back to GeoJSON. The "
                "caller asked for .gpkg and is receiving .geojson.", e,
                exc_info=True,
            )
            filename = filename.replace('.gpkg', '.geojson')
            filepath = os.path.join(temp_dir, filename)
            import json
            with open(filepath, 'w') as f:
                json.dump({"type": "FeatureCollection", "features": features}, f)
            _, disposition = build_disposition(forest_name, "Compartment", "Spatial", "geojson")
            
        except Exception as gpkg_err:
            # Same reasoning as the ImportError above. This is the branch that
            # would have swallowed a fiona 1.10 API break into a silent format
            # change, so it says so loudly and carries the traceback.
            logger.error(
                "GPKG export failed (%s) - falling back to GeoJSON. The caller "
                "asked for .gpkg and is receiving .geojson.", gpkg_err,
                exc_info=True,
            )
            filename = filename.replace('.gpkg', '.geojson')
            filepath = os.path.join(temp_dir, filename)
            import json
            with open(filepath, 'w') as f:
                json.dump({"type": "FeatureCollection", "features": features}, f)
            _, disposition = build_disposition(forest_name, "Compartment", "Spatial", "geojson")
        
        return FileResponse(
            filepath,
            media_type='application/octet-stream',
            filename=filename,
            headers={"Content-Disposition": disposition}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export GPKG: {e}")
        raise i18n_error(500, "editing.export_failed", error=str(e))


@router.get("/calculation/{calculation_id}/export-kml")
def export_blocks_kml(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Export all forest blocks and compartments to KML format

    Args:
        calculation_id: Calculation UUID
        db: Database session
        current_user: Authenticated user

    Returns:
        KML file download
    """
    try:
        from shapely.geometry import shape
        from geoalchemy2.shape import to_shape
        
        # Get all blocks
        all_blocks = db.query(ForestBlock).filter(
            ForestBlock.calculation_id == calculation_id
        ).all()

        if not all_blocks:
            raise i18n_error(404, "compartments.no_divisions_for_calculation")

        # Get forest name for filename
        from app.models.calculation import Calculation
        calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        forest_name = calculation.forest_name if calculation else "forest"

        # Build features data
        features_data = []
        for block in all_blocks:
            try:
                # Convert geometry to shapely object
                geom_obj = to_shape(block.geometry)
                
                # Get area using PostGIS
                area_result = db.execute(
                    text("SELECT ST_Area(geography(geometry)) as area FROM forest_blocks WHERE id = :block_id"),
                    {"block_id": str(block.id)}
                ).scalar()
                
                # Get perimeter
                perimeter_result = db.execute(
                    text("SELECT ST_Perimeter(geography(geometry)) as perimeter FROM forest_blocks WHERE id = :block_id"),
                    {"block_id": str(block.id)}
                ).scalar()
                
                block_geom = db.execute(
                    text("SELECT geometry FROM forest_blocks WHERE id = :block_id"),
                    {"block_id": str(block.id)}
                ).scalar()

                tree_count = 0
                dbh_classes = {}
                mother_trees_count = 0
                felling_trees_count = 0
                if block_geom:
                    counts = db.execute(text("""
                        SELECT
                            COUNT(*) as total,
                            COUNT(*) FILTER (WHERE dia_cm < 4) as regeneration,
                            COUNT(*) FILTER (WHERE dia_cm >= 4 AND dia_cm < 10) as sapling,
                            COUNT(*) FILTER (WHERE dia_cm >= 10 AND dia_cm < 20) as small_pole,
                            COUNT(*) FILTER (WHERE dia_cm >= 20 AND dia_cm < 30) as large_pole,
                            COUNT(*) FILTER (WHERE dia_cm >= 30 AND dia_cm < 40) as small_tree,
                            COUNT(*) FILTER (WHERE dia_cm >= 40 AND dia_cm < 50) as medium_tree,
                            COUNT(*) FILTER (WHERE dia_cm >= 50 AND dia_cm < 60) as large_tree,
                            COUNT(*) FILTER (WHERE dia_cm >= 60) as very_large_tree,
                            COUNT(*) FILTER (WHERE remark = 'Mother Tree') as mother_trees,
                            COUNT(*) FILTER (WHERE remark = 'Felling Tree') as felling_trees
                        FROM inventory_trees t
                        JOIN inventory_calculations ic ON ic.id = t.inventory_calculation_id
                        WHERE ST_Intersects(t.location, :block_geom)
                          AND ic.calculation_id = :calc_id
                    """), {"block_geom": block_geom, "calc_id": str(calculation_id)}).first()

                    if counts:
                        tree_count = counts.total or 0
                        dbh_classes = {
                            'Regeneration': counts.regeneration or 0,
                            'Sapling': counts.sapling or 0,
                            'Small_pole': counts.small_pole or 0,
                            'Large_pole': counts.large_pole or 0,
                            'Small_tree': counts.small_tree or 0,
                            'Medium_tree': counts.medium_tree or 0,
                            'Large_tree': counts.large_tree or 0,
                            'Very_large_tree': counts.very_large_tree or 0,
                        }
                        mother_trees_count = counts.mother_trees or 0
                        felling_trees_count = counts.felling_trees or 0

                # Get parent block name
                parent_name = None
                if block.parent_block_id:
                    parent_block = db.query(ForestBlock).filter(
                        ForestBlock.id == block.parent_block_id
                    ).first()
                    if parent_block:
                        parent_name = parent_block.name

                features_data.append({
                    'name': block.name,
                    'geometry': mapping(geom_obj),
                    'area_sqm': float(area_result) if area_result else (block.area_sqm or 0),
                    'area_hectares': float(block.area_hectares or 0),
                    'perimeter_m': float(perimeter_result) if perimeter_result else 0,
                    'tree_count': tree_count,
                    'mother_tree': mother_trees_count,
                    'felling_tree': felling_trees_count,
                    'regeneration': dbh_classes.get('Regeneration', 0),
                    'sapling': dbh_classes.get('Sapling', 0),
                    'small_pole': dbh_classes.get('Small_pole', 0),
                    'large_pole': dbh_classes.get('Large_pole', 0),
                    'small_tree': dbh_classes.get('Small_tree', 0),
                    'medium_tree': dbh_classes.get('Medium_tree', 0),
                    'large_tree': dbh_classes.get('Large_tree', 0),
                    'very_large_tree': dbh_classes.get('Very_large_tree', 0),
                    'is_compartment': block.is_compartment,
                    'compartment_code': block.compartment_code,
                    'parent_block_name': parent_name,
                    'index': block.index
                })
            except Exception as geom_err:
                logger.error(f"Failed to process block {block.id}: {geom_err}")
                logger.exception("Failed to process block geometry")
                continue

        if not features_data:
            raise i18n_error(500, "compartments.failed_process_areas")

        from app.utils.file_export import build_disposition

        # Generate KML
        _, disposition = build_disposition(forest_name, "Compartment", "Spatial", "kml")
        filename = _.replace(" ", "_")  # use the filename from build_disposition
        
        kml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{forest_name}</name>
    <description>Forest Blocks and Compartments Export</description>
    <Style id="blockStyle">
      <LineStyle>
        <color>ff0000ff</color>
        <width>2</width>
      </LineStyle>
      <PolyStyle>
        <color>4d0099ff</color>
        <fill>1</fill>
      </PolyStyle>
    </Style>
    <Style id="compartmentStyle">
      <LineStyle>
        <color>ff00ff00</color>
        <width>2</width>
      </LineStyle>
      <PolyStyle>
        <color>4d00ff00</color>
        <fill>1</fill>
      </PolyStyle>
    </Style>
'''.format(forest_name=forest_name)

        for feature in features_data:
            geom = feature['geometry']
            coords = geom['coordinates'][0] if geom['type'] == 'Polygon' else geom['coordinates']
            
            # Format coordinates for KML (lon,lat,alt)
            coord_str = ' '.join([f"{c[0]},{c[1]},0" for c in coords])
            
            style_url = '#compartmentStyle' if feature['is_compartment'] else '#blockStyle'
            
            kml_content += f'''    <Placemark>
      <name>{feature['name']}</name>
      <styleUrl>{style_url}</styleUrl>
      <ExtendedData>
        <Data name="Area_sqm"><value>{feature['area_sqm']:,.2f}</value></Data>
        <Data name="Area_ha"><value>{feature['area_hectares']:.4f}</value></Data>
        <Data name="Perimeter_m"><value>{feature['perimeter_m']:,.2f}</value></Data>
        <Data name="Tree_count"><value>{feature['tree_count']}</value></Data>
        <Data name="Mother_trees"><value>{feature['mother_tree']}</value></Data>
        <Data name="Felling_trees"><value>{feature['felling_tree']}</value></Data>
        <Data name="Regeneration"><value>{feature['regeneration']}</value></Data>
        <Data name="Sapling"><value>{feature['sapling']}</value></Data>
        <Data name="Small_pole"><value>{feature['small_pole']}</value></Data>
        <Data name="Large_pole"><value>{feature['large_pole']}</value></Data>
        <Data name="Small_tree"><value>{feature['small_tree']}</value></Data>
        <Data name="Medium_tree"><value>{feature['medium_tree']}</value></Data>
        <Data name="Large_tree"><value>{feature['large_tree']}</value></Data>
        <Data name="Very_large_tree"><value>{feature['very_large_tree']}</value></Data>
        <Data name="Is_Compartment"><value>{'Yes' if feature['is_compartment'] else 'No'}</value></Data>
        <Data name="Compartment_Code"><value>{feature['compartment_code'] or ''}</value></Data>
        <Data name="Parent_Block"><value>{feature['parent_block_name'] or ''}</value></Data>
        <Data name="Index"><value>{feature['index']}</value></Data>
      </ExtendedData>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>{coord_str}</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
'''

        kml_content += '''  </Document>
</kml>'''

        # Write to temp file
        temp_dir = tempfile.mkdtemp()
        filepath = os.path.join(temp_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(kml_content)

        logger.info(f"Exported {len(features_data)} blocks to KML: {filepath}")

        return FileResponse(
            filepath,
            media_type='application/vnd.google-earth.kml+xml',
            filename=filename,
            headers={"Content-Disposition": disposition}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export KML: {e}")
        raise i18n_error(500, "editing.export_failed", error=str(e))


# why: three split methods — parallel strips at configurable angle, grid by rows/columns, and auto-detect optimal
@router.post("/preview-split", response_model=SplitPreviewResponse)
def preview_split(
    request: SplitPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Preview compartment split without saving

    Args:
        request: Split preview request
        db: Database session
        current_user: Authenticated user

    Returns:
        Preview of compartments with validation
    """
    try:
        # Get forest block
        block = db.query(ForestBlock).filter(ForestBlock.id == request.block_id).first()
        if not block:
            raise i18n_error(404, "blocks.forest_division_not_found")

        # Check if THIS block already has compartments
        existing_compartments = db.query(ForestBlock).filter(
            ForestBlock.parent_block_id == block.id,
            ForestBlock.is_compartment == True
        ).count()

        if existing_compartments > 0:
            raise i18n_error(400, "compartments.division_once_only")

        # Check if block-level sampling exists — compartments are mutually exclusive with block-level sampling
        existing_sampling = db.query(SamplingDesign).filter(
            SamplingDesign.calculation_id == block.calculation_id
        ).count()

        if existing_sampling > 0:
            raise i18n_error(400, "compartments.sampling_mutex_preview")

        # Convert to Shapely polygon
        polygon = postgis_to_shapely(block.geometry)
        
        # constraint: split methods — "parallel" strips at configurable angle or "grid" by rows/columns
        if request.method == "parallel":
            compartments = CompartmentSplitter.split_parallel_strips(
                polygon,
                request.parameters.get("direction_angle", 0),
                request.parameters.get("num_compartments"),
                request.parameters.get("target_area_sqm"),
                request.parameters.get("min_area_sqm", 1000)
            )
        elif request.method == "grid":
            compartments = CompartmentSplitter.split_grid(
                polygon,
                request.parameters.get("rows", 2),
                request.parameters.get("columns", 2),
                request.parameters.get("min_area_sqm", 1000)
            )
        else:
            raise i18n_error(400, "compartments.split_method_invalid")

        # Validate split
        validation_result = CompartmentSplitter.validate_split(
            compartments,
            request.parameters.get("min_area_sqm", 1000),
            request.parameters.get("max_deviation_percent", 10)
        )

        # Count trees in each compartment
        tree_counts = []
        for comp in compartments:
            count = CompartmentSplitter.count_trees_in_polygon(db, block.id, comp)
            tree_counts.append(count)

        # Generate preview response
        total_area = sum(c.area for c in compartments)
        target_area = total_area / len(compartments) if compartments else 0

        compartment_previews = []

        for i, comp in enumerate(compartments):
            # Calculate deviation
            deviation = abs((comp.area - target_area) / target_area * 100) if target_area > 0 else 0

            # Convert to square meters (approximate)
            comp_area_sqm = calculate_area_sqm(comp)
            comp_area_ha = comp_area_sqm / SQM_PER_HA

            # Calculate perimeter
            perimeter_m = calculate_perimeter_m(comp)

            compartment_previews.append(CompartmentPreview(
                index=i + 1,
                name=f"{block.name}-C{i+1}",
                geometry=mapping(comp),
                area_sqm=comp_area_sqm,
                area_hectares=comp_area_ha,
                area_deviation_percent=deviation,
                tree_count=tree_counts[i],
                perimeter_m=perimeter_m
            ))

        return SplitPreviewResponse(
            compartments=compartment_previews,
            validation=SplitValidation(**validation_result),
            total_area_sqm=validation_result["total_area_sqm"],
            parent_block_name=block.name
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to preview split: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Preview failed: {str(e)}")


@router.post("/execute-split", response_model=ExecuteSplitResponse)
async def execute_split(
    request: ExecuteSplitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Execute compartment split and save to database

    Args:
        request: Split execution request
        db: Database session
        current_user: Authenticated user

    Returns:
        Result of split operation
    """
    try:
        # Get forest block
        block = db.query(ForestBlock).filter(ForestBlock.id == request.block_id).first()
        if not block:
            raise i18n_error(404, "blocks.forest_division_not_found")

        # Check if THIS block already has compartments
        existing_compartments = db.query(ForestBlock).filter(
            ForestBlock.parent_block_id == block.id,
            ForestBlock.is_compartment == True
        ).count()

        if existing_compartments > 0:
            raise i18n_error(400, "compartments.division_once_only")

        # Check if block-level sampling exists — compartments are mutually exclusive with block-level sampling
        existing_sampling = db.query(SamplingDesign).filter(
            SamplingDesign.calculation_id == block.calculation_id
        ).count()

        if existing_sampling > 0:
            raise i18n_error(400, "compartments.sampling_mutex")

        # Convert to Shapely polygon
        polygon = postgis_to_shapely(block.geometry)
        
        # Perform split
        if request.method == "parallel":
            compartments = CompartmentSplitter.split_parallel_strips(
                polygon,
                request.parameters.get("direction_angle", 0),
                request.parameters.get("num_compartments"),
                request.parameters.get("target_area_sqm"),
                request.parameters.get("min_area_sqm", 1000)
            )
        elif request.method == "grid":
            compartments = CompartmentSplitter.split_grid(
                polygon,
                request.parameters.get("rows", 2),
                request.parameters.get("columns", 2),
                request.parameters.get("min_area_sqm", 1000)
            )
        else:
            raise i18n_error(400, "compartments.split_method_invalid")

        if not compartments:
            raise i18n_error(400, "editing.split_failed")

        # why: compartments persist to forest_blocks table with parent_block_id, is_compartment=True, and division_level
        # Splitting changes geometry only -- every non-geometric attribute
        # describing the parent's forest/management character (working
        # circle, orientation, style, natural name, dominant slope/aspect/
        # canopy, color) still describes the same ground, so every
        # compartment inherits it unchanged (D-2026-09-15 -- previously this
        # legacy endpoint dropped all of these, resetting split-off
        # compartments to plain Production/no-style with a fresh palette
        # color, unlike the workspace divide tool).
        inherited = child_inherit_kwargs(block)
        if not inherited["color"]:
            inherited["color"] = COMPARTMENT_COLORS[0]

        # Create compartment records in database
        compartment_ids = []
        for i, comp_polygon in enumerate(compartments):
            # Generate compartment name
            naming_pattern = request.naming_pattern or "{block_name}-C{index}"
            comp_name = naming_pattern.replace("{block_name}", block.name).replace("{index}", str(i + 1))

            # Calculate area
            comp_area_sqm = calculate_area_sqm(comp_polygon)
            comp_area_ha = comp_area_sqm / SQM_PER_HA

            # Convert to PostGIS geometry
            comp_geom = shapely_to_postgis(comp_polygon)

            # Create ForestBlock record (compartment)
            compartment = ForestBlock(
                calculation_id=block.calculation_id,
                name=comp_name,
                block_name=comp_name,
                geometry=comp_geom,
                area_hectares=comp_area_ha,
                index=i,
                is_compartment=True,
                parent_block_id=block.id,
                compartment_code=comp_name,
                area_sqm=comp_area_sqm,
                division_level=DEPTH_TOP_COMPARTMENT,
                **inherited,
            )

            db.add(compartment)
            db.flush()  # Get the ID
            compartment_ids.append(compartment.id)

        # Create split history record
        split_history = CompartmentSplitHistory(
            parent_block_id=block.id,
            calculation_id=block.calculation_id,
            split_method=request.method,
            split_direction=request.parameters.get("direction_angle"),
            split_parameters=request.parameters,
            number_of_compartments=len(compartments),
            created_by=current_user.id,
            naming_pattern=request.naming_pattern,
            notes=request.notes
        )

        db.add(split_history)

        # Mark calculation as compartment mode in result_data
        calc = db.query(Calculation).filter(Calculation.id == block.calculation_id).first()
        if calc:
            new_result_data = dict(calc.result_data or {})
            new_result_data['polygon_type'] = 'compartment'
            calc.result_data = new_result_data

        db.commit()

        # business: trees on split boundaries reassigned by nearest centroid via auto_assign_trees_by_location
        trees_reassigned = 0
        if request.reassign_trees:
            try:
                # Get trees assigned to parent block
                trees_in_block = db.query(InventoryTree).filter(
                    InventoryTree.block_id == block.id
                ).count()

                if trees_in_block > 0:
                    reassignment_result = await auto_assign_trees_by_location(db, block.id)
                    trees_reassigned = reassignment_result["total_assigned"]
            except Exception as e:
                logger.warning(f"Failed to auto-assign trees: {e}")

        return ExecuteSplitResponse(
            split_history_id=split_history.id,
            compartments_created=compartment_ids,
            trees_reassigned=trees_reassigned,
            success=True,
            message=f"Successfully created {len(compartments)} compartments"
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to execute split: {e}", exc_info=True)
        raise i18n_error(500, "editing.split_execution_failed", error=str(e))


@router.get("/split-directions", response_model=List[SplitDirection])
async def get_split_directions():
    """
    Get preset splitting directions

    Returns:
        List of predefined split directions
    """
    return [
        SplitDirection(name="North-South", angle=0, description="Vertical strips (0°)"),
        SplitDirection(name="East-West", angle=90, description="Horizontal strips (90°)"),
        SplitDirection(name="Northeast-Southwest", angle=45, description="Diagonal (45°)"),
        SplitDirection(name="Northwest-Southeast", angle=135, description="Diagonal (135°)"),
        SplitDirection(name="Optimal (auto)", angle=None, description="Auto-detect based on block shape")
    ]


# business: compartment deletion restores trees to parent block — prevents orphan trees
@router.delete("/block/{block_id}/compartments")
def delete_compartments_by_block(
    block_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete all compartments for a block and restore trees to parent block

    Args:
        block_id: Parent block UUID
        db: Database session
        current_user: Authenticated user

    Returns:
        Success message
    """
    try:
        # Get parent block
        parent_block = db.query(ForestBlock).filter(
            ForestBlock.id == block_id
        ).first()

        if not parent_block:
            raise i18n_error(404, "blocks.forest_division_not_found")

        # Get compartments
        compartments = db.query(ForestBlock).filter(
            ForestBlock.parent_block_id == block_id,
            ForestBlock.is_compartment == True
        ).all()

        if not compartments:
            raise i18n_error(404, "compartments.no_subdivisions_found")

        compartment_ids = [c.id for c in compartments]

        # Check if trees are associated with these compartments through inventory_calculation
        from app.models.inventory import InventoryCalculation
        
        # Trees in compartments (block_id points to compartment)
        trees_in_compartments = db.query(InventoryTree).filter(
            InventoryTree.block_id.in_(compartment_ids)
        ).count()

        # Trees through inventory_calculation relationship
        trees_through_inventory = db.query(InventoryTree).join(
            InventoryCalculation, InventoryCalculation.id == InventoryTree.inventory_calculation_id
        ).filter(
            InventoryCalculation.calculation_id == parent_block.calculation_id
        ).count()

        total_trees = trees_in_compartments + trees_through_inventory

        if total_trees > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete compartments: {total_trees} trees are associated with this area. Please delete the tree inventory upload first, then come back to delete the compartments."
            )

        # Delete split history for this block
        split_histories = db.query(CompartmentSplitHistory).filter(
            CompartmentSplitHistory.parent_block_id == block_id
        ).all()
        for history in split_histories:
            db.delete(history)

        # Delete compartments
        for compartment in compartments:
            db.delete(compartment)

        db.commit()

        _recheck_dimension_after_delete(db, parent_block.calculation_id, current_user)
        db.commit()

        return {
            "success": True,
            "block_id": str(block_id),
            "block_name": parent_block.name,
            "compartments_deleted": len(compartments)
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete compartments: {e}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


@router.delete("/{compartment_id}")
def delete_compartment(
    compartment_id: UUID,
    confirm_children: bool = Query(
        False,
        description="FS-4a.9: required to delete a unit that has sub-units below it",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a single compartment or sub-compartment.
    Trees assigned to this compartment are moved back to the parent block.

    FS-4a.9 (D13): if it has sub-units at ANY depth (A1: nesting is not
    capped at one sub-level -- the old direct-children-only check here missed
    grandchildren), ``confirm_children=true`` is required or this returns 409
    with the total descendant count. Once confirmed, a plain ``db.delete()``
    now genuinely cascade-removes every descendant, recursively, through
    Postgres's own ``ON DELETE CASCADE`` (``ForestBlock.compartments`` gained
    ``passive_deletes=True``) -- this endpoint no longer walks and deletes
    each generation by hand.

    Args:
        compartment_id: Compartment UUID
        confirm_children: required when sub-units exist below this one
        db: Database session
        current_user: Authenticated user

    Returns:
        Success message
    """
    try:
        compartment = db.query(ForestBlock).filter(
            ForestBlock.id == compartment_id
        ).first()

        if not compartment:
            raise HTTPException(status_code=404, detail="Compartment not found")

        if not compartment.is_compartment:
            raise HTTPException(status_code=400, detail="Can only delete compartments")

        parent_block_id = compartment.parent_block_id

        # Every descendant, any depth (A1) -- needed both for the trees guard
        # below and for the confirm/reported counts.
        ids_to_delete = [compartment_id]
        frontier = [compartment_id]
        while frontier:
            next_gen = db.query(ForestBlock.id).filter(
                ForestBlock.parent_block_id.in_(frontier)
            ).all()
            frontier = [row.id for row in next_gen]
            ids_to_delete.extend(frontier)

        descendant_count = len(ids_to_delete) - 1

        if descendant_count > 0 and not confirm_children:
            raise i18n_error(
                409, "blocks.has_children_confirm_required", count=descendant_count
            )

        # Owner report 2026-10-02: collected BEFORE the delete below -- the
        # rows (and their raster_layer_id) are gone afterward. Passed to
        # `demote_orphaned_layers` once the delete is committed, so a
        # promoted layer that loses its last row here gets cleared instead
        # of silently surviving as a zombie `promoted_as` with zero rows.
        raster_layer_ids_touched = {
            row.raster_layer_id
            for row in db.query(ForestBlock.raster_layer_id)
            .filter(ForestBlock.id.in_(ids_to_delete), ForestBlock.raster_layer_id.isnot(None))
            .all()
        }

        # Check for trees assigned to any of these compartments
        trees_in_compartment = db.query(InventoryTree).filter(
            InventoryTree.block_id.in_(ids_to_delete)
        ).count()

        if trees_in_compartment > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete: {trees_in_compartment} trees are assigned to this compartment. Please delete the tree inventory first."
            )

        # Delete the compartment itself -- passive_deletes=True (FS-4a.9)
        # lets Postgres's own ON DELETE CASCADE remove every descendant
        # collected above, recursively, in one statement.
        db.delete(compartment)

        # Update parent's child_count if parent exists
        if parent_block_id:
            parent = db.query(ForestBlock).filter(ForestBlock.id == parent_block_id).first()
            if parent:
                parent.child_count = db.query(ForestBlock).filter(
                    ForestBlock.parent_block_id == parent_block_id
                ).count()

        db.commit()

        if raster_layer_ids_touched:
            from ..services.auto_block_service import demote_orphaned_layers
            demote_orphaned_layers(db, raster_layer_ids_touched)

        _recheck_dimension_after_delete(db, compartment.calculation_id, current_user)
        db.commit()

        return {
            "success": True,
            "compartment_id": str(compartment_id),
            "compartment_name": compartment.name,
            "deleted": True,
            "children_deleted": descendant_count,
            "trees_moved_back": 0
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete compartment: {e}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


# why: undo_split reverses full split history — moves trees back to parent, deletes compartments and history record
@router.delete("/split/{split_history_id}")
def undo_split(
    split_history_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Undo a compartment split (delete compartments and restore trees)

    Args:
        split_history_id: Split history UUID
        db: Database session
        current_user: Authenticated user

    Returns:
        Success message
    """
    try:
        # Get split history
        split_history = db.query(CompartmentSplitHistory).filter(
            CompartmentSplitHistory.id == split_history_id
        ).first()

        if not split_history:
            raise HTTPException(status_code=404, detail="Split history not found")

        parent_block_id = split_history.parent_block_id
        parent_block = db.query(ForestBlock).filter(
            ForestBlock.id == parent_block_id
        ).first()

        # Get compartments created by this split
        compartments = db.query(ForestBlock).filter(
            ForestBlock.parent_block_id == parent_block_id,
            ForestBlock.is_compartment == True
        ).all()

        compartment_ids = [c.id for c in compartments]

        # Move trees back to parent block
        trees_moved = 0
        for comp_id in compartment_ids:
            trees = db.query(InventoryTree).filter(
                InventoryTree.block_id == comp_id
            ).all()

            for tree in trees:
                tree.block_id = parent_block_id
                tree.block_name = parent_block.name
                trees_moved += 1

        # Delete compartments
        for compartment in compartments:
            db.delete(compartment)

        # Delete split history
        db.delete(split_history)

        db.commit()

        _recheck_dimension_after_delete(db, split_history.calculation_id, current_user)
        db.commit()

        return {
            "success": True,
            "restored_block_id": str(parent_block_id),
            "compartments_deleted": len(compartments),
            "trees_moved_back": trees_moved
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to undo split: {e}")
        raise HTTPException(status_code=500, detail=f"Undo failed: {str(e)}")


# business: CFMG — tree locations on map for visual compartment assignment verification
@router.get("/calculation/{calculation_id}/trees")
def get_trees_for_map(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all trees for a calculation to display on map

    Args:
        calculation_id: Calculation UUID
        db: Database session
        current_user: Authenticated user

    Returns:
        List of tree points with metadata
    """
    logger.info(f"[get_trees_for_map] Endpoint called for calculation {calculation_id}")
    
    try:
        from geoalchemy2.shape import to_shape
        from app.models.inventory import InventoryCalculation
        from app.models.field_inventory import FieldInventoryCalculation, FieldInventorySamplePlot, FieldInventoryMeasurement
        
        logger.info(f"[get_trees_for_map] Starting query for calculation {calculation_id}")
        
        tree_features = []
        
        # 1. Get trees from regular inventory (InventoryTree) - only from user's inventory linked to this calculation
        inventory_calcs = db.query(InventoryCalculation).filter(
            InventoryCalculation.calculation_id == calculation_id,
            InventoryCalculation.user_id == current_user.id
        ).all()
        logger.info(f"[get_trees_for_map] Found {len(inventory_calcs)} inventory_calculations for this calculation (user: {current_user.id})")
        
        if len(inventory_calcs) == 0:
            logger.warning(f"[get_trees_for_map] No inventory_calculations found for calculation_id={calculation_id} and user_id={current_user.id}")
        
        # Get trees only from inventory_calculations that are properly linked to this calculation
        inventory_trees = db.query(InventoryTree).join(
            InventoryCalculation, InventoryCalculation.id == InventoryTree.inventory_calculation_id
        ).filter(
            InventoryCalculation.calculation_id == calculation_id,
            InventoryCalculation.user_id == current_user.id
        ).all()
        logger.info(f"[get_trees_for_map] Found {len(inventory_trees)} trees from regular inventory")
        
        for tree in inventory_trees:
            try:
                location = to_shape(tree.location)
                
                # Calculate DBH class using shared classifier
                dbh = float(tree.dia_cm) if tree.dia_cm else 0
                dbh_class = DbhClassRegistry.classify_detailed(dbh) or 'Unknown'
                
                tree_features.append({
                    "id": str(tree.id),
                    "latitude": location.y,
                    "longitude": location.x,
                    "species": tree.species or "Unknown",
                    "dbh_cm": float(tree.dia_cm) if tree.dia_cm else 0,
                    "height_m": float(tree.height_m) if tree.height_m else 0,
                    "volume_m3": float(tree.tree_volume) if tree.tree_volume else 0,
                    "dbh_class": dbh_class,
                    "block_id": str(tree.block_id) if tree.block_id else None,
                    "block_name": tree.block_name,
                    "remark": tree.remark,
                    "grid_cell_id": tree.grid_cell_id,
                    "source": "inventory"
                })
            except Exception as tree_err:
                logger.warning(f"[get_trees_for_map] Failed to process inventory tree {tree.id}: {tree_err}")
        
        logger.debug(f"[DEBUG] Current user id: {current_user.id}")
        
        # 2. Get trees from field inventory (FieldInventoryMeasurement)
        logger.debug(f"[DEBUG] Looking for field_inventory with calculation_id={calculation_id}, user_id={current_user.id}")
        field_calcs = db.query(FieldInventoryCalculation).filter(
            FieldInventoryCalculation.calculation_id == calculation_id,
            FieldInventoryCalculation.user_id == current_user.id
        ).all()
        logger.debug(f"[DEBUG] Found {len(field_calcs)} field_inventory_calculations matching filter")
        
        # Also check WITHOUT user filter to see if that's the issue
        field_calcs_all = db.query(FieldInventoryCalculation).filter(
            FieldInventoryCalculation.calculation_id == calculation_id
        ).all()
        logger.debug(f"[DEBUG] Found {len(field_calcs_all)} field_inventory_calculations WITHOUT user filter")
        
        # SKIP field inventory trees - only use Tree Mapping trees (inventory_trees)
        # User requested: "Just use from Tree mapping source. Other source must be discarded."
        logger.info(f"[get_trees_for_map] Total trees: {len(tree_features)}")
        
        # Get grid spacing from inventory calculations if available
        grid_spacing = None
        inventory_id = None
        if inventory_calcs:
            ic = inventory_calcs[0]
            grid_spacing = float(ic.grid_spacing_meters) if ic.grid_spacing_meters else None
            inventory_id = str(ic.id)
        
        return {
            "count": len(tree_features),
            "trees": tree_features,
            "grid_spacing_meters": grid_spacing,
            "inventory_id": inventory_id
        }
        
    except Exception as e:
        logger.error(f"[get_trees_for_map] Exception: {e}")
        logger.exception("Failed to get trees for map")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trees-needing-assignment/{block_id}")
async def get_trees_needing_assignment_endpoint(
    block_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get trees that need compartment assignment

    Args:
        block_id: Parent block UUID
        db: Database session
        current_user: Authenticated user

    Returns:
        Trees and compartments with suggestions
    """
    try:
        result = await get_trees_needing_assignment(db, block_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get trees needing assignment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# business: auto-assign by GPS location or manual assignment — CFMG forest management flexibility
@router.post("/reassign-trees", response_model=TreeReassignmentResponse)
async def reassign_trees(
    request: TreeReassignmentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reassign trees from parent block to compartments

    Args:
        request: Reassignment request
        db: Database session
        current_user: Authenticated user

    Returns:
        Assignment statistics
    """
    try:
        if request.auto_assign:
            # Auto-assign based on GPS location
            result = await auto_assign_trees_by_location(db, request.block_id)
        elif request.manual_assignments:
            # Manual assignment
            result = await manual_assign_trees(db, request.manual_assignments)
        else:
            raise HTTPException(
                status_code=400,
                detail="Must specify either auto_assign=true or provide manual_assignments"
            )

        return TreeReassignmentResponse(**result)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to reassign trees: {e}")
        raise HTTPException(status_code=500, detail=f"Reassignment failed: {str(e)}")


@router.patch("/{compartment_id}/name")
def update_compartment_name(
    compartment_id: UUID,
    request: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update compartment name.
    
    Args:
        compartment_id: Compartment UUID
        request: Dict with 'name' field
        db: Database session
        current_user: Authenticated user
    
    Returns:
        Updated compartment info
    """
    try:
        from app.models.forest_block import ForestBlock
        
        # Get compartment
        compartment = db.query(ForestBlock).filter(
            ForestBlock.id == compartment_id,
            ForestBlock.is_compartment == True
        ).first()
        
        if not compartment:
            raise HTTPException(status_code=404, detail="Compartment not found")
        
        # Phase E-1 single-authority (review-fix #8): name-only endpoint —
        # geometry writes route through the editing router.
        if "geometry" in request:
            raise HTTPException(status_code=400, detail="Use POST /calculations/{id}/geometry/edit-geometry for geometry edits — this endpoint is attribute-only (Phase E-1 single-authority).")
        # Update name
        new_name = request.get('name')
        if not new_name:
            raise HTTPException(status_code=400, detail="Name is required")
        
        compartment.name = new_name
        compartment.compartment_code = new_name
        db.commit()
        
        return {
            "success": True,
            **i18n_success("compartments.compartment_name_updated"),
            "id": str(compartment.id),
            "name": compartment.name
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update compartment name: {e}")
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


# ============================================================================
# NEW: Compartment Hierarchy Endpoints (Added 2026-05-07)
# ============================================================================

# constraint: lock prevents further division — ensures compartment integrity after approval
@router.patch("/blocks/{block_id}/toggle-lock")
def toggle_lock_block(
    block_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Toggle lock status to prevent/allow further division
    
    Args:
        block_id: Block/Compartment UUID
        db: Database session
        current_user: Authenticated user
    
    Returns:
        Updated lock status
    """
    try:
        block = db.query(ForestBlock).filter(
            ForestBlock.id == block_id
        ).first()
        
        if not block:
            raise i18n_error(404, "blocks.forest_division_not_found")
        
        # Toggle lock status
        block.is_locked = not block.is_locked
        db.commit()
        
        status = "locked" if block.is_locked else "unlocked"
        logger.info(f"Toggled lock for block {block.name}: now {status}")
        
        return {
            "success": True,
            "block_id": str(block_id),
            "is_locked": block.is_locked,
            "message": f"Block '{block.name}' is now {status}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to toggle lock: {e}")
        raise HTTPException(status_code=500, detail=f"Toggle lock failed: {str(e)}")


def _child_orientation_note(children: list, lang: str) -> Optional[str]:
    """Why a divided parent shows the orientation it does: it is the one covering the largest area of its sub-units."""
    ori = _dominant_child_orientation(children)
    if not ori:
        return None
    n = len(children)
    if lang == "ne":
        return f"{n} उप-इकाईको सारांश: सबैभन्दा ठूलो क्षेत्रफल ओगट्ने अभिमुखीकरण ({ori})।"
    return f"Summary of {n} sub-unit(s): the orientation covering the largest area ({ori})."


def _dominant_child_orientation(children: list) -> Optional[str]:
    """A divided parent's suggested orientation: the one covering the largest area of its sub-units (None for a leaf)."""
    from ..services.unit_rollup import dominant_by_area

    return dominant_by_area(
        (c.get("area_hectares") or 0, c.get("suggested_orientation") or c.get("management_orientation")) for c in children
    )


@router.get("/calculations/{calculation_id}/compartment-tree")
def get_compartment_tree(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get hierarchical tree of blocks → compartments → sub-compartments
    
    Args:
        calculation_id: Calculation UUID
        db: Database session
        current_user: Authenticated user
    
    Returns:
        Hierarchical tree structure with all blocks and compartments
    """
    from ..services.forest_units.mode import forest_stream

    try:
        # Fetch all blocks for calculation. RS-2.16/P2.5 (owner report,
        # 2026-10-01): an unpromoted Auto-Block trial layer must not appear
        # here as if it were real structure -- this is the tree every
        # builtin layer (blocks/compartments/sub_blocks/sub_compartments)
        # is actually built from on the frontend (`layerRegistry.ts`'s
        # `compartment-tree` fetch), so missing this filter is exactly how
        # an unpromoted MMU/slope/etc. layer showed up as though the system
        # had auto-assigned it.
        from ..services.forest_units.queries import promoted_or_unlayered

        blocks = promoted_or_unlayered(
            db.query(ForestBlock).filter(
                ForestBlock.calculation_id == calculation_id
            )
        ).order_by(ForestBlock.display_order).all()

        logger.info(f"Building tree for calculation {calculation_id}: {len(blocks)} blocks")

        # Field-inventory forest condition per block name (P4.5 "Colour by condition").
        from app.models.field_inventory import FieldInventoryCalculation, FieldInventoryBlockSummary
        _fi = db.query(FieldInventoryCalculation).filter(
            FieldInventoryCalculation.calculation_id == calculation_id
        ).first()
        condition_by_name: dict = {}
        if _fi:
            for _name, _cond in db.query(
                FieldInventoryBlockSummary.block_name, FieldInventoryBlockSummary.forest_condition
            ).filter(
                FieldInventoryBlockSummary.field_inventory_calculation_id == _fi.id,
                FieldInventoryBlockSummary.forest_condition.isnot(None),
            ).all():
                if _name:
                    condition_by_name[_name] = _cond

        # A divided parent has no inventory row of its own: its condition is the rule applied to its sub-units' roll-up.
        rolled_fi: dict = {}
        try:
            from ..services.operational_plan import unit_maps as _um

            rolled_fi = (_um.unit_values(db, calculation_id) or {}).get("units", {})
        except Exception:  # noqa: BLE001 -- the tree must still load; parents just show no rolled-up condition (logged)
            logger.exception("compartment tree: rolled-up condition failed")

        # Build tree structure recursively
        def build_tree(parent_id=None, level=0):
            nodes = []
            for block in blocks:
                if block.parent_block_id == parent_id:
                    # Get children recursively
                    children = build_tree(block.id, level + 1)
                    
                    # Count trees in this block/compartment
                    from app.models.inventory import InventoryTree
                    tree_count = db.query(InventoryTree).filter(
                        InventoryTree.block_id == block.id
                    ).count()
                    
                    node = {
                        "id": str(block.id),
                        "name": block.name,
                        "area_hectares": block.area_hectares,
                        "area_sqm": block.area_sqm or (block.area_hectares * SQM_PER_HA),
                        "division_level": block.division_level,
                        "color": block.color,
                        "is_locked": block.is_locked,
                        "child_count": len(children),
                        "is_compartment": block.is_compartment,
                        "compartment_code": block.compartment_code,
                        # Auto-block provenance (block_name/natural_name from the
                        # MMU source, dominant_slope_band from the slope source)
                        # — previously dropped here, so it never reached the
                        # compartments/sub-compartments attribute table.
                        "block_name": block.block_name,
                        "natural_name": block.natural_name,
                        "dominant_slope_band": getattr(block, "dominant_slope_band", None),
                        "dominant_aspect": getattr(block, "dominant_aspect", None),
                        "dominant_canopy_class": getattr(block, "dominant_canopy_class", None),
                        # The four Raster-Sources Auto-Block classifications and
                        # the read-only elevation trio (migration 105). Same
                        # shape as the 084/085 dominant_* fields above.
                        "dominant_health_class": getattr(block, "dominant_health_class", None),
                        "dominant_nasa_quality": getattr(block, "dominant_nasa_quality", None),
                        # Raw NASA class 0-3 incl. non-forest (migration 106 /
                        # RS-2.14): the fact that explains a NULL above.
                        "dominant_nasa_code": getattr(block, "dominant_nasa_code", None),
                        "dominant_landcover": getattr(block, "dominant_landcover", None),
                        "dominant_elevation_zone": getattr(block, "dominant_elevation_zone", None),
                        "elevation_min_m": float(block.elevation_min_m) if block.elevation_min_m is not None else None,
                        "elevation_mean_m": float(block.elevation_mean_m) if block.elevation_mean_m is not None else None,
                        "elevation_max_m": float(block.elevation_max_m) if block.elevation_max_m is not None else None,
                        "management_orientation": getattr(block, "management_orientation", None)
                        or _dominant_child_orientation(children),
                        "suggested_orientation": getattr(block, "suggested_orientation", None) or _dominant_child_orientation(children),
                        "orientation_justification_ne": getattr(block, "orientation_justification_ne", None)
                        or _child_orientation_note(children, "ne"),
                        "orientation_justification_en": getattr(block, "orientation_justification_en", None)
                        or _child_orientation_note(children, "en"),
                        "working_circle": getattr(block, "working_circle", None) or "production",
                        "style": getattr(block, "style", None),
                        "forest_condition": (
                            condition_by_name.get(block.block_name)
                            or condition_by_name.get(block.name)
                            or (rolled_fi.get(block.name) or {}).get("fi_condition")
                        ),
                        "tree_count": tree_count,
                        "geometry": polygon_to_geojson(postgis_to_shapely(block.geometry)) if block.geometry else None,
                        "children": children
                    }
                    nodes.append(node)
            
            return nodes
        
        tree = build_tree(None, 0)
        
        # Calculate totals
        total_area = sum(b.area_hectares for b in blocks if b.parent_block_id is None)
        total_compartments = sum(1 for b in blocks if b.is_compartment and b.division_level == DEPTH_TOP_COMPARTMENT)
        total_sub_compartments = sum(1 for b in blocks if b.is_compartment and b.division_level >= DEPTH_SUB)
        total_sub_blocks = sum(1 for b in blocks if not b.is_compartment and b.division_level >= DEPTH_SUB)
        
        # Determine dimension mode
        has_compartments = total_compartments > 0
        has_sampling = db.query(SamplingDesign).filter(
            SamplingDesign.calculation_id == calculation_id
        ).count() > 0

        return {
            "blocks": tree,
            "total_area_hectares": total_area,
            "total_compartments": total_compartments,
            "total_sub_compartments": total_sub_compartments,
            "total_sub_blocks": total_sub_blocks,
            "dimension": "compartment" if has_compartments else "block",
            "stream": forest_stream(db, calculation_id).value,
            "has_sampling_designs": has_sampling
        }
        
    except Exception as e:
        logger.error(f"Failed to build compartment tree: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load tree: {str(e)}")


# why: sub-divide extends execute_split logic — creates next-level hierarchical compartments
@router.post("/blocks/{block_id}/sub-divide")
def subdivide_block(
    block_id: UUID,
    config: dict,  # Will be validated by compartment_splitter
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Divide a compartment into sub-compartments (extends execute_split logic)
    
    Args:
        block_id: Parent block/compartment UUID
        config: { method, parameters, naming_pattern, reassign_trees, notes }
        db: Database session
        current_user: Authenticated user
    
    Returns:
        Success message with created sub-compartments
    """
    try:
        # Get parent block
        parent = db.query(ForestBlock).filter(
            ForestBlock.id == block_id
        ).first()
        
        if not parent:
            raise i18n_error(404, "blocks.forest_division_not_found")
        
        if not parent.is_compartment:
            raise HTTPException(status_code=400, detail="Can only sub-divide compartments")
        
        if parent.is_locked:
            raise HTTPException(status_code=400, detail="Block is locked from further division")
        
        # Update division_level if not set. `parent.is_compartment` is guaranteed True here (checked
        # above), so this always takes the compartment branch (DEPTH_TOP_COMPARTMENT); the `else` side
        # is unreachable but still routed through the module constant, not a bare 0.
        if parent.division_level is None:
            from ..services.forest_units.model import DEPTH_TOP_BLOCK, DEPTH_TOP_COMPARTMENT

            parent.division_level = DEPTH_TOP_COMPARTMENT if parent.is_compartment else DEPTH_TOP_BLOCK
        
        # Use existing compartment splitter logic
        from ..services.compartment_splitter import CompartmentSplitter
        
        splitter = CompartmentSplitter(db)
        
        # Prepare split request
        method = config.get("method", "parallel")
        parameters = config.get("parameters", {})
        naming_pattern = config.get("naming_pattern", "{parent_name}-SC{index}")
        reassign_trees = config.get("reassign_trees", True)
        
        # Execute split using existing logic
        # This reuses the execute_split logic but sets parent_block_id and division_level
        result = splitter.subdivide_compartment(
            parent_block=parent,
            method=method,
            parameters=parameters,
            naming_pattern=naming_pattern,
            reassign_trees=reassign_trees,
            division_level_increment=DEPTH_STEP  # children are always one level deeper than their parent
        )
        
        # Update parent's child_count
        parent.child_count = db.query(ForestBlock).filter(
            ForestBlock.parent_block_id == parent.id
        ).count()
        
        db.commit()
        
        logger.info(f"Sub-divided {parent.name} into {len(result.get('children', []))} sub-compartments")
        
        return {
            "success": True,
            "message": f"Sub-divided into {parent.child_count} sub-compartments",
            "parent_id": str(block_id),
            "sub_compartments_created": parent.child_count,
            "children": result.get("children", [])
        }
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to sub-divide block: {e}")
        raise HTTPException(status_code=500, detail=f"Sub-division failed: {str(e)}")
