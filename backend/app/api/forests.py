"""
Forest management API endpoints
"""

import logging
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Form,
    Body,
    Query,
)
from app.core.errors import CalculationErrors

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session
from sqlalchemy import func, text, select
from sqlalchemy.orm.attributes import flag_modified
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime, timezone
import json

from ..core.database import get_db
from ..core.exceptions import i18n_error, i18n_success
from ..core.geo import calculate_utm_epsg
from ..core.constants import SQM_PER_HA, METERS_PER_DEGREE_LAT
from ..utils.geometry_utils import calculate_area_geodesic
from ..models.user import User
from ..models.community_forest import CommunityForest
from ..models.forest_manager import ForestManager
from ..models.calculation import Calculation, CalculationStatus
from ..models.forest_block import ForestBlock
from ..services.forest_units.model import DEPTH_TOP_BLOCK, DEPTH_TOP_COMPARTMENT
from ..models.synthetic_tree_model import SyntheticTreeModel
from ..models.field_inventory import (
    FieldInventoryCalculation,
    FieldInventoryBlockSummary,
    FieldInventorySamplePlot,
)
from ..services.block_reconcile_service import (
    reconcile_blocks_from_db,
    reconcile_compartments_from_db,
)
from ..schemas.forest import (
    CommunityForestResponse,
    ForestManagerCreate,
    ForestManagerResponse,
    CalculationResponse,
    MyForestsResponse,
    ReanalysisRequest,
    GenerateMapsRequest,
    AddSpeciesRequest,
    GeometryUpdateRequest,
    SubAreaCreateRequest,
    SubAreaUpdateRequest,
    SubAreaResponse,
    SubAreaListResponse,
    SubAreaCategoryItem,
    BoundaryPieceUpdateRequest,
    BoundaryPieceResponse,
    BoundaryPieceListResponse,
    BlockPolygonResponse,
    BlockPolygonListResponse,
    BlockCreateRequest,
    BlockCreateListRequest,
    BlockCreateFromGeometryRequest,
    BlockResponse,
    BlockRenameRequest,
    BlockListResponse,
    BlockAreaDetailItem,
    BlockBreakdownItem,
    BlockAreaDetailResponse,
    DraftSaveRequest,
    DraftResponse,
    DraftDetailResponse,
    ConvertDraftRequest,
    CreateNameOnlyDraftRequest,
    MergeForestBoundaryRequest,
)
from ..schemas.map_creation import MapCreationRequest
from ..schemas.tree_model import (
    GenerateTreeModelRequest,
    TreeModelResponse,
    TreeModelListResponse,
    TreeModelConfigBase,
)
from ..utils.auth import get_current_active_user, require_super_admin
from ..utils.authz import is_owner_or_admin

try:
    from ..services.file_processor import (
        process_uploaded_file_legacy as process_uploaded_file,
    )

    FILE_UPLOAD_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Warning: File upload disabled due to import error: {e}")
    FILE_UPLOAD_AVAILABLE = False
from ..services.reanalysis_service import run_reanalysis
from ..services.analysis import analyze_forest_boundary
from ..services.boundary_validation import (
    enforce_boundary_rules,
    BoundaryRulesViolation,
)
from ..services.fieldbook import generate_fieldbook_points
from ..services.sub_area_service import (
    place_sub_area_geometry,
    SubAreaPlacementError,
    PLACEMENT_MESSAGES,
)
from ..services.sampling import create_sampling_design
from ..services.map_generator import get_map_generator
from ..services.tree_cover_analysis import (
    calculate_accessible_forest_area,
    calculate_block_tree_cover_areas,
    calculate_block_area_details,
)
from ..services.map_creation_service import (
    geojson_to_wkt,
    process_map_creation_data,
    process_as_compartments,
    validate_map_creation_data,
    prepare_block_analysis_data,
)
from shapely.geometry import mapping, shape
from shapely import wkb
from fastapi.responses import StreamingResponse
import io
import os
from pathlib import Path


_MAP_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", "maps_cache"
)


def _cached_map_stream(calculation_id: UUID, layer: str) -> Optional[StreamingResponse]:
    path = os.path.join(_MAP_CACHE_DIR, str(calculation_id), f"{layer}.png")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return StreamingResponse(
                io.BytesIO(f.read()),
                media_type="image/png",
                headers={
                    "Content-Disposition": f"inline; filename={layer}_{calculation_id}.png"
                },
            )
    return None


def _save_map_cache(calculation_id: UUID, layer: str, data: bytes):
    path = os.path.join(_MAP_CACHE_DIR, str(calculation_id), f"{layer}.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


router = APIRouter()


def calculate_total_excluded_area(sub_areas: List[Dict]) -> float:
    """
    Calculate total excluded area from all sub-areas.

    Business rule (D2c): exclusion is DERIVED from category — only
    `private_land` is excluded from the forest area. The `is_excluded`
    flag is honored as a fallback but never overrides the category rule.
    """
    total_excluded = 0.0

    for sa in sub_areas:
        category = sa.get("category")
        is_excluded = sa.get("is_excluded") or sa.get("isExcluded")
        if category == "private_land" or is_excluded:
            area = sa.get("area_hectares", 0)
            total_excluded += area

    return total_excluded


def calculate_block_excluded_areas(
    blocks: List[Dict], sub_areas: List[Dict]
) -> Dict[str, float]:
    """
    Calculate excluded area for each block, considering sub-areas that span multiple blocks.

    Args:
        blocks: List of block dictionaries with block_id/block_name
        sub_areas: List of sub-area dictionaries with blockBreakdown (optional)

    Returns:
        Dictionary mapping block_id to excluded area in hectares
    """
    block_excluded = {}

    # Initialize all blocks with 0
    for block in blocks:
        block_id = block.get("block_id")
        if block_id:
            block_excluded[block_id] = 0.0

    # Calculate excluded areas. Exclusion derives from category (D2c): only
    # private_land is excluded; the flag is a fallback, never an override.
    for sa in sub_areas:
        category = sa.get("category")
        is_excluded = sa.get("is_excluded") or sa.get("isExcluded")
        if not (category == "private_land" or is_excluded):
            continue

        # Check if sub-area has blockBreakdown (cross-block sub-area)
        block_breakdown = sa.get("blockBreakdown")

        if block_breakdown and len(block_breakdown) > 0:
            # Use blockBreakdown to distribute area across blocks
            for item in block_breakdown:
                block_id = item.get("blockId")
                area = item.get("area", 0)
                if block_id in block_excluded:
                    block_excluded[block_id] += area
                    logger.info(
                        f"  [calc] Block {item.get('blockName')}: +{area:.4f} ha from cross-block sub-area '{sa.get('name')}'"
                    )
        else:
            # Fallback: use single block_id (old behavior)
            block_id = sa.get("block_id") or sa.get("blockId")
            area = sa.get("area_hectares", 0)
            if block_id and block_id in block_excluded:
                block_excluded[block_id] += area
                logger.info(
                    f"  [calc] Block {block_id}: +{area:.4f} ha from single-block sub-area '{sa.get('name')}'"
                )

    return block_excluded


def calculate_block_breakdown(geometry: Dict, blocks: List[Dict]) -> List[Dict]:
    """
    Calculate how a sub-area's geometry intersects with each block.

    Args:
        geometry: GeoJSON geometry dict
        blocks: List of block dictionaries with geometry

    Returns:
        List of dicts with blockId, blockName, area, percentage
    """
    from shapely.geometry import shape
    from shapely.ops import transform

    try:
        sub_geom = shape(geometry)
        sub_area = sub_geom.area

        if sub_area == 0:
            return []

        breakdown = []
        for block in blocks:
            block_geom = block.get("geometry")
            if not block_geom:
                continue

            try:
                block_shape = shape(block_geom)

                # Calculate intersection
                if sub_geom.intersects(block_shape):
                    intersection = sub_geom.intersection(block_shape)
                    intersection_area = intersection.area

                    if intersection_area > 0:
                        percentage = (intersection_area / sub_area) * 100
                        breakdown.append(
                            {
                                "blockId": block.get("block_id"),
                                "blockName": block.get("block_name"),
                                "area": round(
                                    intersection_area / 10000, 4
                                ),  # Convert to hectares
                                "percentage": round(percentage, 2),
                            }
                        )
            except Exception as e:
                logger.error(f"Error calculating intersection with block: {e}")
                continue

        # Sort by area descending
        breakdown.sort(key=lambda x: x.get("area", 0), reverse=True)
        return breakdown

    except Exception as e:
        logger.error(f"Error calculating block breakdown: {e}")
        return []


# constraint: paginated at 20 per page for UI performance (frontend default)
@router.get("/community-forests", response_model=List[CommunityForestResponse])
def list_community_forests(
    search: Optional[str] = None,
    regime: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """
    List community forests from the database

    - **search**: Search by name (case-insensitive)
    - **regime**: Filter by regime type (CF, CFM, etc.)
    - **limit**: Number of results to return (max 1000)
    - **offset**: Number of results to skip for pagination
    """
    query = db.query(CommunityForest)

    # Apply filters
    if search:
        query = query.filter(CommunityForest.name.ilike(f"%{search}%"))
    if regime:
        query = query.filter(CommunityForest.regime == regime)

    # Apply pagination
    query = query.limit(min(limit, 1000)).offset(offset)

    forests = query.all()

    # Convert to response format
    results = []
    for forest in forests:
        results.append(
            {
                "id": forest.id,
                "name": forest.name,
                "code": forest.code,
                "regime": forest.regime,
                "area_hectares": forest.area_hectares,
                "geometry": None,  # Don't include full geometry in list view
            }
        )

    return results


# business: CFMG — forest record must include registration_number, area, and location
@router.get("/community-forests/{forest_id}", response_model=CommunityForestResponse)
def get_community_forest(forest_id: int, db: Session = Depends(get_db)):
    """
    Get detailed information about a specific community forest

    Returns forest metadata and boundary geometry as GeoJSON
    """
    forest = db.query(CommunityForest).filter(CommunityForest.id == forest_id).first()

    if not forest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Community forest with ID {forest_id} not found",
        )

    # Get geometry as GeoJSON
    geojson_query = (
        db.query(func.ST_AsGeoJSON(CommunityForest.geom).label("geojson"))
        .filter(CommunityForest.id == forest_id)
        .first()
    )

    geometry = (
        json.loads(geojson_query.geojson)
        if geojson_query and geojson_query.geojson
        else None
    )

    return {
        "id": forest.id,
        "name": forest.name,
        "code": forest.code,
        "regime": forest.regime,
        "area_hectares": forest.area_hectares,
        "geometry": geometry,
    }


@router.get("/my-forests", response_model=MyForestsResponse)
def get_my_forests(
    current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)
):
    """
    Get forests assigned to current user

    Returns list of community forests the user manages
    """
    # Query forests assigned to user
    query = (
        db.query(CommunityForest, ForestManager.role)
        .join(ForestManager, ForestManager.community_forest_id == CommunityForest.id)
        .filter(
            ForestManager.user_id == current_user.id, ForestManager.is_active == True
        )
    )

    results = query.all()

    forests = []
    total_area = 0.0

    for forest, role in results:
        forests.append(
            {
                "id": forest.id,
                "name": forest.name,
                "code": forest.code,
                "regime": forest.regime,
                "area_hectares": forest.area_hectares,
                "role": role,
            }
        )
        total_area += forest.area_hectares

    return {
        "forests": forests,
        "total_count": len(forests),
        "total_area_hectares": total_area,
    }


@router.post("/assign-manager", response_model=ForestManagerResponse)
def assign_forest_manager(
    assignment: ForestManagerCreate,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """
    Assign a user to manage a community forest

    Requires super admin privileges
    """
    # Verify user exists
    user = db.query(User).filter(User.id == assignment.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Verify forest exists
    forest = (
        db.query(CommunityForest)
        .filter(CommunityForest.id == assignment.community_forest_id)
        .first()
    )
    if not forest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Community forest not found"
        )

    # Check if assignment already exists
    existing = (
        db.query(ForestManager)
        .filter(
            ForestManager.user_id == assignment.user_id,
            ForestManager.community_forest_id == assignment.community_forest_id,
        )
        .first()
    )

    if existing:
        # Update existing assignment
        existing.role = assignment.role
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return existing

    # Create new assignment
    new_assignment = ForestManager(
        user_id=assignment.user_id,
        community_forest_id=assignment.community_forest_id,
        role=assignment.role,
    )

    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)

    return new_assignment


