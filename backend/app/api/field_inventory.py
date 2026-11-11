"""
Field Inventory API endpoints
Handles field inventory upload, validation, processing, and export
"""
from app.services.upload.findings import finding as upload_finding, upload_error
from app.services.upload.field_inventory_findings import enrich_report
from app.services.upload.fi_columns import normalise_columns, normalise_columns_with_units
from app.services.upload.coordinates import apply_chosen_system
from app.services.upload.blank_rows import trim_blank_tail
from app.services.upload.species_resolve import resolve_species_columns
from app.services.upload.corrections import apply_accepted_corrections
from app.services.upload.coordinates import forest_bbox, preview_payload
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List, Any, Dict
from uuid import UUID
import pandas as pd
import numpy as np
import io
import json
import os
import math

from ..core.dbh_classifier import DbhClassRegistry
from app.core.errors import resolve_detail
from app.core.constants import SQM_PER_HA
from app.core.species_policy import (
    ABSOLUTE_MEASURES,
    PER_HA_MEASURES,
    annotate_species_rows,
    build_policy_groups,
)
from app.core import harvest_groups
from app.core.regulation_species import (
    build_regulation_groups,
    region_for_field_inventory,
)


def _per_ha_to_harvest_rows(
    dbh_class_per_ha: Dict[str, Any], block_name: str
) -> List[Dict[str, Any]]:
    """Adapt this pane's per-class shape to `harvest_groups`' neutral one.

    Only the volume key differs: the pane calls it `tree_volume_m3_per_ha` and
    the shared grouping calls it `total_volume_m3_per_ha`. Both mean timber +
    firewood, and both are the same number -- but the shared function must not be
    renamed to either caller's vocabulary, or the other one inherits the rename.
    So the translation lives here, at the one boundary where it is needed.

    Labels are dropped on purpose: `harvest_groups` returns neutral keys and no
    presentation (D10), and passing the class labels through would invite a
    formatter to read them instead of the i18n bundle.
    """
    rows: List[Dict[str, Any]] = []
    for cls_key, data in (dbh_class_per_ha or {}).items():
        rows.append(
            {
                "block_name": block_name,
                "dbh_class": cls_key,
                "count_per_ha": data.get("count_per_ha", 0.0),
                "timber_m3_per_ha": data.get("timber_m3_per_ha", 0.0),
                "firewood_m3_per_ha": data.get("firewood_m3_per_ha", 0.0),
                "total_volume_m3_per_ha": data.get("tree_volume_m3_per_ha", 0.0),
            }
        )
    return rows

from ..core.database import get_db
from ..core.idempotent_route import IdempotentRoute
from ..middleware.rate_limit import import_limiter  # H8.3
from ..models.user import User
from ..models.field_inventory import (
    FieldInventoryCalculation,
    FieldInventorySamplePlot,
    FieldInventoryMeasurement,
    FieldInventoryBlockSummary
)
from ..schemas.field_inventory import (
    FieldInventoryCalculationResponse,
    FieldInventorySummaryResponse,
    FieldInventoryBlockSummaryResponse,
    FieldInventoryValidationReport
)
from ..utils.auth import get_current_active_user
from ..services.field_inventory_validator import FieldInventoryValidator
from ..services.field_inventory_service import FieldInventoryService
from ..services.carbon_calculator import IPCC_BEF, IPCC_RS, IPCC_CF, IPCC_CO2R
from ..core.constants import AAH_MULTIPLIER
from ..core.exceptions import i18n_success
from ..utils.number_format import normalize_nepali_digits
from ..services.forest_units import queries as forest_unit_queries
from ..services.sustainable_fm.stratum_spec import MIN_SAMPLES_PER_UNIT, STRATUM_PLOT_SQM
from ..services.unit_size_review import (
    DEFAULT_REVIEW_PCT,
    describe,
    mmu_hectares,
    review_units,
    summarise,
)

import logging

logger = logging.getLogger(__name__)

router = APIRouter(route_class=IdempotentRoute)


