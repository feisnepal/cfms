"""FP-9 gate: a recorded plan decision reaches the OP document, and saving one clears the cached OP data so the
document is rebuilt with it."""
import uuid

import pytest

from app.models.calculation import Calculation
from app.models.forest_decision import ForestDecision
from app.models.op_data_cache import OpDataCache
from app.models.user import User, UserRole
from app.services.operational_plan import hazard_vuln_narration as nar
from app.services.operational_plan.data_collector import OP_DATA_CACHE_VERSION, _plan_decision_choice

BASE = {"hazard_vuln_available": True, "lsi_class_method": "quantile"}


@pytest.mark.parametrize("lang", ["en", "ne"])
def test_no_decision_adds_no_sentence(lang):
    assert nar._landslide_decision_note(BASE, lang) == ""
    assert nar.methodology(BASE, lang) == nar.methodology({**BASE, "decision_landslide_method": None}, lang)


def test_relative_decision_is_stated_in_both_languages():
    d = {**BASE, "decision_landslide_method": "relative"}
    assert nar.methodology(d, "en").endswith("It has been decided to keep the landslide classes relative to this forest.")
    assert "सापेक्ष राख्ने निर्णय" in nar.methodology(d, "ne")


def test_calibration_request_is_stated_and_the_classes_stay_relative():
    d = {**BASE, "decision_landslide_method": "needs_calibration"}
    en = nar.methodology(d, "en")
    assert "Calibration of the landslide classes" in en and "stay relative" in en
    assert "क्यालिब्रेट" in nar.methodology(d, "ne")


def test_an_unknown_choice_prints_nothing():
    assert nar._landslide_decision_note({"decision_landslide_method": "something-else"}, "en") == ""


def _calc(db):
    user = User(email=f"fp9{uuid.uuid4().hex[:8]}@test.com", full_name="FP-9", role=UserRole.USER, hashed_password="x")
    db.add(user)
    db.flush()
    calc = Calculation(id=str(uuid.uuid4()), user_id=user.id, uploaded_filename="fp9.csv", is_draft=False)
    db.add(calc)
    db.flush()
    return calc, user


def test_collector_reads_only_the_forest_wide_answer(db):
    calc, user = _calc(db)
    assert _plan_decision_choice(db, str(calc.id), "landslide_method") is None
    db.add(ForestDecision(calculation_id=calc.id, key="orientation", scope="b1", choice="custom", decided_by=user.id))
    db.add(ForestDecision(calculation_id=calc.id, key="landslide_method", scope=None, choice="needs_calibration", decided_by=user.id))
    db.flush()
    assert _plan_decision_choice(db, str(calc.id), "landslide_method") == "needs_calibration"
    assert _plan_decision_choice(db, str(calc.id), "household_placement") is None
    db.rollback()


def test_saving_a_decision_clears_the_cached_op_data(db):
    calc, user = _calc(db)
    db.add(OpDataCache(calculation_id=calc.id, data={"_cache_version": OP_DATA_CACHE_VERSION}))
    db.commit()
    assert db.query(OpDataCache).filter(OpDataCache.calculation_id == calc.id).count() == 1
    db.add(ForestDecision(calculation_id=calc.id, key="landslide_method", choice="relative", decided_by=user.id))
    db.commit()
    assert db.query(OpDataCache).filter(OpDataCache.calculation_id == calc.id).count() == 0