# business: CFMG — boundary upload must include valid GeoJSON with SRID 4326
# constraint: max file size 50MB for boundary upload (nginx upstream)
# why: GeoJSON parsed to WKT for PostGIS ST_Transform compatibility
@router.post(
    "/upload", response_model=CalculationResponse, status_code=status.HTTP_201_CREATED
)
async def upload_forest_boundary(
    file: UploadFile = File(...),
    forest_name: str = Form(...),
    block_name: Optional[str] = Form(None),
    # Analysis options (all optional, default True for backward compatibility)
    run_raster_analysis: bool = Form(True),
    run_elevation: bool = Form(True),
    run_slope: bool = Form(True),
    run_aspect: bool = Form(True),
    run_canopy: bool = Form(True),
    run_biomass: bool = Form(True),
    run_forest_health: bool = Form(True),
    run_forest_type: bool = Form(True),
    run_landcover: bool = Form(True),
    run_forest_loss: bool = Form(True),
    run_forest_gain: bool = Form(True),
    run_fire_loss: bool = Form(True),
    run_temperature: bool = Form(True),
    run_precipitation: bool = Form(True),
    run_soil: bool = Form(True),
    run_proximity: bool = Form(True),
    auto_generate_fieldbook: bool = Form(True),
    auto_generate_sampling: bool = Form(True),
    polygon_type: Optional[str] = Form(None),
    compartment_code_column: Optional[str] = Form(None),
    confirmed: bool = Form(False),
    # Map generation options (all optional, default False for on-demand generation)
    generate_boundary_map: bool = Form(False),
    generate_topographic_map: bool = Form(False),
    generate_slope_map: bool = Form(False),
    generate_aspect_map: bool = Form(False),
    generate_forest_type_map: bool = Form(False),
    generate_canopy_height_map: bool = Form(False),
    generate_landcover_change_map: bool = Form(False),
    generate_soil_map: bool = Form(False),
    generate_forest_health_map: bool = Form(False),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Upload forest boundary file for analysis

    Supported formats: Shapefile (.shp/.zip), KML, GeoJSON

    The file will be processed to extract geometry and prepare for analysis

    - **forest_name**: Required - Name of the forest (mandatory)
    - **block_name**: Optional - Name of the block

    Analysis Options (all default to True):
    - **run_raster_analysis**: Run all raster analyses (if False, skips all raster)
    - **run_elevation, run_slope, run_aspect**: Terrain analyses
    - **run_canopy, run_biomass, run_forest_health**: Forest structure
    - **run_forest_type, run_landcover**: Classification
    - **run_forest_loss, run_forest_gain, run_fire_loss**: Change detection
    - **run_temperature, run_precipitation, run_soil**: Climate & soil
    - **run_proximity**: Vector proximity analysis
    - **auto_generate_fieldbook, auto_generate_sampling**: Auto-generation

    Map Generation Options (all default to False for on-demand):
    - **generate_boundary_map**: Boundary map with context
    - **generate_topographic_map**: Elevation contours map
    - **generate_slope_map**: Slope classification map
    - **generate_aspect_map**: Aspect/direction map
    - **generate_forest_type_map**: Forest type classification map
    - **generate_canopy_height_map**: Canopy height structure map
    - **generate_landcover_change_map**: Land cover change map
    - **generate_soil_map**: Soil texture map
    - **generate_forest_health_map**: Forest health map
    """
    # Check if file upload is available
    if not FILE_UPLOAD_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="File upload functionality is temporarily disabled due to missing dependencies (GDAL/pyproj). Please contact support.",
        )

    # Process uploaded file
    try:
        wkt, metadata = await process_uploaded_file(file)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing file: {str(e)}",
        )

    # Forest-boundary validation (UNIFIED_UPLOAD_PLAN.md §5): within Nepal
    # (a boundary straddling the border is clipped to the admin.province union
    # and the user notified), ≤ 1000 ha, ≤ 40% built-up + cropland,
    # protected-area overlap must be a Buffer Zone. Errors block the upload;
    # warnings ride along on the response and are stored on the calculation.
    try:
        _bv = enforce_boundary_rules(db, wkt, forest_name=forest_name)
    except BoundaryRulesViolation as bv:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=bv.detail
        )
    bv_report = _bv.report
    wkt = _bv.effective_wkt  # the clipped-to-Nepal geometry, if R1 trimmed it

    # PF-3 provisional gate for upload: if proposed boundary adjoins/overlaps and not confirmed, return preview without creating calculation
    if not confirmed:
        try:
            from shapely import wkt as _ul_wkt
            from shapely.geometry import mapping as _ul_mapping
            from geoalchemy2 import Geography as _UlGeography
            from sqlalchemy import func as _ul_func
            from decimal import Decimal as _UlDecimal
            from uuid import UUID as _UlUUID
            from app.services.gap_detector import (
                detect_relations as _ul_detect,
                GapParams as _UlGapParams,
            )
            from app.schemas.boundary import (
                GapForest as _UlGapForest,
                OverlappingForest as _UlOverlappingForest,
            )

            _geom = _ul_wkt.loads(wkt)
            if not _geom.is_valid:
                from shapely.validation import make_valid

                _geom = make_valid(_geom)
            existing = (
                db.query(Calculation)
                .filter(
                    Calculation.boundary_geom.isnot(None),
                    _ul_func.ST_DWithin(
                        Calculation.boundary_geom.cast(_UlGeography),
                        _ul_func.ST_GeomFromText(wkt, 4326).cast(_UlGeography),
                        200,
                    ),
                )
                .all()
            )
            relations = _ul_detect(
                _ul_mapping(_geom),
                existing,
                _UlGapParams(adjacency_m=200, min_fragment_ha=0.001),
            )
            has = any(
                float(r.overlap_ha or 0) > 0 for r in relations
            )  # clip-only: overlap gates the review, gaps do not
            if has:
                gaps = []
                gap_total = _UlDecimal("0")
                for r in relations:
                    gap_geom = None
                    if r.gap_polygon is not None and not r.gap_polygon.is_empty:
                        gap_geom = _ul_mapping(r.gap_polygon)
                    gaps.append(
                        _UlGapForest(
                            id=_UlUUID(r.id),
                            name=r.name,
                            name_np=r.name_np,
                            overlap_ha=_UlDecimal(str(r.overlap_ha)),
                            gap_ha=_UlDecimal(str(r.gap_ha)),
                            gap_shape=r.gap_shape,
                            gap_size=r.gap_size,
                            gap_geometry=gap_geom,
                            adjacent=r.adjacent,
                        )
                    )
                    gap_total += _UlDecimal(str(r.gap_ha))
                gap_total = round(gap_total, 4)
                overlapping = []
                for r in relations:
                    if float(r.overlap_ha or 0) > 0:
                        overlapping.append(
                            _UlOverlappingForest(
                                id=_UlUUID(r.id),
                                name=r.name,
                                name_np=r.name_np,
                                overlap_ha=_UlDecimal(str(r.overlap_ha)),
                                forest_area_ha=_UlDecimal("0"),
                                gap_ha=_UlDecimal(str(r.gap_ha)),
                                gap_shape=r.gap_shape,
                                gap_size=r.gap_size,
                                adjacent=r.adjacent,
                            )
                        )
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    content={
                        "needs_overlap_review": True,
                        "provisional": True,
                        "overlapping_forests": [
                            o.model_dump(mode="json") for o in overlapping
                        ],
                        "gaps": [g.model_dump(mode="json") for g in gaps],
                        "gap_total_ha": float(gap_total),
                        "preview_geometry": _ul_mapping(_geom),
                    }
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(
                f"[upload-boundary] preview gate failed, falling through to write: {e}"
            )

    # Prepare blocks data for JSONB storage
    blocks_data = []
    if "blocks" in metadata:
        for block in metadata["blocks"]:
            bg = block["geometry"]
            centroid = block["centroid"]
            blocks_data.append(
                {
                    "block_index": block["index"],
                    "block_name": block["name"],
                    "area_sqm": block["area_sqm"],
                    "area_hectares": block["area_hectares"],
                    "geometry": bg if isinstance(bg, dict) else mapping(bg),
                    "centroid": {
                        "lon": (
                            centroid["lon"]
                            if isinstance(centroid, dict)
                            else centroid.x
                        ),
                        "lat": (
                            centroid["lat"]
                            if isinstance(centroid, dict)
                            else centroid.y
                        ),
                    },
                }
            )

    # Prepare result_data — support both block and compartment modes
    if polygon_type == "compartment":
        from ..services.map_creation_service import process_as_compartments

        # Normalize upload block keys to what process_as_compartments expects (name, id)
        normalized_blocks = []
        for b in blocks_data:
            nb = dict(b)
            nb["name"] = nb.pop("block_name", f"B{nb.get('block_index', 0)}")
            nb["id"] = nb.pop("block_index", None)
            normalized_blocks.append(nb)

        result_data = process_as_compartments(
            normalized_blocks,
            forest_name,
            compartment_code_column=compartment_code_column or "name",
        )
        result_data["creation_method"] = "file_upload"
        result_data["polygon_type"] = "compartment"
        blocks_for_analysis = result_data.get("compartments", [])
        logger.info(
            f"[upload-boundary] Compartment mode: {result_data['total_compartments']} compartments"
        )
    else:
        result_data = {
            "total_blocks": metadata.get("block_count", 1),
            "blocks": blocks_data,
            "creation_method": "file_upload",
            "processing_info": {
                "partitioned": metadata.get("partitioned", False),
                "partition_info": metadata.get("partition_info", {}),
            },
        }

    # Keep the boundary-validation report (facts + any warnings) on the record.
    result_data["boundary_validation"] = bv_report.as_dict()

    # Build analysis options dict (for saving to database)
    analysis_options_dict = {
        "run_raster_analysis": run_raster_analysis,
        "run_elevation": run_elevation,
        "run_slope": run_slope,
        "run_aspect": run_aspect,
        "run_canopy": run_canopy,
        "run_biomass": run_biomass,
        "run_forest_health": run_forest_health,
        "run_forest_type": run_forest_type,
        "run_landcover": run_landcover,
        "run_forest_loss": run_forest_loss,
        "run_forest_gain": run_forest_gain,
        "run_fire_loss": run_fire_loss,
        "run_temperature": run_temperature,
        "run_precipitation": run_precipitation,
        "run_soil": run_soil,
        "run_proximity": run_proximity,
        "auto_generate_fieldbook": auto_generate_fieldbook,
        "auto_generate_sampling": auto_generate_sampling,
    }

    # Build map options dict (for saving to database)
    map_options_dict = {
        "generate_boundary_map": generate_boundary_map,
        "generate_topographic_map": generate_topographic_map,
        "generate_slope_map": generate_slope_map,
        "generate_aspect_map": generate_aspect_map,
        "generate_forest_type_map": generate_forest_type_map,
        "generate_canopy_height_map": generate_canopy_height_map,
        "generate_landcover_change_map": generate_landcover_change_map,
        "generate_soil_map": generate_soil_map,
        "generate_forest_health_map": generate_forest_health_map,
    }

    # Create calculation record with WKT geometry and user options
    # Always set to PENDING to let user review/finalize blocks and sub-areas before analysis
    # User can skip block naming for single polygons, but still has the option to add sub-areas
    initial_status = CalculationStatus.PENDING

    calculation = Calculation(
        user_id=current_user.id,
        uploaded_filename=file.filename,
        boundary_geom=func.ST_GeomFromText(wkt, 4326),
        forest_name=forest_name,  # Now mandatory from form
        block_name=block_name
        or (blocks_data[0]["block_name"] if blocks_data else "B1"),
        status=initial_status,
        result_data=result_data,
        analysis_options=analysis_options_dict,
        map_options=map_options_dict,
    )

    db.add(calculation)
    db.commit()
    db.refresh(calculation)

    # Get the calculation ID
    calc_id = calculation.id

    # Note: Analysis is NOT started here - it should be triggered separately from Analysis page
    # User will configure blocks first, then trigger analysis when ready

    # Re-query calculation to ensure we have fresh data
    calculation = db.query(Calculation).filter(Calculation.id == calc_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calculation not found after processing",
        )

    # Get geometry as GeoJSON
    geometry_json = None
    try:
        # First check if geometry is valid
        validity_check = (
            db.query(func.ST_IsValid(Calculation.boundary_geom).label("is_valid"))
            .filter(Calculation.id == calc_id)
            .first()
        )

        if validity_check and not validity_check.is_valid:
            logger.warning(
                f"WARNING: Geometry for calculation {calc_id} is invalid in database"
            )

        geojson_query = (
            db.query(func.ST_AsGeoJSON(Calculation.boundary_geom).label("geojson"))
            .filter(Calculation.id == calc_id)
            .first()
        )

        if geojson_query and geojson_query.geojson:
            geometry_json = json.loads(geojson_query.geojson)
            logger.info(
                f"Successfully converted geometry to GeoJSON for calculation {calc_id}"
            )
        else:
            logger.warning(f"WARNING: No geometry found for calculation {calc_id}")
    except Exception as e:
        logger.error(
            f"ERROR: Failed to convert geometry to GeoJSON for calculation {calc_id}: {e}"
        )

    # Filter out removed species from potential_species
    result_data = calculation.result_data or {}
    if result_data:
        # Make a copy to avoid modifying the database object
        result_data = dict(result_data)

        # Get list of removed species
        removed_species = result_data.get("removed_species", [])

        # Filter potential_species to exclude removed ones
        if "potential_species" in result_data and removed_species:
            result_data["potential_species"] = [
                sp
                for sp in result_data["potential_species"]
                if sp.get("scientific_name") not in removed_species
            ]
            # Update count
            result_data["species_count"] = len(result_data["potential_species"])

    return CalculationResponse(
        id=calculation.id,
        user_id=calculation.user_id,
        uploaded_filename=calculation.uploaded_filename,
        forest_name=calculation.forest_name,
        block_name=calculation.block_name,
        status=calculation.status,
        processing_time_seconds=calculation.processing_time_seconds,
        error_message=calculation.error_message,
        created_at=calculation.created_at,
        completed_at=calculation.completed_at,
        geometry=geometry_json,
        result_data=result_data,
    )


# why: map-created boundaries use same analysis pipeline as file uploads (reuses process_map_creation_data)
@router.post(
    "/create-from-map",
    response_model=CalculationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_forest_from_map(
    request: MapCreationRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Create forest boundary through interactive map creation

    Allows users to create forest boundaries by:
    - Drawing on map directly
    - Auto-creating from GPS points
    - Splitting into blocks
    - Defining sub-areas

    The created boundary will be analyzed the same way as uploaded files.
    """

    # Validate map creation data
    validation_result = validate_map_creation_data(
        request.outer_boundary, [block.model_dump() for block in request.blocks]
    )

    if not validation_result["valid"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Validation failed: {'; '.join(validation_result['errors'])}",
        )

    # Process map creation data
    try:
        boundary_wkt, metadata = process_map_creation_data(
            request.outer_boundary,
            [block.model_dump() for block in request.blocks],
            gps_points=(
                [point.model_dump() for point in request.gps_points]
                if request.gps_points
                else None
            ),
            sub_areas=(
                [area.model_dump() for area in request.sub_areas]
                if request.sub_areas
                else None
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # PF-3 provisional gate for map-draw: if proposed boundary adjoins/overlaps and not confirmed, return preview without creating
    if not request.confirmed:
        try:
            from shapely import wkt as _cm_wkt
            from shapely.geometry import mapping as _cm_mapping
            from geoalchemy2 import Geography as _CmGeography
            from sqlalchemy import func as _cm_func
            from decimal import Decimal as _CmDecimal
            from uuid import UUID as _CmUUID
            from app.services.gap_detector import (
                detect_relations as _cm_detect,
                GapParams as _CmGapParams,
            )
            from app.schemas.boundary import (
                GapForest as _CmGapForest,
                OverlappingForest as _CmOverlappingForest,
            )

            _geom = _cm_wkt.loads(boundary_wkt)
            if not _geom.is_valid:
                from shapely.validation import make_valid

                _geom = make_valid(_geom)
            existing = (
                db.query(Calculation)
                .filter(
                    Calculation.boundary_geom.isnot(None),
                    _cm_func.ST_DWithin(
                        Calculation.boundary_geom.cast(_CmGeography),
                        _cm_func.ST_GeomFromText(boundary_wkt, 4326).cast(_CmGeography),
                        200,
                    ),
                )
                .all()
            )
            relations = _cm_detect(
                _cm_mapping(_geom),
                existing,
                _CmGapParams(adjacency_m=200, min_fragment_ha=0.001),
            )
            has = any(
                float(r.overlap_ha or 0) > 0 for r in relations
            )  # clip-only: overlap gates the review, gaps do not
            if has:
                gaps = []
                gap_total = _CmDecimal("0")
                for r in relations:
                    gap_geom = None
                    if r.gap_polygon is not None and not r.gap_polygon.is_empty:
                        gap_geom = _cm_mapping(r.gap_polygon)
                    gaps.append(
                        _CmGapForest(
                            id=_CmUUID(r.id),
                            name=r.name,
                            name_np=r.name_np,
                            overlap_ha=_CmDecimal(str(r.overlap_ha)),
                            gap_ha=_CmDecimal(str(r.gap_ha)),
                            gap_shape=r.gap_shape,
                            gap_size=r.gap_size,
                            gap_geometry=gap_geom,
                            adjacent=r.adjacent,
                        )
                    )
                    gap_total += _CmDecimal(str(r.gap_ha))
                gap_total = round(gap_total, 4)
                overlapping = []
                for r in relations:
                    if float(r.overlap_ha or 0) > 0:
                        overlapping.append(
                            _CmOverlappingForest(
                                id=_CmUUID(r.id),
                                name=r.name,
                                name_np=r.name_np,
                                overlap_ha=_CmDecimal(str(r.overlap_ha)),
                                forest_area_ha=_CmDecimal("0"),
                                gap_ha=_CmDecimal(str(r.gap_ha)),
                                gap_shape=r.gap_shape,
                                gap_size=r.gap_size,
                                adjacent=r.adjacent,
                            )
                        )
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    content={
                        "needs_overlap_review": True,
                        "provisional": True,
                        "overlapping_forests": [
                            o.model_dump(mode="json") for o in overlapping
                        ],
                        "gaps": [g.model_dump(mode="json") for g in gaps],
                        "gap_total_ha": float(gap_total),
                        "preview_geometry": _cm_mapping(_geom),
                    }
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(
                f"[create-from-map] preview gate failed, falling through to write: {e}"
            )

    # Prepare blocks for analysis
    blocks_for_analysis = prepare_block_analysis_data(
        [block.model_dump() for block in request.blocks]
    )

    # Dispatch based on polygon_type
    if request.polygon_type.value == "compartment":
        initial_result_data = process_as_compartments(
            [block.model_dump() for block in request.blocks],
            request.forest_name,
            compartment_code_column=request.compartment_code_column,
        )
        initial_result_data["creation_method"] = "map_creation"
        initial_result_data["polygon_type"] = "compartment"
        blocks_for_analysis = initial_result_data.get("compartments", [])
        logger.info(
            f"[create-from-map] Compartment mode: {initial_result_data['total_compartments']} compartments"
        )
    else:
        # Calculate total area from all blocks
        total_area_hectares = sum(
            block["area_hectares"] for block in blocks_for_analysis
        )

        # Create initial result_data with blocks
        initial_result_data = {
            "total_blocks": len(blocks_for_analysis),
            "blocks": blocks_for_analysis,
            "creation_method": "map_creation",
            "area_hectares": round(total_area_hectares, 4),
        }

    # Add GPS points and sub-areas to metadata
    if metadata.get("gps_points"):
        initial_result_data["gps_points"] = metadata["gps_points"]
        initial_result_data["gps_points_count"] = metadata["gps_points_count"]

    if metadata.get("sub_areas"):
        initial_result_data["sub_areas"] = metadata["sub_areas"]
        initial_result_data["sub_areas_count"] = metadata["sub_areas_count"]

        # DEBUG LOGGING: Track sub-area geometries
        logger.info(f"\n{'='*60}")
        logger.info(f"📍 SUB-AREAS RECEIVED: {metadata['sub_areas_count']} sub-areas")
        for idx, sub_area in enumerate(metadata["sub_areas"]):
            geom = sub_area.get("geometry", {})
            coords = geom.get("coordinates", [])
            area_ha = sub_area.get("area_hectares", 0)
            category = sub_area.get("category", "unknown")
            name = sub_area.get("name", f"SubArea {idx+1}")

            logger.info(f"  Sub-area #{idx+1}: {name}")
            logger.info(f"    Category: {category}")
            logger.info(f"    Area: {area_ha:.4f} ha")
            logger.info(f"    Geometry type: {geom.get('type', 'unknown')}")
            if coords:
                # Show first coordinate to verify it's not block coordinates
                first_ring = coords[0] if coords else []
                if first_ring and len(first_ring) > 0:
                    first_point = first_ring[0]
                    logger.info(
                        f"    First coordinate: [{first_point[0]:.6f}, {first_point[1]:.6f}]"
                    )
                    logger.info(f"    Total points: {len(first_ring)}")
        logger.info(f"{'='*60}\n")

        # Calculate excluded area from sub-areas (use helper for consistency)
        excluded_area = calculate_total_excluded_area(metadata["sub_areas"])
        initial_result_data["excluded_area_hectares"] = round(excluded_area, 4)
        initial_result_data["effective_area_hectares"] = round(
            total_area_hectares - excluded_area, 4
        )

        if excluded_area > 0:
            logger.info(f"  Excluded area total: {excluded_area:.4f} ha")
            logger.info(
                f"  Effective forest area: {initial_result_data['effective_area_hectares']:.4f} ha"
            )

            # Calculate excluded area per block (handles cross-block sub-areas)
            logger.info(f"\n[create-from-map] Calculating per-block excluded areas...")
            block_excluded_map = calculate_block_excluded_areas(
                blocks_for_analysis, metadata["sub_areas"]
            )

            for block in blocks_for_analysis:
                block_id = block.get("block_id")
                block_name = block.get("block_name")
                block_excluded = block_excluded_map.get(block_id, 0.0)

                block["excluded_area_hectares"] = round(block_excluded, 4)
                original_area = block.get("area_hectares", 0)
                block["effective_area_hectares"] = round(
                    original_area - block_excluded, 4
                )

                if block_excluded > 0:
                    logger.info(
                        f"  Block '{block_name}': {original_area:.2f} ha - {block_excluded:.2f} ha = {block['effective_area_hectares']:.2f} ha"
                    )
    else:
        # No sub-areas: set excluded to 0 and effective = total
        initial_result_data["excluded_area_hectares"] = 0.0
        initial_result_data["effective_area_hectares"] = round(total_area_hectares, 4)
        # Set effective_area_hectares for each block
        for block in blocks_for_analysis:
            block["excluded_area_hectares"] = 0
            block["effective_area_hectares"] = block.get("area_hectares", 0)

    # Create Calculation record (wrapped in single transaction with rollback)
    try:
        calculation = Calculation(
            user_id=current_user.id,
            uploaded_filename="map_created_boundary.geojson",
            forest_name=request.forest_name,
            boundary_geom=boundary_wkt,
            status=CalculationStatus.PROCESSING,
            result_data=initial_result_data,
            created_at=datetime.now(timezone.utc),
        )

        db.add(calculation)
        db.flush()
        db.refresh(calculation)

        # Mark result_data as modified (JSONB column)
        flag_modified(calculation, "result_data")
        db.flush()

        # Create ForestBlock records from blocks or compartments in result_data
        if blocks_for_analysis:
            from app.models.forest_block import ForestBlock
            from uuid import uuid4

            logger.info(
                f"[create-from-map] Creating {len(blocks_for_analysis)} ForestBlock records"
                f" (mode: {request.polygon_type.value})..."
            )

            is_compartment_mode = request.polygon_type.value == "compartment"

            if is_compartment_mode:
                # Create parent block (union of all compartment geometries)
                parent_uuid = uuid4()
                parent_block = None

            for idx, block_data in enumerate(blocks_for_analysis):
                geometry = block_data.get("geometry")
                if not geometry:
                    continue

                block_geom_wkt = db.scalar(
                    select(
                        func.ST_AsText(func.ST_GeomFromGeoJSON(json.dumps(geometry)))
                    )
                )

                if not block_geom_wkt:
                    logger.warning(
                        f"  Warning: Could not convert geometry for {block_data.get('block_name')}"
                    )
                    continue

                if is_compartment_mode:
                    # Create parent block first (only once)
                    if parent_block is None:
                        from shapely.geometry import shape
                        from shapely.ops import unary_union

                        # Compute parent geometry union in Python using Shapely
                        parent_shape = unary_union(
                            [
                                shape(b.get("geometry"))
                                for b in blocks_for_analysis
                                if b.get("geometry")
                            ]
                        )

                        if parent_shape and not parent_shape.is_empty:
                            from shapely import wkt as shapely_wkt

                            parent_union_wkt = shapely_wkt.dumps(parent_shape)

                            parent_uuid = uuid4()
                            parent_block = ForestBlock(
                                id=parent_uuid,
                                calculation_id=calculation.id,
                                name=request.forest_name or "Forest",
                                geometry=func.ST_GeomFromText(parent_union_wkt, 4326),
                                area_hectares=sum(
                                    b.get("area_hectares", 0)
                                    for b in blocks_for_analysis
                                ),
                                index=0,
                                created_at=datetime.now(timezone.utc),
                                division_level=DEPTH_TOP_BLOCK,
                                is_compartment=False,
                            )
                            db.add(parent_block)
                            db.flush()

                    # Create compartment record
                    forest_block = ForestBlock(
                        id=uuid4(),
                        calculation_id=calculation.id,
                        name=block_data.get("block_name", f"Compartment {idx + 1}"),
                        geometry=func.ST_GeomFromText(block_geom_wkt, 4326),
                        area_hectares=block_data.get("area_hectares", 0),
                        index=idx,
                        created_at=datetime.now(timezone.utc),
                        is_compartment=True,
                        division_level=DEPTH_TOP_COMPARTMENT,
                        parent_block_id=parent_uuid,
                        compartment_code=block_data.get(
                            "compartment_code",
                            block_data.get("block_name", f"C{idx + 1}"),
                        ),
                    )
                else:
                    forest_block = ForestBlock(
                        id=uuid4(),
                        calculation_id=calculation.id,
                        name=block_data.get("block_name", f"B{idx + 1}"),
                        geometry=func.ST_GeomFromText(block_geom_wkt, 4326),
                        area_hectares=block_data.get("area_hectares", 0),
                        index=idx,
                        created_at=datetime.now(timezone.utc),
                        division_level=DEPTH_TOP_BLOCK,
                    )
                db.add(forest_block)

        # Single commit for all operations
        db.commit()
        db.refresh(calculation)
        logger.info(
            f"[create-forest-from-map] Forest created with status PENDING. Analysis can be triggered from Analysis page."
        )

    except Exception as e:
        db.rollback()
        logger.error(
            f"[create-forest-from-map] Transaction failed, rolled back: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create forest: {str(e)}",
        )

    # Prepare response
    geometry_json = None
    if calculation.boundary_geom:
        try:
            geom_wkb = db.execute(
                text("SELECT ST_AsEWKB(:geom) as geom"),
                {"geom": calculation.boundary_geom},
            ).scalar()
            if geom_wkb:
                geom = wkb.loads(bytes(geom_wkb))
                geometry_json = mapping(geom)
        except Exception as e:
            logger.error(f"Error converting geometry: {e}")

    result_data = calculation.result_data or {}

    # Final verification before returning response
    from app.models.fieldbook import Fieldbook

    final_count = (
        db.query(Fieldbook).filter(Fieldbook.calculation_id == calculation.id).count()
    )
    logger.info(
        f"✓ Final verification before response: {final_count} fieldbook points in database"
    )

    return CalculationResponse(
        id=calculation.id,
        user_id=calculation.user_id,
        uploaded_filename=calculation.uploaded_filename,
        forest_name=calculation.forest_name,
        block_name=calculation.block_name,
        status=calculation.status,
        processing_time_seconds=calculation.processing_time_seconds,
        error_message=calculation.error_message,
        created_at=calculation.created_at,
        completed_at=calculation.completed_at,
        geometry=geometry_json,
        result_data=result_data,
    )


# business: CFMG — calculation status tracks: pending → analyzing → completed/failed
# why: async analysis runs per-block in background for large forests
@router.post(
    "/calculations/{calculation_id}/reanalyze", response_model=CalculationResponse
)
async def reanalyze_calculation(
    calculation_id: UUID,
    request: ReanalysisRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Re-run analysis on an existing calculation with different options

    This allows users to re-analyze their boundary with different parameters
    without re-uploading the file. Useful for:
    - Enabling analyses that were initially skipped
    - Disabling expensive analyses to save processing time
    - Experimenting with different analysis combinations

    The boundary geometry and forest/block names are preserved.
    Only the analysis results are updated based on new options.
    """
    # Get existing calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership (users can only reanalyze their own calculations, except super admins)
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to reanalyze this calculation",
        )

    # Merge new options with stored options (new options override stored ones)
    stored_options = calculation.analysis_options or {}
    new_options = {}

    # Build analysis options from request (only include non-None values)
    if request.run_raster_analysis is not None:
        new_options["run_raster_analysis"] = request.run_raster_analysis
    if request.run_elevation is not None:
        new_options["run_elevation"] = request.run_elevation
    if request.run_slope is not None:
        new_options["run_slope"] = request.run_slope
    if request.run_aspect is not None:
        new_options["run_aspect"] = request.run_aspect
    if request.run_canopy is not None:
        new_options["run_canopy"] = request.run_canopy
    if request.run_biomass is not None:
        new_options["run_biomass"] = request.run_biomass
    if request.run_forest_health is not None:
        new_options["run_forest_health"] = request.run_forest_health
    if request.run_forest_type is not None:
        new_options["run_forest_type"] = request.run_forest_type
    if request.run_landcover is not None:
        new_options["run_landcover"] = request.run_landcover
    if request.run_forest_loss is not None:
        new_options["run_forest_loss"] = request.run_forest_loss
    if request.run_forest_gain is not None:
        new_options["run_forest_gain"] = request.run_forest_gain
    if request.run_fire_loss is not None:
        new_options["run_fire_loss"] = request.run_fire_loss
    if request.run_temperature is not None:
        new_options["run_temperature"] = request.run_temperature
    if request.run_precipitation is not None:
        new_options["run_precipitation"] = request.run_precipitation
    if request.run_soil is not None:
        new_options["run_soil"] = request.run_soil
    if request.run_proximity is not None:
        new_options["run_proximity"] = request.run_proximity

    # Merge with stored options (new options take precedence)
    analysis_options = {**stored_options, **new_options}

    # The analysis itself is shared with the workspace's "Update attribute" command (services/reanalysis_service.py).
    try:
        await run_reanalysis(db, calculation, analysis_options)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Re-analysis failed: {str(e)}",
        )

    # Refresh calculation
    db.refresh(calculation)

    # Get geometry as GeoJSON
    geojson_query = (
        db.query(func.ST_AsGeoJSON(Calculation.boundary_geom).label("geojson"))
        .filter(Calculation.id == calculation_id)
        .first()
    )

    geometry_json = (
        json.loads(geojson_query.geojson)
        if geojson_query and geojson_query.geojson
        else None
    )

    # Filter out removed species from potential_species
    result_data = calculation.result_data or {}
    if result_data:
        # Make a copy to avoid modifying the database object
        result_data = dict(result_data)

        # Get list of removed species
        removed_species = result_data.get("removed_species", [])

        # Filter potential_species to exclude removed ones
        if "potential_species" in result_data and removed_species:
            result_data["potential_species"] = [
                sp
                for sp in result_data["potential_species"]
                if sp.get("scientific_name") not in removed_species
            ]
            # Update count
            result_data["species_count"] = len(result_data["potential_species"])

    return CalculationResponse(
        id=calculation.id,
        user_id=calculation.user_id,
        uploaded_filename=calculation.uploaded_filename,
        forest_name=calculation.forest_name,
        block_name=calculation.block_name,
        status=calculation.status,
        processing_time_seconds=calculation.processing_time_seconds,
        error_message=calculation.error_message,
        created_at=calculation.created_at,
        completed_at=calculation.completed_at,
        geometry=geometry_json,
        result_data=result_data,
    )


# NOTE: some map layers (topographic, forest_type, canopy_height, soil, forest_health) not yet implemented — return "not implemented" status
@router.post("/calculations/{calculation_id}/generate-maps")
def generate_maps(
    calculation_id: UUID,
    request: GenerateMapsRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Generate maps on-demand for a calculation

    This endpoint generates the selected maps for an existing calculation.
    Maps are generated as A5 PNG files (1748×2480 pixels at 300 DPI) with:
    - Professional cartographic styling
    - Title, legend, north arrow
    - Thematic colors and classifications

    Available maps:
    - Boundary Map: Forest boundary with surrounding context
    - Topographic Map: Elevation contours
    - Slope Map: Slope classification (Gentle, Moderate, Steep, Very Steep)
    - Aspect Map: 8-directional aspect distribution
    - Forest Type Map: Forest species classification
    - Canopy Height Map: Forest structure (Open, Medium, Dense, Very Dense)
    - Land Cover Change Map: Historical land cover changes
    - Soil Map: Soil texture classification
    - Forest Health Map: Forest health status (5 classes)

    The endpoint returns download URLs for each generated map.
    """
    # Get existing calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to generate maps for this calculation",
        )

    # Verify calculation is completed
    if calculation.status != CalculationStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot generate maps for calculation with status: {calculation.status.value}. Analysis must be completed first.",
        )

    # Verify at least one map type is selected
    map_types_selected = [
        request.generate_boundary_map,
        request.generate_topographic_map,
        request.generate_slope_map,
        request.generate_aspect_map,
        request.generate_forest_type_map,
        request.generate_canopy_height_map,
        request.generate_landcover_change_map,
        request.generate_soil_map,
        request.generate_forest_health_map,
    ]

    if not any(map_types_selected):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one map type must be selected",
        )

    # Build map generation results
    generated_maps = []
    failed_maps = []

    # Map generation functions mapping
    # NOTE: Some maps are not yet implemented
    map_functions = {
        "boundary": ("generate_boundary_map", request.generate_boundary_map),
        "slope": ("generate_slope_map", request.generate_slope_map),
        "aspect": ("generate_aspect_map", request.generate_aspect_map),
        "landcover": ("generate_landcover_map", request.generate_landcover_change_map),
        # TODO: Implement these 5 maps
        # 'topographic': ('generate_topographic_map', request.generate_topographic_map),
        # 'forest_type': ('generate_forest_type_map', request.generate_forest_type_map),
        # 'canopy_height': ('generate_canopy_height_map', request.generate_canopy_height_map),
        # 'soil': ('generate_soil_map', request.generate_soil_map),
        # 'forest_health': ('generate_forest_health_map', request.generate_forest_health_map),
    }

    # TODO: For maps not yet implemented, return "not implemented" status
    not_implemented = []
    if request.generate_topographic_map:
        not_implemented.append("topographic")
    if request.generate_forest_type_map:
        not_implemented.append("forest_type")
    if request.generate_canopy_height_map:
        not_implemented.append("canopy_height")
    if request.generate_soil_map:
        not_implemented.append("soil")
    if request.generate_forest_health_map:
        not_implemented.append("forest_health")

    # Generate requested maps
    for map_type, (function_name, should_generate) in map_functions.items():
        if not should_generate:
            continue

        try:
            logger.info(f"Generating {map_type} map for calculation {calculation_id}")
            # Map is generated dynamically via existing endpoints
            # Maps are not stored but generated on-demand
            generated_maps.append(
                {
                    "map_type": map_type,
                    "status": "success",
                    "download_url": f"/api/forests/calculations/{calculation_id}/maps/{map_type}",
                }
            )
        except Exception as e:
            logger.error(f"Failed to generate {map_type} map: {e}")
            failed_maps.append(
                {"map_type": map_type, "status": "failed", "error": str(e)}
            )

    # Update map_options in calculation to track what user requested
    updated_map_options = {
        "generate_boundary_map": request.generate_boundary_map,
        "generate_topographic_map": request.generate_topographic_map,
        "generate_slope_map": request.generate_slope_map,
        "generate_aspect_map": request.generate_aspect_map,
        "generate_forest_type_map": request.generate_forest_type_map,
        "generate_canopy_height_map": request.generate_canopy_height_map,
        "generate_landcover_change_map": request.generate_landcover_change_map,
        "generate_soil_map": request.generate_soil_map,
        "generate_forest_health_map": request.generate_forest_health_map,
    }

    # Save updated map options
    calculation.map_options = updated_map_options
    flag_modified(calculation, "map_options")
    db.commit()

    return {
        "calculation_id": str(calculation_id),
        "status": "success",
        "generated_maps": generated_maps,
        "failed_maps": failed_maps,
        "not_implemented": not_implemented,
        "message": f"Generated {len(generated_maps)} maps successfully. {len(failed_maps)} failed. {len(not_implemented)} not yet implemented.",
    }


# NOTE: tree cover area computed via pixel ratio (tree_pixels / total_pixels × boundary_area) ensuring consistency
@router.post("/calculations/{calculation_id}/tree-cover-areas")
def calculate_and_store_tree_cover_areas(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Calculate tree cover areas for all blocks and store in calculation result_data.

    Uses ratio-based approach to ensure consistency:
    1. Get authoritative boundary area from PostGIS geometry
    2. Count total pixels and tree pixels within boundary
    3. Calculate tree coverage ratio = tree_pixels / total_pixels
    4. Effective area = boundary_area × ratio

    This ensures pixel-based tree cover calculations align with geometry-based areas.

    **Returns:**
    - Block-wise tree cover statistics
    - Stores results in calculation.result_data['tree_cover_areas']
    """
    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    from ..models.user import UserRole

    if (
        calculation.user_id != current_user.id
        and current_user.role != UserRole.SUPER_ADMIN
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this calculation",
        )

    # Get blocks from result_data
    result_data = calculation.result_data or {}
    blocks = result_data.get("blocks", [])

    if not blocks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calculation has no defined areas. Analysis may not be complete.",
        )

    # Prepare blocks for tree cover calculation
    # Need to convert GeoJSON to WKT for the service function
    blocks_for_calc = []
    for block in blocks:
        # Try to get geometry in various formats
        block_geom = block.get("geometry_wkt") or block.get("geometry")

        if not block_geom:
            continue

        # Convert to WKT if it's GeoJSON
        try:
            if isinstance(block_geom, dict):
                # It's GeoJSON - convert to WKT
                geom_shape = shape(block_geom)
                block_geom_wkt = geom_shape.wkt
            elif isinstance(block_geom, str):
                # It's already WKT string
                block_geom_wkt = block_geom
            else:
                continue

            blocks_for_calc.append(
                {
                    "block_name": block.get(
                        "block_name", f"Block {block.get('block_number', '?')}"
                    ),
                    "geometry": block_geom_wkt,
                }
            )
        except Exception as e:
            logger.error(
                f"Error converting geometry for block {block.get('block_name')}: {e}"
            )
            continue

    if not blocks_for_calc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No areas with valid geometry found. Total areas: {len(blocks)}",
        )

    # Calculate tree cover areas
    try:
        tree_cover_results = calculate_block_tree_cover_areas(db, blocks_for_calc)

        # Store in calculation result_data
        if result_data is None:
            result_data = {}

        result_data["tree_cover_areas"] = tree_cover_results
        calculation.result_data = result_data
        flag_modified(calculation, "result_data")
        db.commit()

        return {
            "calculation_id": str(calculation_id),
            "forest_name": calculation.forest_name,
            "total_blocks": len(tree_cover_results),
            "tree_cover_areas": tree_cover_results,
            **i18n_success("success.tree_cover_calculated"),
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error calculating tree cover areas: {str(e)}",
        )


# business: CFMG — accessible forest area excludes steep slopes (>45°) and non-tree-cover
@router.get("/calculations/{calculation_id}/accessible-area")
def get_accessible_forest_area(
    calculation_id: UUID,
    filter_slope: bool = False,
    max_slope_degrees: float = 45.0,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Calculate accessible forest area for calculation blocks.

    Returns area breakdown per block showing:
    - Accessible forest area (tree cover + slope OK)
    - Inaccessible steep forest (tree cover but too steep)
    - Non-forest area

    **Parameters:**
    - `filter_slope`: If True, exclude steep slopes (default: False)
    - `max_slope_degrees`: Maximum slope threshold in degrees (default: 45.0)

    **Note:** Tree cover filtering (ESA WorldCover value=10) is always enabled.
    """
    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    from ..models.user import UserRole

    if (
        calculation.user_id != current_user.id
        and current_user.role != UserRole.SUPER_ADMIN
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this calculation",
        )

    # Get analysis units from result_data — compartments when the forest was
    # divided into them, else blocks (mirrors PolygonSource in the analysis
    # engine). The unit dicts store geometry as a GeoJSON dict under "geometry"
    # and a WKT string under "wkt"; "geometry_wkt" is not populated, so a
    # geometry_wkt-only read skipped every unit (and 400'd outright for a
    # compartment forest, whose result_data["blocks"] is empty).
    result_data = calculation.result_data or {}
    from ..services.analysis_polygon_source import PolygonSource

    units = PolygonSource.for_result_data(result_data).get_polygons()

    if not units:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calculation has no defined areas. Analysis may not be complete.",
        )

    def _unit_wkt(unit: dict) -> Optional[str]:
        """Resolve a unit's geometry to a WKT string across the key variants."""
        geom = unit.get("geometry_wkt") or unit.get("wkt") or unit.get("geometry")
        if not geom:
            return None
        if isinstance(geom, str):
            return geom
        if isinstance(geom, dict):
            try:
                return shape(geom).wkt
            except Exception as exc:  # noqa: BLE001 -- bad geometry -> skip this unit
                logger.warning(
                    "accessible-area: bad geometry for %s: %s",
                    unit.get("block_name"),
                    exc,
                )
                return None
        return None

    # Calculate accessible area for each unit
    results = []
    for block in units:
        block_number = (
            block.get("block_number")
            or block.get("compartment_number")
            or block.get("block_index")
        )
        block_name = (
            block.get("block_name")
            or block.get("name")
            or block.get("compartment_code")
            or f"Unit {block_number}"
        )
        block_area_ha = block.get("area_hectares", 0)

        # Get unit geometry
        block_geom_wkt = _unit_wkt(block)
        if not block_geom_wkt:
            # Skip units without geometry
            continue

        # Calculate accessible forest area
        try:
            area_info = calculate_accessible_forest_area(
                db=db,
                geometry_wkt=block_geom_wkt,
                filter_tree_cover=True,  # Always filter to tree cover
                filter_slope=filter_slope,
                max_slope_degrees=max_slope_degrees,
            )

            results.append(
                {
                    "block_name": block_name,
                    "block_number": block_number,
                    "block_area_ha": block_area_ha,
                    **area_info,
                }
            )
        except Exception as e:
            # Log error and continue with next unit
            logger.error(f"Error calculating accessible area for {block_name}: {e}")
            results.append(
                {
                    "block_name": block_name,
                    "block_number": block_number,
                    "block_area_ha": block_area_ha,
                    "error": str(e),
                }
            )

    return {
        "calculation_id": str(calculation_id),
        "forest_name": calculation.forest_name,
        "filter_slope": filter_slope,
        "max_slope_degrees": max_slope_degrees,
        "total_blocks": len(results),
        "blocks": results,
    }


@router.get("/calculations/{calculation_id}", response_model=CalculationResponse)
def get_calculation(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get calculation results by ID

    Users can only access their own calculations unless they are super admin
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    from ..models.user import UserRole

    if (
        calculation.user_id != current_user.id
        and current_user.role != UserRole.SUPER_ADMIN
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this calculation",
        )

    # Keep result_data.blocks reconciled with forest_blocks (single source of
    # truth). The workspace mutations write forest_blocks only; this guarantees
    # the legacy page and all consumers read the same blocks the map shows.
    if reconcile_blocks_from_db(db, calculation):
        db.commit()
        db.refresh(calculation)

    # Get geometry as GeoJSON
    geojson_query = (
        db.query(func.ST_AsGeoJSON(Calculation.boundary_geom).label("geojson"))
        .filter(Calculation.id == calculation_id)
        .first()
    )

    geometry_json = (
        json.loads(geojson_query.geojson)
        if geojson_query and geojson_query.geojson
        else None
    )

    # Filter out removed species from potential_species
    result_data = calculation.result_data or {}
    if result_data:
        # Make a copy to avoid modifying the database object
        result_data = dict(result_data)

        # Get list of removed species
        removed_species = result_data.get("removed_species", [])

        # Filter potential_species to exclude removed ones
        if "potential_species" in result_data and removed_species:
            result_data["potential_species"] = [
                sp
                for sp in result_data["potential_species"]
                if sp.get("scientific_name") not in removed_species
            ]
            # Update count
            result_data["species_count"] = len(result_data["potential_species"])

    return CalculationResponse(
        id=calculation.id,
        user_id=calculation.user_id,
        uploaded_filename=calculation.uploaded_filename,
        forest_name=calculation.forest_name,
        block_name=calculation.block_name,
        status=calculation.status,
        processing_time_seconds=calculation.processing_time_seconds,
        error_message=calculation.error_message,
        created_at=calculation.created_at,
        updated_at=calculation.updated_at,
        completed_at=calculation.completed_at,
        is_draft=calculation.is_draft,
        geometry=geometry_json,
        result_data=result_data,
        draft_data=calculation.draft_data,
        map_lifecycle_status=getattr(calculation, "map_lifecycle_status", None),
        structure_locked=bool(getattr(calculation, "structure_locked", False)),
        structure_locked_at=getattr(calculation, "structure_locked_at", None),
    )


# constraint: paginated at 50 per page for UI performance (also serves mobile)
@router.get("/calculations", response_model=List[CalculationResponse])
def list_calculations(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    List user's calculations

    Returns all calculations for the current user
    """
    query = db.query(Calculation).filter(Calculation.user_id == current_user.id)
    query = query.order_by(Calculation.created_at.desc())
    query = query.limit(limit).offset(offset)

    calculations = query.all()

    results = []
    for calc in calculations:
        results.append(
            CalculationResponse(
                id=calc.id,
                user_id=calc.user_id,
                uploaded_filename=calc.uploaded_filename,
                forest_name=calc.forest_name,
                block_name=calc.block_name,
                status=calc.status,
                processing_time_seconds=calc.processing_time_seconds,
                error_message=calc.error_message,
                created_at=calc.created_at,
                updated_at=calc.updated_at,
                completed_at=calc.completed_at,
                is_draft=calc.is_draft,
                geometry=None,  # Don't include geometry in list view
                result_data=None,  # Don't include full results in list view
                draft_data=calc.draft_data,  # Needed to detect boundary-less drafts
                map_lifecycle_status=getattr(calc, "map_lifecycle_status", None),
                structure_locked=bool(getattr(calc, "structure_locked", False)),
                structure_locked_at=getattr(calc, "structure_locked_at", None),
            )
        )

    return results


# NOTE: ORM cascade delete may be slow for calculations with many fieldbook points — cleans up export files first
@router.delete("/calculations/{calculation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calculation(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Delete a calculation **and all data associated with it** (rows and files). No archive.

    Users can only delete their own calculations
    Note: May be slow for calculations with many fieldbook points (uses ORM cascade)
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions.
    #
    # Owner's rule, 2026-08-27: a user who has submitted a map to calculation
    # may not delete it. A super admin may, whoever owns it. The owner gets it
    # back if the map is withdrawn to `draft` -- the restriction is about the
    # map's CURRENT state, not about it having once been submitted.
    from app.models.calculation import MapLifecycleStatus
    from app.models.user import UserRole

    is_super_admin = current_user.role == UserRole.SUPER_ADMIN
    if not is_super_admin:
        if calculation.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete this calculation",
            )
        if calculation.map_lifecycle_status != MapLifecycleStatus.DRAFT.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "SUBMITTED_NOT_DELETABLE",
                    "message": (
                        "This map has been submitted for calculation and can no "
                        "longer be deleted. Withdraw it back to draft first, or "
                        "ask a super admin."
                    ),
                    "message_np": (
                        "यो नक्सा गणनाका लागि पेश गरिसकिएको हुनाले मेट्न मिल्दैन। "
                        "पहिले ड्राफ्टमा फिर्ता लिनुहोस्, वा सुपर एडमिनलाई अनुरोध गर्नुहोस्।"
                    ),
                    "current_state": calculation.map_lifecycle_status,
                },
            )

    # Owner's rule, 2026-09-21 (replaces the 2026-08-27 "archive, never destroy" rule):
    # deleting a forest deletes ALL of its data. There is NO archive. Every table linked to a
    # forest cascades in the database (migration 092 closed the last gaps); the files the
    # database cannot see -- export files and the per-forest cache folders -- are handled by
    # services/forest_purge.py. Find the export paths BEFORE the rows go (they are stored in
    # them); remove the files only AFTER the commit, so a failed delete never loses a file.
    from ..services.forest_purge import collect_forest_files, remove_forest_files

    try:
        export_paths = collect_forest_files(db, calculation_id)

        # ORM delete: cascades through the relationships that declare it, and the database's
        # ON DELETE CASCADE handles the rest.
        db.delete(calculation)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting calculation {calculation_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete calculation: {str(e)}",
        )

    removed = remove_forest_files(calculation_id, export_paths)
    logger.info(
        "Deleted calculation %s and all of its data (%d export file(s), %d cache folder group(s) removed)",
        calculation_id,
        removed["export_files"],
        removed["cache_folders"],
    )
    return None


@router.patch("/calculations/{calculation_id}/result-data")
def update_result_data(
    calculation_id: UUID,
    update_data: dict,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Update result_data fields for a calculation (field verification edits)

    Users can only update their own calculations.
    Accepts a JSON body with fields to update - merges into existing result_data.
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    from ..models.user import UserRole

    if (
        calculation.user_id != current_user.id
        and current_user.role != UserRole.SUPER_ADMIN
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this calculation",
        )

    # Merge update_data into existing result_data
    existing = calculation.result_data or {}
    existing.update(update_data)
    calculation.result_data = existing
    flag_modified(calculation, "result_data")

    db.commit()
    db.refresh(calculation)

    return {"status": "updated", "result_data": calculation.result_data}


# ============================================================================
# MAP GENERATION ENDPOINTS
# ============================================================================


@router.get("/calculations/{calculation_id}/maps/boundary")
def generate_boundary_map(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Generate an SVG boundary map for the given calculation."""

    cached = _cached_map_stream(calculation_id, "boundary")
    if cached:
        return cached

    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )
    if not calculation.boundary_geom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No boundary geometry"
        )

    try:
        geom_shape = wkb.loads(bytes(calculation.boundary_geom.data))
        geometry = mapping(geom_shape)
        map_generator = get_map_generator()
        buffer = map_generator.generate_boundary_map(
            geometry=geometry,
            forest_name=calculation.forest_name or "Community Forest",
            orientation="auto",
            db_session=db,
            show_schools=True,
            show_poi=True,
            show_roads=True,
            show_rivers=True,
            show_ridges=True,
            show_esa_boundary=True,
            buffer_m=100.0,
        )
        _save_map_cache(calculation_id, "boundary", buffer.getvalue())
        return StreamingResponse(
            io.BytesIO(buffer.getvalue()),
            media_type="image/svg+xml",
            headers={
                "Content-Disposition": f"inline; filename=boundary_map_{calculation_id}.svg"
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error: {str(e)}"
        )


_MAP_LAYER_NAMES = {
    "slope": "slope",
    "aspect": "aspect",
    "landcover": "landcover",
    "topographic": "topographic",
    "forest_type": "forest_type",
    "canopy_height": "canopy_height",
    "soil": "soil",
    "forest_health": "forest_health",
}

_MAP_GENERATORS = {
    "slope": "generate_slope_map",
    "aspect": "generate_aspect_map",
    "landcover": "generate_landcover_map",
    "topographic": "generate_topographic_map",
    "forest_type": "generate_forest_type_map",
    "canopy_height": "generate_canopy_height_map",
    "soil": "generate_soil_map",
    "forest_health": "generate_forest_health_map",
}


def _generate_raster_map(
    calculation_id: UUID, layer: str, db: Session, current_user: User
):
    cached = _cached_map_stream(calculation_id, layer)
    if cached:
        return cached

    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )
    if not calculation.boundary_geom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No boundary geometry"
        )

    try:
        geom_shape = wkb.loads(bytes(calculation.boundary_geom.data))
        geometry = mapping(geom_shape)
        map_generator = get_map_generator()
        fn_name = _MAP_GENERATORS[layer]
        fn = getattr(map_generator, fn_name)
        buffer = fn(
            geometry=geometry,
            db_session=db,
            forest_name=calculation.forest_name or "Community Forest",
            orientation="auto",
        )
        _save_map_cache(calculation_id, layer, buffer.getvalue())
        return StreamingResponse(
            io.BytesIO(buffer.getvalue()),
            media_type="image/svg+xml",
            headers={
                "Content-Disposition": f"inline; filename={layer}_map_{calculation_id}.svg"
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/calculations/{calculation_id}/maps/{layer}")
def generate_raster_map(
    calculation_id: UUID,
    layer: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Generate an SVG raster map for the given layer (slope, aspect, landcover, etc.)."""
    if layer not in _MAP_LAYER_NAMES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown map layer: {layer}"
        )
    return _generate_raster_map(calculation_id, layer, db, current_user)


@router.post("/calculations/{calculation_id}/add-species")
def add_species_to_calculation(
    calculation_id: UUID,
    request: AddSpeciesRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Add a species to a calculation's species list

    This endpoint allows users to manually add species that may have been missed
    by the automatic analysis or to include species found during field surveys.

    The species will be added to the calculation's result_data.potential_species list
    with the specified role and availability rank.
    """
    # Get existing calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this calculation",
        )

    # Get species details from database
    species_query = text(
        """
        SELECT
            id,
            scientific_name,
            local_name,
            family,
            growth_rate,
            min_altitude_m,
            max_altitude_m,
            economic_value,
            main_uses,
            nitrogen_fixing,
            rarity_status,
            ecological_role
        FROM tree_species_coefficients
        WHERE id = :species_id
    """
    )

    species_result = db.execute(
        species_query, {"species_id": request.species_id}
    ).fetchone()

    if not species_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Species with ID {request.species_id} not found",
        )

    # Create species data object
    new_species = {
        "scientific_name": species_result.scientific_name,
        "local_name": species_result.local_name or "Unknown",
        "role": request.role,
        "availability_rank": request.availability_rank,
        "economic_value": species_result.economic_value or "Medium",
        "growth_rate": species_result.growth_rate,
        "min_altitude_m": species_result.min_altitude_m,
        "max_altitude_m": species_result.max_altitude_m,
        "main_uses": species_result.main_uses,
        "nitrogen_fixing": species_result.nitrogen_fixing or False,
        "rarity_status": species_result.rarity_status or "Common",
        "family": species_result.family,
        "forest_types": ["User Added"],
        "manually_added": True,  # Flag to indicate this was manually added
    }

    # Get current result_data
    result_data = calculation.result_data or {}

    # Initialize potential_species if it doesn't exist
    if "potential_species" not in result_data:
        result_data["potential_species"] = []

    # Check if species already exists
    existing_species = [
        s
        for s in result_data["potential_species"]
        if s.get("scientific_name") == new_species["scientific_name"]
    ]

    if existing_species:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Species {new_species['scientific_name']} already exists in this calculation",
        )

    # Add new species to the list
    result_data["potential_species"].append(new_species)
    result_data["species_count"] = len(result_data["potential_species"])

    # Update calculation
    calculation.result_data = result_data
    flag_modified(calculation, "result_data")  # Mark JSONB column as modified
    db.commit()
    db.refresh(calculation)

    return {
        "success": True,
        "message": f"Successfully added {new_species['scientific_name']} ({new_species['local_name']}) to the species list",
        "species": new_species,
        "total_species": result_data["species_count"],
    }


