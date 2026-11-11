"""
Geometry and sub-area editing endpoints.
Extracted from forests.py
# business: CFMG — geometry must be valid for all forest operations (area calc, sampling, reporting)
# constraint: GeoJSON with SRID 4326 required — all geometry operations expect WGS84
# why: geometry operations done server-side via Shapely — avoids client-side distortion
# NOTE: extracted from legacy forests.py (4750→215 lines) during code quality split
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sqlalchemy.orm.attributes import flag_modified
from uuid import UUID
from datetime import datetime, timezone
import json
import logging

from shapely.geometry import mapping, shape
from shapely import wkb

from ..core.database import get_db
from ..core.exceptions import i18n_success
from ..core.geo import calculate_utm_epsg
from ..core.constants import SQM_PER_HA
from ..models.user import User
from ..models.calculation import Calculation, CalculationStatus
from ..models.forest_block import ForestBlock
from ..schemas.forest import (
    GeometryUpdateRequest,
    SubAreaCreateRequest,
    SubAreaUpdateRequest,
    SubAreaResponse,
    SubAreaListResponse,
    BlockBreakdownItem,
)
from app.core.errors import CalculationErrors
from ..utils.auth import get_current_active_user
from ..utils.authz import is_owner_or_admin
from ..utils.geometry_utils import calculate_area_geodesic_from_shapely
from shapely.ops import unary_union
from ..services.audit_service import log_geometry_audit
from ..models.user import UserRole
from ..services.analysis import analyze_forest_boundary
from ..services.sub_area_service import (
    detect_overlap,
    validate_category,
    clip_against_existing,
    compute_block_breakdown,
    build_sub_area_dict,
    has_forest_extent,
    place_sub_area_geometry,
    SubAreaPlacementError,
    PLACEMENT_MESSAGES,
)
from .forests_helpers import (
    calculate_block_breakdown,
    calculate_total_excluded_area,
    calculate_block_excluded_areas,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["geometry"])


# ============================================================================
# GEOMETRY & SUB-AREA EDITING ENDPOINTS
# ============================================================================

@router.patch("/calculations/{calculation_id}/geometry")
async def update_calculation_geometry(
    calculation_id: UUID,
    request: GeometryUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Update the boundary geometry of a calculation.

    This allows users to edit the forest boundary by:
    - Drawing new polygons
    - Modifying existing geometry
    - Uploading corrected boundary files

    Optionally triggers re-analysis after the geometry update.
    """
    # business: geometry update triggers re-analysis of all dependent calculations
    # constraint: must own calculation or be SUPER_ADMIN to modify geometry
    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    # Boundary status edit permission (S11)
    bstatus = (calculation.boundary_status or "draft")
    if bstatus == "disputed":
        raise HTTPException(403, detail="Boundary is disputed — only DFO can edit")
    if bstatus in ("validated",) and not is_owner_or_admin(calculation, current_user):
        raise HTTPException(403, detail="Only the forest creator or DFO can edit a validated boundary")
    if bstatus == "approved" and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, detail="Only DFO can edit an approved boundary")

    try:
        # Convert GeoJSON to Shapely geometry
        geom = shape(request.geometry)

        # Make geometry valid (fix self-intersections, etc.)
        if not geom.is_valid:
            from shapely.validation import make_valid
            geom = make_valid(geom)

        # Ensure it's a polygon/multipolygon
        if geom.geom_type == "LineString":
            geom = geom.buffer(0)
        elif geom.geom_type == "Point":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Geometry must be a polygon or multipolygon"
            )

        # Convert back to GeoJSON and then to WKT for PostGIS
        geom_geojson = mapping(geom)

        # Calculate area
        area_sqm = geom.area
        area_hectares = area_sqm / SQM_PER_HA

        # Update boundary geometry in database
        update_query = text("""
            UPDATE public.calculations
            SET boundary_geom = ST_GeomFromText(:wkt, 4326)
            WHERE id = :calc_id
        """)

        db.execute(update_query, {
            "wkt": geom.wkt,
            "calc_id": str(calculation_id)
        })

        # Update result_data with new geometry info
        result_data = calculation.result_data or {}
        result_data["geometry_updated"] = True
        result_data["geometry_update_area_hectares"] = round(area_hectares, 4)
        calculation.result_data = result_data
        flag_modified(calculation, "result_data")

        # Update status to indicate geometry was modified
        calculation.status = CalculationStatus.COMPLETED  # Keep completed, but geometry is modified
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
                blocks_data = result_data.get('blocks', [])
                sub_areas = result_data.get('sub_areas', [])

                # Merge analysis results
                updated_result_data = {
                    'blocks': blocks_data,
                    'sub_areas': sub_areas,
                    'geometry_updated': True,
                    'geometry_update_area_hectares': round(area_hectares, 4),
                    **analysis_results
                }

                # Update calculation
                update_result_query = text("""
                    UPDATE public.calculations
                    SET
                        result_data = CAST(:result_data AS jsonb),
                        processing_time_seconds = :processing_time,
                        status = :status,
                        completed_at = NOW()
                    WHERE id = :calc_id
                """)

                db.execute(update_result_query, {
                    "result_data": json.dumps(updated_result_data),
                    "processing_time": processing_time,
                    "status": "COMPLETED",
                    "calc_id": str(calculation_id)
                })

                db.commit()
                logger.info(f"Re-analysis completed after geometry update for calculation {calculation_id}")

            except Exception as e:
                logger.info(f"Re-analysis failed after geometry update: {e}")
                # Still return success, but include warning
                calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
                calculation.status = CalculationStatus.COMPLETED
                db.commit()

        # Get updated geometry as GeoJSON
        geojson_query = db.query(
            func.ST_AsGeoJSON(Calculation.boundary_geom).label("geojson")
        ).filter(Calculation.id == calculation_id).first()

        geometry_json = json.loads(geojson_query.geojson) if geojson_query and geojson_query.geojson else None

        return {
            "success": True,
            **i18n_success("success.geometry_updated_reanalyzed" if request.reanalyze else "success.geometry_updated"),
            "calculation_id": str(calculation_id),
            "area_hectares": round(area_hectares, 4),
            "geometry": geometry_json
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update geometry: {str(e)}"
        )


