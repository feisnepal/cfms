"""POST /forests/boundary/parse-file — server-side boundary-file parsing.

The browser cannot decode GeoPackage (SQLite), so the create-workspace flow
uploads the file here. This endpoint runs the file through the same
Feature-to-Polygon pipeline the workspace Layer Import uses, so closed line
rings and plain polygons behave exactly like their KML/SHP equivalents.

Exercised:
  - plain Polygon GeoJSON → Polygon Feature
  - closed LineString GeoJSON → Polygon (ArcGIS-style Feature to Polygon)
  - real .gpkg (written by pyogrio/geopandas) → Polygon Feature
  - garbage .gpkg → HTTP 400 with bilingual `boundary.file_parse_failed`
  - unauthenticated → HTTP 401
"""
import io
import json
import uuid

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

SQUARE = [[83.50, 27.50], [83.60, 27.50], [83.60, 27.55], [83.50, 27.55]]
SQUARE_CLOSED = SQUARE + [SQUARE[0]]


def _auth_header(client):
    email = f"parse-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Parse File",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _polygon_geojson():
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "square"},
            "geometry": {"type": "Polygon", "coordinates": [SQUARE_CLOSED]},
        }],
    }


def _closed_line_geojson():
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "ring"},
            "geometry": {"type": "LineString", "coordinates": SQUARE_CLOSED},
        }],
    }


def test_parse_file_geojson_polygon(client):
    headers = _auth_header(client)
    content = json.dumps(_polygon_geojson()).encode("utf-8")
    resp = client.post(
        "/api/forests/boundary/parse-file",
        headers=headers,
        files={"file": ("boundary.geojson", io.BytesIO(content), "application/geo+json")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "Feature"
    assert body["geometry"]["type"] == "Polygon"
    coords = body["geometry"]["coordinates"][0]
    assert len(coords) >= 5  # closed ring


def test_parse_file_closed_line_becomes_polygon(client):
    headers = _auth_header(client)
    content = json.dumps(_closed_line_geojson()).encode("utf-8")
    resp = client.post(
        "/api/forests/boundary/parse-file",
        headers=headers,
        files={"file": ("ring.geojson", io.BytesIO(content), "application/geo+json")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["geometry"]["type"] == "Polygon"
    first = body["geometry"]["coordinates"][0][0]
    last = body["geometry"]["coordinates"][0][-1]
    assert first == last  # closed ring preserved


def test_parse_file_gpkg_polygon(client, tmp_path):
    headers = _auth_header(client)
    path = tmp_path / "boundary.gpkg"
    gdf = gpd.GeoDataFrame(
        {"name": ["square"]},
        geometry=[Polygon([tuple(p) for p in SQUARE_CLOSED])],
        crs="EPSG:4326",
    )
    gdf.to_file(path, driver="GPKG")
    bytes_ = path.read_bytes()
    resp = client.post(
        "/api/forests/boundary/parse-file",
        headers=headers,
        files={"file": ("boundary.gpkg", io.BytesIO(bytes_), "application/geopackage+sqlite3")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "Feature"
    assert body["geometry"]["type"] == "Polygon"


def test_parse_file_garbage_gpkg_returns_400(client):
    headers = _auth_header(client)
    garbage = b"this is not a geopackage at all, just some bytes"
    resp = client.post(
        "/api/forests/boundary/parse-file",
        headers=headers,
        files={"file": ("fake.gpkg", io.BytesIO(garbage), "application/geopackage+sqlite3")},
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "boundary.file_parse_failed"
    assert detail["message"]
    assert detail["message_np"]


def test_parse_file_garbage_kml_returns_400(client):
    headers = _auth_header(client)
    resp = client.post(
        "/api/forests/boundary/parse-file",
        headers=headers,
        files={"file": ("fake.kml", io.BytesIO(b'{"not": "kml"}'), "text/xml")},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "boundary.file_parse_failed"


def test_parse_file_requires_auth(client):
    content = json.dumps(_polygon_geojson()).encode("utf-8")
    resp = client.post(
        "/api/forests/boundary/parse-file",
        files={"file": ("boundary.geojson", io.BytesIO(content), "application/geo+json")},
    )
    assert resp.status_code == 401, resp.text