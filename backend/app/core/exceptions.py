"""Standardized error types for structured API error responses."""
import json
import re
from typing import Any, Optional

from fastapi import HTTPException

from .i18n_messages import get_message, MESSAGES


class AppException(Exception):
    """Base exception for all application-level errors.

    Serialized to JSON as: { error_code, message, details, correlation_id }
    """

    def __init__(
        self,
        error_code: str,
        message: str,
        http_status: int = 400,
        details: Optional[Any] = None,
        correlation_id: Optional[str] = None,
    ):
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.details = details
        self.correlation_id = correlation_id
        super().__init__(self.message)


class ImportMaxFeaturesExceeded(AppException):
    def __init__(self, count: int, max_count: int):
        super().__init__(
            error_code="IMPORT_MAX_FEATURES_EXCEEDED",
            message=f"Too many features: {count} (max: {max_count})",
            http_status=400,
            details={"count": count, "max": max_count},
        )


class ImportMaxVerticesExceeded(AppException):
    def __init__(self, count: int, max_count: int):
        super().__init__(
            error_code="IMPORT_MAX_VERTICES_EXCEEDED",
            message=f"Too many vertices: {count} (max: {max_count})",
            http_status=400,
            details={"count": count, "max": max_count},
        )


class ImportAreaLimitExceeded(AppException):
    def __init__(self, area_ha: float, max_ha: float):
        super().__init__(
            error_code="IMPORT_AREA_LIMIT_EXCEEDED",
            message=f"Polygon area {area_ha:.1f} ha exceeds max {max_ha} ha",
            http_status=400,
            details={"area_ha": area_ha, "max_ha": max_ha},
        )


class InvalidCrsError(AppException):
    def __init__(self, epsg: int):
        super().__init__(
            error_code="INVALID_CRS",
            message=f"Unsupported CRS: EPSG:{epsg}",
            http_status=400,
            details={"epsg": epsg},
        )


class BlockNotFirstError(AppException):
    def __init__(self):
        super().__init__(
            error_code="BLOCK_NOT_FIRST",
            message="You must import a Block or Compartment layer first before importing sub-layers or reference data",
            http_status=400,
        )


class OwnershipError(AppException):
    def __init__(self, resource: str = "resource"):
        super().__init__(
            error_code="OWNERSHIP_ERROR",
            message=f"You do not have permission to modify this {resource}",
            http_status=403,
        )


class RateLimitExceeded(AppException):
    def __init__(self, retry_after_seconds: int = 60):
        super().__init__(
            error_code="RATE_LIMIT_EXCEEDED",
            message=f"Too many requests. Retry after {retry_after_seconds} seconds.",
            http_status=429,
            details={"retry_after_seconds": retry_after_seconds},
        )


class ImportDuplicateLayer(AppException):
    def __init__(self, purpose: str):
        super().__init__(
            error_code="IMPORT_DUPLICATE_LAYER",
            message=f"A layer with purpose '{purpose}' already exists. Use replace_existing=true to overwrite.",
            http_status=409,
        )


def i18n_error(http_status: int, code: str, **fields: Any) -> HTTPException:
    """Build a bilingual HTTPException detail `{code, message, message_np, **fields}`.

    Placeholders in the message templates (e.g. `{count}`) are resolved in BOTH
    languages via ``str.format`` before the response is built.
    """
    entry = get_message(code)
    en = entry["en"].format(**fields) if fields else entry["en"]
    ne = entry["ne"].format(**fields) if fields else entry["ne"]
    return HTTPException(
        status_code=http_status,
        detail={"code": code, "message": en, "message_np": ne, **fields},
    )


def i18n_success(code: str, **fields: Any) -> dict:
    """Build a bilingual success body `{message, message_np}` for 200/201 responses."""
    entry = get_message(code)
    en = entry["en"].format(**fields) if fields else entry["en"]
    ne = entry["ne"].format(**fields) if fields else entry["ne"]
    return {"message": en, "message_np": ne}


def _message_exists(code: str) -> bool:
    parts = code.split(".")
    node: Any = MESSAGES
    for part in parts[:-1]:
        node = node.get(part, {})
    return isinstance(node, dict) and parts[-1] in node


