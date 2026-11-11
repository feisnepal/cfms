"""
Centralized API error-code map — flattened registry bridge
===========================================================

Phase 2 of the Nepali-first i18n initiative collapses the legacy per-domain
constant classes into a single ``PREFERRED_CODES`` map: legacy English message
string → dotted registry code (see ``app/core/i18n_messages.py``).

Usage:
    from app.core.errors import CalculationErrors, PREFERRED_CODES, resolve_detail
    raise HTTPException(404, CalculationErrors.NOT_FOUND)          # legacy shape
    detail = resolve_detail("Calculation not found")               # -> bilingual dict
    detail = resolve_detail({"code": "auth.invalid_credentials"})  # -> bilingual dict

Rules:
  1. ``CalculationErrors.NOT_FOUND`` is kept as the ONE compatibility constant
     (used by 115 call sites) and maps to ``calculations.not_found``.
  2. New code — raise via ``app.core.exceptions.i18n_error``.
  3. ``resolve_detail`` handles BOTH response shapes during migration: raw
     string details (old) and ``{code,...}`` dicts (new).
"""

from typing import Any, Dict

from .i18n_messages import get_message

class CalculationErrors:
    """Compatibility constant — the ONE legacy class kept (NOT_FOUND, ×115 call sites)."""

    NOT_FOUND = "Calculation not found"

# Single flat map: legacy English message → dotted registry code.
PREFERRED_CODES: Dict[str, str] = {
    # calculations (the only legacy constant actually in use, ×115)
    "Calculation not found": "calculations.not_found",
    "Calculation has no management units": "calculations.no_blocks",
    "Calculation has no boundary geometry": "calculations.no_geometry",
    "Analysis may not be complete": "calculations.incomplete",
    "Calculation already exists": "calculations.already_exists",
    "Calculation is locked and cannot be modified": "calculations.locked",
    # auth
    "Incorrect email or password": "auth.invalid_credentials",
    "Invalid credentials": "auth.invalid_credentials",
    "Authentication token has expired": "auth.invalid_token",
    "Invalid authentication token": "auth.invalid_token",
    "Insufficient scope for this operation": "auth.insufficient_scope",
    "User not found": "auth.user_not_found",
    # permissions
    "Permission denied": "general.not_authorized",
    "Not authorized": "general.not_authorized",
    "You do not own this resource": "general.not_authorized",
    "Access denied for this forest": "general.not_authorized",
    # blocks
    "Forest unit not found": "blocks.forest_division_not_found",
    "Forest division not found": "blocks.forest_division_not_found",
    "Block is locked from further division": "editing.locked_from_division",
    # compartments
    "Compartment not found": "compartments.not_found",
    "Can only delete compartments": "compartments.can_only_delete_compartments",
    "Can only sub-divide existing sub-divisions": "compartments.can_only_subdivide_compartments",
    "Compartments are mutually exclusive with block-level sampling.": "compartments.mutually_exclusive",
    # forests
    "Forest not found": "boundary.forest_not_found",
    "Forest division not found": "blocks.forest_division_not_found",
    "Forest has no boundary defined": "boundary.forest_or_boundary_not_found",
    "Invalid forest boundary geometry": "geometry.invalid",
    # inventory / sampling
    "Invalid inventory data format": "inventory.invalid_format",
    "Invalid block_areas JSON format": "inventory.invalid_block_areas",
    "No field inventory data found": "inventory.no_field_inventory",
    "Species not found in reference database": "inventory.species_not_found",
    "No sampling points could be generated": "sampling.no_points_generated",
    "Invalid sampling design": "sampling.invalid_design",
    "Insufficient forest area for requested sampling intensity": "sampling.insufficient_area",
    # general
    "Bad request": "general.bad_request",
    "Resource not found": "general.not_found",
    "Internal server error": "general.internal_error",
    "Service temporarily unavailable": "general.service_unavailable",
    "Validation error": "general.validation_error",
}


def resolve_detail(detail: Any, **fields: Any) -> Any:
    """Upgrade a response ``detail`` to the bilingual shape when recognized.

    - str  detail matching ``PREFERRED_CODES`` → full `{code,message,message_np}`
    - dict detail carrying a registry ``code`` → bilingual message/message_np
    - anything else → passed through unchanged (raw-string fallback during migration).
    """
    if isinstance(detail, str):
        code = PREFERRED_CODES.get(detail)
        if code:
            entry = get_message(code)
            en = entry["en"].format(**fields) if fields else entry["en"]
            ne = entry["ne"].format(**fields) if fields else entry["ne"]
            return {"code": code, "message": en, "message_np": ne, **fields}
        return detail
    if isinstance(detail, dict) and "code" in detail:
        code = str(detail["code"])
        try:
            entry = get_message(code)
        except KeyError:
            return detail
        d = dict(detail)
        if not d.get("message"):
            d["message"] = entry["en"]
        if not d.get("message_np"):
            d["message_np"] = entry["ne"]
        return d
    return detail