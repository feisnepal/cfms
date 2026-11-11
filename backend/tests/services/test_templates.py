"""The "Download data template" zip: what it holds, that the system can READ every template, and that the declared coordinate system is checked."""
import io
import zipfile
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook

from app.services.upload import coordinates as co
from app.services.upload.classify import classify_upload, read_signals
from app.services.upload.templates import CRS_COLUMN, EXAMPLE_NOTE, build_templates_zip, build_workbook, csv_bytes, readme_text, tables

pytestmark = pytest.mark.usefixtures("forget_forests")


def _household(unit):
    from app.api.household_info import build_household_template_workbook
    from app.schemas.household_info import TemplateDownloadOptions

    return build_household_template_workbook(TemplateDownloadOptions(land_unit=unit, include_coordinates=False), None)


@pytest.fixture(scope="module")
def zf():
    return zipfile.ZipFile(io.BytesIO(build_templates_zip("ropani", household_workbook=_household)))


# ── what is in the zip ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_zip_holds_excel_templates_only_a_readme_and_the_household_workbook(zf):
    names = set(zf.namelist())
    assert "00_READ_ME.txt" in names and "excel/05_Households_and_Committees.xlsx" in names
    stems = {"01_Forest_Boundary_Stations", "02_Sample_Plots", "03_Field_Inventory", "04_Stem_Mapping", "06_User_Group_Points"}
    assert {f"excel/{s}.xlsx" for s in stems} <= names
    assert not any(n.startswith("csv/") or n.endswith(".csv") for n in names)  # Excel only (owner, 2026-10-13)
    assert not any(n.endswith((".gpkg", ".geojson", ".kml", ".shp")) for n in names)  # Excel or CSV only (owner)


def test_nothing_is_shipped_that_the_system_cannot_read_yet(zf):
    assert not [n for n in zf.namelist() if any(w in n.lower() for w in ("biodiversity", "units"))]


def test_every_excel_template_opens_with_the_data_sheet_first_and_a_guideline_sheet(zf):
    for n in (n for n in zf.namelist() if n.endswith(".xlsx")):
        wb = load_workbook(io.BytesIO(zf.read(n)))
        assert wb.sheetnames[0] in ("Data", "Parameters") or n.endswith("Households_and_Committees.xlsx"), n
        if "Households" not in n:
            assert [x for x in wb.sheetnames if x != "Convert"] == ["Data", "Guideline"], n  # the importers read the FIRST sheet


def test_the_household_workbook_is_the_existing_one_with_the_committee_sheets(zf):
    wb = load_workbook(io.BytesIO(zf.read("excel/05_Households_and_Committees.xlsx")))
    assert {"Household Information", "वन उपभोक्ता समिति", "सल्लाहाकार समिति", "आर्थिक समिति"} <= set(wb.sheetnames)


def test_the_land_unit_is_an_option_and_defaults_to_ropani():
    kaththa = zipfile.ZipFile(io.BytesIO(build_templates_zip("kaththa", household_workbook=_household)))
    wb = load_workbook(io.BytesIO(kaththa.read("excel/05_Households_and_Committees.xlsx")))
    text = " ".join(str(c.value) for row in wb["Instructions"].iter_rows() for c in row if c.value)
    assert "Land Unit: kaththa" in text
    assert "Land Unit: ropani" in " ".join(str(c.value) for row in load_workbook(io.BytesIO(
        zipfile.ZipFile(io.BytesIO(build_templates_zip(household_workbook=_household))).read("excel/05_Households_and_Committees.xlsx")))["Instructions"].iter_rows() for c in row if c.value)


# ── the coordinate system is required ─────────────────────────────────────────────────────────────────────────────────

def test_every_table_with_coordinates_has_the_required_coordinate_system_column_in_excel(zf):
    for t in (t for t in tables() if t.has_coordinates):
        assert CRS_COLUMN in [c.name for c in t.columns]
        ws = load_workbook(io.BytesIO(zf.read(f"excel/{t.file_stem}.xlsx")))["Data"]
        letter = [c.column_letter for c in ws[1] if c.value == "input_coordinate_system_epsg"][0]  # the Excel form: the user names the system, the sheet converts
        dv = next(d for d in ws.data_validations.dataValidation if str(d.sqref).startswith(f"{letter}2"))
        assert dv.type == "list" and dv.formula1 == '"4326,32644,32645"' and dv.errorStyle == "stop"