@router.delete("/calculations/{calculation_id}/remove-species/{scientific_name}")
def remove_species_from_calculation(
    calculation_id: UUID,
    scientific_name: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Remove a species from the calculation's species list.

    This marks the species as removed by the user. It will not appear
    in future queries for this calculation's species list.

    For system-generated species: Adds to removed_species list
    For manually-added species: Removes from potential_species list
    """
    from datetime import datetime, timezone

    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this calculation",
        )

    # Initialize result_data if needed
    if not calculation.result_data:
        calculation.result_data = {}

    result_data = calculation.result_data

    # Initialize removed_species array if needed
    if "removed_species" not in result_data:
        result_data["removed_species"] = []

    # Check if this is a manually added species
    manually_added = False
    if "potential_species" in result_data:
        for species in result_data["potential_species"]:
            if species.get("scientific_name") == scientific_name:
                if species.get("manually_added"):
                    manually_added = True
                break

    if manually_added:
        # Remove manually-added species completely from the list
        result_data["potential_species"] = [
            sp
            for sp in result_data["potential_species"]
            if sp.get("scientific_name") != scientific_name
        ]
        result_data["species_count"] = len(result_data["potential_species"])
        message = f"Manually added species '{scientific_name}' removed completely"
    else:
        # For system-generated species, add to removed list
        if scientific_name not in result_data["removed_species"]:
            result_data["removed_species"].append(scientific_name)
        message = f"System-generated species '{scientific_name}' hidden from list"

    # Mark as modified
    result_data["species_list_modified"] = True
    result_data["species_last_modified"] = datetime.now(timezone.utc).isoformat()

    # Update calculation
    calculation.result_data = result_data
    flag_modified(calculation, "result_data")
    db.commit()
    db.refresh(calculation)

    return {
        "success": True,
        "message": message,
        "removed_species": result_data.get("removed_species", []),
        "manually_added_removed": manually_added,
    }


@router.patch("/calculations/{calculation_id}/species/{scientific_name}/confirm")
def toggle_species_confirmation(
    calculation_id: UUID,
    scientific_name: str,
    request_body: dict,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Toggle species confirmation status.

    Supports block-specific confirmation:
    - If block_name is provided: Only confirms species in that specific block
    - If block_name is None/omitted: Confirms species at whole forest level (not in blocks)

    Confirmed species appear colorful in UI and are included in operational plans.
    Unconfirmed species appear grey and are excluded from final reports.
    """
    from datetime import datetime, timezone

    # Get confirmed value and optional block_name from request body
    confirmed = request_body.get("confirmed", False)
    block_name = request_body.get("block_name", None)  # NEW: Optional block identifier

    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    # Get result_data
    result_data = calculation.result_data or {}

    # NEW: Block-specific confirmation logic
    if block_name is not None:
        # Confirm species in specific block only
        species_found = False
        if "blocks" in result_data:
            for block in result_data["blocks"]:
                if (
                    block.get("block_name") == block_name
                    and "potential_species" in block
                ):
                    for block_species in block["potential_species"]:
                        if block_species.get("scientific_name") == scientific_name:
                            block_species["confirmed"] = confirmed
                            species_found = True
                            break
                    if species_found:
                        break

        if not species_found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Species '{scientific_name}' not found in area '{block_name}'",
            )

        # Mark as modified
        result_data["species_list_modified"] = True
        result_data["species_last_modified"] = datetime.now(timezone.utc).isoformat()

        # Save
        calculation.result_data = result_data
        flag_modified(calculation, "result_data")
        db.commit()
        db.refresh(calculation)

        return {
            "success": True,
            "message": f"Species '{scientific_name}' {'confirmed' if confirmed else 'unconfirmed'} in {block_name}",
            "confirmed": confirmed,
            "block_name": block_name,
            "scope": "block",
        }

    # Original: Whole forest confirmation (does NOT sync to blocks anymore)
    if "potential_species" not in result_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No species data found"
        )

    # Find and update species in whole forest list ONLY
    species_found = False
    for species in result_data["potential_species"]:
        if species.get("scientific_name") == scientific_name:
            species["confirmed"] = confirmed
            species_found = True
            break

    if not species_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Species not found in whole forest list",
        )

    # REMOVED: No longer syncs to blocks automatically
    # Each block maintains independent species confirmations

    # Mark as modified
    result_data["species_list_modified"] = True
    result_data["species_last_modified"] = datetime.now(timezone.utc).isoformat()

    # Save
    calculation.result_data = result_data
    flag_modified(calculation, "result_data")
    db.commit()
    db.refresh(calculation)

    # Count confirmed species (whole forest level)
    removed = result_data.get("removed_species", [])
    confirmed_count = sum(
        1
        for sp in result_data["potential_species"]
        if sp.get("confirmed", False) and sp.get("scientific_name") not in removed
    )

    return {
        "success": True,
        "message": f"Species '{scientific_name}' {'confirmed' if confirmed else 'unconfirmed'} at whole forest level",
        "confirmed": confirmed,
        "confirmed_count": confirmed_count,
        "total_species": len(
            [
                sp
                for sp in result_data["potential_species"]
                if sp.get("scientific_name") not in removed
            ]
        ),
        "scope": "whole_forest",
    }


