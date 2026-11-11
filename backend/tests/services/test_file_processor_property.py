"""Property-based tests for file_processor using Hypothesis.

Tests validate core invariants:
- Geometry validators reject out-of-bounds inputs
- CSV sanitization neutralizes formula injection
- Coordinate parser handles all DMS/DD variants
- Column detection is case-insensitive
- Generated GPX/KML round-trips through readers without error
"""
import os
import tempfile
import xml.etree.ElementTree as ET

import pytest
from hypothesis import given, assume, strategies as st, settings, HealthCheck
from shapely.geometry import Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon

from app.services.file_processor import (
    validate_geometry_types,
    validate_feature_count,
    validate_vertex_count,
    _sanitize_csv_value,
    _parse_coordinate,
    _detect_workspace_columns,
    read_kml,
    read_gpx,
)
from app.core.constants import (
    WORKSPACE_IMPORT_MAX_FEATURES,
    WORKSPACE_IMPORT_MAX_VERTICES,
)


# =========================================================================
# Geometry type validation
# =========================================================================

@given(st.sampled_from([
    Point(0, 0),
    LineString([(0, 0), (1, 1)]),
    Polygon([(0, 0), (1, 0), (1, 1), (0, 0)]),
    MultiPoint([Point(0, 0), Point(1, 1)]),
    MultiLineString([LineString([(0, 0), (1, 1)])]),
    MultiPolygon([Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])]),
]))
def test_validate_geometry_types_valid(geom):
    """All standard geometry types should pass validation."""
    validate_geometry_types([geom])


@settings(deadline=None, max_examples=50, suppress_health_check=[HealthCheck.too_slow])
@given(st.builds(LineString, st.lists(st.tuples(st.floats(-180, 180), st.floats(-90, 90)), min_size=2, max_size=100)))
def test_validate_geometry_types_linestring_variants(geom):
    """Any valid LineString should pass validation."""
    validate_geometry_types([geom])


# =========================================================================
# Feature count validation
# =========================================================================

@given(st.lists(st.just(Point(0, 0)), min_size=0, max_size=WORKSPACE_IMPORT_MAX_FEATURES))
def test_validate_feature_count_valid(geoms):
    """Feature count at or below max should pass."""
    count = validate_feature_count(geoms)
    assert count == len(geoms)


@given(st.lists(st.just(Point(0, 0)), min_size=WORKSPACE_IMPORT_MAX_FEATURES + 1, max_size=WORKSPACE_IMPORT_MAX_FEATURES + 100))
def test_validate_feature_count_exceeds(geoms):
    """Feature count above max should raise ValueError."""
    with pytest.raises(ValueError, match="Too many features"):
        validate_feature_count(geoms)


# =========================================================================
# Vertex count validation
# =========================================================================

@settings(suppress_health_check=[HealthCheck.filter_too_much])
@given(st.builds(
    Polygon,
    st.lists(
        st.tuples(st.floats(-180, 180), st.floats(-90, 90)),
        min_size=4, max_size=20,
    ),
))
def test_validate_vertex_count_polygon(poly):
    """Polygon vertex count should be calculated without error."""
    assume(poly.is_valid)
    count = validate_vertex_count([poly])
    assert count > 0


# =========================================================================
# CSV injection sanitization
# =========================================================================

@given(st.text(alphabet="=+-@\t ", min_size=1, max_size=20))
def test_sanitize_csv_value_prefixes(value):
    """Values with injection prefix (=, +, -, @) should be neutralized; others unchanged."""
    stripped = value.lstrip()
    has_injection_prefix = len(stripped) > 0 and stripped[0] in "=+-@"
    result = _sanitize_csv_value(value)
    if has_injection_prefix:
        assert result.startswith("'")
    else:
        assert result == value


@given(st.text(alphabet="abcxyz123", min_size=0, max_size=50))
def test_sanitize_csv_value_safe(value):
    """Safe values (no injection prefix) should pass through unchanged."""
    result = _sanitize_csv_value(value)
    assert result == value


@given(st.none())
def test_sanitize_csv_value_none(value):
    """None should pass through unchanged."""
    result = _sanitize_csv_value(value)
    assert result is None


# =========================================================================
# Coordinate parser
# =========================================================================

@given(st.floats(-90, 90, allow_nan=False, allow_infinity=False))
def test_parse_coordinate_decimal_degrees(lat):
    """Decimal degree values should parse correctly."""
    result = _parse_coordinate(str(lat))
    assert result is not None
    assert abs(result - lat) < 1e-10


@given(st.floats(-180, -0.001, allow_nan=False, allow_infinity=False))
def test_parse_coordinate_decimal_negative(lon):
    """Negative decimal degrees should parse correctly."""
    result = _parse_coordinate(str(lon))
    assert result is not None
    assert abs(result - lon) < 1e-10