def test_a_coordinate_with_no_declared_system_or_a_number_that_cannot_fit_it_is_red(zf):
    ws = load_workbook(io.BytesIO(zf.read("excel/03_Field_Inventory.xlsx")))["Data"]
    formulas = [r.formula[0] for rules in ws.conditional_formatting._cf_rules.values() for r in rules]
    epsg = [c.column_letter for c in ws[1] if c.value == "input_coordinate_system_epsg"][0]
    calc = [c.column_letter for c in ws[1] if c.value == CRS_COLUMN][0]
    assert any(f"LEN({epsg}2)=0" in f for f in formulas)  # an X typed with no system named
    assert any(f"${calc}2=4326" in f and "<80" in f for f in formulas)  # converted degrees outside Nepal


def test_the_example_row_is_flagged_if_it_is_left_in(zf):
    ws = load_workbook(io.BytesIO(zf.read("excel/04_Stem_Mapping.xlsx")))["Data"]
    assert [c.value for c in ws[2]][0] == EXAMPLE_NOTE  # the species check names it instead of letting it pass as a tree


# ── the limits are the shared rules ───────────────────────────────────────────────────────────────────────────────────

def test_the_field_inventory_template_carries_the_shared_limits(zf):
    ws = load_workbook(io.BytesIO(zf.read("excel/03_Field_Inventory.xlsx")))["Data"]
    cols = {c.value: c.column_letter for c in ws[1]}
    by = {str(d.sqref).split(":")[0]: d for d in ws.data_validations.dataValidation}
    p = f"{cols['pole_dbh_cm']}2"
    assert by[p].type == "custom" and by[p].formula1 == f"AND(ISNUMBER({p}),{p}>=10,{p}<30)"  # the half-open class
    t = by[f"{cols['tree_dbh_cm']}2"]
    assert (t.type, t.formula1, t.formula2) == ("decimal", "30", "200")
    assert set(cols) >= {"regen_dbh", "sapling_dbh_cm", "pole_dbh_cm", "tree_dbh_cm", "tree_species_scientific"}  # all four stands (the workbook sheet lacked two)


def test_stem_mapping_uses_one_continuous_range_not_the_stand_classes(zf):
    ws = load_workbook(io.BytesIO(zf.read("excel/04_Stem_Mapping.xlsx")))["Data"]
    cols = {c.value: c.column_letter for c in ws[1]}
    by = {str(d.sqref).split(":")[0]: d for d in ws.data_validations.dataValidation}
    d = by[f"{cols['dia_cm']}2"]
    assert (d.type, d.formula1, d.formula2) == ("decimal", "1", "200")
    formulas = [r.formula[0] for rules in ws.conditional_formatting._cf_rules.values() for r in rules]
    assert any(f"{cols['dia_cm']}2>100" in f for f in formulas)  # amber above 100 cm: "is it correct?"


def test_the_readme_states_the_coordinate_system_the_limits_and_the_units(zf):
    text = zf.read("00_READ_ME.txt").decode("utf-8-sig")
    for must in (CRS_COLUMN, "4326", "32644", "32645", "Modified UTM", "10 to under 30 cm", "30 to 200 cm", "1 to 200 cm", "walked", "निर्देशाङ्क प्रणाली",
                 "Excel Workbook (*.xlsx)", "ForestName_Module_Type_YYYYMMDD", "Nepali digits (१२३)"):
        assert must in text, must


# ── the system can read every template it ships ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stem, purpose", [("01_Forest_Boundary_Stations", "forest_boundary"), ("02_Sample_Plots", "sample_plots"), ("03_Field_Inventory", "field_inventory"),
                                         ("04_Stem_Mapping", "trees")])
def test_the_classifier_recognises_each_template_by_its_plain_header(zf, stem, purpose):
    content = csv_bytes(next(t for t in tables() if t.file_stem == stem))  # the plain header the importers also read
    sig = read_signals(content, f"{stem}.csv")
    assert classify_upload(filename="data1", **sig).best == purpose