# Service-layer ValueError prefix → registry code. These keep the Nepali text
# verbatim as `ne` while the registry supplies the matching `en`.
_SERVICE_PREFIX_CODES: dict[str, str] = {
    "CALCULATION_NOT_FOUND": "sampling.calculation_not_found",
    "PLOT_SHAPE_REQUIRED": "sampling.plot_shape_required",
    "NO_ACCESSIBLE_FOREST": "sampling.no_accessible_forest",
    "NO_POINTS_GENERATED": "sampling.no_points_generated",
    "BOUNDARY_EMPTY": "boundary.boundary_empty",
    "BOUNDARY_TYPE_INVALID": "boundary.boundary_type_invalid",
    "BOUNDARY_CHECK_FAILED": "boundary.boundary_check_failed",
    "BOUNDARY_ERROR": "sampling.boundary_error",
    "BOUNDARY_WARNING": "sampling.boundary_warning",
    "INVALID_ROLES": "auth.insufficient_permissions",
    "CF_REG_INVALID": "user_group.invalid_data",
    "POLYGON_INVALID": "geometry.invalid",
    "DIVISION_ONCE_ONLY": "compartments.division_once_only",
    "SAMPLING_MUTEX": "compartments.sampling_mutex",
    "CMT_ALREADY_IN_USE": "compartments.compartment_already_in_use",
    "NOT_COMPARTMENT": "compartments.only_subdivide_compartments",
    "LOCKED": "editing.locked_from_division",
    "PARENT_NOT_FOUND": "blocks.forest_division_not_found",
    "SAME_PLACE": "editing.paste_same_place",
    "STREAM_EMPTY_REQUIRED": "editing.paste_stream_not_empty",
    "BLOCK_REQUIRED": "compartments.only_blocks_dividable",
    "OVER_COVERAGE": "compartments.over_coverage",
    "MAX_PIECES": "editing.divide_too_many_pieces",
    "PIECE_AREA_TOO_LARGE": "editing.divide_area_too_large",
    "PIECE_AREA_TOO_SMALL": "editing.divide_area_too_small",
    "PIECE_AREA_SPLIT_FAILED": "editing.divide_area_split_failed",
    "DIVIDE_COUNT_REQUIRED": "editing.divide_count_required",
    # A < 2-piece divide (rule 17). No new source causes it, but every source can
    # hit it -- `effective_floor_ha` returns the whole area as one piece precisely
    # so a source that yields nothing surfaces this instead of a silent success.
    "DIVISION_TOO_FEW": "editing.divide_too_few",
    # imports / file_processor validators
    "MAX_FEATURES": "imports.max_features_exceeded",
    "MAX_VERTICES": "imports.max_vertices_exceeded",
    "AREA_LIMIT": "imports.area_limit_exceeded",
    "FIRST_LAYER": "imports.boundary_required_first",
    "CRS_UNREADABLE": "imports.crs_unreadable",
    "DUPLICATE_PURPOSE": "imports.duplicate_purpose",
    # SFM कार्यविधि §16 stratum floors
    "SFM_INTENSITY_BELOW_FLOOR": "sampling.intensity_below_floor",
}


def with_message_np(
    detail: dict,
    code: str,
    *,
    fallback_to_self: bool = False,
    preserve_code: bool = False,
    **fields: Any,
) -> dict:
    """Return ``detail`` (already carrying ``code``/``message``) enriched with ``message_np``.

    ``code`` is the registry key used to resolve ``{en, ne}``. When ``preserve_code``
    is True, the dict keeps its own ``code`` field (legacy identifiers such as
    ``TOPOLOGY_REJECTED``) and only ``message``/``message_np`` are filled from the
    registry. When the code is unknown (legacy bare codes surfaced from services,
    e.g. ``str(e)``), the caller can pass ``fallback_to_self=True`` so ``message_np``
    mirrors ``message`` instead of raising ``KeyError``.
    """
    if _message_exists(code):
        entry = get_message(code)
        en = entry["en"].format(**fields) if fields else entry["en"]
        ne = entry["ne"].format(**fields) if fields else entry["ne"]
        out = dict(detail)
        out.update({"message": en, "message_np": ne, **fields})
        if not preserve_code:
            out["code"] = code
        else:
            out.setdefault("code", code)
        return out
    if fallback_to_self:
        return {**dict(detail), "message_np": detail.get("message", "")}
    raise KeyError(f"Unknown i18n message code: {code!r}")


