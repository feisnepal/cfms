"""POINT IMPORT → BOUNDARY plan (B-1…B-7) — boundary point-file flow tests.

Exercises at the API boundary:
  - POST /workspace/{id}/polygon-from-points with target_type='boundary' writes
    the forest boundary via the updateBoundaryGeometry path (boundary_geom,
    result_data.geometry, geodesic area, single-block auto-create).
  - POST /workspace/{id}/boundary/preview-mapping returns mapped columns,
    detected CRS, Nepal-extent-validated 4326 points, and needs_user_input.
  - convert-to-builtin with target_type='boundary' (latent G4) sets the boundary.
  - B-4: Nepali lat/lon aliases recognized by CoordinateDetector + file_processor.
"""
import io
import uuid

import pytest

from shapely import wkt as shp_wkt
from shapely.geometry import box, shape
from sqlalchemy import func

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock

pytestmark = pytest.mark.usefixtures("forget_forests")  # fixed coordinates + committed rows: see conftest


def _register_user(client):
    email = f"bnd-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Boundary Flow",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _make_calc(db, user_id, forest_name="Boundary Forest"):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name=forest_name,
        boundary_geom=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
        result_data={},
        geometry_version=0,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


SQUARE = [[83.50, 27.50], [83.60, 27.50], [83.60, 27.55], [83.50, 27.55]]
PENTAGON = [[83.50, 27.50], [83.60, 27.50], [83.65, 27.55], [83.55, 27.60], [83.50, 27.55]]


# ---------- B-1: polygon-from-points boundary target ----------