def test_the_field_inventory_importer_finds_every_required_column_and_all_four_stands():
    from app.services.field_inventory_validator import FieldInventoryValidator

    t = next(t for t in tables() if t.file_stem == "03_Field_Inventory")
    det = FieldInventoryValidator(MagicMock())._detect_columns(pd.DataFrame({c.name: [1] for c in t.columns}))
    assert det["missing_required"] == [] and det["stand_types_present"] == ["regeneration", "sapling", "pole", "tree"]


def test_the_stem_mapping_and_boundary_importers_map_their_columns():
    from app.utils.column_mapper import ColumnMapper

    stem = next(t for t in tables() if t.file_stem == "04_Stem_Mapping")
    mapped = ColumnMapper().auto_map_columns([c.name for c in stem.columns])["mapped"]
    assert set(mapped.values()) >= {"species", "dia_cm", "LONGITUDE", "LATITUDE"}
    bd = next(t for t in tables() if t.file_stem == "01_Forest_Boundary_Stations")
    assert set(ColumnMapper().auto_map_columns([c.name for c in bd.columns])["mapped"].values()) >= {"LONGITUDE", "LATITUDE"}


def test_a_template_filled_with_valid_data_passes_the_field_inventory_validator():
    import asyncio

    from app.services.field_inventory_validator import FieldInventoryValidator

    v = FieldInventoryValidator(MagicMock())
    df = pd.DataFrame({"block_name": ["B1"] * 2, "sample_plot_number": [1, 2], "longitude": [85.56, 85.561], "latitude": [27.405, 27.406], CRS_COLUMN: [4326, 4326],
                       "tree_species_scientific": ["Shorea robusta"] * 2, "tree_dbh_cm": [45.5, 52.0], "tree_height_m": [18.5, 20.0], "tree_class": ["A", "A"]})
    v._species_limits = lambda names: {}
    report = asyncio.run(v.validate_field_inventory_file(df, None))
    assert report["summary"]["ready_for_processing"] is True  # the extra coordinate_system_epsg column does not get in the way


# ── reading the declared system ───────────────────────────────────────────────────────────────────────────────────────

def _df(values, lon=(85.5, 85.6, 85.7), lat=(27.4, 27.5, 27.6)):
    return pd.DataFrame({"longitude": list(lon), "latitude": list(lat), CRS_COLUMN: values})


def test_a_single_declared_system_is_read_in_any_spelling():
    assert co.declared_system(_df([4326, 4326, 4326]))["epsg"] == 4326
    assert co.declared_system(_df(["EPSG:32645", "epsg:32645", " 32645 "]))["epsg"] == 32645
    assert co.declared_system(_df(["३२६४५", "३२६४५", "३२६४५"]))["epsg"] == 32645  # Nepali digits


def test_rows_that_disagree_are_mixed_and_unsupported_codes_are_named():
    d = co.declared_system(_df([4326, 32645, 32645]))
    assert d["mixed"] is True and d["epsg"] is None and d["values"] == [4326, 32645]
    u = co.declared_system(_df([32745, 32745, 32745]))
    assert u["unsupported"] == [32745] and u["epsg"] is None


def test_rows_with_coordinates_and_no_declaration_are_named():
    d = co.declared_system(_df([4326, None, 4326]))
    assert d["epsg"] == 4326 and d["blank_rows"] == [3]


def test_a_file_without_the_column_declares_nothing():
    d = co.declared_system(pd.DataFrame({"longitude": [85.5], "latitude": [27.4]}))
    assert d["column"] is None and d["epsg"] is None and d["mixed"] is False


# ── the endpoints ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_zip_endpoint_needs_a_login_and_returns_a_zip(client, auth_headers):
    assert client.get("/api/uploads/templates.zip").status_code in (401, 403)
    r = client.get("/api/uploads/templates.zip", headers=auth_headers)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "Forest_Data_Templates_" in r.headers["content-disposition"] and r.content[:2] == b"PK"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "00_READ_ME.txt" in names and "excel/05_Households_and_Committees.xlsx" in names


def test_the_land_unit_option_is_validated(client, auth_headers):
    assert client.get("/api/uploads/templates.zip?land_unit=kaththa", headers=auth_headers).status_code == 200
    assert client.get("/api/uploads/templates.zip?land_unit=acre", headers=auth_headers).status_code == 422


