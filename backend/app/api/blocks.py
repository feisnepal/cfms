"""
Block management endpoints — CRUD, bulk update, recalculate areas, Table 5.
Extracted from forests.py
# business: CFMG — blocks are management units, 5-25 ha each
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, text, select
from sqlalchemy.orm.attributes import flag_modified
from typing import Optional, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime, timezone
import json
import logging
from shapely.geometry import shape as shapely_shape

from ..core.database import get_db
from ..models.user import User
from ..models.calculation import Calculation, CalculationStatus
from ..models.forest_block import ForestBlock
from ..services.forest_units.model import DEPTH_TOP_BLOCK
from ..services.block_reconcile_service import reconcile_compartments_from_db
from ..models.field_inventory import (
    FieldInventoryCalculation,
    FieldInventoryBlockSummary,
    FieldInventorySamplePlot,
)
from ..schemas.forest import (
    BlockCreateListRequest,
    BlockResponse,
    BlockRenameRequest,
    BlockListResponse,
    BlockPolygonResponse,
    BlockPolygonListResponse,
    BlockAreaDetailItem,
    BlockAreaDetailResponse,
)
from app.core.errors import CalculationErrors
from ..core.exceptions import i18n_error, i18n_success
from ..utils.auth import get_current_active_user
from ..utils.authz import is_owner_or_admin
from ..services.tree_cover_analysis import calculate_block_area_details
from ..utils.geometry_utils import (
    calculate_area_geodesic,
    compute_geometry_properties,
    strip_geo_fields,
)
from ..core.geo import calculate_utm_epsg
from ..core.sub_area_kinds import is_strip, real_sub_areas
from ..core.constants import SQM_PER_HA
from .forests import calculate_block_excluded_areas, calculate_total_excluded_area
from ..services.sub_area_service import compute_block_breakdown, clip_against_existing

logger = logging.getLogger(__name__)

router = APIRouter()


# business: polygon extraction from MultiPolygon boundary for block naming
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
        raise i18n_error(403, "blocks.not_authorized_calculation")

    # Check if boundary geometry exists
    if not calculation.boundary_geom:
        raise i18n_error(400, "blocks.no_boundary_geometry_calculation")

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
            block_name = block.get("block_name", f"B{i+1}")

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
                            poly_index, f"B{poly_index + 1}"
                        ),
                    )
                )
                poly_index += 1
        except Exception as e:
            logger.error(f"Error extracting polygon {i}: {e}")
            continue

    logger.info(f"Extracted {len(polygons)} polygons from calculation {calculation_id}")

    return BlockPolygonListResponse(polygons=polygons, total_count=len(polygons))


# business: single-block mode for non-partitioned forests
# NOTE: duplicated in forests.py::create_single_default_block, which is the
# copy mounted at /api/forests/... that the frontend actually calls. Keep the
# blocks_cleared_by_user reset (BL-4) in sync between the two.
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
        raise i18n_error(400, "blocks.no_geometry")

    # 4. Calculate area in hectares (UTM zone auto-selected from the boundary centroid)
    # NOTE (BL-4 fix, 2026-08-29): db.scalar() on a two-column select() only
    # ever returns the FIRST column — see forests.py::create_single_default_block
    # for the full note. Use execute().first() to get both columns back.
    centroid = db.execute(
        select(
            func.ST_X(func.ST_Centroid(calculation.boundary_geom)),
            func.ST_Y(func.ST_Centroid(calculation.boundary_geom)),
        )
    ).first()
    if centroid and centroid[0] is not None:
        centroid_lon, centroid_lat = tuple(centroid)
    else:
        centroid_lon, centroid_lat = 85.0, 27.0
    utm_srid_area = calculate_utm_epsg(centroid_lon, centroid_lat)
    area_hectares = db.scalar(
        select(
            func.ST_Area(func.ST_Transform(calculation.boundary_geom, utm_srid_area))
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
    # second JSONB shape here. (Keep in lockstep with forests.py's copy.)
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


# constraint: each polygon becomes one forest block, minimum 1 ha
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
        raise i18n_error(403, "blocks.not_authorized_calculation")

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
            raise i18n_error(
                404, "blocks.polygon_index_not_found", index=block_req.polygon_index
            )

        if not polygon_query.area_hectares or polygon_query.area_hectares <= 0:
            raise i18n_error(
                400,
                "blocks.polygon_index_invalid_area",
                index=block_req.polygon_index,
                area=polygon_query.area_hectares,
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
        if geojson_result and geojson_result.geojson:
            try:
                geom_shape = shapely_shape(json.loads(geojson_result.geojson))
                geo_props = compute_geometry_properties(geom_shape)
            except Exception:
                logger.warning(
                    "derived geometry properties unavailable - area and perimeter "
                    "omitted for this block",
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
        raise i18n_error(403, "blocks.not_authorized_calculation")

    # FS-1c.1: migration 094 puts top-level compartments at the same depth as top-level blocks, so
    # `is_compartment` (the branch) is now required here too - this endpoint is "GET the blocks", not
    # "GET everything at depth 1" (I10). In lockstep with the duplicate endpoint in api/forests.py.
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
    _fi = (
        db.query(FieldInventoryCalculation)
        .filter(FieldInventoryCalculation.calculation_id == calculation_id)
        .first()
    )
    condition_by_name: dict = {}
    if _fi:
        for _name, _cond in (
            db.query(
                FieldInventoryBlockSummary.block_name,
                FieldInventoryBlockSummary.forest_condition,
            )
            .filter(
                FieldInventoryBlockSummary.field_inventory_calculation_id == _fi.id,
                FieldInventoryBlockSummary.forest_condition.isnot(None),
            )
            .all()
        ):
            if _name:
                condition_by_name[_name] = _cond

    block_responses = []
    total_area = 0.0

    for block in blocks:
        geojson_result = db.query(
            func.ST_AsGeoJSON(block.geometry).label("geojson")
        ).first()

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


@router.put("/calculations/{calculation_id}/boundary")
def update_boundary_geometry(
    calculation_id: UUID,
    request: dict,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    # NOTE: updates boundary and recalculates all block geometries
    """
    Update the forest boundary geometry.

    Allows users to edit the boundary polygon after initial creation.
    Updates both the boundary_geom in database and the geometry in result_data.
    """
    from shapely.geometry import shape, mapping
    from geoalchemy2.shape import from_shape
    import json

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
        raise i18n_error(400, "blocks.geometry_required")

    # VR-3 / Rule A — the boundary is editable only while no structural feature
    # exists.  Gated on BOTH write paths: `edit-geometry` carries the vertex
    # tool, this one carries draw/import/undo, and a rule enforced on one route
    # only is not enforced at all.
    #
    # Scope: a boundary RESHAPE.  Setting the first boundary, or re-sending the
    # same shape, is untouched — the check is skipped when the geometry is
    # unchanged, so idempotent saves and area-only updates still work.
    from app.services import vertex_guard_service as _guard

    if calculation.boundary_geom is not None and _guard.has_structural_features(
        db, calculation
    ):
        from shapely.geometry import shape as _shape
        from geoalchemy2.shape import to_shape as _to_shape

        if _guard.boundary_shape_changed(
            _to_shape(calculation.boundary_geom), _shape(geometry)
        ):
            raise i18n_error(409, "blocks.boundary_locked_by_structure")

    try:
        # Convert GeoJSON to PostGIS geometry
        geom_shape = shape(geometry)
        # Forest-boundary rules (within Nepal · ≤ 1000 ha · ≤ 40% built-up +
        # cropland · protected-area / Buffer Zone). This legacy handler writes
        # raw, bypassing persist_boundary's gate.
        from app.services.boundary_validation import (
            enforce_boundary_rules,
            BoundaryRulesViolation,
        )

        try:
            _bv = enforce_boundary_rules(
                db, geom_shape.wkt, forest_name=calculation.forest_name
            )
        except BoundaryRulesViolation as bv:
            raise HTTPException(status_code=422, detail=bv.detail)
        if _bv.clipped:  # R1 trimmed an out-of-Nepal part
            from shapely.wkt import loads as _wkt_loads

            geom_shape = _wkt_loads(_bv.effective_wkt)
            geometry = mapping(geom_shape)
        geom_wkb = from_shape(geom_shape, srid=4326)

        # Update boundary_geom
        calculation.boundary_geom = geom_wkb

        from app.services.boundary_pieces_service import sync_boundary_pieces

        sync_boundary_pieces(db, calculation, geom_shape)

        # Update result_data
        result_data = calculation.result_data or {}
        result_data["geometry"] = geometry
        result_data["area_hectares"] = request.get("area_hectares", 0)
        result_data["boundary_validation"] = _bv.report.as_dict()
        calculation.result_data = result_data

        flag_modified(calculation, "result_data")

        # U-6 Task 6.3 single-block forest: REMOVED (FS-2.4/FS-2.8 + C1-C3 / Q5 —
        # "no automatic single block for a new forest"). The boundary is never
        # silently minted into a block on save; creating the first unit is the
        # user's explicit choice in whichever stream they work in (blocks OR
        # compartments), e.g. via createSingleBlock / the workspace's
        # whole-forest auto-create or root-divide tools.
        db.commit()
        calculation.geometry_version = (calculation.geometry_version or 0) + 1
        db.commit()

        logger.info(
            f"[update-boundary] Updated boundary for calculation {calculation_id}"
        )

        return {
            "success": True,
            **i18n_success("blocks.boundary_updated"),
            "area_hectares": result_data["area_hectares"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.info(f"[update-boundary] Error: {e}")
        raise i18n_error(500, "blocks.failed_update_boundary", error=str(e))


# why: renaming block cascades to field inventory + sub-areas for data consistency
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

    ATTRIBUTE-ONLY endpoint (Phase E-1 single-authority): geometry edits are
    routed exclusively through POST /calculations/{id}/geometry/edit-geometry.
    Legacy clients that still send `geometry` get a 400 so the validated
    pipeline is never bypassed (review-fix #8).

    Phase C (auto-block): accepts a JSON body ``BlockRenameRequest`` with
    ``name`` / ``block_name`` / ``natural_name``. ``name`` is the display name
    and mirrors ``block_name`` unless ``block_name`` is provided explicitly.
    A legacy ``?name=`` query param is still honoured (kept for old clients).
    """
    # NOTE: `name` is a query parameter today. A body geometry dict is
    # impossible to smuggle here, but guard defensively anyway.
    if request and getattr(request, "geometry", None):
        raise i18n_error(400, "blocks.geometry_edits_not_allowed")
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if calculation.user_id != current_user.id:
        raise i18n_error(403, "blocks.not_authorized_calculation")

    block = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.id == block_id, ForestBlock.calculation_id == calculation_id
        )
        .first()
    )

    if not block:
        raise i18n_error(404, "blocks.forest_division_not_found")

    # Resolve new names: legacy `name` query param wins over nothing; the body
    # is the preferred source. `name` mirrors `block_name` when the latter is
    # the auto-generated serial and only `name` was provided.
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
        raise i18n_error(400, "blocks.name_required")

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

    # Per-feature style override (P3): present + dict → store the
    # {fill, fillOpacity, stroke, weight} subset; present + null → clear.
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
    effective_name = new_name or new_block_name

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
            logger.info(
                f"[update_block] Failed to sync field inventory block name: {e}"
            )

    db.commit()
    db.refresh(block)

    geojson_result = db.query(
        func.ST_AsGeoJSON(block.geometry).label("geojson")
    ).first()

    # DB-persisted columns only (populated at commit by auto_block_service._apply_management_orientation),
    # so the values are stable and match what was shown at commit time.
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
        # Raw NASA class 0-3 incl. non-forest, so a NULL above is explicable
        # (RS-2.14). getattr: a block row read before migration 106 has no such
        # attribute on a stale identity-map instance.
        dominant_nasa_code=getattr(block, "dominant_nasa_code", None),
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