def clean_nan_values(obj: Any) -> Any:
    """
    Recursively clean NaN, inf, and -inf values from nested structures
    Converts them to None for JSON serialization
    """
    if isinstance(obj, dict):
        return {k: clean_nan_values(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nan_values(item) for item in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, np.floating):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif pd.isna(obj):
        return None
    return obj


# business: CFMG §6.2 — field inventory data collection endpoints for CSV/Excel upload and processing
@router.post("/preview-mapping")
async def preview_column_mapping(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Preview automatic column mapping for uploaded CSV file
    """
    from app.utils.number_format import normalize_nepali_digits

    try:
        content = await file.read()
        fname = file.filename.lower()
        if fname.endswith('.xlsx') or fname.endswith('.xls'):
            df = pd.read_excel(io.BytesIO(content), nrows=10)
        else:
            encodings = ["utf-8", "latin-1", "cp1252", "cp437", "utf-16"]
            df = None
            for enc in encodings:
                try:
                    df = pd.read_csv(io.BytesIO(content), nrows=10, encoding=enc)
                    if not df.empty:
                        break
                except (UnicodeDecodeError, UnicodeError):
                    continue
                except Exception:
                    logger.debug(
                        "CSV preview failed with encoding %s - trying the next one",
                        enc, exc_info=True,
                    )
                    continue
            if df is None or df.empty:
                raise HTTPException(status_code=400, detail="Could not read file. Supported formats: CSV, Excel (.xlsx/.xls).")
        df = df.map(lambda v: normalize_nepali_digits(v) if isinstance(v, str) else v)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")

    if len(df) == 0:
        raise HTTPException(status_code=400, detail="File is empty")

    # Return preview with column detection (clean NaN values)
    preview_data = {
        "success": True,
        "filename": file.filename,
        "total_rows": len(df),
        "csv_columns": df.columns.tolist(),
        "sample_data": df.head(5).to_dict('records'),
        "detected_stand_types": []  # TODO: Implement auto-detection
    }

    return clean_nan_values(preview_data)


@router.post("/upload")
async def upload_field_inventory(
    file: UploadFile = File(...),
    calculation_id: Optional[str] = Form(None),
    mapping: str = Form(...),  # JSON string
    regeneration_area_sqm: float = Form(10.0),
    sapling_area_sqm: float = Form(25.0),
    pole_area_sqm: float = Form(100.0),
    tree_area_sqm: float = Form(500.0),
    crs_epsg: Optional[int] = Form(None),  # the coordinate system the user chose in Add data (None = as the file is: degrees)
    corrections: Optional[str] = Form(None),  # JSON [{row, column, value}]: the proposed replacements the user accepted
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Upload and validate field inventory CSV
    """
    import_limiter.check(current_user.id)  # H8.3 / S3-66

    if not file.filename.lower().endswith(('.csv', '.xlsx')):
        ext = os.path.splitext(file.filename or "")[1] or "no extension"
        raise upload_error(400, upload_finding("file.wrong_type", found=ext, expected="CSV (.csv) or Excel (.xlsx)", file=file.filename))

    # One inventory per calculation (UNIQUE calculation_id): refuse before parsing,
    # instead of validating happily and then failing on the insert.
    if calculation_id:
        already = (
            db.query(FieldInventoryCalculation.id)
            .filter(FieldInventoryCalculation.calculation_id == UUID(calculation_id))
            .first()
        )
        if already:
            raise HTTPException(
                status_code=409,
                detail=resolve_detail({"code": "general.duplicate_field_inventory"}),
            )

    # Parse mapping
    try:
        mapping_dict = json.loads(mapping)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid mapping JSON")

    # Read file
    content = b""
    try:
        content = await file.read()
        if file.filename.endswith('.xlsx'):
            df = pd.read_excel(io.BytesIO(content))
        else:
            df = pd.read_csv(io.BytesIO(content))
        df = trim_blank_tail(df.map(lambda v: normalize_nepali_digits(v) if isinstance(v, str) else v))
    except Exception as e:  # noqa: BLE001 -- logged; the user gets a plain finding, not the library's words
        logger.warning("field inventory upload: file could not be read (%s): %s", file.filename, e)
        if not content.strip():
            raise upload_error(400, upload_finding("file.empty", file=file.filename))
        raise upload_error(400, upload_finding("file.corrupt" if file.filename.lower().endswith('.xlsx') else "file.unreadable",
                                               expected="CSV (.csv) or Excel (.xlsx)", file=file.filename))

    df, renamed_columns, converted_units = normalise_columns_with_units(df)  # 'Lon' -> longitude, 'Plot No' -> sample_plot_number ... (reported below, never silent)
    df, system_findings = apply_chosen_system(db, df, crs_epsg, file=file.filename)  # UTM chosen in Add data -> degrees, before any check
    df, correction_findings = apply_accepted_corrections(db, df, corrections, file=file.filename)  # only cells the rules refuse; reported
    df, species_findings = resolve_species_columns(db, df, mapping_dict, file=file.filename)  # a code or a local name -> the scientific name
    system_findings = system_findings + correction_findings + species_findings

    # Validate
    validator = FieldInventoryValidator(db)
    calc_id = UUID(calculation_id) if calculation_id else None
    validation_report = await validator.validate_field_inventory_file(df, calc_id)

    # Clean NaN values before JSON serialization
    validation_report = clean_nan_values(validation_report)
    enrich_report(validation_report, df, file.filename, reference_bbox=forest_bbox(db, calc_id), renamed=renamed_columns, converted=converted_units, extra=system_findings,
                  preview=lambda xs, ys: preview_payload(db, calc_id, xs, ys))  # plain-language findings; no-rows is not "ready"; no noise for absent stand types

    # If validation passed, create record and store raw rows immediately
    if validation_report['summary'].get('ready_for_processing'):
        field_inventory = FieldInventoryCalculation(
            user_id=current_user.id,
            calculation_id=calc_id,
            uploaded_filename=file.filename,
            column_mapping=mapping_dict,
            regeneration_area_sqm=regeneration_area_sqm,
            sapling_area_sqm=sapling_area_sqm,
            pole_area_sqm=pole_area_sqm,
            tree_area_sqm=tree_area_sqm,
            status='validated'
        )
        db.add(field_inventory)
        db.flush()  # get ID without committing

        # business: raw measurements stored immediately so {{table:fieldinventory}} renders without re-processing
        # Store raw rows immediately — {{table:fieldinventory}} works after this
        service = FieldInventoryService(db)
        service.store_raw_measurements(field_inventory.id, df, mapping_dict)

        db.commit()
        db.refresh(field_inventory)

        validation_report['field_inventory_id'] = str(field_inventory.id)
        validation_report['next_step'] = 'POST /api/field-inventory/{field_inventory_id}/process'

    return validation_report


@router.post("/{field_inventory_id}/process")
async def process_field_inventory(
    field_inventory_id: UUID,
    file: UploadFile = File(...),
    crs_epsg: Optional[int] = Form(None),  # the same choice as at upload, or the two reads would disagree
    corrections: Optional[str] = Form(None),  # the same accepted corrections as at upload
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Process validated field inventory
    """
    import_limiter.check(current_user.id)  # H8.3 / S3-66

    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()

    if not field_inventory:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    if field_inventory.status != 'validated':
        raise HTTPException(status_code=400, detail=f"Cannot process. Status: {field_inventory.status}")

    # Read file
    try:
        content = await file.read()
        if field_inventory.uploaded_filename.endswith('.xlsx'):
            df = pd.read_excel(io.BytesIO(content))
        else:
            df = pd.read_csv(io.BytesIO(content))
        df = trim_blank_tail(df.map(lambda v: normalize_nepali_digits(v) if isinstance(v, str) else v))
        df, _ = normalise_columns(df)  # same names as at upload
        df, _ = apply_chosen_system(db, df, crs_epsg)  # same coordinates as at upload
        df, _ = apply_accepted_corrections(db, df, corrections)  # same accepted corrections as at upload
        df, _ = resolve_species_columns(db, df, field_inventory.column_mapping or {})  # same species names as at upload
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")

    # Process
    service = FieldInventoryService(db)
    try:
        result = await service.process_field_inventory(
            field_inventory_id,
            df,
            field_inventory.column_mapping
        )
        # A completed run is built against the CURRENT unit geometry, so it
        # answers `structure_stale['field_inventory']`. The service never loads
        # the Calculation, so the flag is cleared here by id -- otherwise the
        # banner kept asking for a field-inventory re-run that had just happened.
        if field_inventory.calculation_id:
            from app.services.forest_units.write import clear_stale_domains_for_calc

            if clear_stale_domains_for_calc(db, field_inventory.calculation_id):
                db.commit()
        return result
    except Exception as e:
        logger.error(f"Processing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.get("/{field_inventory_id}/status", response_model=FieldInventoryCalculationResponse)
def get_status(
    field_inventory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get processing status"""
    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()

    if not field_inventory:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    return field_inventory


@router.get("/{field_inventory_id}/summary", response_model=FieldInventorySummaryResponse)
def get_summary(
    field_inventory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get complete summary with all blocks"""
    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()

    if not field_inventory:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    # Get all block summaries (ordered by name for consistent rendering)
    blocks = db.query(FieldInventoryBlockSummary).filter(
        FieldInventoryBlockSummary.field_inventory_calculation_id == field_inventory_id
    ).order_by(FieldInventoryBlockSummary.block_name).all()

    # Calculate forest-wide averages
    if blocks:
        from collections import Counter
        total_blocks = len(blocks)

        # Average trees per hectare
        avg_regeneration = sum(b.regeneration_per_ha or 0 for b in blocks) / total_blocks
        avg_sapling = sum(b.sapling_per_ha or 0 for b in blocks) / total_blocks
        avg_pole = sum(b.pole_per_ha or 0 for b in blocks) / total_blocks
        avg_tree = sum(b.tree_per_ha or 0 for b in blocks) / total_blocks

        # Average volumes
        avg_pole_timber = sum(float(b.pole_timber_m3_per_ha or 0) for b in blocks) / total_blocks
        avg_pole_firewood = sum(float(b.pole_firewood_m3_per_ha or 0) for b in blocks) / total_blocks
        avg_tree_timber = sum(float(b.tree_timber_m3_per_ha or 0) for b in blocks) / total_blocks
        avg_tree_firewood = sum(float(b.tree_firewood_m3_per_ha or 0) for b in blocks) / total_blocks
        avg_growing_stock = sum(float(b.total_growing_stock_m3_per_ha or 0) for b in blocks) / total_blocks

        # Average basal area
        avg_basal_area = sum(float(b.basal_area_m2_per_ha or 0) for b in blocks) / total_blocks

        # Average carbon metrics
        avg_wood_density = sum(float(b.weighted_wood_density or 0) for b in blocks) / total_blocks
        avg_agb = sum(float(b.agb_t_per_ha or 0) for b in blocks) / total_blocks
        avg_bgb = sum(float(b.bgb_t_per_ha or 0) for b in blocks) / total_blocks
        avg_total_biomass = sum(float(b.total_biomass_t_per_ha or 0) for b in blocks) / total_blocks
        avg_carbon = sum(float(b.carbon_stock_tc_per_ha or 0) for b in blocks) / total_blocks
        avg_co2 = sum(float(b.co2_equivalent_tco2_per_ha or 0) for b in blocks) / total_blocks

        # Average MAI
        avg_mai = sum(float(b.mai_percent or 0) for b in blocks) / total_blocks

        # Overall forest condition (majority vote)
        conditions = [b.forest_condition for b in blocks if b.forest_condition]
        overall_condition = Counter(conditions).most_common(1)[0][0] if conditions else None

        regen_conditions = [b.regeneration_condition for b in blocks if b.regeneration_condition]
        overall_regen = Counter(regen_conditions).most_common(1)[0][0] if regen_conditions else None

        growth_rates = [b.dominant_growth_rate for b in blocks if b.dominant_growth_rate]
        overall_growth_rate = Counter(growth_rates).most_common(1)[0][0] if growth_rates else None
    else:
        # No blocks, return zeros
        avg_regeneration = avg_sapling = avg_pole = avg_tree = 0
        avg_pole_timber = avg_pole_firewood = avg_tree_timber = avg_tree_firewood = 0
        avg_growing_stock = avg_mai = 0
        avg_wood_density = avg_agb = avg_bgb = avg_total_biomass = avg_carbon = avg_co2 = 0
        overall_condition = overall_regen = overall_growth_rate = None

    return {
        "field_inventory_id": field_inventory.id,
        "status": field_inventory.status,
        "total_sample_plots": field_inventory.total_sample_plots or 0,
        "total_blocks": field_inventory.total_blocks or 0,
        "blocks": blocks,

        # Forest-wide averages (NEW)
        "total_regeneration_per_ha": int(avg_regeneration),
        "total_sapling_per_ha": int(avg_sapling),
        "total_pole_per_ha": int(avg_pole),
        "total_tree_per_ha": int(avg_tree),
        "total_pole_timber_m3_per_ha": round(avg_pole_timber, 2),
        "total_pole_firewood_m3_per_ha": round(avg_pole_firewood, 2),
        "total_tree_timber_m3_per_ha": round(avg_tree_timber, 2),
        "total_tree_firewood_m3_per_ha": round(avg_tree_firewood, 2),
        "total_growing_stock_m3_per_ha": round(avg_growing_stock, 2),
        "average_basal_area_m2_per_ha": round(avg_basal_area, 2),

        # Overall assessments
        "overall_forest_condition": overall_condition,
        "overall_regeneration_condition": overall_regen,
        "overall_growth_rate": overall_growth_rate,
        "average_mai_percent": round(avg_mai, 2),

        # Carbon averages (NEW)
        "average_wood_density": round(avg_wood_density, 3),
        "average_agb_t_per_ha": round(avg_agb, 2),
        "average_bgb_t_per_ha": round(avg_bgb, 2),
        "average_total_biomass_t_per_ha": round(avg_total_biomass, 2),
        "average_carbon_stock_tc_per_ha": round(avg_carbon, 2),
        "average_co2_equivalent_tco2_per_ha": round(avg_co2, 2),

        "processing_time_seconds": field_inventory.processing_time_seconds,
        "created_at": field_inventory.created_at,
        "completed_at": field_inventory.completed_at
    }


@router.get("/{field_inventory_id}/blocks", response_model=List[FieldInventoryBlockSummaryResponse])
def list_blocks(
    field_inventory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """List all blocks"""
    # Verify ownership
    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()

    if not field_inventory:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    blocks = db.query(FieldInventoryBlockSummary).filter(
        FieldInventoryBlockSummary.field_inventory_calculation_id == field_inventory_id
    ).all()

    return blocks


@router.get("/{field_inventory_id}/unsampled-units")
def list_unsampled_units(
    field_inventory_id: UUID,
    review_pct: float = Query(
        DEFAULT_REVIEW_PCT,
        ge=0.0,
        le=100.0,
        description="Same field rule of thumb as the sampling review screen.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """P8: the leaf units that received **no sample point**, and therefore have no
    field-inventory summary at all.

    A block gets a summary only if it was sampled
    (``field_inventory_service.py:1347`` builds the list from
    ``SELECT DISTINCT block_name FROM field_inventory_sample_plots``), so an unsampled
    unit simply vanishes. This is where most users actually meet that: they open the
    inventory, count 21 blocks where the forest has 24, and nothing explains the gap.
    Naming the units is what turns an unexplained number into an explained one.

    Read-only, and additive: the existing ``/blocks`` response shape is untouched, so
    the frontend can add the note without a breaking change. Bands and reasons come
    from the same classifier the sampling review screen uses, so the two surfaces can
    never disagree.
    """
    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id,
    ).first()
    if not field_inventory:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    areas = forest_unit_queries.leaf_areas_by_name(db, field_inventory.calculation_id)
    if not areas:
        return {
            "field_inventory_id": str(field_inventory_id),
            "total_units": 0,
            "summarised_units": 0,
            "review_pct": review_pct,
            "unsampled_units": [],
            "summary": {"total": 0, "sub_mmu": 0, "review": 0, "ok": 0,
                        "merge_offers": 0, "unmergeable": 0},
            "read_only": True,
        }

    summarised = {
        str(name)
        for (name,) in db.query(FieldInventoryBlockSummary.block_name)
        .filter(
            FieldInventoryBlockSummary.field_inventory_calculation_id == field_inventory_id
        )
        .all()
        if name
    }

    # `FieldInventoryCalculation.calculation` is a relationship, so no extra import
    # of Calculation is needed here - and the boundary area may legitimately be
    # absent, which leaves the relative 5% screen unevaluable rather than zero.
    boundary_ha = float(
        ((field_inventory.calculation or {}).result_data or {}).get("area_hectares") or 0.0
    )

    candidates = review_units(areas, boundary_ha=boundary_ha, review_pct=review_pct)
    unsampled = [c for c in candidates if c.block_name not in summarised]

    payload = [
        {
            "block_name": c.block_name,
            "area_ha": round(c.area_ha, 4),
            "band": c.band.value,
            "action": c.action,
            "neighbour": c.neighbour,
            "unmergeable": c.unmergeable,
            "reason": describe(
                c,
                mmu_ha=mmu_hectares(),
                plot_area_sqm=STRATUM_PLOT_SQM["production"],
                min_plots=MIN_SAMPLES_PER_UNIT,
            ),
        }
        for c in unsampled
    ]

    return {
        "field_inventory_id": str(field_inventory_id),
        "calculation_id": str(field_inventory.calculation_id),
        "total_units": len(candidates),
        "summarised_units": len(summarised),
        "review_pct": review_pct,
        "unsampled_units": payload,
        "summary": summarise(unsampled),
        "read_only": True,
    }


@router.get("/{field_inventory_id}/regulation-species")
def get_regulation_species(
    field_inventory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """The OP's regulation-species tables, charts and narration (21 designated species + Other Terai/Hill; and the 21 only),
    each with the placeholder that places it in a template. Read-only; same builders as the OP document."""
    from app.services.operational_plan.species_regulation_view import build_view

    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id,
    ).first()
    if not field_inventory:
        raise HTTPException(status_code=404, detail="Field inventory not found")
    return build_view(db, field_inventory.id, field_inventory.calculation_id)


@router.get("/{field_inventory_id}/species-breakdown")
def get_species_breakdown(
    field_inventory_id: UUID,
    group_by: str = Query("block", regex="^(block|compartment)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """# business: species-wise breakdown by block or compartment for DFO reporting
    Get species-wise breakdown by block or compartment"""
    from sqlalchemy import text

    # Verify ownership
    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()

    if not field_inventory:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    # Determine grouping column
    group_col = "compartment_code" if group_by == "compartment" else "block_name"

    # Get sample plot areas
    regen_area = float(field_inventory.regeneration_area_sqm)
    sapling_area = float(field_inventory.sapling_area_sqm)
    pole_area = float(field_inventory.pole_area_sqm)
    tree_area = float(field_inventory.tree_area_sqm)

    # Query to get species-wise breakdown by block or compartment
    query = text(f"""
        WITH block_total_plots AS (
            SELECT {group_col} as group_name, COUNT(DISTINCT id) as total_plots
            FROM public.field_inventory_sample_plots
            WHERE field_inventory_calculation_id = :field_inventory_id
            GROUP BY {group_col}
        ),
        species_data AS (
            SELECT
                sp.{group_col} as group_name,
                m.species_scientific,
                m.species_local,
                m.stand_type,
                SUM(m.count) as total_count,
                SUM(COALESCE(m.net_volume, 0)) as total_timber,
                SUM(COALESCE(m.gross_volume, 0)) as total_gross,
                SUM(COALESCE(m.firewood_m3, 0)) as total_firewood,
                SUM(COALESCE(m.basal_area_m2, 0) * m.count) as total_basal_area
            FROM public.field_inventory_sample_plots sp
            JOIN public.field_inventory_measurements m ON m.sample_plot_id = sp.id
            WHERE sp.field_inventory_calculation_id = :field_inventory_id
            GROUP BY sp.{group_col}, m.species_scientific, m.species_local, m.stand_type
        )
        SELECT
            sd.group_name,
            sd.species_scientific,
            sd.species_local,
            btp.total_plots,
            SUM(CASE WHEN sd.stand_type = 'Regeneration' THEN sd.total_count ELSE 0 END) as regen_count,
            SUM(CASE WHEN sd.stand_type = 'Sapling' THEN sd.total_count ELSE 0 END) as sapling_count,
            SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_count ELSE 0 END) as pole_count,
            SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_count ELSE 0 END) as tree_count,
            SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_basal_area ELSE 0 END) as pole_basal_area,
            SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_basal_area ELSE 0 END) as tree_basal_area,
            SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_timber ELSE 0 END) as pole_timber,
            SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_firewood ELSE 0 END) as pole_firewood,
            SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_timber ELSE 0 END) as tree_timber,
            SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_firewood ELSE 0 END) as tree_firewood,
            SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_gross ELSE 0 END) as pole_gross,
            SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_gross ELSE 0 END) as tree_gross
        FROM species_data sd
        JOIN block_total_plots btp ON btp.group_name = sd.group_name
        GROUP BY sd.group_name, sd.species_scientific, sd.species_local, btp.total_plots
        ORDER BY sd.group_name, sd.species_scientific
    """)

    results = db.execute(query, {"field_inventory_id": str(field_inventory_id)}).fetchall()

    # Load species coefficients (for wood density)
    species_coefficients_query = text("""
        SELECT scientific_name, wood_density_gm_cm3
        FROM public.tree_species_coefficients
        WHERE is_active = TRUE
    """)
    species_coef_results = db.execute(species_coefficients_query).fetchall()
    species_densities = {row.scientific_name: float(row.wood_density_gm_cm3 or 0.65) for row in species_coef_results}

    # business: IPCC Tier 2 carbon — AGB = VOB × WD × BEF (IPCC 2006 GL Vol 4 Ch 4)
    # IPCC 2006 Tier 2 constants — sourced from carbon_calculator (single source of truth).
    # AGB = VOB × WD × BEF; VOB = gross_volume per-ha; BEF = 1.3 (Table 4.4)
    # Per-species entries use gross_volume_per_ha with species-specific density
    CARBON_FRACTION = IPCC_CF  # Table 4.3
    CO2_TO_C_RATIO = IPCC_CO2R

    # Process results to calculate per-hectare values and carbon metrics
    species_data = []
    for row in results:
        total_plots = row.total_plots or 1

        # business: per-ha = measurement / total_plots_in_block / plot_area * SQM_PER_HA
        # Calculate per-hectare counts (convert Decimal to float for calculations)
        regen_per_ha = int((float(row.regen_count or 0) / total_plots / regen_area) * SQM_PER_HA) if row.regen_count > 0 else 0
        sapling_per_ha = int((float(row.sapling_count or 0) / total_plots / sapling_area) * SQM_PER_HA) if row.sapling_count > 0 else 0
        pole_per_ha = int((float(row.pole_count or 0) / total_plots / pole_area) * SQM_PER_HA) if row.pole_count > 0 else 0
        tree_per_ha = int((float(row.tree_count or 0) / total_plots / tree_area) * SQM_PER_HA) if row.tree_count > 0 else 0

        # Calculate per-hectare volumes
        pole_timber_per_ha = (float(row.pole_timber or 0) / total_plots / pole_area) * SQM_PER_HA if row.pole_timber else 0
        pole_firewood_per_ha = (float(row.pole_firewood or 0) / total_plots / pole_area) * SQM_PER_HA if row.pole_firewood else 0
        tree_timber_per_ha = (float(row.tree_timber or 0) / total_plots / tree_area) * SQM_PER_HA if row.tree_timber else 0
        tree_firewood_per_ha = (float(row.tree_firewood or 0) / total_plots / tree_area) * SQM_PER_HA if row.tree_firewood else 0

        # Gross volume per-ha (VOB for IPCC Tier 2 AGB calculation)
        pole_gross_per_ha = (float(row.pole_gross or 0) / total_plots / pole_area) * SQM_PER_HA if row.pole_gross else 0
        tree_gross_per_ha = (float(row.tree_gross or 0) / total_plots / tree_area) * SQM_PER_HA if row.tree_gross else 0
        gross_volume_per_ha = pole_gross_per_ha + tree_gross_per_ha

        growing_stock = pole_timber_per_ha + tree_timber_per_ha
        total_volume = pole_timber_per_ha + pole_firewood_per_ha + tree_timber_per_ha + tree_firewood_per_ha

        # Calculate per-hectare basal area
        pole_basal_per_ha = (float(row.pole_basal_area or 0) / total_plots / pole_area) * SQM_PER_HA if row.pole_basal_area else 0
        tree_basal_per_ha = (float(row.tree_basal_area or 0) / total_plots / tree_area) * SQM_PER_HA if row.tree_basal_area else 0
        basal_area_m2_per_ha = pole_basal_per_ha + tree_basal_per_ha

        # Carbon calculations — IPCC Tier 2 (IPCC 2006 GL Vol 4 Ch 4)
        # AGB = VOB × WD × BEF where VOB = gross_volume, BEF = 1.3 (Table 4.4)
        wood_density = species_densities.get(row.species_scientific, 0.65)
        agb_t_per_ha = gross_volume_per_ha * wood_density * IPCC_BEF
        bgb_t_per_ha = agb_t_per_ha * IPCC_RS
        total_biomass_t_per_ha = agb_t_per_ha + bgb_t_per_ha
        carbon_stock_tC_per_ha = total_biomass_t_per_ha * CARBON_FRACTION
        co2_equivalent_tCO2_per_ha = carbon_stock_tC_per_ha * CO2_TO_C_RATIO

        species_data.append({
            "block_name": row.group_name if group_by == "block" else None,
            "compartment_code": row.group_name if group_by == "compartment" else None,
            "species_scientific": row.species_scientific,
            "species_local": row.species_local or "",
            "regeneration_per_ha": regen_per_ha,
            "sapling_per_ha": sapling_per_ha,
            "pole_per_ha": pole_per_ha,
            "tree_per_ha": tree_per_ha,
            "pole_timber_m3_per_ha": round(pole_timber_per_ha, 2),
            "pole_firewood_m3_per_ha": round(pole_firewood_per_ha, 2),
            "tree_timber_m3_per_ha": round(tree_timber_per_ha, 2),
            "tree_firewood_m3_per_ha": round(tree_firewood_per_ha, 2),
            "growing_stock_m3_per_ha": round(growing_stock, 2),
            "total_volume_m3_per_ha": round(total_volume, 2),
            "basal_area_m2_per_ha": round(basal_area_m2_per_ha, 2),
            # Carbon metrics (IPCC/REDD+)
            "wood_density_t_m3": round(wood_density, 3),
            "agb_t_per_ha": round(agb_t_per_ha, 2),
            "bgb_t_per_ha": round(bgb_t_per_ha, 2),
            "total_biomass_t_per_ha": round(total_biomass_t_per_ha, 2),
            "carbon_stock_tc_per_ha": round(carbon_stock_tC_per_ha, 2),
            "co2_equivalent_tco2_per_ha": round(co2_equivalent_tCO2_per_ha, 2)
        })

    return {"species_breakdown": species_data}


@router.get("/by-calculation/{calculation_id}")
def get_by_calculation(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get field inventory for a calculation"""
    from ..models.calculation import Calculation

    # Owner report 2026-10-03: this must authorize against the CALCULATION's
    # owner, not `FieldInventoryCalculation.user_id` -- the latter is whoever
    # ran that particular upload, which can differ from the calculation's
    # current owner (e.g. admin-seeded data). The old filter made this
    # endpoint 404 "no field inventory" for a calculation that genuinely has
    # one, hiding real data from its own owner and causing the delete-guard
    # (calculation-scoped, not user-scoped) to disagree with what this
    # endpoint reported.
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id,
    ).first()
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")

    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.calculation_id == calculation_id,
    ).first()

    if not field_inventory:
        raise HTTPException(status_code=404, detail="No field inventory found for this calculation")

    return field_inventory


