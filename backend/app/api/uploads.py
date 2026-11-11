"""Unified upload — the Forest Data Workbook download and the schema it is built from.

One "Download the Forest Data Workbook" button (UNIFIED_UPLOAD_PLAN.md §4.1)
backs onto ``GET /uploads/workbook``; the "Add data" dialog reads
``GET /uploads/schema`` to know every purpose, its columns and its rules.

Read-only. No writes here, so nothing for the idempotency gate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse, Response

from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.user import User
from ..services.upload import schema
from ..services.upload.classify import classify_upload, read_signals
from ..services.upload.csv_columns import read_csv_columns
from ..services.upload.workbook import build_excel, build_geopackage
from ..utils.auth import get_current_active_user

logger = logging.getLogger(__name__)

router = APIRouter()

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_GPKG_MIME = "application/geopackage+sqlite3"


@router.get("/uploads/schema", tags=["Unified Upload"])
def get_upload_schema(current_user: User = Depends(get_current_active_user)):
    """The canonical upload schema — purposes, columns, classification signals,
    validation rules. The single source of truth, as JSON."""
    return JSONResponse(schema.to_dict())


@router.get("/uploads/workbook", tags=["Unified Upload"])
def download_workbook(
    format: str = Query(
        "xlsx",
        pattern="^(xlsx|gpkg)$",
        description="`xlsx` (one sheet per purpose, instructions, example rows) "
        "or `gpkg` (empty typed layers for GIS tools).",
    ),
    current_user: User = Depends(get_current_active_user),
):
    """Download the Forest Data Workbook — the one template for every kind of
    forest data, generated from the canonical schema so it cannot drift from the
    validator."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    try:
        if format == "gpkg":
            body = build_geopackage()
            media, ext = _GPKG_MIME, "gpkg"
        else:
            body = build_excel()
            media, ext = _XLSX_MIME, "xlsx"
    except Exception as exc:  # noqa: BLE001 -- surface generation failure as 500
        logger.exception("Forest Data Workbook generation failed (format=%s)", format)
        raise HTTPException(
            status_code=500, detail=f"Could not generate the workbook: {exc}"
        ) from exc

    filename = f"Forest_Data_Workbook_{stamp}.{ext}"
    return Response(
        content=body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(body)),
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.post("/uploads/csv-columns", tags=["Unified Upload"])
async def csv_columns(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
):
    """Read a CSV/Excel file's columns and sample rows for the column picker (UP-3.2).

    Returns the column names, a few sample rows, and the auto-detected lat/lon
    columns so the user can confirm or override the detection before importing.
    """
    content = await file.read()
    try:
        return read_csv_columns(content, file.filename or "upload.csv")
    except Exception as exc:
        logger.warning("csv-columns failed for %s: %s", file.filename, exc)
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}") from exc


