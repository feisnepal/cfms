"""UP-0 characterization: what the field inventory upload does TODAY with each wrong file (UPLOAD_EXPERIENCE_PLAN.md).

``..._today`` tests record known gaps, not wanted behaviour; the phase that closes a gap inverts its assertion.
Found while writing these: a valid tree-only file crashed the upload with a 500 (UnboundLocalError in the count check). Fixed in UP-0 and
pinned by ``test_a_tree_only_file_is_accepted``.
"""
from __future__ import annotations

import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation, CalculationStatus
from tests import upload_fixtures as fx
from tests.integration.test_user_group_journey import _register

pytestmark = pytest.mark.usefixtures("forget_forests")


@pytest.fixture()
def forest(client, db):
    headers, uid = _register(client)
    c = Calculation(
        id=uuid.uuid4(), user_id=uid, forest_name="FI baseline",
        boundary_geom=shp_wkt.dumps(box(85.5, 27.35, 85.65, 27.45)), status=CalculationStatus.PROCESSING, is_draft=True,
    )
    db.add(c)
    db.commit()
    return headers, c


def _upload(client, forest, data: bytes, name: str = "fi.csv"):
    headers, c = forest
    return client.post(
        "/api/field-inventory/upload", headers=headers, data={"calculation_id": str(c.id), "mapping": "{}"},
        files={"file": (name, data, "application/octet-stream")},
    )


def _messages(body, key):
    return [str(x.get("message")) for x in body.get(key, [])]


def test_a_tree_only_file_is_accepted(client, forest):
    """REGRESSION (fixed in UP-0): this crashed with UnboundLocalError because the count check sat outside its loop."""
    r = _upload(client, forest, fx.field_inventory_csv(fx.fi_good_rows()))
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s["ready_for_processing"] is True and s["total_rows"] == 5 and s["error_count"] == 0


def test_absent_stand_types_are_one_info_line_not_nine_warnings(client, forest):
    """Was 9 'Optional column ... not found' warnings for stand types the file does not have (UP-0 gap); one plain info line since UP-2."""
    body = _upload(client, forest, fx.field_inventory_csv(fx.fi_good_rows())).json()
    assert body["summary"]["warning_count"] == 0 and _messages(body, "warnings") == []
    f = [x for x in body["findings"] if x["code"] == "field_inventory.stand_types_found"]
    assert len(f) == 1 and f[0]["severity"] == "info" and f[0]["found"] == "tree" and f[0]["fix_ne"]


def test_a_missing_required_column_names_the_column_says_how_to_fix_it_and_has_both_languages(client, forest):
    """Was 'REQUIRED_COLUMN_MISSING: <Nepali>' (a developer code, no English); plain text in both languages since UP-2."""
    body = _upload(client, forest, fx.fi_missing_longitude()).json()
    assert body["summary"]["ready_for_processing"] is False
    e = body["errors"][0]
    assert "REQUIRED_COLUMN_MISSING" not in e["message"] and '"longitude"' in e["message"] and "Add a column" in e["message"] and "स्तम्भ" in e["message_np"]
    f = [x for x in body["findings"] if x["code"] == "field_inventory.required_column_missing"]
    assert f and f[0]["found"] == "longitude" and f[0]["severity"] == "error"


def test_coordinates_in_the_wrong_projection_are_rejected_and_the_zone_is_named(client, forest):
    """Was 'verify coordinates, EPSG code...' (UP-0); since UP-3.1 the finding says UTM zone 45N and what to do."""
    body = _upload(client, forest, fx.fi_utm_coordinates()).json()
    assert body["summary"]["ready_for_processing"] is False
    assert "outside the boundary" in _messages(body, "errors")[0]
    f = [x for x in body["findings"] if x["code"] == "coordinates.looks_like_utm"]
    assert len(f) == 1 and "zone 45N" in f[0]["title_en"] and "convert the file" in f[0]["fix_en"] and f[0]["fix_ne"]


def test_dbh_entered_in_millimetres_is_stopped_and_the_user_is_told_what_to_do(client, forest):
    """Was accepted without a word (UP-0 gap): every volume would have been ~100x too big. Stopped since UP-3.3."""
    body = _upload(client, forest, fx.fi_dbh_in_mm()).json()
    assert body["summary"]["ready_for_processing"] is False
    f = [x for x in body["findings"] if x["code"] == "field_inventory.dbh_in_mm"]
    assert len(f) == 1 and "millimetres" in f[0]["title_en"] and "divide by 10" in f[0]["fix_en"] and f[0]["fix_ne"]
    assert "millimetres" in body["errors"][-1]["message"] and body["errors"][-1]["message_np"]


