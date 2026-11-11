"""UP-0 characterization: what the user group map import does TODAY with each wrong file (UPLOAD_EXPERIENCE_PLAN.md).

Pins the CURRENT behaviour so the later phases change it on purpose. ``..._today`` tests are known gaps, not wanted behaviour.
Finding from writing these: the /import route already reuses the forest-boundary reader, so its messages are better than the plan's first
reading suggested (it lists the columns it found, and explains coordinates outside Nepal). The real gaps are listed per test below.
"""
from __future__ import annotations

import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box
from sqlalchemy import text

from app.models.calculation import Calculation, CalculationStatus
from tests import upload_fixtures as fx
from tests.integration.test_user_group_journey import _draw, _register, _row_count

pytestmark = pytest.mark.usefixtures("forget_forests")


@pytest.fixture()
def forest(client, db):
    headers, uid = _register(client)
    c = Calculation(
        id=uuid.uuid4(), user_id=uid, forest_name="UG baseline",
        boundary_geom=shp_wkt.dumps(box(85.5, 27.35, 85.65, 27.45)),  # Kavre-sized forest
        status=CalculationStatus.PROCESSING, is_draft=True,
    )
    db.add(c)
    db.commit()
    return headers, c


def _import(client, forest, data: bytes, name: str = "ug.csv"):
    headers, c = forest
    return client.post(f"/api/calculations/{c.id}/user-group/import", headers=headers, files={"file": (name, data, "application/octet-stream")})


def _area_ha(db, calc_id) -> float:
    return float(db.execute(text(
        "SELECT COALESCE(SUM(ST_Area(extent_geometry::geography)) / 10000.0, 0) FROM user_group_extents WHERE calculation_id = :c"
    ), {"c": calc_id}).scalar())


def test_a_correct_file_is_imported_and_the_analysis_is_announced(client, db, forest):
    r = _import(client, forest, fx.csv_square(0.02))
    assert r.status_code == 200
    assert "Analysis is running" in r.json()["message"]  # announced, but nothing later says when it is done
    assert _row_count(db, forest[1].id) == 1


def _d(r):
    return r.json()["detail"]


def test_missing_coordinate_columns_lists_what_was_found_and_says_what_to_name_them(client, db, forest):
    r = _import(client, forest, fx.csv_without_coordinate_columns())
    d = _d(r)
    assert r.status_code == 400 and d["code"] == "user_group.no_coordinates"
    assert "name, village" in d["message"] and '"latitude"' in d["message"] and d["message_np"]
    assert _row_count(db, forest[1].id) == 0


def test_utm_metres_are_converted_automatically_when_one_zone_fits_and_the_user_is_told(client, db, forest):
    """Was refused with 'not in Nepal' (UP-0); since UP-3.1 the zone is found by transforming it, and the conversion is reported."""
    r = _import(client, forest, fx.csv_with_utm_values_and_no_crs())
    assert r.status_code == 200
    f = [x for x in r.json()["findings"] if x["code"] == "coordinates.utm_converted"]
    assert len(f) == 1 and f[0]["severity"] == "info" and "zone 45N" in f[0]["title_en"] and f[0]["title_ne"]
    assert _row_count(db, forest[1].id) == 1
    assert 300 < _area_ha(db, forest[1].id) < 500  # the 2 km x 2 km square came out the right size, in the right place


def test_metres_that_fit_no_zone_are_still_refused_with_the_extent_and_the_fix(client, db, forest):
    r = _import(client, forest, fx.points_csv([(5, 5), (60000, 5), (60000, 70000), (5, 70000)], header="x,y"))
    d = _d(r)
    assert r.status_code == 400 and d["code"] == "user_group.outside_nepal" and "metres (UTM)" in d["message"]


def test_too_few_or_collinear_points_say_what_is_needed(client, forest):
    for data in (fx.csv_with_collinear_points(), fx.csv_with_two_points()):
        r = _import(client, forest, data)
        d = _d(r)
        assert r.status_code == 400 and d["code"] == "user_group.too_few_points" and "at least 3 points" in d["message"]


def test_empty_zip_without_shp_unsupported_extension_and_corrupt_workbook_are_plain_findings(client, forest):
    assert _d(_import(client, forest, fx.empty_file()))["code"] == "file.empty"
    z = _d(_import(client, forest, fx.zip_without_shp(), "ug.zip"))
    assert z["code"] == "user_group.no_shapefile" and ".prj" in z["message"] and z["message_np"]
    t = _d(_import(client, forest, b"hello", "ug.txt"))
    assert t["code"] == "file.wrong_type" and ".txt" in t["message"] and ".geojson" in t["message"]
    c = _d(_import(client, forest, fx.corrupt_xlsx(), "ug.xlsx"))
    assert c["code"] == "file.corrupt" and "password" in c["message"] and "zip file" not in c["message"]  # no library text


def test_columns_labelled_the_wrong_way_round_are_fixed_and_the_user_is_told(client, db, forest):
    """Was accepted without a word (UP-0); since UP-3.1 the response says what we corrected."""
    r = _import(client, forest, fx.csv_with_swapped_lat_lon())
    assert r.status_code == 200 and any(x["code"] == "coordinates.swapped_fixed" for x in r.json()["findings"])
    assert _row_count(db, forest[1].id) == 1


def test_a_group_nowhere_near_the_forest_is_saved_but_the_user_is_warned(client, db, forest):
    """Was accepted silently (UP-3 gap); now saved as uploaded with a warning that says how far it is."""
    far = fx.points_csv([(83.0, 27.0), (83.02, 27.0), (83.02, 27.02), (83.0, 27.02)])
    r = _import(client, forest, far)
    assert r.status_code == 200 and _row_count(db, forest[1].id) == 1
    f = [x for x in r.json()["findings"] if x["code"] == "user_group.far_from_forest"]
    assert len(f) == 1 and f[0]["severity"] == "warning" and "km from the forest" in f[0]["title_en"] and f[0]["fix_ne"]


def test_a_group_beside_the_forest_gets_no_warning(client, db, forest):
    headers, c = forest
    near = fx.points_csv([(85.55, 27.40), (85.57, 27.40), (85.57, 27.42), (85.55, 27.42)])
    r = _import(client, forest, near)
    assert r.status_code == 200 and not [x for x in r.json()["findings"] if x["code"] == "user_group.far_from_forest"]


def test_a_group_over_5000_ha_is_refused_and_the_existing_one_is_kept(client, db, forest):
    """Owner decision D2 (UP-1.3), was the defect 'saved first, reported afterwards'. Coded, bilingual, nothing saved or replaced."""
    headers, c = forest
    _draw(client, headers, c.id, [[85.55, 27.40], [85.57, 27.40], [85.57, 27.42], [85.55, 27.42]])
    small = _area_ha(db, c.id)
    assert 0 < small < 5000

    r = _import(client, forest, fx.csv_square(0.30))
    assert r.status_code == 400
    d = r.json()["detail"]
    assert d["code"] == "user_group.too_large" and "98,5" in d["message"] and "5,000" in d["message"] and d["message_np"]
    assert "nothing was changed" in d["message"]
    assert _row_count(db, c.id) == 1 and abs(_area_ha(db, c.id) - small) < 1  # the good group is still there, untouched