@pytest.fixture()
def nepal_outline(monkeypatch):
    """The test database has no boundary data: a coarse rectangle of Nepal stands in for the real outline."""
    monkeypatch.setattr(co, "inside_nepal_flags", lambda db, lons, lats: [bool(np.isfinite(a) and np.isfinite(b) and 80.0 <= a <= 88.2 and 26.4 <= b <= 30.4) for a, b in zip(lons, lats)])


def _post_coords(client, auth_headers, csv):
    return client.post("/api/uploads/coordinate-system", files={"file": ("stations.csv", csv, "text/csv")}, headers=auth_headers).json()


def test_a_declaration_that_fits_the_numbers_is_accepted_and_wins(client, auth_headers, nepal_outline):
    body = _post_coords(client, auth_headers, f"longitude,latitude,{CRS_COLUMN}\n85.5,27.4,4326\n85.6,27.5,4326\n")
    assert body["declared_epsg"] == 4326 and body["declared_ok"] is True and body["suggested_epsg"] == 4326


def test_a_declaration_the_numbers_do_not_fit_is_named_not_trusted(client, auth_headers, nepal_outline):
    # the file says degrees, but the numbers are UTM metres
    body = _post_coords(client, auth_headers, f"longitude,latitude,{CRS_COLUMN}\n356841.9,3031794.4,4326\n357143.7,3032234.1,4326\n")
    assert body["declared_epsg"] == 4326 and body["declared_ok"] is False and body["declared_fraction"] == 0.0
    assert body["suggested_epsg"] == 32645  # what the numbers do fit


def test_a_utm_declaration_that_fits_selects_that_zone(client, auth_headers, nepal_outline):
    body = _post_coords(client, auth_headers, f"easting,northing,{CRS_COLUMN}\n356841.9,3031794.4,32645\n357143.7,3032234.1,32645\n")
    assert body["declared_epsg"] == 32645 and body["declared_ok"] is True and body["suggested_epsg"] == 32645


