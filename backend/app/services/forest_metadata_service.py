"""Reading and writing a forest's metadata.

WORKSPACE_FLOW_NAV_PLAN D5. The form lives in the browser; the record does not.
Two rules here, and both exist because of a specific failure:

1. **The stored row wins over anything the browser posts.** `get_for_report`
   overlays the saved values on top of the derived ones, so a .docx cover page
   is a function of the database, not of whoever happened to press Generate. The
   old flow had the client POST the whole metadata dict with every generation,
   which meant two people generating a report for the same forest got two
   different cover pages and neither was a record.

2. **Derived values are only defaults.** `forest_name`, `group_name` (= the forest name), `province`, `district`,
   `palika`, `ward`, `division` and `sub_division` can be inferred from the calculation's `result_data`
   (`services/analysis.py:485` writes `whole_province` and friends). Those seed
   the form the first time it is opened, and are the fallback for the report
   afterwards -- but once a person has corrected a ward number, the stored value
   is the one that counts. `result_data` is where analysis put a value, not where
   a person put one.

   The fiscal year is a third kind of default: nobody stores it and the analysis
   cannot see it, but it is not a *guess* either. It is read off the calendar
   (`fiscal_year_defaults`), so the two date fields open on the current Nepali
   fiscal year (and ten years on) instead of blank.

Nothing here writes a partial row on a read. `get` is a pure read; a first-time
visit returns seeded defaults with `persisted: False` so the client can show them
as suggestions rather than as saved values, and the row is only created when
somebody actually saves.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as _date
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..models.calculation import Calculation
from ..models.forest_metadata import ForestMetadata
from ..utils.nepali_date import current_fiscal_year_start, fiscal_year_label

logger = logging.getLogger(__name__)

# How far ahead the default FY End sits: the current fiscal year plus ten.
FY_DEFAULT_SPAN_YEARS = 10

# The fields a person can author, in the order the form shows them. Everything
# else on the model is identity or audit. (Address and serial number were dropped from the form on 2026-10-12;
# their columns remain, so earlier values are kept, and new fields are expected to be added here.)
EDITABLE_FIELDS: tuple[str, ...] = (
    "forest_name",
    "group_name",
    "province",
    "district",
    "palika",
    "ward",
    "division",
    "sub_division",
    "cf_national_code",
    "fy_start",
    "fy_end",
)

# Optional plan details that belong to the forest. Not part of EDITABLE_FIELDS on purpose: the form stays complete
# without them, the workflow step never waits for them, and the cover-page report does not read them.
OPTIONAL_FIELDS: tuple[str, ...] = (
    "sub_division_chief",
    "forest_management_section_chief",
    "division_forest_officer",
    "technical_assistance_org",
    "cf_handover_date",
    "cf_first_renewal_date",
    "cf_history_note",
    "cf_registration_number",
    "constitution_approved_year",
    "user_group_reg_no",
    "cf_sn_number",
    "cf_boundary_east",
    "cf_boundary_south",
    "cf_boundary_west",
    "cf_boundary_north",
    "physiography_zone",
    "protected_area_status",
    "forest_type",
    "forest_abundance",
    "forest_avg_age",
    "main_non_timber_fp",
    "avg_crown_density_pct",
    "ug_province",
    "ug_district",
    "ug_municipality",
    "ug_municipality_type",
    "ug_ward",
    "ug_division",
    "ug_sub_division",
    "ug_settlement",
    "ug_boundary_east",
    "ug_boundary_south",
    "ug_boundary_west",
    "ug_boundary_north",
)
ALL_FIELDS: tuple[str, ...] = EDITABLE_FIELDS + OPTIONAL_FIELDS

# The column width each field is checked against. Kept next to the field list so
# the two cannot drift; the same limits are CHECK constraints in migration 098, and
# this is the early, friendly error rather than an IntegrityError.
FIELD_MAXLEN: Dict[str, int] = {
    "ward": 64,
    "cf_national_code": 32,
    "fy_start": 32,
    "fy_end": 32,
    "cf_handover_date": 32,
    "cf_first_renewal_date": 32,
    "cf_history_note": 4000,
    "cf_registration_number": 64,
    "constitution_approved_year": 32,
    "user_group_reg_no": 32,
    "cf_sn_number": 32,
    "cf_boundary_east": 2000,
    "cf_boundary_south": 2000,
    "cf_boundary_west": 2000,
    "cf_boundary_north": 2000,
    "physiography_zone": 255,
    "protected_area_status": 255,
    "forest_type": 64,
    "forest_abundance": 64,
    "forest_avg_age": 32,
    "main_non_timber_fp": 2000,
    "avg_crown_density_pct": 32,
    "ug_province": 255,
    "ug_district": 255,
    "ug_municipality": 255,
    "ug_municipality_type": 64,
    "ug_ward": 64,
    "ug_division": 255,
    "ug_sub_division": 255,
    "ug_settlement": 255,
    "ug_boundary_east": 2000,
    "ug_boundary_south": 2000,
    "ug_boundary_west": 2000,
    "ug_boundary_north": 2000,
}


class MetadataValidationError(ValueError):
    """A field the caller can correct. Carries the field name and the limit."""

    def __init__(self, code: str, *, field: str = "", max_len: int = 0) -> None:
        super().__init__(code)
        self.code = code
        self.field = field
        self.max_len = max_len


def _clean(value: Any) -> Optional[str]:
    """Normalise a posted value to a string or None.

    Blank means "not recorded", not "the empty string" -- a form that submits an
    empty text input should clear the column rather than store ''. `0` and `False`
    are rejected because no metadata field is numeric, and coercing them would let
    a stray `0` become the string "0" on a cover page.
    """
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return None
    text = str(value).strip()
    return text or None


def derived_defaults(calculation: Calculation) -> Dict[str, Optional[str]]:
    """What the calculation already knows about where this forest is.

    Best effort, never authoritative: these are analysis outputs, and a missing
    `result_data` must not stop someone recording a ward number by hand.
    """
    result_data: Dict[str, Any] = {}
    try:
        result_data = calculation.result_data or {}
    except Exception:  # pragma: no cover - a detached/odd row should not 500
        logger.warning("could not read result_data for %s", calculation.id, exc_info=True)

    def pick(*keys: str) -> Optional[str]:
        for key in keys:
            value = _clean(result_data.get(key))
            if value:
                return value
        return None

    forest_name = _clean(getattr(calculation, "forest_name", None))
    return {
        "forest_name": forest_name,
        # In most cases the user group carries the forest's name (owner, 2026-10-11): a suggestion the user can overwrite.
        "group_name": forest_name,
        "province": pick("whole_province_ne", "whole_province"),
        # The district is the district; it used to be seeded from the division office, which is a different thing.
        "district": pick("whole_district"),
        "palika": pick("whole_municipality", "whole_palika"),
        "ward": pick("whole_ward"),
        # The forest office the analysis located the forest in (Nepali, as the cover page prints it).
        "division": pick("whole_division_n"),
        "sub_division": pick("whole_subdivis_n"),
    }


def fiscal_year_defaults(today: Optional[_date] = None) -> Dict[str, Optional[str]]:
    """The current Nepali fiscal year, and the same year ten on, as text.

    The period a report covers is the plan's own dates, so the form opens on the
    fiscal year in progress rather than blank: for a day in 2083 Shrawan or later
    that is `2083/84`, and the end is `2093/94`. It is a suggestion the officer can
    overwrite -- a stored record always wins -- and the analysis has no opinion on
    it, so it is read off the calendar instead of `result_data`.

    `today` is a Gregorian date, threaded through so a test can pin the year.
    """
    start = current_fiscal_year_start(today)
    return {
        "fy_start": fiscal_year_label(start),
        "fy_end": fiscal_year_label(start + FY_DEFAULT_SPAN_YEARS),
    }


def _row_to_dict(row: ForestMetadata) -> Dict[str, Any]:
    return {field: getattr(row, field) for field in ALL_FIELDS}


def get_row(db: Session, calculation_id: uuid.UUID) -> Optional[ForestMetadata]:
    return (
        db.query(ForestMetadata)
        .filter(ForestMetadata.calculation_id == calculation_id)
        .one_or_none()
    )


def _plan_typed_values(db: Session, calculation_id: uuid.UUID) -> Dict[str, Any]:
    """What the forest's latest operational plan typed for the optional facts (a suggestion for a forest not saved yet)."""
    from ..models.operational_plan import OperationalPlan

    try:
        plan = (
            db.query(OperationalPlan)
            .filter(OperationalPlan.calculation_id == calculation_id)
            .order_by(OperationalPlan.updated_at.desc())
            .first()
        )
    except Exception:  # noqa: BLE001 -- a suggestion only: no plan data just means the form opens blank
        logger.warning("could not read the plan's typed values for %s", calculation_id, exc_info=True)
        return {}
    inputs = ((plan.plan_metadata or {}).get("user_inputs") or {}) if plan is not None else {}
    return {f: _clean(inputs.get(f)) or (str(inputs[f]) if isinstance(inputs.get(f), (int, float)) and not isinstance(inputs.get(f), bool) else None)
            for f in OPTIONAL_FIELDS if f in inputs}


