"""
Inventory API endpoints
Handles tree inventory upload, validation, and processing
"""

from app.services.upload.findings import finding as upload_finding, upload_error
from app.services.upload.coordinates import coordinate_findings, forest_bbox, preview_payload
from app.services.upload.units import dbh_unit_findings, height_unit_findings
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Any
from uuid import UUID
import pandas as pd
import numpy as np
import io
import os
import tempfile

from ..core.database import get_db
from ..core.idempotent_route import IdempotentRoute
from ..middleware.rate_limit import (
    import_limiter,
)  # H8.3: same 5/min budget as workspace layer import
from ..core.geo import calculate_utm_epsg
from ..core.exceptions import i18n_error, i18n_success
from ..services import optimistic_lock
from ..models.user import User
from ..models.inventory import (
    InventoryCalculation,
    InventoryTree,
    TreeSpeciesCoefficient,
)
from ..schemas.inventory import (
    TreeSpeciesCoefficientResponse,
    ValidationReportResponse,
    InventoryCalculationResponse,
    InventoryTreeResponse,
    InventoryTreesListResponse,
    InventorySummaryResponse,
    MyInventoriesResponse,
)
from ..utils.auth import get_current_active_user
from ..services.inventory_validator import InventoryValidator
from ..services.inventory import InventoryService
from ..utils.column_mapper import ColumnMapper
from ..utils.number_format import normalize_nepali_digits
from ..models.calculation import Calculation
from ..utils.column_mapping_helpers import (
    merge_auto_mapping_with_preferences,
    save_user_column_preferences,
    validate_and_prepare_dataframe,
)

import logging

logger = logging.getLogger(__name__)


router = APIRouter(route_class=IdempotentRoute)


def _f(value):
    """Decimal -> float, preserving None (H6.2, migration 060)."""
    return None if value is None else float(value)


def _require_forest(db: Session, calculation_id: Optional[str], user: User) -> None:
    """An inventory must belong to a forest the caller may use.

    Owner's rule, 2026-09-21: deleting a forest deletes all of its data, so no data may exist
    without a forest (migration 092 made ``inventory_calculations.calculation_id`` NOT NULL).
    Checking here, before any file is read, turns a would-be database error into a clear,
    bilingual answer.
    """
    from ..models.user import UserRole

    if not calculation_id:
        raise i18n_error(422, "inventory.forest_required")
    try:
        forest_id = UUID(str(calculation_id))
    except ValueError:
        raise i18n_error(422, "inventory.forest_required")
    forest = db.query(Calculation).filter(Calculation.id == forest_id).first()
    if forest is None:
        raise i18n_error(404, "inventory.forest_not_found")
    if forest.user_id != user.id and user.role != UserRole.SUPER_ADMIN:
        raise i18n_error(403, "inventory.forest_not_yours")


# NOTE: reads CSV, Excel, or GeoPackage — auto-detects format by extension with fallback chain
def read_upload_file(
    content: bytes, filename: str, nrows: Optional[int] = None
) -> pd.DataFrame:
    """
    Read an uploaded file (CSV, Excel, or GeoPackage) into a pandas DataFrame.
    Automatically detects format by extension and falls back if parsing fails.
    GeoPackage geometry columns are extracted into LONGITUDE/LATITUDE columns.
    Returns a DataFrame with Nepali digits normalized in string columns.
    """
    fname = filename.lower()

    def try_csv(data) -> Optional[pd.DataFrame]:
        encodings = ["utf-8", "latin-1", "cp1252", "cp437", "utf-16"]
        for enc in encodings:
            try:
                df = pd.read_csv(io.BytesIO(data), nrows=nrows, encoding=enc)
                if not df.empty:
                    return df
            except (UnicodeDecodeError, UnicodeError):
                continue
            except Exception:
                logger.debug(
                    "CSV preview failed with encoding %s - trying the next one",
                    enc,
                    exc_info=True,
                )
                continue
        return None

    def try_excel(data) -> Optional[pd.DataFrame]:
        try:
            df = pd.read_excel(io.BytesIO(data), nrows=nrows)
            if not df.empty:
                return df
        except Exception:
            logger.warning(
                "default Excel engine could not read the upload - trying "
                "openpyxl next",
                exc_info=True,
            )
        try:
            df = pd.read_excel(io.BytesIO(data), engine="openpyxl", nrows=nrows)
            if not df.empty:
                return df
        except Exception:
            logger.warning(
                "openpyxl could not read the upload either - the caller will be "
                "told the file is unreadable",
                exc_info=True,
            )
        return None

    def try_geopackage(data) -> Optional[pd.DataFrame]:
        try:
            import geopandas as gpd

            with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            try:
                gdf = gpd.read_file(tmp_path, rows=nrows)
            finally:
                os.unlink(tmp_path)

            if gdf.empty:
                return None

            geom_col = gdf.geometry.name
            if (
                geom_col
                and geom_col in gdf.columns
                and hasattr(gdf[geom_col].dtype, "name")
                and gdf[geom_col].dtype.name == "geometry"
            ):
                # Drop pre-existing LONGITUDE/LATITUDE columns to avoid duplicates
                # from GPKG files that also have lon/lat as attribute columns
                for c in ("LONGITUDE", "LATITUDE"):
                    if c in gdf.columns:
                        gdf = gdf.drop(columns=[c])
                gdf["LONGITUDE"] = gdf[geom_col].apply(
                    lambda g: g.x if g is not None and not g.is_empty else None
                )
                gdf["LATITUDE"] = gdf[geom_col].apply(
                    lambda g: g.y if g is not None and not g.is_empty else None
                )
                gdf = gdf.drop(columns=[geom_col])

            return pd.DataFrame(gdf)
        except Exception as e:
            logger.warning(f"GPKG read failed (will not fallback to CSV/Excel): {e}")
            return None

    if fname.endswith(".csv"):
        df = try_csv(content)
        if df is None:
            df = try_excel(content)
    elif fname.endswith((".xlsx", ".xls")):
        df = try_excel(content)
        if df is None:
            df = try_csv(content)
    elif fname.endswith(".gpkg"):
        df = try_geopackage(content)
        if df is None:
            raise i18n_error(400, "inventory.geopackage_read_failed")
    else:
        df = try_csv(content)
        if df is None:
            df = try_excel(content)
        if df is None:
            df = try_geopackage(content)

    if df is None:
        if not content.strip():
            raise upload_error(400, upload_finding("file.empty", file=fname))  # a zero-byte file is not an "unsupported format"
        if fname.endswith(".csv") and len(content.strip().splitlines()) == 1:
            raise upload_error(400, upload_finding("file.no_rows", file=fname))  # one line = the column names and nothing under them
        raise i18n_error(400, "inventory.unsupported_format")
    if df.empty:
        raise upload_error(400, upload_finding("file.no_rows", file=fname))  # column names but no trees: say that, not "unsupported format"

    from app.services.upload.blank_rows import trim_blank_tail

    df = trim_blank_tail(df)  # empty-text rows below the data (a template's calculated columns) are not records
    if df.empty:
        raise upload_error(400, upload_finding("file.no_rows", file=fname))

    df = df.map(lambda v: normalize_nepali_digits(v) if isinstance(v, str) else v)
    # Hand-typed coordinates become numbers, here, once, for every read of the file (preview, confirm, upload, process, accept-corrections all use this
    # reader, so they cannot disagree): degrees-minutes-seconds text (27°41'12"N), decimal commas (84,25), thousands separators (345,678.5).
    # A cell that cannot be read with confidence stays as typed and is named by the validator.
    from app.services.upload.column_synonyms import coordinate_columns
    from app.services.upload.coordinate_text import clean_coordinate_columns

    lon_header, lat_header = coordinate_columns(df.columns, "trees")
    typed_columns = tuple(c for c in (lon_header, lat_header) if c)
    if typed_columns:
        df = clean_coordinate_columns(df, typed_columns)
    return df


def convert_numpy_types(obj: Any) -> Any:
    """
    Recursively convert numpy types to Python native types for JSON serialization
    """
    if isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    else:
        return obj