# business: deleting a block removes it from result_data + cascade
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
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if calculation.user_id != current_user.id:
        raise i18n_error(403, "blocks.not_authorized_calculation")

    block = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.id == block_id, ForestBlock.calculation_id == calculation_id
        )
        .first()
    )

    if not block:
        raise i18n_error(404, "blocks.forest_division_not_found")

    if not confirm_children:
        from ..services.forest_units.operations.reparent import child_count

        n = child_count(db, block.id)
        if n > 0:
            raise i18n_error(409, "blocks.has_children_confirm_required", count=n)

    was_compartment = bool(getattr(block, "is_compartment", False))
    # Owner report 2026-10-02: collected BEFORE the delete below -- the
    # rows (and their raster_layer_id) are gone afterward. Every
    # descendant, any depth, same BFS `compartments.py::delete_compartment`
    # uses, since a cascade delete here can remove more than just `block`
    # itself.
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

    Duplicate of ``forests.py::_clear_stale_result_data_units`` — kept in sync so
    either mount of ``DELETE .../blocks/{id}`` behaves the same. Those arrays are
    the legacy *upload-mode* structure store; once a forest is edited in the
    workspace the ``forest_blocks`` table is authoritative, and a stale array
    left behind by a since-deleted division otherwise shadows the current
    structure — e.g. sampling generated against deleted compartments (covering
    only part of the forest).
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


