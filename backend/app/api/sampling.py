"""
Sampling design API endpoints for forest inventory sampling.
# business: CFMG §X.Y — systematic sampling with 200m × 250m grid
# business: supports Guideline-2061 (DoF standard) and Manual sampling methods
# constraint: minimum 15 plots per block — ensures statistical validity
# constraint: plot sizes — Pole=100m², Tree=500m² per CFMG standard
# why: stratification by block and land cover for representative sampling
# why: boundary_buffer=50m avoids edge effects (roads, trails, canopy edge)
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel
import io
import logging
from decimal import Decimal
from app.core.errors import CalculationErrors
from app.core.exceptions import i18n_error, i18n_success, resolve_service_detail

logger = logging.getLogger(__name__)

from app.core.database import get_db
from app.services import optimistic_lock
from app.core.idempotent_route import IdempotentRoute
from app.services.forest_units import queries as forest_unit_queries
from app.services.sustainable_fm.stratum_spec import (
    MIN_SAMPLES_PER_UNIT,
    STRATUM_PLOT_SQM,
)
from app.services import sampling_add_units, sampling_unit_plan
from app.services.unit_size_review import (
    DEFAULT_REVIEW_PCT,
    DEFAULT_TOUCH_TOLERANCE_M,
    describe,
    mmu_hectares,
    review_units,
    summarise,
)
from app.utils.auth import get_current_user
from app.models.user import User
from app.models.calculation import Calculation
from app.models.sampling import SamplingDesign
from app.models.field_inventory import FieldInventoryCalculation
from app.models.forest_block import ForestBlock
from app.schemas.sampling import (
    SamplingDesignCreate,
    SamplingDesignUpdate,
    SamplingDesign as SamplingDesignSchema,
    SamplingGenerateResponse,
    SamplingPreviewResponse,
    SamplingPointsGeoJSON,
    SamplingExportFormat,
    SamplingMethod,
    ProtectedZoneInfo,
)
from app.services.sampling import (
    create_sampling_design,
    create_sampling_design_guideline_2061,
    get_sampling_points_geojson,
    SamplingPreviewResult,
)
from app.services.guideline_sampling import detect_protected_zones
from app.services.export import (
    export_sampling_csv,
    export_sampling_gpx,
    export_sampling_kml,
)
from app.utils.geospatial import extract_elevation_at_point
from app.utils.geospatial_vector import find_nearest_topographic_feature_vector
from app.utils.geospatial_vector_optimized import (
    preclip_topographic_features,
    find_nearest_topographic_feature_optimized,
)
from app.services.tree_cover_analysis import extract_accessible_forest_mask
from fastapi.responses import StreamingResponse, JSONResponse
import io
import json
from app.core.constants import METERS_PER_DEGREE_LAT

router = APIRouter(route_class=IdempotentRoute)


# ============================================================================
# Phase F (rule F) — pre-create sample-plot preview helpers
# ============================================================================


def _preview_boundary_layer(db, calculation) -> dict:
    """GeoJSON Feature for the forest boundary (shared with map-layers)."""
    boundary_query = text(
        """
        SELECT ST_AsGeoJSON(boundary_geom) as g
        FROM public.calculations
        WHERE id = :cid
    """
    )
    row = db.execute(boundary_query, {"cid": str(calculation.id)}).first()
    geometry = json.loads(row.g) if row and row.g else None
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "name": calculation.forest_name or "Forest Boundary",
            "layer_type": "boundary",
        },
    }


def _unit_key(block) -> str:
    """The name sampling files a unit's plots under (``compartment_code or block_name or name``, the rule of
    ``forest_units.sampling_view``). The map shows the unit's workspace ``name``; this key lets it translate a plot's unit back."""
    return block.compartment_code or block.block_name or block.name or ""


def _preview_forest_blocks_layer(db, calculation_id) -> Optional[dict]:
    """GeoJSON FeatureCollection of blocks/compartments/sub-compartments."""
    from sqlalchemy import func as sa_func

    from ..services.forest_units.model import DEPTH_SUB

    blocks = (
        db.query(
            ForestBlock.id,
            ForestBlock.name,
            ForestBlock.block_name,
            ForestBlock.compartment_code,
            ForestBlock.division_level,
            ForestBlock.is_compartment,
            ForestBlock.area_hectares,
            sa_func.ST_AsGeoJSON(ForestBlock.geometry).label("geojson"),
        )
        .filter(ForestBlock.calculation_id == calculation_id)
        .order_by(ForestBlock.division_level, ForestBlock.index)
        .all()
    )

    if not blocks:
        return None

    features = []
    for block in blocks:
        block_geom = json.loads(block.geojson)
        # FS-1c.1 straggler: migration 094 puts top-level blocks and top-level compartments at the same
        # depth, so this label - and any consumer's "which layer is this" toggle - must read the branch
        # (`is_compartment`), never the depth alone (I10).
        if not block.is_compartment:
            level_name = "Block"
        elif (block.division_level or 0) >= DEPTH_SUB:
            level_name = "Sub-compartment"
        else:
            level_name = "Compartment"
        features.append(
            {
                "type": "Feature",
                "geometry": block_geom,
                "properties": {
                    "id": str(block.id),
                    "name": block.name,
                    "unit_key": _unit_key(block),
                    "division_level": block.division_level,
                    "is_compartment": bool(block.is_compartment),
                    "area_hectares": block.area_hectares,
                    "level_name": level_name,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


@router.get("/calculations/{calculation_id}/sampling/blocks-layer")
def get_current_blocks_layer(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Live GeoJSON FeatureCollection of blocks/compartments/sub-compartments,
    same shape `_preview_forest_blocks_layer` builds for both the one-shot
    Preview response and a persisted design's /map-layers.

    Owner report 2026-10-02: after promoting a raster layer to Blocks/
    Compartments and then editing it (split a piece, merge), the Sample Plot
    preview map kept showing the ORIGINAL (pre-edit) geometry. Root cause was
    purely client-side: the Preview response's `forest_blocks_layer` is a
    one-shot GeoJSON snapshot the frontend holds in React state and never
    re-fetches; it has nothing to do with this becoming stale in the
    database, which is already correct in real time. This endpoint lets the
    frontend refresh just the block geometry for an already-captured preview
    without re-running the whole sampling preview (which would also
    regenerate the sample points themselves).
    """
    calculation = (
        db.query(Calculation)
        .filter(Calculation.id == calculation_id, Calculation.user_id == current_user.id)
        .first()
    )
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    layer = _preview_forest_blocks_layer(db, calculation_id)
    return layer or {"type": "FeatureCollection", "features": []}


def _filter_settings_from_request(request: SamplingDesignCreate) -> dict:
    return {
        "filter_tree_cover": (
            request.filter_tree_cover if request.filter_tree_cover is not None else True
        ),
        "filter_slope": (
            request.filter_slope if request.filter_slope is not None else False
        ),
        "max_slope_degrees": request.max_slope_degrees or 45.0,
    }


def _create_from_preview(
    db, calculation_id, request: SamplingDesignCreate
) -> SamplingGenerateResponse:
    """Deterministic create from a captured preview (rule F / F.3).

    Persists the EXACT plot locations the user previewed (no re-generation),
    so what you preview is what gets created — for all sampling types,
    including random. Stored in exactly the same form the engines use, so
    map-layers / points export / per-block summary all work unchanged.
    """
    import math

    preview = request.preview
    features = preview.sampling_points_geojson.features or []
    points = []
    for f in features:
        coords = f.geometry.get("coordinates") or []
        if len(coords) >= 2:
            points.append((float(coords[0]), float(coords[1])))
    if not points:
        raise ValueError(
            "PREVIEW_EMPTY: पूर्वावलोकन नमूना बिन्दुहरू फेला परेन (कृपया पुन: पूर्वावलोकन गर्नुहोस्)"
        )

    block_assignments = []
    for i, f in enumerate(features):
        props = f.properties or {}
        block_assignments.append(
            {
                "point_index": i,
                "block_number": props.get("block_number"),
                "block_name": props.get("block_name"),
                "zone_type": props.get("zone_type", "productive"),
            }
        )

    points_wkt = (
        "MULTIPOINT(" + ", ".join([f"{lon} {lat}" for lon, lat in points]) + ")"
    )
    sampling_type = request.sampling_type or "systematic"
    plot_shape = request.plot_shape or "circular"
    is_guideline = request.sampling_method == SamplingMethod.GUIDELINE_2061
    total_points = len(points)
    total_blocks = preview.total_blocks

    # Plot dimensions for the design record (mirror the two create engines)
    if is_guideline:
        plot_size_sqm = request.plot_size_sqm or 500
        if plot_shape == "circular":
            plot_radius_meters = Decimal(str(math.sqrt(plot_size_sqm / math.pi)))
            plot_length_meters = plot_width_meters = None
        else:
            side = Decimal(str(math.sqrt(plot_size_sqm)))
            plot_radius_meters = None
            plot_length_meters = plot_width_meters = side
    else:
        plot_radius_meters = request.plot_radius_meters
        plot_length_meters = request.plot_length_meters
        plot_width_meters = request.plot_width_meters

    sampling_design = SamplingDesign(
        calculation_id=calculation_id,
        sampling_type=sampling_type,
        intensity_per_hectare=preview.actual_intensity_per_hectare,
        grid_spacing_meters=None,
        min_distance_meters=request.min_distance_meters,
        plot_shape=plot_shape,
        plot_radius_meters=plot_radius_meters,
        plot_length_meters=plot_length_meters,
        plot_width_meters=plot_width_meters,
        total_points=total_points,
        notes=request.notes,
    )
    db.add(sampling_design)
    db.flush()  # Get ID

    if is_guideline:
        default_parameters = {
            "sampling_method": "guideline_2061",
            "productive_intensity": (
                float(request.productive_intensity.value)
                if request.productive_intensity
                else 0.5
            ),
            "sample_protected_zone": request.sample_protected_zone or False,
            "plot_size_sqm": request.plot_size_sqm or 500,
            "boundary_buffer_meters": request.boundary_buffer_meters or 50.0,
            "filter_tree_cover": (
                request.filter_tree_cover
                if request.filter_tree_cover is not None
                else True
            ),
            "filter_slope": (
                request.filter_slope if request.filter_slope is not None else False
            ),
            "max_slope_degrees": request.max_slope_degrees or 45.0,
            "area_basis": preview.area_basis,
        }
    else:
        default_parameters = {
            "sampling_type": sampling_type,
            "sampling_intensity_percent": (
                float(request.sampling_intensity_percent)
                if request.sampling_intensity_percent is not None
                else 0.5
            ),
            "min_samples_per_block": request.min_samples_per_block or 5,
            "min_samples_small_blocks": request.min_samples_small_blocks or 2,
            "boundary_buffer_meters": request.boundary_buffer_meters or 50.0,
            "min_distance_meters": request.min_distance_meters,
            "filter_tree_cover": (
                request.filter_tree_cover
                if request.filter_tree_cover is not None
                else True
            ),
            "filter_slope": (
                request.filter_slope if request.filter_slope is not None else False
            ),
            "max_slope_degrees": request.max_slope_degrees or 45.0,
            "area_basis": preview.area_basis,
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
            "params": json.dumps(default_parameters),
            "design_id": str(sampling_design.id),
        },
    )

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
        total_points=total_points,
        total_blocks=total_blocks,
        forest_area_hectares=preview.forest_area_hectares,
        requested_intensity_percent=preview.requested_intensity_percent,
        actual_intensity_per_hectare=preview.actual_intensity_per_hectare,
        plot_area_sqm=preview.plot_area_sqm,
        total_sampled_area_hectares=preview.total_sampled_area_hectares,
        sampling_percentage=preview.sampling_percentage,
        blocks_info=preview.blocks_info,
    )

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


