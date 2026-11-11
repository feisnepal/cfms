from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Request, Query
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import os
import csv as _csv
import io as _io
import logging

from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.user import User
from ..utils.auth import require_super_admin
from ..core.exceptions import i18n_error
from ..services.translation_service import (
    parse_translation_csv,
    save_translation_csv,
    get_overlay_json,
    list_archived_versions,
    CSV_PATH,
    TRANSLATIONS_DIR,
    MAX_FILE_SIZE_BYTES,
    seed_translations,
    get_overlay_rows,
    upsert_translation,
    missing_placeholders,
    list_translations,
    get_translation_stats,
)
from ..core.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["translations"])


class TranslationUploadResponse(BaseModel):
    success: bool = True
    message: str = "Translations updated successfully"
    key_count: int = Field(..., description="Number of keys parsed from CSV")
    backup_file: Optional[str] = Field(None, description="Previous version backup filename")


class TranslationOverlay(BaseModel):
    ne: Dict[str, object] = Field(default_factory=dict)
    en: Dict[str, object] = Field(default_factory=dict)


class TranslationListResponse(BaseModel):
    current: Optional[str] = Field(None, description="Current CSV filename")
    archives: List[str] = Field(default_factory=list, description="Archived version filenames")


class TranslationErrorResponse(BaseModel):
    detail: str
    errors: Optional[List[Dict[str, str]]] = Field(None, description="Per-row validation errors")


class TranslationUpsertRequest(BaseModel):
    en: Optional[str] = Field(None, description="English text (leave null to keep)")
    ne: Optional[str] = Field(None, description="Nepali text (leave null to keep)")
    note: Optional[str] = Field(None, description="Editor note appended to history")


class TranslationItem(BaseModel):
    id: int
    key: str
    en: Optional[str]
    ne: Optional[str]
    context: Optional[str]
    source_file: str
    is_override: bool
    reviewed: bool
    updated_by: Optional[str]
    history_count: Optional[int] = 0
    updated_at: Optional[str]


class TranslationListPage(BaseModel):
    items: List[TranslationItem]
    total: int
    page: int
    per_page: int


class TranslationStats(BaseModel):
    total_keys: int
    ne_keys: int
    en_keys: int
    untranslated_ne: int
    overrides: int
    reviewed: int
    archive_count: int


class TranslationUpdateResponse(BaseModel):
    id: int
    key: str
    en: Optional[str]
    ne: Optional[str]
    context: Optional[str]
    source_file: str
    is_override: bool
    reviewed: bool
    updated_by: Optional[str]
    history: List[object] = Field(default_factory=list)
    updated_at: Optional[str]


@router.get(
    "/translations/csv",
    response_class=Response,
    responses={
        200: {"content": {"text/csv": {}}, "description": "CSV file with all translation keys"},
        404: {"description": "No translations CSV found"},
    },
    dependencies=[Depends(require_super_admin)],
)
async def download_translations_csv(
    current_user: User = Depends(require_super_admin),
):
    if not CSV_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No translations CSV found. Upload one first via POST /translations/csv",
        )

    content = CSV_PATH.read_bytes()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="geometry_np.csv"',
            "Content-Length": str(len(content)),
        },
    )