@router.post("/calculations/{calculation_id}/species/confirm-all")
def confirm_all_species(
    calculation_id: UUID,
    request_body: dict,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Confirm or unconfirm all species at once.
    Useful for 'Confirm All' or 'Clear All' buttons.
    """
    from datetime import datetime, timezone

    # Get confirmed value from request body
    confirmed = request_body.get("confirmed", False)

    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    result_data = calculation.result_data or {}

    if "potential_species" not in result_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No species data found"
        )

    # Update all species in whole forest list
    for species in result_data["potential_species"]:
        species["confirmed"] = confirmed

    # PHASE 1: Sync confirmation to all blocks
    blocks_updated = 0
    if "blocks" in result_data:
        for block in result_data["blocks"]:
            if "potential_species" in block:
                for block_species in block["potential_species"]:
                    block_species["confirmed"] = confirmed
                    blocks_updated += 1

    # Mark as modified
    result_data["species_list_modified"] = True
    result_data["species_last_modified"] = datetime.now(timezone.utc).isoformat()

    # Save
    calculation.result_data = result_data
    flag_modified(calculation, "result_data")
    db.commit()

    removed = result_data.get("removed_species", [])
    affected_count = len(
        [
            sp
            for sp in result_data["potential_species"]
            if sp.get("scientific_name") not in removed
        ]
    )

    return {
        "success": True,
        "message": f"{'Confirmed' if confirmed else 'Unconfirmed'} {affected_count} species",
        "count": affected_count,
    }


@router.get("/calculations/{calculation_id}/species-summary")
def get_species_summary(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get whole forest species summary auto-calculated from block-level confirmations.

    Returns:
    - Total species count
    - Species-by-species statistics (which blocks, coverage %, confirmed count)
    - Role distribution
    - Confirmation statistics
    """

    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    result_data = calculation.result_data or {}
    blocks = result_data.get("blocks", [])
    removed_species = result_data.get("removed_species", [])

    # Build species map from all blocks
    species_map = {}
    total_blocks = len(blocks)

    for block_idx, block in enumerate(blocks):
        block_species_list = block.get("potential_species", [])

        for species in block_species_list:
            scientific_name = species.get("scientific_name")

            # Skip removed species
            if scientific_name in removed_species:
                continue

            if scientific_name not in species_map:
                species_map[scientific_name] = {
                    "scientific_name": scientific_name,
                    "local_name": species.get("local_name"),
                    "family": species.get("family"),
                    "economic_value": species.get("economic_value"),
                    "growth_rate": species.get("growth_rate"),
                    "min_altitude_m": species.get("min_altitude_m"),
                    "max_altitude_m": species.get("max_altitude_m"),
                    "nitrogen_fixing": species.get("nitrogen_fixing"),
                    "blocks": [],
                    "block_indices": [],
                    "roles": set(),
                    "confirmed_in_blocks": 0,
                    "unconfirmed_in_blocks": 0,
                }

            # Track which blocks this species appears in
            block_name = block.get("block_name", f"Block {block_idx + 1}")
            species_map[scientific_name]["blocks"].append(block_name)
            species_map[scientific_name]["block_indices"].append(block_idx)

            # Track roles
            role = species.get("role", "Associate")
            species_map[scientific_name]["roles"].add(role)

            # Track confirmation status per block
            if species.get("confirmed", False):
                species_map[scientific_name]["confirmed_in_blocks"] += 1
            else:
                species_map[scientific_name]["unconfirmed_in_blocks"] += 1

    # Convert to list with calculated statistics
    species_summary = []
    for species_data in species_map.values():
        present_in_blocks = len(species_data["blocks"])
        coverage_percentage = (
            (present_in_blocks / total_blocks * 100) if total_blocks > 0 else 0
        )

        species_summary.append(
            {
                "scientific_name": species_data["scientific_name"],
                "local_name": species_data["local_name"],
                "family": species_data["family"],
                "economic_value": species_data["economic_value"],
                "growth_rate": species_data["growth_rate"],
                "min_altitude_m": species_data["min_altitude_m"],
                "max_altitude_m": species_data["max_altitude_m"],
                "nitrogen_fixing": species_data["nitrogen_fixing"],
                "blocks": species_data["blocks"],
                "block_indices": species_data["block_indices"],
                "present_in_blocks": present_in_blocks,
                "total_blocks": total_blocks,
                "coverage_percentage": round(coverage_percentage, 1),
                "roles": sorted(list(species_data["roles"])),
                "confirmed_in_blocks": species_data["confirmed_in_blocks"],
                "unconfirmed_in_blocks": species_data["unconfirmed_in_blocks"],
                "confirmed": species_data["confirmed_in_blocks"]
                > 0,  # At least one block confirmed
            }
        )

    # Sort by coverage percentage (descending)
    species_summary.sort(key=lambda x: x["coverage_percentage"], reverse=True)

    # Calculate statistics
    total_species = len(species_summary)
    confirmed_species = sum(1 for s in species_summary if s["confirmed"])
    unconfirmed_species = total_species - confirmed_species

    # Role distribution
    role_counts = {}
    for species in species_summary:
        for role in species["roles"]:
            role_counts[role] = role_counts.get(role, 0) + 1

    return {
        "total_species": total_species,
        "confirmed_species": confirmed_species,
        "unconfirmed_species": unconfirmed_species,
        "total_blocks": total_blocks,
        "species_details": species_summary,
        "role_distribution": role_counts,
        "confirmation_stats": {
            "confirmed": confirmed_species,
            "unconfirmed": unconfirmed_species,
            "percentage_confirmed": round(
                (confirmed_species / total_species * 100) if total_species > 0 else 0, 1
            ),
        },
    }


# ============================================================================
# GEOMETRY & SUB-AREA EDITING ENDPOINTS
# ============================================================================


# business: CFMG — geometry must be valid (no self-intersections, non-empty)
@router.patch("/calculations/{calculation_id}/geometry")
async def update_calculation_geometry(
    calculation_id: UUID,
    request: GeometryUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Update the boundary geometry of a calculation.

    This allows users to edit the forest boundary by:
    - Drawing new polygons
    - Modifying existing geometry
    - Uploading corrected boundary files

    Optionally triggers re-analysis after the geometry update.
    """
    from shapely.geometry import shape
    from shapely.validation import make_valid

    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    try:
        # Convert GeoJSON to Shapely geometry
        geom = shape(request.geometry)

        # Make geometry valid (fix self-intersections, etc.)
        if not geom.is_valid:
            geom = make_valid(geom)

        # Ensure it's a polygon/multipolygon
        if geom.geom_type == "LineString":
            geom = geom.buffer(0)
        elif geom.geom_type == "Point":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Geometry must be a polygon or multipolygon",
            )

        # Convert back to GeoJSON and then to WKT for PostGIS
        geom_geojson = mapping(geom)

        # Calculate area and geo-derived properties
        from ..utils.geometry_utils import compute_geometry_properties

        area_sqm = geom.area
        area_hectares = area_sqm / SQM_PER_HA
        geo_props = compute_geometry_properties(geom)

        # Update boundary geometry in database
        update_query = text(
            """
            UPDATE public.calculations
            SET boundary_geom = ST_GeomFromText(:wkt, 4326)
            WHERE id = :calc_id
        """
        )

        db.execute(update_query, {"wkt": geom.wkt, "calc_id": str(calculation_id)})

        # Update result_data with new geometry info
        result_data = calculation.result_data or {}
        result_data["geometry_updated"] = True
        result_data["geometry_update_area_hectares"] = round(area_hectares, 4)
        for k, v in geo_props.items():
            result_data[k] = v
        calculation.result_data = result_data
        flag_modified(calculation, "result_data")

        # A new boundary: every sub-area must lie inside it. The optional
        # re-analysis below rebuilds result_data from this local, so refresh it.
        from app.services.sub_area_reclip_service import reclip_after_boundary_write

        _reclip = reclip_after_boundary_write(db, calculation, geom)
        result_data = calculation.result_data or result_data

        # Update status to indicate geometry was modified
        calculation.status = (
            CalculationStatus.COMPLETED
        )  # Keep completed, but geometry is modified
        db.commit()

        # Optionally run re-analysis
        if request.reanalyze:
            # Set status to processing
            calculation.status = CalculationStatus.PROCESSING
            db.commit()

            # Get existing analysis options
            analysis_options = calculation.analysis_options or {}

            try:
                analysis_results, processing_time = await analyze_forest_boundary(
                    calculation_id, db, options=analysis_options
                )

                # Preserve sub-areas and blocks from original data
                blocks_data = result_data.get("blocks", [])
                sub_areas = result_data.get("sub_areas", [])

                # Merge analysis results
                updated_result_data = {
                    "blocks": blocks_data,
                    "sub_areas": sub_areas,
                    "geometry_updated": True,
                    "geometry_update_area_hectares": round(area_hectares, 4),
                    **analysis_results,
                }

                # Update calculation
                update_result_query = text(
                    """
                    UPDATE public.calculations
                    SET
                        result_data = CAST(:result_data AS jsonb),
                        processing_time_seconds = :processing_time,
                        status = :status,
                        completed_at = NOW()
                    WHERE id = :calc_id
                """
                )

                db.execute(
                    update_result_query,
                    {
                        "result_data": json.dumps(updated_result_data),
                        "processing_time": processing_time,
                        "status": "COMPLETED",
                        "calc_id": str(calculation_id),
                    },
                )

                db.commit()
                logger.info(
                    f"Re-analysis completed after geometry update for calculation {calculation_id}"
                )

            except Exception as e:
                logger.error(f"Re-analysis failed after geometry update: {e}")
                # Still return success, but include warning
                calculation = (
                    db.query(Calculation)
                    .filter(Calculation.id == calculation_id)
                    .first()
                )
                calculation.status = CalculationStatus.COMPLETED
                db.commit()

        # Get updated geometry as GeoJSON
        geojson_query = (
            db.query(func.ST_AsGeoJSON(Calculation.boundary_geom).label("geojson"))
            .filter(Calculation.id == calculation_id)
            .first()
        )

        geometry_json = (
            json.loads(geojson_query.geojson)
            if geojson_query and geojson_query.geojson
            else None
        )

        return {
            "success": True,
            **i18n_success(
                "success.geometry_updated_reanalyzed"
                if request.reanalyze
                else "success.geometry_updated"
            ),
            "calculation_id": str(calculation_id),
            "area_hectares": round(area_hectares, 4),
            "sub_areas_clipped": _reclip["clipped"],
            "sub_areas_dropped": _reclip["dropped"],
            "geometry": geometry_json,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update geometry: {str(e)}",
        )


# business: CFMG — sub-areas categorize land use: protected, plantation, pro-poor, religious, biodiversity, tourist, office, private_land
# NOTE: excluded sub-areas (private land) subtracted from block effective area; cross-block sub-areas use blockBreakdown
@router.post("/calculations/{calculation_id}/sub-areas", response_model=SubAreaResponse)
def add_sub_area(
    calculation_id: UUID,
    request: SubAreaCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Add a sub-area to an existing calculation.

    Sub-areas are special zones within the forest boundary:
    - Protected Zone (protected)
    - Plantation Area (plantation)
    - Pro-Poor Income Generation (pro-poor)
    - Religious Area (religious)
    - Bio-diversity Rich (biodiversity)
    - Tourist Attraction (tourist)
    - Office Area (office)
    - Private Land (Excluded) (private_land)

    Private land is excluded from forest area calculations.
    """
    from datetime import datetime, timezone
    from shapely.geometry import shape
    from shapely.validation import make_valid
    import uuid

    # Debug logging
    logger.info(f"\n[add_sub_area] Received request:")
    logger.info(f"  name: {request.name}")
    logger.info(f"  category: {request.category}")
    logger.info(f"  block_id: {request.block_id}")
    logger.info(f"  block_name: {request.block_name}")
    logger.info(f"  block_breakdown: {request.block_breakdown}")
    logger.info(f"  is_excluded: {request.is_excluded}")
    logger.info(f"  area_hectares: {request.area_hectares}")
    if request.block_breakdown:
        logger.info(f"  block_breakdown items: {len(request.block_breakdown)}")
        for item in request.block_breakdown:
            logger.info(
                f"    - blockId: {item.blockId}, blockName: {item.blockName}, area: {item.area}, percentage: {item.percentage}"
            )

    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    # Validate category
    from app.schemas.forest import SubAreaCategory

    valid_categories = SubAreaCategory.valid_categories()
    if request.category not in valid_categories:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}",
        )

    try:
        # Convert GeoJSON to Shapely geometry
        geom = shape(request.geometry)
        logger.info(f"[add_sub_area] Input geometry type: {geom.geom_type}")
        logger.info(f"[add_sub_area] Input geometry area: {geom.area}")

        # Make geometry valid
        if not geom.is_valid:
            geom = make_valid(geom)

        # Ensure it's a polygon
        if geom.geom_type == "MultiPolygon":
            geom = geom.buffer(0)
        elif geom.geom_type not in ["Polygon", "MultiPolygon"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Geometry must be a polygon or multipolygon",
            )

        # Placement rules (inside the forest, never overlapping another sub-area)
        # live in ONE place: place_sub_area_geometry. It clips to the boundary --
        # or to the blocks until there is one -- and verifies the result. With no
        # forest at all it keeps sub-areas disjoint and marks this one pending,
        # so it is clipped the moment a boundary goes live.
        submitted_area = geom.area
        try:
            geom, pending_boundary_clip = place_sub_area_geometry(db, calculation, geom)
        except SubAreaPlacementError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=PLACEMENT_MESSAGES[exc.reason],
            )
        geometry_changed = abs(geom.area - submitted_area) > 1e-12

        # Calculate area (after clipping) using accurate geodesic calculation
        # Import the helper functions
        from ..utils.geometry_utils import (
            calculate_area_geodesic_from_shapely,
            compute_geometry_properties,
        )

        # Use provided area if available (from frontend calculation which may use turf.js)
        if request.area_hectares and request.area_hectares > 0 and not geometry_changed:
            area_hectares = request.area_hectares
            area_sqm = area_hectares * SQM_PER_HA
            logger.info(
                f"[add_sub_area] Using PROVIDED area: {area_hectares} ha (from request)"
            )
        else:
            # Calculate using UTM projection for accuracy
            area_sqm, area_hectares = calculate_area_geodesic_from_shapely(geom)
            logger.info(
                f"[add_sub_area] Using CALCULATED geodesic area: {area_hectares} ha"
            )

        # Compute geometry-derived properties (single source of truth)
        geo_props = compute_geometry_properties(geom)

        # Generate unique ID
        sub_area_id = str(uuid.uuid4())

        # Calculate block breakdown from geometry (handles cross-block sub-areas)
        blocks_for_breakdown = (calculation.result_data or {}).get("blocks", [])
        if request.block_breakdown:
            block_breakdown = [item.model_dump() for item in request.block_breakdown]
        else:
            block_breakdown = calculate_block_breakdown(
                mapping(geom), blocks_for_breakdown
            )

        # Create sub-area object. Exclusion derives from category (D2c):
        # private_land is excluded; all other categories remain part of forest.
        _is_excluded = request.category == "private_land"
        new_sub_area = {
            "id": sub_area_id,
            "name": request.name,
            "category": request.category,
            "geometry": mapping(geom),
            "area_sqm": round(area_sqm, 4),
            "area_hectares": round(area_hectares, 4),
            "blockId": request.block_id,
            "blockName": request.block_name,
            "blockBreakdown": block_breakdown,
            "isExcluded": _is_excluded,
            "is_excluded": _is_excluded,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **geo_props,
        }

        if pending_boundary_clip:
            # No forest yet: this sub-area is clipped to the boundary the moment
            # one goes live (persist_boundary -> reclip_sub_areas_to_boundary).
            new_sub_area["pending_boundary_clip"] = True

        # Update primary block assignment if blockBreakdown is available
        if block_breakdown and not request.block_id:
            primary = max(block_breakdown, key=lambda x: x.get("area", 0))
            new_sub_area["blockId"] = primary.get("blockId")
            new_sub_area["blockName"] = primary.get("blockName")

        # Get or initialize result_data
        result_data = calculation.result_data or {}

        # Initialize sub_areas array if needed
        if "sub_areas" not in result_data:
            result_data["sub_areas"] = []

        # Add new sub-area
        result_data["sub_areas"].append(new_sub_area)
        result_data["sub_areas_count"] = len(result_data["sub_areas"])

        logger.info(
            f"[add_sub_area] Added sub-area {sub_area_id}, total now: {len(result_data['sub_areas'])}"
        )

        # Update calculation
        calculation.result_data = result_data
        flag_modified(calculation, "result_data")
        # Per-unit excluded/effective area, for whichever array (blocks or compartments) this
        # forest actually uses (FS-1b.5/1b.6 - was three copies of this calc, "blocks" only).
        from ..services.forest_units.write import recompute_sub_area_breakdown

        recompute_sub_area_breakdown(db, calculation)
        db.commit()
        _invalidate_layers(calculation.id)
        db.refresh(calculation)

        logger.info(
            f"[add_sub_area] Updated totals - excluded: {calculation.result_data.get('excluded_area_hectares', 0):.4f} ha, effective: {calculation.result_data.get('effective_area_hectares', 0):.4f} ha"
        )

        return SubAreaResponse(
            id=sub_area_id,
            name=request.name,
            category=request.category,
            geometry=mapping(geom),
            area_hectares=round(area_hectares, 4),
            block_id=(
                new_sub_area.get("blockId")
                if not request.block_id
                else request.block_id
            ),
            block_name=(
                new_sub_area.get("blockName")
                if not request.block_name
                else request.block_name
            ),
            block_breakdown=(
                [BlockBreakdownItem(**item) for item in block_breakdown]
                if block_breakdown
                else None
            ),
            is_excluded=request.is_excluded,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        db.rollback()
        logger.error(f"[add_sub_area] ERROR: {str(e)}")
        logger.error(f"[add_sub_area] Traceback:\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to add sub-area: {str(e)}",
        )


@router.get("/sub-area-categories", response_model=List[SubAreaCategoryItem])
def list_sub_area_categories(
    current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)
):
    """
    Sub-area category catalogue (single source of truth for category dropdowns).

    Returns the official 13-value list (List A) with EN/NP labels, color and
    is_excluded. Consumed by MapWorkspace so the frontend cannot drift from
    the backend enum SubAreaCategory.
    """
    from app.schemas.forest import SubAreaCategory

    return SubAreaCategory.catalog()


@router.get(
    "/calculations/{calculation_id}/sub-areas", response_model=SubAreaListResponse
)
def list_sub_areas(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get all sub-areas for a calculation.
    """
    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    # Get sub-areas from result_data
    result_data = calculation.result_data or {}
    sub_areas = result_data.get("sub_areas", [])

    logger.info(
        f"[list_sub_areas] Calculation {calculation_id}: found {len(sub_areas)} sub-areas in result_data"
    )
    if sub_areas:
        logger.info(f"[list_sub_areas] First sub-area keys: {sub_areas[0].keys()}")
        logger.info(
            f"[list_sub_areas] First sub-area area_hectares: {sub_areas[0].get('area_hectares')}"
        )
        logger.info(f"[list_sub_areas] First sub-area full: {sub_areas[0]}")

    # Convert to response format
    sub_area_responses = []
    total_area = 0

    for sa in sub_areas:
        # Convert geometry to GeoJSON if it's stored as Shapely mapping
        geom = sa.get("geometry")
        geometry_json = {}
        sa_area = sa.get("area_hectares", 0)

        if geom:
            from shapely.geometry import mapping as shapely_mapping
            from shapely.wkb import loads as load_wkb

            # Check if it's WKB (bytes) or already GeoJSON
            if isinstance(geom, bytes):
                try:
                    shapely_geom = load_wkb(geom)
                    geometry_json = shapely_mapping(shapely_geom)
                except Exception:
                    logger.exception(
                        "stored geometry unreadable - the feature is returned with an "
                        "empty shape rather than an error"
                    )
                    geometry_json = {}
            elif isinstance(geom, dict):
                geometry_json = geom
            else:
                geometry_json = {}

            # If area is 0 or very small, recalculate from geometry
            if sa_area < 0.001 and geometry_json:
                try:
                    from shapely.geometry import shape
                    from shapely.ops import transform
                    import pyproj

                    # Get geometry and calculate centroid for UTM zone
                    geom_obj = shape(geometry_json)
                    if not geom_obj.is_empty:
                        centroid = geom_obj.centroid
                        utm_srid = calculate_utm_epsg(centroid.x, centroid.y)

                        # Project to UTM and calculate area
                        project = pyproj.Transformer.from_crs(
                            "EPSG:4326", f"EPSG:{utm_srid}", always_xy=True
                        ).transform
                        geom_utm = transform(project, geom_obj)
                        sa_area = geom_utm.area / SQM_PER_HA
                        logger.info(
                            f"[list_sub_areas] Recalculated area for {sa.get('name')}: {sa_area:.4f} ha"
                        )
                except Exception as e:
                    logger.error(f"[list_sub_areas] Error recalculating area: {e}")

        # Get blockBreakdown if exists
        block_breakdown = sa.get("blockBreakdown")
        block_breakdown_items = None
        if block_breakdown:
            from ..schemas.forest import BlockBreakdownItem

            block_breakdown_items = [
                BlockBreakdownItem(**item) if isinstance(item, dict) else item
                for item in block_breakdown
            ]

        sub_area_responses.append(
            SubAreaResponse(
                id=sa.get("id", ""),
                name=sa.get("name", ""),
                category=sa.get("category", ""),
                geometry=geometry_json,
                area_hectares=round(sa_area, 4),
                block_id=sa.get("blockId"),
                block_name=sa.get("blockName"),
                block_breakdown=block_breakdown_items,
                is_excluded=sa.get("isExcluded", False),
            )
        )
        total_area += sa_area

    return SubAreaListResponse(
        sub_areas=sub_area_responses,
        total_count=len(sub_area_responses),
        total_area_hectares=round(total_area, 4),
    )


# NOTE: sub-area area recalculated from geometry using geodesic UTM projection; clipped against other sub-areas to prevent overlap
@router.patch("/calculations/{calculation_id}/sub-areas/{sub_area_id}")
def update_sub_area(
    calculation_id: UUID,
    sub_area_id: str,
    request: SubAreaUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Update a sub-area's properties (name, category, geometry, etc.)

    Phase E-1 single-authority (review-fix #8): `geometry` is rejected with a
    400 — geometry edits must route through
    POST /calculations/{id}/geometry/edit-geometry so the validated pipeline
    (clip R1 / overlap / shared-edge R6) is never bypassed.
    """
    from datetime import datetime, timezone

    if request.geometry is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use POST /calculations/{id}/geometry/edit-geometry for geometry edits — "
            "this endpoint is attribute-only (Phase E-1 single-authority).",
        )

    # Log incoming request for debugging
    logger.info(
        f"[update_sub_area] calculation_id={calculation_id}, sub_area_id={sub_area_id}"
    )
    logger.info(f"[update_sub_area] request.name={request.name}")
    logger.info(
        f"[update_sub_area] request.geometry is not None: {request.geometry is not None}"
    )
    if request.geometry:
        logger.info(
            f"[update_sub_area] request.geometry type: {request.geometry.get('type')}"
        )
        logger.info(
            f"[update_sub_area] request.geometry: {str(request.geometry)[:500]}"
        )

    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    # Get sub-areas from result_data
    result_data = calculation.result_data or {}
    sub_areas = result_data.get("sub_areas", [])

    # Debug: print all sub-area IDs for comparison
    logger.info(f"[update_sub_area] Looking for sub_area_id: '{sub_area_id}'")
    logger.info(
        f"[update_sub_area] Available sub-area IDs: {[sa.get('id') for sa in sub_areas]}"
    )

    # Find the sub-area
    sub_area_found = False
    for i, sa in enumerate(sub_areas):
        sa_id = sa.get("id")
        logger.info(
            f"[update_sub_area] Comparing: '{sa_id}' == '{sub_area_id}' -> {sa_id == sub_area_id}"
        )
        if sa_id == sub_area_id:
            sub_area_found = True

            # Update fields
            if request.name is not None:
                sub_areas[i]["name"] = request.name
            if request.category is not None:
                from app.schemas.forest import SubAreaCategory

                valid_categories = SubAreaCategory.valid_categories()
                if request.category not in valid_categories:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}",
                    )
                sub_areas[i]["category"] = request.category
                # Exclusion derives from category (D2c): private_land is excluded.
                sub_areas[i]["isExcluded"] = request.category == "private_land"
                sub_areas[i]["is_excluded"] = sub_areas[i]["isExcluded"]
            if request.block_id is not None:
                sub_areas[i]["blockId"] = request.block_id
            if request.block_name is not None:
                sub_areas[i]["blockName"] = request.block_name
            if request.is_excluded is not None:
                sub_areas[i]["isExcluded"] = request.is_excluded
            if request.geometry is not None:
                try:
                    # Validate geometry
                    if not isinstance(request.geometry, dict):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Geometry must be a valid GeoJSON object",
                        )
                    if request.geometry.get("type") not in ["Polygon", "MultiPolygon"]:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Geometry type must be Polygon or MultiPolygon",
                        )

                    # Clip against other sub-areas to prevent overlap
                    from shapely.geometry import shape as _shape, mapping as _mapping
                    from shapely.ops import unary_union

                    geom_shape = _shape(request.geometry)
                    other_sub_areas = [sa for j, sa in enumerate(sub_areas) if j != i]
                    other_shapes = []
                    for sa in other_sub_areas:
                        sa_geom = sa.get("geometry")
                        if sa_geom:
                            other_shapes.append(_shape(sa_geom))
                    if other_shapes:
                        other_union = unary_union(other_shapes)
                        clipped_shape = geom_shape.difference(other_union)
                        if clipped_shape.is_empty:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Updated sub-area geometry is entirely within other sub-areas",
                            )
                        geom_shape = clipped_shape
                    sub_area_geojson = _mapping(geom_shape)

                    # Update geometry
                    sub_areas[i]["geometry"] = sub_area_geojson
                    logger.info(
                        f"[update_sub_area] Stored geometry in sub_areas[{i}]: {str(sub_area_geojson)[:200]}"
                    )

                    # Always recalculate area and geo properties from the new geometry (server is authoritative)
                    try:
                        from ..utils.geometry_utils import (
                            calculate_area_geodesic_from_shapely,
                            compute_geometry_properties,
                        )

                        area_sqm, area_ha = calculate_area_geodesic_from_shapely(
                            geom_shape
                        )
                        logger.info(
                            f"[update_sub_area] Recalculated area: {area_sqm:.4f} sqm, {area_ha:.4f} ha"
                        )
                    except Exception as e2:
                        import traceback

                        logger.error(f"[update_sub_area] Area calculation error: {e2}")
                        traceback.print_exc()
                        logger.warning(f"Failed to recalculate area for sub-area: {e2}")
                        # Rough deg² → ha conversion at Nepal's latitude (~28°N)
                        import math as _math

                        _clat = _math.cos(_math.radians(geom_shape.centroid.y))
                        area_ha = (
                            abs(geom_shape.area)
                            * METERS_PER_DEGREE_LAT
                            * METERS_PER_DEGREE_LAT
                            * _clat
                            / SQM_PER_HA
                        )
                        area_sqm = area_ha * SQM_PER_HA

                    sub_areas[i]["area_sqm"] = round(area_sqm, 4)
                    sub_areas[i]["area_hectares"] = round(area_ha, 4)

                    # Compute geometry-derived properties (authoritative)
                    geo_props = compute_geometry_properties(geom_shape)
                    for k, v in geo_props.items():
                        sub_areas[i][k] = v

                    # Recalculate block breakdown for new geometry
                    blocks = result_data.get("blocks", [])
                    block_breakdown = calculate_block_breakdown(
                        sub_area_geojson, blocks
                    )
                    if block_breakdown:
                        sub_areas[i]["blockBreakdown"] = block_breakdown
                        # Update primary block assignment based on largest coverage
                        if block_breakdown:
                            primary = max(
                                block_breakdown, key=lambda x: x.get("area", 0)
                            )
                            sub_areas[i]["blockId"] = primary.get("blockId")
                            sub_areas[i]["blockName"] = primary.get("blockName")

                except Exception as e:
                    # If area calculation fails, log but continue
                    import traceback

                    logger.error(f"[update_sub_area] Error in area calculation: {e}")
                    traceback.print_exc()
                    logger.warning(f"Failed to recalculate area for sub-area: {e}")

            sub_areas[i]["updated_at"] = datetime.now(timezone.utc).isoformat()
            break

    if not sub_area_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sub-area with ID {sub_area_id} not found",
        )

    # Save updated result_data
    result_data["sub_areas"] = sub_areas
    calculation.result_data = result_data
    flag_modified(calculation, "result_data")
    # Per-unit excluded/effective area, whichever array this forest uses (FS-1b.5/1b.6).
    from ..services.forest_units.write import recompute_sub_area_breakdown

    recompute_sub_area_breakdown(db, calculation)
    db.commit()
    _invalidate_layers(calculation.id)
    db.refresh(calculation)

    # Verify saved data
    saved_result_data = calculation.result_data
    saved_sub_areas = saved_result_data.get("sub_areas", [])
    saved_sub_area = next(
        (sa for sa in saved_sub_areas if sa.get("id") == sub_area_id), None
    )
    if saved_sub_area:
        logger.info(
            f"[update_sub_area] VERIFIED - saved geometry type: {saved_sub_area.get('geometry', {}).get('type')}"
        )
        logger.info(
            f"[update_sub_area] VERIFIED - saved geometry coords exist: {'coordinates' in saved_sub_area.get('geometry', {})}"
        )
        logger.info(
            f"[update_sub_area] VERIFIED - saved area_hectares: {saved_sub_area.get('area_hectares')}"
        )
    else:
        logger.error(f"[update_sub_area] ERROR - sub_area not found after save!")

    return {
        "success": True,
        **i18n_success("success.sub_area_updated"),
        "sub_area": sub_areas[
            [i for i, sa in enumerate(sub_areas) if sa.get("id") == sub_area_id][0]
        ],
    }