@router.get("/{field_inventory_id}/mai-aah")
def get_mai_aah(
    field_inventory_id: UUID,
    aah_good: float = 75.0,
    aah_moderate: float = AAH_MULTIPLIER["Moderate"],
    aah_weak: float = 40.0,
    custom_multipliers: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Calculate MAI and AAH tables for field inventory.

    == Algorithm ==

    A) MAI (Mean Annual Increment — औसत वार्षिक वृद्धि):
       MAI (m³/ha/yr) = Growing_Stock (m³/ha) × (MAI% / 100)
       MAI% is determined by the 3×3 (Growth_Rate × Forest_Condition) matrix
       — see _calculate_mai() docstring for full matrix.

    B) AAH (Annual Allowable Cut — वार्षिक स्वीकार्य कटान):
       AAH (m³/ha/yr) = MAI × AAH_Multiplier

       AAH_Multiplier depends on forest_condition:
         राम्रो (Good)      → 75% (default, user-configurable)
         मध्यम (Moderate)   → 60% (default, user-configurable)
         कमजोर (Weak)       → 40% (default, user-configurable)

       Per-block custom multipliers can be provided as JSON:
       {"Block A": 80.0, "Block B": 55.0}

    # business: MAI/AAH per Nepal Forest Regulation 2075/2079 for sustainable harvest calculation
    These follow Nepal Forest Regulation 2075/2079 guidelines for
    sustainable harvest calculation.
    """
    # Parse custom multipliers if provided
    import json
    custom_mult_dict = {}
    if custom_multipliers:
        try:
            custom_mult_dict = json.loads(custom_multipliers)
        except json.JSONDecodeError:
            pass
    # Verify ownership
    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()

    if not field_inventory:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    # Get all block summaries
    blocks = db.query(FieldInventoryBlockSummary).filter(
        FieldInventoryBlockSummary.field_inventory_calculation_id == field_inventory_id
    ).all()

    if not blocks:
        return {
            "mai_blocks": [],
            "aah_blocks": [],
            "mai_overall": {},
            "aah_overall": {},
            "aah_multipliers": {
                "good": aah_good,
                "moderate": aah_moderate,
                "weak": aah_weak
            }
        }

    # Calculate MAI and AAH for each block
    mai_blocks = []
    aah_blocks = []

    for block in blocks:
        # Get MAI percentage (already calculated)
        mai_percent = float(block.mai_percent or 0) / 100  # Convert to decimal

        # Get volumes
        pole_timber = float(block.pole_timber_m3_per_ha or 0)
        pole_firewood = float(block.pole_firewood_m3_per_ha or 0)
        tree_timber = float(block.tree_timber_m3_per_ha or 0)
        tree_firewood = float(block.tree_firewood_m3_per_ha or 0)
        total_growing_stock = float(block.total_growing_stock_m3_per_ha or 0)

        # Get tree counts
        pole_per_ha = int(block.pole_per_ha or 0)
        tree_per_ha = int(block.tree_per_ha or 0)

        # Calculate MAI volumes (Growing Stock × MAI%)
        mai_pole_timber = pole_timber * mai_percent
        mai_pole_firewood = pole_firewood * mai_percent
        mai_pole_total = mai_pole_timber + mai_pole_firewood
        mai_tree_timber = tree_timber * mai_percent
        mai_tree_firewood = tree_firewood * mai_percent
        mai_tree_total = mai_tree_timber + mai_tree_firewood
        mai_total = total_growing_stock * mai_percent

        # Calculate MAI tree counts (Trees × MAI%)
        mai_pole_per_ha = int(pole_per_ha * mai_percent)
        mai_tree_per_ha = int(tree_per_ha * mai_percent)

        # Determine AAH multiplier based on forest condition
        forest_condition = block.forest_condition
        block_name = block.block_name

        # Check if block has custom multiplier
        if block_name in custom_mult_dict:
            aah_multiplier = custom_mult_dict[block_name] / 100
            is_custom = True
        else:
            # Use default based on forest condition
            if forest_condition == 'Good':
                aah_multiplier = aah_good / 100
            elif forest_condition == 'Moderate':
                aah_multiplier = aah_moderate / 100
            else:  # Weak
                aah_multiplier = aah_weak / 100
            is_custom = False

        # Calculate AAH volumes (MAI × AAH multiplier)
        aah_pole_timber = mai_pole_timber * aah_multiplier
        aah_pole_firewood = mai_pole_firewood * aah_multiplier
        aah_pole_total = mai_pole_total * aah_multiplier
        aah_tree_timber = mai_tree_timber * aah_multiplier
        aah_tree_firewood = mai_tree_firewood * aah_multiplier
        aah_tree_total = mai_tree_total * aah_multiplier
        aah_total = mai_total * aah_multiplier

        # Calculate AAH tree counts (MAI trees × AAH multiplier)
        aah_pole_per_ha = int(mai_pole_per_ha * aah_multiplier)
        aah_tree_per_ha = int(mai_tree_per_ha * aah_multiplier)

        # MAI block data
        mai_blocks.append({
            "block_name": block.block_name,
            "pole_per_ha": mai_pole_per_ha,
            "tree_per_ha": mai_tree_per_ha,
            "pole_timber_m3_per_ha": round(mai_pole_timber, 2),
            "pole_firewood_m3_per_ha": round(mai_pole_firewood, 2),
            "pole_total_m3_per_ha": round(mai_pole_total, 2),
            "tree_timber_m3_per_ha": round(mai_tree_timber, 2),
            "tree_firewood_m3_per_ha": round(mai_tree_firewood, 2),
            "tree_total_m3_per_ha": round(mai_tree_total, 2),
            "total_mai_m3_per_ha": round(mai_total, 2),
            "mai_percent": float(block.mai_percent or 0)
        })

        # Determine default multiplier for this block
        if forest_condition == 'Good':
            default_multiplier = aah_good
        elif forest_condition == 'Moderate':
            default_multiplier = aah_moderate
        else:  # Weak
            default_multiplier = aah_weak

        # AAH block data
        aah_blocks.append({
            "block_name": block.block_name,
            "pole_per_ha": aah_pole_per_ha,
            "tree_per_ha": aah_tree_per_ha,
            "forest_condition": forest_condition,
            "aah_multiplier_percent": aah_multiplier * 100,
            "default_multiplier_percent": default_multiplier,
            "is_custom": is_custom,
            "pole_timber_m3_per_ha": round(aah_pole_timber, 2),
            "pole_firewood_m3_per_ha": round(aah_pole_firewood, 2),
            "pole_total_m3_per_ha": round(aah_pole_total, 2),
            "tree_timber_m3_per_ha": round(aah_tree_timber, 2),
            "tree_firewood_m3_per_ha": round(aah_tree_firewood, 2),
            "tree_total_m3_per_ha": round(aah_tree_total, 2),
            "total_aah_m3_per_ha": round(aah_total, 2)
        })

    # Calculate overall forest averages
    total_blocks = len(blocks)

    # Overall MAI
    avg_mai_pole_per_ha = int(sum(b["pole_per_ha"] for b in mai_blocks) / total_blocks)
    avg_mai_tree_per_ha = int(sum(b["tree_per_ha"] for b in mai_blocks) / total_blocks)
    avg_mai_pole_timber = sum(b["pole_timber_m3_per_ha"] for b in mai_blocks) / total_blocks
    avg_mai_pole_firewood = sum(b["pole_firewood_m3_per_ha"] for b in mai_blocks) / total_blocks
    avg_mai_pole_total = sum(b["pole_total_m3_per_ha"] for b in mai_blocks) / total_blocks
    avg_mai_tree_timber = sum(b["tree_timber_m3_per_ha"] for b in mai_blocks) / total_blocks
    avg_mai_tree_firewood = sum(b["tree_firewood_m3_per_ha"] for b in mai_blocks) / total_blocks
    avg_mai_tree_total = sum(b["tree_total_m3_per_ha"] for b in mai_blocks) / total_blocks
    avg_mai_total = sum(b["total_mai_m3_per_ha"] for b in mai_blocks) / total_blocks
    avg_mai_percent = sum(b["mai_percent"] for b in mai_blocks) / total_blocks

    # Overall AAH
    avg_aah_pole_per_ha = int(sum(b["pole_per_ha"] for b in aah_blocks) / total_blocks)
    avg_aah_tree_per_ha = int(sum(b["tree_per_ha"] for b in aah_blocks) / total_blocks)
    avg_aah_pole_timber = sum(b["pole_timber_m3_per_ha"] for b in aah_blocks) / total_blocks
    avg_aah_pole_firewood = sum(b["pole_firewood_m3_per_ha"] for b in aah_blocks) / total_blocks
    avg_aah_pole_total = sum(b["pole_total_m3_per_ha"] for b in aah_blocks) / total_blocks
    avg_aah_tree_timber = sum(b["tree_timber_m3_per_ha"] for b in aah_blocks) / total_blocks
    avg_aah_tree_firewood = sum(b["tree_firewood_m3_per_ha"] for b in aah_blocks) / total_blocks
    avg_aah_tree_total = sum(b["tree_total_m3_per_ha"] for b in aah_blocks) / total_blocks
    avg_aah_total = sum(b["total_aah_m3_per_ha"] for b in aah_blocks) / total_blocks

    # Overall forest condition (majority vote)
    from collections import Counter
    conditions = [b["forest_condition"] for b in aah_blocks if b["forest_condition"]]
    overall_condition = Counter(conditions).most_common(1)[0][0] if conditions else None

    # Overall AAH multiplier based on overall condition
    if overall_condition == 'Good':
        overall_aah_multiplier = aah_good
    elif overall_condition == 'Moderate':
        overall_aah_multiplier = aah_moderate
    else:
        overall_aah_multiplier = aah_weak

    return {
        "mai_blocks": mai_blocks,
        "aah_blocks": aah_blocks,
        "mai_overall": {
            "block_name": "Overall Forest",
            "pole_per_ha": avg_mai_pole_per_ha,
            "tree_per_ha": avg_mai_tree_per_ha,
            "pole_timber_m3_per_ha": round(avg_mai_pole_timber, 2),
            "pole_firewood_m3_per_ha": round(avg_mai_pole_firewood, 2),
            "pole_total_m3_per_ha": round(avg_mai_pole_total, 2),
            "tree_timber_m3_per_ha": round(avg_mai_tree_timber, 2),
            "tree_firewood_m3_per_ha": round(avg_mai_tree_firewood, 2),
            "tree_total_m3_per_ha": round(avg_mai_tree_total, 2),
            "total_mai_m3_per_ha": round(avg_mai_total, 2),
            "mai_percent": round(avg_mai_percent, 2)
        },
        "aah_overall": {
            "block_name": "Overall Forest",
            "pole_per_ha": avg_aah_pole_per_ha,
            "tree_per_ha": avg_aah_tree_per_ha,
            "forest_condition": overall_condition,
            "aah_multiplier_percent": overall_aah_multiplier,
            "pole_timber_m3_per_ha": round(avg_aah_pole_timber, 2),
            "pole_firewood_m3_per_ha": round(avg_aah_pole_firewood, 2),
            "pole_total_m3_per_ha": round(avg_aah_pole_total, 2),
            "tree_timber_m3_per_ha": round(avg_aah_tree_timber, 2),
            "tree_firewood_m3_per_ha": round(avg_aah_tree_firewood, 2),
            "tree_total_m3_per_ha": round(avg_aah_tree_total, 2),
            "total_aah_m3_per_ha": round(avg_aah_total, 2)
        },
        "aah_multipliers": {
            "good": aah_good,
            "moderate": aah_moderate,
            "weak": aah_weak
        }
    }


@router.delete("/{field_inventory_id}")
def delete_field_inventory(
    field_inventory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Delete field inventory"""
    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()

    if not field_inventory:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    calculation_id = field_inventory.calculation_id
    db.delete(field_inventory)
    db.commit()

    # What was derived from this inventory (SFM result, suggested orientation, auto-listed species, cached output) goes with it,
    # so a replacement inventory starts clean. Best effort: the delete itself has already succeeded.
    if calculation_id:
        try:
            from ..services.field_inventory_cleanup import clear_derived_after_delete

            summary = clear_derived_after_delete(db, calculation_id)
            db.commit()
            logger.info("field inventory deleted; cleared derived data: %s", summary)
        except Exception:  # noqa: BLE001 -- logged; the inventory is gone either way and the next rebuild corrects the rest
            db.rollback()
            logger.exception("field inventory deleted, but clearing its derived data failed")

    return {**i18n_success("success.field_inventory_deleted")}


