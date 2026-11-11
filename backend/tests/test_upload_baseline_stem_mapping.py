"""UP-0 characterization: what the stem-mapping (individual tree) upload does TODAY (UPLOAD_EXPERIENCE_PLAN.md).

``..._today`` tests record known gaps, not wanted behaviour; the phase that closes a gap inverts its assertion.
Already good: unsupported-file errors are coded and bilingual (`code`, `message`, `message_np`), and the >20% outside-boundary rule rejects
quickly with counts. The gaps are what the error does NOT say.
"""
from __future__ import annotations

import json
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
        id=uuid.uuid4(), user_id=uid, forest_name="Stem baseline",
        boundary_geom=shp_wkt.dumps(box(85.5, 27.35, 85.65, 27.45)), status=CalculationStatus.PROCESSING, is_draft=True,
    )
    db.add(c)
    db.commit()
    return headers, c


def _confirm(client, forest, data: bytes, name: str = "stem.csv"):
    headers, c = forest
    return client.post(
        "/api/inventory/confirm-mapping", headers=headers,
        data={"mapping": json.dumps(fx.STEM_MAPPING), "save_preference": "false", "grid_spacing_meters": "10", "calculation_id": str(c.id)},
        files={"file": (name, data, "application/octet-stream")},
    )


def _errors(body):
    return [str(e.get("message")) for e in body.get("errors", [])]


def test_a_correct_file_is_ready_for_processing(client, forest):
    body = _confirm(client, forest, fx.stem_csv_good()).json()
    assert body["summary"]["ready_for_processing"] is True and body["summary"]["total_rows"] == 8
    assert body["boundary_check"]["out_of_boundary_count"] == 0


def test_preview_lists_the_columns_it_found(client, forest):
    headers, _ = forest
    r = client.post("/api/inventory/preview-mapping", headers=headers, files={"file": ("stem.csv", fx.stem_csv_good(), "text/csv")})
    assert r.status_code == 200 and r.json()["csv_columns"] == ["tree_id", "species", "dbh_cm", "height_m", "longitude", "latitude"]


def test_a_quarter_of_the_trees_outside_is_rejected_with_the_counts_but_no_map_today(client, forest):
    """>20% outside the boundary is rejected quickly with the numbers (good). GAP (UP-3): nothing shows WHERE the points fall."""
    body = _confirm(client, forest, fx.stem_csv_partly_outside(0.25, 20)).json()
    assert body["summary"]["ready_for_processing"] is False
    assert body["boundary_check"]["out_of_boundary_count"] == 5 and body["boundary_check"]["out_of_boundary_percentage"] == 25.0
    assert "25.0% of trees are outside the boundary" in _errors(body)[0]


def test_wrong_projection_and_swapped_coordinates_each_get_their_own_named_finding(client, forest):
    """Both used to say only 'verify coordinates, EPSG code...' (UP-0 gap). Since UP-3.1 each names the mistake and what to do."""
    utm = _confirm(client, forest, fx.stem_csv_wrong_crs_utm()).json()
    f = [x for x in utm["findings"] if x["code"] == "coordinates.looks_like_utm"]
    assert len(f) == 1 and "zone 45N" in f[0]["title_en"] and "EPSG:32645" in f[0]["fix_en"] and f[0]["fix_ne"]
    swapped = _confirm(client, forest, fx.stem_csv_swapped_xy()).json()
    g = [x for x in swapped["findings"] if x["code"] == "coordinates.looks_swapped"]
    assert len(g) == 1 and "longitude column" in g[0]["fix_en"]
    assert utm["summary"]["ready_for_processing"] is False and swapped["summary"]["ready_for_processing"] is False  # still stopped: we suggest, we do not guess


def test_an_empty_file_and_a_header_only_file_get_their_own_plain_finding(client, forest):
    """Both used to be called an 'unsupported format' (UP-0 gap). Now: empty = nothing in it; header only = no data rows."""
    empty = _confirm(client, forest, fx.empty_file())
    assert empty.status_code == 400 and empty.json()["detail"]["code"] == "file.empty"
    header = _confirm(client, forest, fx.header_only_csv(fx.STEM_HEADER))
    d = header.json()["detail"]
    assert header.status_code == 400 and d["code"] == "file.no_rows" and "data rows" in d["message"] and d["message_np"]


def test_diameters_in_millimetres_stop_the_upload_with_the_fix(client, forest):
    """UP-3.3: a whole column of 300-500 'cm' diameters is millimetres; it must not reach the volume tables."""
    rows = [(i, "Shorea robusta", 280 + i * 20, 15, round(85.55 + i * 0.0004, 6), round(27.40 + i * 0.0004, 6)) for i in range(1, 9)]
    body = _confirm(client, forest, fx.stem_csv(rows)).json()
    assert body["summary"]["ready_for_processing"] is False
    f = [x for x in body["findings"] if x["code"] == "field_inventory.dbh_in_mm"]
    assert len(f) == 1 and "tree diameters" in f[0]["title_en"] and f[0]["fix_ne"]
