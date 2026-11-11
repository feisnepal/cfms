"""UP-2 exit check (UPLOAD_EXPERIENCE_PLAN.md): every bad-file fixture, on every upload, answers with a plain-language finding that says how to fix it
in BOTH languages, and never with raw exception / SQL / library text."""
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

RAW_MARKERS = ("Traceback", "list index out of range", "UniqueViolation", "psycopg2", "not a zip file", "No columns to parse", "SQL", "KeyError", "NoneType")

HOUSEHOLD = {
    "empty": ("hh.csv", fx.empty_file()),
    "header_only": ("hh.csv", fx.header_only_csv("घर नंवर,थर")),
    "non_utf8": ("hh.csv", fx.non_utf8_csv()),
    "xlsx_named_csv": ("hh.csv", fx.csv_that_is_really_xlsx()),
    "txt": ("hh.txt", fx.household_csv([[1, "A", 1, 1]])),
    "corrupt_xlsx": ("hh.xlsx", fx.corrupt_xlsx()),
    "duplicate_house_no": ("hh.csv", fx.household_csv([[4, "G", 1, 1], [4, "G", 1, 1]])),
    "bad_rows": ("hh.csv", fx.household_csv([[1, "A", -1, 1], [2, "B", "x", 1]])),
}
USER_GROUP = {
    "no_coordinate_columns": ("ug.csv", fx.csv_without_coordinate_columns()),
    "metres_that_fit_no_zone": ("ug.csv", fx.points_csv([(5, 5), (60000, 5), (60000, 70000), (5, 70000)], header="x,y")),  # UTM metres are converted since UP-3
    "collinear": ("ug.csv", fx.csv_with_collinear_points()),
    "two_points": ("ug.csv", fx.csv_with_two_points()),
    "empty": ("ug.csv", fx.empty_file()),
    "zip_without_shp": ("ug.zip", fx.zip_without_shp()),
    "unsupported_extension": ("ug.txt", b"hello"),
    "corrupt_xlsx": ("ug.xlsx", fx.corrupt_xlsx()),
    "too_large": ("ug.csv", fx.csv_square(0.30)),
}
FIELD_INVENTORY = {
    "empty": ("fi.csv", fx.empty_file()),
    "header_only": ("fi.csv", fx.header_only_csv(fx.FI_HEADER)),
    "missing_longitude": ("fi.csv", fx.fi_missing_longitude()),
    "unsupported_extension": ("fi.txt", b"x"),
    "corrupt_xlsx": ("fi.xlsx", fx.corrupt_xlsx()),
}
STEM_MAPPING = {
    "empty": ("stem.csv", fx.empty_file()),
    "header_only": ("stem.csv", fx.header_only_csv(fx.STEM_HEADER)),
}


def _findings_of(resp) -> list[dict]:
    body = resp.json()
    if isinstance(body.get("detail"), dict):
        return body["detail"].get("findings", [])
    return body.get("findings", [])


def _assert_plain(resp, *, must_have_error_finding: bool) -> None:
    text = json.dumps(resp.json(), ensure_ascii=False)
    for marker in RAW_MARKERS:
        assert marker not in text, f"raw text leaked: {marker!r} in {text[:300]}"
    findings = _findings_of(resp)
    assert findings, f"no findings in {text[:300]}"
    for f in findings:
        if f["severity"] != "info":
            assert f["fix_en"].strip() and f["fix_ne"].strip(), f"{f['code']} has no fix in both languages"
        assert f["title_en"].strip() and f["title_ne"].strip()
    if must_have_error_finding:
        assert any(f["severity"] == "error" for f in findings) or resp.status_code >= 400


@pytest.mark.parametrize("name", sorted(HOUSEHOLD))
def test_household(name, client, db):
    from tests.test_household_upload_overwrite_branches import _owner

    headers, user = _owner(client, db)
    c = Calculation(user_id=user.id, forest_name=f"HH {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()
    fn, data = HOUSEHOLD[name]
    r = client.post(f"/api/household/calculations/{c.id}/upload", headers=headers, files={"file": (fn, data, "application/octet-stream")})
    _assert_plain(r, must_have_error_finding=name not in ("duplicate_house_no", "bad_rows"))


def _forest(client, db):
    headers, uid = _register(client)
    c = Calculation(id=uuid.uuid4(), user_id=uid, forest_name="exit", boundary_geom=shp_wkt.dumps(box(85.5, 27.35, 85.65, 27.45)),
                    status=CalculationStatus.PROCESSING, is_draft=True)
    db.add(c)
    db.commit()
    return headers, c


@pytest.mark.parametrize("name", sorted(USER_GROUP))
def test_user_group(name, client, db):
    headers, c = _forest(client, db)
    fn, data = USER_GROUP[name]
    r = client.post(f"/api/calculations/{c.id}/user-group/import", headers=headers, files={"file": (fn, data, "application/octet-stream")})
    assert r.status_code == 400
    if name == "too_large":  # the D2 refusal predates findings: it carries its own coded bilingual message
        d = r.json()["detail"]
        assert d["code"] == "user_group.too_large" and d["message"] and d["message_np"]
    else:
        _assert_plain(r, must_have_error_finding=True)


@pytest.mark.parametrize("name", sorted(FIELD_INVENTORY))
def test_field_inventory(name, client, db):
    headers, c = _forest(client, db)
    fn, data = FIELD_INVENTORY[name]
    r = client.post("/api/field-inventory/upload", headers=headers, data={"calculation_id": str(c.id), "mapping": "{}"}, files={"file": (fn, data, "text/csv")})
    _assert_plain(r, must_have_error_finding=True)


@pytest.mark.parametrize("name", sorted(STEM_MAPPING))
def test_stem_mapping(name, client, db):
    headers, c = _forest(client, db)
    fn, data = STEM_MAPPING[name]
    r = client.post("/api/inventory/confirm-mapping", headers=headers,
                    data={"mapping": json.dumps(fx.STEM_MAPPING), "save_preference": "false", "grid_spacing_meters": "10", "calculation_id": str(c.id)},
                    files={"file": (fn, data, "application/octet-stream")})
    assert r.status_code == 400
    _assert_plain(r, must_have_error_finding=True)
