"""The Excel templates convert UTM to WGS 84 themselves (hidden Convert sheet)."""
import io
import math
import re

import pytest
from openpyxl import load_workbook

from app.services.upload import utm_sheet as us
from app.services.upload.templates import build_workbook, tables, workbook_bytes

COORD_TABLES = [t for t in tables() if t.has_coordinates]
POINTS = [  # (epsg, easting, northing) around the community forests of both zones
    (32645, 356841.9, 3031794.4), (32645, 330000.0, 3100000.0), (32644, 640000.0, 3050000.0), (32644, 700000.0, 3200000.0), (32645, 400000.0, 3000000.0),
]


def _excel_to_python(formula: str, cells: dict) -> float:
    """Evaluate one Convert arithmetic formula with Python's maths (only the functions the sheet uses)."""
    expr = formula.lstrip("=").replace("^", "**")
    for f in ("SINH", "COSH", "SIN", "COS", "ASIN", "ATAN", "DEGREES"):
        expr = re.sub(rf"\b{f}\(", f"_{f.lower()}(", expr)
    expr = re.sub(r"\$?([A-Z])\$?(\d+)", lambda m: repr(cells[m.group(1) + m.group(2)]), expr)
    env = {"_sinh": math.sinh, "_cosh": math.cosh, "_sin": math.sin, "_cos": math.cos, "_asin": math.asin, "_atan": math.atan, "_degrees": math.degrees}
    return eval(expr, {"__builtins__": {}}, env)  # noqa: S307 -- our own formulas only


@pytest.mark.parametrize("epsg,e,n", POINTS)
def test_the_series_matches_proj_to_a_millimetre(epsg, e, n):
    from pyproj import Transformer

    lon, lat = Transformer.from_crs(epsg, 4326, always_xy=True).transform(e, n)
    got_lon, got_lat = us.reference(e, n, epsg)
    assert abs(got_lon - lon) * 111_000 < 0.001 and abs(got_lat - lat) * 111_000 < 0.001


@pytest.mark.parametrize("epsg,e,n", POINTS)
def test_the_formulas_in_the_sheet_compute_what_the_series_computes(epsg, e, n):
    wb = load_workbook(io.BytesIO(workbook_bytes(build_workbook(COORD_TABLES[0]))))
    ws = wb[us.SHEET]
    cells = {f"{c}{r}": ws[f"{c}{r}"].value for c in "NO" for r in range(1, 9)}
    r = 2
    cells.update({f"A{r}": epsg, f"B{r}": e, f"C{r}": n, f"D{r}": us.ZONE_CENTRAL_MERIDIAN[epsg]})
    for col in "EFGHIJK":
        cells[f"{col}{r}"] = _excel_to_python(ws[f"{col}{r}"].value, cells)
    lon, lat = us.reference(e, n, epsg)
    assert cells[f"K{r}"] == pytest.approx(lon, abs=1e-9) and cells[f"J{r}"] == pytest.approx(lat, abs=1e-9)


def test_every_coordinate_template_has_a_hidden_convert_sheet_and_calculated_columns():
    for t in COORD_TABLES:
        wb = load_workbook(io.BytesIO(workbook_bytes(build_workbook(t))))
        assert wb[us.SHEET].sheet_state == "hidden" and wb.sheetnames[0] == "Data", t.file_stem
        ws = wb["Data"]
        cols = {c.value: c.column_letter for c in ws[1]}
        assert {us.INPUT_EPSG, us.X_COL, us.Y_COL, "longitude", "latitude", "coordinate_system_epsg"} <= set(cols), t.file_stem
        for name in ("longitude", "latitude", "coordinate_system_epsg"):
            assert str(ws[f"{cols[name]}2"].value).startswith("="), (t.file_stem, name)
        # rows are found by ROW(), never by a fixed address: deleting the example row must not break anything
        assert "INDEX(Convert!$K:$K,ROW())" in ws[f"{cols['longitude']}3"].value
        assert "INDEX(Data!" in wb[us.SHEET]["B3"].value


def test_the_calculated_columns_do_not_confuse_the_importers():
    from app.services.upload.column_synonyms import coordinate_columns
    from app.services.upload.coordinates import CRS_COLUMN_NAMES

    header = [us.INPUT_EPSG, us.X_COL, us.Y_COL, "longitude", "latitude", "coordinate_system_epsg"]
    for purpose in ("trees", "field_inventory", "sample_plots"):
        assert coordinate_columns(header, purpose) == ("longitude", "latitude")
    assert us.INPUT_EPSG not in CRS_COLUMN_NAMES


def test_the_plain_header_keeps_the_plain_columns():
    from app.services.upload.templates import csv_bytes

    for t in COORD_TABLES:
        head = csv_bytes(t).decode("utf-8-sig").splitlines()[0].split(",")
        assert us.X_COL not in head and "longitude" in head and "coordinate_system_epsg" in head


def test_trailing_rows_of_empty_text_are_not_records_but_the_row_numbers_above_stay():
    from app.api.inventory import read_upload_file

    df = read_upload_file(b"a,b\n1,2\n,\n3,4\n,\n \n,\n", "x.csv")
    assert len(df) == 3 and list(df.index) == [0, 1, 2]  # the blank row in the middle stays (row 3 of the sheet); only the empty tail goes
