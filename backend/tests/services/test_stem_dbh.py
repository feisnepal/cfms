"""Stem mapping: one continuous DBH range for every stem, not the stand classes (owner, 2026-10-13)."""
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.services.inventory_validator import InventoryValidator
from app.services.upload.rules import RULES, STEM_DBH


@pytest.fixture()
def validator():
    return InventoryValidator(MagicMock())


def _check(v, values):
    return v._validate_dbh_range(pd.DataFrame({"dia_cm": values}), "dia_cm")


def _rows(items):
    return [i["row"] for i in items]


def test_a_stem_may_measure_from_1_to_100_cm_without_a_word(validator):
    out = _check(validator, [1.0, 2.5, 3.99, 4.0, 10.0, 29.9, 30.0, 55.5, 100.0])
    assert out == {"errors": [], "warnings": []}  # no stand classes: a 25 cm and a 60 cm stem are equally fine


def test_above_100_cm_the_user_is_asked_if_it_is_correct(validator):
    out = _check(validator, [40.0, 100.1, 150.0, 200.0])
    assert out["errors"] == [] and _rows(out["warnings"]) == [3, 4, 5]
    assert "is it correct" in out["warnings"][0]["message"] and out["warnings"][0]["suggestion"] == "Please confirm the measurement"


def test_above_200_cm_is_refused(validator):
    out = _check(validator, [40.0, 200.5, 450.0])
    assert _rows(out["errors"]) == [3, 4] and "unrealistically large" in out["errors"][0]["message"]


def test_a_stem_under_1_cm_cannot_be_measured_at_breast_height(validator):
    out = _check(validator, [2.5, 0.6, 0.99, 1.0])
    assert _rows(out["errors"]) == [3, 4] and out["warnings"] == []


def test_missing_zero_and_negative_are_refused(validator):
    out = _check(validator, [None, 0.0, -3.0, 30.0])
    assert [e["message"] for e in out["errors"]] == ["Missing DBH value", "DBH must be positive", "DBH must be positive"]


def test_the_numbers_come_from_the_rule_table_and_do_not_disturb_the_stand_rules():
    assert (STEM_DBH.hard_bounds(), STEM_DBH.soft_min, STEM_DBH.soft_max) == ((1.0, 200.0), None, 100.0)
    assert STEM_DBH.key not in RULES  # the field inventory (stand classes) and the Excel templates never see it