def test_a_header_only_file_is_not_ready_for_processing_and_says_so(client, forest):
    """Was declared 'ready for processing' (UP-0 defect); fixed in UP-2."""
    body = _upload(client, forest, fx.header_only_csv(fx.FI_HEADER)).json()
    assert body["summary"]["total_rows"] == 0 and body["summary"]["ready_for_processing"] is False
    assert any(x["code"] == "file.no_rows" for x in body["findings"]) and body["errors"][0]["message_np"]


def test_an_empty_file_gets_a_plain_finding(client, forest):
    r = _upload(client, forest, fx.empty_file())
    d = r.json()["detail"]
    assert r.status_code == 400 and d["code"] == "file.empty" and "No columns to parse" not in str(d)


def test_a_wrong_extension_and_a_corrupt_workbook_are_plain_findings(client, forest):
    bad_ext = _upload(client, forest, b"x", "fi.txt").json()["detail"]
    assert bad_ext["code"] == "file.wrong_type" and ".txt" in bad_ext["message"]
    corrupt = _upload(client, forest, fx.corrupt_xlsx(), "fi.xlsx").json()["detail"]
    assert corrupt["code"] == "file.corrupt" and "password" in corrupt["message"]


def test_misspelled_species_are_reported_with_what_we_read_them_as(client, db, forest):
    """UP-3.4. Was accepted without a word (UP-0 gap). A near-miss matched by similarity is shown to the user: 'Shorea robustta -> Shorea robusta'."""
    from app.models.inventory import TreeSpeciesCoefficient

    seeded = None
    if not db.query(TreeSpeciesCoefficient).filter(TreeSpeciesCoefficient.scientific_name == "Shorea robusta").first():
        seeded = TreeSpeciesCoefficient(scientific_name="Shorea robusta", local_name="Sal", species_code=1, is_active=True)
        db.add(seeded)
        db.commit()
    try:
        body = _upload(client, forest, fx.fi_misspelled_species()).json()
    finally:
        if seeded is not None:  # the test database is shared: leave the species table as we found it
            db.delete(seeded)
            db.commit()
    f = [x for x in body["findings"] if x["code"] == "field_inventory.species_suggestion"]
    assert len(f) == 1 and f[0]["severity"] == "warning"
    assert "Shorea robustta → Shorea robusta" in f[0]["title_en"] and "spelling" in f[0]["fix_en"] and f[0]["fix_ne"]
    assert body["summary"]["ready_for_processing"] is True  # a suggestion, never a block
    assert not [w for w in body["warnings"] if str(w.get("type", "")).endswith("_species_validation")]  # the finding replaces the vague warning


def test_a_file_whose_trees_fall_outside_the_forest_comes_with_a_preview(client, forest):
    """UP-3.5: points, the forest boundary and how the numbers were read; nothing to draw when nothing is wrong."""
    body = _upload(client, forest, fx.fi_utm_coordinates()).json()
    assert body["preview"]["assumed"] == "utm_zone_45" and len(body["preview"]["points"]) == 5 and body["preview"]["boundary"]
    ok = _upload(client, forest, fx.field_inventory_csv(fx.fi_good_rows())).json()
    assert "preview" not in ok


def test_columns_under_other_names_are_read_and_the_user_is_told_which(client, forest):
    """UP-3.2: 'Block', 'Plot No', 'Lon', 'Lat' used to be 'required column missing'; now read as the template's names and reported."""
    header = "Block,Plot No,Lon,Lat,tree_species_scientific,tree_dbh_cm,tree_height_m"
    body = _upload(client, forest, fx.field_inventory_csv(fx.fi_good_rows(), header=header)).json()
    assert body["summary"]["ready_for_processing"] is True and body["errors"] == []
    f = [x for x in body["findings"] if x["code"] == "field_inventory.columns_renamed"]
    assert len(f) == 1 and f[0]["severity"] == "info" and "Lon → longitude" in f[0]["title_en"] and f[0]["fix_ne"]


def test_a_column_we_cannot_place_is_still_reported_missing(client, forest):
    header = "Block,Plot No,Lon,Place,tree_species_scientific,tree_dbh_cm,tree_height_m"
    body = _upload(client, forest, fx.field_inventory_csv(fx.fi_good_rows(), header=header)).json()
    assert body["summary"]["ready_for_processing"] is False
    assert any(x["code"] == "field_inventory.required_column_missing" and x["found"] == "latitude" for x in body["findings"])


def test_heights_in_feet_are_flagged_but_do_not_stop_the_upload(client, forest):
    rows = [(a, b, c, d, e, f, g * 3.28 + 20) for a, b, c, d, e, f, g in fx.fi_good_rows()]
    body = _upload(client, forest, fx.field_inventory_csv(rows)).json()
    f = [x for x in body["findings"] if x["code"] == "field_inventory.height_in_feet"]
    assert len(f) == 1 and f[0]["severity"] == "warning" and f[0]["fix_ne"]
    assert body["summary"]["ready_for_processing"] is True
