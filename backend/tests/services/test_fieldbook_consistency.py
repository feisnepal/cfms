"""Every field book output says the same thing.

The tab (API), CSV, Excel, GeoJSON, GPX and the OP document table (`{{fieldbook_points}}`) each used to build their own
row and drifted (a different nearest-feature search buffer, a truncated vs a rounded distance, GeoJSON and GPX without
the nearby feature, three columns that all repeated the units). They now all come from `fieldbook_record.point_record`.
This generates ONE field book and checks every format against that one row.
"""
import csv
import io
import uuid
import xml.etree.ElementTree as ET

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.fieldbook import Fieldbook
from app.models.forest_block import ForestBlock
from app.services.export import (
    export_fieldbook_csv, export_fieldbook_excel, export_fieldbook_geojson, export_fieldbook_gpx,
)
from app.services.fieldbook import generate_fieldbook_points
from app.services.fieldbook_record import COLUMNS, HEADERS, KEYS, csv_text, merge_remark, point_record, topography_for
from app.services.operational_plan.data_collector import _fetch_fieldbook_data

NS, NL, S = 83.5, 27.5, 0.01
HEADER_OF = dict(COLUMNS)


def _login(client, db):
    from app.models.user import User

    email = f"cons-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "Consistency Tester"})
    r = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, db.query(User).filter(User.email == email).first()


@pytest.fixture()
def stub_topography(monkeypatch):
    """The test database has no ridge/river data. A stub that finds a river for the northern half of the forest lets
    the nearby-feature columns be compared across formats too (and leaves the southern half blank)."""
    import app.utils.geospatial_vector_optimized as geo

    monkeypatch.setattr(geo, "preclip_topographic_features", lambda **kw: {"ridges": [], "rivers": [object()]})

    def nearest(db, longitude, latitude, clipped_features, **kw):
        if latitude > NL + S:
            return {"feature_name": "Test Khola", "feature_type": "river", "distance_meters": 42.6, "direction": "NE"}
        return None

    monkeypatch.setattr(geo, "find_nearest_topographic_feature_optimized", nearest)


@pytest.fixture()
def book(client, db, stub_topography):
    headers, user = _login(client, db)
    a, b, c = box(NS, NL, NS + S, NL + 2 * S), box(NS + S, NL + S, NS + 2 * S, NL + 2 * S), box(NS + S, NL, NS + 2 * S, NL + S)
    calc = Calculation(
        user_id=user.id, forest_name=f"CONS {uuid.uuid4().hex[:6]}", structure_locked=False, is_draft=False,
        boundary_geom=from_shape(box(NS, NL, NS + 2 * S, NL + 2 * S), srid=4326),
        result_data={"sub_areas": [{
            "id": str(uuid.uuid4()), "name": "Pond", "category": "water", "is_excluded": True, "isExcluded": True,
            "geometry": box(NS + 0.003, NL + 0.012, NS + 0.006, NL + 0.016).__geo_interface__, "area_hectares": 1.0,
        }]},
    )
    db.add(calc)
    db.flush()
    for i, (g, n) in enumerate(((a, "Block-A"), (b, "Block-B"), (c, "Block-C")), start=1):
        db.add(ForestBlock(calculation_id=calc.id, name=n, block_name=n, geometry=from_shape(g, srid=4326),
                           area_hectares=100.0, area_sqm=1_000_000.0, index=i, is_compartment=False, division_level=1,
                           is_locked=False, child_count=0))
    db.commit()
    generate_fieldbook_points(db, calc.id, interpolation_distance=50.0, extract_elevation=False)
    # a couple of surveyed values so the optional columns are exercised: verified, elevation, UTM
    rows = db.query(Fieldbook).filter(Fieldbook.calculation_id == calc.id).order_by(Fieldbook.point_number).all()
    rows[0].is_verified = True
    rows[0].elevation = 0                 # a real zero must survive every format
    rows[1].elevation = 1234.567
    rows[1].easting_utm, rows[1].northing_utm = 123456.789, 3041234.5
    db.commit()
    return headers, calc, rows


def _expected(db, calc, rows):
    topo = topography_for(db, calc.id, rows)
    return [point_record(p, topo.get(p.id)) for p in rows]


def _blank(v):
    return None if v in (None, "") else v


# --------------------------------------------------------------------------- each format against the one row

def test_csv_matches_the_canonical_row(db, book):
    _, calc, rows = book
    exp = _expected(db, calc, rows)
    table = list(csv.reader(io.StringIO(export_fieldbook_csv(db, calc.id).decode("utf-8"))))
    assert table[0] == HEADERS
    assert len(table) - 1 == len(exp)
    for cells, rec in zip(table[1:], exp):
        for key, cell in zip(KEYS, cells):
            assert cell == csv_text(key, rec[key]), (rec["point"], key)