# NOTE: also deletes from forest_sub_areas table (dual storage — result_data JSONB + relational FK)
@router.delete("/calculations/{calculation_id}/sub-areas/{sub_area_id}")
def delete_sub_area(
    calculation_id: UUID,
    sub_area_id: str,
    plan_lines: Optional[str] = Query(
        None, description="What happens to the yearly-plan lines tied to it: 'delete' or 'keep' (required when there are any)"
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Delete a sub-area from a calculation.
    """
    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    # Get sub-areas from result_data
    result_data = calculation.result_data or {}
    sub_areas = result_data.get("sub_areas", [])

    # Find and remove the sub-area
    sub_area_found = False
    deleted_area = 0
    new_sub_areas = []

    removed_sa = None
    for sa in sub_areas:
        if sa.get("id") == sub_area_id:
            sub_area_found = True
            deleted_area = sa.get("area_hectares", 0)
            removed_sa = sa
        else:
            new_sub_areas.append(sa)

    if not sub_area_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sub-area with ID {sub_area_id} not found",
        )

    # A sub-area is tied to the yearly plan: never remove it silently from under its plan lines (409 until the user chooses).
    from ..services import sub_area_plan as _sap

    _sap.assert_choice_made(db, calculation.id, [sub_area_id], plan_lines)
    _sap.release_sub_areas(db, calculation.id, [sub_area_id], plan_lines or "delete")

    # Save updated result_data
    result_data["sub_areas"] = new_sub_areas
    result_data["sub_areas_count"] = len(new_sub_areas)
    if removed_sa and removed_sa.get("category") == "fire_line" and removed_sa.get("origin") == "auto" and removed_sa.get("unit_key"):
        # deleting a generated fire line = deciding it is not one: remember it, or the next regenerate would put it back
        from ..services.fire_line_service import with_decision

        result_data = with_decision(result_data, removed_sa["unit_key"], included=False)

    # ALSO delete from forest_sub_areas table (source of truth)
    from app.models.forest_sub_area import ForestSubArea

    try:
        sub_area_to_delete = (
            db.query(ForestSubArea).filter(ForestSubArea.id == sub_area_id).first()
        )
        if sub_area_to_delete:
            db.delete(sub_area_to_delete)
            logger.info(f"[delete_sub_area] Also deleted from forest_sub_areas table")
    except Exception as e:
        logger.warning(
            f"[delete_sub_area] Warning: Could not delete from forest_sub_areas table: {e}"
        )

    calculation.result_data = result_data
    flag_modified(calculation, "result_data")
    # Per-unit excluded/effective area, whichever array this forest uses (FS-1b.5/1b.6).
    from ..services.forest_units.write import recompute_sub_area_breakdown

    recompute_sub_area_breakdown(db, calculation)
    db.commit()
    _invalidate_layers(calculation.id)
    db.refresh(calculation)

    logger.info(
        f"[delete_sub_area] Deleted sub-area, new excluded total: {calculation.result_data.get('excluded_area_hectares', 0):.4f} ha, effective: {calculation.result_data.get('effective_area_hectares', 0):.4f} ha"
    )

    return {
        "success": True,
        "message": f"Sub-area deleted successfully. Removed {round(deleted_area, 4)} hectares.",
    }


# ---------------------------------------------------------------------------
# Forest boundary pieces (BOUNDARY_PIECES_PLAN.md P3) — list + rename only.
# Geometry/create/delete are not exposed here: a piece's geometry is a
# byproduct of a boundary write, kept in sync automatically by
# `boundary_pieces_service.sync_boundary_pieces` (D7: piece-level
# reshape/delete is deferred to a later phase).
# ---------------------------------------------------------------------------
@router.get(
    "/calculations/{calculation_id}/boundary-pieces",
    response_model=BoundaryPieceListResponse,
)
def list_boundary_pieces(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List the forest boundary's individual pieces (one row per disjoint
    parcel — most forests have exactly one)."""
    from geoalchemy2.shape import to_shape as _bp_to_shape
    from app.models.forest_boundary_piece import ForestBoundaryPiece

    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND)
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    rows = (
        db.query(ForestBoundaryPiece)
        .filter(ForestBoundaryPiece.calculation_id == calculation_id)
        .order_by(ForestBoundaryPiece.created_at)
        .all()
    )
    pieces = [
        BoundaryPieceResponse(
            id=str(row.id),
            name=row.name,
            geometry=mapping(_bp_to_shape(row.geometry)),
            area_hectares=round(row.area_hectares, 4),
        )
        for row in rows
    ]
    return BoundaryPieceListResponse(
        pieces=pieces,
        total_count=len(pieces),
        total_area_hectares=round(sum(p.area_hectares for p in pieces), 4),
    )


@router.patch(
    "/calculations/{calculation_id}/boundary-pieces/{piece_id}",
    response_model=BoundaryPieceResponse,
)
def rename_boundary_piece(
    calculation_id: UUID,
    piece_id: UUID,
    request: BoundaryPieceUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Rename one boundary piece. Not gated on `structure_locked` — this is a
    pure attribute edit, same rationale as renaming a block/sub-area name
    without touching geometry; it never invalidates anything downstream."""
    from geoalchemy2.shape import to_shape as _bp_to_shape
    from app.models.forest_boundary_piece import ForestBoundaryPiece

    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND)
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    row = (
        db.query(ForestBoundaryPiece)
        .filter(
            ForestBoundaryPiece.id == piece_id,
            ForestBoundaryPiece.calculation_id == calculation_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Boundary piece not found")

    row.name = request.name
    db.commit()
    db.refresh(row)

    return BoundaryPieceResponse(
        id=str(row.id),
        name=row.name,
        geometry=mapping(_bp_to_shape(row.geometry)),
        area_hectares=round(row.area_hectares, 4),
    )


@router.delete("/calculations/{calculation_id}/sub-areas")
def clear_all_sub_areas(
    calculation_id: UUID,
    plan_lines: Optional[str] = Query(
        None, description="What happens to the yearly-plan lines tied to them: 'delete' or 'keep' (required when there are any)"
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Delete ALL sub-areas from a calculation (context menu "Delete Sub-Areas Data").

    Clears result_data["sub_areas"] and recomputes excluded/effective areas,
    mirroring the per-item delete logic in delete_sub_area.
    """
    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    result_data = calculation.result_data or {}
    from ..core.sub_area_kinds import real_sub_areas, is_strip

    # "Delete sub-areas data" clears everything on the layer, the fire lines and river banks included (owner, 2026-10-20: it used to
    # say "deleted" and leave them). A generated strip is removed as a decision, so the next regenerate does not bring it back.
    strips = [sa for sa in (result_data.get("sub_areas") or []) if is_strip(sa)]
    sub_areas = real_sub_areas(result_data.get("sub_areas", []))
    removed_count = len(sub_areas) + len(strips)

    if removed_count == 0:
        return {
            "success": True,
            **i18n_success("success.no_sub_areas_to_delete"),
            "deleted_count": 0,
        }

    from ..services import sub_area_plan as _sap

    _all_ids = [sa.get("id") for sa in sub_areas + strips if sa.get("id")]
    _sap.assert_choice_made(db, calculation.id, _all_ids, plan_lines)
    _sap.release_sub_areas(db, calculation.id, _all_ids, plan_lines or "delete")

    from ..services.fire_line_service import FIRE_KIND, RIVER_KIND, with_decision

    for sa in strips:
        if sa.get("origin") == "auto" and sa.get("unit_key"):
            kind = RIVER_KIND if sa.get("category") == "river_bank" else FIRE_KIND
            result_data = with_decision(result_data, sa["unit_key"], included=False, decisions_key=kind.decisions_key)
    result_data["sub_areas"] = []
    result_data["sub_areas_count"] = 0

    # ALSO delete all from forest_sub_areas table (source of truth)
    from app.models.forest_sub_area import ForestSubArea

    try:
        sub_area_ids = [sa.get("id") for sa in sub_areas + strips if sa.get("id")]
        if sub_area_ids:
            deleted_table_rows = (
                db.query(ForestSubArea)
                .filter(ForestSubArea.id.in_(sub_area_ids))
                .delete(synchronize_session=False)
            )
            logger.info(
                f"[clear_all_sub_areas] Deleted {deleted_table_rows} rows from forest_sub_areas table"
            )
    except Exception as e:
        logger.warning(
            f"[clear_all_sub_areas] Warning: Could not delete from forest_sub_areas table: {e}"
        )

    calculation.result_data = result_data
    flag_modified(calculation, "result_data")
    # Per-unit excluded/effective area, whichever array this forest uses (FS-1b.5/1b.6). sub_areas is now
    # [] (not absent), so this still resets every unit's excluded/effective area to 0/full.
    from ..services.forest_units.write import recompute_sub_area_breakdown

    recompute_sub_area_breakdown(db, calculation)
    db.commit()
    _invalidate_layers(calculation.id)
    db.refresh(calculation)

    logger.info(
        f"[clear_all_sub_areas] Cleared {removed_count} sub-areas, excluded reset to 0, effective: {calculation.result_data.get('effective_area_hectares', 0):.4f} ha"
    )

    return {
        "success": True,
        "message": f"Deleted all {removed_count} sub-areas.",
        "deleted_count": removed_count,
    }


# business: PROTECTION_WORKING_CIRCLE_PLAN.md P3 — a protected sub-area can be
# promoted to a first-class protection working-circle unit (numbered P-N),
# carved out of whatever production compartment(s) it overlapped, and demoted
# back. Both are structure-lock guarded and geometry-versioned.
@router.post("/calculations/{calculation_id}/sub-areas/{sub_area_id}/promote-to-unit")
def promote_sub_area_to_unit(
    calculation_id: UUID,
    sub_area_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    from app.services.protection_unit_service import promote_subarea_to_unit

    try:
        result = promote_subarea_to_unit(db, calculation, sub_area_id)
        # it is a unit now, not a sub-area: its plan lines stay in the plan as forest-wide lines
        from ..services import sub_area_plan as _sap

        _sap.release_sub_areas(db, calculation.id, [sub_area_id], "keep")
    except ValueError as e:
        code = str(e).split(":", 1)[0]
        st = (
            status.HTTP_423_LOCKED
            if code == "STRUCTURE_LOCKED"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=st, detail={"code": code, "message": str(e)})
    db.commit()
    return {"success": True, **result}


@router.post(
    "/calculations/{calculation_id}/protection-units/{block_id}/demote-to-subarea"
)
def demote_protection_unit(
    calculation_id: UUID,
    block_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    from app.services.protection_unit_service import demote_unit_to_subarea

    try:
        result = demote_unit_to_subarea(db, calculation, str(block_id))
    except ValueError as e:
        code = str(e).split(":", 1)[0]
        st = (
            status.HTTP_423_LOCKED
            if code == "STRUCTURE_LOCKED"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=st, detail={"code": code, "message": str(e)})
    db.commit()
    return {"success": True, **result}


# why: interactive editing uses shapely operations (union/difference) directly without PostGIS round-trip for immediate feedback
@router.post("/calculations/{calculation_id}/edit-boundary")
async def edit_boundary_interactive(
    calculation_id: UUID,
    request: dict,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Interactive boundary editing endpoint.

    Accepts operations to modify the boundary geometry:
    - add_polygon: Add a new polygon to the boundary
    - remove_polygon: Remove a polygon from the boundary
    - merge_polygons: Merge multiple polygons into one
    - split_polygon: Split a polygon by a line

    Request format:
    {
        "operation": "add_polygon|remove_polygon|merge|split",
        "features": [...],  // GeoJSON features to add/modify
        "target_index": 0,  // Index of polygon to modify (for remove/merge/split)
        "reanalyze": true   // Whether to re-run analysis
    }
    """
    from shapely.geometry import shape, mapping, MultiPolygon, Polygon
    from shapely.ops import unary_union

    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    operation = request.get("operation", "add_polygon")
    features = request.get("features", [])
    reanalyze = request.get("reanalyze", True)

    try:
        # Get current boundary geometry
        if calculation.boundary_geom:
            geom_wkb = db.execute(
                text("SELECT ST_AsEWKB(:geom) as geom"),
                {"geom": calculation.boundary_geom},
            ).scalar()
            if geom_wkb:
                current_geom = wkb.loads(bytes(geom_wkb))
            else:
                current_geom = None
        else:
            current_geom = None

        if current_geom is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No boundary geometry found for this calculation",
            )

        # Process based on operation
        if operation == "add_polygon":
            # Add new polygon(s) to the boundary
            new_geoms = []
            for feature in features:
                if "geometry" in feature:
                    geom = shape(feature["geometry"])
                    new_geoms.append(geom)

            if new_geoms:
                if current_geom.geom_type == "MultiPolygon":
                    new_polygons = list(current_geom.geoms) + new_geoms
                    current_geom = MultiPolygon(new_polygons)
                else:
                    new_polygons = [current_geom] + new_geoms
                    current_geom = MultiPolygon(new_polygons)

        elif operation == "remove_polygon":
            target_index = request.get("target_index", 0)
            if current_geom.geom_type == "MultiPolygon":
                polygons = list(current_geom.geoms)
                if 0 <= target_index < len(polygons):
                    polygons.pop(target_index)
                    if len(polygons) == 1:
                        current_geom = polygons[0]
                    else:
                        current_geom = MultiPolygon(polygons)
            elif target_index == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot remove single polygon - use update_geometry instead",
                )

        elif operation == "merge":
            # Merge all polygons into one
            if current_geom.geom_type == "MultiPolygon":
                current_geom = unary_union(current_geom)

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown operation: {operation}",
            )

        # Make geometry valid
        if not current_geom.is_valid:
            current_geom = current_geom.buffer(0)

        # Calculate new area
        area_sqm = current_geom.area
        area_hectares = area_sqm / SQM_PER_HA

        # Update boundary geometry in database
        update_query = text(
            """
            UPDATE public.calculations
            SET boundary_geom = ST_GeomFromText(:wkt, 4326)
            WHERE id = :calc_id
        """
        )

        db.execute(
            update_query, {"wkt": current_geom.wkt, "calc_id": str(calculation_id)}
        )

        # Update result_data
        result_data = calculation.result_data or {}
        result_data["boundary_edited"] = True
        result_data["boundary_edit_operation"] = operation
        result_data["new_area_hectares"] = round(area_hectares, 4)
        calculation.result_data = result_data
        flag_modified(calculation, "result_data")

        # The boundary just changed: sub-areas must still lie inside it. The optional
        # re-analysis below rebuilds result_data from this local, so refresh it.
        from app.services.sub_area_reclip_service import reclip_after_boundary_write

        _reclip = reclip_after_boundary_write(db, calculation, current_geom)
        result_data = calculation.result_data or result_data

        db.commit()

        # Optionally run re-analysis
        if reanalyze:
            calculation = (
                db.query(Calculation).filter(Calculation.id == calculation_id).first()
            )
            calculation.status = CalculationStatus.PROCESSING
            db.commit()

            analysis_options = calculation.analysis_options or {}

            try:
                analysis_results, processing_time = await analyze_forest_boundary(
                    calculation_id, db, options=analysis_options
                )

                # Preserve blocks and sub-areas
                blocks_data = result_data.get("blocks", [])
                sub_areas = result_data.get("sub_areas", [])

                updated_result_data = {
                    "blocks": blocks_data,
                    "sub_areas": sub_areas,
                    "boundary_edited": True,
                    "boundary_edit_operation": operation,
                    "new_area_hectares": round(area_hectares, 4),
                    **analysis_results,
                }

                update_result_query = text(
                    """
                    UPDATE public.calculations
                    SET
                        result_data = CAST(:result_data AS jsonb),
                        processing_time_seconds = :processing_time,
                        status = :status,
                        completed_at = NOW()
                    WHERE id = :calc_id
                """
                )

                db.execute(
                    update_result_query,
                    {
                        "result_data": json.dumps(updated_result_data),
                        "processing_time": processing_time,
                        "status": "COMPLETED",
                        "calc_id": str(calculation_id),
                    },
                )

                db.commit()
            except Exception as e:
                logger.error(f"Re-analysis failed after boundary edit: {e}")
                calculation = (
                    db.query(Calculation)
                    .filter(Calculation.id == calculation_id)
                    .first()
                )
                calculation.status = CalculationStatus.COMPLETED
                db.commit()

        # Get updated geometry
        geojson_query = (
            db.query(func.ST_AsGeoJSON(Calculation.boundary_geom).label("geojson"))
            .filter(Calculation.id == calculation_id)
            .first()
        )

        geometry_json = (
            json.loads(geojson_query.geojson)
            if geojson_query and geojson_query.geojson
            else None
        )

        return {
            "success": True,
            "message": f"Boundary {operation} completed"
            + (" and re-analysis done" if reanalyze else ""),
            "calculation_id": str(calculation_id),
            "new_area_hectares": round(area_hectares, 4),
            "sub_areas_clipped": _reclip["clipped"],
            "sub_areas_dropped": _reclip["dropped"],
            "geometry": geometry_json,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to edit boundary: {str(e)}",
        )


# NOTE: area computed geodesically via ST_Transform to UTM projection for accurate per-polygon measurements
@router.get(
    "/calculations/{calculation_id}/polygons", response_model=BlockPolygonListResponse
)
def get_calculation_polygons(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get list of individual polygons from a calculation's boundary geometry.

    This extracts each polygon from the boundary (which could be MultiPolygon)
    and returns them as individual polygons that the user can name as blocks.
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this calculation",
        )

    # Check if boundary geometry exists
    if not calculation.boundary_geom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No boundary geometry found for this calculation",
        )

    # Get existing blocks from result_data (if any) - database table may not have blocks yet
    existing_blocks = {}
    if calculation.result_data and "blocks" in calculation.result_data:
        for block in calculation.result_data.get("blocks", []):
            existing_blocks[block.get("block_index", 0)] = block.get("block_name", "")

    # Extract individual polygons from the boundary geometry
    # First check the geometry type
    geom_type_query = db.execute(
        text(
            "SELECT ST_GeometryType(boundary_geom) as geom_type, ST_NumGeometries(boundary_geom) as num_geoms FROM calculations WHERE id = :calc_id"
        ),
        {"calc_id": str(calculation_id)},
    ).first()

    logger.info(
        f"Boundary geometry type: {geom_type_query.geom_type}, num_geometries: {geom_type_query.num_geoms}"
    )

    # Debug: check if boundary_geom exists and is valid
    boundary_check = db.execute(
        text(
            "SELECT boundary_geom IS NOT NULL as has_geom, ST_IsValid(boundary_geom) as is_valid FROM calculations WHERE id = :calc_id"
        ),
        {"calc_id": str(calculation_id)},
    ).first()
    logger.info(
        f"Boundary check - has_geom: {boundary_check.has_geom}, is_valid: {boundary_check.is_valid}"
    )

    # Try to get valid geometries - check result_data first
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    result_data = calculation.result_data or {}

    # If blocks exist in result_data with valid geometry, use those
    blocks_in_result = result_data.get("blocks", [])
    if blocks_in_result and len(blocks_in_result) > 0:
        logger.info(f"Found {len(blocks_in_result)} blocks in result_data")

        polygons = []
        for i, block in enumerate(blocks_in_result):
            block_geom = block.get("geometry")
            block_area = block.get("area_hectares", 0)
            block_name = block.get("block_name", f"Block {i+1}")

            logger.info(f"Block {i+1} in result_data: area = {block_area}")

            if block_geom:
                polygons.append(
                    BlockPolygonResponse(
                        index=i,
                        geometry=block_geom,
                        area_hectares=round(block_area, 4) if block_area else 0,
                        current_name=block_name,
                    )
                )

        if polygons:
            logger.info(f"Using {len(polygons)} blocks from result_data")
            return BlockPolygonListResponse(
                polygons=polygons, total_count=len(polygons)
            )

    # Otherwise try to extract from boundary_geom
    num_geoms = geom_type_query.num_geoms or 1

    # Get centroid to determine UTM zone (auto-computed from lon/lat via SSOT)
    try:
        centroid_query = db.execute(
            text(
                """
                SELECT ST_X(ST_Centroid(boundary_geom)) as centroid_lon,
                       ST_Y(ST_Centroid(boundary_geom)) as centroid_lat
                FROM calculations
                WHERE id = :calc_id
            """
            ),
            {"calc_id": str(calculation_id)},
        ).first()

        centroid_lon = centroid_query.centroid_lon if centroid_query else 85.0
        centroid_lat = centroid_query.centroid_lat if centroid_query else 27.0
        utm_srid = calculate_utm_epsg(centroid_lon, centroid_lat)
        logger.info(
            f"Using UTM zone {utm_srid} (lon: {centroid_lon}, lat: {centroid_lat})"
        )
    except Exception as e:
        logger.error(f"Error getting centroid: {e}")
        utm_srid = calculate_utm_epsg(85.0, 27.0)  # Default to eastern Nepal
        centroid_lon = 85.0

    # For each geometry, get its area and geometry separately (using UTM for accurate area)
    polygons = []
    poly_index = 0  # Only count polygon geometries
    for i in range(1, num_geoms + 1):
        try:
            # Check geometry type first - skip non-polygons (e.g., LineStrings from corrupted boundaries)
            geom_type_result = db.execute(
                text(
                    "SELECT ST_GeometryType(ST_GeometryN(boundary_geom, :idx)) as gtype FROM calculations WHERE id = :calc_id"
                ),
                {"calc_id": str(calculation_id), "idx": i},
            ).first()
            if geom_type_result and geom_type_result.gtype not in (
                "ST_Polygon",
                "ST_MultiPolygon",
            ):
                logger.info(
                    f"Skipping non-polygon geometry {i}: {geom_type_result.gtype}"
                )
                continue

            # Extract the i-th geometry from the collection and transform to UTM for accurate area
            single_geom_query = db.execute(
                text(
                    f"""
                    SELECT 
                        ST_Area(ST_Transform(ST_GeometryN(boundary_geom, :idx), :utm_srid)) / {SQM_PER_HA} as area_hectares,
                        ST_AsGeoJSON(ST_GeometryN(boundary_geom, :idx)) as geometry
                    FROM calculations
                    WHERE id = :calc_id
                """
                ),
                {"calc_id": str(calculation_id), "idx": i, "utm_srid": utm_srid},
            ).first()

            if single_geom_query and single_geom_query.geometry:
                geom_json = json.loads(single_geom_query.geometry)
                logger.info(
                    f"Polygon {poly_index}: area_hectares = {single_geom_query.area_hectares}"
                )
                polygons.append(
                    BlockPolygonResponse(
                        index=poly_index,
                        geometry=geom_json,
                        area_hectares=(
                            round(single_geom_query.area_hectares, 4)
                            if single_geom_query.area_hectares
                            else 0
                        ),
                        current_name=existing_blocks.get(
                            poly_index, f"Block {poly_index + 1}"
                        ),
                    )
                )
                poly_index += 1
        except Exception as e:
            logger.error(f"Error extracting polygon {i}: {e}")
            continue

    logger.info(f"Extracted {len(polygons)} polygons from calculation {calculation_id}")

    return BlockPolygonListResponse(polygons=polygons, total_count=len(polygons))


# business: CFMG — blocks are the primary management unit, 5-25 ha each
# constraint: minimum block area 1 ha, maximum 50 ha
@router.post(
    "/calculations/{calculation_id}/create-single-block", response_model=BlockResponse
)
def create_single_default_block(
    calculation_id: UUID,
    block_name: Optional[str] = None,
    is_compartment: bool = False,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Create a single default block (or, with `is_compartment=true`, compartment)
    from the calculation's boundary geometry. Used when the user chooses "Single
    Block"/"Single Compartment" in Block Naming or Map Creation, and by the
    workspace's "Import Block/Compartment from Forest Boundary" menu command.

    Args:
        calculation_id: The calculation UUID
        block_name: Optional custom name (default: "B1" / "C1")
        is_compartment: Create the unit on the compartment branch instead of
            the block branch (mutually exclusive per the forest structure rule
            -- callers gate this on no blocks/compartments already existing)

    Returns:
        Created block data with geometry and area
    """
    # 1. Get calculation and verify ownership
    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == calculation_id, Calculation.user_id == current_user.id
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    # 1b. Structure lock (H-SUBMIT). This endpoint DELETEs every block for the
    # calculation before recreating one, so it must honour the same lock the
    # divide / block-edit endpoints do — otherwise a locked map could still be
    # gutted through here (e.g. the "divide into compartments from the boundary"
    # shortcut, which calls this first).
    if getattr(calculation, "structure_locked", False):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "code": "structure_locked",
                "message": "Map structure is locked (submission in progress)",
                "structure_locked_at": (
                    str(calculation.structure_locked_at)
                    if getattr(calculation, "structure_locked_at", None)
                    else None
                ),
            },
        )

    # 2. Delete existing blocks if any
    deleted_count = (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calculation_id)
        .delete()
    )

    if deleted_count > 0:
        logger.info(
            f"Deleted {deleted_count} existing blocks for calculation {calculation_id}"
        )

    # 3. Get boundary geometry as WKT
    boundary_wkt = db.scalar(select(func.ST_AsText(calculation.boundary_geom)))

    if not boundary_wkt:
        raise HTTPException(
            status_code=400, detail="Calculation has no boundary geometry"
        )

    # 4. Calculate area in hectares (using UTM projection 32645 for Nepal)
    # Area in hectares (UTM zone auto-selected from the boundary centroid)
    # NOTE (BL-4 fix, 2026-08-29): db.scalar() on a two-column select() only
    # ever returns the FIRST column (a bare float) — `_clon, _clat = _c` was
    # unconditionally a TypeError whenever the calculation had a real
    # boundary. Pre-existing bug, unrelated to block lifecycle decoupling but
    # blocking it end-to-end (this endpoint is what "Import Block from Forest
    # Boundary" calls), so fixed here. Use execute().first() to get both
    # columns back as a Row.
    _c = db.execute(
        select(
            func.ST_X(func.ST_Centroid(calculation.boundary_geom)),
            func.ST_Y(func.ST_Centroid(calculation.boundary_geom)),
        )
    ).first()
    _clon, _clat = tuple(_c) if _c and _c[0] is not None else (85.0, 27.0)
    _utm_area = calculate_utm_epsg(_clon, _clat)
    area_hectares = db.scalar(
        select(
            func.ST_Area(func.ST_Transform(calculation.boundary_geom, _utm_area))
            / SQM_PER_HA
        )
    )

    # 5. Create default unit name if not provided
    unit_label = "Compartment" if is_compartment else "Block"
    if not block_name:
        from ..core.naming_strategies import unit_serial

        block_name = unit_serial(is_compartment=is_compartment, index=1)  # C1 / B1 -- the forest is already named

    logger.info(
        f"Creating single {unit_label.lower()} '{block_name}' for calculation {calculation_id}"
    )

    # 6. Create ForestBlock record
    forest_block = ForestBlock(
        id=uuid4(),
        calculation_id=calculation_id,
        name=block_name,
        geometry=func.ST_GeomFromText(boundary_wkt, 4326),
        area_hectares=area_hectares,
        index=0,
        created_at=datetime.now(timezone.utc),
        division_level=DEPTH_TOP_BLOCK,
        is_compartment=is_compartment,
    )
    db.add(forest_block)

    block_geojson = db.scalar(
        select(func.ST_AsGeoJSON(func.ST_GeomFromText(boundary_wkt, 4326)))
    )

    # 7. Update calculation result_data with the new unit. The compartment
    # branch already has a dedicated reconciler (block_reconcile_service) that
    # rebuilds the compartment array and `polygon_type` straight from the
    # `forest_blocks` row we just added -- reuse it instead of hand-writing a
    # second JSONB shape here.
    if is_compartment:
        # autoflush is off on this app's sessions (app/core/database.py) — the
        # reconciler queries `forest_blocks` directly, so the just-added row
        # must be flushed first or it reads as "no compartments yet" and
        # no-ops.
        db.flush()
        reconcile_compartments_from_db(db, calculation)
    else:
        result_data = calculation.result_data or {}
        result_data["blocks"] = [
            {
                "id": str(forest_block.id),  # Include UUID id for frontend compatibility
                "block_index": 0,
                "block_name": block_name,
                "area_hectares": float(area_hectares) if area_hectares else 0,
                "geometry": json.loads(block_geojson),
            }
        ]
        result_data["total_blocks"] = 1
        calculation.result_data = result_data

    calculation.status = CalculationStatus.PENDING  # Ready for analysis
    # BL-4 (GAP_HANDLING_PLAN.md): an explicit reimport re-opts the calculation
    # into persist_boundary's auto single-block-create on future saves.
    # (Duplicate of blocks.py::create_single_default_block — this is the copy
    # the frontend actually calls, under the /forests mount.)
    calculation.blocks_cleared_by_user = False

    db.commit()
    db.refresh(forest_block)

    logger.info(f"Successfully created single {unit_label.lower()} with ID {forest_block.id}")

    # 8. Return block response
    return BlockResponse(
        id=str(forest_block.id),
        name=forest_block.name,
        geometry=json.loads(block_geojson),
        area_hectares=float(forest_block.area_hectares),
        index=forest_block.index,
        created_at=forest_block.created_at,
    )


# business: CFMG — block geometry excludes private land (excluded sub-areas)
# NOTE: area computed geodesically via ST_Area(geography()) for WGS84 ellipsoidal accuracy
@router.post("/calculations/{calculation_id}/blocks", response_model=BlockListResponse)
def create_blocks_from_polygons(
    calculation_id: UUID,
    request: BlockCreateListRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Create forest blocks from polygon mapping.

    User provides a list of polygon indices and their names. Each polygon
    from the boundary geometry becomes a forest block.
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this calculation",
        )

    # Delete existing blocks
    db.query(ForestBlock).filter(ForestBlock.calculation_id == calculation_id).delete()

    # Create new blocks
    created_blocks = []
    total_area = 0.0

    for block_req in request.blocks:
        # Get the polygon geometry for this index
        # Filter out non-polygon geometries (e.g., LineStrings from corrupted boundaries)
        # Use ST_Area(geography()) for accurate geodesic calculation
        polygon_query = db.execute(
            text(
                f"""
                WITH polygon_dump AS (
                    SELECT
                        (ST_Dump(boundary_geom)).geom as poly_geom,
                        row_number() OVER () as rn
                    FROM calculations
                    WHERE id = :calc_id
                )
                SELECT
                    poly_geom as polygon_geom,
                    ST_Area(geography(poly_geom)) / {SQM_PER_HA} as area_hectares
                FROM polygon_dump
                WHERE ST_GeometryType(poly_geom) IN ('ST_Polygon', 'ST_MultiPolygon')
                OFFSET :offset LIMIT 1
            """
            ),
            {"calc_id": str(calculation_id), "offset": block_req.polygon_index},
        ).fetchone()

        if not polygon_query:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Polygon index {block_req.polygon_index} not found",
            )

        if not polygon_query.area_hectares or polygon_query.area_hectares <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Polygon index {block_req.polygon_index} has invalid area ({polygon_query.area_hectares} ha)",
            )

        # Create block record
        block = ForestBlock(
            calculation_id=calculation_id,
            name=block_req.name,
            geometry=polygon_query.polygon_geom,
            area_hectares=polygon_query.area_hectares,
            index=block_req.polygon_index,
            division_level=DEPTH_TOP_BLOCK,
        )
        db.add(block)
        created_blocks.append(block)
        total_area += polygon_query.area_hectares

    db.commit()

    # Save block geometries to result_data so frontend can display them
    blocks_for_result_data = []
    for block in created_blocks:
        geojson_result = db.query(
            func.ST_AsGeoJSON(block.geometry).label("geojson")
        ).first()

        # Compute geo-derived properties from geometry
        from ..utils.geometry_utils import compute_geometry_properties

        if geojson_result and geojson_result.geojson:
            try:
                from shapely.geometry import shape

                geom_shape = shape(json.loads(geojson_result.geojson))
                geo_props = compute_geometry_properties(geom_shape)
            except Exception:
                logger.warning(
                    "derived geometry properties unavailable - area and perimeter "
                    "omitted for this feature",
                    exc_info=True,
                )
                geo_props = {}
        else:
            geo_props = {}

        block_data = {
            "id": str(block.id),  # Include UUID id for frontend compatibility
            "block_index": block.index,
            "block_name": block.name,
            "area_hectares": round(block.area_hectares, 4),
            "geometry": (
                json.loads(geojson_result.geojson)
                if geojson_result and geojson_result.geojson
                else None
            ),
            **geo_props,
        }
        blocks_for_result_data.append(block_data)

    # Update result_data with block geometries
    if calculation.result_data:
        calculation.result_data["blocks"] = blocks_for_result_data
        flag_modified(calculation, "result_data")
        db.commit()

    # Set status to PENDING (ready for analysis to be triggered separately from Analysis page)
    calculation.status = CalculationStatus.PENDING
    db.commit()
    logger.info(
        f"Blocks saved for calculation {calculation_id}. Status set to PENDING."
    )

    # Refresh to get IDs
    for block in created_blocks:
        db.refresh(block)

    # Build response
    block_responses = []
    for block in created_blocks:
        # Convert geometry to GeoJSON using proper SQLAlchemy
        geojson_result = db.query(
            func.ST_AsGeoJSON(block.geometry).label("geojson")
        ).first()

        block_responses.append(
            BlockResponse(
                id=str(block.id),
                name=block.name,
                geometry=(
                    json.loads(geojson_result.geojson)
                    if geojson_result and geojson_result.geojson
                    else {}
                ),
                area_hectares=round(block.area_hectares, 4),
                index=block.index,
                created_at=block.created_at,
            )
        )

    return BlockListResponse(
        blocks=block_responses,
        total_count=len(block_responses),
        total_area_hectares=round(total_area, 4),
    )


