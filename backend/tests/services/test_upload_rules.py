"""The rule table for hand-typed inventory numbers (VALIDATION_TRACKER.md step B) and the validator that reads it."""
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.core.dbh_classifier import DbhClassRegistry
from app.services.field_inventory_validator import FieldInventoryValidator
from app.services.upload.rules import RULES, STANDS, evaluate


# ── the table itself ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_rule_has_soft_limits_inside_its_hard_limits():
    for key, r in RULES.items():
        lo, hi = r.hard_bounds()
        assert lo is not None and hi is not None, key
        for soft in (r.soft_min, r.soft_max):
            if soft is not None:
                assert lo <= soft <= hi, f"{key}: soft limit {soft} is outside the hard range {lo}-{hi}"


@pytest.mark.parametrize("stand", STANDS)
def test_dbh_hard_limits_are_the_dbh_class_not_a_copy(stand):
    registry = {c.key: (float(c.lower), float(c.upper) if c.upper is not None else 999.0) for c in DbhClassRegistry.get_system("validation")}
    key = "regen_dbh" if stand == "regeneration" else f"{stand}_dbh"
    assert RULES[key].hard_bounds() == registry[stand]


def test_the_rule_keys_are_the_keys_the_column_detector_produces():
    v = FieldInventoryValidator(MagicMock())
    cols = ["block_name", "sample_plot_number", "longitude", "latitude", "regen_species_scientific", "regen_dbh", "regen_count",
            "sapling_species_scientific", "sapling_dbh_cm", "sapling_count", "pole_species_scientific", "pole_dbh_cm", "pole_height_m",
            "tree_species_scientific", "tree_dbh_cm", "tree_height_m"]
    detected = v._detect_columns(pd.DataFrame({c: [1] for c in cols}))["columns"]
    assert set(RULES) <= set(detected), set(RULES) - set(detected)


def test_owner_decisions_are_in_the_table():
    assert RULES["tree_dbh"].soft_max == 100.0 and RULES["tree_dbh"].hard_bounds()[1] == 200.0
    assert RULES["pole_dbh"].hard_bounds() == (10.0, 30.0)
    assert RULES["regen_count"].integer and RULES["sapling_count"].integer
    assert not RULES["tree_height"].integer and not RULES["tree_dbh"].integer  # decimals are allowed


def test_evaluate_separates_hard_soft_and_fractional_and_numbers_the_spreadsheet_rows():
    ev = evaluate(RULES["sapling_count"], pd.Series([3, 0, 12, 2.5, None, "abc"]))
    assert ev.total == 4  # blanks and text are skipped here
    assert ev.hard_rows == [3]  # 0 is below the minimum of 1 (row 3 = second data row)
    assert ev.soft_rows == [4]  # 12 is above the usual 10
    assert ev.not_whole_rows == [5]


# ── the validator ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def validator():
    v = FieldInventoryValidator(MagicMock())
    v.errors, v.warnings, v.info = [], [], []
    return v


def _run(v, df, *names):
    cols = v._detect_columns(df)["columns"]
    v.errors, v.warnings = [], []
    for name in names:
        getattr(v, name)(df, cols)
    return v


def _frame(**cols):
    n = max(len(x) for x in cols.values())
    base = {"block_name": ["B1"] * n, "sample_plot_number": list(range(1, n + 1)), "longitude": [84.1] * n, "latitude": [28.2] * n}
    base.update(cols)
    return pd.DataFrame(base)


def test_heights_are_checked_and_decimals_are_fine(validator):
    v = _run(validator, _frame(tree_species_scientific=["Shorea robusta"] * 4, tree_dbh_cm=[40.0] * 4, tree_height_m=[12.5, 0.2, 80.0, 55.0]), "_validate_heights")
    assert [(e["type"], e["rows"]) for e in v.errors] == [("height_out_of_range", [3, 4])]  # 0.2 m and 80 m are impossible
    assert [(w["type"], w["rows"]) for w in v.warnings] == [("height_unusual", [5])]  # 55 m is possible but unusual; 12.5 m passes


def test_a_short_pole_is_a_soft_flag_not_a_refusal(validator):
    v = _run(validator, _frame(pole_species_scientific=["Shorea robusta"] * 2, pole_dbh_cm=[15.0, 18.0], pole_height_m=[3.0, 9.5]), "_validate_heights")
    assert v.errors == [] and [w["rows"] for w in v.warnings] == [[2]]