# DMS format: 27°12'34.5"N
@given(
    st.integers(0, 90),
    st.integers(0, 59),
    st.floats(0, 59.999, allow_nan=False, allow_infinity=False),
    st.sampled_from(["N", "S", "E", "W", ""]),
)
def test_parse_coordinate_dms(degrees, minutes, seconds, direction):
    """DMS coordinates should parse correctly."""
    dms_str = f"{degrees}°{minutes}'{seconds:.1f}\"{direction}"
    result = _parse_coordinate(dms_str)
    assert result is not None
    expected = degrees + minutes / 60.0 + seconds / 3600.0
    if direction in ("S", "W"):
        expected = -expected
    assert abs(result - expected) < 1e-4


# =========================================================================
# Column detection
# =========================================================================

@given(st.lists(st.text(alphabet="abcdefghijklmnopqrstuvwxyz_ ", min_size=2, max_size=20), min_size=1, max_size=10))
def test_detect_workspace_columns_always_returns_dict(headers):
    """Column detection should always return a dict with expected keys."""
    result = _detect_workspace_columns(headers)
    assert isinstance(result, dict)
    for key in ("lat", "lon", "wkt", "name", "id"):
        assert key in result


@given(st.just(["Latitude", "Longitude", "Name", "SN"]))
def test_detect_workspace_columns_standard(headers):
    """Standard column names should be detected."""
    result = _detect_workspace_columns(headers)
    assert result["lat"] == "Latitude"
    assert result["lon"] == "Longitude"
    assert result["name"] == "Name"
    assert result["id"] == "SN"


@given(st.just(["lat", "lon", "geom", "title", "s.n"]))
def test_detect_workspace_columns_lowercase(headers):
    """Lowercase column names should be detected."""
    result = _detect_workspace_columns(headers)
    assert result["lat"] == "lat"
    assert result["lon"] == "lon"
    assert result["wkt"] == "geom"
    assert result["name"] == "title"
    assert result["id"] == "s.n"


# =========================================================================
# KML round-trip
# =========================================================================

@given(st.lists(
    st.tuples(
        st.floats(-180, 180, allow_nan=False, allow_infinity=False),
        st.floats(-90, 90, allow_nan=False, allow_infinity=False),
    ),
    min_size=3, max_size=10,
))
@settings(deadline=5000, suppress_health_check=[HealthCheck.too_slow])
def test_read_kml_polygon_roundtrip(coords):
    """A simple KML Polygon should be readable without error."""
    if len(coords) < 3:
        assume(False)
    # Close the ring
    coords_closed = list(coords)
    if coords_closed[0] != coords_closed[-1]:
        coords_closed.append(coords_closed[0])
    coord_str = " ".join(f"{lon},{lat},0" for lat, lon in coords_closed)

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Placemark>
    <name>Test</name>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>{coord_str}</coordinates>
        </LinearRing>
      </outerBoundaryIs>
    </Polygon>
  </Placemark>
</kml>"""

    with tempfile.NamedTemporaryFile(suffix=".kml", mode="w", delete=False, encoding="utf-8") as f:
        f.write(kml)
        tmp_path = f.name

    try:
        geoms, attrs, crs = read_kml(tmp_path)
        assert len(geoms) == 1
        assert attrs[0]["name"] == "Test"
    finally:
        os.unlink(tmp_path)


# =========================================================================
# GPX round-trip
# =========================================================================

@given(st.lists(
    st.tuples(
        st.floats(-180, 180, allow_nan=False, allow_infinity=False),
        st.floats(-90, 90, allow_nan=False, allow_infinity=False),
    ),
    min_size=1, max_size=5,
))
@settings(deadline=5000, suppress_health_check=[HealthCheck.too_slow])
def test_read_gpx_waypoints_roundtrip(coords):
    """Simple GPX waypoints should be readable without error."""
    wpt_str = ""
    for lon, lat in coords:
        wpt_str += f'  <wpt lat="{lat}" lon="{lon}"><name>WPT</name></wpt>\n'

    gpx = f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1">
{wpt_str}
</gpx>"""

    with tempfile.NamedTemporaryFile(suffix=".gpx", mode="w", delete=False, encoding="utf-8") as f:
        f.write(gpx)
        tmp_path = f.name

    try:
        geoms, attrs, crs = read_gpx(tmp_path)
        assert len(geoms) == len(coords)
        for a in attrs:
            assert a["gpx_type"] == "wpt"
    finally:
        os.unlink(tmp_path)


# =========================================================================
# Empty / edge cases
# =========================================================================

def test_validate_geometry_types_empty_list():
    """An empty list should raise no error (nothing to validate)."""
    validate_geometry_types([])


def test_validate_feature_count_zero():
    """Zero features should not raise an error."""
    assert validate_feature_count([]) == 0


@given(st.just(""))
def test_parse_coordinate_empty_string(value):
    """Empty string should return None."""
    assert _parse_coordinate(value) is None


@given(st.just("   "))
def test_parse_coordinate_whitespace(value):
    """Whitespace-only string should return None."""
    assert _parse_coordinate(value) is None


@given(st.just("not_a_coordinate"))
def test_parse_coordinate_garbage(value):
    """Garbage string should return None."""
    assert _parse_coordinate(value) is None