@router.post(
    "/calculations/{calculation_id}/import-blocks", response_model=BlockListResponse
)
def import_blocks_from_geometry(
    calculation_id: UUID,
    request: BlockCreateFromGeometryRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Import forest blocks from arbitrary GeoJSON geometries.

    Creates ForestBlock records directly from provided geometries (not from boundary_geom).
    Used for importing shapefiles/GeoJSON as blocks directly into the builtin Blocks layer.
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this calculation",
        )

    # Create new blocks from provided geometries
    created_blocks = []
    total_area = 0.0

    for idx, block_req in enumerate(request.blocks):
        geometry = block_req.get("geometry")
        name = block_req.get("name") or f"Block {idx + 1}"
        block_index = block_req.get("index", idx)

        if not geometry:
            continue

        # Convert GeoJSON to WKT for PostGIS
        from shapely.geometry import shape
        from shapely import wkt as shapely_wkt

        try:
            geom_shape = shape(geometry)
            if geom_shape.is_empty:
                continue
            geom_wkt = shapely_wkt.dumps(geom_shape)
            # Calculate area in hectares using geodesic calculation
            area_hectares = round(calculate_area_geodesic(geom_shape) / SQM_PER_HA, 4)
        except Exception as e:
            logger.warning(f"Failed to process block geometry {idx}: {e}")
            continue

        # Create block record
        block = ForestBlock(
            calculation_id=calculation_id,
            name=name,
            geometry=func.ST_GeomFromText(geom_wkt, 4326),
            area_hectares=area_hectares,
            index=block_index,
            division_level=DEPTH_TOP_BLOCK,
        )
        db.add(block)
        created_blocks.append(block)
        total_area += area_hectares

    if not created_blocks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid geometries provided",
        )

    db.commit()

    # Save block geometries to result_data
    blocks_for_result_data = []
    for block in created_blocks:
        geojson_result = db.query(
            func.ST_AsGeoJSON(block.geometry).label("geojson")
        ).first()

        from ..utils.geometry_utils import compute_geometry_properties

        if geojson_result and geojson_result.geojson:
            try:
                from shapely.geometry import shape

                geom_shape = shape(json.loads(geojson_result.geojson))
                geo_props = compute_geometry_properties(geom_shape)
            except Exception:
                logger.warning(
                    "derived geometry properties unavailable - area and perimeter "
                    "omitted for this feature",
                    exc_info=True,
                )
                geo_props = {}
        else:
            geo_props = {}

        block_data = {
            "id": str(block.id),
            "block_index": block.index,
            "block_name": block.name,
            "area_hectares": round(block.area_hectares, 4),
            "geometry": (
                json.loads(geojson_result.geojson)
                if geojson_result and geojson_result.geojson
                else None
            ),
            **geo_props,
        }
        blocks_for_result_data.append(block_data)

    # Update result_data with block geometries
    if calculation.result_data:
        calculation.result_data["blocks"] = blocks_for_result_data
        flag_modified(calculation, "result_data")
        db.commit()

    # Set status to PENDING
    calculation.status = CalculationStatus.PENDING
    db.commit()

    # Build response
    block_responses = []
    for block in created_blocks:
        geojson_result = db.query(
            func.ST_AsGeoJSON(block.geometry).label("geojson")
        ).first()

        block_responses.append(
            BlockResponse(
                id=str(block.id),
                name=block.name,
                geometry=(
                    json.loads(geojson_result.geojson)
                    if geojson_result and geojson_result.geojson
                    else {}
                ),
                area_hectares=round(block.area_hectares, 4),
                index=block.index,
                created_at=block.created_at,
            )
        )

    return BlockListResponse(
        blocks=block_responses,
        total_count=len(block_responses),
        total_area_hectares=round(total_area, 4),
    )


def _forest_condition_by_block_name(db: Session, calculation_id) -> dict:
    """{block_name: 'Good'|'Moderate'|'Weak'} from the field-inventory block
    summaries for this calculation, or {} when no field inventory exists.
    Used to surface `forest_condition` on block / compartment features so the
    map can be coloured by condition (WORKSPACE_LAYER_STYLING_PLAN.md P4.5)."""
    fi = (
        db.query(FieldInventoryCalculation)
        .filter(FieldInventoryCalculation.calculation_id == calculation_id)
        .first()
    )
    if not fi:
        return {}
    rows = (
        db.query(
            FieldInventoryBlockSummary.block_name,
            FieldInventoryBlockSummary.forest_condition,
        )
        .filter(
            FieldInventoryBlockSummary.field_inventory_calculation_id == fi.id,
            FieldInventoryBlockSummary.forest_condition.isnot(None),
        )
        .all()
    )
    return {name: cond for name, cond in rows if name}


@router.get("/calculations/{calculation_id}/blocks", response_model=BlockListResponse)
def get_calculation_blocks(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get all forest blocks for a calculation.
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this calculation",
        )

    # FS-1c.1: migration 094 puts top-level compartments at the same depth as top-level blocks, so
    # `is_compartment` (the branch) is now required here too (in lockstep with the duplicate endpoint
    # in api/blocks.py) - this endpoint is "GET the blocks", not "GET everything at depth 1" (I10).
    from ..services.forest_units.queries import promoted_or_unlayered

    blocks = (
        promoted_or_unlayered(
            db.query(ForestBlock).filter(
                ForestBlock.calculation_id == calculation_id,
                ForestBlock.is_compartment.isnot(True),
                ForestBlock.division_level == DEPTH_TOP_BLOCK,
            )
        )
        .order_by(ForestBlock.index)
        .all()
    )

    # Field-inventory forest condition per block name (P4.5 "Colour by condition").
    condition_by_name = _forest_condition_by_block_name(db, calculation_id)
    block_responses = []
    total_area = 0.0

    for block in blocks:
        geojson_result = db.query(
            func.ST_AsGeoJSON(block.geometry).label("geojson")
        ).first()

        # Use DB-persisted columns (populated at commit) for stable values matching commit-time display
        block_responses.append(
            BlockResponse(
                id=str(block.id),
                name=block.name,
                block_name=block.block_name,
                natural_name=block.natural_name,
                geometry=(
                    json.loads(geojson_result.geojson)
                    if geojson_result and geojson_result.geojson
                    else {}
                ),
                area_hectares=round(block.area_hectares, 4),
                index=block.index,
                created_at=block.created_at,
                working_circle=getattr(block, "working_circle", None) or "production",
                style=getattr(block, "style", None),
                forest_condition=condition_by_name.get(block.block_name)
                or condition_by_name.get(block.name),
                dominant_slope_band=getattr(block, "dominant_slope_band", None),
                dominant_aspect=getattr(block, "dominant_aspect", None),
                dominant_canopy_class=getattr(block, "dominant_canopy_class", None),
                dominant_health_class=getattr(block, "dominant_health_class", None),
                dominant_nasa_quality=getattr(block, "dominant_nasa_quality", None),
                dominant_landcover=getattr(block, "dominant_landcover", None),
                dominant_elevation_zone=getattr(block, "dominant_elevation_zone", None),
                elevation_min_m=(
                    float(block.elevation_min_m)
                    if getattr(block, "elevation_min_m", None) is not None
                    else None
                ),
                elevation_mean_m=(
                    float(block.elevation_mean_m)
                    if getattr(block, "elevation_mean_m", None) is not None
                    else None
                ),
                elevation_max_m=(
                    float(block.elevation_max_m)
                    if getattr(block, "elevation_max_m", None) is not None
                    else None
                ),
                management_orientation=getattr(block, "management_orientation", None),
                suggested_orientation=getattr(block, "suggested_orientation", None),
                orientation_justification_ne=getattr(
                    block, "orientation_justification_ne", None
                ),
                orientation_justification_en=getattr(
                    block, "orientation_justification_en", None
                ),
            )
        )
        total_area += block.area_hectares

    from ..services.forest_units.mode import forest_stream

    return BlockListResponse(
        blocks=block_responses,
        total_count=len(block_responses),
        total_area_hectares=round(total_area, 4),
        stream=forest_stream(db, calculation_id).value,
    )