@router.get("/{field_inventory_id}/export-excel")
def export_field_inventory_excel(
    field_inventory_id: UUID,
    aah_good: float = 75.0,
    aah_moderate: float = AAH_MULTIPLIER["Moderate"],
    aah_weak: float = 40.0,
    custom_multipliers: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    # why: measurement-level export enables pivot tables for custom analysis and audit trails
    Export field inventory as a measurement-level Excel file.
    One row = one tree/plant measurement with all calculated volume metrics,
    block-level per-hectare aggregates, and MAI/AAH rates repeated per row.
    Ideal for further analysis, pivot tables, and custom calculations.
    """
    from ..services.field_inventory_excel_export import generate_field_inventory_excel

    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()

    if not field_inventory:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    custom_mult_dict = {}
    if custom_multipliers:
        try:
            custom_mult_dict = json.loads(custom_multipliers)
        except json.JSONDecodeError:
            pass

    from ..models.calculation import Calculation
    from datetime import datetime, timezone
    from urllib.parse import quote

    # Pre-check: ensure there are measurements before calling the generator
    has_measurements = db.query(FieldInventoryMeasurement).join(
        FieldInventorySamplePlot,
        FieldInventoryMeasurement.sample_plot_id == FieldInventorySamplePlot.id
    ).filter(
        FieldInventorySamplePlot.field_inventory_calculation_id == field_inventory_id
    ).first()
    if not has_measurements:
        raise HTTPException(
            status_code=400,
            detail="No measurements found in this field inventory. Please upload and process measurement data first."
        )

    try:
        excel_bytes = generate_field_inventory_excel(
            db=db,
            field_inventory_id=field_inventory_id,
            aah_good=aah_good,
            aah_moderate=aah_moderate,
            aah_weak=aah_weak,
            custom_multipliers=custom_mult_dict,
        )

        calc = db.query(Calculation).filter(Calculation.id == field_inventory.calculation_id).first()
        forest_name = calc.forest_name.replace(" ", "_") if calc and calc.forest_name else "Forest"
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filename = f"{forest_name}_Field_Inventory_Report_{date_str}.xlsx"

        ascii_fallback = filename.encode("ascii", errors="replace").decode("ascii")
        encoded = quote(filename)

        return StreamingResponse(
            io.BytesIO(excel_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}',
                "Content-Length": str(len(excel_bytes)),
            }
        )
    except ValueError as e:
        detail = str(e)
        if "No measurements found" in detail:
            detail = "No measurements found in this field inventory. Please upload and process measurement data first."
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        logger.error(f"Excel export failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Excel export failed: {str(e)}")


@router.get("/{field_inventory_id}/export-dfo-summary")
def export_field_inventory_dfo_summary(
    field_inventory_id: UUID,
    calculation_id: UUID,
    aah_good: float = 75.0,
    aah_moderate: float = AAH_MULTIPLIER["Moderate"],
    aah_weak: float = 40.0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    # why: DFO-format summary with 15 sheets for division forest office regulatory reporting
    Export DFO-format Nepali block-wise + species-wise summary Excel.
    15 sheets: 6 base (Species×Block, Block Aggregate, Carbon, DBH, Regen, Descriptions)
    + 9 management plan sheets (Species Comp, Block Comparison, Harvest Plan,
    Forest Condition, DBH Volume, Carbon Block, Growth Rate, Stand Structure,
    Productivity).
    """
    from ..services.field_inventory_dfo_export import generate_field_inventory_dfo_summary

    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()

    if not field_inventory:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    try:
        excel_bytes = generate_field_inventory_dfo_summary(
            db=db,
            field_inventory_id=field_inventory_id,
            calculation_id=calculation_id,
            aah_good=aah_good,
            aah_moderate=aah_moderate,
            aah_weak=aah_weak,
        )

        from ..models.calculation import Calculation
        from datetime import datetime, timezone
        from urllib.parse import quote

        calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        forest_name = calc.forest_name.replace(" ", "_") if calc and calc.forest_name else "Forest"
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filename = f"{forest_name}_FieldInventory_DFOSummary_{date_str}.xlsx"

        ascii_fallback = filename.encode("ascii", errors="replace").decode("ascii")
        encoded = quote(filename)

        return StreamingResponse(
            io.BytesIO(excel_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}',
                "Content-Length": str(len(excel_bytes)),
            }
        )
    except ValueError as e:
        detail = str(e)
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        logger.error(f"DFO summary export failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"DFO summary export failed: {str(e)}")


@router.get("/{field_inventory_id}/total-inventory")
def get_total_inventory(
    field_inventory_id: UUID,
    block_areas: Optional[str] = None,
    custom_multipliers: Optional[str] = None,
    aah_good: float = 75.0,
    aah_moderate: float = AAH_MULTIPLIER["Moderate"],
    aah_weak: float = 40.0,
    include_other_species: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    # business: total inventory = per-ha × block area for absolute quantities (CFMG §6.4)
    Calculate total inventory (absolute quantities) by multiplying per-hectare values by block area

    Requires block_areas parameter as JSON string: {"Block A": 45.5, "Block B": 32.0}
    Returns total quantities for each block and forest-wide totals
    """
    # Verify ownership
    field_inventory = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()

    if not field_inventory:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    # Parse block areas
    block_area_dict = {}
    if block_areas:
        try:
            block_area_dict = json.loads(block_areas)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid block_areas JSON format")

    # Compute block effective areas from calculation result_data — same approach
    # as the OP document path (_fetch_block_effective_areas).  Overrides whatever
    # the frontend passed, guaranteeing consistent block name matching.
    try:
        from ..models.calculation import Calculation
        calc = db.query(Calculation).filter(Calculation.id == field_inventory.calculation_id).first()
        if calc and calc.result_data:
            from app.services.tree_cover_analysis import calculate_block_area_details
            from app.services.analysis_polygon_source import PolygonSource
            rd = calc.result_data
            # The unit set the analysis ran on (leaf view: FS-1a.10), not just the blocks array.
            blocks_rd = PolygonSource.for_result_data(rd).get_polygons()
            sub_areas_rd = rd.get('sub_areas', [])
            if blocks_rd:
                details = calculate_block_area_details(db, blocks_rd, sub_areas_rd)
                block_area_dict = {d['block_name']: round(d['effective_area_ha'], 2) for d in details}
    except Exception:
        logger.exception(
            "effective block areas could not be computed - per-block figures "
            "fall back to gross area, which is larger than the usable area"
        )

    # Parse custom AAH multipliers
    custom_mult_dict = {}
    if custom_multipliers:
        try:
            custom_mult_dict = json.loads(custom_multipliers)
        except json.JSONDecodeError:
            pass

    # Get all block summaries
    blocks = db.query(FieldInventoryBlockSummary).filter(
        FieldInventoryBlockSummary.field_inventory_calculation_id == field_inventory_id
    ).all()

    if not blocks:
        return {
            "blocks": [],
            "forest_totals": {},
            "missing_areas": []
        }

    # DBH class keys for implementation plan (Pole + Tree volume-carrying classes)
    # TWO class sets, because there are two questions and they have different
    # answers. Conflating them is what dropped seedling (0-4 cm) and sapling
    # (4-10 cm) out of a stock report: they were computed, stored in
    # `dbh_class_breakdown`, and then projected away before the UI saw them.
    #
    #   * STOCK_DISPLAY - what a forest HOLDS. All eight classes, because
    #     regeneration is real stock and the two largest per-hectare densities in
    #     a forest. Omitting them made a table headed "DBH Class" quietly cover
    #     only 10 cm and above.
    #   * VOLUME_CARRYING - what may be HARVESTED. Pole and tree only, because
    #     regeneration carries no harvestable volume.
    #
    # `dfo_export` is the right set for the second question and the wrong set for
    # the first. The mistake was one variable serving both.
    STOCK_DISPLAY_CLASS_KEYS = [c.key for c in DbhClassRegistry.get_system("guideline_2061")]
    VOLUME_CARRYING_CLASS_KEYS = [c.key for c in DbhClassRegistry.get_system("dfo_export")]

    # Calculate totals for each block
    total_blocks = []
    missing_areas = []

    # Forest-wide accumulators
    forest_total_area = 0
    forest_total_regeneration = 0
    forest_total_sapling = 0
    forest_total_pole = 0
    forest_total_tree = 0
    forest_total_growing_stock = 0
    forest_total_mai = 0
    forest_total_aah = 0
    forest_total_agb = 0
    forest_total_bgb = 0
    forest_total_biomass = 0
    forest_total_carbon = 0
    forest_total_co2 = 0

    # Forest-wide DBH class accumulators
    forest_dbh_class_totals = {}
    for cls_key in STOCK_DISPLAY_CLASS_KEYS:
        forest_dbh_class_totals[cls_key] = {
            "total_count": 0,
            "total_timber_m3": 0.0,
            "total_firewood_m3": 0.0,
            "total_tree_volume_m3": 0.0
        }

    for block in blocks:
        block_name = block.block_name

        # Get block area
        if block_name not in block_area_dict:
            missing_areas.append(block_name)
            continue

        area_ha = float(block_area_dict[block_name])

        # Get per-hectare values
        regeneration_per_ha = int(block.regeneration_per_ha or 0)
        sapling_per_ha = int(block.sapling_per_ha or 0)
        pole_per_ha = int(block.pole_per_ha or 0)
        tree_per_ha = int(block.tree_per_ha or 0)

        pole_timber_per_ha = float(block.pole_timber_m3_per_ha or 0)
        pole_firewood_per_ha = float(block.pole_firewood_m3_per_ha or 0)
        tree_timber_per_ha = float(block.tree_timber_m3_per_ha or 0)
        tree_firewood_per_ha = float(block.tree_firewood_m3_per_ha or 0)
        growing_stock_per_ha = float(block.total_growing_stock_m3_per_ha or 0)

        # Carbon/biomass per hectare
        agb_per_ha = float(block.agb_t_per_ha or 0)
        bgb_per_ha = float(block.bgb_t_per_ha or 0)
        biomass_per_ha = float(block.total_biomass_t_per_ha or 0)
        carbon_per_ha = float(block.carbon_stock_tc_per_ha or 0)
        co2_per_ha = float(block.co2_equivalent_tco2_per_ha or 0)

        # Calculate MAI and AAH
        mai_percent = float(block.mai_percent or 0) / 100
        mai_per_ha = growing_stock_per_ha * mai_percent

        # Determine AAH multiplier
        forest_condition = block.forest_condition
        if block_name in custom_mult_dict:
            aah_multiplier = custom_mult_dict[block_name] / 100
        else:
            if forest_condition == 'Good':
                aah_multiplier = aah_good / 100
            elif forest_condition == 'Moderate':
                aah_multiplier = aah_moderate / 100
            else:
                aah_multiplier = aah_weak / 100

        aah_per_ha = mai_per_ha * aah_multiplier

        # Calculate TOTALS (multiply by area)
        total_regeneration = int(regeneration_per_ha * area_ha)
        total_sapling = int(sapling_per_ha * area_ha)
        total_pole = int(pole_per_ha * area_ha)
        total_tree = int(tree_per_ha * area_ha)

        total_pole_timber = pole_timber_per_ha * area_ha
        total_pole_firewood = pole_firewood_per_ha * area_ha
        total_tree_timber = tree_timber_per_ha * area_ha
        total_tree_firewood = tree_firewood_per_ha * area_ha
        total_growing_stock = growing_stock_per_ha * area_ha
        total_mai = mai_per_ha * area_ha
        total_aah = aah_per_ha * area_ha

        total_agb = agb_per_ha * area_ha
        total_bgb = bgb_per_ha * area_ha
        total_biomass = biomass_per_ha * area_ha
        total_carbon = carbon_per_ha * area_ha
        total_co2 = co2_per_ha * area_ha

        # Compute DBH class breakdown for this block
        dbh_class_per_ha = {}
        dbh_class_totals = {}
        if block.dbh_class_breakdown:
            for cls_key in STOCK_DISPLAY_CLASS_KEYS:
                cls_data = block.dbh_class_breakdown.get(cls_key, {})
                if cls_data:
                    cpk = float(cls_data.get('count_per_ha', 0) or 0)
                    tpk = float(cls_data.get('timber_m3_per_ha', 0) or 0)
                    fpk = float(cls_data.get('firewood_m3_per_ha', 0) or 0)
                    tvpk = tpk + fpk

                    dbh_class_per_ha[cls_key] = {
                        "count_per_ha": round(cpk, 2),
                        "timber_m3_per_ha": round(tpk, 2),
                        "firewood_m3_per_ha": round(fpk, 2),
                        "tree_volume_m3_per_ha": round(tvpk, 2),
                        "label_en": cls_data.get('label_en', ''),
                        "label_np": cls_data.get('label_np', '')
                    }

                    dbh_class_totals[cls_key] = {
                        "total_count": int(round(cpk * area_ha)),
                        "total_timber_m3": round(tpk * area_ha, 2),
                        "total_firewood_m3": round(fpk * area_ha, 2),
                        "total_tree_volume_m3": round(tvpk * area_ha, 2)
                    }

                    # Accumulate forest-wide DBH totals
                    fct = forest_dbh_class_totals[cls_key]
                    fct["total_count"] += int(round(cpk * area_ha))
                    fct["total_timber_m3"] += round(tpk * area_ha, 2)
                    fct["total_firewood_m3"] += round(fpk * area_ha, 2)
                    fct["total_tree_volume_m3"] += round(tvpk * area_ha, 2)

        # Accumulate forest totals
        forest_total_area += area_ha
        forest_total_regeneration += total_regeneration
        forest_total_sapling += total_sapling
        forest_total_pole += total_pole
        forest_total_tree += total_tree
        forest_total_growing_stock += total_growing_stock
        forest_total_mai += total_mai
        forest_total_aah += total_aah
        forest_total_agb += total_agb
        forest_total_bgb += total_bgb
        forest_total_biomass += total_biomass
        forest_total_carbon += total_carbon
        forest_total_co2 += total_co2

        # Build block result
        total_blocks.append({
            "block_name": block_name,
            "area_ha": round(area_ha, 2),
            "sample_plots": block.total_sample_plots,
            "forest_condition": forest_condition,

            # Per-hectare reference values
            "regeneration_per_ha": regeneration_per_ha,
            "sapling_per_ha": sapling_per_ha,
            "pole_per_ha": pole_per_ha,
            "tree_per_ha": tree_per_ha,
            "growing_stock_m3_per_ha": round(growing_stock_per_ha, 2),
            "mai_m3_per_ha": round(mai_per_ha, 2),
            "aah_m3_per_ha": round(aah_per_ha, 2),

            # TOTAL quantities
            "total_regeneration": total_regeneration,
            "total_sapling": total_sapling,
            "total_pole": total_pole,
            "total_tree": total_tree,
            "total_pole_timber_m3": round(total_pole_timber, 2),
            "total_pole_firewood_m3": round(total_pole_firewood, 2),
            "total_tree_timber_m3": round(total_tree_timber, 2),
            "total_tree_firewood_m3": round(total_tree_firewood, 2),
            "total_growing_stock_m3": round(total_growing_stock, 2),
            "total_mai_m3": round(total_mai, 2),
            "total_aah_m3": round(total_aah, 2),
            "total_agb_tonnes": round(total_agb, 2),
            "total_bgb_tonnes": round(total_bgb, 2),
            "total_biomass_tonnes": round(total_biomass, 2),
            "total_carbon_tc": round(total_carbon, 2),
            "total_co2_tco2": round(total_co2, 2),

            # DBH class breakdown
            "dbh_class_per_ha": dbh_class_per_ha,
            "dbh_class_totals": dbh_class_totals,

            # CFMG harvest-class rollup (DBH_SSOT_P2b). Per hectare, so it is a
            # rate in stage 1; the absolute figures are already in
            # `dbh_class_totals` and the stage-3 tables roll those.
            #
            # Regeneration is included and flagged `harvestable: False` rather
            # than dropped (D12): the Operational Plan has always omitted it, and
            # omitting it silently is how a reader ends up believing the three
            # groups cover the whole forest when they cover 10 cm upward.
            "harvest_class_groups": harvest_groups.group_rollup(
                _per_ha_to_harvest_rows(dbh_class_per_ha, block_name),
            ),
        })


    # Forest-wide totals
    forest_totals = {
        "total_area_ha": round(forest_total_area, 2),
        "total_blocks": len(total_blocks),
        "total_regeneration": forest_total_regeneration,
        "total_sapling": forest_total_sapling,
        "total_pole": forest_total_pole,
        "total_tree": forest_total_tree,
        "total_growing_stock_m3": round(forest_total_growing_stock, 2),
        "total_mai_m3_per_year": round(forest_total_mai, 2),
        "total_aah_m3_per_year": round(forest_total_aah, 2),
        "total_agb_tonnes": round(forest_total_agb, 2),
        "total_bgb_tonnes": round(forest_total_bgb, 2),
        "total_biomass_tonnes": round(forest_total_biomass, 2),
        "total_carbon_tc": round(forest_total_carbon, 2),
        "total_co2_tco2": round(forest_total_co2, 2),

        # Forest-wide DBH class totals
        "dbh_class_totals": {
            cls_key: {
                "total_count": int(v["total_count"]),
                "total_timber_m3": round(v["total_timber_m3"], 2),
                "total_firewood_m3": round(v["total_firewood_m3"], 2),
                "total_tree_volume_m3": round(v["total_tree_volume_m3"], 2)
            }
              for cls_key, v in forest_dbh_class_totals.items()
          },
      }

    # CFMG harvest classes, forest-wide (DBH_SSOT_P2b). Sits beside the DBH
    # class totals rather than inside them, because these are a grouping of those
    # classes, not a different set of measurements.
    #
    # The plain sum of the per-compartment rows, which is an exact sum of
    # per-hectare values and must NOT be read as a per-hectare rate: area
    # weighting needs areas, and those are per compartment. D11's weighted figure
    # belongs to the caller that holds the areas; this one is here so the three
    # groups visibly account for every class in the forest.
    forest_totals["harvest_class_groups"] = harvest_groups.forest_rollup(
        [row for b in total_blocks for row in (b.get("harvest_class_groups") or [])]
    )


    # ── Species breakdown (absolute totals across all blocks) ──
    species_breakdown = []
    # Default before the try so the fallback path below cannot leave the response
    # referencing an unbound name. An empty breakdown yields honest zero groups
    # rather than a missing key, so the report shows "no species" instead of
    # silently omitting the section.
    species_policy_groups = build_policy_groups([], ABSOLUTE_MEASURES)
    try:
        from sqlalchemy import text as _sql_text
        pole_area_sqm = 100.0
        tree_area_sqm = 500.0

        sp_block_query = _sql_text("""
            WITH block_total_plots AS (
                SELECT block_name, COUNT(DISTINCT id) as total_plots
                FROM public.field_inventory_sample_plots
                WHERE field_inventory_calculation_id = :fi_id
                GROUP BY block_name
            ),
            species_data AS (
                SELECT
                    sp.block_name,
                    m.species_scientific,
                    m.species_local,
                    m.stand_type,
                    SUM(m.count) as total_count,
                    SUM(COALESCE(m.net_volume, 0)) as total_timber,
                    SUM(COALESCE(m.firewood_m3, 0)) as total_firewood
                FROM public.field_inventory_sample_plots sp
                JOIN public.field_inventory_measurements m ON m.sample_plot_id = sp.id
                WHERE sp.field_inventory_calculation_id = :fi_id
                GROUP BY sp.block_name, m.species_scientific, m.species_local, m.stand_type
            )
            SELECT
                sd.block_name,
                sd.species_scientific,
                sd.species_local,
                btp.total_plots,
                SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_count ELSE 0 END) as pole_count,
                SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_count ELSE 0 END) as tree_count,
                SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_timber ELSE 0 END) as pole_timber,
                SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_firewood ELSE 0 END) as pole_firewood,
                SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_timber ELSE 0 END) as tree_timber,
                SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_firewood ELSE 0 END) as tree_firewood
            FROM species_data sd
            JOIN block_total_plots btp ON btp.block_name = sd.block_name
            GROUP BY sd.block_name, sd.species_scientific, sd.species_local, btp.total_plots
            ORDER BY sd.block_name, sd.species_scientific
        """)

        sp_results = db.execute(sp_block_query, {"fi_id": str(field_inventory_id)}).fetchall()

        species_agg: Dict[str, dict] = {}
        species_order: List[str] = []
        for row in sp_results:
            btp = float(row.total_plots or 1)
            area_ha = block_area_dict.get(row.block_name or "", 0)
            if area_ha <= 0:
                continue

            sci = row.species_scientific or ""
            loc = row.species_local or ""
            key = f"{sci}||{loc}"
            if key not in species_agg:
                species_agg[key] = {"species_scientific": sci, "species_local": loc,
                                    "count": 0, "timber_m3": 0.0, "fuelwood_m3": 0.0, "volume_m3": 0.0}
                species_order.append(key)

            s = species_agg[key]
            pole_cnt = float(row.pole_count or 0)
            tree_cnt = float(row.tree_count or 0)
            pole_tim = float(row.pole_timber or 0)
            pole_fuel = float(row.pole_firewood or 0)
            tree_tim = float(row.tree_timber or 0)
            tree_fuel = float(row.tree_firewood or 0)

            # why: per-ha → absolute extrapolation using block area for DFO reporting format
            # Per-ha = sum_value / total_plots / plot_area * SQM_PER_HA
            s["count"] += int(((pole_cnt / btp / pole_area_sqm) + (tree_cnt / btp / tree_area_sqm)) * SQM_PER_HA * area_ha)
            s["timber_m3"] += round(((pole_tim / btp / pole_area_sqm) + (tree_tim / btp / tree_area_sqm)) * SQM_PER_HA * area_ha, 2)
            s["fuelwood_m3"] += round(((pole_fuel / btp / pole_area_sqm) + (tree_fuel / btp / tree_area_sqm)) * SQM_PER_HA * area_ha, 2)
            s["volume_m3"] += round((((pole_tim + pole_fuel) / btp / pole_area_sqm) + ((tree_tim + tree_fuel) / btp / tree_area_sqm)) * SQM_PER_HA * area_ha, 2)

        species_breakdown = [species_agg[k] for k in species_order]

        # P2/D3: classify at read time and roll up. The rollup sums the very rows
        # above, so `reference + other == total` holds by construction rather than
        # by a second query that could round differently. See species_policy.
        species_policy = annotate_species_rows(species_breakdown)
        species_policy_groups = build_policy_groups(
            species_policy, ABSOLUTE_MEASURES
        )
    except Exception:
        logger.exception(
            "per-species block query failed - the response falls back "
            "without it"
        )
        species_breakdown = []
        species_policy_groups = build_policy_groups([], ABSOLUTE_MEASURES)

    # ── Economic valuation ──
    stumpage_rate = 5000.0
    aah_value_rate = 8000.0
    carbon_price_per_tco2 = 1500.0
    firewood_rate_per_m3 = 500.0

    gs_value = forest_totals.get("total_growing_stock_m3", 0) * stumpage_rate
    aah_value = forest_totals.get("total_aah_m3_per_year", 0) * aah_value_rate
    carbon_value = forest_totals.get("total_co2_tco2", 0) * carbon_price_per_tco2
    firewood_total_m3 = sum(b.get("total_pole_firewood_m3", 0) + b.get("total_tree_firewood_m3", 0) for b in total_blocks)
    firewood_value = firewood_total_m3 * firewood_rate_per_m3

    economic_valuation = {
        "stumpage_rate_per_m3": stumpage_rate,
        "growing_stock_value": round(gs_value, 2),
        "aah_rate_per_m3": aah_value_rate,
        "aah_annual_value": round(aah_value, 2),
        "carbon_price_per_tco2": carbon_price_per_tco2,
        "carbon_value": round(carbon_value, 2),
        "firewood_rate_per_m3": firewood_rate_per_m3,
        "firewood_total_value": round(firewood_value, 2),
        "total_standing_value": round(gs_value + carbon_value + firewood_value, 2),
        "total_annual_value": round(aah_value, 2),
        "currency": "NPR",
        "note": "Values are estimates based on standard rates. Adjust rates as needed.",
    }

    # ── Sustainability indices ──
    total_regen = forest_totals.get("total_regeneration", 0)
    total_tree_count = forest_totals.get("total_tree", 0) + forest_totals.get("total_pole", 0)
    regen_adequacy = round(total_regen / max(total_tree_count, 1), 2) if total_tree_count > 0 else 0

    if regen_adequacy >= 10:
        regen_status = "पर्याप्त"
        regen_status_en = "Adequate"
    elif regen_adequacy >= 5:
        regen_status = "मध्यम"
        regen_status_en = "Moderate"
    else:
        regen_status = "अपर्याप्त"
        regen_status_en = "Inadequate"

    carbon_density = round(forest_totals.get("total_carbon_tc", 0) / max(forest_totals.get("total_area_ha", 1), 1), 2)
    stock_per_ha = round(forest_totals.get("total_growing_stock_m3", 0) / max(forest_totals.get("total_area_ha", 1), 1), 2)
    mai_pct = round((forest_totals.get("total_mai_m3_per_year", 0) / max(forest_totals.get("total_growing_stock_m3", 1), 1)) * 100, 2)

    sustainability_indices = {
        "regeneration_adequacy_ratio": regen_adequacy,
        "regeneration_status_np": regen_status,
        "regeneration_status_en": regen_status_en,
        "carbon_density_tc_per_ha": carbon_density,
        "growing_stock_density_m3_per_ha": stock_per_ha,
        "mai_percent": mai_pct,
        "self_sufficiency_pct": 65.0,
        "self_sufficiency_status_np": "आंशिक",
        "self_sufficiency_status_en": "Partial",
    }

    # ── Chart-ready data ──
    chart_colors = ["#22c55e", "#3b82f6", "#eab308", "#f97316", "#a855f7", "#ec4899", "#14b8a6", "#f43f5e"]
    block_chart_labels = [b["block_name"] for b in total_blocks]
    block_chart_stocks = [b.get("total_growing_stock_m3", 0) for b in total_blocks]
    block_chart_mais = [b.get("total_mai_m3", 0) for b in total_blocks]
    block_chart_aahs = [b.get("total_aah_m3", 0) for b in total_blocks]

    chart_data = {
        "block_stock_pie": {
            "type": "pie",
            "title_np": "ब्लक अनुसार कुल ग्रोइङ स्टक वितरण",
            "title_en": "Block-wise Total Growing Stock Distribution",
            "labels": block_chart_labels,
            "data": block_chart_stocks,
            "backgroundColor": chart_colors[:len(block_chart_labels)],
            "unit": "m³",
        },
        "block_comparison_bar": {
            "type": "bar",
            "title_np": "ब्लक अनुसार ग्रोइङ स्टक, MAI तथा AAH तुलना",
            "title_en": "Block-wise Growing Stock, MAI & AAH Comparison",
            "labels": block_chart_labels,
            "datasets": [
                {"label": "ग्रोइङ स्टक (m³)", "data": block_chart_stocks, "backgroundColor": "#22c55e"},
                {"label": "MAI (m³/yr)", "data": block_chart_mais, "backgroundColor": "#a855f7"},
                {"label": "AAH (m³/yr)", "data": block_chart_aahs, "backgroundColor": "#f59e0b"},
            ],
        },
    }

    # ── AAH table (per-block breakdown) ──
    aah_table = []
    for b in total_blocks:
        cond = b.get("forest_condition", "Moderate")
        gs_ha = b.get("growing_stock_m3_per_ha", 0)
        mai_ha = b.get("mai_m3_per_ha", 0)
        aah_ha = b.get("aah_m3_per_ha", 0)
        aah_mult = round((aah_ha / mai_ha * 100) if mai_ha > 0 else AAH_MULTIPLIER["Moderate"], 0)
        pole_n = b.get("pole_per_ha", 0)
        tree_n = b.get("tree_per_ha", 0)
        total_trees_ha = pole_n + tree_n
        avg_vol_per_tree = gs_ha / total_trees_ha if total_trees_ha > 0 else 0
        aah_tree_count = int(round(aah_ha / avg_vol_per_tree)) if avg_vol_per_tree > 0 else 0
        aah_table.append({
            "block_name": b["block_name"],
            "forest_condition": cond,
            "pole_per_ha": pole_n,
            "tree_per_ha": tree_n,
            "growing_stock_m3_per_ha": round(gs_ha, 2),
            "mai_m3_per_ha": round(mai_ha, 2),
            "aah_multiplier_pct": int(aah_mult),
            "aah_m3_per_ha": round(aah_ha, 2),
            "aah_tree_count_per_ha": aah_tree_count,
            "total_aah_m3_per_year": round(b.get("total_aah_m3", 0), 2),
        })
    # Forest-wide AAH summary row
    ft = forest_totals
    gs_ha_t = ft["total_growing_stock_m3"] / ft["total_area_ha"] if ft["total_area_ha"] > 0 else 0
    mai_ha_t = ft["total_mai_m3_per_year"] / ft["total_area_ha"] if ft["total_area_ha"] > 0 else 0
    aah_ha_t = ft["total_aah_m3_per_year"] / ft["total_area_ha"] if ft["total_area_ha"] > 0 else 0
    pole_n_t = ft.get("total_pole", 0) / ft["total_area_ha"] if ft["total_area_ha"] > 0 else 0
    tree_n_t = ft.get("total_tree", 0) / ft["total_area_ha"] if ft["total_area_ha"] > 0 else 0
    aah_table.append({
        "block_name": "जम्मा वन",
        "forest_condition": "—",
        "pole_per_ha": round(pole_n_t, 0),
        "tree_per_ha": round(tree_n_t, 0),
        "growing_stock_m3_per_ha": round(gs_ha_t, 2),
        "mai_m3_per_ha": round(mai_ha_t, 2),
        "aah_multiplier_pct": int(AAH_MULTIPLIER["Moderate"]),
        "aah_m3_per_ha": round(aah_ha_t, 2),
        "aah_tree_count_per_ha": 0,
        "total_aah_m3_per_year": round(ft["total_aah_m3_per_year"], 2),
    })

    # ── DBH class-wise AAH table ──
    aah_dbh_table = []
    for b in total_blocks:
        dbh_data = b.get("dbh_class_per_ha", {})
        if not dbh_data:
            continue
        total_vol = sum(d.get("tree_volume_m3_per_ha", 0) for d in dbh_data.values())
        total_cnt = sum(d.get("count_per_ha", 0) for d in dbh_data.values())
        aah_ha = b.get("aah_m3_per_ha", 0)
        aah_tree = b.get("aah_tree_count_per_ha", 0)
        for cls_key in VOLUME_CARRYING_CLASS_KEYS:
            d = dbh_data.get(cls_key)
            if not d:
                continue
            vol_frac = d["tree_volume_m3_per_ha"] / total_vol if total_vol > 0 else 0
            cnt_frac = d["count_per_ha"] / total_cnt if total_cnt > 0 else 0
            cls_aah_vol = round(aah_ha * vol_frac, 4)
            cls_aah_tree = round(aah_tree * cnt_frac, 2)
            aah_dbh_table.append({
                "block_name": b["block_name"],
                "dbh_class_key": cls_key,
                "label_np": d.get("label_np", ""),
                "label_en": d.get("label_en", ""),
                "count_per_ha": round(d["count_per_ha"], 2),
                "volume_per_ha": round(d["tree_volume_m3_per_ha"], 2),
                "aah_m3_per_ha": cls_aah_vol,
                "aah_tree_count_per_ha": cls_aah_tree,
            })

    # ── MAI table (per-block breakdown) ──
    mai_table = []
    for b in total_blocks:
        gs_ha = b.get("growing_stock_m3_per_ha", 0)
        mai_ha = b.get("mai_m3_per_ha", 0)
        mai_pct = round((mai_ha / gs_ha * 100) if gs_ha > 0 else 0, 2)
        mai_table.append({
            "block_name": b["block_name"],
            "forest_condition": b.get("forest_condition", ""),
            "growing_stock_m3_per_ha": round(gs_ha, 2),
            "mai_m3_per_ha": round(mai_ha, 2),
            "mai_percent": mai_pct,
            "total_mai_m3_per_year": round(b.get("total_mai_m3", 0), 2),
        })
    ft = forest_totals
    gs_ha_f = ft["total_growing_stock_m3"] / ft["total_area_ha"] if ft["total_area_ha"] > 0 else 0
    mai_ha_f = ft["total_mai_m3_per_year"] / ft["total_area_ha"] if ft["total_area_ha"] > 0 else 0
    mai_pct_f = round((mai_ha_f / gs_ha_f * 100) if gs_ha_f > 0 else 0, 2)
    mai_table.append({
        "block_name": "जम्मा वन",
        "forest_condition": "—",
        "growing_stock_m3_per_ha": round(gs_ha_f, 2),
        "mai_m3_per_ha": round(mai_ha_f, 2),
        "mai_percent": mai_pct_f,
        "total_mai_m3_per_year": round(ft["total_mai_m3_per_year"], 2),
    })

    # ── DBH class-wise MAI table ──
    mai_dbh_table = []
    for b in total_blocks:
        dbh_data = b.get("dbh_class_per_ha", {})
        if not dbh_data:
            continue
        total_vol = sum(d.get("tree_volume_m3_per_ha", 0) for d in dbh_data.values())
        mai_ha = b.get("mai_m3_per_ha", 0)
        for cls_key in VOLUME_CARRYING_CLASS_KEYS:
            d = dbh_data.get(cls_key)
            if not d:
                continue
            vol_frac = d["tree_volume_m3_per_ha"] / total_vol if total_vol > 0 else 0
            cls_mai_vol = round(mai_ha * vol_frac, 4)
            mai_dbh_table.append({
                "block_name": b["block_name"],
                "dbh_class_key": cls_key,
                "label_np": d.get("label_np", ""),
                "label_en": d.get("label_en", ""),
                "volume_per_ha": round(d["tree_volume_m3_per_ha"], 2),
                "mai_m3_per_ha": cls_mai_vol,
            })

    return {
        "blocks": total_blocks,
        "forest_totals": forest_totals,
        "missing_areas": missing_areas,
        "species_breakdown": species_breakdown,
        "species_policy_groups": species_policy_groups,
        # Regulation view: codes 1-21 named, the rest as Terai spp / Hill spp.
        "species_regulation_groups": build_regulation_groups(
            species_breakdown,
            ABSOLUTE_MEASURES,
            region_for_field_inventory(db, field_inventory_id),
            include_other=include_other_species,
        ),
        "economic_valuation": economic_valuation,
        "sustainability_indices": sustainability_indices,
        "chart_data": chart_data,
        "aah_table": aah_table,
        "aah_dbh_table": aah_dbh_table,
        "mai_table": mai_table,
        "mai_dbh_table": mai_dbh_table,
    }


@router.get("/{field_inventory_id}/management-plan-data")
def get_management_plan_data_endpoint(
    field_inventory_id: UUID,
    calculation_id: UUID,
    aah_good: float = 75.0,
    aah_moderate: float = AAH_MULTIPLIER["Moderate"],
    aah_weak: float = 40.0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """# business: management plan data bundles 9 datasets for frontend charts
    Get management plan summary data (all 9 datasets) for frontend charts.
    """
    from ..services.field_inventory_mgmt_data import get_management_plan_data

    fi = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()
    if not fi:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    try:
        data = get_management_plan_data(
            db=db,
            field_inventory_id=field_inventory_id,
            calculation_id=calculation_id,
            aah_good=aah_good,
            aah_moderate=aah_moderate,
            aah_weak=aah_weak,
        )
        return data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{field_inventory_id}/export-management-plan-docx")
def export_management_plan_docx(
    field_inventory_id: UUID,
    calculation_id: UUID,
    aah_good: float = 75.0,
    aah_moderate: float = AAH_MULTIPLIER["Moderate"],
    aah_weak: float = 40.0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Export 10-Year Management Plan DOCX with 12 chapters, embedded maps,
    charts, block-wise 10-year schedule, and data tables.
    Replaces the previous flat maps+charts export.
    """
    from ..services.management_plan_docx import generate_10yr_management_plan_docx

    fi = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()
    if not fi:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    try:
        docx_bytes = generate_10yr_management_plan_docx(
            db=db,
            field_inventory_id=field_inventory_id,
            calculation_id=calculation_id,
            aah_good=aah_good,
            aah_moderate=aah_moderate,
            aah_weak=aah_weak,
        )

        from ..models.calculation import Calculation
        from urllib.parse import quote
        from datetime import datetime, timezone

        calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        forest_name = calc.forest_name.replace(" ", "_") if calc and calc.forest_name else "Forest"
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filename = f"{forest_name}_ManagementPlan_10Yr_{date_str}.docx"

        ascii_fallback = filename.encode("ascii", errors="replace").decode("ascii")
        encoded = quote(filename)

        return StreamingResponse(
            io.BytesIO(docx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}',
                "Content-Length": str(len(docx_bytes)),
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Management plan DOCX export failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Management plan DOCX export failed: {str(e)}")

@router.get("/{field_inventory_id}/export-10yr-plan-docx")
def export_10yr_plan_docx(
    field_inventory_id: UUID,
    calculation_id: UUID,
    aah_good: float = 75.0,
    aah_moderate: float = AAH_MULTIPLIER["Moderate"],
    aah_weak: float = 40.0,
    include_maps: bool = True,
    include_charts: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Export 10-Year Management Plan DOCX with full chapter structure.
    Same as export-management-plan-docx but with additional options
    for including/excluding maps and charts.
    """
    from ..services.management_plan_docx import generate_10yr_management_plan_docx

    fi = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id,
        FieldInventoryCalculation.user_id == current_user.id
    ).first()
    if not fi:
        raise HTTPException(status_code=404, detail="Field inventory not found")

    try:
        docx_bytes = generate_10yr_management_plan_docx(
            db=db,
            field_inventory_id=field_inventory_id,
            calculation_id=calculation_id,
            aah_good=aah_good,
            aah_moderate=aah_moderate,
            aah_weak=aah_weak,
            include_maps=include_maps,
            include_charts=include_charts,
        )

        from ..models.calculation import Calculation
        from urllib.parse import quote
        from datetime import datetime, timezone

        calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        forest_name = calc.forest_name.replace(" ", "_") if calc and calc.forest_name else "Forest"
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filename = f"{forest_name}_10Yr_ManagementPlan_{date_str}.docx"

        ascii_fallback = filename.encode("ascii", errors="replace").decode("ascii")
        encoded = quote(filename)

        return StreamingResponse(
            io.BytesIO(docx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}',
                "Content-Length": str(len(docx_bytes)),
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"10-Year plan DOCX export failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"10-Year plan DOCX export failed: {str(e)}")


# business: species × DBH breakdown for pivot-style analysis across blocks and diameter classes
@router.get("/{field_inventory_id}/species-dbh-breakdown")
def get_species_dbh_breakdown(
    field_inventory_id: UUID,
    include_other_species: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return species breakdown per DBH class (count, timber, fuelwood, volume)."""
    from sqlalchemy import text as _sql_text
    pole_area_sqm = 100.0
    tree_area_sqm = 500.0

    query = _sql_text("""
        WITH block_total_plots AS (
            SELECT block_name, COUNT(DISTINCT id) as total_plots
            FROM public.field_inventory_sample_plots
            WHERE field_inventory_calculation_id = :fi_id
            GROUP BY block_name
        ),
        species_dbh_data AS (
            SELECT
                sp.block_name,
                m.species_scientific,
                m.species_local,
                m.stand_type,
                m.dbh_class,
                SUM(m.count) as total_count,
                SUM(COALESCE(m.net_volume, 0)) as total_timber,
                SUM(COALESCE(m.firewood_m3, 0)) as total_firewood
            FROM public.field_inventory_sample_plots sp
            JOIN public.field_inventory_measurements m ON m.sample_plot_id = sp.id
            WHERE sp.field_inventory_calculation_id = :fi_id
              AND m.dbh_class IS NOT NULL
              AND m.species_scientific IS NOT NULL
            GROUP BY sp.block_name, m.species_scientific, m.species_local, m.stand_type, m.dbh_class
        )
        SELECT
            sd.block_name,
            sd.species_scientific,
            sd.species_local,
            sd.dbh_class,
            btp.total_plots,
            SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_count ELSE 0 END) as pole_count,
            SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_count ELSE 0 END) as tree_count,
            SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_timber ELSE 0 END) as pole_timber,
            SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_firewood ELSE 0 END) as pole_firewood,
            SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_timber ELSE 0 END) as tree_timber,
            SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_firewood ELSE 0 END) as tree_firewood
        FROM species_dbh_data sd
        JOIN block_total_plots btp ON btp.block_name = sd.block_name
        GROUP BY sd.block_name, sd.species_scientific, sd.species_local, sd.dbh_class, btp.total_plots
        ORDER BY sd.block_name, sd.species_scientific, sd.dbh_class
    """)

    results = db.execute(query, {"fi_id": str(field_inventory_id)}).fetchall()

    # Build block-wise species-by-DBH response
    species_dbh_list = []
    block_names: List[str] = []
    for row in results:
        btp = float(row.total_plots or 1)
        pole_cnt = float(row.pole_count or 0)
        tree_cnt = float(row.tree_count or 0)
        pole_tim = float(row.pole_timber or 0)
        pole_fuel = float(row.pole_firewood or 0)
        tree_tim = float(row.tree_timber or 0)
        tree_fuel = float(row.tree_firewood or 0)

        per_ha_factor = SQM_PER_HA / btp
        count_val = int((pole_cnt / pole_area_sqm + tree_cnt / tree_area_sqm) * per_ha_factor)
        timber_val = round((pole_tim / pole_area_sqm + tree_tim / tree_area_sqm) * per_ha_factor, 4)
        fuelwood_val = round((pole_fuel / pole_area_sqm + tree_fuel / tree_area_sqm) * per_ha_factor, 4)
        volume_val = round(((pole_tim + pole_fuel) / pole_area_sqm + (tree_tim + tree_fuel) / tree_area_sqm) * per_ha_factor, 4)

        if row.block_name and row.block_name not in block_names:
            block_names.append(row.block_name)

        species_dbh_list.append({
            "block_name": row.block_name,
            "species_scientific": row.species_scientific or "",
            "species_local": row.species_local or "",
            "dbh_class": row.dbh_class or "",
            "count_per_ha": round(count_val, 2),
            "timber_m3_per_ha": timber_val,
            "fuelwood_m3_per_ha": fuelwood_val,
            "volume_m3_per_ha": volume_val,
        })

    # Forest-wide aggregate (across all blocks)
    fw_query = _sql_text("""
        WITH forest_total_plots AS (
            SELECT COUNT(DISTINCT id) as total_plots
            FROM public.field_inventory_sample_plots
            WHERE field_inventory_calculation_id = :fi_id
        ),
        fw_data AS (
            SELECT
                m.species_scientific,
                m.species_local,
                m.stand_type,
                m.dbh_class,
                SUM(m.count) as total_count,
                SUM(COALESCE(m.net_volume, 0)) as total_timber,
                SUM(COALESCE(m.firewood_m3, 0)) as total_firewood
            FROM public.field_inventory_sample_plots sp
            JOIN public.field_inventory_measurements m ON m.sample_plot_id = sp.id
            WHERE sp.field_inventory_calculation_id = :fi_id2
              AND m.dbh_class IS NOT NULL
              AND m.species_scientific IS NOT NULL
            GROUP BY m.species_scientific, m.species_local, m.stand_type, m.dbh_class
        )
        SELECT
            fw.species_scientific,
            fw.species_local,
            fw.dbh_class,
            ftp.total_plots,
            SUM(CASE WHEN fw.stand_type = 'Pole' THEN fw.total_count ELSE 0 END) as pole_count,
            SUM(CASE WHEN fw.stand_type = 'Tree' THEN fw.total_count ELSE 0 END) as tree_count,
            SUM(CASE WHEN fw.stand_type = 'Pole' THEN fw.total_timber ELSE 0 END) as pole_timber,
            SUM(CASE WHEN fw.stand_type = 'Pole' THEN fw.total_firewood ELSE 0 END) as pole_firewood,
            SUM(CASE WHEN fw.stand_type = 'Tree' THEN fw.total_timber ELSE 0 END) as tree_timber,
            SUM(CASE WHEN fw.stand_type = 'Tree' THEN fw.total_firewood ELSE 0 END) as tree_firewood
        FROM fw_data fw
        CROSS JOIN forest_total_plots ftp
        GROUP BY fw.species_scientific, fw.species_local, fw.dbh_class, ftp.total_plots
        ORDER BY fw.species_scientific, fw.dbh_class
    """)

    fw_results = db.execute(fw_query, {"fi_id": str(field_inventory_id), "fi_id2": str(field_inventory_id)}).fetchall()

    species_dbh_forest = []
    for row in fw_results:
        ftp = float(row.total_plots or 1)
        pole_cnt = float(row.pole_count or 0)
        tree_cnt = float(row.tree_count or 0)
        pole_tim = float(row.pole_timber or 0)
        pole_fuel = float(row.pole_firewood or 0)
        tree_tim = float(row.tree_timber or 0)
        tree_fuel = float(row.tree_firewood or 0)

        per_ha_factor = SQM_PER_HA / ftp
        count_val = int((pole_cnt / pole_area_sqm + tree_cnt / tree_area_sqm) * per_ha_factor)
        timber_val = round((pole_tim / pole_area_sqm + tree_tim / tree_area_sqm) * per_ha_factor, 4)
        fuelwood_val = round((pole_fuel / pole_area_sqm + tree_fuel / tree_area_sqm) * per_ha_factor, 4)
        volume_val = round(((pole_tim + pole_fuel) / pole_area_sqm + (tree_tim + tree_fuel) / tree_area_sqm) * per_ha_factor, 4)

        species_dbh_forest.append({
            "species_scientific": row.species_scientific or "",
            "species_local": row.species_local or "",
            "dbh_class": row.dbh_class or "",
            "count_per_ha": round(count_val, 2),
            "timber_m3_per_ha": timber_val,
            "fuelwood_m3_per_ha": fuelwood_val,
            "volume_m3_per_ha": volume_val,
        })

    return {
        "species_dbh_breakdown": species_dbh_list,
        "species_dbh_forest_wide": species_dbh_forest,
        # P2/D3. Per-compartment and forest-wide, for the per-hectare view.
        # `blocks` is passed so a compartment whose species all fall in one group
        # still appears in the rollup -- a reader comparing compartments needs
        # them all present, not only the mixed ones.
        "species_dbh_policy_groups": build_policy_groups(
            annotate_species_rows(species_dbh_list),
            PER_HA_MEASURES,
            group_by="block_name",
            blocks=block_names,
        ),
        "species_dbh_forest_policy_groups": build_policy_groups(
            annotate_species_rows(species_dbh_forest), PER_HA_MEASURES
        ),
        "species_dbh_forest_regulation_groups": build_regulation_groups(
            species_dbh_forest,
            PER_HA_MEASURES,
            region_for_field_inventory(db, field_inventory_id),
            include_other=include_other_species,
        ),
    }