def test_excel_matches_the_canonical_row(db, book):
    from openpyxl import load_workbook
    _, calc, rows = book
    exp = _expected(db, calc, rows)
    ws = load_workbook(io.BytesIO(export_fieldbook_excel(db, calc.id)))["Points"]
    assert [c.value for c in ws[1]] == HEADERS
    for xrow, rec in zip(ws.iter_rows(min_row=2), exp):
        for key, cell in zip(KEYS, xrow):
            assert _blank(cell.value) == _blank(rec[key]), (rec["point"], key, cell.value, rec[key])


def test_geojson_matches_the_canonical_row(db, book):
    _, calc, rows = book
    exp = _expected(db, calc, rows)
    feats = [f for f in export_fieldbook_geojson(db, calc.id)["features"] if f["properties"]["layer"] == "point"]
    assert len(feats) == len(exp)
    for f, rec in zip(feats, exp):
        assert {k: f["properties"][k] for k in KEYS} == dict(rec)
        assert f["geometry"]["coordinates"] == [rec["longitude"], rec["latitude"]]


def test_api_list_matches_the_canonical_row(client, db, book):
    headers, calc, rows = book
    exp = _expected(db, calc, rows)
    body = client.get(f"/api/calculations/{calc.id}/fieldbook?include_topographic=true", headers=headers).json()
    assert len(body["points"]) == len(exp)
    for p, rec in zip(body["points"], exp):
        assert p["point_label"] == rec["point"] and p["point_type"] == rec["type"]
        assert (p["boundary_class"] or None) == rec["boundary"]
        assert (p["junction_degree"] if p["is_junction"] else None) == rec["junction"]
        assert p["remarks"] == rec["remarks"] and p["next_point_label"] == rec["next_point"] and p["line_id"] == rec["line"]
        assert p["sub_area_name"] == rec["sub_area"] and p["sub_area_category"] == rec["sub_area_category"]
        for api_key, key in (("latitude", "latitude"), ("longitude", "longitude"), ("azimuth_to_next", "azimuth"),
                             ("distance_to_next", "distance"), ("elevation", "elevation")):
            assert (None if p[api_key] is None else round(float(p[api_key]), 7)) == (
                None if rec[key] is None else round(rec[key], 7)), (rec["point"], key)
        # the nearby feature in the TAB is the same one the files carry (same search buffer, same rounding)
        assert p["nearest_feature"] == rec["nearest_feature"]
        assert p["feature_type"] == rec["nearest_feature_type"]
        assert p["distance_to_feature"] == rec["nearest_feature_distance_m"]
        assert p["direction_to_feature"] == rec["nearest_feature_direction"]


def test_gpx_carries_the_canonical_row_in_its_name_elevation_and_description(db, book):
    _, calc, rows = book
    exp = _expected(db, calc, rows)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    wpts = ET.fromstring(export_fieldbook_gpx(db, calc.id)).findall("g:wpt", ns)
    assert len(wpts) == len(exp)
    for w, rec in zip(wpts, exp):
        assert w.find("g:name", ns).text == rec["point"] and w.find("g:type", ns).text == rec["type"]
        assert float(w.get("lat")) == rec["latitude"] and float(w.get("lon")) == rec["longitude"]
        ele = w.find("g:ele", ns)
        assert (None if ele is None else float(ele.text)) == rec["elevation"]
        desc = w.find("g:desc", ns).text or ""
        for needle in (rec["remarks"], rec["line"] and f"Line: {rec['line']}", rec["next_point"] and f"Next: {rec['next_point']}",
                       rec["sub_area"] and f"Sub-area: {rec['sub_area']}", rec["nearest_feature"] and f"Nearest: {rec['nearest_feature']}"):
            if needle:
                assert needle in desc, (rec["point"], needle, desc)
        if rec["azimuth"] is not None:
            assert f"Azimuth: {rec['azimuth']:.2f}" in desc and f"Distance: {rec['distance']:.2f}" in desc
        if rec["nearest_feature_distance_m"] is not None:
            assert f", {rec['nearest_feature_distance_m']}m" in desc
        assert ("Verified" in desc) == (rec["verified"] == "Yes")


