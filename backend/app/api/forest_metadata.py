"""Forest metadata: the record, and the two endpoints that read and write it.

WORKSPACE_FLOW_NAV_PLAN D5 -- "Forest Metadata is collected in the field during
field inventory, so it is a third tab on the Field Inventory page, not a separate
step."

The service holds the logic; this is the transport. Two decisions worth stating:

**404 rather than 403 for someone else's calculation.** That is this codebase's
convention (`api/forest_committee.py` filters on `user_id` and 404s), and it is
the better one: a 403 confirms the id exists, which turns the endpoint into a
way to enumerate other users' forests.

**Reads are open to super admins, writes are not.** A super admin legitimately
needs to *see* a forest's cover page to check a submission, but recording it is
the field officer's job -- so an admin reading a value does not quietly become an
admin who wrote one, and `updated_by` stays meaningful.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.exceptions import i18n_error, i18n_success
from ..core.idempotent_route import IdempotentRoute
from ..models.calculation import Calculation
from ..models.user import User, UserRole
from ..services import forest_metadata_service as svc
from ..utils.auth import get_current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Forest Metadata"],
    route_class=IdempotentRoute,
)
# No `prefix` here on purpose. `main._build_api_router` already prepends the base
# (`/api` and `/api/v1`), and the mount supplies `/calculations` -- the same
# arrangement as `api/fieldbook.py`. Declaring `prefix="/api/calculations"` as
# well would produce `/api/api/calculations/...` on both mounts, which 404s while
# looking like a correct registration in the source.


class ForestMetadataPayload(BaseModel):
    """The whole form. Absent or blank means cleared, not unchanged.

    That is the opposite of a PATCH, and deliberately so: the form always submits
    every field, so treating an omission as "leave it alone" would make it
    impossible to remove a value somebody typed by mistake.
    """

    forest_name: Optional[str] = Field(default=None, max_length=255)
    group_name: Optional[str] = Field(default=None, max_length=255)
    province: Optional[str] = Field(default=None, max_length=255)
    district: Optional[str] = Field(default=None, max_length=255)
    palika: Optional[str] = Field(default=None, max_length=255)
    ward: Optional[str] = Field(default=None, max_length=64)
    division: Optional[str] = Field(default=None, max_length=255)
    sub_division: Optional[str] = Field(default=None, max_length=255)
    cf_national_code: Optional[str] = Field(default=None, max_length=32)
    fy_start: Optional[str] = Field(default=None, max_length=32)
    fy_end: Optional[str] = Field(default=None, max_length=32)
    # optional plan details (see the service's OPTIONAL_FIELDS)
    sub_division_chief: Optional[str] = Field(default=None, max_length=255)
    forest_management_section_chief: Optional[str] = Field(default=None, max_length=255)
    division_forest_officer: Optional[str] = Field(default=None, max_length=255)
    technical_assistance_org: Optional[str] = Field(default=None, max_length=255)
    cf_handover_date: Optional[str] = Field(default=None, max_length=32)
    cf_first_renewal_date: Optional[str] = Field(default=None, max_length=32)
    cf_history_note: Optional[str] = Field(default=None, max_length=4000)
    cf_registration_number: Optional[str] = Field(default=None, max_length=64)
    constitution_approved_year: Optional[str] = Field(default=None, max_length=32)
    user_group_reg_no: Optional[str] = Field(default=None, max_length=32)
    cf_sn_number: Optional[str] = Field(default=None, max_length=32)
    cf_boundary_east: Optional[str] = Field(default=None, max_length=2000)
    cf_boundary_south: Optional[str] = Field(default=None, max_length=2000)
    cf_boundary_west: Optional[str] = Field(default=None, max_length=2000)
    cf_boundary_north: Optional[str] = Field(default=None, max_length=2000)
    physiography_zone: Optional[str] = Field(default=None, max_length=255)
    protected_area_status: Optional[str] = Field(default=None, max_length=255)
    forest_type: Optional[str] = Field(default=None, max_length=64)
    forest_abundance: Optional[str] = Field(default=None, max_length=64)
    forest_avg_age: Optional[str] = Field(default=None, max_length=32)
    main_non_timber_fp: Optional[str] = Field(default=None, max_length=2000)
    avg_crown_density_pct: Optional[str] = Field(default=None, max_length=32)
    ug_province: Optional[str] = Field(default=None, max_length=255)
    ug_district: Optional[str] = Field(default=None, max_length=255)
    ug_municipality: Optional[str] = Field(default=None, max_length=255)
    ug_municipality_type: Optional[str] = Field(default=None, max_length=64)
    ug_ward: Optional[str] = Field(default=None, max_length=64)
    ug_division: Optional[str] = Field(default=None, max_length=255)
    ug_sub_division: Optional[str] = Field(default=None, max_length=255)
    ug_settlement: Optional[str] = Field(default=None, max_length=255)
    ug_boundary_east: Optional[str] = Field(default=None, max_length=2000)
    ug_boundary_south: Optional[str] = Field(default=None, max_length=2000)
    ug_boundary_west: Optional[str] = Field(default=None, max_length=2000)
    ug_boundary_north: Optional[str] = Field(default=None, max_length=2000)


def _resolve_calculation_id(calculation_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(calculation_id))
    except (ValueError, AttributeError, TypeError):
        # A malformed id is a 404, not a 500: the client sent something that
        # cannot name a row, and the honest answer is "no such calculation".
        raise i18n_error(404, "forest_metadata.calc_not_found")


def _own_calculation(db: Session, calculation_id: uuid.UUID, user: User) -> Calculation:
    calculation = (
        db.query(Calculation).filter(Calculation.id == calculation_id).one_or_none()
    )
    if calculation is None or calculation.user_id != user.id:
        raise i18n_error(404, "forest_metadata.calc_not_found")
    return calculation


# Status per code, rather than one status for the whole exception type.
#
# This exists because of a bug the live checks caught: a super admin reading a
# forest that does not exist is let past the ownership gate (admins may read
# anything), reaches the service, and the service's "no such calculation" was
# mapped to 400 -- so the same missing row was a 404 on PUT and a 400 on GET.
# A missing resource is 404 on every path.
_STATUS_FOR_CODE: Dict[str, int] = {
    "forest_metadata.calc_not_found": 404,
    "forest_metadata.field_too_long": 422,
    "forest_metadata.empty_update": 400,
    "forest_metadata.fy_order": 400,
}


def _handle(exc: svc.MetadataValidationError):
    status = _STATUS_FOR_CODE.get(exc.code, 400)
    if exc.code == "forest_metadata.field_too_long":
        return i18n_error(status, exc.code, field=exc.field, max_len=exc.max_len)
    return i18n_error(status, exc.code)


@router.get("/forest-metadata/national-code-reference")
def national_code_reference(current_user: User = Depends(get_current_active_user)) -> Dict[str, Any]:
    """Schedule 11 of the Community Forestry Guidelines 2081 as a picker: provinces -> division forest offices -> local levels, each
    with the code or number that goes into the national database code (``PPP/DDD/SS/LL/NNN``)."""
    from ..services import cf_national_code as nc

    return {"source": "Community Forestry Guidelines 2081, Schedule 11", "provinces": nc.reference()}


@router.get("/forest-metadata/national-code-check")
def national_code_check(code: str = "", current_user: User = Depends(get_current_active_user)) -> Dict[str, Any]:
    """Compare a typed code with the schedule. Advisory: the answer lists what does not match and never blocks saving."""
    from ..services import cf_national_code as nc

    return nc.check(code)


@router.get("/{calculation_id}/forest-metadata/national-code-match")
def national_code_match(
    calculation_id: str,
    province: str = "",
    palika: str = "",
    district: str = "",
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Preselect the Schedule 11 code's province / division / local level from the Province and Municipality the form holds.

    The calculation's own analysis also records the real (English) district, which tells apart two municipalities that share a name;
    the form's own District field is not used for that because it is seeded from the division office. Advisory: the client shows the
    result as a starting point to confirm."""
    from ..services import cf_national_code as nc

    cid = _resolve_calculation_id(calculation_id)
    calculation = db.query(Calculation).filter(Calculation.id == cid).one_or_none()
    is_owner = calculation is not None and calculation.user_id == current_user.id
    is_admin = current_user.role == UserRole.SUPER_ADMIN.value
    if not (is_owner or is_admin):
        raise i18n_error(404, "forest_metadata.calc_not_found")
    rd = calculation.result_data or {}
    hints = [h for h in (district, rd.get("whole_district")) if h]
    return nc.match_location(province, palika, hints)