@router.post("/uploads/classify", tags=["Unified Upload"])
async def classify(
    file: UploadFile = File(...),
    expected: Optional[str] = Query(default=None, description="The purpose the user dropped this file for"),
    calculation_id: Optional[str] = Query(default=None, description="When given, say whether the file lies inside this forest"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Identify what a loose file is from its contents (UP-4.2a).

    Reads the first rows / geometry type (signal 2, signal 3) and folds them in
    with the name / layer / sheet signals (signal 1) the frontend already has.
    Returns the ranked candidates, the best match, and — when the caller says
    what it expected — whether the file looks like something else.
    """
    content = await file.read()
    filename = file.filename or "upload.csv"
    signals = read_signals(content, filename)
    result = classify_upload(filename=filename.rsplit(".", 1)[0], **signals)

    out = result.as_dict()
    out["best_label"] = (
        {"en": schema.get(result.best).label_en, "ne": schema.get(result.best).label_ne}
        if result.best
        else None
    )
    if calculation_id:
        from uuid import UUID

        from .workspace import _require_calculation_access
        from ..services.upload.forest_overlap import read_overlap

        _require_calculation_access(db, UUID(calculation_id), current_user)
        out["forest_overlap"] = await read_overlap(db, UUID(calculation_id), content, filename)
    if expected:
        out["expected"] = expected
        expected_p = schema.get(expected)
        out["expected_label"] = (
            {"en": expected_p.label_en, "ne": expected_p.label_ne} if expected_p else None
        )
        out["looks_like_other"] = bool(result.best and result.best != expected)
    return out



@router.post("/uploads/coordinate-system", tags=["Unified Upload"])
def coordinate_system(
    file: UploadFile = File(...),
    calculation_id: Optional[str] = Query(default=None, description="When given, the forest boundary breaks a tie between UTM zones"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Which coordinate system is this table in? (VALIDATION_TRACKER.md, C2)

    Read-only. Reads the longitude / latitude columns (any spelling, typed formats converted), judges every point by its size, and returns the
    systems that could explain the file with the share of points that land inside Nepal under each. The dialog pre-selects ``suggested_epsg``
    and asks when ``ambiguous`` or ``none_fit``; the user's choice is the authority.
    """
    import io

    import pandas as pd

    from ..services.upload.column_synonyms import coordinate_columns
    from ..services.upload.coordinate_text import clean_coordinate_columns
    from ..services.upload.coordinates import SYSTEM_LABELS, detect_systems, forest_bbox

    content = file.file.read()
    filename = file.filename or "upload.csv"
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext not in ("csv", "xlsx", "xls"):
        return {"has_coordinates": False, "reason": "not_a_table"}
    try:
        df = pd.read_excel(io.BytesIO(content)) if ext in ("xlsx", "xls") else pd.read_csv(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 -- an unreadable table is answered, not raised: the import step reports the file properly
        logger.info("coordinate-system: %s could not be read: %s", filename, exc)
        return {"has_coordinates": False, "reason": "unreadable"}
    lon_col, lat_col = coordinate_columns(df.columns, "trees")
    if lon_col is None or lat_col is None:
        return {"has_coordinates": False, "reason": "no_coordinate_columns"}
    ref = None
    if calculation_id:
        from uuid import UUID

        from .workspace import _require_calculation_access
        from ..services.upload.coordinates import forest_bbox as _fb

        _require_calculation_access(db, UUID(calculation_id), current_user)
        ref = _fb(db, UUID(calculation_id))
    cleaned = clean_coordinate_columns(df.rename(columns={lon_col: "longitude", lat_col: "latitude"}))
    result = detect_systems(db, pd.to_numeric(cleaned["longitude"], errors="coerce"), pd.to_numeric(cleaned["latitude"], errors="coerce"), reference_bbox=ref)
    # the system the file DECLARES (the templates make the column required): it wins when the numbers fit it, and the mismatch is named when they do not
    from ..services.upload.coordinates import declared_system

    declared = declared_system(df)
    extra = {"declared": declared, "declared_epsg": declared["epsg"], "declared_ok": None}
    if declared["epsg"] is not None:
        fit = next((c["inside_fraction"] for c in result.get("candidates", []) if c["epsg"] == declared["epsg"]), 0.0)
        extra["declared_fraction"] = fit
        extra["declared_ok"] = fit >= 0.95
        if extra["declared_ok"]:
            result = {**result, "suggested_epsg": declared["epsg"], "ambiguous": False}
    return {"has_coordinates": True, "lon_column": str(lon_col), "lat_column": str(lat_col), "labels": {str(k): v for k, v in SYSTEM_LABELS.items()},
            **result, **extra}


@router.get("/uploads/templates.zip", tags=["Unified Upload"])
def download_templates_zip(
    land_unit: str = Query("ropani", pattern="^(ropani|kaththa)$", description="Land unit of the household workbook"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """The "Download data template" zip: every data type the system reads from Excel or CSV, with the required coordinate-system column,
    validation generated from the shared rule table, and a bilingual README. Generic (no forest needed)."""
    from ..schemas.household_info import TemplateDownloadOptions
    from ..services.upload.field_inventory_template import build_field_inventory_workbook
    from ..services.upload.templates import build_templates_zip
    from .household_info import build_household_template_workbook

    try:
        body = build_templates_zip(
            land_unit,
            household_workbook=lambda unit: build_household_template_workbook(TemplateDownloadOptions(land_unit=unit, include_coordinates=False), None),
            field_inventory_workbook=lambda: build_field_inventory_workbook(db),  # the species list is read fresh from the table
        )
    except Exception as exc:  # noqa: BLE001 -- surface a generation failure as a 500 with the reason
        logger.exception("Data template zip generation failed")
        raise HTTPException(status_code=500, detail=f"Could not generate the templates: {exc}") from exc
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        content=body,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="Forest_Data_Templates_{stamp}.zip"',
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
    )
