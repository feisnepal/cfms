"""DBH range checks of the field-inventory validator (owner rules 2026-10-13).

The check used to look sapling / pole / tree columns up under keys the detector never produces, so only regeneration was ever checked.
"""
import asyncio
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.services.field_inventory_validator import FieldInventoryValidator


@pytest.fixture()
def validator():
    v = FieldInventoryValidator(MagicMock())
    v.errors, v.warnings, v.info = [], [], []
    return v


def _check(v, df):
    cols = v._detect_columns(df)["columns"]
    v.errors, v.warnings = [], []  # the detector's own notes (missing optional columns) are not what is under test
    v._validate_dbh_ranges(df, cols)
    return v


def _frame(**dbh):
    n = max(len(x) for x in dbh.values())
    base = {"block_name": ["B1"] * n, "sample_plot_number": list(range(1, n + 1)), "longitude": [84.1] * n, "latitude": [28.2] * n}
    for stand in ("pole", "tree"):
        if f"{stand}_dbh_cm" in dbh:
            base[f"{stand}_species_scientific"] = ["Shorea robusta"] * n
    base.update(dbh)
    return pd.DataFrame(base)


def test_a_pole_of_50_cm_is_an_error_with_its_row(validator):
    v = _check(validator, _frame(pole_dbh_cm=[15.0, 18.0, 50.0, 22.0]))
    errs = [e for e in v.errors if e["type"] == "dbh_out_of_range"]
    assert len(errs) == 1 and errs[0]["stand_type"] == "pole" and errs[0]["rows"] == [4]  # sheet row 4 = the third data row


def test_a_tree_below_the_tree_class_is_an_error(validator):
    v = _check(validator, _frame(tree_dbh_cm=[35.0, 12.0, 60.0]))
    assert [(e["stand_type"], e["rows"]) for e in v.errors] == [("tree", [3])]


def test_a_tree_above_the_hard_stop_is_an_error(validator):
    v = _check(validator, _frame(tree_dbh_cm=[35.0, 450.0]))
    assert [e["stand_type"] for e in v.errors] == ["tree"]


def test_a_tree_between_100_and_200_cm_needs_confirming_but_is_not_refused(validator):
    v = _check(validator, _frame(tree_dbh_cm=[35.0, 120.0, 150.0, 60.0]))
    assert v.errors == []
    unusual = [w for w in v.warnings if w["type"] == "dbh_unusual"]
    assert len(unusual) == 1 and unusual[0]["rows"] == [3, 4]


def test_values_inside_the_classes_pass_silently(validator):
    v = _check(validator, _frame(pole_dbh_cm=[10.0, 20.0, 29.99, 29.999], tree_dbh_cm=[30.0, 60.0, 100.0, 100.0]))
    assert v.errors == [] and v.warnings == []


def test_the_upper_edge_of_a_class_belongs_to_the_next_class(validator):
    """The DBH classes are half-open [lower, upper): a stem of exactly 30.0 cm is a tree, so it is wrong in the pole column."""
    v = _check(validator, _frame(pole_dbh_cm=[29.999, 30.0, 31.0]))
    assert [(e["stand_type"], e["rows"]) for e in v.errors] == [("pole", [3, 4])]
    assert _check(validator, _frame(tree_dbh_cm=[30.0, 200.0])).errors == []  # a tree may be exactly 30 and exactly 200 (the hard stop)
    assert [e["rows"] for e in _check(validator, _frame(tree_dbh_cm=[30.0, 200.0001])).errors] == [[3]]


def test_sapling_and_regeneration_are_still_checked(validator):
    df = _frame(sapling_dbh_cm=[5.0, 50.0], regen_dbh=[2.0, 9.0])
    df["sapling_species_scientific"] = "Shorea robusta"
    df["regen_species_scientific"] = "Shorea robusta"
    v = _check(validator, df)
    assert sorted(e["stand_type"] for e in v.errors) == ["regeneration", "sapling"]


def test_text_in_a_dbh_column_does_not_crash_the_check(validator):
    v = _check(validator, _frame(pole_dbh_cm=[15.0, "abc", 50.0]))
    assert [e["rows"] for e in v.errors] == [[4]]