def test_counts_must_be_whole_and_at_least_one(validator):
    v = _run(validator, _frame(regen_species_scientific=["Shorea robusta"] * 4, regen_dbh=[2.0] * 4, regen_count=[3, 0, 2.5, 20]), "_validate_counts")
    errs = sorted((e["type"], tuple(e["rows"])) for e in v.errors)
    assert errs == [("invalid_count", (3,)), ("invalid_count", (4,))]  # 0 -> row 3, 2.5 -> row 4
    assert [(w["type"], w["rows"]) for w in v.warnings] == [("count_unusual", [5])]  # 20 stems in the plot


def test_a_file_without_these_columns_is_untouched(validator):
    v = _run(validator, _frame(tree_species_scientific=["Shorea robusta"], tree_dbh_cm=[40.0]), "_validate_heights", "_validate_counts")
    assert v.errors == [] and v.warnings == []


def test_a_species_cannot_exceed_its_own_maximum(validator, monkeypatch):
    monkeypatch.setattr(validator, "_species_limits", lambda names: {"shorea robusta": (150.0, 35.0), "schima wallichii": (100.0, 30.0)})
    df = _frame(tree_species_scientific=["Shorea robusta", "Schima wallichii", "Shorea robusta", "Unknown sp"], tree_dbh_cm=[140.0, 120.0, 160.0, 190.0],
                tree_height_m=[30.0, 31.0, 36.0, 40.0])
    v = _run(validator, df, "_validate_species_limits")
    by = {w["type"]: w["rows"] for w in v.warnings}
    assert by["dbh_above_species_max"] == [3, 4]  # 120 > 100 (Schima), 160 > 150 (Shorea); the unknown species has no cap
    assert by["height_above_species_max"] == [3, 4]  # 31 > 30, 36 > 35


def test_a_value_the_hard_limits_already_refuse_is_not_repeated_as_a_species_flag(validator, monkeypatch):
    monkeypatch.setattr(validator, "_species_limits", lambda names: {"shorea robusta": (150.0, 35.0)})
    v = _run(validator, _frame(tree_species_scientific=["Shorea robusta"], tree_dbh_cm=[450.0], tree_height_m=[30.0]), "_validate_dbh_ranges", "_validate_species_limits")
    assert [e["type"] for e in v.errors] == ["dbh_out_of_range"] and v.warnings == []


def test_a_whole_column_in_the_wrong_unit_is_left_to_the_unit_finding(validator):
    feet = _run(validator, _frame(tree_species_scientific=["Shorea robusta"] * 4, tree_dbh_cm=[40.0] * 4, tree_height_m=[90.0, 100.0, 110.0, 120.0]), "_validate_heights")
    assert feet.errors == [] and feet.warnings == []  # median 105 looks like feet: one warning from the unit check, not four refusals
    mm = _run(validator, _frame(tree_species_scientific=["Shorea robusta"] * 4, tree_dbh_cm=[350.0, 400.0, 450.0, 500.0], tree_height_m=[20.0] * 4), "_validate_dbh_ranges")
    assert mm.errors == []  # median 425 looks like millimetres: the dbh_unit error says so once
    stray = _run(validator, _frame(tree_species_scientific=["Shorea robusta"] * 4, tree_dbh_cm=[40.0, 45.0, 50.0, 450.0], tree_height_m=[20.0] * 4), "_validate_dbh_ranges")
    assert [e["rows"] for e in stray.errors] == [[5]]  # one stray value in an otherwise good column is still refused


# ── which stand a DBH belongs to (the tree-model exports used to type the edges: 4, 10, 20, 30) ────────────────────────

@pytest.mark.parametrize("dbh, stand", [
    (0.5, "regeneration"), (1.0, "regeneration"), (3.999, "regeneration"),
    (4.0, "sapling"), (9.999, "sapling"),
    (10.0, "pole"), (19.99, "pole"), (20.0, "pole"), (29.999, "pole"),
    (30.0, "tree"), (100.0, "tree"), (200.0, "tree"), (350.0, "tree"),
])
def test_stand_for_dbh_follows_the_half_open_dbh_classes(dbh, stand):
    from app.services.upload.rules import stand_for_dbh

    assert stand_for_dbh(dbh) == stand


def test_the_exports_place_a_stem_in_the_same_stand_the_validation_expects():
    """A value the export writes into the pole column must be one the pole rule accepts, at every edge."""
    from app.services.upload.rules import stand_for_dbh

    for dbh in (1.0, 3.999, 4.0, 9.999, 10.0, 29.999, 30.0, 150.0):
        stand = stand_for_dbh(dbh)
        key = {"regeneration": "regen_dbh", "sapling": "sapling_dbh", "pole": "pole_dbh", "tree": "tree_dbh"}[stand]
        assert evaluate(RULES[key], pd.Series([dbh])).hard_rows == [], (dbh, stand)
