"""
Purpose → allowed geometry matrix tests — backend SSOT for digitizing.

Verifies `purpose_geometry_rules` against `process_geometry_list`
(`file_processor.py`) — the canonical acceptance logic. The matrix is a curated
subset of processor behaviour (draw modes, not import conveniences), so the
parity guarantee is directional: **every geometry type the matrix allows for a
purpose must be accepted by the processor as a complete drawn feature.**

Expected matrix:
- STRICT_POINT (inventory, sample_plot) → {Point}
- roads → {LineString}
- polygon-auto-buffer (blocks, boundary, user_group_boundary) → {Polygon}
- water → {LineString, Polygon}
- other → {Point, LineString, Polygon}
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from shapely.geometry import Point, LineString, Polygon, box

from app.core.constants import IMPORT_PURPOSE_ALL, IMPORT_PURPOSE_ROADS
from app.services.file_processor import process_geometry_list
from app.services.purpose_geometry_rules import (
    PURPOSE_ALLOWED_GEOMETRY_TYPES,
    allowed_geometry_types,
)

# Geometry fixtures (complete, valid drawn features)
PT = Point(85.32, 27.71)
LINE = LineString([(85.30, 27.70), (85.31, 27.71), (85.32, 27.72)])
POLY = box(85.30, 27.70, 85.32, 27.72)


def _accepts(purpose: str, geoms) -> bool:
    """True if process_geometry_list accepts the geometries for purpose."""
    try:
        process_geometry_list(geoms, [{} for _ in geoms], purpose=purpose)
        return True
    except ValueError:
        return False


def test_matrix_covers_exactly_all_purposes():
    assert set(PURPOSE_ALLOWED_GEOMETRY_TYPES.keys()) == IMPORT_PURPOSE_ALL


def test_strict_point_purposes_only_points():
    for purpose in PURPOSE_ALLOWED_GEOMETRY_TYPES:
        if purpose in ("inventory", "sample_plot"):
            assert PURPOSE_ALLOWED_GEOMETRY_TYPES[purpose] == {"Point"}


def test_polygon_purposes_only_polygons():
    for purpose in ("user_group_boundary", "boundary", "blocks"):
        assert PURPOSE_ALLOWED_GEOMETRY_TYPES[purpose] == {"Polygon"}


def test_roads_line_only():
    assert PURPOSE_ALLOWED_GEOMETRY_TYPES[IMPORT_PURPOSE_ROADS] == {"LineString"}


def test_water_and_other():
    assert PURPOSE_ALLOWED_GEOMETRY_TYPES["water"] == {"LineString", "Polygon"}
    assert PURPOSE_ALLOWED_GEOMETRY_TYPES["other"] == {"Point", "LineString", "Polygon"}


def test_unknown_purpose_raises():
    with pytest.raises(ValueError):
        allowed_geometry_types("not_a_purpose")
    with pytest.raises(ValueError):
        allowed_geometry_types("")


def test_parity_matrix_allows_only_what_processor_accepts():
    """Directional parity: every draw mode the matrix offers for a purpose is
    accepted by process_geometry_list as a complete feature."""
    geom_by_type = {"Point": PT, "LineString": LINE, "Polygon": POLY}
    for purpose, allowed in PURPOSE_ALLOWED_GEOMETRY_TYPES.items():
        for geo_type in allowed:
            assert _accepts(purpose, [geom_by_type[geo_type]]), (
                f"{purpose} matrix allows {geo_type} but process_geometry_list rejects it"
            )
