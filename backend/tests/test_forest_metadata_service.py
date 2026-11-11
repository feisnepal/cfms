"""Forest metadata: the record, and the precedence the .docx cover page obeys.

WORKSPACE_FLOW_NAV_PLAN D5. The behaviour worth protecting is not the CRUD -- it is
which of three sources of the same field wins when they disagree:

    saved (a person recorded it) > derived (the calculation knows it) > posted
    (the browser claimed it)

That order is the whole point of moving metadata out of `ReportTab`'s component
state. Before, the cover page was whatever one person had typed at the moment
they pressed Generate, so two people exporting the same forest got two different
documents and neither was a record. The tamper case is the same rule seen from
the other side: a client must not be able to restate a forest's official details
on a document that gets printed and filed.

Also covered: the 1:1 (a second save updates, never duplicates), whitespace being
blank rather than a value, and the fiscal-year check reading Devanagari digits --
"२०८१/८२" and "2081/82" are the same year, and a plain string comparison would
order every Nepali numeral after every Latin one and make the check meaningless.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.calculation import Calculation
from app.models.forest_metadata import ForestMetadata
from app.models.user import User
from app.services import forest_metadata_service as svc


@pytest.fixture
def owner(db):
    user = User(
        email=f"fm-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="h",
        full_name="FM Owner",
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def calc(db, owner):
    calculation = Calculation(user_id=owner.id, forest_name="recorded in the system")
    db.add(calculation)
    db.flush()
    return calculation


ALL_FIELDS = {f: f"v-{f}" for f in svc.EDITABLE_FIELDS}


# --------------------------------------------------------------- reading ----
def test_get_metadata_does_not_create_a_row(db, calc):
    """A read is a read. Writing on a GET would mean a poll invents a record."""
    body = svc.get_metadata(db, calc.id)
    assert body["persisted"] is False
    assert svc.get_row(db, calc.id) is None


def test_get_metadata_seeds_from_the_calculation(db, calc):
    body = svc.get_metadata(db, calc.id)
    assert body["forest_name"] == "recorded in the system"
    assert body["persisted"] is False


def test_get_metadata_prefers_ne_value_for_a_location(db, calc):
    # `result_data` carries both scripts; the Nepali one is what a Nepali-first
    # cover page should print. The shapes below are what `services/analysis.py`
    # actually writes -- notably `whole_ward` is a string, so seeding works.
    calc.result_data = {
        "whole_province": "Bagmati", "whole_province_ne": "बाग्मती",
        "whole_district": "Makawanpur", "whole_division_n": "मकवानपुर",
        "whole_municipality": "Makawanpurgadhi", "whole_ward": "4", "whole_subdivis_n": "मकवानपुरगढी",
    }
    db.flush()
    body = svc.get_metadata(db, calc.id)
    assert body["province"] == "बाग्मती"
    assert body["district"] == "Makawanpur"  # the district itself, no longer the division office
    assert body["division"] == "मकवानपुर" and body["sub_division"] == "मकवानपुरगढी"  # located by the analysis
    assert body["group_name"] == calc.forest_name  # the user group usually carries the forest's name
    assert body["palika"] == "Makawanpurgadhi"
    assert body["ward"] == "4"


def test_get_metadata_on_a_missing_calculation_is_reported(db):
    with pytest.raises(svc.MetadataValidationError) as exc:
        svc.get_metadata(db, uuid.uuid4())
    assert exc.value.code == "forest_metadata.calc_not_found"


def test_get_metadata_seeds_the_current_fiscal_year(db, calc):
    """The two date fields open on the current Nepali fiscal year, and ten on.

    Nobody stores this and the analysis cannot see it, so it is read off the
    calendar. The exact year is left to `current_fiscal_year_start`; what this
    pins is that the form is seeded from it and that the span is ten years.
    """
    from app.utils.nepali_date import current_fiscal_year_start, fiscal_year_label

    body = svc.get_metadata(db, calc.id)
    start = current_fiscal_year_start()
    assert body["fy_start"] == fiscal_year_label(start)
    assert body["fy_end"] == fiscal_year_label(start + svc.FY_DEFAULT_SPAN_YEARS)


def test_a_seeded_fiscal_year_is_still_only_a_suggestion(db, calc):
    body = svc.get_metadata(db, calc.id)
    assert body["persisted"] is False
    assert svc.get_row(db, calc.id) is None, "seeding a read must not create a record"


# --------------------------------------------------------------- writing ----
def test_upsert_creates_then_updates_one_row(db, calc, owner):
    svc.upsert_metadata(db, calc.id, {**ALL_FIELDS, "ward": "1"}, updated_by=owner.id)
    svc.upsert_metadata(db, calc.id, {**ALL_FIELDS, "ward": "2"}, updated_by=owner.id)

    rows = db.query(ForestMetadata).filter(ForestMetadata.calculation_id == calc.id).all()
    assert len(rows) == 1, "the UNIQUE constraint is the backstop; this is the intent"
    assert rows[0].ward == "2"
    assert rows[0].updated_by == owner.id


def test_upsert_treats_a_blank_value_as_cleared(db, calc):
    """Not "unchanged". Otherwise a mistyped value could never be removed."""
    svc.upsert_metadata(db, calc.id, {**ALL_FIELDS, "ward": "9"})
    svc.upsert_metadata(db, calc.id, {**ALL_FIELDS, "ward": "  "})
    assert svc.get_row(db, calc.id).ward is None


def test_upsert_rejects_a_whitespace_only_submission(db, calc):
    with pytest.raises(svc.MetadataValidationError) as exc:
        svc.upsert_metadata(db, calc.id, {"forest_name": "   ", "ward": "\t"})
    assert exc.value.code == "forest_metadata.empty_update"


def test_upsert_rejects_an_empty_submission(db, calc):
    with pytest.raises(svc.MetadataValidationError) as exc:
        svc.upsert_metadata(db, calc.id, {})
    assert exc.value.code == "forest_metadata.empty_update"


def test_upsert_ignores_a_stray_number(db, calc):
    """No metadata field is numeric, so a `0` must not become the string "0"."""
    svc.upsert_metadata(db, calc.id, {**ALL_FIELDS, "ward": 0})
    assert svc.get_row(db, calc.id).ward is None


def test_upsert_rejects_an_over_long_value(db, calc):
    with pytest.raises(svc.MetadataValidationError) as exc:
        svc.upsert_metadata(db, calc.id, {**ALL_FIELDS, "cf_national_code": "x" * 33})
    assert exc.value.code == "forest_metadata.field_too_long"
    assert exc.value.field == "cf_national_code"
    assert exc.value.max_len == 32


def test_address_and_serial_number_are_no_longer_part_of_the_form(db, calc):
    """Dropped from the form on 2026-10-12: not editable, not returned, and not needed for the form to count as complete."""
    assert "address" not in svc.EDITABLE_FIELDS and "serial_number" not in svc.EDITABLE_FIELDS
    svc.upsert_metadata(db, calc.id, {"forest_name": "F", "address": "ignored", "serial_number": "9"})
    row = svc.get_row(db, calc.id)
    assert row.address is None and row.serial_number is None
    assert "address" not in svc.get_metadata(db, calc.id) and "serial_number" not in svc.get_metadata(db, calc.id)

def test_upsert_rejects_a_backwards_fiscal_year(db, calc):
    with pytest.raises(svc.MetadataValidationError) as exc:
        svc.upsert_metadata(db, calc.id, {**ALL_FIELDS, "fy_start": "2085/86", "fy_end": "2080/81"})
    assert exc.value.code == "forest_metadata.fy_order"


def test_upsert_accepts_a_fiscal_year_written_in_devanagari(db, calc):
    """The cover page prints these verbatim, and both spellings are legitimate."""
    svc.upsert_metadata(db, calc.id, {"forest_name": "F", "fy_start": "२०८१/८२", "fy_end": "२०८२/८३"})
    assert svc.get_row(db, calc.id).fy_start == "२०८१/८२"


def test_upsert_rejects_a_backwards_fiscal_year_in_devanagari(db, calc):
    """The check that a plain string comparison would get wrong."""
    with pytest.raises(svc.MetadataValidationError) as exc:
        svc.upsert_metadata(db, calc.id, {"forest_name": "F", "fy_start": "२०८५/८६", "fy_end": "२०८०/८१"})
    assert exc.value.code == "forest_metadata.fy_order"


# ------------------------------------------------- the cover-page precedence ----
def test_a_saved_value_beats_a_posted_one(db, calc, owner):
    svc.upsert_metadata(db, calc.id, {**ALL_FIELDS, "forest_name": "SAVED"}, updated_by=owner.id)
    merged = svc.get_for_report(db, calc.id, {f: "TAMPERED" for f in svc.EDITABLE_FIELDS})
    assert merged["forest_name"] == "SAVED"
    assert "TAMPERED" not in merged.values()


def test_a_derived_value_beats_a_posted_one_when_nothing_is_saved(db, calc):
    """`calculation.forest_name` came from the database, so it outranks a browser."""
    merged = svc.get_for_report(db, calc.id, {"forest_name": "FROM THE BROWSER"})
    assert merged["forest_name"] == "recorded in the system"


def test_a_posted_value_fills_what_nothing_else_knows(db, calc):
    """The rollout path: a client that never adopted the tab still works."""
    merged = svc.get_for_report(db, calc.id, {"cf_national_code": "LEGACY-CF", "fy_start": "2079/80"})
    assert merged["cf_national_code"] == "LEGACY-CF"
    assert merged["fy_start"] == "2079/80"


def test_report_metadata_carries_every_field_the_builder_reads(db, calc):
    """`build_cover_page` does `metadata.get(...)` on named keys; a missing key
    silently prints a placeholder, so the shape is part of the contract."""
    merged = svc.get_for_report(db, calc.id, {})
    assert set(svc.EDITABLE_FIELDS) <= set(merged)


def test_report_metadata_survives_a_missing_row(db, calc):
    """A forest with no metadata must still produce a usable cover page."""
    merged = svc.get_for_report(db, calc.id, None)
    assert merged["forest_name"] == "recorded in the system"


def test_report_metadata_falls_back_to_the_calendar_for_the_fiscal_year(db, calc):
    """With nothing saved and nothing posted, the period still names a real year."""
    from app.utils.nepali_date import current_fiscal_year_start, fiscal_year_label

    merged = svc.get_for_report(db, calc.id, {})
    start = current_fiscal_year_start()
    assert merged["fy_start"] == fiscal_year_label(start)
    assert merged["fy_end"] == fiscal_year_label(start + svc.FY_DEFAULT_SPAN_YEARS)


def test_a_posted_fiscal_year_beats_the_calendar_default(db, calc):
    """The default is a guess at what the form would open with, not a fact about
    the forest, so a caller that still sends its own period keeps it."""
    merged = svc.get_for_report(db, calc.id, {"fy_start": "2079/80", "fy_end": "2084/85"})
    assert merged["fy_start"] == "2079/80"
    assert merged["fy_end"] == "2084/85"
