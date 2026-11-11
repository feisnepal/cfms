"""CSV/Excel column reading for the user-group coordinate picker and the
user-picked lat/lon override (UP-3.2)."""

import pandas as pd

from app.services.file_processor import read_csv
from app.services.upload.csv_columns import read_csv_columns


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_read_csv_columns_reports_columns_rows_and_autodetected_lat_lon():
    data = b"Village,Latitude,Longitude\nA,27.1,85.2\nB,27.2,85.3\n"
    out = read_csv_columns(data, "villages.csv")
    assert out["columns"] == ["Village", "Latitude", "Longitude"]
    assert out["lat_col"] == "Latitude"
    assert out["lon_col"] == "Longitude"
    assert out["total_rows"] == 2
    assert out["sample_rows"][0][0] == "A"


def test_read_csv_columns_recognises_nepali_coordinate_headers():
    data = "गाउँ,अक्षांश,देशान्तर\nA,27.1,85.2\n".encode("utf-8")
    out = read_csv_columns(data, "gaun.csv")
    assert out["lat_col"] == "अक्षांश"
    assert out["lon_col"] == "देशान्तर"


def test_read_csv_columns_says_nothing_when_coordinates_are_unlabelled():
    data = b"name,east,west\nA,1,2\n"
    out = read_csv_columns(data, "mystery.csv")
    assert out["lat_col"] is None and out["lon_col"] is None
    assert out["columns"] == ["name", "east", "west"]


def test_read_csv_columns_reads_excel(tmp_path):
    p = tmp_path / "points.xlsx"
    pd.DataFrame({"Lat": [27.1], "Lon": [85.2]}).to_excel(p, index=False)
    out = read_csv_columns(p.read_bytes(), "points.xlsx")
    assert out["columns"] == ["Lat", "Lon"]
    assert out["lat_col"] == "Lat" and out["lon_col"] == "Lon"
    assert out["total_rows"] == 1


def test_picked_lat_lon_wins_over_detection(tmp_path):
    path = _write(tmp_path, "x.csv", "Name,col1,col2\nA,27.1,85.2\n")
    # Auto-detection cannot name these columns: importing fails.
    try:
        read_csv(path)
        raised = False
    except ValueError:
        raised = True
    assert raised
    # The user's pick makes the same file importable.
    geoms, _attrs, _crs = read_csv(path, lat_col="col1", lon_col="col2")
    assert len(geoms) == 1
    assert abs(geoms[0].x - 85.2) < 1e-6 and abs(geoms[0].y - 27.1) < 1e-6


def test_picked_column_that_does_not_exist_is_named(tmp_path):
    path = _write(tmp_path, "x.csv", "Name,col1,col2\nA,27.1,85.2\n")
    try:
        read_csv(path, lat_col="missing", lon_col="col2")
        raised = None
    except ValueError as exc:
        raised = str(exc)
    assert raised is not None and "missing" in raised