@router.post("/calculations/{calculation_id}/sub-areas/validate-overlap")
def validate_sub_area_overlap(
    calculation_id: UUID,
    request: Dict[str, Any],
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Validate a candidate sub-area geometry against existing sub-areas for overlap.
    Returns overlap conflicts without modifying any data.

    Request body: { "geometry": GeoJSON, "exclude_id": "optional-sub-area-id" }
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    geometry = request.get("geometry")
    if not geometry:
        raise HTTPException(status_code=400, detail="geometry is required")

    exclude_id = request.get("exclude_id")
    sub_areas = (calculation.result_data or {}).get("sub_areas", [])

    try:
        conflicts = detect_overlap(geometry, sub_areas, exclude_id=exclude_id)
        return {
            "overlap_detected": len(conflicts) > 0,
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Overlap validation failed: {str(e)}")


@router.post("/calculations/{calculation_id}/sub-areas", response_model=SubAreaResponse)
def add_sub_area(
    calculation_id: UUID,
    request: SubAreaCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    # business: sub-areas represent special-use zones that affect area calculations (Table 5)
    # constraint: sub-areas are subtracted from block geometry for effective forest area
    # why: separate treatment ensures protected/plantation areas don't double-count in reports
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
    from shapely.validation import make_valid
    import uuid

    # Debug logging
    logger.info(f"\n[add_sub_area] Received request:")
    logger.debug(f"  name: {request.name}")
    logger.debug(f"  category: {request.category}")
    logger.debug(f"  block_id: {request.block_id}")
    logger.debug(f"  block_name: {request.block_name}")
    logger.debug(f"  block_breakdown: {request.block_breakdown}")
    logger.debug(f"  is_excluded: {request.is_excluded}")
    logger.debug(f"  area_hectares: {request.area_hectares}")
    if request.block_breakdown:
        logger.debug(f"  block_breakdown items: {len(request.block_breakdown)}")
        for item in request.block_breakdown:
            logger.debug(f"    - blockId: {item.blockId}, blockName: {item.blockName}, area: {item.area}, percentage: {item.percentage}")

    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalculationErrors.NOT_FOUND
        )

    # Check structure lock (S14)
    if calculation.structure_locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "code": "structure_locked",
                "message": "Structure is locked — sub-area edits are disabled.",
                "message_np": "\u092f\u094b \u0938\u0902\u0930\u091a\u0928\u093e \u0932\u0915 \u0917\u0930\u093f\u090f\u0915\u094b \u091b \u2014 \u0909\u092a-\u0915\u094d\u0937\u0947\u0924\u094d\u0930 \u0938\u092e\u094d\u092a\u093e\u0926\u0928 \u0917\u0930\u094d\u0928 \u0938\u0915\u093f\u0902\u0926\u0948\u0928\u0964",
                "structure_locked_at": str(calculation.structure_locked_at) if calculation.structure_locked_at else None,
            },
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    # A sub-area is a zone *within* the forest — it is clipped to
    # (boundary ∪ blocks). Refuse it until that extent exists, matching the
    # boundary-first rule already enforced for tree-inventory import.
    if not has_forest_extent(db, calculation):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "boundary_required",
                "message": "Draw or import the forest boundary (or blocks) before adding a sub-area.",
                "message_np": "उप-क्षेत्र थप्नुअघि वनको सीमा (वा ब्लक) कोर्नुहोस् वा आयात गर्नुहोस्।",
            },
        )

    # Validate category
    from app.schemas.forest import SubAreaCategory
    valid_categories = SubAreaCategory.valid_categories()
    if request.category not in valid_categories:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
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
                detail="Geometry must be a polygon or multipolygon"
            )

        # Placement rules (inside the forest, never overlapping) live in ONE place,
        # shared with the live handler in forests.py -- see place_sub_area_geometry.
        submitted_area = geom.area
        try:
            geom, pending_boundary_clip = place_sub_area_geometry(db, calculation, geom)
        except SubAreaPlacementError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=PLACEMENT_MESSAGES[exc.reason])
        geometry_changed = abs(geom.area - submitted_area) > 1e-12

        # Calculate area (after clipping) using accurate geodesic calculation
        # Use provided area if available (from frontend calculation which may use turf.js)
        if request.area_hectares and request.area_hectares > 0 and not geometry_changed:
            area_hectares = request.area_hectares
            area_sqm = area_hectares * SQM_PER_HA
            logger.info(f"[add_sub_area] Using PROVIDED area: {area_hectares} ha (from request)")
        else:
            # Calculate using UTM projection for accuracy
            area_sqm, area_hectares = calculate_area_geodesic_from_shapely(geom)
            logger.info(f"[add_sub_area] Using CALCULATED geodesic area: {area_hectares} ha")

        # Generate unique ID
        sub_area_id = str(uuid.uuid4())

        # Calculate block breakdown from geometry (handles cross-block sub-areas)
        blocks_for_breakdown = (calculation.result_data or {}).get("blocks", [])
        if request.block_breakdown:
            block_breakdown = [item.model_dump() for item in request.block_breakdown]
        else:
            block_breakdown = calculate_block_breakdown(mapping(geom), blocks_for_breakdown)

        # Create sub-area object
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
            "isExcluded": request.is_excluded,
            "created_at": datetime.now(timezone.utc).isoformat()
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

        logger.info(f"[add_sub_area] Added sub-area {sub_area_id}, total now: {len(result_data['sub_areas'])}")

        # Recalculate total excluded area from scratch (avoids accumulation errors)
        excluded_total = calculate_total_excluded_area(result_data["sub_areas"])
        result_data["excluded_area_hectares"] = round(excluded_total, 4)

        # Recalculate effective_area_hectares at forest level
        total_area = result_data.get("area_hectares", 0)
        result_data["effective_area_hectares"] = round(total_area - excluded_total, 4)

        # Recalculate per-block excluded and effective areas (handles cross-block sub-areas)
        blocks = result_data.get("blocks", [])
        block_excluded_map = calculate_block_excluded_areas(blocks, result_data["sub_areas"])

        for block in blocks:
            block_id = block.get("block_id")
            block_excluded = block_excluded_map.get(block_id, 0.0)

            block["excluded_area_hectares"] = round(block_excluded, 4)
            original_area = block.get("area_hectares", 0)
            block["effective_area_hectares"] = round(original_area - block_excluded, 4)

        result_data["blocks"] = blocks

        # Update calculation
        calculation.result_data = result_data
        flag_modified(calculation, "result_data")
        db.commit()
        db.refresh(calculation)

        logger.info(f"[add_sub_area] Updated totals - excluded: {excluded_total:.4f} ha, effective: {result_data['effective_area_hectares']:.4f} ha")

        return SubAreaResponse(
            id=sub_area_id,
            name=request.name,
            category=request.category,
            geometry=mapping(geom),
            area_hectares=round(area_hectares, 4),
            block_id=new_sub_area.get("blockId") if not request.block_id else request.block_id,
            block_name=new_sub_area.get("blockName") if not request.block_name else request.block_name,
            block_breakdown=[BlockBreakdownItem(**item) for item in block_breakdown] if block_breakdown else None,
            is_excluded=request.is_excluded
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        db.rollback()
        logger.info(f"[add_sub_area] ERROR: {str(e)}")
        logger.info(f"[add_sub_area] Traceback:\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to add sub-area: {str(e)}"
        )


@router.get("/calculations/{calculation_id}/sub-areas", response_model=SubAreaListResponse)
def list_sub_areas(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get all sub-areas for a calculation.
    """
    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    # Get sub-areas from result_data
    result_data = calculation.result_data or {}
    sub_areas = result_data.get("sub_areas", [])
    
    logger.info(f"[list_sub_areas] Calculation {calculation_id}: found {len(sub_areas)} sub-areas in result_data")
    if sub_areas:
        logger.info(f"[list_sub_areas] First sub-area keys: {sub_areas[0].keys()}")
        logger.info(f"[list_sub_areas] First sub-area area_hectares: {sub_areas[0].get('area_hectares')}")
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
                except Exception as e:
                    logger.warning(f"Error loading WKB geometry: {e}")
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
                            "EPSG:4326", 
                            f"EPSG:{utm_srid}", 
                            always_xy=True
                        ).transform
                        geom_utm = transform(project, geom_obj)
                        sa_area = geom_utm.area / SQM_PER_HA
                        logger.info(f"[list_sub_areas] Recalculated area for {sa.get('name')}: {sa_area:.4f} ha")
                except Exception as e:
                    logger.info(f"[list_sub_areas] Error recalculating area: {e}")
        
        # Get blockBreakdown if exists
        block_breakdown = sa.get("blockBreakdown")
        block_breakdown_items = None
        if block_breakdown:
            from ..schemas.forest import BlockBreakdownItem
            block_breakdown_items = [
                BlockBreakdownItem(**item) if isinstance(item, dict) else item
                for item in block_breakdown
            ]

        sub_area_responses.append(SubAreaResponse(
            id=sa.get("id", ""),
            name=sa.get("name", ""),
            category=sa.get("category", ""),
            geometry=geometry_json,
            area_hectares=round(sa_area, 4),
            block_id=sa.get("blockId"),
            block_name=sa.get("blockName"),
            block_breakdown=block_breakdown_items,
            is_excluded=sa.get("isExcluded", False),
            style=sa.get("style"),
        ))
        total_area += sa_area

    return SubAreaListResponse(
        sub_areas=sub_area_responses,
        total_count=len(sub_area_responses),
        total_area_hectares=round(total_area, 4)
    )


@router.patch("/calculations/{calculation_id}/sub-areas/{sub_area_id}")
def update_sub_area(
    calculation_id: UUID,
    sub_area_id: str,
    request: SubAreaUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Update a sub-area's properties (name, category, geometry, etc.)
    """
    
    # Log incoming request for debugging
    logger.info(f"[update_sub_area] calculation_id={calculation_id}, sub_area_id={sub_area_id}")
    logger.info(f"[update_sub_area] request.name={request.name}")
    logger.info(f"[update_sub_area] request.geometry is not None: {request.geometry is not None}")
    if request.geometry:
        logger.info(f"[update_sub_area] request.geometry type: {request.geometry.get('type')}")
    logger.info(f"[update_sub_area] request.geometry: {str(request.geometry)[:500]}")

    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalculationErrors.NOT_FOUND
        )

    # Check structure lock (S14)
    if calculation.structure_locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "code": "structure_locked",
                "message": "Structure is locked — sub-area edits are disabled.",
                "message_np": "\u092f\u094b \u0938\u0902\u0930\u091a\u0928\u093e \u0932\u0915 \u0917\u0930\u093f\u090f\u0915\u094b \u091b \u2014 \u0909\u092a-\u0915\u094d\u0937\u0947\u0924\u094d\u0930 \u0938\u092e\u094d\u092a\u093e\u0926\u0928 \u0917\u0930\u094d\u0928 \u0938\u0915\u093f\u0902\u0926\u0948\u0928\u0964",
                "structure_locked_at": str(calculation.structure_locked_at) if calculation.structure_locked_at else None,
            },
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    # Get sub-areas from result_data
    result_data = calculation.result_data or {}
    sub_areas = result_data.get("sub_areas", [])

    # Debug: print all sub-area IDs for comparison
    logger.info(f"[update_sub_area] Looking for sub_area_id: '{sub_area_id}'")
    logger.info(f"[update_sub_area] Available sub-area IDs: {[sa.get('id') for sa in sub_areas]}")

    # Find the sub-area
    sub_area_found = False
    for i, sa in enumerate(sub_areas):
        sa_id = sa.get("id")
        logger.info(f"[update_sub_area] Comparing: '{sa_id}' == '{sub_area_id}' -> {sa_id == sub_area_id}")
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
                        detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
                    )
                sub_areas[i]["category"] = request.category
            if request.block_id is not None:
                sub_areas[i]["blockId"] = request.block_id
            if request.block_name is not None:
                sub_areas[i]["blockName"] = request.block_name
            if request.is_excluded is not None:
                sub_areas[i]["isExcluded"] = request.is_excluded
            # Per-feature style override (P3). `style` present + null clears it
            # back to the category colour; present + dict stores the subset.
            if "style" in request.model_fields_set:
                if request.style:
                    sub_areas[i]["style"] = {
                        k: request.style[k]
                        for k in ("fill", "fillOpacity", "stroke", "weight")
                        if k in request.style and request.style[k] is not None
                    } or None
                else:
                    sub_areas[i]["style"] = None
            if request.geometry is not None:
                try:
                    # Validate geometry
                    if not isinstance(request.geometry, dict):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Geometry must be a valid GeoJSON object"
                        )
                    if request.geometry.get("type") not in ["Polygon", "MultiPolygon"]:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Geometry type must be Polygon or MultiPolygon"
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
                                detail="Updated sub-area geometry is entirely within other sub-areas"
                            )
                        geom_shape = clipped_shape
                    sub_area_geojson = _mapping(geom_shape)
                    
                    # Update geometry
                    sub_areas[i]["geometry"] = sub_area_geojson
                    logger.info(f"[update_sub_area] Stored geometry in sub_areas[{i}]: {str(sub_area_geojson)[:200]}")
                    
                    # Always recalculate area from the new geometry (server is authoritative)
                    try:
                        area_sqm, area_ha = calculate_area_geodesic_from_shapely(geom_shape)
                        logger.info(f"[update_sub_area] Recalculated area: {area_sqm:.4f} sqm, {area_ha:.4f} ha")
                    except Exception as e2:
                        logger.info(f"[update_sub_area] Area calculation error: {e2}")
                        logger.exception("Failed to recalculate area for sub-area")
                        logger.warning(f"Failed to recalculate area for sub-area: {e2}")
                        # Rough deg² → ha conversion at Nepal's latitude (~28°N)
                        import math as _math
                        _clat = _math.cos(_math.radians(geom_shape.centroid.y))
                        area_ha = abs(geom_shape.area) * METERS_PER_DEGREE_LAT * METERS_PER_DEGREE_LAT * _clat / SQM_PER_HA
                        area_sqm = area_ha * SQM_PER_HA
                    
                    sub_areas[i]["area_sqm"] = round(area_sqm, 4)
                    sub_areas[i]["area_hectares"] = round(area_ha, 4)
                    
                    # Recalculate block breakdown for new geometry
                    blocks = result_data.get("blocks", [])
                    block_breakdown = calculate_block_breakdown(sub_area_geojson, blocks)
                    if block_breakdown:
                        sub_areas[i]["blockBreakdown"] = block_breakdown
                        # Update primary block assignment based on largest coverage
                        if block_breakdown:
                            primary = max(block_breakdown, key=lambda x: x.get("area", 0))
                            sub_areas[i]["blockId"] = primary.get("blockId")
                            sub_areas[i]["blockName"] = primary.get("blockName")
                                
                except Exception as e:
                    # If area calculation fails, log but continue
                    logger.info(f"[update_sub_area] Error in area calculation: {e}")
                    logger.exception("Failed to recalculate area for sub-area")
                    logger.warning(f"Failed to recalculate area for sub-area: {e}")

            sub_areas[i]["updated_at"] = datetime.now(timezone.utc).isoformat()
            break

    if not sub_area_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sub-area with ID {sub_area_id} not found"
        )

    # Save updated result_data
    result_data["sub_areas"] = sub_areas

    # Recalculate total excluded area from scratch (avoids accumulation errors)
    excluded_total = calculate_total_excluded_area(sub_areas)
    result_data["excluded_area_hectares"] = round(excluded_total, 4)

    # Recalculate effective_area_hectares at forest level
    total_area = result_data.get("area_hectares", 0)
    result_data["effective_area_hectares"] = round(total_area - excluded_total, 4)

    # Recalculate per-block excluded and effective areas (handles cross-block sub-areas)
    blocks = result_data.get("blocks", [])
    block_excluded_map = calculate_block_excluded_areas(blocks, sub_areas)

    for block in blocks:
        block_id = block.get("block_id")
        block_excluded = block_excluded_map.get(block_id, 0.0)

        block["excluded_area_hectares"] = round(block_excluded, 4)
        original_area = block.get("area_hectares", 0)
        block["effective_area_hectares"] = round(original_area - block_excluded, 4)

    result_data["blocks"] = blocks
    calculation.result_data = result_data
    flag_modified(calculation, "result_data")
    db.commit()
    db.refresh(calculation)
    
    # Verify saved data
    saved_result_data = calculation.result_data
    saved_sub_areas = saved_result_data.get("sub_areas", [])
    saved_sub_area = next((sa for sa in saved_sub_areas if sa.get("id") == sub_area_id), None)
    if saved_sub_area:
        logger.info(f"[update_sub_area] VERIFIED - saved geometry type: {saved_sub_area.get('geometry', {}).get('type')}")
        logger.info(f"[update_sub_area] VERIFIED - saved geometry coords exist: {'coordinates' in saved_sub_area.get('geometry', {})}")
        logger.info(f"[update_sub_area] VERIFIED - saved area_hectares: {saved_sub_area.get('area_hectares')}")
    else:
        logger.info(f"[update_sub_area] ERROR - sub_area not found after save!")

    return {
        "success": True,
        **i18n_success("success.sub_area_updated"),
        "sub_area": sub_areas[[i for i, sa in enumerate(sub_areas) if sa.get("id") == sub_area_id][0]]
    }