# why: boundary geometry updated via geoalchemy2 from_shape for direct PostGIS WKB storage (avoids WKT round-trip)
@router.put("/calculations/{calculation_id}/boundary")
def update_boundary_geometry(
    calculation_id: UUID,
    request: dict,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Update the forest boundary geometry.

    Allows users to edit the boundary polygon after initial creation.
    Updates both the boundary_geom in database and the geometry in result_data.
    """
    from shapely.geometry import shape

    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == calculation_id, Calculation.user_id == current_user.id
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    geometry = request.get("geometry")
    if not geometry:
        raise HTTPException(status_code=400, detail="Geometry is required")

    # VR-3 / Rule A — the forest boundary is editable only while no structural
    # feature exists.  This is the route that actually serves
    # PUT /api/forests/calculations/{id}/boundary (there is a second, similar
    # handler in blocks.py); gating only one of them would leave the rule
    # unenforced, which is how it was missed until an API test caught it.
    #
    # Scope is a RESHAPE: setting the first boundary, or re-sending the same
    # shape, stays allowed so idempotent and area-only saves keep working.
    from app.services import vertex_guard_service as _guard

    if calculation.boundary_geom is not None and _guard.has_structural_features(
        db, calculation
    ):
        from geoalchemy2.shape import to_shape as _to_shape

        if _guard.boundary_shape_changed(
            _to_shape(calculation.boundary_geom), shape(geometry)
        ):
            raise i18n_error(409, "blocks.boundary_locked_by_structure")

    try:
        # Convert GeoJSON to shapely polygon, then write through the single
        # boundary-write point (PB-3) so result_data, geodesic area,
        # geometry_version and single-block auto-create match every other path.
        from app.services.boundary_write_service import persist_boundary

        geom_shape = shape(geometry)
        if not geom_shape.is_valid:
            from shapely.validation import make_valid

            geom_shape = make_valid(geom_shape)
        if geom_shape.geom_type not in ("Polygon", "MultiPolygon"):
            raise HTTPException(
                status_code=400, detail="Geometry must be Polygon or MultiPolygon"
            )

        # PF-3 provisional gate: if the proposed boundary would adjoin/overlap
        # another CF and the caller did not set confirmed=true, return the
        # preview relations without writing (frontend opens the decision panel).
        # The write path is byte-for-byte unchanged for the fast path (no relations).
        if not request.get("confirmed"):
            try:
                from shapely.geometry import mapping as _mapping
                from geoalchemy2 import Geography
                from sqlalchemy import func as _func
                from decimal import Decimal as _Decimal
                from uuid import UUID as _UUID
                from app.services.gap_detector import detect_relations, GapParams
                from app.schemas.boundary import (
                    GapForest as _GapForest,
                    OverlappingForest as _OverlappingForest,
                )

                wkt = geom_shape.wkt
                existing = (
                    db.query(Calculation)
                    .filter(
                        Calculation.boundary_geom.isnot(None),
                        _func.ST_DWithin(
                            Calculation.boundary_geom.cast(Geography),
                            _func.ST_GeomFromText(wkt, 4326).cast(Geography),
                            200,
                        ),
                        Calculation.id != calculation_id,
                    )
                    .all()
                )
                relations = detect_relations(
                    _mapping(geom_shape),
                    existing,
                    GapParams(adjacency_m=200, min_fragment_ha=0.001),
                )
                has = any(
                    float(r.overlap_ha or 0) > 0 for r in relations
                )  # clip-only: overlap gates the review, gaps do not
                if has:
                    # Compute clipped resolved geometry for Accept (overlap removed)
                    try:
                        from shapely.ops import unary_union as _uu

                        _r_geoms = []
                        for _cc in existing:
                            if _cc.boundary_geom is not None:
                                try:
                                    from geoalchemy2.shape import (
                                        to_shape as _r_to_shape,
                                    )

                                    _r_geoms.append(_r_to_shape(_cc.boundary_geom))
                                except Exception:
                                    logger.warning(
                                        "boundary-overlap preview: neighbour %s geometry "
                                        "unreadable - excluded from the resolved-geometry "
                                        "union, understating the clip",
                                        _cc.id,
                                        exc_info=True,
                                    )
                        _r_union = _uu(_r_geoms) if _r_geoms else None
                        _r_resolved = (
                            geom_shape.difference(_r_union)
                            if _r_union and not _r_union.is_empty
                            else geom_shape
                        )
                        if not _r_resolved.is_valid:
                            from shapely.validation import make_valid as _r_mv

                            _r_resolved = _r_mv(_r_resolved)
                        _r_resolved_geojson = (
                            _mapping(_r_resolved) if not _r_resolved.is_empty else None
                        )
                    except Exception:
                        logger.warning(
                            "boundary-overlap preview: resolved-geometry computation "
                            "failed - Accept will show no clipped preview",
                            exc_info=True,
                        )
                        _r_resolved_geojson = None
                    # Build neighbour geometry map for overlay
                    _bnd_by_id: dict[str, dict] = {}
                    for _c in existing:
                        if _c.boundary_geom is not None:
                            try:
                                from geoalchemy2.shape import to_shape as _to_shape

                                _bnd_by_id[str(_c.id)] = _mapping(
                                    _to_shape(_c.boundary_geom)
                                )
                            except Exception:
                                logger.warning(
                                    "boundary-overlap preview: neighbour %s geometry "
                                    "unreadable - overlay omits it",
                                    _c.id,
                                    exc_info=True,
                                )
                                _bnd_by_id[str(_c.id)] = None  # type: ignore[assignment]
                    gaps = []
                    gap_total = _Decimal("0")
                    for r in relations:
                        gap_geom = None
                        if r.gap_polygon is not None and not r.gap_polygon.is_empty:
                            gap_geom = _mapping(r.gap_polygon)
                        gaps.append(
                            _GapForest(
                                id=_UUID(r.id),
                                name=r.name,
                                name_np=r.name_np,
                                overlap_ha=_Decimal(str(r.overlap_ha)),
                                gap_ha=_Decimal(str(r.gap_ha)),
                                gap_shape=r.gap_shape,
                                gap_size=r.gap_size,
                                gap_geometry=gap_geom,
                                adjacent=r.adjacent,
                                geometry=_bnd_by_id.get(str(r.id)),
                            )
                        )
                        gap_total += _Decimal(str(r.gap_ha))
                    gap_total = round(gap_total, 4)
                    overlapping = []
                    for r in relations:
                        if float(r.overlap_ha or 0) > 0:
                            overlapping.append(
                                _OverlappingForest(
                                    id=_UUID(r.id),
                                    name=r.name,
                                    name_np=r.name_np,
                                    overlap_ha=_Decimal(str(r.overlap_ha)),
                                    forest_area_ha=_Decimal("0"),
                                    gap_ha=_Decimal(str(r.gap_ha)),
                                    gap_shape=r.gap_shape,
                                    gap_size=r.gap_size,
                                    adjacent=r.adjacent,
                                    geometry=_bnd_by_id.get(str(r.id)),
                                )
                            )
                    return {
                        "needs_overlap_review": True,
                        "provisional": True,
                        "overlapping_forests": [
                            o.model_dump(mode="json") for o in overlapping
                        ],
                        "gaps": [g.model_dump(mode="json") for g in gaps],
                        "gap_total_ha": float(gap_total),
                        "preview_geometry": geometry,
                        "resolved_geometry": _r_resolved_geojson,
                    }
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(
                    f"[update-boundary] preview gate failed, falling through to write: {e}"
                )

        # Honour a client-supplied area (the edit/import PUT trusts it; PB-3
        # parity), otherwise persist_boundary computes geodesic area.
        # persist_boundary also clips against adjoining forests (import / edit /
        # extend all clip identically).
        from app.services.boundary_write_service import BoundaryFullyInsideExisting
        from app.services.boundary_validation import BoundaryRulesViolation

        try:
            _write = persist_boundary(
                db,
                calculation,
                geom_shape,
                area_hectares=request.get("area_hectares"),
                validate=True,
                reclip_sub_areas=False,  # re-clipped and REPORTED below
            )
        except BoundaryFullyInsideExisting:
            raise i18n_error(409, "boundary.overlap_detected_relock")
        except BoundaryRulesViolation as bv:
            # within Nepal · ≤ 1000 ha · ≤ 40% built-up+cropland · protected-area
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=bv.detail
            )
        from shapely.geometry import shape as _shp_clip

        geom_shape = _shp_clip(_write["geometry"])  # clipped geometry for reclip below

        db.commit()
        db.refresh(calculation)

        # VR-6 (D6) — a sub-area sticking out past the new edge would keep
        # subtracting land the forest no longer contains from every report.
        # Applied on BOTH boundary write paths (this one and edit-geometry):
        # this route carries draw / import / undo, the other carries the vertex
        # tool, and a repair wired to one of them repairs half the cases.
        from app.services.sub_area_reclip_service import reclip_sub_areas_to_boundary

        _reclip = reclip_sub_areas_to_boundary(db, calculation, geom_shape)
        if _reclip["clipped"] or _reclip["dropped"]:
            db.commit()

        logger.info(
            f"[update-boundary] Updated boundary for calculation {calculation_id}"
        )

        return {
            "success": True,
            **i18n_success("success.boundary_updated"),
            "area_hectares": _write["area_hectares"],
            "sub_areas_clipped": _reclip["clipped"],
            "sub_areas_dropped": _reclip["dropped"],
            # warnings (e.g. "clipped to Nepal") for the client to surface
            "boundary_validation": _write.get("boundary_validation"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[update-boundary] Error: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update boundary: {str(e)}"
        )


# why: purpose-first creation — Block/Compartment pieces are merged into the single forest boundary
@router.post("/calculations/{calculation_id}/merge-forest-boundary")
def merge_forest_boundary(
    calculation_id: UUID,
    request: MergeForestBoundaryRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Merge one or more geometry pieces into the single forest boundary.

    Purpose-first creation (NAME_FIRST_CREATION_PLAN.md Phase 3): a CFOP's
    Block / Compartment / Forest-boundary pieces can be merged into the forest
    boundary. All pieces are unioned (shapely unary_union) into boundary_geom
    and the geodesic area is recomputed. Keeps is_draft=True until the user
    explicitly proceeds.
    """
    from shapely.geometry import shape, mapping
    from shapely.ops import unary_union
    from geoalchemy2.shape import from_shape

    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == calculation_id, Calculation.user_id == current_user.id
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    if not request.geometries:
        raise HTTPException(status_code=400, detail="At least one geometry is required")

    try:
        pieces = []
        for geometry in request.geometries:
            pieces.append(shape(geometry))

        if len(pieces) == 1:
            boundary_shape = pieces[0]
        else:
            boundary_shape = unary_union(pieces)

        # Forest-boundary rules — purpose-first creation establishes the forest's
        # boundary here (blocks become the boundary), so the same gate as an
        # upload applies (within Nepal · ≤ 1000 ha · ≤ 40% built-up + cropland ·
        # protected-area / Buffer Zone).
        from app.services.boundary_validation import (
            enforce_boundary_rules,
            BoundaryRulesViolation,
        )

        try:
            _bv = enforce_boundary_rules(
                db, boundary_shape.wkt, forest_name=calculation.forest_name
            )
        except BoundaryRulesViolation as bv:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=bv.detail
            )
        if _bv.clipped:  # R1 trimmed an out-of-Nepal part
            from shapely.wkt import loads as _wkt_loads

            boundary_shape = _wkt_loads(_bv.effective_wkt)

        boundary_geometry = mapping(boundary_shape)

        boundary_wkb = from_shape(boundary_shape, srid=4326)

        # Update boundary_geom
        calculation.boundary_geom = boundary_wkb

        # BOUNDARY_PIECES_PLAN.md P2: sync from `pieces` (what the user actually
        # drew), NOT `boundary_shape` (the post-unary_union value) -- a union can
        # fuse two pieces that merely touch or share a snapped edge, which would
        # silently lose one piece's identity if pieces were re-derived from the
        # already-merged shape instead.
        from app.services.boundary_pieces_service import sync_boundary_pieces_from_parts

        sync_boundary_pieces_from_parts(db, calculation, pieces)

        # Update result_data
        result_data = calculation.result_data or {}
        result_data["geometry"] = boundary_geometry
        result_data["area_hectares"] = calculate_area_geodesic(boundary_geometry)[1]
        result_data["boundary_validation"] = _bv.report.as_dict()
        calculation.result_data = result_data

        flag_modified(calculation, "result_data")

        from app.services.sub_area_reclip_service import reclip_after_boundary_write

        _reclip = reclip_after_boundary_write(db, calculation, boundary_shape)
        db.commit()

        logger.info(
            f"[merge-forest-boundary] Merged {len(pieces)} piece(s) into boundary for calculation {calculation_id}"
        )

        return {
            "success": True,
            "message": f"Merged {len(pieces)} piece(s) into forest boundary",
            "area_hectares": result_data["area_hectares"],
            "geometry_type": boundary_geometry["type"],
            "boundary_validation": _bv.report.as_dict(),
            "sub_areas_clipped": _reclip["clipped"],
            "sub_areas_dropped": _reclip["dropped"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[merge-forest-boundary] Error: {e}")
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to merge forest boundary: {str(e)}"
        )


# NOTE: block rename syncs across result_data blocks array, sub-areas blockName references, and calculation.block_name
@router.patch(
    "/calculations/{calculation_id}/blocks/{block_id}", response_model=BlockResponse
)
def update_block(
    calculation_id: UUID,
    block_id: UUID,
    name: Optional[str] = Query(None, min_length=1, max_length=255),
    request: Optional[BlockRenameRequest] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Update a forest block's name / serial / natural name.

    Phase C (auto-block): accepts a JSON body ``BlockRenameRequest`` with
    ``name`` / ``block_name`` / ``natural_name``. ``name`` is the display name
    and mirrors ``block_name`` unless ``block_name`` is provided explicitly.
    A legacy ``?name=`` query param is still honoured (kept for old clients).
    """
    if request and getattr(request, "geometry", None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Geometry updates are not allowed via this endpoint. Use POST /calculations/{id}/geometry/edit-geometry.",
        )
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this calculation",
        )

    block = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.id == block_id, ForestBlock.calculation_id == calculation_id
        )
        .first()
    )

    if not block:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Forest division not found"
        )

    new_name = (request.name if request else None) or (
        name if isinstance(name, str) else None
    )
    new_block_name = (request.block_name if request else None) or (
        new_name if new_name else None
    )
    new_natural_name = request.natural_name if request else None
    natural_explicit = (
        request is not None and "natural_name" in request.model_fields_set
    )
    style_explicit = request is not None and "style" in request.model_fields_set
    # Attribute-table editability (user report, 2026-09-12): a merge
    # auto-picks compartment_code/dominant_slope_band/dominant_aspect/
    # dominant_canopy_class from the larger source feature, and the user
    # must still be able to correct that pick by hand. Same
    # present-in-request-including-null clears / absent-leaves-untouched
    # rule as natural_name/style above.
    code_explicit = (
        request is not None and "compartment_code" in request.model_fields_set
    )
    slope_explicit = (
        request is not None and "dominant_slope_band" in request.model_fields_set
    )
    aspect_explicit = (
        request is not None and "dominant_aspect" in request.model_fields_set
    )
    canopy_explicit = (
        request is not None and "dominant_canopy_class" in request.model_fields_set
    )
    health_explicit = (
        request is not None and "dominant_health_class" in request.model_fields_set
    )
    nasa_explicit = (
        request is not None and "dominant_nasa_quality" in request.model_fields_set
    )
    landcover_explicit = (
        request is not None and "dominant_landcover" in request.model_fields_set
    )
    zone_explicit = (
        request is not None and "dominant_elevation_zone" in request.model_fields_set
    )
    orientation_explicit = (
        request is not None and "management_orientation" in request.model_fields_set
    )
    classification_explicit = (
        code_explicit
        or slope_explicit
        or aspect_explicit
        or canopy_explicit
        or health_explicit
        or nasa_explicit
        or landcover_explicit
        or zone_explicit
        or orientation_explicit
    )
    if (
        not new_name
        and not new_block_name
        and not natural_explicit
        and not style_explicit
        and not classification_explicit
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Provide at least one of name, block_name, natural_name, "
                "compartment_code, dominant_slope_band, dominant_aspect, "
                "dominant_canopy_class, dominant_health_class, "
                "dominant_nasa_quality, dominant_landcover, "
                "dominant_elevation_zone, management_orientation or style."
            ),
        )

    old_name = block.name
    old_block_name = block.block_name
    if new_name:
        block.name = new_name
    if new_block_name:
        block.block_name = new_block_name
    # an automatic code that was just a copy of the old name follows the rename; a code typed by the user (below) always wins
    from ..services.forest_units.write import keep_code_in_step

    keep_code_in_step(block, old_name, old_block_name)
    # natural_name clears only when the client explicitly sent `natural_name`
    # (model_fields_set tracks it) — so `{"natural_name": null}` resets it,
    # while omitting the key leaves it untouched.
    if request is not None and "natural_name" in request.model_fields_set:
        block.natural_name = (
            new_natural_name.strip()
            if new_natural_name and new_natural_name.strip()
            else None
        )
    if code_explicit:
        code = request.compartment_code
        block.compartment_code = code.strip() if code and code.strip() else None
    if slope_explicit:
        block.dominant_slope_band = request.dominant_slope_band
    if aspect_explicit:
        block.dominant_aspect = request.dominant_aspect
    if canopy_explicit:
        block.dominant_canopy_class = request.dominant_canopy_class
    if health_explicit:
        block.dominant_health_class = request.dominant_health_class
    if nasa_explicit:
        block.dominant_nasa_quality = request.dominant_nasa_quality
    if landcover_explicit:
        block.dominant_landcover = request.dominant_landcover
    if zone_explicit:
        block.dominant_elevation_zone = request.dominant_elevation_zone
    if orientation_explicit:
        from ..services.forest_units.write import set_management_orientation

        set_management_orientation(calculation, block, request.management_orientation)

    # Per-feature style override (P3). Present + dict → store the {fill,
    # fillOpacity, stroke, weight} subset; present + null → clear it.
    if style_explicit:
        if request.style:
            block.style = {
                k: request.style[k]
                for k in ("fill", "fillOpacity", "stroke", "weight")
                if k in request.style and request.style[k] is not None
            } or None
        else:
            block.style = None

    # Sync result_data blocks array
    result_data = calculation.result_data or {}

    # result_data['blocks'/'compartments'/'sub_compartments'] is a snapshot
    # that shadows the forest_blocks table for some readers (see the
    # "result_data units stale trap" lesson) — style already re-syncs it on
    # every PATCH, so the classification/code fields must too, or a stale
    # snapshot silently keeps showing the pre-edit value.
    if style_explicit or classification_explicit:
        _bid = str(block_id)
        for _coll in ("blocks", "compartments", "sub_compartments"):
            for _bd in result_data.get(_coll, []) or []:
                if _bd.get("block_id") == _bid or _bd.get("id") == _bid:
                    if style_explicit:
                        _bd["style"] = block.style
                    if code_explicit:
                        _bd["compartment_code"] = block.compartment_code
                    if slope_explicit:
                        _bd["dominant_slope_band"] = block.dominant_slope_band
                    if aspect_explicit:
                        _bd["dominant_aspect"] = block.dominant_aspect
                    if canopy_explicit:
                        _bd["dominant_canopy_class"] = block.dominant_canopy_class
                    if health_explicit:
                        _bd["dominant_health_class"] = block.dominant_health_class
                    if nasa_explicit:
                        _bd["dominant_nasa_quality"] = block.dominant_nasa_quality
                    if landcover_explicit:
                        _bd["dominant_landcover"] = block.dominant_landcover
                    if zone_explicit:
                        _bd["dominant_elevation_zone"] = block.dominant_elevation_zone
    effective_name = new_name or new_block_name
    if effective_name and "blocks" in result_data:
        for block_data in result_data["blocks"]:
            if (
                block_data.get("block_id") == str(block_id)
                or block_data.get("block_name") == old_name
            ):
                block_data["block_name"] = effective_name

    # Sync sub-areas blockName references
    if effective_name and "sub_areas" in result_data:
        block_id_str = str(block_id)
        for sa in result_data["sub_areas"]:
            if sa.get("blockId") == block_id_str:
                sa["blockName"] = effective_name
            if sa.get("block_name") == old_name:
                sa["block_name"] = effective_name
            # Sync block_breakdown items
            if "blockBreakdown" in sa:
                for bb in sa["blockBreakdown"]:
                    if bb.get("blockId") == block_id_str:
                        bb["blockName"] = effective_name

    # Sync calculation.block_name if it matches the old name
    if effective_name and calculation.block_name == old_name:
        calculation.block_name = effective_name

    # SV-1.3: drop both SFM variant blobs on attribute edits that change
    # slope/orientation — the only columns that feed the zone classifier.
    if slope_explicit or orientation_explicit:
        result_data.pop("sfm", None)
        result_data.pop("sfm_user", None)

    calculation.result_data = result_data
    flag_modified(calculation, "result_data")

    # Sync field inventory block names so Field Inventory tab stays in sync
    if effective_name:
        try:
            field_inv = (
                db.query(FieldInventoryCalculation)
                .filter(FieldInventoryCalculation.calculation_id == calculation_id)
                .first()
            )
            if field_inv:
                db.query(FieldInventoryBlockSummary).filter(
                    FieldInventoryBlockSummary.field_inventory_calculation_id
                    == field_inv.id,
                    FieldInventoryBlockSummary.block_name == old_name,
                ).update({"block_name": effective_name})
                # Also update sample plot block names (used by species breakdown query)
                db.query(FieldInventorySamplePlot).filter(
                    FieldInventorySamplePlot.field_inventory_calculation_id
                    == field_inv.id,
                    FieldInventorySamplePlot.block_name == old_name,
                ).update({"block_name": effective_name})
        except Exception as e:
            logger.error(
                f"[update_block] Failed to sync field inventory block name: {e}"
            )

    db.commit()
    db.refresh(block)

    geojson_result = db.query(
        func.ST_AsGeoJSON(block.geometry).label("geojson")
    ).first()

    # DB-persisted columns only (populated at commit): stable values matching commit-time display.
    return BlockResponse(
        id=str(block.id),
        name=block.name,
        block_name=block.block_name,
        natural_name=block.natural_name,
        compartment_code=block.compartment_code,
        geometry=(
            json.loads(geojson_result.geojson)
            if geojson_result and geojson_result.geojson
            else {}
        ),
        area_hectares=round(block.area_hectares, 4),
        index=block.index,
        created_at=block.created_at,
        working_circle=getattr(block, "working_circle", None) or "production",
        style=getattr(block, "style", None),
        dominant_slope_band=block.dominant_slope_band,
        dominant_aspect=block.dominant_aspect,
        dominant_canopy_class=block.dominant_canopy_class,
        dominant_health_class=block.dominant_health_class,
        dominant_nasa_quality=block.dominant_nasa_quality,
        dominant_landcover=block.dominant_landcover,
        dominant_elevation_zone=block.dominant_elevation_zone,
        elevation_min_m=(
            float(block.elevation_min_m) if block.elevation_min_m is not None else None
        ),
        elevation_mean_m=(
            float(block.elevation_mean_m) if block.elevation_mean_m is not None else None
        ),
        elevation_max_m=(
            float(block.elevation_max_m) if block.elevation_max_m is not None else None
        ),
        management_orientation=block.management_orientation,
        suggested_orientation=block.suggested_orientation,
        orientation_justification_ne=block.orientation_justification_ne,
        orientation_justification_en=block.orientation_justification_en,
    )


@router.delete(
    "/calculations/{calculation_id}/blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_block(
    calculation_id: UUID,
    block_id: UUID,
    confirm_children: bool = Query(
        False,
        description="FS-4a.9: required to delete a unit that has sub-units below it",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Delete a forest block.

    FS-4a.9 (D13): if the block has sub-units, ``confirm_children=true`` is
    required or this returns 409 with the count -- a plain delete now
    genuinely cascade-removes every descendant (``ForestBlock.compartments``
    gained ``passive_deletes=True``), so the caller must say so on purpose.
    Kept in lockstep with ``blocks.py``'s own mount of this same route (see
    the module note on the duplicate routers).
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this calculation",
        )

    block = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.id == block_id, ForestBlock.calculation_id == calculation_id
        )
        .first()
    )

    if not block:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Forest division not found"
        )

    if not confirm_children:
        from ..services.forest_units.operations.reparent import child_count

        n = child_count(db, block.id)
        if n > 0:
            raise i18n_error(409, "blocks.has_children_confirm_required", count=n)

    was_compartment = bool(getattr(block, "is_compartment", False))
    # Owner report 2026-10-02: collected BEFORE the delete below -- kept in
    # lockstep with blocks.py's own mount of this same route (see the
    # module note on the duplicate routers).
    ids_to_delete = [block.id]
    frontier = [block.id]
    while frontier:
        next_gen = db.query(ForestBlock.id).filter(ForestBlock.parent_block_id.in_(frontier)).all()
        frontier = [row.id for row in next_gen]
        ids_to_delete.extend(frontier)
    raster_layer_ids_touched = {
        row.raster_layer_id
        for row in db.query(ForestBlock.raster_layer_id)
        .filter(ForestBlock.id.in_(ids_to_delete), ForestBlock.raster_layer_id.isnot(None))
        .all()
    }
    db.delete(block)
    db.commit()
    if raster_layer_ids_touched:
        from ..services.auto_block_service import demote_orphaned_layers
        demote_orphaned_layers(db, raster_layer_ids_touched)
    _enforce_invariant_after_delete(db, calculation, was_compartment)
    _clear_stale_result_data_units(db, calculation)


def _clear_stale_result_data_units(db, calculation) -> None:
    """Keep ``result_data['blocks'/'compartments']`` in step with the DB.

    Those arrays are the legacy *upload-mode* structure store. Once a forest is
    edited in the workspace the ``forest_blocks`` table is authoritative, and a
    stale array left behind by a since-deleted division otherwise shadows the
    current structure — e.g. sampling generated against deleted compartments
    (only covering part of the forest). Drop each array whose corresponding DB
    rows are gone.
    """
    rd = calculation.result_data
    if not isinstance(rd, dict):
        return
    has_compartments = (
        db.query(ForestBlock.id)
        .filter(
            ForestBlock.calculation_id == calculation.id,
            ForestBlock.is_compartment.is_(True),
        )
        .first()
        is not None
    )
    has_blocks = (
        db.query(ForestBlock.id)
        .filter(
            ForestBlock.calculation_id == calculation.id,
            ForestBlock.is_compartment.isnot(True),
            ForestBlock.division_level == DEPTH_TOP_BLOCK,
        )
        .first()
        is not None
    )
    changed = False
    new_rd = dict(rd)
    if not has_compartments and new_rd.get("compartments"):
        new_rd["compartments"] = []
        new_rd["total_compartments"] = 0
        changed = True
    if not has_blocks and new_rd.get("blocks"):
        new_rd["blocks"] = []
        new_rd["total_blocks"] = 0
        changed = True
    if changed:
        calculation.result_data = new_rd
        flag_modified(calculation, "result_data")
        db.commit()


def _enforce_invariant_after_delete(db, calculation, was_compartment) -> None:
    """Boundary≡Blocks invariant (plan BLOCK_BOUNDARY_INVARIANT, E.4).

    Deleting a block normally opens a coverage gap → silently auto-fill it as
    a Remainder Block/Compartment so total block area always equals the
    boundary.

    Block-lifecycle decoupling (2026-08-29, GAP_HANDLING_PLAN.md BL-2):
    deleting the LAST remaining row at the top-level `blocks` division
    (top-level, non-compartment) is instead treated as a deliberate
    "clear structure" action, not a gap — the remainder-fill is skipped and
    `blocks_cleared_by_user` is set so `persist_boundary` stops re-creating a
    block on every subsequent save. Scoped to `blocks` only (Decision C):
    compartments keep the original always-refill behaviour.

    NOTE: this is a duplicate of `blocks.py::_enforce_invariant_after_delete`
    — `forests.py`'s `delete_block` (below) is the route the frontend
    actually calls (`/api/forests/calculations/{id}/blocks/{id}`); the
    `blocks.py` copy is kept in sync so either mount behaves the same.
    """
    from ..services.block_area_invariant_service import enforce_block_coverage

    level = "compartments" if was_compartment else "blocks"

    if level == "blocks":
        remaining = (
            db.query(ForestBlock)
            .filter(
                ForestBlock.calculation_id == calculation.id,
                ForestBlock.is_compartment.isnot(True),
                ForestBlock.division_level == DEPTH_TOP_BLOCK,
            )
            .count()
        )
        if remaining == 0:
            calculation.blocks_cleared_by_user = True
            db.commit()
            return

    try:
        enforce_block_coverage(db, calculation, level=level)
        db.commit()
    except ValueError as e:
        if str(e) == "TOPOLOGY_REJECTED":
            # Over-coverage cannot happen from a delete; if it does, roll back.
            db.rollback()
            return
        raise


@router.delete("/calculations/{calculation_id}/blocks", status_code=status.HTTP_200_OK)
def delete_all_blocks(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Delete all forest blocks for a calculation.

    Useful for clearing blocks before re-importing.
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this calculation",
        )

    deleted_count = (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calculation_id)
        .delete()
    )
    calculation.geometry_version = (calculation.geometry_version or 0) + 1
    # BL-2 (GAP_HANDLING_PLAN.md): this is exactly the "deliberate clear"
    # this docstring already described ("clearing blocks before
    # re-importing") — record it so persist_boundary doesn't silently
    # recreate a block on the next boundary save.
    calculation.blocks_cleared_by_user = True
    # Legacy upload-mode structure arrays must not survive a full DB clear —
    # otherwise they shadow the (now empty) DB for sampling / exports / OP data.
    rd = calculation.result_data
    if isinstance(rd, dict) and (rd.get("blocks") or rd.get("compartments")):
        new_rd = dict(rd)
        new_rd["blocks"] = []
        new_rd["compartments"] = []
        new_rd["total_blocks"] = 0
        new_rd["total_compartments"] = 0
        calculation.result_data = new_rd
        flag_modified(calculation, "result_data")
    db.commit()

    return {
        "success": True,
        "deleted_count": deleted_count,
        "message": f"Deleted {deleted_count} blocks",
    }


# business: CFMG — block geometry excludes private land (excluded sub-areas); sub-areas clipped when blocks resize
@router.patch("/calculations/{calculation_id}/update-blocks")
def update_blocks_geometry(
    calculation_id: UUID,
    request: Dict[str, Any],
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Update block geometries from the frontend editor.

    This endpoint handles:
    1. Updating block geometries in result_data
    2. Detecting outer vs inner vertex changes
    3. Updating forest boundary if outer vertices changed
    4. Clipping sub-areas that fall outside new block boundaries

    Request body:
    {
        "blocks": [
            {
                "block_id": "...",
                "block_name": "...",
                "geometry": {...},  // GeoJSON
                "area_hectares": ...
            }
        ],
        "update_boundary": true/false  // Whether to also update forest boundary
    }
    """
    from shapely.geometry import shape, mapping
    from shapely.ops import transform
    import pyproj
    from geoalchemy2.shape import from_shape
    from sqlalchemy.orm import Session as SqlSession
    from datetime import datetime, timezone
    from ..utils.geometry_utils import compute_geometry_properties, strip_geo_fields

    logger.info(f"\n[update_blocks_geometry] calculation_id={calculation_id}")

    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this calculation",
        )

    blocks_data = request.get("blocks", [])
    update_boundary = request.get("update_boundary", False)

    logger.info(f"[update_blocks_geometry] Received {len(blocks_data)} blocks")
    logger.info(f"[update_blocks_geometry] update_boundary={update_boundary}")

    if not calculation.result_data:
        calculation.result_data = {}

    result_data = calculation.result_data

    # Get existing blocks
    existing_blocks = result_data.get("blocks", [])
    logger.info(f"[update_blocks_geometry] Existing blocks: {len(existing_blocks)}")

    # Helper function to calculate geodesic area
    def calculate_geodesic_area(geometry):
        try:
            geom = shape(geometry)
            geodesic = pyproj.Geod(ellps="WGS84")
            area_sqm, _ = geodesic.geometry_area_perimeter(geom)
            return abs(area_sqm) / SQM_PER_HA  # hectares
        except Exception as e:
            logger.error(f"[update_blocks_geometry] Error calculating area: {e}")
            return 0

    # Track if boundary was updated
    boundary_updated = False

    # Update each block
    updated_blocks = []
    for block_data in blocks_data:
        block_id = block_data.get("block_id")
        geometry = block_data.get("geometry")

        if not geometry:
            continue

        # Strip any geo_* fields from client payload (tamper-proof)
        block_data = strip_geo_fields(block_data)

        # Calculate new area
        new_area = calculate_geodesic_area(geometry)

        # Find existing block to preserve data
        existing = None
        for eb in existing_blocks:
            if eb.get("block_id") == block_id:
                existing = eb
                break

        # Compute geometry-derived properties (authoritative server-side)
        try:
            geom = shape(geometry)
            geo_props = compute_geometry_properties(geom)
        except Exception as e:
            logger.warning(f"Error computing geometry properties for block: {e}")
            geo_props = {}

        updated_block = {
            "block_id": block_id,
            "block_name": block_data.get(
                "block_name",
                (
                    existing.get("block_name")
                    if existing
                    else f"Block {len(updated_blocks)+1}"
                ),
            ),
            "geometry": geometry,
            "area_hectares": round(new_area, 4),
            "index": block_data.get("index", len(updated_blocks)),
            **geo_props,
        }

        # Preserve centroid if exists
        if existing and "centroid" in existing:
            updated_block["centroid"] = existing["centroid"]
        else:
            # Calculate centroid
            try:
                geom = shape(geometry)
                centroid = geom.centroid
                updated_block["centroid"] = {"lon": centroid.x, "lat": centroid.y}
            except Exception:
                logger.exception(
                    "centroid could not be computed - the block keeps its PREVIOUS "
                    "centroid, which now points at where it used to be"
                )

        updated_blocks.append(updated_block)
        logger.info(
            f"[update_blocks_geometry] Updated block {block_id}: area={new_area:.4f} ha"
        )

    # Update result_data
    result_data["blocks"] = updated_blocks
    result_data["total_blocks"] = len(updated_blocks)

    # If update_boundary flag is set, update forest boundary from block geometries
    if update_boundary and len(updated_blocks) > 0:
        logger.info(f"[update_blocks_geometry] Updating forest boundary using ST_Union")

        try:
            from shapely.ops import unary_union

            # Collect all block geometries
            block_geometries = []
            for block in updated_blocks:
                block_geom = block.get("geometry")
                if block_geom:
                    block_shape = shape(block_geom)
                    block_geometries.append(block_shape)

            if len(block_geometries) == 1:
                # Single block - use its geometry directly
                boundary_shape = block_geometries[0]
            elif len(block_geometries) > 1:
                # Multiple blocks - use ST_Union (unary_union) to create proper boundary
                boundary_shape = unary_union(block_geometries)
            else:
                boundary_shape = None

            if boundary_shape:
                # Convert to GeoJSON
                boundary_geometry = mapping(boundary_shape)

                # Ensure it's MultiPolygon (for consistency)
                if boundary_shape.geom_type == "Polygon":
                    boundary_geometry = {
                        "type": "MultiPolygon",
                        "coordinates": [boundary_geometry["coordinates"]],
                    }

                # Update boundary_geom in database
                boundary_wkb = from_shape(boundary_shape, srid=4326)
                calculation.boundary_geom = boundary_wkb

                # BOUNDARY_PIECES_PLAN.md D4: this legacy path re-derives the
                # boundary from the current block set (not a user drawing
                # distinct parcels) -- still sync so boundary_geom never
                # drifts from the piece table, same as every other write site
                # (kept in lockstep with blocks.py's identical duplicate route).
                from app.services.boundary_pieces_service import sync_boundary_pieces

                sync_boundary_pieces(db, calculation, boundary_shape)

                # Update geometry field
                result_data["geometry"] = boundary_geometry
                result_data["area_hectares"] = calculate_geodesic_area(
                    boundary_geometry
                )

                boundary_updated = True
                logger.info(
                    f"[update_blocks_geometry] Forest boundary updated using ST_Union"
                )
            else:
                logger.info(
                    f"[update_blocks_geometry] No block geometries to create boundary"
                )
        except Exception as e:
            import traceback

            logger.error(f"[update_blocks_geometry] Error updating boundary: {e}")
            traceback.print_exc()

    # Every sub-area must lie inside the forest -- which here IS the union of the
    # blocks just saved. The per-block clipping below is the legacy behaviour: it
    # clips to ONE "best" block and never removes a sub-area that is wholly outside,
    # so the standard re-clip runs first and it can only narrow things further.
    from shapely.ops import unary_union as _union
    from ..utils.geometry_utils import calculate_area_geodesic_from_shapely
    from app.services.sub_area_reclip_service import reclip_after_boundary_write

    _forest_parts = []
    for _b in updated_blocks:
        if _b.get("geometry"):
            try:
                _forest_parts.append(shape(_b["geometry"]))
            except Exception:
                logger.exception(
                    "update_blocks_geometry: block geometry unreadable for the re-clip"
                )
    _reclip = {"clipped": [], "dropped": [], "unchanged": 0}
    if _forest_parts:
        calculation.result_data = result_data
        _reclip = reclip_after_boundary_write(db, calculation, _union(_forest_parts))
        result_data = calculation.result_data or result_data

    # Now handle sub-area clipping
    sub_areas = result_data.get("sub_areas", [])
    clipped_sub_areas = []

    logger.info(
        f"[update_blocks_geometry] Processing {len(sub_areas)} sub-areas for clipping"
    )

    for sub_area in sub_areas:
        sub_area_geom = sub_area.get("geometry")
        if not sub_area_geom:
            continue

        sub_area_shape = shape(sub_area_geom)

        # Find which block(s) this sub-area belongs to
        # For simplicity, clip to the first block that contains most of the sub-area
        best_block = None
        best_coverage = 0

        for block in updated_blocks:
            block_geom = block.get("geometry")
            if not block_geom:
                continue

            block_shape = shape(block_geom)

            try:
                intersection = sub_area_shape.intersection(block_shape)
                if not intersection.is_empty:
                    coverage = (
                        intersection.area / sub_area_shape.area
                        if sub_area_shape.area > 0
                        else 0
                    )
                    if coverage > best_coverage:
                        best_coverage = coverage
                        best_block = block
                        best_intersection = intersection
            except Exception as e:
                logger.error(
                    f"[update_blocks_geometry] Error checking intersection: {e}"
                )

        if best_block and best_coverage < 1.0:
            # Sub-area is partially outside - clip it
            try:
                block_geom = best_block.get("geometry")
                block_shape = shape(block_geom)

                clipped = sub_area_shape.intersection(block_shape)

                if not clipped.is_empty and clipped.area > 0:
                    # Update sub-area geometry
                    clipped_geom = mapping(clipped)
                    sub_area["geometry"] = clipped_geom
                    # geodesic hectares (clipped.area is square DEGREES: / SQM_PER_HA gave ~0)
                    clipped_area = round(
                        calculate_area_geodesic_from_shapely(clipped)[1], 4
                    )
                    sub_area["area_hectares"] = round(clipped_area, 4)

                    clipped_sub_areas.append(
                        {
                            "id": sub_area.get("id"),
                            "name": sub_area.get("name"),
                            "original_area": sub_area_shape.area / 10000,
                            "clipped_area": clipped_area,
                            "block_id": best_block.get("block_id"),
                            "block_name": best_block.get("block_name"),
                        }
                    )
                    logger.info(
                        f"[update_blocks_geometry] Clipped sub-area '{sub_area.get('name')}' to {clipped_area:.4f} ha"
                    )
                elif clipped.is_empty:
                    # Sub-area is completely outside - mark for removal or keep minimal
                    logger.info(
                        f"[update_blocks_geometry] Sub-area '{sub_area.get('name')}' is completely outside blocks"
                    )
            except Exception as e:
                logger.error(f"[update_blocks_geometry] Error clipping sub-area: {e}")

    # Recalculate excluded areas
    excluded_total = calculate_total_excluded_area(sub_areas)
    result_data["excluded_area_hectares"] = round(excluded_total, 4)

    # Recalculate effective areas per block
    block_excluded_map = calculate_block_excluded_areas(updated_blocks, sub_areas)
    for block in updated_blocks:
        block_id = block.get("block_id")
        block_excluded = block_excluded_map.get(block_id, 0.0)
        block["excluded_area_hectares"] = round(block_excluded, 4)
        original_area = block.get("area_hectares", 0)
        block["effective_area_hectares"] = round(original_area - block_excluded, 4)

    # Save to database
    calculation.result_data = result_data
    flag_modified(calculation, "result_data")
    # BA-4: forest_blocks is authoritative — re-assert the DB block set over any stale
    # request-driven snapshot after the bulk update. Routed through the write funnel
    # (FS-1b.4a): also bumps geometry_version (this endpoint never had before — a real
    # gap, since it changes geometry) and marks downstream data stale.
    from ..services.forest_units.write import structure_write

    with structure_write(db, calculation, change="bulk block-geometry update"):
        pass
    db.commit()
    db.refresh(calculation)

    logger.info(
        f"[update_blocks_geometry] Saved {len(updated_blocks)} blocks, {len(clipped_sub_areas)} sub-areas clipped"
    )
    logger.info(f"[update_blocks_geometry] boundary_updated={boundary_updated}")

    return {
        "success": True,
        "blocks": updated_blocks,
        "sub_areas": sub_areas,
        "clipped_sub_areas": clipped_sub_areas,
        "boundary_updated": boundary_updated,
        "sub_areas_clipped_to_forest": _reclip["clipped"],
        "sub_areas_dropped": _reclip["dropped"],
        "message": f"Updated {len(updated_blocks)} blocks. {len(clipped_sub_areas)} sub-areas were clipped to fit within block boundaries.",
    }


# why: recalculates using ST_Area(geography()) for geodesic accuracy to fix legacy incorrect area calculations (previously used raw ST_Area in 4326)
@router.post("/calculations/{calculation_id}/recalculate-areas")
def recalculate_areas(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Recalculate all area values for blocks and sub-areas using accurate geodesic calculations.

    This endpoint will:
    1. Recalculate areas for all blocks using ST_Area(geography())
    2. Recalculate areas for all sub-areas using UTM projection
    3. Update the result_data with corrected values

    Use this endpoint to fix any area calculations that were done with the old (incorrect) method.
    """
    from ..utils.geometry_utils import (
        calculate_area_geodesic_from_shapely,
        compute_geometry_properties,
    )
    from shapely import wkb

    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this calculation",
        )

    recalculated_blocks = 0
    recalculated_subareas = 0

    # Recalculate block areas
    blocks = (
        db.query(ForestBlock).filter(ForestBlock.calculation_id == calculation_id).all()
    )
    for block in blocks:
        # Use PostGIS geography for accurate calculation
        area_query = db.execute(
            text(
                f"SELECT ST_Area(geography(geometry)) / {SQM_PER_HA} as area_ha FROM forest_blocks WHERE id = :block_id"
            ),
            {"block_id": str(block.id)},
        ).fetchone()

        if area_query:
            new_area = round(area_query.area_ha, 4)
            old_area = block.area_hectares
            block.area_hectares = new_area
            recalculated_blocks += 1
            logger.info(
                f"Block {block.name}: {old_area:.4f} ha -> {new_area:.4f} ha (diff: {abs(new_area - old_area):.4f} ha)"
            )

    db.commit()

    # Recalculate sub-area areas and geo props in result_data
    result_data = calculation.result_data or {}
    sub_areas = result_data.get("sub_areas", [])

    for sa in sub_areas:
        if "geometry" in sa:
            try:
                # Calculate using geodesic method
                area_sqm, area_hectares = calculate_area_geodesic(sa["geometry"])
                old_area = sa.get("area_hectares", 0)
                sa["area_hectares"] = round(area_hectares, 4)
                sa["area_sqm"] = round(area_sqm, 4)
                recalculated_subareas += 1
                logger.info(
                    f"Sub-area {sa.get('name', 'Unknown')}: {old_area:.4f} ha -> {area_hectares:.4f} ha (diff: {abs(area_hectares - old_area):.4f} ha)"
                )
                # Recompute geo_* properties
                from shapely.geometry import shape as _shp

                sa_geom = _shp(sa["geometry"])
                geo_props = compute_geometry_properties(sa_geom)
                for k, v in geo_props.items():
                    sa[k] = v
            except Exception as e:
                logger.error(
                    f"Error recalculating sub-area {sa.get('name', 'Unknown')}: {e}"
                )

    # Recalculate total excluded area
    excluded_total = sum(
        sa.get("area_hectares", 0)
        for sa in sub_areas
        if sa.get("isExcluded", False) or sa.get("is_excluded", False)
    )
    result_data["excluded_area_hectares"] = round(excluded_total, 4)

    # Update blocks in result_data with new areas
    if "blocks" in result_data:
        for block_data in result_data["blocks"]:
            block_name = block_data.get("block_name")
            # Find corresponding ForestBlock
            for db_block in blocks:
                if db_block.name == block_name:
                    block_data["area_hectares"] = round(db_block.area_hectares, 4)
                    # Recompute geo_* properties
                    try:
                        block_shape = wkb.loads(bytes(db_block.geometry.data))
                        geo_props = compute_geometry_properties(block_shape)
                        for k, v in geo_props.items():
                            block_data[k] = v
                    except Exception:
                        logger.exception(
                            "derived properties unavailable for block %s - its area and "
                            "perimeter are absent from the response",
                            getattr(db_block, "id", "?"),
                        )
                    break

    # Recalculate block-level excluded areas
    if "blocks" in result_data:
        for block_data in result_data["blocks"]:
            block_name = block_data.get("block_name")
            block_excluded = sum(
                sa.get("area_hectares", 0)
                for sa in sub_areas
                if (sa.get("isExcluded", False) or sa.get("is_excluded", False))
                and sa.get("blockName") == block_name
            )
            block_data["excluded_area_hectares"] = round(block_excluded, 4)
            original_area = block_data.get("area_hectares", 0)
            block_data["effective_area_hectares"] = round(
                original_area - block_excluded, 4
            )

    # Recalculate whole forest effective area
    total_area = result_data.get("area_hectares", 0)
    result_data["effective_area_hectares"] = round(total_area - excluded_total, 4)

    calculation.result_data = result_data
    flag_modified(calculation, "result_data")
    db.commit()

    return {
        "success": True,
        "message": f"Recalculated areas for {recalculated_blocks} blocks and {recalculated_subareas} sub-areas",
        "blocks_updated": recalculated_blocks,
        "sub_areas_updated": recalculated_subareas,
        "total_excluded_area": round(excluded_total, 4),
    }


# ============================================
# TABLE 5: Block Area Detail Endpoint
# ============================================


# business: CFMG — Table 5: block area detail combines geometric area, tree cover, other landcover, protected area, private land, effective area
@router.get(
    "/calculations/{calculation_id}/block-area-detail",
    response_model=BlockAreaDetailResponse,
)
def get_block_area_detail(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get per-block area details for Table 5 (सामुदायिक वन तथा वन खण्डको क्षेत्रफल सम्वन्धी विवरण).

    Combines:
    - Geometric block area (from coordinates)
    - Tree cover area (ESA WorldCover pixel value=10, proportional)
    - Other landcover area (ESA WorldCover pixel value≠10, proportional)
    - Protected area (from sub-areas with category='protected')
    - Private land (from sub-areas with category='private_land')
    - Effective area = Tree Cover - Protected - Private Land

    Uses proportional pixel-to-area conversion to ensure Tree + Other = Total Block Area.
    """
    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
        )

    # Get analysis units from result_data — compartments when the forest was
    # divided into them (mirrors PolygonSource in the analysis engine), else
    # blocks. Table 5 must be per whatever unit the analysis actually ran on.
    result_data = calculation.result_data or {}
    from ..services.analysis_polygon_source import PolygonSource

    blocks = PolygonSource.for_result_data(result_data).get_polygons()

    if not blocks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calculation has no defined areas. Create them first.",
        )

    # Get sub-areas from result_data
    sub_areas = result_data.get("sub_areas", [])

    # Calculate block area details
    try:
        block_details = calculate_block_area_details(db, blocks, sub_areas)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error calculating area details: {str(e)}",
        )

    # Calculate totals
    totals = BlockAreaDetailItem(
        block_name="TOTAL",
        total_area_ha=round(sum(b["total_area_ha"] for b in block_details), 4),
        tree_cover_area_ha=round(
            sum(b["tree_cover_area_ha"] for b in block_details), 4
        ),
        other_landcover_area_ha=round(
            sum(b["other_landcover_area_ha"] for b in block_details), 4
        ),
        protected_area_ha=round(sum(b["protected_area_ha"] for b in block_details), 4),
        private_land_area_ha=round(
            sum(b["private_land_area_ha"] for b in block_details), 4
        ),
        effective_area_ha=round(sum(b["effective_area_ha"] for b in block_details), 4),
        official_area_ha=round(sum(b["official_area_ha"] for b in block_details), 4),
    )

    return BlockAreaDetailResponse(
        calculation_id=str(calculation_id),
        forest_name=calculation.forest_name or "Unknown",
        total_blocks=len(block_details),
        block_details=[BlockAreaDetailItem(**b) for b in block_details],
        totals=totals,
    )