def get_metadata(db: Session, calculation_id: uuid.UUID) -> Dict[str, Any]:
    """The saved row, or seeded defaults marked as not yet saved.

    A read never writes. Returning the derived values with `persisted: False` lets
    the form open pre-filled and still tell the truth about what is stored, which
    is the difference between "District: 2081/82" and "District: (suggested)".
    """
    calculation = (
        db.query(Calculation).filter(Calculation.id == calculation_id).one_or_none()
    )
    if calculation is None:
        raise MetadataValidationError("forest_metadata.calc_not_found")

    row = get_row(db, calculation_id)
    if row is not None:
        return {
            **_row_to_dict(row),
            "persisted": True,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    # The analysis knows where the forest is; the calendar knows the fiscal year.
    # Both are suggestions, so they merge into one seeded form.
    defaults = {**derived_defaults(calculation), **fiscal_year_defaults()}
    seeded = _plan_typed_values(db, calculation_id)
    return {
        **{field: defaults.get(field) for field in EDITABLE_FIELDS},
        **{field: seeded.get(field) for field in OPTIONAL_FIELDS},
        "persisted": False,
        "updated_at": None,
    }


def upsert_metadata(
    db: Session,
    calculation_id: uuid.UUID,
    payload: Dict[str, Any],
    *,
    updated_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Create or update the row. Full replace, because the form is the whole form.

    A partial PATCH would be wrong here: the form always submits every field, and
    treating an omitted field as "unchanged" makes it impossible to *clear* a
    value. Absent or blank means cleared.
    """
    calculation = (
        db.query(Calculation).filter(Calculation.id == calculation_id).one_or_none()
    )
    if calculation is None:
        raise MetadataValidationError("forest_metadata.calc_not_found")

    if not isinstance(payload, dict) or not any(
        _clean(payload.get(field)) is not None for field in ALL_FIELDS
    ):
        raise MetadataValidationError("forest_metadata.empty_update")

    values: Dict[str, Optional[str]] = {}
    for field in ALL_FIELDS:
        value = _clean(payload.get(field))
        limit = FIELD_MAXLEN.get(field, 255)
        if value is not None and limit and len(value) > limit:
            raise MetadataValidationError(
                "forest_metadata.field_too_long", field=field, max_len=limit
            )
        values[field] = value

    fy_start, fy_end = values["fy_start"], values["fy_end"]
    if fy_start and fy_end and _fy_sort_key(fy_start) > _fy_sort_key(fy_end):
        raise MetadataValidationError("forest_metadata.fy_order")

    row = get_row(db, calculation_id)
    if row is None:
        row = ForestMetadata(calculation_id=calculation_id, **values)
        db.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    if updated_by is not None:
        row.updated_by = updated_by

    db.commit()
    db.refresh(row)
    logger.info("forest metadata saved for calculation %s", calculation_id)
    return {
        **_row_to_dict(row),
        "persisted": True,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _fy_sort_key(value: str):
    """Order two fiscal-year strings that may be Latin or Devanagari digits.

    "2081/82" and "२०८१/८२" are the same year written two ways, so the comparison
    has to read the digits rather than compare characters -- otherwise a Nepali
    numeral sorts after every Latin one and the check is meaningless. Non-digits
    are ignored, so "FY 2081" and "2081/82" still order correctly.
    """
    digits = []
    for ch in value:
        if "0" <= ch <= "9":
            digits.append(ch)
        elif "०" <= ch <= "९":  # ०-९
            digits.append(str(ord(ch) - ord("०")))
    return int("".join(digits)) if digits else 0


def get_for_report(
    db: Session,
    calculation_id: uuid.UUID,
    posted: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The metadata dict `build_report_document` expects.

    Precedence, highest first:

      1. **saved** -- what a person recorded. A record beats a form submission.
      2. **derived** -- what the calculation already knows (`result_data`, and
         `calculation.forest_name`). Not a person's statement, but it came out of
         the database rather than the browser, so it outranks one.
      3. **posted** -- whatever the browser sent with the generate request.

    Levels 1 and 2 exist to stop two people generating a report for one forest
    from getting two different cover pages, and to stop an old or tampered client
    restating a forest's official details on a statutory document. Level 3 keeps a
    client that never adopted the Forest Metadata tab working during the rollout --
    in practice it fills the fields nothing else knows, like `cf_national_code`,
    which has no derived source at all.

    The fiscal year is the one exception to "derived over posted". Its fallback is
    read off today's date (`fiscal_year_defaults`), which is a *guess at what the
    form would open with*, not a fact about the forest -- so an explicit posted
    value outranks it rather than the other way round. That keeps a legacy caller
    that still sends its own period in charge of the period it asked for.
    """
    calculation = (
        db.query(Calculation).filter(Calculation.id == calculation_id).one_or_none()
    )
    if calculation is None:
        raise MetadataValidationError("forest_metadata.calc_not_found")

    posted = posted or {}
    row = get_row(db, calculation_id)
    if row is not None:
        saved = _row_to_dict(row)
        return {
            field: _clean(saved.get(field)) or _clean(posted.get(field))
            for field in EDITABLE_FIELDS
        }

    derived = derived_defaults(calculation)
    fiscal = fiscal_year_defaults()
    return {
        field: (
            derived.get(field)
            or _clean(posted.get(field))
            or fiscal.get(field)
        )
        for field in EDITABLE_FIELDS
    }