@router.delete("/calculations/{calculation_id}/sub-areas/{sub_area_id}")
def delete_sub_area(
    calculation_id: UUID,
    sub_area_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Delete a sub-area from a calculation.
    """
    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalculationErrors.NOT_FOUND
        )

    # Check structure lock (S14)
    if calculation.structure_locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "code": "structure_locked",
                "message": "Structure is locked — sub-area edits are disabled.",
                "message_np": "\u092f\u094b \u0938\u0902\u0930\u091a\u0928\u093e \u0932\u0915 \u0917\u0930\u093f\u090f\u0915\u094b \u091b \u2014 \u0909\u092a-\u0915\u094d\u0937\u0947\u0924\u094d\u0930 \u0938\u092e\u094d\u092a\u093e\u0926\u0928 \u0917\u0930\u094d\u0928 \u0938\u0915\u093f\u0902\u0926\u0948\u0928\u0964",
                "structure_locked_at": str(calculation.structure_locked_at) if calculation.structure_locked_at else None,
            },
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    # Get sub-areas from result_data
    result_data = calculation.result_data or {}
    sub_areas = result_data.get("sub_areas", [])

    # Find and remove the sub-area
    sub_area_found = False
    deleted_area = 0
    new_sub_areas = []

    for sa in sub_areas:
        if sa.get("id") == sub_area_id:
            sub_area_found = True
            deleted_area = sa.get("area_hectares", 0)
        else:
            new_sub_areas.append(sa)

    if not sub_area_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sub-area with ID {sub_area_id} not found"
        )

    # Save updated result_data
    result_data["sub_areas"] = new_sub_areas
    result_data["sub_areas_count"] = len(new_sub_areas)

    # ALSO delete from forest_sub_areas table (source of truth)
    from app.models.forest_sub_area import ForestSubArea
    try:
        sub_area_to_delete = db.query(ForestSubArea).filter(
            ForestSubArea.id == sub_area_id
        ).first()
        if sub_area_to_delete:
            db.delete(sub_area_to_delete)
            logger.info(f"[delete_sub_area] Also deleted from forest_sub_areas table")
    except Exception as e:
        logger.info(f"[delete_sub_area] Warning: Could not delete from forest_sub_areas table: {e}")

    # Recalculate total excluded area from scratch (avoids accumulation errors)
    excluded_total = calculate_total_excluded_area(new_sub_areas)
    result_data["excluded_area_hectares"] = round(excluded_total, 4)

    # Recalculate effective_area_hectares at forest level
    total_area = result_data.get("area_hectares", 0)
    result_data["effective_area_hectares"] = round(total_area - excluded_total, 4)

    # Recalculate per-block excluded and effective areas (handles cross-block sub-areas)
    blocks = result_data.get("blocks", [])
    block_excluded_map = calculate_block_excluded_areas(blocks, new_sub_areas)

    for block in blocks:
        block_id = block.get("block_id")
        block_excluded = block_excluded_map.get(block_id, 0.0)

        block["excluded_area_hectares"] = round(block_excluded, 4)
        original_area = block.get("area_hectares", 0)
        block["effective_area_hectares"] = round(original_area - block_excluded, 4)

    result_data["blocks"] = blocks
    calculation.result_data = result_data
    flag_modified(calculation, "result_data")
    db.commit()
    db.refresh(calculation)

    logger.info(f"[delete_sub_area] Deleted sub-area, new excluded total: {excluded_total:.4f} ha, effective: {result_data['effective_area_hectares']:.4f} ha")

    return {
        "success": True,
        "message": f"Sub-area deleted successfully. Removed {round(deleted_area, 4)} hectares."
    }


@router.patch("/admin/calculations/{calculation_id}/structure-lock")
def toggle_structure_lock(
    calculation_id: UUID,
    lock: bool = Query(True),
    reason: Optional[str] = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    SUPER_ADMIN endpoint to toggle structure_locked on a calculation.
    Unlocking requires a reason.
    Uses state machine (S14) for validated transitions and audit trail.
    """
    from ..services.structure_lock_service import (
        apply_structure_lock_transition,
        LockTransition,
    )

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc:
        raise HTTPException(status_code=404, detail="Calculation not found")

    transition = LockTransition.DFO_UNLOCK if not lock else LockTransition.MANUAL_LOCK
    result = apply_structure_lock_transition(
        calculation=calc,
        transition=transition,
        db=db,
        current_user=current_user,
        reason_np=reason,
    )

    db.commit()
    return {
        "calculation_id": str(calculation_id),
        "structure_locked": result["to_state"],
        "transition": result["transition"],
        "audit_id": result["audit_id"],
        "unlocked_by": str(current_user.id) if not lock else None,
        "unlocked_at": str(calc.structure_locked_at) if calc.structure_locked_at else None,
    }


# ============================================================================
# LEGACY: interactive boundary editing endpoint (kept for backward compat)
# ============================================================================


@router.post("/calculations/{calculation_id}/edit-boundary")
async def edit_boundary_interactive(
    calculation_id: UUID,
    request: dict,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Interactive boundary editing endpoint.

    # NOTE: edit-boundary is the interactive alternative to direct PATCH /geometry
    # constraint: all operations validated server-side via Shapely before persistence
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
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.ops import unary_union

    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()

    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    operation = request.get("operation", "add_polygon")
    features = request.get("features", [])
    reanalyze = request.get("reanalyze", True)

    try:
        # Get current boundary geometry
        if calculation.boundary_geom:
            geom_wkb = db.execute(
                text("SELECT ST_AsEWKB(:geom) as geom"),
                {"geom": calculation.boundary_geom}
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
                detail="No boundary geometry found for this calculation"
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
                    detail="Cannot remove single polygon - use update_geometry instead"
                )

        elif operation == "merge":
            # Merge all polygons into one
            if current_geom.geom_type == "MultiPolygon":
                current_geom = unary_union(current_geom)

        elif operation == "split_polygon":
            from app.services.geometry_splitter import (
                split_polygon_with_line,
                validate_split_pieces,
                SplitValidationError,
            )

            cut_line_geojson = request.get("cut_line")
            if not cut_line_geojson:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="split.requires_cut_line"
                )

            cut_line = shape(cut_line_geojson)
            if cut_line.geom_type != "LineString":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="split.cut_must_be_linestring"
                )

            if cut_line.length < 0.00001:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="split.cut_line_too_short"
                )

            target_index = request.get("target_index", 0)

            if current_geom.geom_type == "MultiPolygon":
                polygons = list(current_geom.geoms)
                if target_index < 0 or target_index >= len(polygons):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"split.invalid_target_index: must be 0-{len(polygons)-1}"
                    )
                target_polygon = polygons[target_index]
            else:
                target_polygon = current_geom
                polygons = [current_geom]

            try:
                pieces = split_polygon_with_line(target_polygon, cut_line)
            except SplitValidationError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )

            validation = validate_split_pieces(pieces)
            if not validation["valid"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=validation["error"],
                )

            if current_geom.geom_type == "MultiPolygon":
                remaining = [p for i, p in enumerate(polygons) if i != target_index]
                current_geom = MultiPolygon(remaining + pieces)
            else:
                current_geom = MultiPolygon(pieces) if len(pieces) > 1 else pieces[0]

            piece_features = []
            for i, piece in enumerate(pieces):
                piece_features.append({
                    "type": "Feature",
                    "geometry": mapping(piece),
                    "properties": {
                        "id": f"{str(calculation_id)}_{target_index}_piece_{i}",
                        "piece_index": i,
                        "area_hectares": round(piece.area / SQM_PER_HA, 4),
                        "original_target_index": target_index,
                    },
                })

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown operation: {operation}"
            )

        # Make geometry valid
        if not current_geom.is_valid:
            current_geom = current_geom.buffer(0)

        # Calculate new area
        area_sqm = current_geom.area
        area_hectares = area_sqm / SQM_PER_HA

        # Update boundary geometry in database
        update_query = text("""
            UPDATE public.calculations
            SET boundary_geom = ST_GeomFromText(:wkt, 4326)
            WHERE id = :calc_id
        """)

        db.execute(update_query, {
            "wkt": current_geom.wkt,
            "calc_id": str(calculation_id)
        })

        # Update result_data
        result_data = calculation.result_data or {}
        result_data["boundary_edited"] = True
        result_data["boundary_edit_operation"] = operation
        result_data["new_area_hectares"] = round(area_hectares, 4)
        calculation.result_data = result_data
        flag_modified(calculation, "result_data")

        db.commit()

        # Optionally run re-analysis
        if reanalyze:
            calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
            calculation.status = CalculationStatus.PROCESSING
            db.commit()

            analysis_options = calculation.analysis_options or {}

            try:
                analysis_results, processing_time = await analyze_forest_boundary(
                    calculation_id, db, options=analysis_options
                )

                # Preserve blocks and sub-areas
                blocks_data = result_data.get('blocks', [])
                sub_areas = result_data.get('sub_areas', [])

                updated_result_data = {
                    'blocks': blocks_data,
                    'sub_areas': sub_areas,
                    'boundary_edited': True,
                    'boundary_edit_operation': operation,
                    'new_area_hectares': round(area_hectares, 4),
                    **analysis_results
                }

                update_result_query = text("""
                    UPDATE public.calculations
                    SET
                        result_data = CAST(:result_data AS jsonb),
                        processing_time_seconds = :processing_time,
                        status = :status,
                        completed_at = NOW()
                    WHERE id = :calc_id
                """)

                db.execute(update_result_query, {
                    "result_data": json.dumps(updated_result_data),
                    "processing_time": processing_time,
                    "status": "COMPLETED",
                    "calc_id": str(calculation_id)
                })

                db.commit()
            except Exception as e:
                logger.info(f"Re-analysis failed after boundary edit: {e}")
                calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
                calculation.status = CalculationStatus.COMPLETED
                db.commit()

        # Get updated geometry
        geojson_query = db.query(
            func.ST_AsGeoJSON(Calculation.boundary_geom).label("geojson")
        ).filter(Calculation.id == calculation_id).first()

        geometry_json = json.loads(geojson_query.geojson) if geojson_query and geojson_query.geojson else None

        return {
            "success": True,
            "message": f"Boundary {operation} completed" + (" and re-analysis done" if reanalyze else ""),
            "calculation_id": str(calculation_id),
            "new_area_hectares": round(area_hectares, 4),
            "geometry": geometry_json
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to edit boundary: {str(e)}"
        )