def test_the_boundary_preview_uses_the_declared_system_without_being_told(client, auth_headers, db):
    import uuid

    from app.models.calculation import Calculation
    from app.models.user import User

    owner = db.query(User).filter(User.email == "testuser@example.com").first()
    c = Calculation(id=uuid.uuid4(), user_id=owner.id, forest_name="declared system test")
    db.add(c)
    db.commit()
    rows = "\n".join(f"{i},{356841.9 + 40 * i},{3031794.4 + 30 * (i % 3)},32645" for i in range(1, 9))
    csv = f"station_no,longitude,latitude,{CRS_COLUMN}\n{rows}\n"
    r = client.post(f"/api/workspace/{c.id}/boundary/preview-mapping", files={"file": ("st.csv", csv, "text/csv")}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["declared_epsg"] == 32645 and body["detected_crs"] == 32645
    assert 85.4 < body["points_4326"][0]["lng"] < 85.7  # converted from UTM 45 without the user choosing a zone


def test_the_boundary_preview_refuses_a_file_that_declares_two_systems_or_an_unsupported_one(client, auth_headers, db):
    import uuid

    from app.models.calculation import Calculation
    from app.models.user import User

    owner = db.query(User).filter(User.email == "testuser@example.com").first()
    c = Calculation(id=uuid.uuid4(), user_id=owner.id, forest_name="declared system refusal")
    db.add(c)
    db.commit()

    def post(csv):
        return client.post(f"/api/workspace/{c.id}/boundary/preview-mapping", files={"file": ("st.csv", csv, "text/csv")}, headers=auth_headers)

    mixed = post(f"longitude,latitude,{CRS_COLUMN}\n85.5,27.4,4326\n85.6,27.5,32645\n85.7,27.6,4326\n")
    assert mixed.status_code == 400 and "more than one coordinate system" in mixed.text
    unsupported = post(f"longitude,latitude,{CRS_COLUMN}\n85.5,27.4,32745\n85.6,27.5,32745\n85.7,27.6,32745\n")
    assert unsupported.status_code == 400 and "not supported yet" in unsupported.text


# ── the guideline sheet, the cell comments and the "Save as" advice ───────────────────────────────────────────────────────

def _sheet_text(wb, name):
    return "\n".join(str(c.value) for row in wb[name].iter_rows() for c in row if c.value)


def test_every_header_has_a_comment_saying_what_to_enter_in_both_languages(zf):
    for t in tables():
        ws = load_workbook(io.BytesIO(zf.read(f"excel/{t.file_stem}.xlsx")))["Data"]
        for cell in ws[1]:
            assert cell.comment is not None, (t.file_stem, cell.value)
            text = cell.comment.text
            assert ("REQUIRED" in text or "Optional" in text) and ("अनिवार्य" in text or "ऐच्छिक" in text), (t.file_stem, cell.value)
        if not t.has_coordinates:
            continue
        crs = next(c for c in ws[1] if c.value == CRS_COLUMN)
        assert "4326" in crs.comment.text and "32645" in crs.comment.text and "Allowed" in crs.comment.text


def test_a_comment_on_a_limited_column_states_the_limit(zf):
    ws = load_workbook(io.BytesIO(zf.read("excel/03_Field_Inventory.xlsx")))["Data"]
    pole = next(c for c in ws[1] if c.value == "pole_dbh_cm")
    assert "10 to under 30 cm" in pole.comment.text and "Diameter at breast height" in pole.comment.text


def test_the_guideline_sheet_gives_the_data_entry_procedure_step_by_step(zf):
    text = _sheet_text(load_workbook(io.BytesIO(zf.read("excel/03_Field_Inventory.xlsx"))), "Guideline")
    for must in ("HOW TO FILL THIS TEMPLATE", "Delete the grey example row", "Leave a cell empty", "RED cell", "AMBER cell", "drop it into 'Add data'",
                 "यो टेम्प्लेट कसरी भर्ने", "खैरो उदाहरण पङ्क्ति"):
        assert must in text, must


def test_the_guideline_sheet_lists_every_column_with_what_to_enter_and_the_limits(zf):
    for t in tables():
        text = _sheet_text(load_workbook(io.BytesIO(zf.read(f"excel/{t.file_stem}.xlsx"))), "Guideline")
        for c in t.columns:
            assert c.name in text, (t.file_stem, c.name)
        assert "COLUMNS" in text and "स्तम्भहरू" in text
    fi = _sheet_text(load_workbook(io.BytesIO(zf.read("excel/03_Field_Inventory.xlsx"))), "Guideline")
    assert "10 to under 30 cm" in fi and "30 to 200 cm" in fi and "whole numbers" in fi


def test_the_guideline_sheet_says_what_to_remember_from_the_file_name_to_the_digits(zf):
    text = _sheet_text(load_workbook(io.BytesIO(zf.read("excel/04_Stem_Mapping.xlsx"))), "Guideline")
    for must in ("FILE NAME", "ForestName_Module_Type_YYYYMMDD", "no spaces or symbols", "Nepali digits (१२३)", "do not mix letters into a number",
                 "thousands separators", "Format those cells as Number", "VALUES, NOT FORMULAS", "Paste Special > Values", "फाइलको नाम"):
        assert must in text, must


def test_the_guideline_sheet_explains_the_save_as_dialog_for_excel(zf):
    text = _sheet_text(load_workbook(io.BytesIO(zf.read("excel/03_Field_Inventory.xlsx"))), "Guideline")
    for must in ("SAVING THE FILE ('Save as...')", "File > Save As", "Excel Workbook (*.xlsx)", "Do not choose .xls", "Close the file in Excel before you upload", "फाइल सुरक्षित गर्ने"):
        assert must in text, must


def test_the_readme_repeats_the_same_advice_for_people_who_never_open_the_excel_files(zf):
    text = zf.read("00_READ_ME.txt").decode("utf-8-sig")
    for must in ("THINGS TO REMEMBER", "SAVING THE FILE", "FILE NAME", "NUMBERS", "COORDINATES", "Excel Workbook (*.xlsx)"):
        assert must in text, must


def test_the_numbers_a_user_is_told_to_type_are_numbers_the_system_reads():
    """The guideline promises Nepali digits, degrees-minutes-seconds and decimal commas work. Prove each promise with the real reader."""
    from app.services.upload.coordinate_text import parse_coordinate

    assert parse_coordinate("२७.४१०५") == pytest.approx(27.4105)  # Nepali digits
    assert parse_coordinate("27°41'12\"N") == pytest.approx(27 + 41 / 60 + 12 / 3600)  # degrees-minutes-seconds
    assert parse_coordinate("27,41") == pytest.approx(27.41)  # a decimal comma is read, a point is safer
    assert parse_coordinate("345,678") == 345678.0  # thousands separators are read, but the guideline says not to type them