def test_boundary_target_ordered_writes_boundary(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    db.expire_all()

    resp = client.post(
        f"/api/workspace/{calc.id}/polygon-from-points",
        headers=headers,
        json={"points": PENTAGON, "target_type": "boundary", "name": "Forest Boundary"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["target_type"] == "boundary"
    assert body["feature_id"] is None

    db.expire_all()
    db.refresh(calc)
    assert calc.boundary_geom is not None, "boundary_geom not written"
    from geoalchemy2.shape import to_shape
    assert to_shape(calc.boundary_geom).area > 1e-9
    assert shape(calc.result_data["geometry"]).area > 1e-9
    assert calc.result_data["area_hectares"] > 0
    assert calc.geometry_version == 1


def test_boundary_target_single_block_autocreate(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    db.expire_all()

    resp = client.post(
        f"/api/workspace/{calc.id}/polygon-from-points",
        headers=headers,
        json={"points": SQUARE, "target_type": "boundary", "name": "Forest Boundary"},
    )
    assert resp.status_code == 200, resp.text

    db.expire_all()
    blocks = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment != True,
        ForestBlock.division_level == 1,
    ).all()
    assert len(blocks) == 1
    assert blocks[0].area_hectares > 0


def test_boundary_target_collinear_falls_back_to_hull(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    db.expire_all()

    # A nearly-degenerate ring falls back to the shared case-D hull engine; a
    # perfect straight line cannot form a polygon and must be rejected clearly.
    resp = client.post(
        f"/api/workspace/{calc.id}/polygon-from-points",
        headers=headers,
        json={"points": PENTAGON, "target_type": "boundary"},
    )
    assert resp.status_code == 200, resp.text

    resp_line = client.post(
        f"/api/workspace/{calc.id}/polygon-from-points",
        headers=headers,
        json={"points": [[83.0, 27.0], [83.1, 27.0], [83.2, 27.0], [83.3, 27.0], [83.4, 27.0]],
              "target_type": "boundary"},
    )
    assert resp_line.status_code in (400, 500), resp_line.text


def test_boundary_target_too_few_points(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    db.expire_all()

    resp = client.post(
        f"/api/workspace/{calc.id}/polygon-from-points",
        headers=headers,
        json={"points": [[83.5, 27.5], [83.6, 27.5]], "target_type": "boundary"},
    )
    assert resp.status_code in (400, 422), resp.text


# ---------- B-2: preview-mapping endpoint ----------

def _preview(client, calc_id, headers, csv_text, filename="pts.csv", crs_epsg=None, mapping=None, fix_swap=None):
    data = {}
    if crs_epsg is not None:
        data["crs_epsg"] = str(crs_epsg)
    if mapping is not None:
        data["mapping"] = mapping
    if fix_swap is not None:
        data["fix_swap"] = str(fix_swap)
    return client.post(
        f"/api/workspace/{calc_id}/boundary/preview-mapping",
        headers=headers,
        data=data,
        files={"file": (filename, io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
    )


def test_preview_mapping_english_headers(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    csv_text = "longitude,latitude\n83.5,27.5\n83.6,27.6\n83.7,27.55\n"

    resp = _preview(client, calc.id, headers, csv_text)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["needs_user_input"] is False
    assert body["detected_crs"] == 4326
    assert len(body["points_4326"]) == 3
    assert body["required_columns"] == ["LONGITUDE", "LATITUDE"]
    assert body["mapping"].get("longitude") == "LONGITUDE"
    assert body["mapping"].get("latitude") == "LATITUDE"


def test_preview_mapping_nepali_headers_and_digits(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    csv_text = "देशान्तर,अक्षांश\n८३.५,२७.५\n८३.६,२७.६\n"

    resp = _preview(client, calc.id, headers, csv_text)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_user_input"] is False, body
    mapped = body["mapping"]
    assert "देशान्तर" in mapped and mapped["देशान्तर"] == "LONGITUDE"
    assert "अक्षांश" in mapped and mapped["अक्षांश"] == "LATITUDE"
    assert len(body["points_4326"]) == 2
    assert 80.0 <= body["points_4326"][0]["lng"] <= 88.3


def test_preview_mapping_utm_with_override(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    # UTM Zone 44N coordinates inside NEPAL_BOUNDS['utm_44n'].
    csv_text = "x,y\n550000,3090000\n560000,3100000\n570000,3110000\n"

    resp = _preview(client, calc.id, headers, csv_text, crs_epsg=32644)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_user_input"] is False
    assert body["detected_crs"] == 32644
    pts = body["points_4326"]
    assert len(pts) == 3
    for p in pts:
        assert 80.0 <= p["lng"] <= 88.3, p
        assert 26.3 <= p["lat"] <= 30.5, p


def test_preview_mapping_over_50_rows_not_truncated(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    rows = [f"83.{i%10+1},27.{i%10+1}" for i in range(120)]
    csv_text = "longitude,latitude\n" + "\n".join(rows) + "\n"

    resp = _preview(client, calc.id, headers, csv_text)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 120
    assert len(body["points_4326"]) == 120


def test_preview_mapping_out_of_nepal_extent(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    csv_text = "longitude,latitude\n100,10\n83.6,27.6\n"

    resp = _preview(client, calc.id, headers, csv_text)
    assert resp.status_code == 400, resp.text
    assert "Nepal" in resp.json()["detail"]


def test_preview_mapping_needs_user_input_and_recall(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    csv_text = "foo,bar\n83.5,27.5\n83.6,27.6\n"

    resp = _preview(client, calc.id, headers, csv_text)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_user_input"] is True
    assert body["points_4326"] == []
    assert body["sample_data"]

    resp2 = _preview(client, calc.id, headers, csv_text,
                     mapping='{"foo": "LONGITUDE", "bar": "LATITUDE"}')
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    assert body2["needs_user_input"] is False
    assert len(body2["points_4326"]) == 2


def test_preview_mapping_dms_coordinates(client, db):
    """DMS cells ('83°30'00\"') must decode, not 500. Regression for the
    unhandled ValueError from df.to_numpy(dtype=float)."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    csv_text = "longitude,latitude\n83°30'00\",27°30'00\"\n83°36'00\",27°36'00\"\n"

    resp = _preview(client, calc.id, headers, csv_text)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    pts = body["points_4326"]
    assert len(pts) == 2
    assert abs(pts[0]["lng"] - 83.5) < 1e-6
    assert abs(pts[0]["lat"] - 27.5) < 1e-6
    assert abs(pts[1]["lng"] - 83.6) < 1e-6
    assert abs(pts[1]["lat"] - 27.6) < 1e-6


def test_preview_mapping_swapped_lat_lon_asks_then_fixes(client, db):
    """Latitude values in the longitude column (and vice versa) first ask the
    user (swap_detected + swap_message, no points). With fix_swap confirmed the
    values are swapped back automatically and normal 4326 points returned.
    Regression: the swap detection result used to be discarded (confusing
    raw-bounds error / boundary rendered at the edge of the globe)."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    csv_text = "longitude,latitude\n27.5,83.5\n27.6,83.6\n27.55,83.55\n"

    # 1. First call -> ask the user, do not guess.
    resp = _preview(client, calc.id, headers, csv_text)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["swap_detected"] is True, body
    assert body["points_4326"] == [], body
    assert "swapped" in body["swap_message"].lower(), body
    assert "swap longitude and latitude" in body["swap_message"].lower(), body

    # 2. User confirms -> auto-fix swaps values back and maps normally.
    resp = _preview(client, calc.id, headers, csv_text, fix_swap=True)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("swapped_fixed") is True, body
    assert body["needs_user_input"] is False, body
    pts = body["points_4326"]
    assert len(pts) == 3, body
    for p in pts:
        assert 80.0 <= p["lng"] <= 88.3, p
        assert 26.3 <= p["lat"] <= 30.5, p


def test_preview_mapping_unparseable_cell_is_400(client, db):
    """A non-numeric, non-DMS cell must return a clear 400 (not a 500)."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    csv_text = "longitude,latitude\n83.5,abc\n83.6,27.6\n"

    resp = _preview(client, calc.id, headers, csv_text)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "Could not parse latitude coordinates" in detail
    assert "row 2" in detail


def test_preview_mapping_empty_extra_column_is_200(client, db):
    """NaN cells in non-coordinate columns must not break JSON serialization.
    Regression for the 'Out of range float values are not JSON compliant: nan'
    500 (sample_data must replace NaN with None before serialization)."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    csv_text = "longitude,latitude,species\n83.5,27.5,Sal\n83.6,27.6,\n83.7,27.55,Pine\n"

    resp = _preview(client, calc.id, headers, csv_text)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 3
    assert body["sample_data"][1]["species"] is None
    assert len(body["points_4326"]) == 3


# ---------- B-7: convert-to-builtin boundary target ----------

def test_convert_to_builtin_boundary_sets_boundary(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)

    # Import a custom polygon layer first.
    import json as _json
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "imported"},
            "geometry": {"type": "Polygon", "coordinates": [[[83.50, 27.50], [83.51, 27.50], [83.51, 27.51], [83.50, 27.51], [83.50, 27.50]]]},
        }],
    }
    upload = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        data={"purpose": "custom", "crs_epsg": "4326"},
        files={"file": ("poly.geojson", io.BytesIO(_json.dumps(fc).encode("utf-8")), "application/geo+json")},
    )
    assert upload.status_code in (200, 201), upload.text
    layer_id = upload.json().get("id")
    assert layer_id, upload.text

    resp = client.post(
        f"/api/workspace/{calc.id}/import-layers/{layer_id}/convert-to-builtin",
        headers=headers,
        json={"target_type": "boundary"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["target_type"] == "boundary"
    assert body["area_hectares"] > 0

    db.expire_all()
    db.refresh(calc)
    assert calc.boundary_geom is not None
    assert shape(calc.result_data["geometry"]).area > 1e-9


def test_convert_to_builtin_point_layer_becomes_boundary(client, db):
    """Assign-purpose-later: a custom point layer converted to 'boundary' must be
    polygonised (points -> hull -> polygon) and stored as the forest boundary.

    Regression for the 500 where raw points were handed to derive_boundary_from_polygons
    (unary_union of points = MultiPoint, zero area) and the auto-created block then
    violated forest_blocks CHECK (area_hectares > 0)."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id, forest_name="Point Forest")

    import json as _json
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "p1"},
             "geometry": {"type": "Point", "coordinates": [83.50, 27.50]}},
            {"type": "Feature", "properties": {"name": "p2"},
             "geometry": {"type": "Point", "coordinates": [83.60, 27.50]}},
            {"type": "Feature", "properties": {"name": "p3"},
             "geometry": {"type": "Point", "coordinates": [83.60, 27.55]}},
            {"type": "Feature", "properties": {"name": "p4"},
             "geometry": {"type": "Point", "coordinates": [83.50, 27.55]}},
        ],
    }
    upload = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        data={"purpose": "custom", "crs_epsg": "4326"},
        files={"file": ("pts.geojson", io.BytesIO(_json.dumps(fc).encode("utf-8")), "application/geo+json")},
    )
    assert upload.status_code in (200, 201), upload.text
    layer_id = upload.json().get("id")
    assert layer_id, upload.text

    resp = client.post(
        f"/api/workspace/{calc.id}/import-layers/{layer_id}/convert-to-builtin",
        headers=headers,
        json={"target_type": "boundary"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["area_hectares"] > 0, body

    db.expire_all()
    db.refresh(calc)
    from geoalchemy2.shape import to_shape as _t_shape
    bnd = _t_shape(calc.boundary_geom)
    assert "Polygon" in bnd.geom_type, bnd.geom_type
    assert bnd.area > 1e-9
    assert shape(calc.result_data["geometry"]).area > 1e-9

    blocks = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment != True,
        ForestBlock.division_level == 1,
    ).all()
    assert len(blocks) == 1
    assert blocks[0].area_hectares > 0


def test_convert_to_builtin_point_layer_to_blocks_skipped_cleanly(client, db):
    """Zero-area point geometry converted to blocks must be skipped (with a
    warning counter), never inserted into forest_blocks — no DB check violation /
    500. Regression guard alongside the boundary polygonise fix."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)

    import json as _json
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "sample"},
             "geometry": {"type": "Point", "coordinates": [83.50, 27.50]}},
        ],
    }
    upload = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        data={"purpose": "custom", "crs_epsg": "4326"},
        files={"file": ("one.geojson", io.BytesIO(_json.dumps(fc).encode("utf-8")), "application/geo+json")},
    )
    assert upload.status_code in (200, 201), upload.text
    layer_id = upload.json().get("id")
    assert layer_id, upload.text

    # purpose gate (line ~1477) rejects custom -> blocks with a clear 400, so a
    # point layer cannot even reach the insert path for blocks today.
    resp = client.post(
        f"/api/workspace/{calc.id}/import-layers/{layer_id}/convert-to-builtin",
        headers=headers,
        json={"target_type": "blocks"},
    )
    assert resp.status_code == 400, resp.text
    assert "cannot be converted to 'blocks'" in resp.text


def test_convert_to_builtin_closed_line_layer_becomes_boundary(client, db):
    """A closed line ring converted to 'boundary' snaps to a polygon (case B of
    the shared engine) and becomes the forest boundary. Open lines cannot form a
    closed boundary and are rejected with a clear 400."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)

    import json as _json
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "ring"},
            "geometry": {
                "type": "LineString",
                "coordinates": [[83.50, 27.50], [83.60, 27.50], [83.60, 27.55], [83.50, 27.55], [83.50, 27.50]],
            },
        }],
    }
    upload = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        data={"purpose": "custom", "crs_epsg": "4326"},
        files={"file": ("ring.geojson", io.BytesIO(_json.dumps(fc).encode("utf-8")), "application/geo+json")},
    )
    assert upload.status_code in (200, 201), upload.text
    layer_id = upload.json().get("id")
    assert layer_id, upload.text

    resp = client.post(
        f"/api/workspace/{calc.id}/import-layers/{layer_id}/convert-to-builtin",
        headers=headers,
        json={"target_type": "boundary"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["area_hectares"] > 0, resp.text

    db.refresh(calc)
    from geoalchemy2.shape import to_shape as _t_shape
    assert "Polygon" in _t_shape(calc.boundary_geom).geom_type


def test_convert_to_builtin_polygon_layer_preserved_as_is(client, db):
    """A polygon layer converted to 'boundary' keeps its polygons unchanged
    (case A of the shared engine) — no shape distortion from the boundary path."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)

    import json as _json
    raw_ring = [[83.50, 27.50], [83.505, 27.50], [83.505, 27.505], [83.50, 27.505]]
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "parcel"},
            "geometry": {"type": "Polygon", "coordinates": [raw_ring + [raw_ring[0]]]},
        }],
    }
    upload = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        data={"purpose": "custom", "crs_epsg": "4326"},
        files={"file": ("parcel.geojson", io.BytesIO(_json.dumps(fc).encode("utf-8")), "application/geo+json")},
    )
    assert upload.status_code in (200, 201), upload.text
    layer_id = upload.json().get("id")
    assert layer_id, upload.text

    resp = client.post(
        f"/api/workspace/{calc.id}/import-layers/{layer_id}/convert-to-builtin",
        headers=headers,
        json={"target_type": "boundary"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["area_hectares"] > 0, resp.text

    db.refresh(calc)
    from geoalchemy2.shape import to_shape as _t_shape
    bnd = _t_shape(calc.boundary_geom)
    assert "Polygon" in bnd.geom_type
    assert bnd.bounds == (83.5, 27.5, 83.505, 27.505), bnd.wkt


def test_convert_to_builtin_swapped_point_layer_auto_fixes(client, db):
    """A point layer whose coordinates are accidentally swapped (lon in lat
    range, lat in lon range) must be auto-fixed at IMPORT time — so a 'Skip /
    Assign Purpose Later' import never stores/renders the layer at the edge of
    the globe. The import response flags `swapped_fixed`; the converted boundary
    then lands inside Nepal."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id, forest_name="Swap Forest")

    import json as _json
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "s1"},
             "geometry": {"type": "Point", "coordinates": [27.50, 83.50]}},
            {"type": "Feature", "properties": {"name": "s2"},
             "geometry": {"type": "Point", "coordinates": [27.50, 83.60]}},
            {"type": "Feature", "properties": {"name": "s3"},
             "geometry": {"type": "Point", "coordinates": [27.55, 83.55]}},
        ],
    }
    upload = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        data={"purpose": "custom", "crs_epsg": "4326"},
        files={"file": ("swapped.geojson", io.BytesIO(_json.dumps(fc).encode("utf-8")), "application/geo+json")},
    )
    assert upload.status_code in (200, 201), upload.text
    assert upload.json().get("swapped_fixed") is True, upload.text
    layer_id = upload.json().get("id")
    assert layer_id, upload.text

    # The STORED features must already be inside Nepal (not the edge of the globe).
    feats = client.get(f"/api/workspace/{calc.id}/import-layers/{layer_id}/features", headers=headers)
    assert feats.status_code == 200, feats.text
    for f in feats.json()["features"]:
        c = f["geometry"]["coordinates"]
        if f["geometry"]["type"] == "Point":
            cx, cy = c
        else:
            cx, cy = c[0]
        assert 80.0 <= cx <= 88.3, (f["geometry"], cx)
        assert 26.3 <= cy <= 30.5, (f["geometry"], cy)

    resp = client.post(
        f"/api/workspace/{calc.id}/import-layers/{layer_id}/convert-to-builtin",
        headers=headers,
        json={"target_type": "boundary"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["area_hectares"] > 0, body

    # The boundary must lie INSIDE Nepal's extent.
    geom = body["geometry"]
    assert geom["type"] == "Polygon", geom
    lons = [c[0] for c in geom["coordinates"][0]]
    lats = [c[1] for c in geom["coordinates"][0]]
    assert 80.0 <= min(lons) and max(lons) <= 88.3, geom
    assert 26.3 <= min(lats) and max(lats) <= 30.5, geom


# ---------- B-4: Nepali aliases in coordinate detection paths ----------

def test_coordinate_detector_nepali_aliases():
    import pandas as pd
    from app.services.validators.coordinate_detector import CoordinateDetector
    detector = CoordinateDetector()
    x_col, y_col = detector.detect_coordinate_columns(pd.DataFrame([{"देशान्तर": 1, "अक्षांश": 2}]))
    assert x_col == "देशान्तर"
    assert y_col == "अक्षांश"


def test_detect_workspace_columns_nepali():
    from app.services.file_processor import _detect_workspace_columns
    result = _detect_workspace_columns(["देशान्तर", "अक्षांश"])
    assert result["lon"] == "देशान्तर"
    assert result["lat"] == "अक्षांश"
