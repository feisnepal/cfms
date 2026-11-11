"""The field-inventory template is the Tree Model workbook, empty, with the species list read fresh from the table."""
import io
import zipfile

import pandas as pd
import pytest
from openpyxl import load_workbook
from sqlalchemy import text

from app.services.tree_distribution import TREE_MODEL_COLUMNS
from app.services.upload import field_inventory_template as fit
from app.services.upload import utm_sheet as us
from app.services.upload.species_resolve import resolve_species_columns


_BUILT = {}


@pytest.fixture
def wb(db):
    if "bytes" not in _BUILT:  # the build takes a few seconds: once per run
        _BUILT["bytes"] = fit.build_field_inventory_workbook(db)
    return load_workbook(io.BytesIO(_BUILT["bytes"]))


def test_sheets_and_no_exported_data(wb):
    assert [(w.title, w.sheet_state) for w in wb] == [("Data", "visible"), ("Guideline", "visible"), ("SPECIES_DATABASE", "hidden"), ("Convert", "hidden")]
    ws = wb["Data"]
    assert [c.value for c in ws[1] if c.value] == fit.columns()
    assert ws["B2"].value == "B1" and ws["B3"].value is None  # one example row; nothing else typed (formula columns aside)
    assert "Volumes" not in wb.sheetnames and "VALIDATION_GUIDE" not in wb.sheetnames  # the guide is folded into Guideline


def test_it_is_the_export_layout_plus_the_coordinate_columns():
    names = fit.columns()
    assert [n for n in names if n not in (us.INPUT_EPSG, us.X_COL, us.Y_COL, "coordinate_system_epsg")] == list(TREE_MODEL_COLUMNS)  # one list, two uses


def test_species_list_is_the_table_as_it_is_now(wb, db):
    n = db.execute(text("select count(*) from tree_species_coefficients where is_active = true")).scalar()
    sd = wb["SPECIES_DATABASE"]
    assert sd.max_row == n + 1
    shorea = next(r for r in sd.iter_rows(min_row=2, values_only=True) if r[1] == "Shorea robusta")
    assert shorea[0] == 18 and ", sal," in shorea[7] and ", shorea robusta," in shorea[7]


def test_species_cells_accept_code_scientific_and_every_local_name_and_ask_before_keeping_others(wb):
    ws = wb["Data"]
    col = next(c.column_letter for c in ws[1] if c.value == "tree_species_scientific")
    formulas = [r.formula[0] for rules in ws.conditional_formatting._cf_rules.values() for r in rules]
    assert any("<=23" in f and "SPECIES_DATABASE!$H$2" in f and f"{col}2" in f for f in formulas)
    dv = next(d for d in ws.data_validations.dataValidation if str(d.sqref).startswith(f"{col}2"))
    assert dv.type == "custom" and dv.errorStyle == "warning"


def test_yields_are_required_and_the_coordinates_convert(wb):
    ws = wb["Data"]
    head = {c.value: c for c in ws[1]}
    for n in fit.YIELD_COLUMNS:
        assert "REQUIRED" in head[n].comment.text, n
    assert str(ws[f"{head['longitude'].column_letter}3"].value).startswith("=IF(AND(ISNUMBER(")
    assert wb["Convert"].sheet_state == "hidden"


def test_guideline_carries_the_procedure_and_the_old_validation_guide(wb):
    text_ = "\n".join(str(c.value) for row in wb["Guideline"].iter_rows() for c in row if c.value)
    assert "HOW TO FILL THIS TEMPLATE" in text_ and "SAVING THE FILE" in text_ and "NUMERIC LIMITS AND COLOURS" in text_ and "TREE CLASS" in text_


def test_codes_and_local_names_become_scientific_names_and_the_rest_is_left_alone(db):
    df = pd.DataFrame({"tree_species_scientific": [18, 18.0, "18", "Sal", "sal", "Khayar", "Shorea robusta", "Nonexistent plantus", None]})
    out, findings = resolve_species_columns(db, df, {"tree_species_scientific": "tree_species_scientific"})
    got = list(out["tree_species_scientific"])
    assert got[:7] == ["Shorea robusta", "Shorea robusta", "Shorea robusta", "Shorea robusta", "Shorea robusta", "Acacia catechu", "Shorea robusta"]
    assert got[7] == "Nonexistent plantus" and pd.isna(got[8])
    assert [f.code for f in findings] == ["field_inventory.species_resolved"]


def test_zip_download_carries_the_new_workbook(client, auth_headers):
    r = client.get("/api/uploads/templates.zip", headers=auth_headers)
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    ws = load_workbook(io.BytesIO(z.read("excel/03_Field_Inventory.xlsx")))
    assert ws.sheetnames[:2] == ["Data", "Guideline"]
    assert not [n for n in z.namelist() if n.endswith(".csv")]  # Excel only


def test_a_file_in_the_template_layout_uploads_with_codes_local_names_and_the_extra_columns(client, db):
    import json
    import uuid

    from shapely import wkt as shp_wkt
    from shapely.geometry import box

    from app.models.calculation import Calculation
    from tests.integration.test_sampling_routing import _register

    headers, uid = _register(client)
    calc = Calculation(id=uuid.uuid4(), user_id=uid, forest_name="Template upload", boundary_geom=shp_wkt.dumps(box(83.4, 27.4, 83.6, 27.6)), is_draft=True)
    db.add(calc)
    db.commit()
    header = ",".join(fit.columns())
    values = {n: "" for n in fit.columns()}
    def row(**kw):
        v = dict(values, input_coordinate_system_epsg=4326, x_easting=83.5, y_northing=27.5, longitude=83.5, latitude=27.5, coordinate_system_epsg=4326, **kw)
        return ",".join(str(v[n]) for n in fit.columns())
    rows = [
        row(fid=1, block_name="B1", sample_plot_number=1, tree_species_scientific="Sal", tree_dbh_cm=45.5, tree_height_m=18.5, tree_class=1,
            pole_species_scientific=18, pole_dbh_cm=18.5, pole_height_m=11, pole_class=2,
            firewood_kg_per_100sqm_per_year=50, grass_kg_per_100sqm_per_year=50, bedding_material_kg_per_100sqm_per_year=50, ntfp_kg_per_100sqm_per_year=1),
        row(fid=2, block_name="B1", sample_plot_number=1, tree_species_scientific="Khayar", tree_dbh_cm=60, tree_height_m=20, tree_class=1),
    ]
    mapping = {n: n for n in fit.columns() if n.endswith(("_scientific", "_dbh", "_dbh_cm", "_count", "_height_m", "_class")) or n in ("block_name", "sample_plot_number", "longitude", "latitude")}
    r = client.post("/api/field-inventory/upload", headers=headers, data={"mapping": json.dumps(mapping), "calculation_id": str(calc.id)},
                    files={"file": ("fi.csv", io.BytesIO(("\n".join([header, *rows]) + "\n").encode()), "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    codes = [f["code"] for f in body.get("findings", [])]
    assert "field_inventory.species_resolved" in codes and "coordinates.system_mismatch" not in codes
    assert body["summary"]["ready_for_processing"] is True