def test_the_op_document_table_agrees_on_every_value_it_shows(db, book):
    _, calc, rows = book
    exp = _expected(db, calc, rows)
    table = _fetch_fieldbook_data(db, calc.id)["points"]
    assert len(table) == len(exp)
    dev = str.maketrans("०१२३४५६७८९", "0123456789")
    for row, rec in zip(table, exp):
        assert row["बिन्दु_नं"] == rec["point"]
        assert row["प्रकार"] == ("V" if rec["type"] == "vertex" else "I")
        assert row["कैफियत"] == (rec["remarks"] or "")
        assert (None if row["उप-क्षेत्र"] == "-" else row["उप-क्षेत्र"].split(" (")[0]) == rec["sub_area"]
        assert float(row["देशान्तर"].translate(dev)) == pytest.approx(rec["longitude"], abs=1e-7)
        assert float(row["अक्षांश"].translate(dev)) == pytest.approx(rec["latitude"], abs=1e-7)
        for key, k in (("अजिमुथ", "azimuth"), ("दुरी_मि", "distance")):
            if rec[k] is None:
                assert row[key] == "-"
            else:
                assert float(row[key]) == pytest.approx(rec[k], abs=0.051)     # one decimal in the printed table
    # a real elevation of 0 is shown as a number, not a dash
    assert table[0]["उचाइ_मि"] != "-"


def test_the_formats_agree_with_each_other_pairwise(db, book):
    """CSV, Excel and GeoJSON are checked against the canonical row above; here they are compared directly."""
    from openpyxl import load_workbook
    _, calc, _ = book
    csv_rows = list(csv.reader(io.StringIO(export_fieldbook_csv(db, calc.id).decode("utf-8"))))[1:]
    xl = list(load_workbook(io.BytesIO(export_fieldbook_excel(db, calc.id)))["Points"].iter_rows(min_row=2, values_only=True))
    gj = [f for f in export_fieldbook_geojson(db, calc.id)["features"] if f["properties"]["layer"] == "point"]
    for c, x, f in zip(csv_rows, xl, gj):
        for i, key in enumerate(KEYS):
            assert csv_text(key, _blank(x[i])) == c[i] == csv_text(key, _blank(f["properties"][key])), (c[0], key)


# --------------------------------------------------------------------------- one column is enough

def test_the_remark_names_every_unit_a_point_separates(db, book):
    """Why `Block` and `Separates` could go: whatever they said, the remark already says."""
    _, calc, rows = book
    for p in rows:
        for unit in p.adjacent_units or []:
            assert unit in (p.remarks or ""), (p.point_label, unit, p.remarks)
        assert (p.remarks or "").startswith(p.boundary_class)


def test_no_output_has_a_separate_block_or_units_column(db, book):
    from openpyxl import load_workbook
    _, calc, _ = book
    table = list(csv.reader(io.StringIO(export_fieldbook_csv(db, calc.id).decode("utf-8"))))
    ws = load_workbook(io.BytesIO(export_fieldbook_excel(db, calc.id)))["Points"]
    for headers in (table[0], [c.value for c in ws[1]]):
        assert not any(w in h for h in headers for w in ("Block", "Adjacent", "Separates"))
        assert "कैफियत (Remarks)" in headers
    keys = set(next(f for f in export_fieldbook_geojson(db, calc.id)["features"] if f["properties"]["layer"] == "point")["properties"])
    assert not keys & {"block_name", "block_number", "adjacent_units"}
    assert "ब्लकको_नाम" not in _fetch_fieldbook_data(db, calc.id)["points"][0]


def test_the_nearby_feature_appears_in_every_format_or_in_none_for_a_point(db, book):
    """GeoJSON and GPX used to leave the nearby ridge/river out entirely."""
    _, calc, rows = book
    exp = _expected(db, calc, rows)
    with_feature = [r for r in exp if r["nearest_feature"]]
    without = [r for r in exp if not r["nearest_feature"]]
    assert with_feature and without, "the stub must give some points a feature and others none"
    assert all(r["nearest_feature_distance_m"] == 43 for r in with_feature)           # 42.6 rounded, not truncated to 42
    assert all(r["nearest_feature_type"] is None and r["nearest_feature_direction"] is None for r in without)
    gj = {f["properties"]["point"]: f["properties"] for f in export_fieldbook_geojson(db, calc.id)["features"] if f["properties"]["layer"] == "point"}
    assert all(gj[r["point"]]["nearest_feature"] == "Test Khola" for r in with_feature)


# --------------------------------------------------------------------------- a field note never removes the units

def test_a_field_note_is_added_after_the_generated_text_never_instead_of_it(db, book):
    _, _, rows = book
    p = next(r for r in rows if r.boundary_class == "outer" and r.adjacent_units)
    base = p.remarks
    assert merge_remark(p, "stone pillar") == f"{base}; stone pillar"
    assert merge_remark(p, f"{base}; stone pillar") == f"{base}; stone pillar"       # an edited full copy is kept as is
    assert merge_remark(p, "") == base and merge_remark(p, None) == base             # clearing restores the generated text
    assert merge_remark(p, "  boundary pillar  ").startswith(base)


def test_a_point_from_an_older_book_keeps_a_plain_note(db):
    class Old:
        boundary_class = None
        adjacent_units = None
        junction_degree = None
        sub_area_name = None
    assert merge_remark(Old(), "hello") == "hello" and merge_remark(Old(), "") is None