@router.post(
    "/calculations/{calculation_id}/sampling/create",
    response_model=SamplingGenerateResponse,
)
def create_sampling(
    calculation_id: UUID,
    request: SamplingDesignCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a sampling design with either Guideline-2061 or Manual method.

    **Guideline-2061 Method (Recommended):**
    - Nepal DoF standard sampling methodology
    - Sample counts determined by lookup tables based on block size
    - Supports 0.5%, 1%, or 0.1% intensity
    - Systematic sampling only
    - Automatic protected zone detection

    **Manual Method (Advanced):**
    - Full control over sampling parameters
    - Supports systematic, random, stratified algorithms
    - Intensity as percentage with min samples rules
    - Custom plot sizes and shapes
    """
    # Verify calculation exists and belongs to user
    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == calculation_id, Calculation.user_id == current_user.id
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    if not calculation.boundary_geom:
        raise i18n_error(400, "calculations.no_geometry")

    # Check if a sampling design already exists for this calculation
    existing_design = (
        db.query(SamplingDesign)
        .filter(SamplingDesign.calculation_id == calculation_id)
        .first()
    )

    if existing_design:
        raise i18n_error(
            400, "sampling.design_already_exists", design_id=str(existing_design.id)
        )

    try:
        if request.preview is not None:
            # F.3 — deterministic create-from-preview: persist the EXACT plot
            # locations the user previewed (no re-generation).
            logger.info(
                f"Creating sampling design #{request.preview.preview_token} from preview for calculation {calculation_id} (deterministic, {len(request.preview.sampling_points_geojson.features)} plots)"
            )
            summary = _create_from_preview(db, calculation_id, request)
        elif request.sampling_method == SamplingMethod.GUIDELINE_2061:
            # Use Guideline-2061 method
            logger.info(
                f"Creating Guideline-2061 sampling design for calculation {calculation_id}"
            )

            # Calculate plot dimensions from plot_size_sqm
            plot_size_sqm = request.plot_size_sqm or 500
            if request.plot_shape == "circular":
                import math

                plot_radius_meters = math.sqrt(plot_size_sqm / math.pi)
            else:
                plot_side_meters = math.sqrt(plot_size_sqm)

            summary = create_sampling_design_guideline_2061(
                db=db,
                calculation_id=calculation_id,
                productive_intensity=(
                    float(request.productive_intensity.value)
                    if request.productive_intensity
                    else 0.5
                ),
                sample_protected_zone=request.sample_protected_zone or False,
                plot_size_sqm=plot_size_sqm,
                plot_shape=request.plot_shape or "circular",
                filter_tree_cover=(
                    request.filter_tree_cover
                    if request.filter_tree_cover is not None
                    else True
                ),
                filter_slope=(
                    request.filter_slope if request.filter_slope is not None else False
                ),
                max_slope_degrees=request.max_slope_degrees or 45.0,
                boundary_buffer_meters=request.boundary_buffer_meters or 50.0,
                notes=request.notes,
                per_block_intensity=request.per_block_intensity,
                per_block_plots=request.per_block_plots,
                enforce_min_samples_production=(
                    request.enforce_min_samples_production
                    if request.enforce_min_samples_production is not None
                    else True
                ),
                enforce_min_samples_conservation=(
                    request.enforce_min_samples_conservation
                    if request.enforce_min_samples_conservation is not None
                    else True
                ),
                enforce_min_samples_protection=(
                    request.enforce_min_samples_protection
                    if request.enforce_min_samples_protection is not None
                    else True
                ),
            )

        else:
            # Use existing manual method
            logger.info(
                f"Creating manual sampling design for calculation {calculation_id}"
            )

            # Convert block_overrides from Pydantic models to dicts if present
            block_overrides_dict = None
            if request.block_overrides:
                block_overrides_dict = {}
                for block_name, override in request.block_overrides.items():
                    if hasattr(override, "model_dump"):
                        block_overrides_dict[block_name] = override.model_dump(
                            exclude_none=True
                        )
                    elif hasattr(override, "dict"):
                        block_overrides_dict[block_name] = override.dict(
                            exclude_none=True
                        )
                    else:
                        block_overrides_dict[block_name] = override

            summary = create_sampling_design(
                db=db,
                calculation_id=calculation_id,
                sampling_type=request.sampling_type,
                sampling_intensity_percent=request.sampling_intensity_percent,
                min_samples_per_block=request.min_samples_per_block or 5,
                min_samples_small_blocks=request.min_samples_small_blocks or 2,
                boundary_buffer_meters=request.boundary_buffer_meters or 50.0,
                filter_tree_cover=(
                    request.filter_tree_cover
                    if request.filter_tree_cover is not None
                    else True
                ),
                filter_slope=(
                    request.filter_slope if request.filter_slope is not None else False
                ),
                max_slope_degrees=request.max_slope_degrees or 45.0,
                intensity_per_hectare=request.intensity_per_hectare,
                grid_spacing_meters=request.grid_spacing_meters,
                min_distance_meters=request.min_distance_meters,
                plot_shape=request.plot_shape or "circular",
                plot_radius_meters=request.plot_radius_meters,
                plot_length_meters=request.plot_length_meters,
                plot_width_meters=request.plot_width_meters,
                notes=request.notes,
                block_overrides=_with_plot_counts(block_overrides_dict, request),
                enforce_min_samples_production=(
                    request.enforce_min_samples_production
                    if request.enforce_min_samples_production is not None
                    else True
                ),
                enforce_min_samples_conservation=(
                    request.enforce_min_samples_conservation
                    if request.enforce_min_samples_conservation is not None
                    else True
                ),
                enforce_min_samples_protection=(
                    request.enforce_min_samples_protection
                    if request.enforce_min_samples_protection is not None
                    else True
                ),
            )

        db.commit()

        # A freshly generated design is built from the CURRENT unit geometry, so
        # `structure_stale['sampling']` is answered. The engines commit
        # internally and never see the Calculation, so the flag is cleared here
        # by id. Without this the banner kept asking for a sampling re-run the
        # user had just done.
        from app.services.forest_units.write import clear_stale_domains_for_calc

        if clear_stale_domains_for_calc(db, calculation_id):
            db.commit()

        return summary

    except ValueError as e:
        raise HTTPException(status_code=400, detail=resolve_service_detail(str(e)))
    except Exception as e:
        db.rollback()
        import logging

        logging.error(f"Sampling design creation failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to create sampling design: {str(e)}"
        )


def _with_plot_counts(overrides, request: SamplingDesignCreate):
    """The intensity engine takes per-polygon settings as ``block_overrides``; carry the typed plot counts in as ``sample_count``."""
    if not request.per_block_plots:
        return overrides
    out = {k: dict(v) for k, v in (overrides or {}).items()}
    for name, n in request.per_block_plots.items():
        out.setdefault(name, {})["sample_count"] = int(n)
    return out


def _requests_for_added_units(db, calculation, design, request: SamplingDesignCreate) -> SamplingDesignCreate:
    """The request for a LATER ROUND: only the polygons the user ticked (intensity > 0) and that have no plots yet are sampled.

    Every other polygon - already sampled, or simply not ticked - is held at 0 % (the engines' "do not sample this unit"), so the
    round cannot touch plots that exist. A ticked polygon that already has plots is refused by name; so is a round with nothing ticked.
    """
    plan = sampling_unit_plan.unit_plan(db, calculation)
    names = [u["name"] for u in plan["units"]]
    sampled = {u["name"] for u in plan["units"] if u["sampled_plots"] > 0}

    def _val(v) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    guideline = request.sampling_method == SamplingMethod.GUIDELINE_2061
    if guideline:
        wanted = {n: _val(v) for n, v in (request.per_block_intensity or {}).items()}
    else:
        wanted = {}
        for n, o in (request.block_overrides or {}).items():
            d = o.model_dump(exclude_none=True) if hasattr(o, "model_dump") else dict(o)
            wanted[n] = _val(d.get("sampling_intensity_percent"))
    plots_wanted = {n: int(v) for n, v in (request.per_block_plots or {}).items() if v is not None}
    # ticked = an intensity above 0 OR a number of plots above 0 (a polygon given an explicit count needs no intensity)
    ticked = {n for n in names if wanted.get(n, 0) > 0 or plots_wanted.get(n, 0) > 0}
    again = sorted(ticked & sampled)
    if again:
        raise i18n_error(409, "sampling.unit_already_sampled", units=", ".join(again))
    if not ticked:
        raise i18n_error(400, "sampling.add_no_unit_selected")

    # a later round keeps the FIRST round's settings (plot size, tree-cover filter, buffers ...), whatever the form shows now
    carried = {
        k: v
        for k, v in (design.default_parameters or {}).items()
        if k in ("plot_size_sqm", "sample_protected_zone", "boundary_buffer_meters", "filter_tree_cover", "filter_slope",
                 "max_slope_degrees", "sampling_type", "min_samples_per_block", "min_samples_small_blocks", "min_distance_meters",
                 "enforce_min_samples_production", "enforce_min_samples_conservation", "enforce_min_samples_protection")
        and v is not None
    }
    # explicit counts: kept for the ticked polygons that have one, 0 ("do not sample") for every polygon that is not ticked
    plots_out = {n: (plots_wanted[n] if n in ticked else 0) for n in names if n in plots_wanted or n not in ticked}
    if guideline:
        return request.model_copy(update={**carried, "per_block_plots": plots_out,
                                          "per_block_intensity": {n: (wanted.get(n, 0.0) if n in ticked else 0.0) for n in names}})
    overrides = {}
    for n in names:
        base = request.block_overrides.get(n) if request.block_overrides else None
        d = (base.model_dump(exclude_none=True) if hasattr(base, "model_dump") else dict(base or {}))
        d["sampling_intensity_percent"] = wanted.get(n, 0.0) if n in ticked else 0.0
        overrides[n] = d
    return request.model_copy(update={**carried, "per_block_plots": plots_out, "block_overrides": overrides})


@router.get("/calculations/{calculation_id}/sampling/unit-plan")
def get_unit_plan(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One row per polygon for the sampling screen, for ANY forest (no forest type, no plots needed): stratum with the reason it was
    proposed, the legal minimum and plot size, slope band, and how many plots the forest's design already holds there. Read-only.

    ``field_data_exists`` says whether plots can still be added or deleted (they cannot once field inventory data exists)."""
    calculation = (
        db.query(Calculation)
        .filter(Calculation.id == calculation_id, Calculation.user_id == current_user.id)
        .first()
    )
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    plan = sampling_unit_plan.unit_plan(db, calculation)
    plan["field_data_exists"] = _design_has_field_data(db, calculation_id)
    return plan


class SuggestedCountsRequest(BaseModel):
    intensities: Dict[str, float] = {}
    method: str = "guideline"  # "guideline" (Guideline-2061 lookup) | "manual" (the intensity engine)


@router.post("/calculations/{calculation_id}/sampling/suggested-counts")
def get_suggested_counts(
    calculation_id: UUID,
    body: SuggestedCountsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """How many plots each polygon's intensity amounts to, and the number we suggest (never fewer than 5). The user may type any
    number - more or fewer - as long as it amounts to the stratum's legal minimum intensity and at most 5 %. Read-only."""
    calculation = (
        db.query(Calculation)
        .filter(Calculation.id == calculation_id, Calculation.user_id == current_user.id)
        .first()
    )
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    method = "manual" if body.method == "manual" else "guideline"
    return sampling_unit_plan.suggested_counts(db, calculation, body.intensities, method)


@router.post("/calculations/{calculation_id}/sampling/{design_id}/add-units")
def add_units_to_design(
    calculation_id: UUID,
    design_id: UUID,
    request: SamplingDesignCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Append a previewed LATER ROUND (``request.preview``, from ``/sampling/preview?add_to_design=``) to the forest's one design.
    Existing plots do not move; the new ones are numbered after them. Refused while field inventory data exists, for a polygon that
    already has plots, and when nothing was previewed."""
    calculation = (
        db.query(Calculation)
        .filter(Calculation.id == calculation_id, Calculation.user_id == current_user.id)
        .first()
    )
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    design = (
        db.query(SamplingDesign)
        .filter(SamplingDesign.id == design_id, SamplingDesign.calculation_id == calculation_id)
        .first()
    )
    if design is None:
        raise HTTPException(status_code=404, detail="Sampling design not found")
    if calculation.structure_locked:
        raise i18n_error(423, "sampling.design_locked")
    if _design_has_field_data(db, calculation_id):
        raise i18n_error(409, "sampling.cannot_add_units_field_data_exists")
    if request.preview is None:
        raise i18n_error(400, "sampling.add_no_unit_selected")
    try:
        features = request.preview.sampling_points_geojson.features or []
        sampled = {u["name"] for u in sampling_unit_plan.unit_plan(db, calculation)["units"] if u["sampled_plots"] > 0}
        again = sorted({(f.properties or {}).get("block_name") for f in features} & sampled)
        if again:
            raise i18n_error(409, "sampling.unit_already_sampled", units=", ".join(again))
        out = sampling_add_units.merge_preview_into_design(db, design, features, request.preview)
        db.commit()
        from app.services.forest_units.write import clear_stale_domains_for_calc

        if clear_stale_domains_for_calc(db, calculation_id):
            db.commit()
        return {"design_id": str(design.id), **out}
    except HTTPException:
        db.rollback()
        raise
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=resolve_service_detail(str(e)))


@router.delete("/sampling/{design_id}/units/{unit_name}/points")
def delete_unit_plots(
    design_id: UUID,
    unit_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete every plot of ONE polygon so it can be sampled again. Same gate as deleting a single plot: refused once field
    inventory data exists. Remaining plots are renumbered 1..N without a gap."""
    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Sampling design not found")
    calculation = (
        db.query(Calculation)
        .filter(Calculation.id == design.calculation_id, Calculation.user_id == current_user.id)
        .first()
    )
    if not calculation:
        raise HTTPException(status_code=403, detail="Access denied")
    if _design_has_field_data(db, design.calculation_id):
        raise i18n_error(409, "sampling.cannot_delete_plot_field_data_exists")
    try:
        out = sampling_add_units.remove_unit_plots(db, design, unit_name)
        db.commit()
    except LookupError:
        db.rollback()
        raise i18n_error(404, "sampling.unit_has_no_plots")
    except ValueError:
        db.rollback()
        raise i18n_error(400, "sampling.cannot_delete_unit_plots_last")
    return {"success": True, "design_id": str(design_id), "unit": unit_name, **out}


@router.post(
    "/calculations/{calculation_id}/sampling/preview",
    response_model=SamplingPreviewResponse,
)
def preview_sampling(
    calculation_id: UUID,
    request: SamplingDesignCreate,
    add_to_design: Optional[UUID] = Query(
        None,
        description="Preview a LATER ROUND for this forest's one design: only the polygons ticked (intensity > 0) that do not "
        "already have plots are sampled; every other polygon is held at 0.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pre-create sample-plot preview (rule F).

    Computes the sample-plot layout with the SAME engine as ``/sampling/create``
    but WITHOUT writing any DB rows, so the user can compare designs before
    committing. The response includes the exact plot GeoJSON plus boundary/block
    layers so the shared ``SamplingMapView`` renders identical symbols/labels to
    a persisted design.

    Guards mirror the create endpoint: 404 (calc not found/owned), 400 (no
    boundary, or a design already exists — one design per forest), 423
    (structure locked).

    Determinism note: for Random (and intensity-systematic which uses a
    randomized grid origin) the preview is a *representative* layout; the exact
    locations may differ slightly on create. The create endpoint accepts the
    captured ``preview`` payload to persist the previewed locations exactly
    (rule F.3).
    """
    # Verify calculation exists and belongs to user
    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == calculation_id, Calculation.user_id == current_user.id
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    if not calculation.boundary_geom:
        raise i18n_error(400, "calculations.no_geometry")

    if calculation.structure_locked:
        raise i18n_error(423, "sampling.design_locked")

    # Reuse the create guard: one sampling design per forest. A later round for polygons not sampled yet goes to THAT design.
    existing_design = (
        db.query(SamplingDesign)
        .filter(SamplingDesign.calculation_id == calculation_id)
        .first()
    )

    if add_to_design is not None:
        if existing_design is None or existing_design.id != add_to_design:
            raise HTTPException(status_code=404, detail="Sampling design not found")
        request = _requests_for_added_units(db, calculation, existing_design, request)
    elif existing_design:
        raise i18n_error(
            400, "sampling.design_already_exists", design_id=str(existing_design.id)
        )

    try:
        if request.sampling_method == SamplingMethod.GUIDELINE_2061:
            plot_size_sqm = request.plot_size_sqm or 500
            result = create_sampling_design_guideline_2061(
                db=db,
                calculation_id=calculation_id,
                preview=True,
                productive_intensity=(
                    float(request.productive_intensity.value)
                    if request.productive_intensity
                    else 0.5
                ),
                sample_protected_zone=request.sample_protected_zone or False,
                plot_size_sqm=plot_size_sqm,
                plot_shape=request.plot_shape or "circular",
                filter_tree_cover=(
                    request.filter_tree_cover
                    if request.filter_tree_cover is not None
                    else True
                ),
                filter_slope=(
                    request.filter_slope if request.filter_slope is not None else False
                ),
                max_slope_degrees=request.max_slope_degrees or 45.0,
                boundary_buffer_meters=request.boundary_buffer_meters or 50.0,
                notes=request.notes,
                per_block_intensity=request.per_block_intensity,
                per_block_plots=request.per_block_plots,
                enforce_min_samples_production=(
                    request.enforce_min_samples_production
                    if request.enforce_min_samples_production is not None
                    else True
                ),
                enforce_min_samples_conservation=(
                    request.enforce_min_samples_conservation
                    if request.enforce_min_samples_conservation is not None
                    else True
                ),
                enforce_min_samples_protection=(
                    request.enforce_min_samples_protection
                    if request.enforce_min_samples_protection is not None
                    else True
                ),
            )
        else:
            block_overrides_dict = None
            if request.block_overrides:
                block_overrides_dict = {}
                for block_name, override in request.block_overrides.items():
                    if hasattr(override, "model_dump"):
                        block_overrides_dict[block_name] = override.model_dump(
                            exclude_none=True
                        )
                    elif hasattr(override, "dict"):
                        block_overrides_dict[block_name] = override.dict(
                            exclude_none=True
                        )
                    else:
                        block_overrides_dict[block_name] = override

            result = create_sampling_design(
                db=db,
                calculation_id=calculation_id,
                preview=True,
                sampling_type=request.sampling_type,
                sampling_intensity_percent=request.sampling_intensity_percent,
                min_samples_per_block=request.min_samples_per_block or 5,
                min_samples_small_blocks=request.min_samples_small_blocks or 2,
                boundary_buffer_meters=request.boundary_buffer_meters or 50.0,
                filter_tree_cover=(
                    request.filter_tree_cover
                    if request.filter_tree_cover is not None
                    else True
                ),
                filter_slope=(
                    request.filter_slope if request.filter_slope is not None else False
                ),
                max_slope_degrees=request.max_slope_degrees or 45.0,
                intensity_per_hectare=request.intensity_per_hectare,
                grid_spacing_meters=request.grid_spacing_meters,
                min_distance_meters=request.min_distance_meters,
                plot_shape=request.plot_shape or "circular",
                plot_radius_meters=request.plot_radius_meters,
                plot_length_meters=request.plot_length_meters,
                plot_width_meters=request.plot_width_meters,
                notes=request.notes,
                block_overrides=_with_plot_counts(block_overrides_dict, request),
                enforce_min_samples_production=(
                    request.enforce_min_samples_production
                    if request.enforce_min_samples_production is not None
                    else True
                ),
                enforce_min_samples_conservation=(
                    request.enforce_min_samples_conservation
                    if request.enforce_min_samples_conservation is not None
                    else True
                ),
                enforce_min_samples_protection=(
                    request.enforce_min_samples_protection
                    if request.enforce_min_samples_protection is not None
                    else True
                ),
            )

        if not isinstance(result, SamplingPreviewResult):
            raise HTTPException(
                status_code=500,
                detail="Preview engine returned an unexpected result type",
            )

        boundary_layer = _preview_boundary_layer(db, calculation)
        forest_blocks_layer = _preview_forest_blocks_layer(db, calculation_id)

        return SamplingPreviewResponse(
            preview_token=result.response.sampling_design_id,
            total_points=result.response.total_points,
            total_units=result.response.total_blocks,
            total_blocks=result.response.total_blocks,
            requested_intensity_percent=result.response.requested_intensity_percent,
            sampling_percentage=result.response.sampling_percentage,
            area_basis=result.area_basis,
            forest_area_hectares=result.response.forest_area_hectares,
            actual_intensity_per_hectare=result.response.actual_intensity_per_hectare,
            plot_area_sqm=result.response.plot_area_sqm,
            total_sampled_area_hectares=result.response.total_sampled_area_hectares,
            blocks_info=result.response.blocks_info,
            sampling_points_geojson=result.points_geojson,
            boundary_layer=boundary_layer,
            forest_blocks_layer=forest_blocks_layer,
            filter_settings=_filter_settings_from_request(request),
            calculation_id=calculation_id,
            sampling_type=result.response.sampling_type,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=resolve_service_detail(str(e)))
    except Exception as e:
        db.rollback()
        logger.error(f"Sampling preview failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to preview sampling design: {str(e)}"
        )


@router.get(
    "/calculations/{calculation_id}/protected-zones", response_model=ProtectedZoneInfo
)
def get_protected_zones(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # business: Guideline-2061 detects protected zones (religious, biodiversity, etc.)
    # business: protected zones require separate sampling treatment per CFMG
    """
    Get protected zone information for a calculation.

    Used to determine if protected zone sampling option should be shown
    in Guideline-2061 sampling method.

    Returns information about:
    - Whether protected zones exist
    - Total protected area
    - Names of protected zones
    - Productive (non-protected) area

    This endpoint is called by the frontend when user selects Guideline-2061
    method to display protected zone sampling checkbox if applicable.
    """
    # Verify calculation exists and belongs to user
    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == calculation_id, Calculation.user_id == current_user.id
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    # Detect protected zones
    protected_info = detect_protected_zones(calculation)

    return ProtectedZoneInfo(**protected_info)


@router.get(
    "/calculations/{calculation_id}/sampling", response_model=List[SamplingDesignSchema]
)
def list_sampling_designs(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all sampling designs for a calculation.
    """
    # Verify calculation belongs to user
    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == calculation_id, Calculation.user_id == current_user.id
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    designs = (
        db.query(SamplingDesign)
        .filter(SamplingDesign.calculation_id == calculation_id)
        .order_by(SamplingDesign.created_at.desc())
        .all()
    )

    return [SamplingDesignSchema.model_validate(d) for d in designs]


@router.get("/sampling/{design_id}", response_model=SamplingDesignSchema)
def get_sampling_design(
    design_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a specific sampling design by ID.
    """
    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()

    if not design:
        raise HTTPException(status_code=404, detail="Sampling design not found")

    # Verify user has access to this design's calculation
    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == design.calculation_id,
            Calculation.user_id == current_user.id,
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=403, detail="Access denied")

    return SamplingDesignSchema.model_validate(design)


@router.get("/sampling/{design_id}/points")
def get_sampling_points(
    design_id: UUID,
    format: Optional[str] = Query(
        None, description="Export format: csv, gpx, kml, geojson"
    ),
    include_elevation: bool = Query(True, description="Include elevation (ASLM) data"),
    include_topographic_features: bool = Query(
        False, description="Include nearest ridge/valley info"
    ),
    prefer_rivers: bool = Query(
        True, description="Prefer rivers/valleys over ridges for navigation"
    ),
    min_feature_distance: float = Query(
        20.0, description="Minimum distance to report feature (meters)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # why: elevation + topographic features help field crews navigate to plots on ground
    # constraint: GPX export uses GPS Exchange Format for handheld device import
    """
    Get sampling points for a design.

    Optionally export in CSV, GPX, KML, or GeoJSON format.

    Navigation Enhancement Options:
    - include_elevation: Add elevation (ASLM) at each point (default: True)
    - include_topographic_features: Add nearest ridge/valley with distance and direction (default: False)
    - prefer_rivers: Prefer valleys/rivers over ridges when both are close (default: True)
    - min_feature_distance: Don't report features closer than this (default: 20m)
                           If < 20m, the point is likely ON the feature, not near it
    """
    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()

    if not design:
        raise HTTPException(status_code=404, detail="Sampling design not found")

    # Verify user has access
    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == design.calculation_id,
            Calculation.user_id == current_user.id,
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=403, detail="Access denied")

    from app.utils.file_export import build_disposition

    # Handle export formats
    if format:
        try:
            forest_name = calculation.forest_name

            if format == "csv":
                csv_data = export_sampling_csv(db, design_id)
                _, disposition = build_disposition(
                    forest_name, "Sampling", "SamplePoints", "csv"
                )
                return StreamingResponse(
                    io.BytesIO(csv_data),
                    media_type="text/csv",
                    headers={"Content-Disposition": disposition},
                )

            elif format == "gpx":
                gpx_data = export_sampling_gpx(db, design_id)
                _, disposition = build_disposition(
                    forest_name, "Sampling", "SamplePoints", "gpx"
                )
                return StreamingResponse(
                    io.BytesIO(gpx_data),
                    media_type="application/gpx+xml",
                    headers={"Content-Disposition": disposition},
                )

            elif format == "kml":
                kml_data = export_sampling_kml(db, design_id)
                _, disposition = build_disposition(
                    forest_name, "Sampling", "SamplePoints", "kml"
                )
                return StreamingResponse(
                    io.BytesIO(kml_data),
                    media_type="application/vnd.google-earth.kml+xml",
                    headers={"Content-Disposition": disposition},
                )

            elif format == "geojson":
                geojson_data = get_sampling_points_geojson(db, design_id)
                _, disposition = build_disposition(
                    forest_name, "Sampling", "SamplePoints", "geojson"
                )
                return JSONResponse(
                    content=geojson_data, headers={"Content-Disposition": disposition}
                )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

    # Return cached points if available (always — eliminates recomputation on tab switch / reload)
    if design.points_data:
        return design.points_data

    from shapely import wkt as shapely_wkt
    from pyproj import Transformer

    # Get points geometry as WKT
    wkt_query = text(
        """
        SELECT ST_AsText(points_geometry) as wkt,
               points_block_assignment
        FROM public.sampling_designs
        WHERE id = :design_id
    """
    )
    result = db.execute(wkt_query, {"design_id": str(design_id)}).first()

    if not result or not result.wkt:
        return {"points": []}

    # Parse MultiPoint geometry
    multipoint = shapely_wkt.loads(result.wkt)
    block_assignment = result.points_block_assignment or []

    # Get calculation boundary for distance calculation
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

    # OPTIMIZATION: Pre-clip ridge/river data ONCE before the loop
    # This dramatically speeds up exports (20-100x faster!)
    # Always compute on cache miss so cached data is complete
    clipped_features = None
    if boundary_wkt:
        clipped_features = preclip_topographic_features(
            db=db, boundary_wkt=boundary_wkt, buffer_meters=100.0
        )

    # Helper function to safely convert float to JSON-compatible value
    def safe_float(value, decimals=2):
        """Convert float to JSON-safe value, replacing NaN/inf with None"""
        if value is None:
            return None
        try:
            import math

            if math.isnan(value) or math.isinf(value):
                return None
            return float(f"{value:.{decimals}f}")
        except (TypeError, ValueError):
            return None

    def safe_int(value):
        """Convert to int, replacing NaN/None with None"""
        if value is None:
            return None
        try:
            import math

            if math.isnan(value) or math.isinf(value):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    # Build points array
    points = []
    for i, point in enumerate(multipoint.geoms):
        lon, lat = point.x, point.y

        # Find block assignment
        block_info = next(
            (b for b in block_assignment if b.get("point_index") == i), None
        )
        block_number = block_info.get("block_number", 1) if block_info else 1
        block_name = (
            block_info.get("block_name", f"Block {block_number}")
            if block_info
            else f"Block {block_number}"
        )
        zone_type = (
            block_info.get("zone_type", "Productive") if block_info else "Productive"
        )

        # Calculate UTM coordinates
        utm_zone = 44 if lon < 84 else 45  # Nepal is in zones 44N and 45N
        transformer = Transformer.from_crs(
            f"EPSG:4326", f"EPSG:326{utm_zone}", always_xy=True
        )
        utm_easting, utm_northing = transformer.transform(lon, lat)

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

        # Extract elevation (ASLM - Above Sea Level Meter)
        # Always computed on cache miss so cached data is complete
        elevation_m = extract_elevation_at_point(db, lon, lat)

        # Find nearest topographic feature using OPTIMIZED pre-clipped data
        # Always computed on cache miss so cached data is complete
        topo_feature = None
        if clipped_features:
            topo_feature = find_nearest_topographic_feature_optimized(
                db=db,
                longitude=lon,
                latitude=lat,
                clipped_features=clipped_features,
                search_radius_meters=100.0,
                prefer_rivers=prefer_rivers,
                min_distance_threshold=min_feature_distance,
            )

        # Build topographic context string for display with NAMES
        topo_context = None
        if topo_feature:
            feature_name = topo_feature.get("feature_name", "unnamed feature")
            distance = topo_feature.get("distance_meters", 0)
            direction = topo_feature.get("direction", "")
            # NEW: Include feature name!
            topo_context = f"{int(distance)}m {direction} of {feature_name}"

        point_data = {
            "id": f"{design_id}_{i}",
            "plot_number": i + 1,
            "block_number": block_number,
            "block_name": block_name,
            "zone_type": zone_type,
            "longitude": safe_float(lon, 7),
            "latitude": safe_float(lat, 7),
            "utm_easting": safe_float(utm_easting, 2),
            "utm_northing": safe_float(utm_northing, 2),
            "utm_zone": f"{utm_zone}N",
            "distance_from_boundary": safe_float(distance_from_boundary, 2),
        }

        # Always include elevation and topographic context in cached response
        point_data["elevation_m"] = safe_int(elevation_m)
        point_data["topographic_context"] = topo_context
        point_data["nearest_feature_type"] = (
            topo_feature.get("feature_type") if topo_feature else None
        )
        point_data["nearest_feature_name"] = (
            topo_feature.get("feature_name") if topo_feature else None
        )
        point_data["nearest_feature_distance_m"] = safe_int(
            topo_feature.get("distance_meters", 0) if topo_feature else None
        )
        point_data["nearest_feature_direction"] = (
            topo_feature.get("direction") if topo_feature else None
        )
        point_data["nearest_feature_bearing"] = safe_int(
            topo_feature.get("bearing_degrees", 0) if topo_feature else None
        )

        points.append(point_data)

    result = {"points": points}

    # Cache computed points for instant loading on subsequent visits.
    #
    # H8.2 / S2-63: derived data, not a user edit, so the version must NOT be
    # bumped -- a client holding version 4 would otherwise get a 409 on its
    # next write because somebody else merely VIEWED the points.
    optimistic_lock.record_derived_write(
        db,
        "sampling",
        design.id,
        "cached computed sample points",
    )
    design.points_data = result
    db.add(design)
    db.commit()

    return result


@router.put("/sampling/{design_id}", response_model=SamplingDesignSchema)
def update_sampling_design(
    design_id: UUID,
    update_data: SamplingDesignUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update sampling design notes.
    """
    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()

    if not design:
        raise HTTPException(status_code=404, detail="Sampling design not found")

    # Verify user has access
    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == design.calculation_id,
            Calculation.user_id == current_user.id,
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=403, detail="Access denied")

    # H8.2 / S2-63: take the design before changing it. A sampling design
    # decides which plots get visited, so silently accepting one of two
    # conflicting edits is a change to the field programme nobody approved --
    # hence `operator_resolved` in the 409, not last-write-wins.
    optimistic_lock.check_and_bump(db, "sampling", design_id, update_data.version)

    # Update notes
    if update_data.notes is not None:
        design.notes = update_data.notes

    try:
        db.commit()
        db.refresh(design)
        return SamplingDesignSchema.model_validate(design)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


@router.delete("/sampling/{design_id}")
def delete_sampling_design(
    design_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a sampling design.
    """
    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()

    if not design:
        raise HTTPException(status_code=404, detail="Sampling design not found")

    # Verify user has access
    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == design.calculation_id,
            Calculation.user_id == current_user.id,
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        db.delete(design)
        db.commit()

        return {
            "success": True,
            **i18n_success("success.sampling_design_deleted"),
            "design_id": str(design_id),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


class SamplePlotPointBody(BaseModel):
    longitude: float
    latitude: float


class SamplePlotMoveBody(BaseModel):
    """Move a plot by a dragged position (longitude AND latitude), or by typing ONE value of either pair: a latitude, a longitude, a UTM
    easting or a UTM northing. The value not typed is taken from the plot as it is. The UTM zone is never typed: it is the plot's own."""
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    utm_easting: Optional[float] = None
    utm_northing: Optional[float] = None


def _forest_crosses_utm_zones(db, calculation_id) -> bool:
    row = db.execute(
        text("SELECT ST_XMin(boundary_geom) AS x0, ST_XMax(boundary_geom) AS x1 FROM public.calculations WHERE id = :c"),
        {"c": str(calculation_id)},
    ).first()
    if not row or row.x0 is None:
        return False
    from app.services import sample_plot_coordinates as scoords

    return scoords.utm_zone_for(row.x0) != scoords.utm_zone_for(row.x1)


def _resolve_move(db, calculation_id, current_point, body: "SamplePlotMoveBody"):
    """The plot's new position from what was dragged or typed, or a friendly 400 saying what is wrong and that nothing was saved."""
    from app.services import sample_plot_coordinates as scoords

    try:
        res = scoords.resolve_new_location(
            current_point.x, current_point.y,
            longitude=body.longitude, latitude=body.latitude, utm_easting=body.utm_easting, utm_northing=body.utm_northing,
        )
    except scoords.CoordinateError as e:
        raise i18n_error(400, f"sampling.{e.code}", **e.fields)
    if not _point_inside_boundary(db, calculation_id, res.longitude, res.latitude):
        if not res.typed:
            raise i18n_error(400, "sampling.point_outside_boundary")  # a dragged position keeps its short message
        key = "point_outside_boundary_typed_two_zones" if _forest_crosses_utm_zones(db, calculation_id) else "point_outside_boundary_typed"
        raise i18n_error(400, f"sampling.{key}", point=res.describe())
    return res


def _design_has_field_data(db, calculation_id) -> bool:
    """Shared gate for add/move/delete-one-plot (owner report 2026-10-02):
    `FieldInventorySamplePlot` matches a crew's uploaded rows by block_name
    + a plot number from their own file, with no FK back to this sampling
    design -- so changing the point set once that data exists would
    silently desync it. The gate is calculation-wide, not per-plot."""
    return (
        db.query(FieldInventoryCalculation)
        .filter(FieldInventoryCalculation.calculation_id == calculation_id)
        .first()
        is not None
    )


def _point_inside_boundary(db, calculation_id, longitude: float, latitude: float) -> bool:
    """Owner report 2026-10-02 (rule 4): a moved/added plot must never land
    outside the forest boundary."""
    row = db.execute(
        text(
            """
            SELECT ST_Contains(boundary_geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) as inside
            FROM public.calculations
            WHERE id = :calc_id
            """
        ),
        {"calc_id": str(calculation_id), "lon": longitude, "lat": latitude},
    ).first()
    return bool(row and row.inside)


def _locate_point_assignment(db, calculation_id, longitude: float, latitude: float) -> Dict[str, Any]:
    """Spatial lookup for ONE lon/lat (rules 2/3 -- block/compartment/sub-
    block/sub-compartment, and sub-area, kept in sync automatically): which
    `ForestBlock` it falls in (covers every division level -- block,
    compartment, sub-block, sub-compartment all live in that one table) and
    which `ForestSubArea` category, if any.

    Scoped to a SINGLE point deliberately -- unlike
    `assign_blocks_to_sampling` (app/services/sampling.py), which bulk-
    reassigns and would renumber/clobber every other point's
    `point_index` just to place one new/moved point. Smallest-area-first
    picks the most specific containing polygon where units nest/overlap
    (e.g. a sub-compartment inside its compartment).

    Owner report 2026-10-02 ("SFM stratum field is not updated" after a
    move): a forest that has gone through raster-layer promote/trial/
    promote-again cycles can have an UNPROMOTED trial layer's `ForestBlock`
    rows still sitting in the table alongside the real, promoted ones --
    same geometry, same area, different name/case (e.g. "Block-2" from an
    unpromoted `mmu` trial vs. the real "blocks-2" from a promoted
    `union_zonal` compartment). Querying `forest_blocks` directly without
    the P2.5 promotion filter (`forest_units.queries.promoted_or_unlayered`,
    already the SSOT every other block-reading code path uses) let this
    pick either one on an area tie -- and SFM's own `sampling_plan` only
    ever lists the real, promoted unit, so picking the trial one silently
    produced a stratum lookup miss. The `LEFT JOIN`/`OR` clause below is
    that same filter inlined for this raw-SQL query.
    """
    point_wkt = f"POINT({longitude} {latitude})"
    block_row = db.execute(
        text(
            """
            SELECT fb.name FROM forest_blocks fb
            LEFT JOIN raster_layers rl ON fb.raster_layer_id = rl.id
            WHERE fb.calculation_id = :calc_id
              AND (fb.raster_layer_id IS NULL OR rl.promoted_as IS NOT NULL)
              AND ST_Contains(fb.geometry, ST_SetSRID(ST_GeomFromText(:wkt), 4326))
            ORDER BY ST_Area(fb.geometry) ASC
            LIMIT 1
            """
        ),
        {"calc_id": str(calculation_id), "wkt": point_wkt},
    ).first()
    sub_area_row = db.execute(
        text(
            """
            SELECT category, is_excluded FROM forest_sub_areas
            WHERE calculation_id = :calc_id
              AND ST_Contains(geometry, ST_SetSRID(ST_GeomFromText(:wkt), 4326))
            ORDER BY area_hectares ASC
            LIMIT 1
            """
        ),
        {"calc_id": str(calculation_id), "wkt": point_wkt},
    ).first()
    return {
        "block_name": block_row.name if block_row else None,
        "sub_area_category": sub_area_row.category if sub_area_row else None,
        "sub_area_excluded": bool(sub_area_row.is_excluded) if sub_area_row else False,
    }


def _enrich_one_sample_point(
    db, design_id, calculation_id, point_index: int, longitude: float, latitude: float,
    block_number: Optional[int], block_name: Optional[str], zone_type: str,
) -> Dict[str, Any]:
    """Same per-point computation `get_sampling_points` runs in its own loop
    (elevation, UTM, nearest topographic feature, distance from boundary) --
    but for exactly ONE point, so add/move can patch just that point into
    the `points_data` cache instead of invalidating it and forcing a full
    recompute over every point in the design.

    Owner report 2026-10-02 ("it takes more time"): a move/add used to set
    `points_data = NULL`, and the next read recomputed elevation + nearest-
    ridge/valley for the WHOLE design (every point, not just the moved one)
    -- the dominant cost for a design with hundreds of plots. This keeps
    the recompute O(1) per move/add instead of O(N).
    """
    from pyproj import Transformer
    from shapely import wkt as shapely_wkt
    from shapely.geometry import Point

    def safe_float(value, decimals=2):
        if value is None:
            return None
        try:
            import math
            if math.isnan(value) or math.isinf(value):
                return None
            return float(f"{value:.{decimals}f}")
        except (TypeError, ValueError):
            return None

    def safe_int(value):
        if value is None:
            return None
        try:
            import math
            if math.isnan(value) or math.isinf(value):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    boundary_result = db.execute(
        text("SELECT ST_AsText(boundary_geom) as wkt FROM public.calculations WHERE id = :calc_id"),
        {"calc_id": str(calculation_id)},
    ).first()
    boundary_wkt = boundary_result.wkt if boundary_result else None

    utm_zone = 44 if longitude < 84 else 45
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:326{utm_zone}", always_xy=True)
    utm_easting, utm_northing = transformer.transform(longitude, latitude)

    distance_from_boundary = None
    if boundary_wkt:
        try:
            boundary_geom = shapely_wkt.loads(boundary_wkt)
            distance_from_boundary = (
                Point(longitude, latitude).distance(boundary_geom.boundary) * METERS_PER_DEGREE_LAT
            )
        except Exception:
            logger.warning(
                "distance-from-boundary unavailable for one enriched point", exc_info=True,
            )

    elevation_m = extract_elevation_at_point(db, longitude, latitude)

    topo_feature = None
    if boundary_wkt:
        clipped_features = preclip_topographic_features(db=db, boundary_wkt=boundary_wkt, buffer_meters=100.0)
        if clipped_features:
            topo_feature = find_nearest_topographic_feature_optimized(
                db=db, longitude=longitude, latitude=latitude, clipped_features=clipped_features,
                search_radius_meters=100.0, prefer_rivers=True, min_distance_threshold=20.0,
            )

    topo_context = None
    if topo_feature:
        topo_context = f"{int(topo_feature.get('distance_meters', 0))}m {topo_feature.get('direction', '')} of {topo_feature.get('feature_name', 'unnamed feature')}"

    return {
        "id": f"{design_id}_{point_index}",
        "plot_number": point_index + 1,
        "block_number": block_number if block_number is not None else 1,
        "block_name": block_name or f"Block {block_number if block_number is not None else 1}",
        "zone_type": zone_type,
        "longitude": safe_float(longitude, 7),
        "latitude": safe_float(latitude, 7),
        "utm_easting": safe_float(utm_easting, 2),
        "utm_northing": safe_float(utm_northing, 2),
        "utm_zone": f"{utm_zone}N",
        "distance_from_boundary": safe_float(distance_from_boundary, 2),
        "elevation_m": safe_int(elevation_m),
        "topographic_context": topo_context,
        "nearest_feature_type": topo_feature.get("feature_type") if topo_feature else None,
        "nearest_feature_name": topo_feature.get("feature_name") if topo_feature else None,
        "nearest_feature_distance_m": safe_int(topo_feature.get("distance_meters", 0) if topo_feature else None),
        "nearest_feature_direction": topo_feature.get("direction") if topo_feature else None,
        "nearest_feature_bearing": safe_int(topo_feature.get("bearing_degrees", 0) if topo_feature else None),
    }


@router.post("/sampling/{design_id}/points")
def add_sample_plot(
    design_id: UUID,
    body: SamplePlotPointBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add ONE sample plot at (longitude, latitude) to the end of the design's
    point set. Same two rules as move/delete: refused once field inventory
    data exists, and the point must be inside the forest boundary.
    """
    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Sampling design not found")

    calculation = (
        db.query(Calculation)
        .filter(Calculation.id == design.calculation_id, Calculation.user_id == current_user.id)
        .first()
    )
    if not calculation:
        raise HTTPException(status_code=403, detail="Access denied")

    if _design_has_field_data(db, design.calculation_id):
        raise i18n_error(409, "sampling.cannot_delete_plot_field_data_exists")

    if not _point_inside_boundary(db, design.calculation_id, body.longitude, body.latitude):
        raise i18n_error(400, "sampling.point_outside_boundary")

    from shapely import wkt as shapely_wkt
    from shapely.geometry import MultiPoint, Point

    wkt_result = db.execute(
        text("SELECT ST_AsText(points_geometry) as wkt FROM public.sampling_designs WHERE id = :design_id"),
        {"design_id": str(design_id)},
    ).first()
    existing_points = (
        list(shapely_wkt.loads(wkt_result.wkt).geoms) if wkt_result and wkt_result.wkt else []
    )
    new_index = len(existing_points)
    new_points = existing_points + [Point(body.longitude, body.latitude)]
    new_wkt = MultiPoint(new_points).wkt

    location = _locate_point_assignment(db, design.calculation_id, body.longitude, body.latitude)
    assignments = list(design.points_block_assignment or [])
    assignments.append({
        "point_index": new_index,
        "block_name": location["block_name"],
        "block_number": None,
        "zone_type": "productive",
        "sub_area_category": location["sub_area_category"],
        "sub_area_excluded": location["sub_area_excluded"],
    })

    # The point itself (geometry + block/sub-area assignment + total_points)
    # is the ONE thing that must never be lost -- committed on its own,
    # before anything else touches this session. Owner report 2026-10-02
    # ("system says added but I cannot see it"): the enrichment helper below
    # (`_enrich_one_sample_point`, added for the earlier performance fix)
    # calls shared geospatial utilities that recover from a failed query by
    # calling `db.rollback()` internally (`geospatial_vector_optimized.py`,
    # `geospatial.py`) -- when that ran in the SAME uncommitted transaction
    # as this write, it silently discarded the just-added point even though
    # the endpoint still returned success. Committing the real write first
    # makes it durable regardless of what the enrichment step does next.
    try:
        db.execute(
            text("UPDATE public.sampling_designs SET points_geometry = ST_GeomFromText(:wkt, 4326) WHERE id = :design_id"),
            {"wkt": new_wkt, "design_id": str(design_id)},
        )
        db.execute(
            text("UPDATE public.sampling_designs SET points_block_assignment = CAST(:assignments AS jsonb) WHERE id = :design_id"),
            {"assignments": json.dumps(assignments), "design_id": str(design_id)},
        )
        db.execute(
            text("UPDATE public.sampling_designs SET total_points = :n WHERE id = :design_id"),
            {"n": len(new_points), "design_id": str(design_id)},
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Add failed: {str(e)}")

    # Best-effort cache patch, its OWN transaction, strictly after the real
    # write above is durable. `points_data` is just a read-side cache (UTM/
    # elevation/topo) -- patch the one new point into it (O(1)) so the next
    # read doesn't recompute the whole design, but if anything here fails,
    # fall back to invalidating the cache (NULL) rather than leaving it
    # stale: the next read is then merely slow (full recompute), never wrong.
    try:
        db.refresh(design)
        cached = design.points_data
        if cached and isinstance(cached.get("points"), list):
            new_point_enriched = _enrich_one_sample_point(
                db, design_id, design.calculation_id, new_index, body.longitude, body.latitude,
                block_number=None, block_name=location["block_name"], zone_type="productive",
            )
            cached = dict(cached)
            cached["points"] = cached["points"] + [new_point_enriched]
            db.execute(
                text("UPDATE public.sampling_designs SET points_data = CAST(:points_data AS jsonb) WHERE id = :design_id"),
                {"points_data": json.dumps(cached), "design_id": str(design_id)},
            )
            db.commit()
    except Exception:
        logger.warning("sampling points cache update failed for design %s; clearing it", design_id, exc_info=True)
        db.rollback()
        try:
            db.execute(
                text("UPDATE public.sampling_designs SET points_data = NULL WHERE id = :design_id"),
                {"design_id": str(design_id)},
            )
            db.commit()
        except Exception:  # noqa: BLE001 -- clearing the cache is best effort; the points are recomputed on the next read
            db.rollback()

    return {
        "success": True,
        "design_id": str(design_id),
        "plot_number": new_index + 1,
        "total_points": len(new_points),
        "block_name": location["block_name"],
    }


@router.patch("/sampling/{design_id}/points/{plot_number}")
def move_sample_plot(
    design_id: UUID,
    plot_number: int,
    body: SamplePlotMoveBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move ONE existing sample plot to a new (longitude, latitude). Same two
    rules as add/delete: refused once field inventory data exists, and the
    new location must be inside the forest boundary. The plot's block/
    compartment/sub-block/sub-compartment and sub-area assignment are
    recomputed from the new location automatically.
    """
    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Sampling design not found")

    calculation = (
        db.query(Calculation)
        .filter(Calculation.id == design.calculation_id, Calculation.user_id == current_user.id)
        .first()
    )
    if not calculation:
        raise HTTPException(status_code=403, detail="Access denied")

    if _design_has_field_data(db, design.calculation_id):
        raise i18n_error(409, "sampling.cannot_delete_plot_field_data_exists")

    from shapely import wkt as shapely_wkt
    from shapely.geometry import MultiPoint, Point

    wkt_result = db.execute(
        text("SELECT ST_AsText(points_geometry) as wkt FROM public.sampling_designs WHERE id = :design_id"),
        {"design_id": str(design_id)},
    ).first()
    if not wkt_result or not wkt_result.wkt:
        raise HTTPException(status_code=404, detail="No sample plots found for this design")

    points = list(shapely_wkt.loads(wkt_result.wkt).geoms)
    idx = plot_number - 1
    if idx < 0 or idx >= len(points):
        raise HTTPException(status_code=404, detail=f"Plot {plot_number} not found")

    resolved = _resolve_move(db, design.calculation_id, points[idx], body)  # friendly 400 if invalid or outside the forest
    new_lon, new_lat = resolved.longitude, resolved.latitude
    points[idx] = Point(new_lon, new_lat)
    new_wkt = MultiPoint(points).wkt

    location = _locate_point_assignment(db, design.calculation_id, new_lon, new_lat)
    assignments = list(design.points_block_assignment or [])
    existing_entry = next((a for a in assignments if a.get("point_index") == idx), None)
    zone_type = (existing_entry or {}).get("zone_type", "productive")
    block_number = (existing_entry or {}).get("block_number")
    updated = False
    for a in assignments:
        if a.get("point_index") == idx:
            a["block_name"] = location["block_name"]
            a["sub_area_category"] = location["sub_area_category"]
            a["sub_area_excluded"] = location["sub_area_excluded"]
            updated = True
            break
    if not updated:
        assignments.append({
            "point_index": idx,
            "block_name": location["block_name"],
            "block_number": None,
            "zone_type": "productive",
            "sub_area_category": location["sub_area_category"],
            "sub_area_excluded": location["sub_area_excluded"],
        })

    # The move itself (geometry + assignment) must be durable before
    # anything else touches this session. Owner report 2026-10-02 ("although
    # it goes back to its original location"): `_enrich_one_sample_point`
    # below calls shared geospatial utilities that recover from a failed
    # query by calling `db.rollback()` internally -- running that in the
    # SAME uncommitted transaction as this write silently discarded the
    # move even though the endpoint still returned success.
    try:
        db.execute(
            text("UPDATE public.sampling_designs SET points_geometry = ST_GeomFromText(:wkt, 4326) WHERE id = :design_id"),
            {"wkt": new_wkt, "design_id": str(design_id)},
        )
        db.execute(
            text("UPDATE public.sampling_designs SET points_block_assignment = CAST(:assignments AS jsonb) WHERE id = :design_id"),
            {"assignments": json.dumps(assignments), "design_id": str(design_id)},
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Move failed: {str(e)}")

    # Best-effort cache patch, its OWN transaction, strictly after the real
    # move above is durable. On any failure, fall back to invalidating the
    # cache rather than leaving it stale -- the next read is then merely
    # slow (full recompute), never wrong.
    try:
        db.refresh(design)
        cached = design.points_data
        if cached and isinstance(cached.get("points"), list) and idx < len(cached["points"]):
            moved_point_enriched = _enrich_one_sample_point(
                db, design_id, design.calculation_id, idx, new_lon, new_lat,
                block_number=block_number, block_name=location["block_name"], zone_type=zone_type,
            )
            cached = dict(cached)
            cached["points"] = list(cached["points"])
            cached["points"][idx] = moved_point_enriched
            db.execute(
                text("UPDATE public.sampling_designs SET points_data = CAST(:points_data AS jsonb) WHERE id = :design_id"),
                {"points_data": json.dumps(cached), "design_id": str(design_id)},
            )
            db.commit()
    except Exception:
        logger.warning("sampling points cache update failed for design %s; clearing it", design_id, exc_info=True)
        db.rollback()
        try:
            db.execute(
                text("UPDATE public.sampling_designs SET points_data = NULL WHERE id = :design_id"),
                {"design_id": str(design_id)},
            )
            db.commit()
        except Exception:  # noqa: BLE001 -- clearing the cache is best effort; the points are recomputed on the next read
            db.rollback()

    return {
        "success": True,
        "design_id": str(design_id),
        "plot_number": plot_number,
        "block_name": location["block_name"],
        "longitude": new_lon,
        "latitude": new_lat,
        "utm_zone": resolved.zone,
        "utm_easting": round(resolved.easting, 2),
        "utm_northing": round(resolved.northing, 2),
    }


@router.delete("/sampling/{design_id}/points/{plot_number}")
def delete_sample_plot(
    design_id: UUID,
    plot_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete ONE sample plot (1-based `plot_number`, same numbering the
    map/table/export already use) from a design's point set.

    Owner report 2026-10-02: a map-workspace "Delete" for an individual
    sample plot only makes sense while no field crew has recorded real data
    for this forest yet -- once field inventory data exists, deleting or
    renumbering a plot here would silently break that data's linkage
    (`FieldInventorySamplePlot` matches by `block_name` + a plot number from
    the UPLOADED FILE, with no FK back to this design, so it has no way to
    follow a renumber). The gate is therefore calculation-wide, not
    per-plot: ANY `FieldInventoryCalculation` existing for this design's
    calculation blocks every plot delete, not just a plot a crew happened
    to visit.
    """
    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Sampling design not found")

    calculation = (
        db.query(Calculation)
        .filter(Calculation.id == design.calculation_id, Calculation.user_id == current_user.id)
        .first()
    )
    if not calculation:
        raise HTTPException(status_code=403, detail="Access denied")

    if _design_has_field_data(db, design.calculation_id):
        raise i18n_error(409, "sampling.cannot_delete_plot_field_data_exists")

    from shapely import wkt as shapely_wkt
    from shapely.geometry import MultiPoint

    wkt_result = db.execute(
        text(
            """
            SELECT ST_AsText(points_geometry) as wkt
            FROM public.sampling_designs
            WHERE id = :design_id
            """
        ),
        {"design_id": str(design_id)},
    ).first()
    if not wkt_result or not wkt_result.wkt:
        raise HTTPException(status_code=404, detail="No sample plots found for this design")

    multipoint = shapely_wkt.loads(wkt_result.wkt)
    points = list(multipoint.geoms)
    idx = plot_number - 1
    if idx < 0 or idx >= len(points):
        raise HTTPException(status_code=404, detail=f"Plot {plot_number} not found")

    if len(points) <= 1:
        raise i18n_error(400, "sampling.cannot_delete_last_plot")

    remaining_points = [p for i, p in enumerate(points) if i != idx]
    new_wkt = MultiPoint(remaining_points).wkt

    # Drop the removed point's assignment entry and shift every later
    # point_index down by one -- `plot_number` everywhere else (map-layers,
    # the points export, the attribute table) is derived positionally as
    # `point_index + 1`, so the remaining plots must stay contiguously
    # numbered 1..N-1 after this, not carry a gap at the deleted number.
    assignments = design.points_block_assignment or []
    new_assignments = []
    for a in assignments:
        pi = a.get("point_index")
        if pi is None or pi == idx:
            continue
        a = dict(a)
        if pi > idx:
            a["point_index"] = pi - 1
        new_assignments.append(a)

    try:
        db.execute(
            text(
                "UPDATE public.sampling_designs SET points_geometry = ST_GeomFromText(:wkt, 4326) WHERE id = :design_id"
            ),
            {"wkt": new_wkt, "design_id": str(design_id)},
        )
        db.execute(
            text(
                "UPDATE public.sampling_designs SET points_block_assignment = CAST(:assignments AS jsonb) WHERE id = :design_id"
            ),
            {"assignments": json.dumps(new_assignments), "design_id": str(design_id)},
        )
        # `total_points` must stay in sync with the real point count. None of
        # the SURVIVING points' own elevation/UTM/topo values change from a
        # delete -- only their position/label does -- so patch the cached
        # enrichment blob in place (drop the removed row, relabel `id`/
        # `plot_number` for everything after it) instead of nulling it,
        # which forced a full O(N) recompute of every remaining point on
        # the next read.
        cached = design.points_data
        if cached and isinstance(cached.get("points"), list):
            cached = dict(cached)
            relabeled = []
            for i, p in enumerate(cached["points"]):
                if i == idx:
                    continue
                p = dict(p)
                new_i = i - 1 if i > idx else i
                p["id"] = f"{design_id}_{new_i}"
                p["plot_number"] = new_i + 1
                relabeled.append(p)
            cached["points"] = relabeled
            db.execute(
                text(
                    "UPDATE public.sampling_designs SET total_points = :n, points_data = CAST(:points_data AS jsonb) WHERE id = :design_id"
                ),
                {"n": len(remaining_points), "points_data": json.dumps(cached), "design_id": str(design_id)},
            )
        else:
            db.execute(
                text(
                    "UPDATE public.sampling_designs SET total_points = :n WHERE id = :design_id"
                ),
                {"n": len(remaining_points), "design_id": str(design_id)},
            )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

    return {
        "success": True,
        "design_id": str(design_id),
        "deleted_plot_number": plot_number,
        "remaining_points": len(remaining_points),
    }


@router.post("/calculations/{calculation_id}/preview-accessible-forest")
def preview_accessible_forest(
    calculation_id: UUID,
    filter_tree_cover: bool = Query(True, description="Filter to tree cover only"),
    filter_slope: bool = Query(False, description="Filter by slope accessibility"),
    max_slope_degrees: float = Query(
        45.0, description="Maximum slope threshold in degrees"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # business: preview lets user see accessible forest BEFORE committing to sampling design
    # constraint: slope filter uses DEM-based ST_Slope() — 45° max per CFMG accessibility
    """
    Preview accessible and protected forest areas BEFORE creating sampling design.

    Returns:
    - Boundary geometry
    - Accessible forest area (GREEN) - tree cover with acceptable slope
    - Protected forest area (RED) - tree cover with steep slope
    - Area statistics

    This allows users to visualize which areas will be sampled before generating the design.
    """
    # Verify calculation exists and belongs to user
    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == calculation_id, Calculation.user_id == current_user.id
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    if not calculation.boundary_geom:
        raise i18n_error(400, "calculations.no_geometry")

    try:
        # Set statement timeout per-transaction (SET LOCAL auto-resets on commit/rollback).
        # Global 60s timeout is already enforced via connect_args in database.py.
        db.execute(
            text("SET LOCAL statement_timeout = '120000'")
        )  # 120 seconds = 2 minutes

        # Get boundary WKT
        boundary_wkt_query = text(
            """
            SELECT ST_AsText(boundary_geom) as wkt,
                   ST_AsGeoJSON(boundary_geom) as geojson
            FROM public.calculations
            WHERE id = :calc_id
        """
        )
        boundary_result = db.execute(
            boundary_wkt_query, {"calc_id": str(calculation_id)}
        ).first()

        if not boundary_result:
            raise HTTPException(status_code=404, detail="Boundary not found")

        boundary_wkt = boundary_result.wkt
        boundary_geojson = json.loads(boundary_result.geojson)

        # Calculate area statistics
        # IMPORTANT: Slope visualization is too slow for preview
        # We show tree cover only, slope filtering happens during actual sampling
        from app.services.tree_cover_analysis import calculate_accessible_forest_area

        if filter_slope:
            # User requested slope filtering, but it's too slow for preview
            # Show tree cover only with a note
            import logging

            logging.warning(
                f"Slope filtering requested in preview - showing tree cover only for performance"
            )

        area_stats = calculate_accessible_forest_area(
            db=db,
            geometry_wkt=boundary_wkt,
            filter_tree_cover=filter_tree_cover,
            filter_slope=False,  # Always False for preview - too slow
            max_slope_degrees=max_slope_degrees,
        )

        # Add note if slope was requested but not applied
        if filter_slope:
            area_stats["preview_note"] = (
                "Preview shows tree cover only. Slope filtering will be applied during sampling design generation."
            )

        # Extract accessible forest mask (GREEN areas)
        # NOTE: Slope visualization removed for performance - too slow
        # Preview shows tree cover only, slope filtering happens during sampling
        accessible_forest_geojson = None
        if filter_tree_cover:
            # Always use tree cover only for preview (no slope - too slow)
            if False:  # DISABLED: Slope filtering too slow for preview
                # DISABLED: This was too slow and causing 0.00 ha results
                accessible_query = text(
                    """
                    WITH boundary AS (
                        SELECT ST_GeomFromText(:wkt, 4326) as geom
                    ),
                    tree_pixels AS (
                        SELECT
                            val,
                            geom,
                            ST_Centroid(geom) as center
                        FROM (
                            SELECT (ST_PixelAsPolygons(
                                ST_Clip(rast, b.geom, 0.0, true), 1
                            )).*
                            FROM rasters.esa_world_cover, boundary b
                            WHERE ST_Intersects(rast, b.geom)
                        ) pixels
                        WHERE val = 10
                    ),
                    tree_in_boundary AS (
                        SELECT geom, center
                        FROM tree_pixels, boundary b
                        WHERE ST_Within(center, b.geom)
                    ),
                    dem_slope_tiles AS (
                        SELECT ST_Slope(rast, 1, '32BF') as slope_rast
                        FROM rasters.dem, boundary
                        WHERE ST_Intersects(rast, boundary.geom)
                    ),
                    accessible_forest AS (
                        SELECT t.geom
                        FROM tree_in_boundary t
                        LEFT JOIN LATERAL (
                            SELECT ST_Value(slope_rast, t.center) as slope_degrees
                            FROM dem_slope_tiles
                            WHERE ST_Intersects(slope_rast, t.center)
                            LIMIT 1
                        ) s ON true
                        WHERE s.slope_degrees IS NOT NULL
                          AND s.slope_degrees <= :max_slope
                    )
                    SELECT ST_AsGeoJSON(
                        ST_SimplifyPreserveTopology(
                            ST_Union(geom),
                            0.0001
                        )
                    ) as geojson
                    FROM accessible_forest
                    WHERE geom IS NOT NULL
                """
                )

                try:
                    accessible_result = db.execute(
                        accessible_query,
                        {"wkt": boundary_wkt, "max_slope": max_slope_degrees},
                    ).first()

                    if accessible_result and accessible_result.geojson:
                        accessible_forest_geojson = json.loads(
                            accessible_result.geojson
                        )
                except Exception as e:
                    import logging

                    logging.warning(
                        f"Failed to extract accessible forest mask: {str(e)}"
                    )
            else:
                # Tree cover only, no slope filtering
                accessible_mask_wkt = extract_accessible_forest_mask(
                    db=db,
                    geometry_wkt=boundary_wkt,
                    filter_slope=False,
                    max_slope_degrees=max_slope_degrees,
                )

                if accessible_mask_wkt:
                    accessible_geojson_query = text(
                        """
                        SELECT ST_AsGeoJSON(ST_GeomFromText(:wkt, 4326)) as geojson
                    """
                    )
                    accessible_result = db.execute(
                        accessible_geojson_query, {"wkt": accessible_mask_wkt}
                    ).first()

                    if accessible_result:
                        accessible_forest_geojson = json.loads(
                            accessible_result.geojson
                        )

        # Extract protected forest mask (RED areas - steep slopes)
        # DISABLED: Too slow for preview, causes 0.00 ha results
        # Slope filtering happens during actual sampling, not in preview
        protected_forest_geojson = None
        if False:  # DISABLED: filter_tree_cover and filter_slope - too slow
            # Get steep forest areas (tree cover with slope > threshold)
            # OPTIMIZED: Calculate slope once per DEM tile, then sample
            protected_query = text(
                """
                WITH boundary AS (
                    SELECT ST_GeomFromText(:wkt, 4326) as geom
                ),
                -- Extract tree pixels using optimized method
                tree_pixels AS (
                    SELECT
                        val,
                        geom,
                        ST_Centroid(geom) as center
                    FROM (
                        SELECT (ST_PixelAsPolygons(
                            ST_Clip(rast, b.geom, 0.0, true), 1
                        )).*
                        FROM rasters.esa_world_cover, boundary b
                        WHERE ST_Intersects(rast, b.geom)
                    ) pixels
                    WHERE val = 10  -- Tree cover only
                ),
                tree_in_boundary AS (
                    SELECT geom, center
                    FROM tree_pixels, boundary b
                    WHERE ST_Within(center, b.geom)
                ),
                -- OPTIMIZED: Pre-calculate slope for DEM tiles
                dem_slope_tiles AS (
                    SELECT ST_Slope(rast, 1, '32BF') as slope_rast
                    FROM rasters.dem, boundary
                    WHERE ST_Intersects(rast, boundary.geom)
                ),
                -- Sample slope at tree pixel centers
                tree_with_slope AS (
                    SELECT
                        t.geom,
                        ST_Value(dst.slope_rast, t.center) as slope_degrees
                    FROM tree_in_boundary t
                    LEFT JOIN LATERAL (
                        SELECT slope_rast
                        FROM dem_slope_tiles
                        WHERE ST_Intersects(slope_rast, t.center)
                        LIMIT 1
                    ) dst ON true
                ),
                steep_forest AS (
                    SELECT geom
                    FROM tree_with_slope
                    WHERE slope_degrees IS NOT NULL
                      AND slope_degrees > :max_slope
                )
                SELECT ST_AsGeoJSON(
                    ST_SimplifyPreserveTopology(
                        ST_Union(geom),
                        0.0001
                    )
                ) as geojson
                FROM steep_forest
                WHERE geom IS NOT NULL
            """
            )

            try:
                protected_result = db.execute(
                    protected_query,
                    {"wkt": boundary_wkt, "max_slope": max_slope_degrees},
                ).first()

                if protected_result and protected_result.geojson:
                    protected_forest_geojson = json.loads(protected_result.geojson)
            except Exception as e:
                import logging

                logging.warning(f"Failed to extract protected forest mask: {str(e)}")
                # Continue without protected forest visualization

        return {
            "boundary": {
                "type": "Feature",
                "geometry": boundary_geojson,
                "properties": {
                    "name": calculation.forest_name or "Forest Boundary",
                    "layer_type": "boundary",
                },
            },
            "accessible_forest": (
                {
                    "type": "Feature",
                    "geometry": accessible_forest_geojson,
                    "properties": {
                        "layer_type": "accessible_forest",
                        "color": "green",
                        "description": "Resource Effective Area - Can be sampled and managed",
                    },
                }
                if accessible_forest_geojson
                else None
            ),
            "protected_forest": (
                {
                    "type": "Feature",
                    "geometry": protected_forest_geojson,
                    "properties": {
                        "layer_type": "protected_forest",
                        "color": "red",
                        "description": "Protected Area - Steep slopes, should be preserved",
                    },
                }
                if protected_forest_geojson
                else None
            ),
            "area_statistics": area_stats,
            "filter_settings": {
                "filter_tree_cover": filter_tree_cover,
                "filter_slope": filter_slope,
                "max_slope_degrees": max_slope_degrees,
            },
        }

    except Exception as e:
        import logging

        logging.error(f"Preview accessible forest failed: {str(e)}", exc_info=True)

        # Check if it's a timeout error
        error_msg = str(e).lower()
        if (
            "timeout" in error_msg
            or "statement timeout" in error_msg
            or "canceling statement" in error_msg
        ):
            raise HTTPException(
                status_code=408,
                detail=(
                    "Analysis timeout: This forest area is too large or complex for real-time preview. "
                    "Try: (1) Disable slope filter for faster preview, or "
                    "(2) Skip preview and create sampling design directly (slope filtering will still work during sampling)."
                ),
            )
        else:
            raise HTTPException(
                status_code=500, detail=f"Failed to preview forest areas: {str(e)}"
            )
    finally:
        # statement_timeout set via SET LOCAL auto-resets on transaction end — no RESET needed
        pass


@router.get("/sampling/{design_id}/map-layers")
def get_sampling_map_layers(
    design_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get GeoJSON layers for sampling map visualization:
    - Block boundary
    - Accessible forest area (after tree cover + slope filtering)
    - Sampling points

    Returns GeoJSON FeatureCollection for map display.
    """
    # Get sampling design
    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()

    if not design:
        raise HTTPException(status_code=404, detail="Sampling design not found")

    # Verify user has access
    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == design.calculation_id,
            Calculation.user_id == current_user.id,
        )
        .first()
    )

    if not calculation:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get boundary geometry
    boundary_query = text(
        """
        SELECT ST_AsGeoJSON(boundary_geom) as boundary_geojson
        FROM public.calculations
        WHERE id = :calc_id
    """
    )
    boundary_result = db.execute(
        boundary_query, {"calc_id": str(design.calculation_id)}
    ).first()

    if not boundary_result:
        raise HTTPException(status_code=404, detail="Boundary not found")

    boundary_geojson = json.loads(boundary_result.boundary_geojson)

    # Get forest blocks (blocks, compartments, sub-compartments)
    forest_blocks_geojson = None
    from sqlalchemy import func as sa_func

    from ..services.forest_units.model import DEPTH_SUB

    blocks = (
        db.query(
            ForestBlock.id,
            ForestBlock.name,
            ForestBlock.block_name,
            ForestBlock.compartment_code,
            ForestBlock.division_level,
            ForestBlock.is_compartment,
            ForestBlock.area_hectares,
            sa_func.ST_AsGeoJSON(ForestBlock.geometry).label("geojson"),
        )
        .filter(ForestBlock.calculation_id == design.calculation_id)
        .order_by(ForestBlock.division_level, ForestBlock.index)
        .all()
    )

    if blocks:
        block_features = []
        for block in blocks:
            block_geom = json.loads(block.geojson)
            # FS-1c.1: same fix as `_preview_forest_blocks_layer` above - the branch (`is_compartment`),
            # never the depth alone, decides the label (I10).
            if not block.is_compartment:
                level_name = "Block"
            elif (block.division_level or 0) >= DEPTH_SUB:
                level_name = "Sub-compartment"
            else:
                level_name = "Compartment"
            block_features.append(
                {
                    "type": "Feature",
                    "geometry": block_geom,
                    "properties": {
                        "id": str(block.id),
                        "name": block.name,
                        "unit_key": _unit_key(block),
                        "division_level": block.division_level,
                        "is_compartment": bool(block.is_compartment),
                        "area_hectares": block.area_hectares,
                        "level_name": level_name,
                    },
                }
            )
        forest_blocks_geojson = {
            "type": "FeatureCollection",
            "features": block_features,
        }

    # Get rivers clipped to forest boundary
    rivers_geojson = None
    try:
        river_query = text(
            """
            SELECT
                COALESCE(NULLIF(TRIM(r."river name"), ''), 'River') as name,
                ST_AsGeoJSON(ST_Intersection(r.shape, calc_geom.geom)) as geometry
            FROM river.river84 r,
                (SELECT boundary_geom as geom FROM public.calculations WHERE id = :calc_id) calc_geom
            WHERE ST_Intersects(r.shape, calc_geom.geom)
            LIMIT 50
        """
        )
        river_results = db.execute(
            river_query, {"calc_id": str(design.calculation_id)}
        ).fetchall()
        if river_results:
            river_features = []
            for r in river_results:
                geom = json.loads(r.geometry)
                if geom and geom.get("type") and geom["type"] != "GeometryCollection":
                    river_features.append(
                        {
                            "type": "Feature",
                            "geometry": geom,
                            "properties": {"name": r.name or "River"},
                        }
                    )
            if river_features:
                rivers_geojson = {
                    "type": "FeatureCollection",
                    "features": river_features,
                }
    except Exception as e:
        logger.warning(f"Failed to query rivers: {e}")
        db.rollback()
        rivers_geojson = None

    # Get accessible forest mask (if filters were applied)
    accessible_forest_geojson = None
    filter_info = design.default_parameters or {}

    if filter_info.get("filter_tree_cover") or filter_info.get("filter_slope"):
        # Get boundary WKT
        boundary_wkt_query = text(
            """
            SELECT ST_AsText(boundary_geom) as wkt
            FROM public.calculations
            WHERE id = :calc_id
        """
        )
        boundary_wkt_result = db.execute(
            boundary_wkt_query, {"calc_id": str(design.calculation_id)}
        ).first()

        if boundary_wkt_result:
            accessible_mask_wkt = extract_accessible_forest_mask(
                db=db,
                geometry_wkt=boundary_wkt_result.wkt,
                filter_slope=filter_info.get("filter_slope", False),
                max_slope_degrees=filter_info.get("max_slope_degrees", 45.0),
            )

            if accessible_mask_wkt:
                # Convert WKT to GeoJSON
                accessible_geojson_query = text(
                    """
                    SELECT ST_AsGeoJSON(ST_GeomFromText(:wkt, 4326)) as geojson
                """
                )
                accessible_result = db.execute(
                    accessible_geojson_query, {"wkt": accessible_mask_wkt}
                ).first()

                if accessible_result:
                    accessible_forest_geojson = json.loads(accessible_result.geojson)

    # Get sampling points
    points_query = text(
        """
        SELECT ST_AsGeoJSON(points_geometry) as points_geojson,
               points_block_assignment
        FROM public.sampling_designs
        WHERE id = :design_id
    """
    )
    points_result = db.execute(points_query, {"design_id": str(design_id)}).first()

    points_geojson = None
    if points_result and points_result.points_geojson:
        points_data = json.loads(points_result.points_geojson)
        block_assignments = points_result.points_block_assignment or []

        # Convert MultiPoint to FeatureCollection with individual point features
        features = []
        if points_data["type"] == "MultiPoint":
            for i, coord in enumerate(points_data["coordinates"]):
                # Find block assignment
                block_info = next(
                    (b for b in block_assignments if b.get("point_index") == i), None
                )
                block_name = (
                    block_info.get("block_name", f"Plot {i+1}")
                    if block_info
                    else f"Plot {i+1}"
                )
                zone_type = (
                    block_info.get("zone_type", "Productive")
                    if block_info
                    else "Productive"
                )

                feature = {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": coord},
                    "properties": {
                        "plot_number": i + 1,
                        "block_name": block_name,
                        "zone_type": zone_type,
                        "plot_id": f"P{i+1}",
                    },
                }
                features.append(feature)

        points_geojson = {"type": "FeatureCollection", "features": features}

    return {
        "boundary": {
            "type": "Feature",
            "geometry": boundary_geojson,
            "properties": {
                "name": calculation.forest_name or "Forest Boundary",
                "layer_type": "boundary",
            },
        },
        "accessible_forest": (
            {
                "type": "Feature",
                "geometry": accessible_forest_geojson,
                "properties": {"layer_type": "accessible_forest"},
            }
            if accessible_forest_geojson
            else None
        ),
        "forest_blocks": forest_blocks_geojson,
        "rivers": rivers_geojson,
        "sampling_points": points_geojson,
        "filter_settings": filter_info,
        "calculation_id": str(design.calculation_id),
    }


def _touching_by_name(
    db: Session,
    calculation_id,
    areas: dict,
    tol_m: float = DEFAULT_TOUCH_TOLERANCE_M,
) -> dict:
    """Which leaf units share a boundary, keyed by unit name.

    P8 6: *touching* is a hard requirement before size is even considered, because
    pure "nearest" can pick another sliver and merging sliver-into-sliver is no
    improvement.

    ``ST_Touches`` alone is too strict for digitised geometry - hairline gaps are
    normal - so a sub-millimetre ``ST_DWithin`` is allowed alongside it. Bounding-box
    tests are deliberately not used: they would call units neighbours across a real
    gap, and the test suite pins that a 30 m gap is not bridged while a 0.5 mm one
    is.
    """
    from ..services.forest_units import sql as unit_sql

    rows = db.execute(
        text(
            """
            SELECT a.block_name AS a_name, b.block_name AS b_name
            FROM forest_blocks a
            JOIN forest_blocks b
              ON a.calculation_id = b.calculation_id
             AND a.id <> b.id
             AND a.block_name IS NOT NULL
             AND b.block_name IS NOT NULL
             AND {leaf_a}
             AND {leaf_b}
             AND (ST_Touches(a.geometry, b.geometry)
                  OR ST_DWithin(a.geometry, b.geometry, :tol))
            WHERE a.calculation_id = :cid
            """.format(leaf_a=unit_sql.leaf("a"), leaf_b=unit_sql.leaf("b"))
        ),
        {"cid": str(calculation_id), "tol": tol_m},
    ).fetchall()

    out: dict = {name: [] for name in areas}
    for a_name, b_name in rows:
        if a_name in out and b_name in out:
            out[a_name].append(b_name)
    return out



# ---------------------------------------------------------------------------
# P8 tier 1 - unit size review (read-only)
# ---------------------------------------------------------------------------
@router.get("/calculations/{calculation_id}/unit-size-review")
def unit_size_review(
    calculation_id: UUID,
    review_pct: float = Query(
        DEFAULT_REVIEW_PCT,
        ge=0.0,
        le=100.0,
        description=(
            "Field rule of thumb: a unit under this share of the forest boundary area "
            "is flagged for review. A default, not a law - the absolute MMU still "
            "decides whether a merge is proposed."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Classify every leaf unit by size, *before* any sampling design exists.

    A unit that receives no sample point gets no field-inventory summary
    (``field_inventory_service.py:1347``), so it vanishes from the inventory with no
    message. This is the prevention half of P8: say so while a merge still costs
    nothing. It is strictly read-only - it classifies, proposes, and changes
    nothing. Applying a merge is the caller's job via ``merge_features``, so that
    ``structure_write`` performs the invalidation.

    Two thresholds, deliberately different in kind:

    - **MMU** (absolute, ``MMU_SLIVER_AREA_M2``) decides the *action*. 5% of a
      forest does not scale - 18.3 ha on this forest but 183 ha on a 3,660 ha one -
      and a management unit's minimum should not move with forest size.
    - **review_pct** (relative) only decides who gets *looked at*. It catches the
      mid-sized units a 1 ha MMU is blind to, and never authorises a merge.
    """
    calculation = (
        db.query(Calculation)
        .filter(
            Calculation.id == calculation_id, Calculation.user_id == current_user.id
        )
        .first()
    )
    if calculation is None:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    areas = forest_unit_queries.leaf_areas_by_name(db, calculation.id)
    if not areas:
        # An upload-mode forest with no unit rows has nothing to review; an empty
        # result is the honest answer, not an error.
        return {
            "calculation_id": str(calculation.id),
            "boundary_area_ha": 0.0,
            "mmu_ha": mmu_hectares(),
            "review_pct": review_pct,
            "summary": {"total": 0, "sub_mmu": 0, "review": 0, "ok": 0,
                        "merge_offers": 0, "unmergeable": 0},
            "candidates": [],
        }

    boundary_ha = float((calculation.result_data or {}).get("area_hectares") or 0.0)
    touching = _touching_by_name(db, calculation.id, areas)
    candidates = review_units(
        areas,
        boundary_ha=boundary_ha,
        touching=touching,
        review_pct=review_pct,
    )

    # P8 merge action: the client needs the unit's UUID (merge-features takes
    # feature_ids, not names) and the unit's OWN layer type. `layer_of` is the
    # single source of truth for blocks/sub_blocks/compartments/sub_compartments, so
    # deriving it here makes "merge like with like" structural: a sub-compartment
    # cannot be merged into a block, because the wrong layer_type is not expressible
    # from the client rather than merely discouraged.
    from ..models.forest_block import ForestBlock as _FB
    from ..services.forest_units.operations.divide import layer_of as _layer_of

    rows = {
        str(row.block_name or row.name): row
        for row in db.query(_FB)
        .filter(_FB.calculation_id == calculation.id)
        .filter(_FB.block_name.isnot(None))
        .all()
    }

    payload = []
    for c in candidates:
        row = rows.get(c.block_name)
        neighbour_row = rows.get(c.neighbour) if c.neighbour else None
        payload.append(
            {
                "block_name": c.block_name,
                "id": str(row.id) if row is not None else None,
                "layer_type": _layer_of(row) if row is not None else None,
                "area_ha": round(c.area_ha, 4),
                "band": c.band.value,
                "action": c.action,
                "neighbour": c.neighbour,
                "neighbour_id": str(neighbour_row.id) if neighbour_row is not None else None,
                "neighbour_area_ha": (
                    round(c.neighbour_area_ha, 4) if c.neighbour_area_ha is not None else None
                ),
                "unmergeable": c.unmergeable,
                "reason": describe(
                    c,
                    mmu_ha=mmu_hectares(),
                    plot_area_sqm=STRATUM_PLOT_SQM["production"],
                    min_plots=MIN_SAMPLES_PER_UNIT,
                ),
            }
        )

    counts = summarise(candidates)
    return {
        "calculation_id": str(calculation.id),
        "boundary_area_ha": round(boundary_ha, 4),
        "mmu_ha": mmu_hectares(),
        "review_pct": review_pct,
        "summary": counts,
        "candidates": payload,
        "read_only": True,
    }

@router.post("/calculations/{calculation_id}/sampling/import-plots")
def import_sample_plots(
    calculation_id: UUID,
    file: UploadFile = File(...),
    crs_epsg: Optional[int] = Form(None),
    renumber: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sample plots prepared elsewhere (Excel / CSV, the ``02_Sample_Plots`` template) become the forest's sampling design.

    Sync on purpose: it reads a file. Refuses, naming the rows, when the table is wrong (see ``services/upload/sample_plots.py``); a forest already
    holding a design is refused like ``/sampling/create``. The design is stored in the engines' own form, so the map layer, per-unit summary and field
    inventory read it unchanged; ``sampling_type`` is ``imported``.
    """
    import math

    from app.api.inventory import read_upload_file
    from app.services.forest_units.sampling_view import sampling_units
    from app.services.upload.findings import upload_error
    from app.services.upload.sample_plots import plot_area_sqm, prepare_sample_plots

    calculation = (
        db.query(Calculation)
        .filter(Calculation.id == calculation_id, Calculation.user_id == current_user.id)
        .first()
    )
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    if not calculation.boundary_geom:
        raise i18n_error(400, "calculations.no_geometry")
    existing = db.query(SamplingDesign).filter(SamplingDesign.calculation_id == calculation_id).first()
    if existing:
        raise i18n_error(400, "sampling.design_already_exists", design_id=str(existing.id))

    df = read_upload_file(file.file.read(), file.filename or "plots.csv")
    boundary_wkt = db.execute(
        text("SELECT ST_AsText(ST_Transform(boundary_geom, 4326)) FROM public.calculations WHERE id = :id"), {"id": str(calculation_id)}
    ).scalar()
    units = sampling_units(db, calculation)
    prepared = prepare_sample_plots(df, db, units=units, boundary_wkt=boundary_wkt, crs_epsg=crs_epsg, renumber=renumber, file=file.filename)
    if prepared.errors:
        raise upload_error(422, *prepared.errors)

    per_unit: Dict[int, int] = {}
    for p in prepared.plots:
        per_unit[p.unit_index] = per_unit.get(p.unit_index, 0) + 1
    assignments = [
        {"point_index": i, "block_number": p.unit_index + 1, "block_name": p.unit_name, "zone_type": "productive", "sampling_method": "imported"}
        for i, p in enumerate(prepared.plots)
    ]
    area_sqm = plot_area_sqm(prepared.radius_m)
    total_ha = sum(float(u.get("area_ha") or 0) for u in units)
    blocks_info = [
        {
            "block_number": idx + 1,
            "block_name": u["name"],
            "block_area_hectares": float(u.get("area_ha") or 0),
            "samples_generated": per_unit.get(idx, 0),
            "minimum_enforced": False,
            "actual_intensity_percent": round(per_unit.get(idx, 0) * area_sqm / 100 / float(u["area_ha"]), 4) if u.get("area_ha") else 0,
        }
        for idx, u in enumerate(units)
    ]
    total = len(prepared.plots)
    sampled_ha = total * area_sqm / 10000.0
    design = SamplingDesign(
        calculation_id=calculation_id,
        sampling_type="imported",
        intensity_per_hectare=Decimal(str(round(total / total_ha, 6))) if total_ha else None,
        plot_shape="circular",
        plot_radius_meters=Decimal(str(prepared.radius_m)),
        total_points=total,
        notes=f"Imported from {file.filename}",
    )
    db.add(design)
    db.flush()
    wkt = "MULTIPOINT(" + ", ".join(f"{p.lon} {p.lat}" for p in prepared.plots) + ")"
    params = {"sampling_method": "imported", "plot_size_sqm": round(area_sqm, 2), "source_file": file.filename}
    db.execute(
        text(
            "UPDATE public.sampling_designs SET default_parameters = CAST(:params AS jsonb), points_geometry = ST_GeomFromText(:wkt, 4326), "
            "points_block_assignment = CAST(:assignments AS jsonb) WHERE id = :id"
        ),
        {"params": json.dumps(params), "wkt": wkt, "assignments": json.dumps(assignments), "id": str(design.id)},
    )
    response = SamplingGenerateResponse(
        sampling_design_id=design.id,
        calculation_id=calculation_id,
        sampling_type="imported",
        total_points=total,
        total_blocks=len(units),
        forest_area_hectares=total_ha,
        requested_intensity_percent=0,
        actual_intensity_per_hectare=round(total / total_ha, 6) if total_ha else 0,
        plot_area_sqm=round(area_sqm, 2),
        total_sampled_area_hectares=round(sampled_ha, 4),
        sampling_percentage=round(100 * sampled_ha / total_ha, 4) if total_ha else None,
        blocks_info=blocks_info,
    )
    optimistic_lock.record_derived_write(db, "sampling", design.id, "imported sample plots")
    design.result_data = response.model_dump(mode="json")
    db.add(design)
    db.commit()
    return {
        "sampling_design_id": str(design.id),
        "total_points": total,
        "radius_m": prepared.radius_m,
        "per_unit": {units[i]["name"]: n for i, n in per_unit.items()},
        "findings": [f.to_dict() for f in prepared.infos],
    }
