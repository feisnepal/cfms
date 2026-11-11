"""A tree inventory with some blank coordinates uploads, processes, and says which rows it skipped.

Regression: a blank longitude/latitude (NaN) used to
  * turn CRS detection into "Could not detect CRS automatically" (min/max of NaN is NaN), and
  * be stored as POINT(nan nan), which then failed mother-tree selection for the WHOLE file with
    "transform: Point outside of projection domain" -- the upload came back as a 500, and the
    retry left the person looking at an empty analysis.
"""
import io
import uuid

import numpy as np
import pandas as pd
import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import box

from app.models.calculation import Calculation
from app.services.validators.coordinate_detector import CoordinateDetector


def _login(client, db, prefix="mc"):
    from app.models.user import User

    email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "MC"})
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, db.query(User).filter(User.email == email).first()


def _csv(blank_rows=(3,), n=8) -> bytes:
    rows = []
    for i in range(n):
        lon, lat = (85.2300 + i * 0.0003, 27.6800 + i * 0.0002)
        blank = i in blank_rows
        rows.append(f"{'' if blank else lon},{'' if blank else lat},Shorea robusta,{22 + i},{14 + i}")
    return ("longitude,latitude,species,dia_cm,height_m\n" + "\n".join(rows) + "\n").encode()


@pytest.fixture()
def forest(client, db):
    headers, user = _login(client, db)
    calc = Calculation(
        user_id=user.id, forest_name=f"MC {uuid.uuid4().hex[:6]}", structure_locked=False, is_draft=False,
        boundary_geom=from_shape(box(85.2290, 27.6790, 85.2330, 27.6820), srid=4326),
    )
    db.add(calc)
    db.commit()
    return headers, str(calc.id)


def _upload_and_process(client, headers, forest_id, content):
    up = client.post("/api/inventory/upload", headers=headers, data={"calculation_id": forest_id},
                     files={"file": ("t.csv", content, "text/csv")})
    assert up.status_code == 200, up.text
    report = up.json()
    pr = client.post(f"/api/inventory/{report['inventory_id']}/process", headers=headers,
                     files={"file": ("t.csv", content, "text/csv")})
    return report, pr


def test_validator_names_the_rows_without_coordinates_and_does_not_misreport_the_crs(client, forest):
    headers, fid = forest
    report, _ = _upload_and_process(client, headers, fid, _csv(blank_rows=(3, 5)))
    types = [w.get("type") for w in report["warnings"]]
    assert "missing_coordinate_rows" in types
    w = next(w for w in report["warnings"] if w.get("type") == "missing_coordinate_rows")
    assert w["count"] == 2 and w["rows"] == [5, 7]          # CSV line numbers (header = 1)
    assert "skipped" in w["message"]
    # the blank cells no longer make the CRS undetectable...
    assert not any(e.get("type") == "unknown_crs" for e in report["errors"])
    assert report["data_detection"]["crs"]["epsg"] == 4326
    # ...and are not ALSO flagged once per row as "Longitude nan outside Nepal bounds"
    assert not any("nan" in str(x.get("message", "")).lower() for x in report["warnings"] if x.get("type") != "missing_coordinate_rows")


def test_processing_skips_the_blank_rows_instead_of_failing_the_whole_file(client, forest):
    headers, fid = forest
    _, pr = _upload_and_process(client, headers, fid, _csv(blank_rows=(3,), n=8))
    assert pr.status_code == 200, pr.text
    body = pr.json()
    assert body["status"] == "completed"
    summary = client.get(f"/api/inventory/{body['id']}/summary", headers=headers).json()
    assert summary["total_trees"] == 7                      # 8 rows, 1 without coordinates
    assert body["row_errors"] and len(body["row_errors"]) == 1
    assert body["row_errors"][0]["row_number"] == 5
    assert "coordinates" in body["row_errors"][0]["reason"].lower()


def test_retrying_the_same_file_gives_the_same_result(client, forest):
    headers, fid = forest
    content = _csv(blank_rows=(3,), n=8)
    totals = []
    for _ in range(2):
        _, pr = _upload_and_process(client, headers, fid, content)
        assert pr.status_code == 200, pr.text
        totals.append(client.get(f"/api/inventory/{pr.json()['id']}/summary", headers=headers).json()["total_trees"])
    assert totals == [7, 7]


def test_a_file_with_no_blank_coordinates_is_unchanged(client, forest):
    headers, fid = forest
    report, pr = _upload_and_process(client, headers, fid, _csv(blank_rows=(), n=6))
    assert not any(w.get("type") == "missing_coordinate_rows" for w in report["warnings"])
    assert pr.status_code == 200 and not pr.json().get("row_errors")


# ---- the detector itself ----

def test_crs_detection_ignores_blank_coordinates():
    det = CoordinateDetector()
    x = np.array([85.23, np.nan, 85.24, 85.25])
    y = np.array([27.68, np.nan, 27.69, 27.70])
    assert det.detect_crs(x, y)["epsg"] == 4326


def test_crs_detection_with_nothing_usable_is_unknown_not_a_crash():
    det = CoordinateDetector()
    assert det.detect_crs(np.array([np.nan, np.nan]), np.array([np.nan, np.nan]))["epsg"] == "UNKNOWN"


def test_dbh_cm_and_species_scientific_columns_are_recognised(db):
    from app.services.inventory_validator import InventoryValidator

    v = InventoryValidator(db)
    df = pd.DataFrame(columns=["tree_id", "species_scientific", "dbh_cm", "height_m", "lon", "lat"])
    assert v._detect_diameter_column(df) == "dbh_cm"
    assert v._detect_species_column(df) == "species_scientific"
