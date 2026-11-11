"""Facts that belong to the FOREST, entered once on the Forest Metadata tab and shared by every plan.

Owner decision 2026-10-14: a plan does not carry its own copy of these - no override. The plan's Metadata form shows them
read-only, the document reads them from here, and anything a plan once typed for them is only a last resort when the
forest has no value (so plans made before this rule keep rendering).

``SHARED_FIELDS`` maps the plan-form key to the ``forest_metadata`` column it now comes from.
"""

import logging
import re
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SHARED_FIELDS: Dict[str, str] = {
    "province": "province",
    "forest_district": "district",
    "forest_municipality": "palika",
    "forest_ward": "ward",
    "division": "division",
    "sub_division": "sub_division",
    "op_start_fy": "fy_start",
    "op_end_fy": "fy_end",
    "cf_code": "cf_national_code",
    "sub_division_chief": "sub_division_chief",
    "forest_management_section_chief": "forest_management_section_chief",
    "division_forest_officer": "division_forest_officer",
    "technical_assistance_org": "technical_assistance_org",
    "cf_handover_date": "cf_handover_date",
    "cf_first_renewal_date": "cf_first_renewal_date",
    "cf_history_note": "cf_history_note",
    "cf_registration_number": "cf_registration_number",
    "constitution_approved_year": "constitution_approved_year",
    "user_group_reg_no": "user_group_reg_no",
    "cf_sn_number": "cf_sn_number",
    "cf_boundary_east": "cf_boundary_east",
    "cf_boundary_south": "cf_boundary_south",
    "cf_boundary_west": "cf_boundary_west",
    "cf_boundary_north": "cf_boundary_north",
    "physiography_zone": "physiography_zone",
    "protected_area_status": "protected_area_status",
    "forest_type": "forest_type",
    "forest_abundance": "forest_abundance",
    "forest_avg_age": "forest_avg_age",
    "main_non_timber_fp": "main_non_timber_fp",
    "avg_crown_density_pct": "avg_crown_density_pct",
    "ug_province": "ug_province",
    "ug_district": "ug_district",
    "ug_municipality": "ug_municipality",
    "ug_municipality_type": "ug_municipality_type",
    "ug_ward": "ug_ward",
    "ug_division": "ug_division",
    "ug_sub_division": "ug_sub_division",
    "ug_settlement": "ug_settlement",
    "ug_boundary_east": "ug_boundary_east",
    "ug_boundary_south": "ug_boundary_south",
    "ug_boundary_west": "ug_boundary_west",
    "ug_boundary_north": "ug_boundary_north",
}

_FY_KEYS = ("op_start_fy", "op_end_fy")
_DEV = str.maketrans("०१२३४५६७८९", "0123456789")
_NE = str.maketrans("0123456789", "०१२३४५६७८९")


def fy_text(value: Any) -> Optional[str]:
    """'2083/84', '2083/084' or '२०८३/०८४' -> '२०८३/०८४' (the format the plan documents print)."""
    if not value:
        return None
    m = re.match(r"\s*(\d{4})\s*[/.-]\s*(\d{2,4})\s*$", str(value).translate(_DEV))
    if not m:
        return None
    return f"{m.group(1)}/0{m.group(2)[-2:]}".translate(_NE)


def shared_values(db: Session, calculation_id: Any) -> Dict[str, str]:
    """The non-empty shared values of this forest, keyed by the plan-form key. Empty when nothing is recorded."""
    from app.models.forest_metadata import ForestMetadata

    try:
        row = db.query(ForestMetadata).filter(ForestMetadata.calculation_id == calculation_id).first()
    except Exception:  # noqa: BLE001 -- a failed lookup must not stop the form or the document; the fields stay as the plan has them
        logger.exception("shared forest fields could not be read for %s", calculation_id)
        return {}
    if row is None:
        return {}
    out: Dict[str, str] = {}
    for plan_key, column in SHARED_FIELDS.items():
        value = (getattr(row, column, None) or "").strip()
        if plan_key in _FY_KEYS:
            value = fy_text(value) or ""
        if value:
            out[plan_key] = _as_number(plan_key, value)
    return out


def _as_number(plan_key: str, value: str) -> Any:
    """Stored as text; a variable the registry types as a number (age, crown density, reg. numbers) is handed back as one."""
    from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY

    vd = VARIABLE_REGISTRY.get(plan_key)
    if vd is None or vd.var_type != "number":
        return value
    try:
        num = float(value.translate(_DEV))
    except ValueError:
        return value
    return int(num) if num == int(num) else num


def without_shared(user_inputs: Dict[str, Any]) -> Dict[str, Any]:
    """A plan's own inputs minus the shared keys (what the plan form may store)."""
    return {k: v for k, v in (user_inputs or {}).items() if k not in SHARED_FIELDS}