@router.get("/{calculation_id}/forest-metadata")
def read_forest_metadata(
    calculation_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """The saved record, or the calculation's own values as suggestions.

    Never 404s for a forest that exists but has no metadata row -- an unsaved
    form is a normal state, not a missing resource. `persisted` distinguishes
    the two so the client can label a suggestion as one.
    """
    cid = _resolve_calculation_id(calculation_id)
    calculation = (
        db.query(Calculation).filter(Calculation.id == cid).one_or_none()
    )
    is_owner = calculation is not None and calculation.user_id == current_user.id
    is_admin = current_user.role == UserRole.SUPER_ADMIN.value
    if not (is_owner or is_admin):
        raise i18n_error(404, "forest_metadata.calc_not_found")

    try:
        return svc.get_metadata(db, cid)
    except svc.MetadataValidationError as exc:
        raise _handle(exc)


@router.put("/{calculation_id}/forest-metadata")
def write_forest_metadata(
    calculation_id: str,
    payload: ForestMetadataPayload,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Create or replace the record. Idempotent: the same body twice is one row."""
    cid = _resolve_calculation_id(calculation_id)
    _own_calculation(db, cid, current_user)

    data: Dict[str, Any] = payload.model_dump()
    try:
        saved = svc.upsert_metadata(db, cid, data, updated_by=current_user.id)
    except svc.MetadataValidationError as exc:
        db.rollback()
        raise _handle(exc)
    except Exception:
        db.rollback()
        logger.exception("forest metadata write failed for %s", cid)
        raise i18n_error(500, "general.unexpected_error")

    # `i18n_success` builds only `{message, message_np}` and discards any extra
    # kwargs as format fields, so the saved row is merged in beside it rather than
    # passed to it -- otherwise the client would get a success message and no data.
    return {**i18n_success("forest_metadata.saved"), "data": saved}


@router.post("/{calculation_id}/forest-metadata/import")
def import_forest_metadata(
    calculation_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Fill the forest's details from the ``07_Forest_Metadata`` template (Excel / CSV, one row).

    Sync on purpose (it reads a file). A detail the file leaves empty keeps its saved value: an import never clears one. A file that cannot be used is
    refused with findings naming what is wrong.
    """
    from .inventory import read_upload_file
    from ..services.upload.findings import upload_error
    from ..services.upload.metadata_import import read_metadata

    cid = _resolve_calculation_id(calculation_id)
    _own_calculation(db, cid, current_user)
    values, errors, infos = read_metadata(read_upload_file(file.file.read(), file.filename or "metadata.csv"), file=file.filename)
    if errors:
        raise upload_error(422, *errors)
    current = svc.get_metadata(db, cid)
    merged = {f: values.get(f) or (current.get(f) if current.get("persisted") else None) for f in svc.ALL_FIELDS}
    try:
        saved = svc.upsert_metadata(db, cid, merged, updated_by=current_user.id)
    except svc.MetadataValidationError as exc:
        db.rollback()
        raise _handle(exc)
    return {"data": saved, "findings": [f.to_dict() for f in infos]}