# ============================================================================
# CONSOLIDATED EDIT-BOUNDARY ENDPOINT (merge, rename_feature, buffer_operation)
# ============================================================================


def _check_structure_not_locked(calculation):
    """Raise 423 if the calculation's structure is locked."""
    if calculation.structure_locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "error": "structure_locked",
                "message": "Forest structure is locked because the Operational Plan has been submitted. Contact DFO to unlock.",
                "code": "geometry.locked.structure_locked",
            },
            headers={"X-Locked-Reason": "OP submitted"},
        )


@router.post("/calculations/{calculation_id}/edit-boundary")
def edit_boundary(
    calculation_id: UUID,
    request: Dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Unified geometry mutation endpoint.
    Operations: split_polygon, merge, rename_feature, buffer_operation
    """
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc:
        raise HTTPException(status_code=404, detail="Calculation not found")

    operation = request.get("operation")
    if not operation:
        raise HTTPException(status_code=400, detail="edit.requires_operation")

    _check_structure_not_locked(calc)

    if operation == "merge":
        return _handle_merge(calculation_id, request, db, current_user)
    elif operation == "rename_feature":
        return _handle_rename_feature(calculation_id, request, db, current_user)
    elif operation == "buffer_operation":
        return _handle_buffer_operation(calculation_id, request, db, current_user)
    elif operation == "split_polygon":
        from .geometry import handle_split_polygon
        return handle_split_polygon(calculation_id, request, db, current_user)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"edit.unknown_operation: {operation}"
        )


def _handle_merge(calculation_id: UUID, request: Dict, db: Session, current_user: User):
    target_ids = request.get("target_feature_ids", [])
    feature_type = request.get("feature_type", "block")
    keep_from = request.get("keep_properties_from", "largest")

    if len(target_ids) < 2:
        raise HTTPException(status_code=400, detail="edit.merge_requires_two")

    if feature_type == "block":
        features = (
            db.query(ForestBlock)
            .filter(ForestBlock.id.in_(target_ids), ForestBlock.calculation_id == calculation_id)
            .all()
        )
    elif feature_type == "sub_area":
        calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        if not calc:
            raise HTTPException(status_code=404, detail="Calculation not found")
        sub_areas = (calc.result_data or {}).get("sub_areas", [])
        features = [sa for sa in sub_areas if sa.get("id") in target_ids]
    else:
        raise HTTPException(status_code=400, detail=f"Unknown feature_type: {feature_type}")

    if len(features) < 2:
        raise HTTPException(status_code=400, detail="edit.merge_targets_not_found")

    polygons = []
    for feat in features:
        geom = shape(feat.geometry) if hasattr(feat, 'geometry') else shape(feat["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        polygons.append(geom)

    merged = unary_union(polygons)
    if merged.is_empty or merged.area < 0.0001:
        raise HTTPException(status_code=400, detail="edit.merge_result_empty")

    if merged.geom_type == "MultiPolygon" and len(merged.geoms) == 1:
        merged = list(merged.geoms)[0]

    if keep_from == "largest":
        largest_idx = max(range(len(polygons)), key=lambda i: polygons[i].area)
        source_feature = features[largest_idx]
    else:
        source_feature = features[0]

    source_name = (
        source_feature.name if hasattr(source_feature, 'name')
        else source_feature.get("name", "Merged")
    )

    merged_geojson = {
        "type": "Feature",
        "geometry": mapping(merged),
        "properties": {
            "name": f"{source_name}_merged",
            "area_hectares": round(merged.area / 10000, 4),
            "merged_from": target_ids,
            "feature_type": feature_type,
        },
    }

    log_geometry_audit(
        db=db,
        calculation_id=str(calculation_id),
        layer_type="blocks" if feature_type == "block" else "sub_areas",
        operation="MERGE",
        feature_id="+".join(str(t) for t in target_ids),
        previous_geometry={"type": "FeatureCollection", "features": [mapping(p) for p in polygons]},
        new_geometry=merged_geojson,
        user_id=str(current_user.id),
    )

    if feature_type == "block":
        for block in features:
            db.delete(block)
        merged_block = ForestBlock(
            calculation_id=calculation_id,
            geometry=merged,
            name=merged_geojson["properties"]["name"],
        )
        db.add(merged_block)
        db.flush()
        merged_geojson["properties"]["id"] = str(merged_block.id)
        # BA-4: reconcile the block snapshot after merging blocks so the next
        # analysis / legacy view reflects the merge.
        calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        from ..services.block_reconcile_service import reconcile_blocks_from_db
        reconcile_blocks_from_db(db, calc)

    db.commit()
    return merged_geojson


def _handle_rename_feature(calculation_id: UUID, request: Dict, db: Session, current_user: User):
    feature_id = request.get("feature_id")
    new_name = request.get("new_name", "").strip()
    feature_type = request.get("feature_type", "block")

    if not new_name:
        raise HTTPException(status_code=400, detail="edit.no_name_empty")
    if not feature_id:
        raise HTTPException(status_code=400, detail="edit.no_feature_id")

    previous_name = None
    previous_geom = None

    if feature_type == "block":
        block = db.query(ForestBlock).filter(
            ForestBlock.id == feature_id,
            ForestBlock.calculation_id == calculation_id,
        ).first()
        if not block:
            raise HTTPException(status_code=404, detail="Block not found")
        previous_name = block.name
        previous_block_name = block.block_name
        previous_geom = mapping(block.geometry)

        duplicate = db.query(ForestBlock).filter(
            ForestBlock.calculation_id == calculation_id,
            ForestBlock.name == new_name,
            ForestBlock.id != feature_id,
        ).first()
        if duplicate:
            raise HTTPException(status_code=400, detail="edit.duplicate_name")

        block.name = new_name
        from ..services.forest_units.write import keep_code_in_step

        keep_code_in_step(block, previous_name, previous_block_name)

    elif feature_type == "sub_area":
        calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        if not calc:
            raise HTTPException(status_code=404, detail="Calculation not found")
        result_data = dict(calc.result_data or {})
        sub_areas = list(result_data.get("sub_areas", []))
        target = None
        for sa in sub_areas:
            if sa.get("id") == feature_id:
                target = sa
                break
        if not target:
            raise HTTPException(status_code=404, detail="Sub-area not found")
        previous_name = target.get("name")
        previous_geom = target.get("geometry")

        for sa in sub_areas:
            if sa.get("name") == new_name and sa.get("id") != feature_id:
                raise HTTPException(status_code=400, detail="edit.duplicate_name")

        target["name"] = new_name
        result_data["sub_areas"] = sub_areas
        calc.result_data = result_data
    else:
        raise HTTPException(status_code=400, detail=f"Unknown feature_type: {feature_type}")

    log_geometry_audit(
        db=db,
        calculation_id=str(calculation_id),
        layer_type="blocks" if feature_type == "block" else "sub_areas",
        operation="RENAME",
        feature_id=feature_id,
        previous_geometry={"name": previous_name},
        new_geometry={"name": new_name},
        user_id=str(current_user.id),
    )

    db.commit()
    return {"success": True, "feature_id": feature_id, "new_name": new_name}


def _handle_buffer_operation(calculation_id: UUID, request: Dict, db: Session, current_user: User):
    feature_id = request.get("feature_id")
    feature_type = request.get("feature_type", "block")
    distance_meters = request.get("distance_meters", 0)
    steps = request.get("steps", 8)
    preview_only = request.get("preview_only", False)

    if abs(distance_meters) < 0.1:
        raise HTTPException(status_code=400, detail="edit.buffer_distance_too_small")

    if feature_type == "block":
        block = db.query(ForestBlock).filter(ForestBlock.id == feature_id).first()
        if not block:
            raise HTTPException(status_code=404, detail="Block not found")
        geom = block.geometry
        original_geom = mapping(geom)
    elif feature_type == "sub_area":
        calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        if not calc:
            raise HTTPException(status_code=404, detail="Calculation not found")
        sub_areas = (calc.result_data or {}).get("sub_areas", [])
        target = next((sa for sa in sub_areas if sa.get("id") == feature_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Sub-area not found")
        geom = shape(target["geometry"])
        original_geom = target["geometry"]
    else:
        raise HTTPException(status_code=400, detail=f"Unknown feature_type: {feature_type}")

    buffered = geom.buffer(distance_meters / 111320, steps)

    if buffered.is_empty or buffered.area < 0.000001:
        raise HTTPException(status_code=400, detail="edit.buffer_result_empty")

    if not buffered.is_valid:
        buffered = buffered.buffer(0)

    if feature_type == "sub_area":
        block_id = target.get("block_id")
        block = db.query(ForestBlock).filter(ForestBlock.id == block_id).first()
        if block:
            buffered = buffered.intersection(block.geometry)
            if buffered.is_empty:
                raise HTTPException(status_code=400, detail="edit.buffer_clipped_away")

    if preview_only:
        return {
            "preview": True,
            "original_area_ha": round(geom.area / 10000, 4),
            "buffered_area_ha": round(buffered.area / 10000, 4),
            "geometry": mapping(buffered),
        }

    if feature_type == "block":
        block.geometry = buffered
    elif feature_type == "sub_area":
        new_data = dict(calc.result_data or {})
        for sa in new_data.get("sub_areas", []):
            if sa.get("id") == feature_id:
                sa["geometry"] = mapping(buffered)
                sa["area_hectares"] = round(buffered.area / 10000, 4)
                break
        calc.result_data = new_data

    log_geometry_audit(
        db=db,
        calculation_id=str(calculation_id),
        layer_type="blocks" if feature_type == "block" else "sub_areas",
        operation="BUFFER",
        feature_id=feature_id,
        previous_geometry=original_geom,
        new_geometry=mapping(buffered),
        user_id=str(current_user.id),
    )

    db.commit()
    return {
        "success": True,
        "geometry": mapping(buffered),
        "area_ha": round(buffered.area / 10000, 4),
    }