@router.post(
    "/translations/csv",
    response_model=TranslationUploadResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": TranslationErrorResponse, "description": "Validation error in CSV"},
        413: {"description": "File too large (max 1MB)"},
        422: {"model": TranslationErrorResponse, "description": "Malformed CSV"},
        429: {"description": "Rate limit exceeded (5/minute)"},
        500: {"description": "Server error during save"},
    },
    dependencies=[Depends(require_super_admin)],
)
@limiter.limit("5/minute")
async def upload_translations_csv(
    file: UploadFile = File(..., description="CSV file (UTF-8 BOM, max 1MB)"),
    current_user: User = Depends(require_super_admin),
    request: Request = None,
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv files are accepted",
        )

    filename = os.path.basename(file.filename)
    if filename != file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename -- path traversal detected",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE_BYTES // (1024*1024)}MB",
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    try:
        result = parse_translation_csv(content)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=TranslationErrorResponse(
                detail="Failed to parse CSV",
                errors=[{"row": "file", "error": str(e)}],
            ).model_dump(),
        )

    if result.get("errors"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=TranslationErrorResponse(
                detail="CSV contains validation errors",
                errors=result["errors"],
            ).model_dump(),
        )

    key_count = result.get("key_count", 0)
    if key_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV contains no valid translation rows",
        )

    # Phase 3: import writes through the DB (overrides), CSV file kept as a
    # durable artifact/backup (existing archive behaviour preserved).
    try:
        text = content.decode("utf-8-sig")
        reader = _csv.DictReader(_io.StringIO(text))
        for row in reader:
            key = (row.get("key") or "").strip()
            if not key:
                continue
            en_val = (row.get("en") or "").strip()
            ne_val = (row.get("np") or row.get("ne") or "").strip()
            if not en_val and not ne_val:
                continue
            upsert_translation(
                db,
                key,
                en=en_val or None,
                ne=ne_val or None,
                user_id=str(current_user.id),
                note="CSV import",
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply CSV to database: {str(e)}",
        )

    if CSV_PATH.exists():
        try:
            backup_file = save_translation_csv(content)
        except IOError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save CSV: {str(e)}",
            )
    else:
        CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        CSV_PATH.write_bytes(content)
        backup_file = None

    logger.info(
        "Translations CSV updated by user %s: %d keys, backup=%s",
        current_user.id, key_count, backup_file,
    )

    return TranslationUploadResponse(
        success=True,
        message=f"Translations updated successfully ({key_count} keys)",
        key_count=key_count,
        backup_file=backup_file,
    )


@router.get(
    "/translations/overlay",
    response_model=TranslationOverlay,
    responses={200: {"description": "JSON overlay with ne/en translations"}},
)
def get_translations_overlay(db: Session = Depends(get_db)):
    """Public overlay: DB overrides (falls back to legacy CSV when empty)."""
    try:
        seed_translations(db)
        overlay = get_overlay_rows(db)
        if not overlay.get("ne") and not overlay.get("en"):
            overlay = get_overlay_json()
    except Exception as exc:
        logger.warning("DB overlay unavailable (%s) — falling back to CSV", exc)
        overlay = get_overlay_json()
    return TranslationOverlay(
        ne=overlay.get("ne", {}),
        en=overlay.get("en", {}),
    )


@router.get(
    "/translations/archive",
    response_model=TranslationListResponse,
    dependencies=[Depends(require_super_admin)],
)
async def list_translation_archives(
    current_user: User = Depends(require_super_admin),
):
    current_name = CSV_PATH.name if CSV_PATH.exists() else None
    archives = list_archived_versions()
    return TranslationListResponse(
        current=current_name,
        archives=[a.name for a in archives],
    )


@router.get(
    "/translations",
    response_model=TranslationListPage,
    dependencies=[Depends(require_super_admin)],
)
def admin_list_translations(
    search: Optional[str] = None,
    lang_is_empty: Optional[str] = Query(None, description="'ne' or 'en' to filter empty"),
    override_only: bool = False,
    category: Optional[str] = None,
    reviewed: Optional[bool] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    seed_translations(db)
    return list_translations(
        db,
        search=search,
        lang_is_empty=lang_is_empty,
        override_only=override_only,
        category=category,
        reviewed=reviewed,
        page=page,
        per_page=per_page,
    )


@router.put(
    "/translations/{key}",
    response_model=TranslationUpdateResponse,
    responses={200: {"description": "Translation upserted"}, 404: {"description": "Key not found"}},
)
def admin_upsert_translation(
    key: str,
    payload: TranslationUpsertRequest,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if not key or not key.strip():
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "translations.key_empty")
    if payload.en is None and payload.ne is None:
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "translations.nothing_to_update")
    seed_translations(db)
    missing = missing_placeholders(db, key.strip(), payload.en, payload.ne)
    if missing:
        raise i18n_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "translations.placeholder_missing",
            placeholders=", ".join(missing),
        )
    updated = upsert_translation(
        db,
        key.strip(),
        en=payload.en,
        ne=payload.ne,
        user_id=str(current_user.id),
        note=payload.note,
    )
    return TranslationUpdateResponse(**updated)


@router.get(
    "/translations/stats",
    response_model=TranslationStats,
    dependencies=[Depends(require_super_admin)],
)
def admin_translation_stats(
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    seed_translations(db)
    return get_translation_stats(db)