# NOTE: frontend editor syncs outer vertices with forest boundary
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

    logger.info(f"\n[update_blocks_geometry] calculation_id={calculation_id}")

    # Phase E-1 single-authority (review-fix #8): geometry writes route through
    # POST /calculations/{id}/geometry/edit-geometry.  Reject any legacy body
    # that still carries `geometry` so the validated pipeline is never bypassed.
    legacy_geometry = [
        b.get("geometry")
        for b in request.get("blocks", [])
        if isinstance(b, dict) and b.get("geometry") is not None
    ]
    if legacy_geometry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use POST /calculations/{id}/geometry/edit-geometry for geometry edits — "
            "this endpoint is attribute-only (Phase E-1 single-authority).",
        )

    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND
        )

    # Check ownership
    if calculation.user_id != current_user.id:
        raise i18n_error(403, "blocks.not_authorized_calculation")

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
            logger.info(f"[update_blocks_geometry] Error calculating area: {e}")
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
                    else f"B{len(updated_blocks)+1}"
                ),
            ),
            "geometry": geometry,
            "area_hectares": round(new_area, 4),
            "index": block_data.get("index", len(updated_blocks)),
            **geo_props,
        }

        # Preserve centroid if exists (legacy; geo_centroid_lat/lng replaces it)
        if existing and "centroid" in existing:
            updated_block["centroid"] = existing["centroid"]
        else:
            try:
                centroid = geom.centroid
                updated_block["centroid"] = {"lon": centroid.x, "lat": centroid.y}
            except Exception as e:
                logger.warning(f"Error calculating centroid for block: {e}")

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
                # drifts from the piece table, same as every other write site.
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
            logger.info(f"[update_blocks_geometry] Error updating boundary: {e}")
            logger.exception("Failed to update forest boundary")

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
        if is_strip(sub_area):
            continue  # a strip crosses blocks by design; it is clipped to the forest area, never to one block

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
                logger.info(
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
                    clipped_area = abs(clipped.area) / SQM_PER_HA  # hectares
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
                logger.info(f"[update_blocks_geometry] Error clipping sub-area: {e}")

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
    # (FS-1b.4a, in lockstep with the duplicate endpoint in api/forests.py): also bumps
    # geometry_version (this endpoint never had before) and marks downstream data stale.
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
        **i18n_success(
            "blocks.blocks_updated",
            blocks=len(updated_blocks),
            clipped=len(clipped_sub_areas),
        ),
    }


