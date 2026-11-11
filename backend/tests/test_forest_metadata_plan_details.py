"""The optional plan details kept on the forest (officers, handover / renewal dates, history, service provider).

They live beside the mandatory form but outside EDITABLE_FIELDS, so adding them never turns the Forest Metadata step red,
and an operational plan reads them only when its own form field is empty."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.models.calculation import Calculation
from app.models.user import User
from app.services import forest_metadata_service as svc
from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY
from app.services.operational_plan.variable_resolver import VariableResolver

MANDATORY = {f: f"v-{f}" for f in svc.EDITABLE_FIELDS}
DETAILS = {
    "sub_division_chief": "सिद्धान्त बराल",
    "forest_management_section_chief": "रमेश खनाल", "division_forest_officer": "प्रविण बिँडारी",
    "technical_assistance_org": "पञ्चासे बहुसेवा", "cf_handover_date": "२०६९/१२/२९",
    "cf_first_renewal_date": "२०७८/०३/३०", "cf_history_note": "संरक्षण समिति बनेर वन जोगाइयो।",
}


@pytest.fixture
def calc(db):
    user = User(email=f"pd-{uuid.uuid4().hex[:10]}@example.com", hashed_password="h", full_name="PD")
    db.add(user)
    db.flush()
    c = Calculation(user_id=user.id, forest_name="सामुदायिक")
    db.add(c)
    db.flush()
    return c


def test_optional_fields_are_outside_the_mandatory_list():
    assert set(DETAILS) <= set(svc.OPTIONAL_FIELDS)
    assert not set(svc.OPTIONAL_FIELDS) & set(svc.EDITABLE_FIELDS)          # the step does not wait for them


def test_optional_details_round_trip_and_clear(db, calc):
    saved = svc.upsert_metadata(db, calc.id, {**MANDATORY, **DETAILS})
    assert all(saved[k] == v for k, v in DETAILS.items())
    cleared = svc.upsert_metadata(db, calc.id, {**MANDATORY, **{k: "" for k in DETAILS}})
    assert all(cleared[k] is None for k in DETAILS)                         # full replace: blank clears


def test_an_unsaved_forest_offers_no_details(db, calc):
    body = svc.get_metadata(db, calc.id)
    assert all(body[k] is None for k in svc.OPTIONAL_FIELDS)


def test_a_too_long_history_note_is_refused(db, calc):
    with pytest.raises(svc.MetadataValidationError):
        svc.upsert_metadata(db, calc.id, {**MANDATORY, "cf_history_note": "x" * 4001})


def test_report_cover_does_not_read_the_details(db, calc):
    svc.upsert_metadata(db, calc.id, {**MANDATORY, **DETAILS})
    assert set(svc.get_for_report(db, calc.id)) == set(svc.EDITABLE_FIELDS)


def test_plan_reads_the_forest_details_and_cannot_override_them(db, calc):
    svc.upsert_metadata(db, calc.id, {**MANDATORY, **DETAILS})
    key = "division_forest_officer"
    empty_plan = VariableResolver(db, str(calc.id), SimpleNamespace(plan_metadata={}))
    assert empty_plan._resolve_user_input(VARIABLE_REGISTRY[key]) == "प्रविण बिँडारी"
    typed = VariableResolver(db, str(calc.id), SimpleNamespace(plan_metadata={"user_inputs": {key: "अर्को"}}))
    assert typed._resolve_user_input(VARIABLE_REGISTRY[key]) == "प्रविण बिँडारी"      # one place, no per-plan override
