"""One place for the forest's facts: no per-plan override (owner, 2026-10-14)."""
import uuid
from types import SimpleNamespace

import pytest

from app.models.calculation import Calculation
from app.models.user import User
from app.services import forest_metadata_service as svc
from app.services.operational_plan.forest_shared_fields import SHARED_FIELDS, fy_text, shared_values, without_shared
from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY
from app.services.operational_plan.variable_resolver import VariableResolver

MANDATORY = {f: f"v-{f}" for f in svc.EDITABLE_FIELDS}


@pytest.fixture
def calc(db):
    u = User(email=f"sh-{uuid.uuid4().hex[:10]}@example.com", hashed_password="h", full_name="S")
    db.add(u)
    db.flush()
    c = Calculation(user_id=u.id, forest_name="वन")
    db.add(c)
    db.flush()
    return c


def test_fiscal_year_text_is_the_plan_format():
    assert fy_text("2083/84") == "२०८३/०८४" and fy_text("") is None


def test_every_shared_key_is_a_registered_plan_variable_and_a_real_forest_column():
    from app.models.forest_metadata import ForestMetadata

    for plan_key, column in SHARED_FIELDS.items():
        assert plan_key in VARIABLE_REGISTRY, plan_key
        assert hasattr(ForestMetadata, column), column


def test_shared_values_come_from_the_forest_only_when_recorded(db, calc):
    assert shared_values(db, calc.id) == {}
    svc.upsert_metadata(db, calc.id, {**MANDATORY, "fy_start": "2083/84", "fy_end": "2093/94", "cf_history_note": "इतिहास"})
    got = shared_values(db, calc.id)
    assert got["op_start_fy"] == "२०८३/०८४" and got["forest_district"] == "v-district" and got["cf_history_note"] == "इतिहास"
    assert "sub_division_chief" not in got                                       # not recorded -> absent, not blank


def test_the_forest_value_beats_what_the_plan_typed_and_the_plan_value_is_only_a_last_resort(db, calc):
    svc.upsert_metadata(db, calc.id, {**MANDATORY, "sub_division_chief": "वनबाट"})
    plan = SimpleNamespace(plan_metadata={"user_inputs": {"sub_division_chief": "योजनाबाट", "division_forest_officer": "पुरानो"}})
    r = VariableResolver(db, str(calc.id), plan)
    assert r._resolve_user_input(VARIABLE_REGISTRY["sub_division_chief"]) == "वनबाट"          # forest wins, no override
    assert r._resolve_user_input(VARIABLE_REGISTRY["division_forest_officer"]) == "पुरानो"     # forest has none: old plan keeps working


def test_a_plan_form_save_never_stores_a_shared_key():
    kept = without_shared({"province": "x", "op_start_fy": "y", "rotation_years": 80, "cf_history_note": "z", "forest_type": "प्राकृतिक",
                           "ug_settlement": "टोल", "op_preparation_year": 2083})
    assert kept == {"rotation_years": 80, "op_preparation_year": 2083}      # plan-specific items stay with the plan


def test_the_chairperson_is_read_from_the_user_committee_not_typed_anywhere():
    from app.services.operational_plan.op_docx_builder import _resolve_var_from_raw

    raw = {"committees": {"user_committee": {"members": [
        {"name": "उपाध्यक्ष जी", "position": "उपाध्यक्ष"}, {"name": "चुना देबी सारू", "position": "अध्यक्ष"}]}}}
    assert _resolve_var_from_raw("cf_chairperson", raw) == "चुना देबी सारू"
    assert _resolve_var_from_raw("cf_chairperson", {}) is None