# business: CFMG — species coefficients drive volume equations for growing stock calculation
@router.get("/species", response_model=List[TreeSpeciesCoefficientResponse])
def list_species(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)
):
    """
    List all available tree species with coefficients
    """
    species = (
        db.query(TreeSpeciesCoefficient)
        .filter(TreeSpeciesCoefficient.is_active == True)
        .order_by(TreeSpeciesCoefficient.scientific_name)
        .all()
    )

    return species


@router.get("/template")
async def download_template(current_user: User = Depends(get_current_active_user)):
    """
    Download CSV template for tree inventory
    """
    # Read template file
    import os

    template_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "templates",
        "TreeInventory_Template.csv",
    )

    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail="Template file not found")

    with open(template_path, "r") as f:
        content = f.read()

    return StreamingResponse(
        io.StringIO(content),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=TreeInventory_Template.csv"
        },
    )


@router.post("/preview-mapping")
async def preview_column_mapping(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Preview automatic column mapping for uploaded CSV file.

    Analyzes the CSV column names and returns:
    - Automatic mapping suggestions
    - Confidence scores
    - Sample data preview (first 5 rows)
    - Missing required columns
    - Duplicate mappings
    - User's saved preferences (if any)

    Use this endpoint BEFORE uploading inventory data to confirm column mapping.
    """
    # Read file (CSV or Excel) - first 10 rows for preview
    try:
        content = await file.read()
        df = read_upload_file(content, file.filename, nrows=10)
    except HTTPException:
        raise
    except Exception as e:
        raise i18n_error(400, "inventory.read_failed", error=str(e))

    if len(df) == 0:
        raise i18n_error(400, "inventory.file_empty")

    # Get automatic mapping merged with user preferences
    try:
        mapping_result = merge_auto_mapping_with_preferences(
            db, current_user.id, df.columns.tolist()
        )
    except Exception as e:
        logger.exception("Failed to analyze columns")
        raise i18n_error(500, "inventory.analyze_failed", error=str(e))

    # Auto-resolve any remaining duplicates: keep the shortest column name
    if mapping_result["duplicates"]:
        mapper = ColumnMapper()
        for std_col, csv_cols in list(mapping_result["duplicates"].items()):
            best = min(csv_cols, key=len)
            for csv_col in csv_cols:
                if csv_col != best:
                    del mapping_result["mapped"][csv_col]
                    del mapping_result["confidence"][csv_col]
                    if csv_col not in mapping_result["unmapped"]:
                        mapping_result["unmapped"].append(csv_col)
        mapping_result["duplicates"] = mapper._check_duplicates(
            mapping_result["mapped"]
        )

    # Prepare sample data (first 5 rows)
    sample_data = df.head(5).replace({np.nan: None}).to_dict("records")

    # Determine if user input is needed
    needs_user_input = (
        len(mapping_result["missing_required"]) > 0
        or len(mapping_result["duplicates"]) > 0
        or any(score < 85 for score in mapping_result["confidence"].values())
    )

    response = {
        "success": True,
        "filename": file.filename,
        "total_rows": len(df),
        "csv_columns": df.columns.tolist(),
        "sample_data": sample_data,
        "mapping": mapping_result["mapped"],
        "confidence": mapping_result["confidence"],
        "unmapped_columns": mapping_result["unmapped"],
        "suggestions": mapping_result["suggestions"],
        "missing_required": mapping_result["missing_required"],
        "duplicates": mapping_result["duplicates"],
        "needs_user_input": needs_user_input,
        "required_columns": ["species", "dia_cm", "height_m", "LONGITUDE", "LATITUDE"],
        "optional_columns": ["class"],
    }

    return convert_numpy_types(response)


# business: CFMG — column mapping workflow enables flexible CSV upload from diverse field formats
@router.post("/confirm-mapping")
async def confirm_and_upload_with_mapping(
    file: UploadFile = File(...),
    mapping: str = Form(...),  # JSON string of {csv_col: std_col}
    save_preference: bool = Form(False),
    calculation_id: Optional[str] = Form(None),
    grid_spacing_meters: float = Form(20.0),
    projection_epsg: Optional[int] = Form(None),
    correction_strategy: str = Form(
        "nearest_tree"
    ),  # "nearest_tree" or "boundary_edge"
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Confirm column mapping and upload inventory CSV.

    This endpoint:
    1. Validates the confirmed mapping
    2. Applies column renaming to the uploaded CSV
    3. Saves user preferences (if requested)
    4. Processes the inventory upload (same as /upload endpoint)

    Args:
        file: CSV file to upload
        mapping: JSON string of column mapping {csv_col: standard_col}
        save_preference: Whether to save this mapping for future uploads
        calculation_id: The forest this inventory belongs to (required — 422 without it)
        grid_spacing_meters: Grid spacing for plot creation
        projection_epsg: Optional projection EPSG code
    """
    _require_forest(db, calculation_id, current_user)

    # Parse mapping JSON
    import json

    try:
        mapping_dict = json.loads(mapping)
    except json.JSONDecodeError:
        raise i18n_error(400, "inventory.mapping_invalid")

    # Read file (CSV or Excel)
    try:
        content = await file.read()
        df = read_upload_file(content, file.filename)
    except HTTPException:
        raise
    except Exception as e:
        raise i18n_error(400, "inventory.read_failed", error=str(e))

    # Validate and apply mapping
    try:
        mapper = ColumnMapper()
        validation = mapper.validate_mapping(mapping_dict)

        if not validation["valid"]:
            return {
                "success": False,
                "errors": validation["errors"],
                "warnings": validation.get("warnings", []),
            }

        # Apply mapping to dataframe
        result = mapper.apply_mapping(df, mapping_dict)
        df_renamed = result["df"]

        logger.info(
            f"Applied column mapping. Renamed columns: {result['renamed_columns']}"
        )
        logger.info(f"Preserved columns: {result['preserved_columns']}")

    except Exception as e:
        raise i18n_error(400, "inventory.mapping_apply_failed", error=str(e))

    # Save user preferences if requested
    if save_preference:
        try:
            save_user_column_preferences(db, current_user.id, mapping_dict)
            logger.info(f"Saved column mapping preferences for user {current_user.id}")
        except Exception as e:
            logger.warning(f"Failed to save user preferences: {str(e)}")
            # Don't fail the upload if preference saving fails

    # Store column mapping in calculation metadata
    column_mapping_metadata = {
        "original_columns": list(mapping_dict.keys()),
        "mapped": mapping_dict,
        "confidence": {},  # Will be populated if we have confidence data
        "preserved_columns": result["preserved_columns"],
    }

    # Now proceed with normal inventory upload validation
    # (Re-use existing validation logic from /upload endpoint)

    # Check if tree mapping already exists for this calculation
    existing_mapping = None
    if calculation_id:
        existing_mapping = (
            db.query(InventoryCalculation)
            .filter(InventoryCalculation.calculation_id == UUID(calculation_id))
            .first()
        )

        # If exists - return it instead of blocking (show user what exists)
        if existing_mapping:
            return {
                "inventory_id": str(existing_mapping.id),
                "exists": True,
                "filename": existing_mapping.uploaded_filename,
                "status": existing_mapping.status,
                "summary": {
                    "ready_for_processing": False,
                    "message": f"Tree mapping already exists: {existing_mapping.uploaded_filename}. Delete it first to upload new data.",
                },
                "errors": [
                    {
                        "type": "existing",
                        "message": f"Tree mapping '{existing_mapping.uploaded_filename}' already exists. Delete it to upload new data.",
                    }
                ],
                "warnings": [],
                "boundary_check": None,
            }

    fname_for_findings = getattr(file, "filename", None)
    # NOTE: boundary check BEFORE full validation — fails fast if >20% outside tolerance
    # IMPORTANT: Check boundary FIRST if calculation_id provided
    # This gives fast feedback if >20% outside, before expensive validation
    boundary_check_result = None
    if calculation_id:
        logger.info(f"[BOUNDARY] Checking boundary first (fast fail for >20%)...")
        try:
            from app.services.boundary_validator import validate_inventory_boundary

            # Get coordinate columns from mapping
            # Find longitude/latitude columns
            x_col = None
            y_col = None
            for csv_col, std_col in mapping_dict.items():
                if std_col.upper() == "LONGITUDE":
                    x_col = std_col
                elif std_col.upper() == "LATITUDE":
                    y_col = std_col

            if (
                x_col
                and y_col
                and x_col in df_renamed.columns
                and y_col in df_renamed.columns
            ):
                # Quick boundary check BEFORE full validation
                # UTM metres are converted (with the zone the user chose) before they are compared with the boundary in degrees; they used to be compared
                # as if they were degrees, so every tree of a UTM file was reported outside the forest.
                from app.services.upload.coordinates import boundary_check_points, forest_bbox as _forest_bbox

                tree_points = boundary_check_points(
                    pd.to_numeric(df_renamed[x_col], errors="coerce"),
                    pd.to_numeric(df_renamed[y_col], errors="coerce"),
                    projection_epsg=projection_epsg,
                    reference_bbox=_forest_bbox(db, UUID(calculation_id)),
                )

                boundary_check_result = validate_inventory_boundary(
                    db, UUID(calculation_id), tree_points, tolerance_percent=20.0
                )

                logger.info(
                    f"[BOUNDARY] Quick check: {boundary_check_result['out_of_boundary_percentage']}% outside, tolerance: {boundary_check_result['within_tolerance']}"
                )

                # If >20% outside, return error IMMEDIATELY (before full validation)
                if not boundary_check_result["within_tolerance"]:
                    logger.warning(
                        f"[BOUNDARY] REJECTED: {boundary_check_result['out_of_boundary_percentage']}% exceeds 20% tolerance"
                    )
                    error_response = {
                        "success": False,
                        "summary": {
                            "total_rows": len(df_renamed),
                            "ready_for_processing": False,
                            "has_critical_errors": True,
                        },
                        "boundary_check": {
                            "total_points": boundary_check_result["total_points"],
                            "out_of_boundary_count": boundary_check_result[
                                "out_of_boundary_count"
                            ],
                            "out_of_boundary_percentage": boundary_check_result[
                                "out_of_boundary_percentage"
                            ],
                            "within_tolerance": False,
                            "needs_correction": False,
                            "correction_strategy": correction_strategy,
                        },
                        "errors": [
                            {
                                "type": "boundary_error",
                                "severity": "error",
                                "message": boundary_check_result.get(
                                    "error_message", "Too many trees outside boundary"
                                ),
                            }
                        ],
                        "warnings": [],
                        "data_detection": {},
                        "corrections": [],
                        "preview": preview_payload(
                            db, calculation_id, pd.to_numeric(df_renamed[x_col], errors="coerce"), pd.to_numeric(df_renamed[y_col], errors="coerce"),
                        ),
                        # UP-3.1: name WHY the points are outside (UTM metres, swapped columns) instead of "verify coordinates, EPSG code..."
                        "findings": [
                            f.to_dict()
                            for f in coordinate_findings(
                                pd.to_numeric(df_renamed[x_col], errors="coerce"), pd.to_numeric(df_renamed[y_col], errors="coerce"),
                                reference_bbox=forest_bbox(db, calculation_id), file=fname_for_findings,
                            )
                        ],
                    }
                    logger.info(
                        f"[BOUNDARY] Returning error response with {len(error_response['errors'])} errors"
                    )
                    return convert_numpy_types(error_response)
        except Exception as e:
            logger.warning(f"[BOUNDARY] Quick check failed: {str(e)}")
            # Continue with normal validation if boundary check fails
            pass

    # Validate data with renamed columns (only if boundary check passed or not applicable)
    logger.info(
        f"[VALIDATION] Starting full inventory validation for {len(df_renamed)} rows..."
    )
    validator = InventoryValidator(db)
    validation_report = await validator.validate_inventory_file(
        df_renamed, user_specified_crs=projection_epsg, calculation_id=calculation_id
    )
    # UP-3.3: a whole column of diameters in millimetres would make every volume ~100x too big. Stop it and say what to do.
    if "dia_cm" in df_renamed.columns:
        mm = dbh_unit_findings([("tree diameters", df_renamed["dia_cm"])], file=fname_for_findings)
        if mm:
            validation_report.setdefault("findings", []).extend(f.to_dict() for f in mm)
            validation_report.setdefault("errors", []).extend(
                {"severity": "error", "type": "dbh_unit", "message": f"{f.title_en} {f.fix_en}", "message_np": f"{f.title_ne} {f.fix_ne}"} for f in mm
            )
            validation_report["summary"].update(ready_for_processing=False, has_critical_errors=True)
    if "height_m" in df_renamed.columns:  # feet look like metres x3.28: a warning only
        ft = height_unit_findings([("tree heights", df_renamed["height_m"])], file=fname_for_findings)
        if ft:
            validation_report.setdefault("findings", []).extend(f.to_dict() for f in ft)
    logger.info(
        f"[VALIDATION] Inventory validation complete. Ready for processing: {validation_report['summary'].get('ready_for_processing')}"
    )

    # Add boundary check to validation report if we already have it from quick check
    if (
        boundary_check_result
        and calculation_id
        and validation_report["summary"].get("ready_for_processing")
    ):
        logger.info(f"[BOUNDARY] Adding boundary check to validation report...")
        validation_report["boundary_check"] = {
            "total_points": boundary_check_result["total_points"],
            "out_of_boundary_count": boundary_check_result["out_of_boundary_count"],
            "out_of_boundary_percentage": boundary_check_result[
                "out_of_boundary_percentage"
            ],
            "within_tolerance": boundary_check_result["within_tolerance"],
            "needs_correction": boundary_check_result["needs_correction"],
            "correction_strategy": correction_strategy,
        }

        # Generate correction preview if corrections are needed (already checked tolerance in quick check)
        if boundary_check_result["needs_correction"]:
            try:
                # Get coordinate columns for correction generation
                coord_cols = validation_report["data_detection"].get(
                    "coordinate_columns", {}
                )
                x_col = coord_cols.get("x")
                y_col = coord_cols.get("y")

                if correction_strategy == "nearest_tree":
                    # Use tree-to-tree correction
                    from app.services.tree_to_tree_corrector import TreeToTreeCorrector

                    corrector = TreeToTreeCorrector(db)
                    corrections_result = corrector.generate_corrections(
                        df_renamed[
                            (
                                [x_col, y_col, "row_number"]
                                if "row_number" in df_renamed.columns
                                else df_renamed[[x_col, y_col]].assign(
                                    row_number=range(1, len(df_renamed) + 1)
                                )
                            )
                        ].rename(columns={x_col: "longitude", y_col: "latitude"}),
                        boundary_check_result["boundary_wkt"],
                        str(UUID(calculation_id)),
                    )

                    validation_report["boundary_check"]["corrections"] = (
                        corrections_result["corrections"]
                    )
                    validation_report["boundary_check"]["correction_summary"] = (
                        corrections_result["correction_summary"]
                    )
                    validation_report["boundary_check"]["correctable"] = (
                        corrections_result["correctable"]
                    )
                    validation_report["boundary_check"]["uncorrectable"] = (
                        corrections_result["uncorrectable"]
                    )
                    validation_report["boundary_check"]["recommendation"] = (
                        corrections_result["recommendation"]
                    )

                else:
                    # Use boundary edge correction (existing method)
                    from app.services.boundary_corrector import (
                        generate_correction_preview,
                    )

                    species_col = validation_report["data_detection"].get(
                        "species_column", "Species"
                    )

                    corrections_preview = generate_correction_preview(
                        df_renamed,
                        boundary_check_result["boundary_wkt"],
                        boundary_check_result["out_of_boundary_points"],
                        x_col,
                        y_col,
                        species_col,
                    )

                    validation_report["boundary_check"]["corrections"] = (
                        corrections_preview["corrections"]
                    )
                    validation_report["boundary_check"]["correction_summary"] = (
                        corrections_preview["summary"]
                    )

            except Exception as e:
                # Log correction generation error but don't fail upload
                logger.warning(f"Correction generation failed: {str(e)}")
                validation_report["warnings"].append(
                    {
                        "type": "correction_generation_error",
                        "severity": "warning",
                        "message": f"Could not generate correction preview: {str(e)}",
                    }
                )

    # If validation passed, create inventory calculation record
    if validation_report["summary"].get("ready_for_processing"):
        # Determine CRS
        detected_crs = validation_report["data_detection"].get("crs", {}).get("epsg")
        if detected_crs == "UNKNOWN":
            detected_crs = projection_epsg or 4326
        elif isinstance(detected_crs, str):
            detected_crs = 4326

        # Determine projection CRS for grid creation
        if projection_epsg and projection_epsg >= 32600:
            final_projection_epsg = projection_epsg
        elif detected_crs == 4326 or detected_crs == "WGS84":
            # Data is in lat/lon - auto-detect UTM zone from mean coordinates (SSOT)
            coord_cols = validation_report["data_detection"].get(
                "coordinate_columns", {}
            )
            x_col = coord_cols.get("x")
            y_col = coord_cols.get("y")
            if x_col and x_col in df_renamed.columns:
                col = df_renamed[x_col]
                if isinstance(col, pd.DataFrame):
                    col = col.iloc[:, 0]
                mean_lon = float(col.mean())
                mean_lat = 0.0
                if y_col and y_col in df_renamed.columns:
                    col_y = df_renamed[y_col]
                    if isinstance(col_y, pd.DataFrame):
                        col_y = col_y.iloc[:, 0]
                    mean_lat = float(col_y.mean())
                final_projection_epsg = calculate_utm_epsg(mean_lon, mean_lat)
                validation_report["info"] = validation_report.get("info", [])
                validation_report["info"].append(
                    {
                        "type": "auto_utm_detection",
                        "message": f"Auto-detected UTM Zone (EPSG:{final_projection_epsg}) based on centroid lon={mean_lon:.2f}°E, lat={mean_lat:.2f}°N",
                    }
                )
            else:
                final_projection_epsg = calculate_utm_epsg(85.0, 27.0)
        else:
            final_projection_epsg = projection_epsg or detected_crs

        inventory = InventoryCalculation(
            user_id=current_user.id,
            calculation_id=UUID(calculation_id) if calculation_id else None,
            uploaded_filename=file.filename,
            grid_spacing_meters=grid_spacing_meters,
            projection_epsg=final_projection_epsg,
            column_mapping=mapping_dict,  # Store column mapping for processing
            status="validated",
        )
        db.add(inventory)

        try:
            db.commit()
            db.refresh(inventory)
        except Exception as e:
            db.rollback()
            if "uq_inventory_calculations_calculation_id" in str(
                e
            ) or "duplicate key value" in str(e):
                # Check what exists and return info
                existing = (
                    db.query(InventoryCalculation)
                    .filter(InventoryCalculation.calculation_id == UUID(calculation_id))
                    .first()
                )
                if existing:
                    return {
                        "inventory_id": str(existing.id),
                        "exists": True,
                        "filename": existing.uploaded_filename,
                        "status": existing.status,
                        "summary": {
                            "ready_for_processing": False,
                            "message": f"Tree mapping already exists: {existing.uploaded_filename}",
                        },
                        "errors": [
                            {
                                "type": "existing",
                                "message": "Tree mapping already exists. Delete it to upload new data.",
                            }
                        ],
                        "warnings": [],
                        "boundary_check": None,
                    }
            raise

        validation_report["inventory_id"] = str(inventory.id)
        validation_report["next_step"] = "POST /api/inventory/{inventory_id}/process"

    # Add column mapping info to report
    validation_report["column_mapping"] = column_mapping_metadata
    validation_report["mapping_applied"] = True

    return convert_numpy_types(validation_report)


# business: CFMG — inventory upload triggers validation and boundary check for growing stock assessment
@router.post("/upload", response_model=dict)
async def upload_inventory(
    file: UploadFile = File(...),
    calculation_id: Optional[str] = Form(None),
    grid_spacing_meters: float = Form(20.0),
    projection_epsg: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Upload and validate tree mapping CSV file

    Returns validation report
    """
    # H8.3 / S3-66: a large file already costs real processing time on a
    # blocking session (S1-17); this bounds how often one user can start that.
    import_limiter.check(current_user.id)

    _require_forest(db, calculation_id, current_user)

    # Check if tree mapping already exists for this calculation - auto-delete if exists
    if calculation_id:
        existing_mapping = (
            db.query(InventoryCalculation)
            .filter(
                InventoryCalculation.calculation_id == UUID(calculation_id),
                InventoryCalculation.user_id == current_user.id,
            )
            .first()
        )

        if existing_mapping:
            # Delete existing mapping (cascade deletes trees)
            db.delete(existing_mapping)
            db.commit()

    # Read file (CSV or Excel)
    try:
        content = await file.read()
        df = read_upload_file(content, file.filename)
    except HTTPException:
        raise
    except Exception as e:
        raise i18n_error(400, "inventory.read_failed", error=str(e))

    # Validate data
    validator = InventoryValidator(db)
    validation_report = await validator.validate_inventory_file(
        df, user_specified_crs=projection_epsg
    )

    # Check boundary if calculation_id is provided
    boundary_check_result = None
    if calculation_id and validation_report["summary"].get("ready_for_processing"):
        try:
            from app.services.boundary_validator import validate_inventory_boundary

            # Get coordinate columns
            coord_cols = validation_report["data_detection"].get(
                "coordinate_columns", {}
            )
            x_col = coord_cols.get("x")
            y_col = coord_cols.get("y")

            if x_col and y_col and x_col in df.columns and y_col in df.columns:
                # Extract tree points (lon, lat, row_number)
                from app.services.upload.coordinates import boundary_check_points, forest_bbox as _forest_bbox

                tree_points = boundary_check_points(  # UTM metres are converted before they are compared with the boundary in degrees
                    pd.to_numeric(df[x_col], errors="coerce"), pd.to_numeric(df[y_col], errors="coerce"),
                    projection_epsg=projection_epsg, reference_bbox=_forest_bbox(db, UUID(calculation_id)),
                )

                # Validate boundary
                boundary_check_result = validate_inventory_boundary(
                    db, UUID(calculation_id), tree_points, tolerance_percent=5.0
                )

                # Add boundary check to validation report
                validation_report["boundary_check"] = {
                    "total_points": boundary_check_result["total_points"],
                    "out_of_boundary_count": boundary_check_result[
                        "out_of_boundary_count"
                    ],
                    "out_of_boundary_percentage": boundary_check_result[
                        "out_of_boundary_percentage"
                    ],
                    "within_tolerance": boundary_check_result["within_tolerance"],
                    "needs_correction": boundary_check_result["needs_correction"],
                }

                # Generate correction preview if corrections are needed
                if boundary_check_result["needs_correction"]:
                    from app.services.boundary_corrector import (
                        generate_correction_preview,
                    )

                    species_col = validation_report["data_detection"].get(
                        "species_column", "Species"
                    )

                    corrections_preview = generate_correction_preview(
                        df,
                        boundary_check_result["boundary_wkt"],
                        boundary_check_result["out_of_boundary_points"],
                        x_col,
                        y_col,
                        species_col,
                    )

                    validation_report["boundary_check"]["corrections"] = (
                        corrections_preview["corrections"]
                    )
                    validation_report["boundary_check"]["correction_summary"] = (
                        corrections_preview["summary"]
                    )

                # If too many points outside boundary, fail validation
                if not boundary_check_result["within_tolerance"]:
                    validation_report["summary"]["ready_for_processing"] = False
                    validation_report["errors"].append(
                        {
                            "type": "boundary_error",
                            "severity": "error",
                            "message": boundary_check_result.get(
                                "error_message", "Too many trees outside boundary"
                            ),
                        }
                    )

        except Exception as e:
            # Log boundary check error but don't fail upload
            import logging

            logging.error(f"Boundary check failed: {str(e)}")
            validation_report["warnings"].append(
                {
                    "type": "boundary_check_error",
                    "severity": "warning",
                    "message": f"Could not validate boundary: {str(e)}",
                }
            )

    # If validation passed, create inventory calculation record
    if validation_report["summary"].get("ready_for_processing"):
        # Determine CRS
        detected_crs = validation_report["data_detection"].get("crs", {}).get("epsg")
        if detected_crs == "UNKNOWN":
            detected_crs = projection_epsg or 4326
        elif isinstance(detected_crs, str):
            detected_crs = 4326

        # Determine projection CRS for grid creation
        # If user specified a UTM zone, use it
        # Otherwise, auto-detect UTM zone based on data longitude
        if projection_epsg and projection_epsg >= 32600:
            # User specified UTM zone
            final_projection_epsg = projection_epsg
        elif detected_crs == 4326 or detected_crs == "WGS84":
            # Data is in lat/lon - auto-detect UTM zone from mean coordinates (SSOT)
            coord_cols = validation_report["data_detection"].get(
                "coordinate_columns", {}
            )
            x_col = coord_cols.get("x")
            y_col = coord_cols.get("y")
            if x_col and x_col in df.columns:
                # Calculate mean longitude/latitude (convert to Python float)
                mean_lon = float(df[x_col].mean())
                mean_lat = (
                    float(df[y_col].mean()) if (y_col and y_col in df.columns) else 0.0
                )
                final_projection_epsg = calculate_utm_epsg(mean_lon, mean_lat)
                validation_report["info"] = validation_report.get("info", [])
                validation_report["info"].append(
                    {
                        "type": "auto_utm_detection",
                        "message": f"Auto-detected UTM Zone (EPSG:{final_projection_epsg}) based on centroid lon={mean_lon:.2f}°E, lat={mean_lat:.2f}°N",
                    }
                )
            else:
                # Default to UTM 45N for Nepal
                final_projection_epsg = calculate_utm_epsg(85.0, 27.0)
        else:
            # Use detected/specified CRS
            final_projection_epsg = projection_epsg or detected_crs

        inventory = InventoryCalculation(
            user_id=current_user.id,
            calculation_id=UUID(calculation_id) if calculation_id else None,
            uploaded_filename=file.filename,
            grid_spacing_meters=grid_spacing_meters,
            projection_epsg=final_projection_epsg,
            status="validated",
        )
        db.add(inventory)

        try:
            db.commit()
            db.refresh(inventory)
        except Exception as e:
            db.rollback()
            # Check if it's a unique constraint violation
            if "uq_inventory_calculations_calculation_id" in str(
                e
            ) or "duplicate key value" in str(e):
                raise i18n_error(400, "inventory.tree_mapping_exists")
            # Re-raise other errors
            raise

        validation_report["inventory_id"] = str(inventory.id)
        validation_report["next_step"] = "POST /api/inventory/{inventory_id}/process"

    # Convert numpy types to native Python types for JSON serialization
    return convert_numpy_types(validation_report)


# business: CFMG — volume calculation using species-specific stem_volume equations from TreeSpeciesCoefficient
@router.post("/{inventory_id}/process", response_model=InventoryCalculationResponse)
async def process_inventory(
    inventory_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Process validated inventory: calculate volumes and store trees

    Requires re-uploading the CSV file for processing
    """
    import logging

    logger = logging.getLogger(__name__)

    import_limiter.check(current_user.id)  # H8.3 / S3-66

    inventory = (
        db.query(InventoryCalculation)
        .filter(
            InventoryCalculation.id == inventory_id,
            InventoryCalculation.user_id == current_user.id,
        )
        .first()
    )

    if not inventory:
        raise i18n_error(404, "inventory.not_found")

    if inventory.status not in ["validated", "failed", "corrections_applied"]:
        raise HTTPException(
            status_code=400,
            detail=f"Inventory cannot be processed. Current status: {inventory.status}",
        )

    # Read file (CSV or Excel)
    try:
        content = await file.read()
        df = read_upload_file(content, file.filename)
    except HTTPException:
        raise
    except Exception as e:
        raise i18n_error(400, "inventory.read_failed", error=str(e))

    # Apply column mapping if it was saved during upload
    if inventory.column_mapping:
        logger.info(f"Applying saved column mapping: {inventory.column_mapping}")
        try:
            from ..utils.column_mapper import ColumnMapper

            mapper = ColumnMapper()
            result = mapper.apply_mapping(df, inventory.column_mapping)
            df = result["df"]
            logger.info(
                f"Column mapping applied. Renamed columns: {result['renamed_columns']}"
            )
        except Exception as e:
            logger.error(f"Failed to apply column mapping: {str(e)}")
            raise HTTPException(
                status_code=400, detail=f"Error applying column mapping: {str(e)}"
            )

    # Check if corrections were applied and need to be used
    from app.models.inventory import TreeCorrectionLog
    import logging

    logger = logging.getLogger(__name__)

    corrections = (
        db.query(TreeCorrectionLog)
        .filter(TreeCorrectionLog.inventory_calculation_id == inventory_id)
        .all()
    )

    if corrections and len(corrections) > 0:
        logger.info(f"Found {len(corrections)} corrections to apply")

        # Detect coordinate columns by looking for common column names
        x_col = None
        y_col = None

        for col in df.columns:
            col_lower = col.lower()
            if col_lower in ["x", "longitude", "lon", "long", "easting"]:
                x_col = col
            if col_lower in ["y", "latitude", "lat", "northing"]:
                y_col = col

        if x_col and y_col:
            # Convert coordinate columns to float to avoid dtype errors
            # (CSV may have read them as integers)
            logger.info(
                f"Converting coordinate columns to float: {x_col}={df[x_col].dtype}, {y_col}={df[y_col].dtype}"
            )
            df[x_col] = df[x_col].astype(float)
            df[y_col] = df[y_col].astype(float)
            logger.info(
                f"Converted to: {x_col}={df[x_col].dtype}, {y_col}={df[y_col].dtype}"
            )

            # Apply each correction
            correction_map = {c.tree_row_number: c for c in corrections}

            for idx in range(len(df)):
                row_num = idx + 1  # CSV rows are 1-indexed (first data row is 1)
                if row_num in correction_map:
                    correction = correction_map[row_num]
                    df.at[idx, x_col] = correction.corrected_x
                    df.at[idx, y_col] = correction.corrected_y
                    logger.debug(f"Applied correction to row {row_num}")

            logger.info(f"Applied {len(corrections)} boundary corrections to dataframe")
        else:
            logger.warning(
                f"Could not detect coordinate columns. Found: {df.columns.tolist()}"
            )

    # Process with simplified service (no GDAL required)
    service = InventoryService(db)

    try:
        result = await service.process_inventory_simple(
            inventory_id=inventory_id,
            df=df,
            grid_spacing_meters=inventory.grid_spacing_meters,
        )

        return inventory

    except Exception as e:
        # process_inventory_simple's own except already deletes+commits the row
        # on most failures (see that method), so `inventory` is often already
        # gone by the time this runs; when it isn't (a failure between here and
        # there), this write is still on the guarded table.
        optimistic_lock.record_derived_write(
            db, "inventory", inventory_id, "pipeline_failed"
        )
        inventory.status = "failed"
        inventory.error_message = str(e)
        db.commit()
        raise i18n_error(500, "inventory.processing_failed", error=str(e))


@router.get("/{inventory_id}/status", response_model=InventoryCalculationResponse)
def get_inventory_status(
    inventory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Get processing status of inventory calculation
    """
    inventory = (
        db.query(InventoryCalculation)
        .filter(
            InventoryCalculation.id == inventory_id,
            InventoryCalculation.user_id == current_user.id,
        )
        .first()
    )

    if not inventory:
        raise i18n_error(404, "inventory.not_found")

    return inventory


@router.get("/{inventory_id}/summary", response_model=InventorySummaryResponse)
def get_inventory_summary(
    inventory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Get inventory summary statistics
    """
    inventory = (
        db.query(InventoryCalculation)
        .filter(
            InventoryCalculation.id == inventory_id,
            InventoryCalculation.user_id == current_user.id,
        )
        .first()
    )

    if not inventory:
        raise i18n_error(404, "inventory.not_found")

    # Get species distribution
    from sqlalchemy import text

    species_query = db.execute(
        text(
            """
        SELECT species, COUNT(*) as count
        FROM public.inventory_trees
        WHERE inventory_calculation_id = :inventory_id
        GROUP BY species
        ORDER BY count DESC
        """
        ),
        {"inventory_id": str(inventory_id)},
    )
    species_distribution = {row[0]: row[1] for row in species_query.fetchall()}

    # constraint: Nepal forest inventory DBH classes — seedling <4cm, sapling 4-10cm, pole 10-30cm, mature >30cm
    # Get DBH classes using subquery
    # Uses Nepal forest inventory standards: seedling <4, sapling 4-10, pole 10-30, mature >30
    dbh_query = db.execute(
        text(
            """
        SELECT dbh_class, COUNT(*) as count
        FROM (
            SELECT
                CASE
                    WHEN dia_cm < 4 THEN 'Seedling (<4cm)'
                    WHEN dia_cm < 10 THEN 'Sapling (4-10cm)'
                    WHEN dia_cm < 30 THEN 'Pole (10-30cm)'
                    ELSE 'Mature (>30cm)'
                END as dbh_class
            FROM public.inventory_trees
            WHERE inventory_calculation_id = :inventory_id AND dia_cm IS NOT NULL
        ) sub
        GROUP BY dbh_class
        ORDER BY dbh_class
        """
        ),
        {"inventory_id": str(inventory_id)},
    )
    dbh_classes = {row[0]: row[1] for row in dbh_query.fetchall()}

    return {
        "inventory_id": inventory.id,
        "total_trees": inventory.total_trees or 0,
        "mother_trees_count": inventory.mother_trees_count or 0,
        "felling_trees_count": inventory.felling_trees_count or 0,
        "seedling_count": inventory.seedling_count or 0,
        "total_volume_m3": inventory.total_volume_m3 or 0,
        "total_net_volume_m3": inventory.total_net_volume_m3 or 0,
        "total_net_volume_cft": inventory.total_net_volume_cft or 0,
        "total_firewood_m3": inventory.total_firewood_m3 or 0,
        "total_firewood_chatta": inventory.total_firewood_chatta or 0,
        "species_distribution": species_distribution,
        "dbh_classes": dbh_classes,
        "status": inventory.status,
        "created_at": inventory.created_at,
        "completed_at": inventory.completed_at,
        "processing_time_seconds": inventory.processing_time_seconds,
    }


@router.get("/{inventory_id}/trees", response_model=InventoryTreesListResponse)
def list_inventory_trees(
    inventory_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    remark: Optional[str] = Query(
        None, description="Filter by remark (Mother Tree, Felling Tree, Seedling)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    List trees in inventory with pagination
    """
    # Verify ownership
    inventory = (
        db.query(InventoryCalculation)
        .filter(
            InventoryCalculation.id == inventory_id,
            InventoryCalculation.user_id == current_user.id,
        )
        .first()
    )

    if not inventory:
        raise i18n_error(404, "inventory.not_found")

    # Build query
    query = db.query(InventoryTree).filter(
        InventoryTree.inventory_calculation_id == inventory_id
    )

    # Apply filters
    if remark:
        query = query.filter(InventoryTree.remark == remark)

    # Get total count
    total_count = query.count()

    # Apply pagination
    offset = (page - 1) * page_size
    trees = query.offset(offset).limit(page_size).all()

    # Convert to response format (with lon/lat)
    # Bulk fetch coordinates for all trees in one query (avoids N+1)
    tree_ids = [tree.id for tree in trees]
    coord_map = {}
    if tree_ids:
        from sqlalchemy import text

        coords = db.execute(
            text(
                "SELECT id, ST_X(location::geometry) as lon, ST_Y(location::geometry) as lat FROM public.inventory_trees WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": [str(tid) for tid in tree_ids]},
        ).all()
        coord_map = {row.id: (row.lon, row.lat) for row in coords}

    tree_responses = []
    for tree in trees:
        lon, lat = coord_map.get(tree.id, (None, None))

        tree_responses.append(
            InventoryTreeResponse(
                id=tree.id,
                species=tree.species,
                local_name=tree.local_name,
                dia_cm=tree.dia_cm,
                height_m=tree.height_m,
                tree_class=tree.tree_class,
                stem_volume=tree.stem_volume,
                branch_volume=tree.branch_volume,
                tree_volume=tree.tree_volume,
                gross_volume=tree.gross_volume,
                net_volume=tree.net_volume,
                net_volume_cft=tree.net_volume_cft,
                firewood_m3=tree.firewood_m3,
                firewood_chatta=tree.firewood_chatta,
                remark=tree.remark,
                grid_cell_id=tree.grid_cell_id,
                block_id=tree.block_id,
                block_name=tree.block_name,
                sub_area_id=tree.sub_area_id,
                sub_area_name=tree.sub_area_name,
                longitude=lon,
                latitude=lat,
            )
        )

    has_more = (offset + len(trees)) < total_count

    return {
        "trees": tree_responses,
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
    }


# constraint: Excel export uses OpenXML format for compatibility with government reporting
@router.get("/{inventory_id}/export")
async def export_inventory(
    inventory_id: UUID,
    format: str = Query("csv", regex="^(csv|geojson)$"),
    module: str = Query("TreeInventory", description="Module name for filename"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Export inventory results (CSV or GeoJSON)
    """
    # Verify ownership
    inventory = (
        db.query(InventoryCalculation)
        .filter(
            InventoryCalculation.id == inventory_id,
            InventoryCalculation.user_id == current_user.id,
        )
        .first()
    )

    if not inventory:
        raise i18n_error(404, "inventory.not_found")

    # Get inventory service
    service = InventoryService(db)

    from app.utils.file_export import build_disposition

    try:
        content, _ = await service.export_inventory(inventory_id, format)

        inventory = (
            db.query(InventoryCalculation)
            .filter(
                InventoryCalculation.id == inventory_id,
                InventoryCalculation.user_id == current_user.id,
            )
            .first()
        )
        forest_name = None
        if inventory and inventory.calculation_id:
            calc = (
                db.query(Calculation)
                .filter(Calculation.id == inventory.calculation_id)
                .first()
            )
            forest_name = calc.forest_name if calc else None

        ext = "csv" if format == "csv" else "geojson"
        _, disposition = build_disposition(forest_name, module, "Data", ext)
        media_type = "text/csv" if format == "csv" else "application/geo+json"

        return StreamingResponse(
            io.BytesIO(content),
            media_type=media_type,
            headers={"Content-Disposition": disposition},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/by-calculation/{calculation_id}", response_model=InventoryCalculationResponse
)
def get_tree_mapping_by_calculation(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Get tree mapping for a specific calculation
    Returns tree mapping if it exists, otherwise 404
    """
    tree_mapping = (
        db.query(InventoryCalculation)
        .filter(
            InventoryCalculation.calculation_id == calculation_id,
            InventoryCalculation.user_id == current_user.id,
        )
        .first()
    )

    if not tree_mapping:
        raise HTTPException(
            status_code=404, detail="No tree mapping found for this calculation"
        )

    return tree_mapping


@router.get("/by-calculation/{calculation_id}/check")
def check_tree_mapping_exists(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Check if ANY tree mapping exists for this calculation (regardless of owner)
    """
    tree_mapping = (
        db.query(InventoryCalculation)
        .filter(InventoryCalculation.calculation_id == calculation_id)
        .first()
    )

    if not tree_mapping:
        return {"exists": False}

    return {
        "exists": True,
        "inventory_id": str(tree_mapping.id),
        "filename": tree_mapping.uploaded_filename,
        "status": tree_mapping.status,
    }


@router.delete("/{inventory_id}")
def delete_inventory(
    inventory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Delete tree mapping calculation and all associated trees
    """
    inventory = (
        db.query(InventoryCalculation)
        .filter(
            InventoryCalculation.id == inventory_id,
            InventoryCalculation.user_id == current_user.id,
        )
        .first()
    )

    if not inventory:
        raise HTTPException(status_code=404, detail="Tree mapping not found")

    db.delete(inventory)
    db.commit()

    return {**i18n_success("success.tree_mapping_deleted")}


@router.delete("/by-calculation/{calculation_id}/force")
def force_delete_inventory_by_calculation(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Force delete tree mapping for a calculation (overrides user ownership)
    """
    inventory = (
        db.query(InventoryCalculation)
        .filter(InventoryCalculation.calculation_id == calculation_id)
        .first()
    )

    if not inventory:
        raise HTTPException(status_code=404, detail="No tree mapping found")

    db.delete(inventory)
    db.commit()

    return {**i18n_success("success.tree_mapping_deleted")}


@router.get("/my-inventories", response_model=MyInventoriesResponse)
def list_my_inventories(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)
):
    """
    List all inventories for current user
    """
    inventories = (
        db.query(InventoryCalculation)
        .filter(InventoryCalculation.user_id == current_user.id)
        .order_by(InventoryCalculation.created_at.desc())
        .all()
    )

    return {"inventories": inventories, "total_count": len(inventories)}


@router.get("/{inventory_id}/correction-preview")
def get_correction_preview(
    inventory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Get preview of boundary corrections for out-of-boundary trees

    Returns proposed corrections without applying them
    """
    from app.services.boundary_validator import get_boundary_from_calculation
    from app.services.boundary_corrector import generate_correction_preview
    from app.models.inventory import TreeCorrectionLog

    # Verify ownership
    inventory = (
        db.query(InventoryCalculation)
        .filter(
            InventoryCalculation.id == inventory_id,
            InventoryCalculation.user_id == current_user.id,
        )
        .first()
    )

    if not inventory:
        raise i18n_error(404, "inventory.not_found")

    if inventory.status != "validated":
        raise HTTPException(
            status_code=400,
            detail=f"Inventory must be in 'validated' status. Current status: {inventory.status}",
        )

    if not inventory.calculation_id:
        raise HTTPException(
            status_code=400, detail="Inventory not linked to a calculation boundary"
        )

    # Check if already corrected
    existing_corrections = (
        db.query(TreeCorrectionLog)
        .filter(TreeCorrectionLog.inventory_calculation_id == inventory_id)
        .first()
    )

    if existing_corrections:
        raise HTTPException(
            status_code=400, detail="Corrections already applied to this inventory"
        )

    # Re-read the uploaded file to get tree data
    # Note: In production, you might want to cache this data
    try:
        import os

        upload_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads"
        )
        # For now, we'll need to re-upload or store the dataframe
        # This is a simplified version - in production, consider storing validated data
        raise HTTPException(
            status_code=501,
            detail="Correction preview requires re-upload. Use process endpoint with corrections enabled.",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{inventory_id}/accept-corrections")
async def accept_corrections(
    inventory_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Apply boundary corrections and proceed with processing

    Requires re-uploading the CSV file
    """
    from app.services.boundary_validator import (
        validate_inventory_boundary,
        get_boundary_from_calculation,
    )
    from app.services.boundary_corrector import (
        generate_correction_preview,
        apply_corrections_to_dataframe,
    )
    from app.models.inventory import TreeCorrectionLog
    from app.services.inventory_validator import InventoryValidator

    logger.info(f"Accepting corrections for inventory {inventory_id}")

    # Verify ownership
    inventory = (
        db.query(InventoryCalculation)
        .filter(
            InventoryCalculation.id == inventory_id,
            InventoryCalculation.user_id == current_user.id,
        )
        .first()
    )

    if not inventory:
        logger.error(f"Inventory {inventory_id} not found for user {current_user.id}")
        raise i18n_error(404, "inventory.not_found")

    logger.info(
        f"Inventory status: {inventory.status}, calculation_id: {inventory.calculation_id}"
    )

    if inventory.status != "validated":
        logger.error(f"Invalid status for corrections: {inventory.status}")
        raise HTTPException(
            status_code=400,
            detail=f"Inventory must be in 'validated' status. Current status: {inventory.status}. "
            f"Cannot apply corrections to inventories that are already processed or have corrections applied.",
        )

    if not inventory.calculation_id:
        logger.error(f"Inventory {inventory_id} not linked to calculation")
        raise HTTPException(
            status_code=400,
            detail="Inventory not linked to a calculation boundary. Please ensure you uploaded the file with a calculation_id.",
        )

    # Read file (CSV, Excel, or GeoPackage)
    try:
        content = await file.read()
        df = read_upload_file(content, file.filename)
        logger.info(
            f"File read successfully: {len(df)} rows, columns: {list(df.columns)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading file: {str(e)}")
        raise i18n_error(400, "inventory.read_failed", error=str(e))

    # Validate again
    validator = InventoryValidator(db)
    validation_report = await validator.validate_inventory_file(df)

    if not validation_report["summary"].get("ready_for_processing"):
        logger.error(f"File validation failed: {validation_report}")
        raise HTTPException(
            status_code=400,
            detail=f"File validation failed. Please check the file format and required columns.",
        )

    # Get coordinate columns
    coord_cols = validation_report["data_detection"].get("coordinate_columns", {})
    x_col = coord_cols.get("x")
    y_col = coord_cols.get("y")
    species_col = "Species"  # Adjust if different

    if not x_col or not y_col:
        logger.error(f"Could not detect coordinates. Found columns: {list(df.columns)}")
        raise HTTPException(
            status_code=400,
            detail=f"Could not detect coordinate columns. Found columns: {list(df.columns)}",
        )

    logger.info(f"Detected coordinate columns: X={x_col}, Y={y_col}")

    # Extract tree points
    from app.services.upload.coordinates import boundary_check_points, forest_bbox as _forest_bbox

    tree_points = boundary_check_points(  # UTM metres are converted before they are compared with the boundary in degrees
        pd.to_numeric(df[x_col], errors="coerce"), pd.to_numeric(df[y_col], errors="coerce"),
        projection_epsg=inventory.projection_epsg, reference_bbox=_forest_bbox(db, inventory.calculation_id),
    )

    # Validate boundary with updated 20% tolerance
    try:
        boundary_check = validate_inventory_boundary(
            db, inventory.calculation_id, tree_points, tolerance_percent=20.0
        )
    except Exception as e:
        logger.error(f"Boundary validation failed: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Boundary validation error: {str(e)}"
        )

    # Provide specific error messages
    if not boundary_check["needs_correction"]:
        # Check why correction is not needed
        if boundary_check["out_of_boundary_count"] == 0:
            raise HTTPException(
                status_code=400,
                detail="All trees are already within the boundary. No corrections needed.",
            )
        elif not boundary_check["within_tolerance"]:
            raise HTTPException(
                status_code=400,
                detail=f"Too many trees outside boundary ({boundary_check['out_of_boundary_percentage']}% > 20%). "
                f"Please check your data: verify coordinates, EPSG code, and boundary selection. "
                f"Automatic correction is only available when <20% of trees are outside the boundary.",
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Boundary correction not available for this dataset",
            )

    # Generate corrections
    try:
        logger.info(
            f"Generating corrections for {len(boundary_check['out_of_boundary_points'])} trees"
        )
        corrections_data = generate_correction_preview(
            df,
            boundary_check["boundary_wkt"],
            boundary_check["out_of_boundary_points"],
            x_col,
            y_col,
            species_col,
        )
        logger.info(f"Generated {len(corrections_data['corrections'])} corrections")
    except Exception as e:
        logger.error(f"Error generating corrections: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate corrections: {str(e)}"
        )

    # Apply corrections to dataframe (not used directly, just for validation)
    try:
        df_corrected = apply_corrections_to_dataframe(
            df, corrections_data["corrections"], x_col, y_col
        )
    except Exception as e:
        logger.error(f"Error applying corrections to dataframe: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to apply corrections: {str(e)}"
        )

    # Log corrections to database
    try:
        for correction in corrections_data["corrections"]:
            correction_log = TreeCorrectionLog(
                inventory_calculation_id=inventory_id,
                tree_row_number=correction["row_number"],
                species=correction["species"],
                original_x=correction["original_x"],
                original_y=correction["original_y"],
                corrected_x=correction["corrected_x"],
                corrected_y=correction["corrected_y"],
                distance_moved_meters=correction["distance_moved_meters"],
                correction_reason="out_of_boundary",
            )
            db.add(correction_log)

        # G-SYNC-2: inventory_calculations is versioned (optimistic_lock.DOMAINS
        # ['inventory']); accepting corrections is a real user decision (not a
        # pipeline-driven transition, cf. InventoryService.process_inventory*),
        # so it takes the lock rather than just declaring the write. The
        # frontend sends no version for this endpoint, so expected=None (logged,
        # not refused — see check_and_bump's docstring).
        optimistic_lock.check_and_bump(db, "inventory", inventory_id, expected=None)

        # Update inventory status
        inventory.status = "corrections_applied"
        db.commit()
        logger.info(
            f"Successfully saved {len(corrections_data['corrections'])} corrections to database"
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Error saving corrections to database: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to save corrections: {str(e)}"
        )

    return {
        "message": "Corrections applied successfully",
        "corrections_count": len(corrections_data["corrections"]),
        "summary": corrections_data["summary"],
        "next_step": "POST /api/inventory/{inventory_id}/process with corrected file",
    }


@router.post("/{inventory_id}/update-block-subarea")
async def update_tree_block_subarea(
    inventory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Resolve block, sub-area, and compartment hierarchy for all trees
    in the inventory using spatial intersection.

    This:
    1. Matches each tree to its containing forest block (top-level, not a compartment)
    2. Matches each tree to its containing sub-area (if any)
    3. Matches each tree to its containing compartment/sub-compartment (if any)
    4. Stores the resolved info on each InventoryTree record

    Call this before exporting CSV to ensure block/sub-area/compartment fields are populated.
    """
    inventory = (
        db.query(InventoryCalculation)
        .filter(
            InventoryCalculation.id == inventory_id,
            InventoryCalculation.user_id == current_user.id,
        )
        .first()
    )

    if not inventory:
        raise i18n_error(404, "inventory.not_found")

    if not inventory.calculation_id:
        raise HTTPException(
            status_code=400, detail="Inventory has no associated calculation"
        )

    service = InventoryService(db)
    try:
        updated_count = await service._update_tree_spatial_relationships(
            inventory_id, inventory.calculation_id
        )
        return {
            "message": "Block/Sub-area updated successfully",
            "trees_updated": updated_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{inventory_id}/grid-cells")
def get_grid_cells(
    inventory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Get grid cell polygons for a processed inventory.

    Reconstructs the grid from stored origin/dimensions (saved during
    mother tree identification) and returns cells clipped to the
    forest boundary as GeoJSON.

    Returns 404 if inventory not found or grid not yet generated.
    """
    from sqlalchemy import text
    import json

    inventory = (
        db.query(InventoryCalculation)
        .filter(
            InventoryCalculation.id == inventory_id,
            InventoryCalculation.user_id == current_user.id,
        )
        .first()
    )

    if not inventory:
        raise i18n_error(404, "inventory.not_found")

    if not inventory.calculation_id:
        raise HTTPException(
            status_code=400, detail="Inventory has no associated calculation"
        )

    # why: grid cells reconstructed on-the-fly for inventories created before grid persistence feature was added
    # Compute grid origin on-the-fly if not yet stored (handles pre-existing inventories)
    if not all(
        [
            inventory.grid_origin_x,
            inventory.grid_origin_y,
            inventory.grid_num_cols,
            inventory.grid_num_rows,
        ]
    ):
        inv_id_str = str(inventory_id)
        bounds = db.execute(
            text(
                """
            SELECT
                ST_XMin(ST_Extent(ST_Transform(location::geometry, :epsg))) AS xmin,
                ST_YMin(ST_Extent(ST_Transform(location::geometry, :epsg))) AS ymin,
                ST_XMax(ST_Extent(ST_Transform(location::geometry, :epsg))) AS xmax,
                ST_YMax(ST_Extent(ST_Transform(location::geometry, :epsg))) AS ymax
            FROM public.inventory_trees
            WHERE inventory_calculation_id = :inv_id
              AND dia_cm > 30
              AND remark != 'Seedling'
        """
            ),
            {"inv_id": inv_id_str, "epsg": inventory.projection_epsg},
        ).first()

        if not bounds or bounds.xmin is None:
            raise HTTPException(
                status_code=404, detail="No eligible trees found for grid generation"
            )

        xmin, ymin, xmax, ymax = bounds.xmin, bounds.ymin, bounds.xmax, bounds.ymax
        num_cols = int((xmax - xmin) / inventory.grid_spacing_meters) + 1
        num_rows = int((ymax - ymin) / inventory.grid_spacing_meters) + 1

        # Persist for subsequent requests
        db.execute(
            text(
                """
            UPDATE public.inventory_calculations
            SET grid_origin_x = :ox, grid_origin_y = :oy,
                grid_num_cols = :nc, grid_num_rows = :nr
            WHERE id = :inv_id
        """
            ),
            {
                "ox": xmin,
                "oy": ymin,
                "nc": num_cols,
                "nr": num_rows,
                "inv_id": inv_id_str,
            },
        )
        db.commit()

        # Refresh the ORM object
        db.refresh(inventory)

    # Get forest boundary WKT directly from DB
    calc_id_str = str(inventory.calculation_id)
    boundary_wkt = db.execute(
        text("SELECT ST_AsText(boundary_geom) FROM calculations WHERE id = :calc_id"),
        {"calc_id": calc_id_str},
    ).scalar()

    if not boundary_wkt:
        raise HTTPException(status_code=404, detail="Calculation boundary not found")

    inv_id_str = str(inventory_id)

    # Reconstruct grid cells from stored params, clip to boundary,
    # and spatially JOIN mother tree data (one tree per cell)
    rows = db.execute(
        text(
            """
        WITH
        col_series AS (
            SELECT generate_series(0, :num_cols - 1) AS col
        ),
        row_series AS (
            SELECT generate_series(0, :num_rows - 1) AS row
        ),
        grid AS (
            SELECT
                row_number() OVER (ORDER BY col, row) AS cell_id,
                ST_SetSRID(ST_MakeEnvelope(
                    :origin_x + col::double precision * :grid_size,
                    :origin_y + row::double precision * :grid_size,
                    :origin_x + (col::double precision + 1) * :grid_size,
                    :origin_y + (row::double precision + 1) * :grid_size
                ), :projection_epsg) AS geom
            FROM col_series, row_series
        )
        SELECT
            g.cell_id,
            ST_AsGeoJSON(ST_Transform(g.geom, 4326), 6) AS geojson,
            mt.id AS mother_tree_id,
            mt.species AS mother_tree_species,
            mt.dia_cm AS mother_tree_dbh,
            mt.height_m AS mother_tree_height,
            mt.tree_volume AS mother_tree_volume,
            mt.net_volume AS mother_tree_net_volume,
            mt.firewood_m3 AS mother_tree_firewood
        FROM grid g
        LEFT JOIN public.inventory_trees mt
            ON mt.inventory_calculation_id = :inventory_id
            AND mt.remark = 'Mother Tree'
            AND ST_Contains(g.geom, ST_Transform(mt.location::geometry, :projection_epsg))
        WHERE ST_Intersects(
            g.geom,
            ST_Transform(
                ST_SetSRID(ST_GeomFromText(:boundary_wkt), 4326),
                :projection_epsg
            )
        )
        ORDER BY g.cell_id
    """
        ),
        {
            "origin_x": inventory.grid_origin_x,
            "origin_y": inventory.grid_origin_y,
            "num_cols": inventory.grid_num_cols,
            "num_rows": inventory.grid_num_rows,
            "grid_size": inventory.grid_spacing_meters,
            "projection_epsg": inventory.projection_epsg,
            "boundary_wkt": boundary_wkt,
            "inventory_id": inv_id_str,
        },
    ).fetchall()

    features = []
    for row in rows:
        props = {"cell_id": row.cell_id}
        if row.mother_tree_id:
            props["mother_tree"] = {
                "id": str(row.mother_tree_id),
                "species": row.mother_tree_species,
                # H6.2: Numeric as of migration 060 -- GeoJSON properties must
                # be JSON scalars, and `json.dumps` refuses a Decimal.
                "dbh_cm": _f(row.mother_tree_dbh),
                "height_m": _f(row.mother_tree_height),
                "volume_m3": _f(row.mother_tree_volume),
                "net_volume_m3": _f(row.mother_tree_net_volume),
                "firewood_m3": _f(row.mother_tree_firewood),
            }
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(row.geojson),
                "properties": props,
            }
        )

    return {
        "features": features,
        "metadata": {
            "grid_spacing_meters": inventory.grid_spacing_meters,
            "origin_x": inventory.grid_origin_x,
            "origin_y": inventory.grid_origin_y,
            "num_cols": inventory.grid_num_cols,
            "num_rows": inventory.grid_num_rows,
            "total_cells": inventory.grid_num_cols * inventory.grid_num_rows,
            "cells_within_boundary": len(features),
            "projection_epsg": inventory.projection_epsg,
        },
    }


# business: CFMG — analysis endpoint provides sm_* variable data for operational plan reports
@router.get("/{inventory_id}/analysis")
def get_inventory_analysis(
    inventory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Get tree mapping analysis data for sm_* variables.
    Returns spatial hierarchy summary, species composition, DBH distribution,
    stand type, carbon stock, volume analysis, and mother tree coverage.
    """
    try:
        service = InventoryService(db)
        data = service.get_inventory_analysis(inventory_id)
        return data
    except Exception as e:
        logger.error("Error getting inventory analysis: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