# Registry codes whose templates contain placeholders resolved from the raw ValueError
# text (numeric fields extracted and zipped in template order).
_SERVICE_FIELD_EXTRACTORS: dict[str, list[str]] = {
    "imports.max_features_exceeded": ["count", "max_count"],
    "imports.max_vertices_exceeded": ["count", "max_count"],
    "imports.area_limit_exceeded": ["area", "max"],
    "editing.divide_too_many_pieces": ["count", "max"],
    "editing.divide_area_too_small": ["min"],
}


def resolve_service_detail(text: str) -> dict:
    """Convert prefixed service ``ValueError`` text into a structured bilingual detail.

    Service layers raise messages like ``"CALCULATION_NOT_FOUND: गणना ... फेला परेन"``.
    This strips the known key prefix, resolves the registry code, and keeps the full
    original text available under ``raw`` — the ``message``/``message_np`` fields hold
    the bilingual static text so the value stays readable in both languages.
    """
    code = None
    for prefix in _SERVICE_PREFIX_CODES:
        if text.startswith(f"{prefix}:"):
            code = _SERVICE_PREFIX_CODES[prefix]
            break
    if code is None:
        return {"code": "general.unexpected_error", "message": text, "message_np": text, "raw": text}
    entry = get_message(code)
    fields: dict[str, Any] = {}
    raw_payload = text.split(":", 1)[1].strip()
    json_payload = None
    if raw_payload.startswith("{"):
        try:
            json_payload = json.loads(raw_payload)
        except Exception:  # noqa: BLE001
            json_payload = None
    if isinstance(json_payload, dict):
        # Structured payload (e.g. unit/stratum names) overrides numeric extraction.
        fields = {k: v for k, v in json_payload.items() if isinstance(v, (str, int, float, bool))}
    else:
        field_names = _SERVICE_FIELD_EXTRACTORS.get(code)
        if field_names:
            nums = re.findall(r"(\d+(?:\.\d+)?)", text)
            for name, val in zip(field_names, nums):
                fields[name] = val
    try:
        en = entry["en"].format(**fields) if fields else entry["en"]
        ne = entry["ne"].format(**fields) if fields else entry["ne"]
    except (KeyError, IndexError):
        en, ne = entry["en"], entry["ne"]
    return {
        "code": code,
        "message": en,
        "message_np": ne,
        "raw": text,
    }


#: Categories a *bare* service token may live in, tried in order. Explicit on
#: purpose: 11 bare registry keys collide across categories (``not_found``
#: alone lives in 8), so a global first-match scan would resolve some tokens
#: by luck rather than by intent. A token not listed here keeps the old
#: passthrough behaviour.
_BARE_SERVICE_CATEGORIES: tuple[str, ...] = ("blocks",)


def resolve_bare_service_detail(text: str) -> dict:
    """Resolve a bare, category-less service token (``no_slope_coverage``).

    The auto-block previews raise short tokens like ``no_nasa_quality_coverage``
    rather than dotted registry codes. ``with_message_np`` splits on ``.`` and
    looks the result up at the top level, so a bare token never resolved and the
    user was shown the raw snake_case string in *both* languages -- even for the
    three coverage codes that had been registered all along. This tries
    ``<category>.<token>`` for each category a service token may belong to and
    falls back to the previous passthrough when none matches.
    """
    if ":" in text or "." in text:
        # A prefixed guard message or an already-dotted code: not a bare token.
        return resolve_service_detail(text)
    for category in _BARE_SERVICE_CATEGORIES:
        dotted = f"{category}.{text}"
        if _message_exists(dotted):
            return with_message_np({"code": text, "message": text}, dotted)
    return with_message_np(
        {"code": text, "message": text}, text, fallback_to_self=True
    )
