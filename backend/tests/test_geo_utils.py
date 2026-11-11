"""
UTM zone calculation tests — SSOT geo utility.

Tests calculate_utm_epsg from app.core.geo for global coverage:
- Northern hemisphere (326xx series)
- Southern hemisphere (327xx series)
- Zone boundaries (0°, 180°, -180°)
- Major cities worldwide
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from shapely.geometry import shape
from app.core.geo import calculate_utm_epsg
from app.utils.geometry_utils import (
    compute_geometry_properties,
    strip_geo_fields,
    GEO_COMPUTED_KEYS,
)


@pytest.mark.parametrize("lon,lat,expected_epsg,label", [
    (85.3, 27.7, 32645, "Kathmandu, Nepal"),
    (-122.4, 37.8, 32610, "San Francisco, USA"),
    (0.0, 0.0, 32631, "Equator at Prime Meridian"),
    (180.0, 0.0, 32660, "Antimeridian east"),
    (-180.0, 0.0, 32601, "Antimeridian west"),
    (9.0, 60.0, 32632, "Oslo, Norway"),
    (139.0, 35.0, 32654, "Tokyo, Japan"),
    (151.2, -33.9, 32756, "Sydney, Australia (southern)"),
])
def test_calculate_utm_epsg(lon, lat, expected_epsg, label):
    assert calculate_utm_epsg(lon, lat) == expected_epsg, f"Failed for {label}"


class TestEdgeCases:
    def test_zone_boundary_84east(self):
        """Longitude=84 is in zone 45 (floor((84+180)/6)+1 = floor(264/6)+1 = 44+1 = 45)."""
        assert calculate_utm_epsg(84.0, 27.0) == 32645

    def test_zone_boundary_78east(self):
        """Longitude=78 is in zone 44 (floor((78+180)/6)+1 = floor(258/6)+1 = 43+1 = 44)."""
        assert calculate_utm_epsg(78.0, 27.0) == 32644

    def test_southern_america(self):
        """Santiago, Chile — southern hemisphere, zone 19."""
        assert calculate_utm_epsg(-70.0, -33.0) == 32719

    def test_northern_high_latitude(self):
        """Longyearbyen, Svalbard — zone 33."""
        assert calculate_utm_epsg(15.0, 78.0) == 32633

    def test_zone_60_wrap(self):
        """Longitude near 180 should give zone 60, not 61."""
        assert calculate_utm_epsg(179.9, 45.0) == 32660

    def test_zone_1_wrap(self):
        """Longitude near -180 should give zone 1."""
        assert calculate_utm_epsg(-179.9, 45.0) == 32601


class TestComputeGeometryProperties:
    """Regression guard for the geo_* SSOT (Shapely 2.x + SQM_PER_HA import)."""

    def test_polygon_gets_area_and_perimeter(self):
        poly = shape({
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        })
        props = compute_geometry_properties(poly)
        assert props["geo_area_ha"] > 0
        assert props["geo_perimeter_km"] > 0
        assert props["geo_length_km"] is None
        assert props["geo_centroid_lat"] is not None
        assert props["geo_bbox_xmin"] == 0.0

    def test_point_gets_centroid_and_bbox_only(self):
        pt = shape({"type": "Point", "coordinates": [2.0, 3.0]})
        props = compute_geometry_properties(pt)
        assert props["geo_area_ha"] is None
        assert props["geo_perimeter_km"] is None
        assert props["geo_length_km"] is None
        assert props["geo_centroid_lat"] == 3.0
        assert props["geo_centroid_lng"] == 2.0

    def test_linestring_gets_length(self):
        line = shape({"type": "LineString", "coordinates": [[0, 0], [1, 1]]})
        props = compute_geometry_properties(line)
        assert props["geo_length_km"] > 0
        assert props["geo_area_ha"] is None
        assert props["geo_perimeter_km"] is None

    def test_empty_geometry_returns_all_none(self):
        props = compute_geometry_properties(None)
        assert all(v is None for v in props.values())

    def test_all_geojson_types_work(self):
        for gj in [
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            {"type": "Point", "coordinates": [2.0, 3.0]},
            {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            {
                "type": "MultiPolygon",
                "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]],
            },
        ]:
            props = compute_geometry_properties(shape(gj))
            assert props["geo_centroid_lat"] is not None

    def test_strip_geo_fields_removes_all_computed_keys(self):
        payload = {"name": "kept", **{k: 123.0 for k in GEO_COMPUTED_KEYS}}
        cleaned = strip_geo_fields(payload)
        assert cleaned == {"name": "kept"}
        assert len(GEO_COMPUTED_KEYS) == 9
