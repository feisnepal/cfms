"""Forest details from the 07_Forest_Metadata template (POST /forest-metadata/import)."""
import io
import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation
from tests.integration.test_sampling_routing import _register

pytestmark = pytest.mark.usefixtures("forget_forests")


def _forest(db, uid):
    calc = Calculation(id=uuid.uuid4(), user_id=uid, forest_name="Meta", boundary_geom=shp_wkt.dumps(box(83.4, 27.4, 83.6, 27.6)), is_draft=True)
    db.add(calc)
    db.commit()
    return calc


def _post(client, headers, calc, csv):
    return client.post(f"/api/calculations/{calc.id}/forest-metadata/import", headers=headers, files={"file": ("meta.csv", io.BytesIO(csv.encode()), "text/csv")})


def test_import_fills_details_and_keeps_what_the_file_leaves_empty(client, db):
    headers, uid = _register(client)
    calc = _forest(db, uid)
    r = _post(client, headers, calc, "forest_name,group_name,district,ward,fy_start,fy_end\nRambhadevi,Rambhadevi CFUG,Kavre,५,2083/84,2092/93\n")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["forest_name"] == "Rambhadevi" and d["ward"] == "5" and d["fy_start"] == "2083/84"
    r = _post(client, headers, calc, "वनको नाम,जिल्ला\n,Sindhupalchok\n")  # Nepali headers; the empty name keeps the saved one
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["district"] == "Sindhupalchok" and d["forest_name"] == "Rambhadevi" and d["group_name"] == "Rambhadevi CFUG"


def test_end_before_start_and_empty_files_are_refused(client, db):
    headers, uid = _register(client)
    calc = _forest(db, uid)
    r = _post(client, headers, calc, "forest_name,fy_start,fy_end\nX,2092/93,2083/84\n")
    assert r.status_code == 422 and r.json()["detail"]["findings"][0]["code"] == "forest_metadata.fy_order"
    r = _post(client, headers, calc, "colour,size\nred,3\n")
    assert r.status_code == 422 and r.json()["detail"]["findings"][0]["code"] == "forest_metadata.nothing_found"


def test_the_example_row_is_not_a_record(client, db):
    headers, uid = _register(client)
    calc = _forest(db, uid)
    r = _post(client, headers, calc, "forest_name,district\nEXAMPLE - delete this row,Kavre\n")
    assert r.status_code == 422


def test_template_header_is_recognised_as_forest_details_by_its_columns():
    from app.services.upload import classify
    from app.services.upload.templates import csv_bytes, tables

    t = next(t for t in tables() if t.file_stem == "07_Forest_Metadata")
    cols = csv_bytes(t).decode("utf-8-sig").splitlines()[0].split(",")
    assert classify.classify_upload(columns=cols, filename="whatever.csv").best == "forest_metadata"
    # a household list shares 'ward' and must not be taken for it
    assert classify.classify_upload(columns=["household_head", "ward", "members"], filename="x.csv").best != "forest_metadata"


def test_template_sample_roundtrip_through_the_reader():
    import pandas as pd

    from app.services.upload.metadata_import import read_metadata

    df = pd.DataFrame([{"forest_name": "Rambhadevi", "district": "Kavre", "ward": 5.0}])
    values, errors, _ = read_metadata(df)
    assert not errors and values == {"forest_name": "Rambhadevi", "district": "Kavre", "ward": "5"}