@router.post("/calculations/{calculation_id}/clip-sub-areas")
def clip_sub_areas_to_blocks(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Clip all sub-areas to fit within their containing blocks.
    Called after block geometry editing to ensure sub-areas
    don't extend outside block boundaries.

    Returns summary of clipped sub-areas.
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    if calculation.user_id != current_user.id:
        raise i18n_error(403, "blocks.not_authorized")

    result_data = calculation.result_data or {}
    blocks = result_data.get("blocks", [])
    sub_areas = result_data.get("sub_areas", [])

    if not blocks:
        raise i18n_error(400, "blocks.no_blocks_defined")

    clipped = []
    for sa in sub_areas:
        sa_geom = sa.get("geometry")
        if not sa_geom:
            continue
        if is_strip(sa):
            continue  # clipped to the forest area by the strip service, not to the blocks

        from shapely.geometry import shape as shp, mapping as mpp
        from shapely.ops import unary_union

        block_union = unary_union(
            [shp(b["geometry"]) for b in blocks if b.get("geometry")]
        )
        if block_union.is_empty:
            continue

        geom = shp(sa_geom)
        clipped_geom = geom.intersection(block_union)

        if clipped_geom.is_empty:
            clipped.append(
                {
                    "id": sa.get("id"),
                    "name": sa.get("name"),
                    "clipped": True,
                    "area_ha": 0,
                }
            )
            sa["geometry"] = None
            sa["area_hectares"] = 0
            sa["area_sqm"] = 0
        elif clipped_geom.area < geom.area * 0.999:
            sa["geometry"] = mpp(clipped_geom)
            area_ha = clipped_geom.area / SQM_PER_HA
            sa["area_hectares"] = round(area_ha, 4)
            sa["area_sqm"] = round(area_ha * SQM_PER_HA, 4)
            clipped.append(
                {
                    "id": sa.get("id"),
                    "name": sa.get("name"),
                    "clipped": True,
                    "area_ha": round(area_ha, 4),
                }
            )

    result_data["sub_areas"] = [
        sa for sa in sub_areas if sa.get("geometry") is not None
    ]

    excluded_total = calculate_total_excluded_area(result_data["sub_areas"])
    result_data["excluded_area_hectares"] = round(excluded_total, 4)
    total_area = result_data.get("area_hectares", 0)
    result_data["effective_area_hectares"] = round(total_area - excluded_total, 4)

    calculation.result_data = result_data
    flag_modified(calculation, "result_data")
    db.commit()

    return {
        "success": True,
        "clipped_count": len(clipped),
        "clipped": clipped,
        "remaining_count": len(result_data["sub_areas"]),
    }


# business: Table 5 — block-wise area breakdown for official reports
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
        raise i18n_error(403, "blocks.not_authorized_calculation")

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
            # Recompute geo_* properties from block geometry
            try:
                block_shape = shapely_shape(wkb.loads(bytes(block.geometry.data)))
                geo_props = compute_geometry_properties(block_shape)
                # Store geo props in result_data block entry (found later by name match)
            except Exception:
                logger.exception(
                    "derived properties unavailable for block %s - they are left out "
                    "of result_data, so the block shows no area",
                    getattr(block, "name", "?"),
                )

    db.commit()

    # Recalculate sub-area areas in result_data
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
                    # Recompute geo_* properties from block geometry
                    try:
                        block_shape = shapely_shape(
                            wkb.loads(bytes(db_block.geometry.data))
                        )
                        geo_props = compute_geometry_properties(block_shape)
                        for k, v in geo_props.items():
                            block_data[k] = v
                    except Exception:
                        logger.exception(
                            "derived properties unavailable for block %s - its area and "
                            "perimeter are absent from the response",
                            getattr(db_block, "name", "?"),
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
        **i18n_success(
            "blocks.areas_recalculated",
            blocks=recalculated_blocks,
            subareas=recalculated_subareas,
        ),
        "blocks_updated": recalculated_blocks,
        "sub_areas_updated": recalculated_subareas,
        "total_excluded_area": round(excluded_total, 4),
    }


# ============================================
# TABLE 5: Block Area Detail Endpoint
# ============================================


# business: Table 5 endpoint — official area breakdown report
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
        raise i18n_error(403, "blocks.permission_denied")

    # Get analysis units from result_data — compartments when the forest was
    # divided into them (mirrors PolygonSource in the analysis engine), else
    # blocks. Table 5 must be per whatever unit the analysis actually ran on.
    result_data = calculation.result_data or {}
    from ..services.analysis_polygon_source import PolygonSource

    blocks = PolygonSource.for_result_data(result_data).get_polygons()

    if not blocks:
        raise i18n_error(400, "blocks.no_areas_defined")

    # Get sub-areas from result_data (calculate_block_area_details drops the fire lines and keeps the river bank, a protection area)
    sub_areas = result_data.get("sub_areas", [])

    # Calculate block area details
    try:
        block_details = calculate_block_area_details(db, blocks, sub_areas)
    except Exception as e:
        raise i18n_error(400, "blocks.area_details_error", error=str(e))

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


# ---------------------------------------------------------------------------
# Backfill endpoint — recompute geo_* properties for all features
# ---------------------------------------------------------------------------
@router.post("/calculations/{calculation_id}/recompute-geo")
def recompute_geo_properties(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Recompute geo_* derived properties for ALL geometry features in a calculation.

    This backfills geo_area_ha, geo_perimeter_km, geo_length_km,
    geo_centroid_lat/lng, geo_bbox_* for blocks, sub-areas, and the boundary.

    Safe to call at any time — only updates geo_* keys, leaves everything else
    untouched. Handles dual storage: result_data (blocks, sub-areas, boundary)
    and forest_blocks DB table.
    """
    from ..utils.geometry_utils import compute_geometry_properties
    from shapely import wkb

    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    if calculation.user_id != current_user.id:
        raise i18n_error(403, "blocks.not_authorized")

    result_data = calculation.result_data or {}
    updated = {"blocks": 0, "sub_areas": 0, "boundary": 0}

    # --- Recompute geo_* for blocks (result_data + ForestBlock DB) ---
    blocks_list = result_data.get("blocks", [])
    for block_data in blocks_list:
        geom_geojson = block_data.get("geometry")
        if not geom_geojson:
            continue
        try:
            from shapely.geometry import shape

            geom = shape(geom_geojson)
            geo_props = compute_geometry_properties(geom)
            for k, v in geo_props.items():
                block_data[k] = v
            updated["blocks"] += 1
        except Exception as e:
            logger.warning(
                f"Failed to recompute geo for block {block_data.get('block_id')}: {e}"
            )

    # Also update ForestBlock DB rows
    db_blocks = (
        db.query(ForestBlock).filter(ForestBlock.calculation_id == calculation_id).all()
    )
    for db_block in db_blocks:
        try:
            block_shape = wkb.loads(bytes(db_block.geometry.data))
            geo_props = compute_geometry_properties(block_shape)
            # geo_* not stored on ForestBlock model — only in result_data
        except Exception:
            logger.exception(
                "derived properties unavailable for block %s - its area and "
                "perimeter are absent from the response",
                getattr(db_block, "name", "?"),
            )

    # --- Recompute geo_* for sub-areas (result_data only) ---
    sub_areas_list = result_data.get("sub_areas", [])
    for sa in sub_areas_list:
        sa_geom_geojson = sa.get("geometry")
        if not sa_geom_geojson:
            continue
        try:
            from shapely.geometry import shape

            geom = shape(sa_geom_geojson)
            geo_props = compute_geometry_properties(geom)
            for k, v in geo_props.items():
                sa[k] = v
            updated["sub_areas"] += 1
        except Exception as e:
            logger.warning(f"Failed to recompute geo for sub-area {sa.get('id')}: {e}")

    # --- Recompute geo_* for boundary (result_data) ---
    boundary_geom = result_data.get("geometry")
    if boundary_geom:
        try:
            from shapely.geometry import shape

            geom = shape(boundary_geom)
            geo_props = compute_geometry_properties(geom)
            for k, v in geo_props.items():
                result_data[k] = v
            updated["boundary"] = 1
        except Exception as e:
            logger.warning(f"Failed to recompute geo for boundary: {e}")

    # Flush changes
    if updated["blocks"] or updated["sub_areas"] or updated["boundary"]:
        result_data["blocks"] = blocks_list
        result_data["sub_areas"] = sub_areas_list
        calculation.result_data = result_data
        flag_modified(calculation, "result_data")
        db.commit()

    return {
        "success": True,
        "message": f"Recomputed geo properties for {updated['blocks']} blocks, {updated['sub_areas']} sub-areas, {updated['boundary']} boundary entries",
        "updated": updated,
    }