# ============================================
# DRAFT ENDPOINTS - Save work-in-progress
# ============================================


# NOTE: drafts store island geometry in draft_data JSONB; no boundary_geom until convert
@router.post(
    "/drafts/create-name-only",
    response_model=DraftResponse,
    status_code=status.HTTP_200_OK,
)
def create_name_only_draft(
    request: CreateNameOnlyDraftRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Create a draft by name only, without any geometry yet.

    The CFOP is created as a draft (name-first), then geometry is added
    afterwards in the workspace via the purpose-aware "Add Geometry" action
    (first purpose is Forest boundary, Block or Compartment; block/compartment
    pieces can later be merged into the forest boundary). Keeps is_draft=True
    until the user explicitly proceeds.
    """
    try:
        # Check for existing draft with same forest name
        existing_draft = (
            db.query(Calculation)
            .filter(
                Calculation.user_id == current_user.id,
                Calculation.forest_name == request.forest_name,
                Calculation.is_draft == True,
            )
            .first()
        )

        if existing_draft:
            # Update existing draft instead of creating new one
            existing_draft.draft_data = {
                "islands": [],
                "mode": "manual",
                "islands_count": 0,
                "total_area": 0.0,
                "draft_step_index": None,
            }
            existing_draft.updated_at = datetime.now(timezone.utc)

            db.commit()
            db.refresh(existing_draft)

            return DraftResponse(
                id=existing_draft.id,
                forest_name=existing_draft.forest_name,
                islands_count=0,
                total_area=0.0,
                mode="manual",
                created_at=existing_draft.created_at,
                updated_at=existing_draft.updated_at,
            )

        # Create new name-only draft
        calculation = Calculation(
            user_id=current_user.id,
            forest_name=request.forest_name,
            status=CalculationStatus.PENDING,
            is_draft=True,
            draft_data={
                "islands": [],
                "mode": "manual",
                "islands_count": 0,
                "total_area": 0.0,
                "draft_step_index": None,
            },
            result_data={"draft": True},
            uploaded_filename="draft",
            boundary_geom=None,
        )
        db.add(calculation)
        db.commit()
        db.refresh(calculation)

        return DraftResponse(
            id=calculation.id,
            forest_name=calculation.forest_name,
            islands_count=0,
            total_area=0.0,
            mode="manual",
            created_at=calculation.created_at,
            updated_at=calculation.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create draft: {str(e)}",
        )


@router.post(
    "/save-draft", response_model=DraftResponse, status_code=status.HTTP_200_OK
)
def save_draft(
    request: DraftSaveRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Save work-in-progress polygon creation (islands) as a draft.

    Allows users to save their progress while creating forest boundaries with multiple islands.
    Drafts can be resumed later from any device.

    - **forest_name**: Name for the forest (required)
    - **islands**: Array of island objects with geometry and area
    - **mode**: Creation mode ('auto' or 'manual')
    - **draft_id**: Optional UUID of existing draft to update
    """
    try:
        # Calculate summary data
        total_area = sum(island.get("area", 0) for island in request.islands)
        islands_count = len(request.islands)

        # Prepare draft data
        draft_data = {
            "islands": request.islands,
            "mode": request.mode,
            "islands_count": islands_count,
            "total_area": total_area,
            # U11: wizard step index for resume
            "draft_step_index": request.draft_step_index,
        }

        if request.draft_id:
            # Update existing draft by ID
            calculation = (
                db.query(Calculation)
                .filter(
                    Calculation.id == request.draft_id,
                    Calculation.user_id == current_user.id,
                    Calculation.is_draft == True,
                )
                .first()
            )

            if not calculation:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Draft not found or you don't have permission to update it",
                )

            calculation.forest_name = request.forest_name
            calculation.draft_data = draft_data
            calculation.updated_at = datetime.now(timezone.utc)

        else:
            # Check for existing draft with same forest name
            existing_draft = (
                db.query(Calculation)
                .filter(
                    Calculation.user_id == current_user.id,
                    Calculation.forest_name == request.forest_name,
                    Calculation.is_draft == True,
                )
                .first()
            )

            if existing_draft:
                # Update existing draft instead of creating new one
                existing_draft.draft_data = draft_data
                existing_draft.updated_at = datetime.now(timezone.utc)

                db.commit()
                db.refresh(existing_draft)

                return DraftResponse(
                    id=existing_draft.id,
                    forest_name=existing_draft.forest_name,
                    islands_count=islands_count,
                    total_area=total_area,
                    mode=request.mode,
                    created_at=existing_draft.created_at,
                    updated_at=existing_draft.updated_at,
                )

            # Create new draft - use placeholder values for required fields
            calculation = Calculation(
                user_id=current_user.id,
                forest_name=request.forest_name,
                status=CalculationStatus.PENDING,
                is_draft=True,
                draft_data=draft_data,
                result_data={"draft": True},  # Minimal result_data
                uploaded_filename="draft",  # Required field - placeholder for drafts
                boundary_geom=None,  # Will be set when draft is converted to final
            )
            db.add(calculation)

        db.commit()
        db.refresh(calculation)

        return DraftResponse(
            id=calculation.id,
            forest_name=calculation.forest_name,
            islands_count=islands_count,
            total_area=total_area,
            mode=request.mode,
            created_at=calculation.created_at,
            updated_at=calculation.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save draft: {str(e)}",
        )


@router.get("/drafts", response_model=List[DraftResponse])
def list_drafts(
    current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)
):
    """
    List all drafts for the current user.

    Returns summary information for each draft including:
    - Forest name
    - Number of islands
    - Total area
    - Creation mode
    - Timestamps
    """
    try:
        drafts = (
            db.query(Calculation)
            .filter(
                Calculation.user_id == current_user.id, Calculation.is_draft == True
            )
            .order_by(Calculation.updated_at.desc())
            .all()
        )

        response = []
        for draft in drafts:
            draft_data = draft.draft_data or {}
            response.append(
                DraftResponse(
                    id=draft.id,
                    forest_name=draft.forest_name or "Untitled Draft",
                    islands_count=draft_data.get("islands_count", 0),
                    total_area=draft_data.get("total_area", 0.0),
                    mode=draft_data.get("mode", "manual"),
                    created_at=draft.created_at,
                    updated_at=draft.updated_at,
                )
            )

        return response

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list drafts: {str(e)}",
        )


@router.get("/drafts/{draft_id}", response_model=DraftDetailResponse)
def get_draft(
    draft_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get full draft data including all islands and geometries.

    Used when resuming a draft to restore the exact state.
    """
    try:
        draft = (
            db.query(Calculation)
            .filter(
                Calculation.id == draft_id,
                Calculation.user_id == current_user.id,
                Calculation.is_draft == True,
            )
            .first()
        )

        if not draft:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Draft not found or you don't have permission to access it",
            )

        return DraftDetailResponse(
            id=draft.id,
            forest_name=draft.forest_name or "Untitled Draft",
            draft_data=draft.draft_data or {},
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get draft: {str(e)}",
        )


@router.delete("/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(
    draft_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Delete a draft.

    Permanently removes the draft from the database.
    """
    try:
        draft = (
            db.query(Calculation)
            .filter(
                Calculation.id == draft_id,
                Calculation.user_id == current_user.id,
                Calculation.is_draft == True,
            )
            .first()
        )

        if not draft:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Draft not found or you don't have permission to delete it",
            )

        db.delete(draft)
        db.commit()

        return None

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete draft: {str(e)}",
        )


# business: CFMG — draft converted to calculation sets is_draft=False, stores boundary_geom from merged islands
@router.post("/drafts/{draft_id}/convert", response_model=CalculationResponse)
def convert_draft_to_calculation(
    draft_id: UUID,
    request: ConvertDraftRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Convert a draft into an actual calculation.

    Called when user completes the wizard after loading from draft.
    Updates the is_draft flag and saves the boundary geometry.
    """
    try:
        draft = (
            db.query(Calculation)
            .filter(
                Calculation.id == draft_id,
                Calculation.user_id == current_user.id,
                Calculation.is_draft == True,
            )
            .first()
        )

        if not draft:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Draft not found or you don't have permission to convert it",
            )

        # Get the outer boundary from the request
        outer_boundary = request.outer_boundary

        # Debug: Log what we received
        logger.info(
            f"[convert_draft] Received outer_boundary type: {type(outer_boundary)}"
        )
        logger.info(f"[convert_draft] outer_boundary: {outer_boundary}")

        # Convert GeoJSON to WKT for PostGIS storage
        from ..services.map_creation_service import geojson_to_wkt

        boundary_wkt = geojson_to_wkt(outer_boundary)

        # Forest-boundary rules (within Nepal · ≤ 1000 ha · ≤ 40% built-up +
        # cropland · protected-area / Buffer Zone) — a name-first draft is
        # becoming a real forest here, so the same gate as an upload applies.
        from app.services.boundary_validation import (
            enforce_boundary_rules,
            BoundaryRulesViolation,
        )

        try:
            _bv = enforce_boundary_rules(
                db, boundary_wkt, forest_name=draft.forest_name
            )
        except BoundaryRulesViolation as bv:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=bv.detail
            )
        boundary_wkt = _bv.effective_wkt  # clipped to Nepal if R1 trimmed it

        # Update calculation
        draft.is_draft = False
        draft.boundary_geom = func.ST_GeomFromText(boundary_wkt, 4326)
        draft.draft_data = None  # Clear draft data
        _draft_rd = dict(draft.result_data or {})
        _draft_rd["boundary_validation"] = _bv.report.as_dict()
        draft.result_data = _draft_rd
        flag_modified(draft, "result_data")
        # Sub-areas recorded while the draft had no boundary are clipped to it now.
        from shapely import wkt as _draft_wkt
        from app.services.sub_area_reclip_service import reclip_after_boundary_write
        from app.services.boundary_pieces_service import sync_boundary_pieces

        _draft_boundary_shape = _draft_wkt.loads(boundary_wkt.split(";", 1)[-1])
        sync_boundary_pieces(db, draft, _draft_boundary_shape)
        reclip_after_boundary_write(db, draft, _draft_boundary_shape)
        if not draft.uploaded_filename or draft.uploaded_filename == "draft":
            draft.uploaded_filename = f"{draft.forest_name or 'Forest'}.geojson"
        draft.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(draft)

        # Return as CalculationResponse
        return CalculationResponse(
            id=draft.id,
            user_id=draft.user_id,
            uploaded_filename=draft.uploaded_filename,
            forest_name=draft.forest_name,
            block_name=draft.block_name,
            status=draft.status,
            processing_time_seconds=draft.processing_time_seconds,
            error_message=draft.error_message,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
            completed_at=draft.completed_at,
            is_draft=draft.is_draft,
            geometry=(
                json.loads(db.scalar(func.ST_AsGeoJSON(draft.boundary_geom)))
                if draft.boundary_geom
                else None
            ),
            result_data=draft.result_data,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to convert draft: {str(e)}",
        )


def _invalidate_layers(calculation_id) -> None:
    """The workspace serves its layer list from a cache: after a sub-area is added, changed or deleted, drop it, or the map keeps
    showing the old list (a deleted fire line seemed not to be deleted)."""
    from ..services.workspace_cache import invalidate_layers_cache

    invalidate_layers_cache(calculation_id)
