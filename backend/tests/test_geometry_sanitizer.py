"""
Unit tests for geometry_sanitizer.py (GD 1.2.4 / Gap 6.2).

The sanitizer is the defence-in-depth gate that runs at the head of every
digitize write path. These tests pin its three guarantees:
1. Vertex cap (5000) — coordinate-count DoS killed.
2. ±10 km bounds check against the calculation boundary bbox.
3. 6 dp precision truncation (float-noise removal for EPSG:4326).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.services.geometry_sanitizer import (
    sanitize_geometry,
    truncate_precision,
    extract_coordinates,
    GeometrySanitizationError,
    MAX_VERTICES,
    PRECISION,
)


def _point(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


def _line(coords):
    return {"type": "LineString", "coordinates": coords}


class TestVertexCap:
    def test_accepts_at_cap(self):
        coords = [[84.0 + i * 0.0001, 28.0] for i in range(MAX_VERTICES)]
        g = _line(coords)
        out = sanitize_geometry(g, [83.0, 27.0, 85.0, 29.0])
        assert len(extract_coordinates(out)) == MAX_VERTICES

    def test_rejects_over_cap(self):
        coords = [[84.0 + i * 0.0001, 28.0] for i in range(MAX_VERTICES + 1)]
        with pytest.raises(GeometrySanitizationError, match="Vertex limit"):
            sanitize_geometry(_line(coords), [83.0, 27.0, 85.0, 29.0])

    def test_point_rejects_over_cap_impossible(self):
        # A single Point is trivially under the cap — sanity check no false reject
        out = sanitize_geometry(_point(84.0, 28.0), [83.0, 27.0, 85.0, 29.0])
        assert out["type"] == "Point"


class TestBoundsCheck:
    BBOX = [83.0, 27.0, 85.0, 29.0]

    def test_inside_bbox_accepted(self):
        out = sanitize_geometry(_point(84.0, 28.0), self.BBOX)
        assert out["coordinates"] == [84.0, 28.0]

    def test_within_10km_buffer_accepted(self):
        # ~0.08 deg ≈ 8.9 km north of the bbox edge at 28° lat
        out = sanitize_geometry(_point(84.0, 29.08), self.BBOX)
        assert out["coordinates"] == [84.0, 29.08]

    def test_beyond_10km_rejected(self):
        with pytest.raises(GeometrySanitizationError, match="outside the project area"):
            sanitize_geometry(_point(84.0, 30.0), self.BBOX)

    def test_no_bbox_skips_bounds(self):
        # calc_bbox=None → bounds gate skipped (authoritative check at finalize)
        out = sanitize_geometry(_point(84.0, 60.0), None)
        assert out["coordinates"] == [84.0, 60.0]

    def test_invalid_coordinate_range_rejected(self):
        with pytest.raises(GeometrySanitizationError, match="out of range"):
            sanitize_geometry(_point(200.0, 0.0), self.BBOX)


class TestPrecision:
    def test_truncates_to_6dp(self):
        g = _point(84.123456789, 28.123456789)
        out = sanitize_geometry(g, None)
        lon, lat = out["coordinates"]
        assert lon == round(84.123456789, PRECISION)
        assert lat == round(28.123456789, PRECISION)

    def test_truncate_precision_is_pure(self):
        g = _point(1.123456789, 2.987654321)
        out = truncate_precision(g, 4)
        assert g["coordinates"] == [1.123456789, 2.987654321]  # input unchanged
        assert out["coordinates"] == [1.1235, 2.9877]

    def test_nested_coordinates_truncated(self):
        poly = {
            "type": "Polygon",
            "coordinates": [[[84.123456789, 28.0], [85.0, 28.0], [85.0, 28.123456789]]],
        }
        out = sanitize_geometry(poly, None)
        assert out["coordinates"][0][0][0] == round(84.123456789, PRECISION)


class TestValidation:
    def test_non_geojson_rejected(self):
        with pytest.raises(GeometrySanitizationError, match="GeoJSON geometry"):
            sanitize_geometry({"foo": "bar"}, None)

    def test_unsupported_type_rejected(self):
        with pytest.raises(GeometrySanitizationError, match="Unsupported geometry type"):
            sanitize_geometry({"type": "Circle", "coordinates": [[0, 0], [1, 1]]}, None)

    def test_non_numeric_coordinates_rejected(self):
        with pytest.raises(GeometrySanitizationError, match="Coordinates must be numeric"):
            sanitize_geometry(_point("abc", 28.0), None)

    def test_multi_polygon_flattened(self):
        mp = {
            "type": "MultiPolygon",
            "coordinates": [
                [[[84.0, 28.0], [84.1, 28.0], [84.1, 28.1], [84.0, 28.0]]],
                [[[84.2, 28.0], [84.3, 28.0], [84.3, 28.1], [84.2, 28.0]]],
            ],
        }
        out = sanitize_geometry(mp, None)
        assert len(extract_coordinates(out)) == 8

    def test_geometry_collection_recurses(self):
        gc = {
            "type": "GeometryCollection",
            "geometries": [_point(84.0, 28.0), _line([[84.0, 28.0], [84.1, 28.0]])],
        }
        out = sanitize_geometry(gc, None)
        assert len(out["geometries"]) == 2
        assert out["geometries"][0]["type"] == "Point"
        assert out["geometries"][1]["type"] == "LineString"
