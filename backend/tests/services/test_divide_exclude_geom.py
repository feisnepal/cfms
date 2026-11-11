"""divide_equal_area(exclude_geom=...) — divide the NET manageable area.

PROTECTION_WORKING_CIRCLE_PLAN.md P2. Private land + protection working-circle
units are punched out of the parent before an equal-area divide, so the pieces
have equal *net* area and the exclusions become permanent holes.
"""
from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from app.services.geometry_edit_service import (
    W_DIVIDE_EXCLUSION_DISCONNECTED,
    W_DIVIDE_TOLERANCE_EXCEEDED,
    area_sqm,
    divide_equal_area,
)


def _sq(x0, y0, x1, y1):
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])


# ~2 km × 2.2 km parent near Chitwan.
PARENT = _sq(84.00, 28.00, 84.02, 28.02)


def test_no_exclude_geom_is_unchanged():
    pieces, warns = divide_equal_area(PARENT, layer_type="blocks", n=2)
    assert len(pieces) == 2 and warns == []
    a0, a1 = area_sqm(pieces[0]), area_sqm(pieces[1])
    assert abs(a0 - a1) / max(a0, 1) < 0.05


def test_exclude_hole_gives_equal_NET_pieces():
    hole = _sq(84.002, 28.002, 84.010, 28.018)  # a private parcel wholly inside
    gross = area_sqm(PARENT)
    net = area_sqm(PARENT.difference(hole))
    assert net < gross

    pieces, warns = divide_equal_area(PARENT, layer_type="blocks", n=2, exclude_geom=hole)
    assert W_DIVIDE_TOLERANCE_EXCEEDED not in warns
    assert len(pieces) == 2

    areas = sorted(area_sqm(p) for p in pieces)
    # each piece ~= net / 2, well within ±5%
    assert abs(areas[0] - net / 2) / (net / 2) < 0.05
    assert abs(areas[1] - net / 2) / (net / 2) < 0.05
    # and together they are the NET area, not the gross
    assert abs(sum(areas) - net) / net < 0.02


def test_exclude_everything_raises():
    with pytest.raises(ValueError, match="nothing left to divide"):
        divide_equal_area(PARENT, layer_type="blocks", n=2, exclude_geom=PARENT.buffer(0.001))


def test_exclusion_that_disconnects_divides_the_largest_lobe():
    # a full-height vertical strip through the middle splits the parent in two
    wall = _sq(84.0098, 28.00, 84.0102, 28.02)
    pieces, warns = divide_equal_area(PARENT, layer_type="blocks", n=2, exclude_geom=wall)
    assert W_DIVIDE_EXCLUSION_DISCONNECTED in warns
    assert len(pieces) == 2  # the larger lobe still got divided into 2
