"""The Excel validation is generated from the rule table (step D): decimals, half-open classes, soft highlighting, rows added later, species maximums."""
import glob
import re
from unittest.mock import MagicMock

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook

from app.services.excel_validator import add_validation_to_excel
from app.services.upload.excel_rules import MIN_VALIDATED_ROWS, rule_key_for
from app.services.upload.rules import RULES, evaluate

COLUMNS = ["fid", "sample_plot_number", "regen_species_scientific", "regen_dbh", "regen_count", "sapling_species_scientific", "sapling_dbh_cm",
           "sapling_count", "pole_species_scientific", "pole_dbh_cm", "pole_height_m", "pole_class", "tree_species_scientific", "tree_dbh_cm",
           "tree_height_m", "tree_class", "firewood_kg_per_100sqm_per_year", "grass_kg_per_100sqm_per_year",
           "bedding_material_kg_per_100sqm_per_year", "ntfp_kg_per_100sqm_per_year"]


def _letter(name):
    from openpyxl.utils import get_column_letter
    return get_column_letter(COLUMNS.index(name) + 1)


@pytest.fixture()
def sheet(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(COLUMNS)
    ws.append([1, 1, "Shorea robusta", 2.5, 3, "Shorea robusta", 6.5, 2, "Shorea robusta", 22.5, 11.25, "3", "Shorea robusta", 45.5, 18.75, "2", 10.5, 5.5, 4.5, 1.5])
    path = str(tmp_path / "t.xlsx")
    wb.save(path)
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [
        ("SHO", "Shorea robusta", "Sal", True, 150.0, 35.0, "High"), ("SCH", "Schima wallichii", "Chilaune", True, 100.0, 30.0, "Moderate")]
    add_validation_to_excel(path, db)
    return load_workbook(path)


def _dv(ws, name):
    letter = _letter(name)
    found = [dv for dv in ws.data_validations.dataValidation if any(str(r).startswith(letter) and re.match(rf"{letter}\d", str(r)) for r in str(dv.sqref).split())]
    assert len(found) == 1, (name, len(found))
    return found[0]


def test_class_dbh_uses_a_half_open_range_so_decimals_just_under_the_edge_are_valid(sheet):
    ws = sheet["Data"]
    # the upper edge of a class belongs to the next class: 29.999 is a pole, 30.0 is not
    for name, lo, hi in (("regen_dbh", 1, 4), ("sapling_dbh_cm", 4, 10), ("pole_dbh_cm", 10, 30)):
        dv = _dv(ws, name)
        c = f"{_letter(name)}2"
        assert dv.type == "custom" and dv.formula1 == f"AND(ISNUMBER({c}),{c}>={lo},{c}<{hi})", name
        assert "next size class" in dv.error


def test_tree_dbh_is_30_to_200_inclusive_and_decimal(sheet):
    dv = _dv(sheet["Data"], "tree_dbh_cm")
    assert (dv.type, dv.operator, dv.formula1, dv.formula2) == ("decimal", "between", "30", "200")


def test_heights_and_resources_accept_decimals_counts_stay_whole(sheet):
    ws = sheet["Data"]
    for name in ("pole_height_m", "tree_height_m"):
        dv = _dv(ws, name)
        assert (dv.type, dv.formula1, dv.formula2) == ("decimal", "0.5", "70"), name
    for name in ("firewood_kg_per_100sqm_per_year", "grass_kg_per_100sqm_per_year", "bedding_material_kg_per_100sqm_per_year", "ntfp_kg_per_100sqm_per_year"):
        assert _dv(ws, name).type == "decimal", name
    for name in ("regen_count", "sapling_count"):
        dv = _dv(ws, name)
        assert (dv.type, dv.formula1, dv.formula2) == ("whole", "1", "1000"), name


def test_validation_runs_well_below_the_data_so_added_rows_are_checked(sheet):
    ws = sheet["Data"]
    for dv in ws.data_validations.dataValidation:
        for rng in str(dv.sqref).split():
            assert int(re.search(r"(\d+)$", rng).group(1)) >= MIN_VALIDATED_ROWS, rng


def _cf_formulas(ws, name):
    letter = _letter(name)
    out = []
    for rng, rules in ws.conditional_formatting._cf_rules.items():
        if str(rng.sqref).startswith(letter) and re.match(rf"{letter}\d", str(rng.sqref)):
            out += [(r.formula[0], r.dxf.fill.bgColor.rgb if r.dxf and r.dxf.fill else None) for r in rules]
    return out


def test_a_pasted_value_outside_the_limits_is_red_and_an_unusual_one_amber(sheet):
    ws = sheet["Data"]
    formulas = [f for f, _ in _cf_formulas(ws, "tree_dbh_cm")]
    c = f"{_letter('tree_dbh_cm')}2"
    assert f"AND(ISNUMBER({c}),OR({c}<30,{c}>200))" in formulas  # hard: red
    assert f"AND(ISNUMBER({c}),OR({c}>100))" in formulas  # soft: amber (a tree above 100 cm)
    h = f"{_letter('pole_height_m')}2"
    assert f"AND(ISNUMBER({h}),OR({h}<5,{h}>25))" in [f for f, _ in _cf_formulas(ws, "pole_height_m")]
    k = f"{_letter('regen_count')}2"
    assert f"AND(ISNUMBER({k}),OR({k}<1,{k}>1000,{k}<>INT({k})))" in [f for f, _ in _cf_formulas(ws, "regen_count")]


def test_a_dbh_or_height_above_the_species_maximum_is_amber(sheet):
    ws = sheet["Data"]
    for name, col_index in (("tree_dbh_cm", 4), ("tree_height_m", 5), ("pole_dbh_cm", 4), ("pole_height_m", 5)):
        joined = " ".join(f for f, _ in _cf_formulas(ws, name))
        assert "VLOOKUP" in joined and "SPECIES_DATABASE!$B$2:$F$3" in joined and f",{col_index},FALSE" in joined, name


def test_the_guide_says_what_the_rules_say(sheet):
    text = " ".join(str(v) for row in sheet["VALIDATION_GUIDE"].iter_rows(values_only=True) for v in row if v)
    assert "10 to under 30 cm" in text and "30 to 200 cm" in text and "1 to under 4 cm" in text
    assert "G2061" not in text and "0-4.0 cm (seedling)" not in text  # the old guide contradicted the validation it described
    assert "Decimals are allowed" in text


def test_every_rule_key_is_recognised_from_the_exports_column_names():
    assert [rule_key_for(c) for c in COLUMNS if rule_key_for(c)] == ["regen_dbh", "regen_count", "sapling_dbh", "sapling_count", "pole_dbh", "pole_height",
                                                                     "tree_dbh", "tree_height"]
    assert set(RULES) == {rule_key_for(c) for c in COLUMNS if rule_key_for(c)}


@pytest.mark.skipif(not glob.glob("../testData/old/sample_data/*TreeModel_SyntheticTrees*.xlsx"), reason="no exported sample workbooks in this checkout")
def test_the_exports_own_data_passes_its_own_rules():
    """The audit that found the problem: 46 of 108 pole heights and 22 of 23 tree heights broke the old integer-only rule."""
    for path in glob.glob("../testData/old/sample_data/*TreeModel_SyntheticTrees*.xlsx"):
        df = pd.read_excel(path, sheet_name=0)  # old exports call it "Data Template", new ones "Data"
        for col in df.columns:
            key = rule_key_for(col)
            if key:
                ev = evaluate(RULES[key], df[col])
                assert ev.hard_rows == [] and ev.not_whole_rows == [], (path, col, ev.hard_rows[:5])


# ── the Forest Data Workbook ───────────────────────────────────────────────────────────────────────────────────────────

def _workbook():
    import io

    from app.services.upload.workbook import build_excel

    return load_workbook(io.BytesIO(build_excel()))


def test_the_workbooks_field_inventory_sheet_uses_the_same_rule_table():
    from app.services.upload import schema

    ws = _workbook()["field_inventory"]
    cols = [c.name for c in schema.get("field_inventory").columns]
    from openpyxl.utils import get_column_letter

    letter = lambda n: get_column_letter(cols.index(n) + 1)  # noqa: E731
    by = {str(dv.sqref).split(":")[0]: dv for dv in ws.data_validations.dataValidation}
    p = f"{letter('pole_dbh_cm')}2"
    assert by[p].type == "custom" and by[p].formula1 == f"AND(ISNUMBER({p}),{p}>=10,{p}<30)"
    t = by[f"{letter('tree_dbh_cm')}2"]
    assert (t.type, t.formula1, t.formula2) == ("decimal", "30", "200")
    h = by[f"{letter('tree_height_m')}2"]
    assert (h.type, h.formula1, h.formula2) == ("decimal", "0.5", "70")


def test_the_other_sheets_take_their_ranges_and_lists_from_the_schema():
    from app.services.upload import schema

    wb = _workbook()
    ward = next(c for c in schema.get("households").columns if c.name == "ward")
    ws = wb["households"]
    from openpyxl.utils import get_column_letter

    idx = [c.name for c in schema.get("households").columns].index("ward") + 1
    dv = next(d for d in ws.data_validations.dataValidation if str(d.sqref).startswith(f"{get_column_letter(idx)}2"))
    assert dv.type == "whole" and float(dv.formula1) == ward.minimum and float(dv.formula2) == ward.maximum


def test_every_example_row_satisfies_the_validation_of_its_own_sheet():
    """A template whose own example is 'invalid' teaches users to ignore the validation."""
    from app.services.upload import schema

    for p in schema.ordered():
        for col in p.columns:
            ex = col.example
            if ex in (None, ""):
                continue
            if col.enum:
                assert str(ex) in col.enum, (p.id, col.name, ex)
            elif isinstance(ex, (int, float)) and (col.minimum is not None or col.maximum is not None):
                assert (col.minimum is None or ex >= col.minimum) and (col.maximum is None or ex <= col.maximum), (p.id, col.name, ex)
            key = rule_key_for(col.name) if p.id == "field_inventory" else None
            if key and isinstance(ex, (int, float)):
                ev = evaluate(RULES[key], pd.Series([ex]))
                assert ev.hard_rows == [] and ev.not_whole_rows == [], (col.name, ex)
