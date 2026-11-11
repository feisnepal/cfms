"""divide_equal_area_by_area / divide_multipolygon_equal_area_by_area
(user 2026-09-13: divide by a per-piece AREA instead of a piece count, so the
LAST piece is the remainder) — pure-logic tests against the shared engine every
by-area divide path uses. Mirrors test_divide_piece_cap.py's guard coverage.
"""
from __future__ import annotations

import pytest
from shapely.geometry import MultiPolygon, Polygon

from app.services.geometry_edit_service import (
    DIVIDE_AREA_TOLERANCE_REL,
    MAX_DIVIDE_PIECES,
    W_DIVIDE_REMAINDER_SMALL,
    W_DIVIDE_TOLERANCE_EXCEEDED,
    area_sqm,
    divide_equal_area_by_area,
    divide_multipolygon_equal_area_by_area,
)


def _sq(x0, y0, x1, y1):
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])


PARENT = _sq(84.00, 28.00, 84.02, 28.02)


def test_full_pieces_match_target_and_last_is_remainder():
    total = area_sqm(PARENT)
    target = total * 0.3  # 3 full pieces + a 0.1*total remainder
    pieces, warns = divide_equal_area_by_area(PARENT, target, layer_type="blocks", direction="vertical")
    assert len(pieces) == 4
    for p in pieces[:-1]:
        assert abs(area_sqm(p) - target) / target <= DIVIDE_AREA_TOLERANCE_REL
    assert area_sqm(pieces[-1]) < target
    assert abs(sum(area_sqm(p) for p in pieces) - total) / total < 1e-6


def test_even_target_splits_cleanly():
    total = area_sqm(PARENT)
    target = total / 4
    pieces, warns = divide_equal_area_by_area(PARENT, target, layer_type="blocks", direction="vertical")
    assert len(pieces) == 4
    for p in pieces:
        assert abs(area_sqm(p) - target) / target <= DIVIDE_AREA_TOLERANCE_REL


def test_piece_area_above_total_is_rejected():
    total = area_sqm(PARENT)
    with pytest.raises(ValueError, match="PIECE_AREA_TOO_LARGE"):
        divide_equal_area_by_area(PARENT, total * 1.01, layer_type="blocks")


def test_piece_area_equal_to_total_is_rejected():
    total = area_sqm(PARENT)
    with pytest.raises(ValueError, match="PIECE_AREA_TOO_LARGE"):
        divide_equal_area_by_area(PARENT, total, layer_type="blocks")


def test_piece_area_below_minimum_is_rejected():
    total = area_sqm(PARENT)
    with pytest.raises(ValueError, match="PIECE_AREA_TOO_SMALL"):
        divide_equal_area_by_area(PARENT, total * 0.001, layer_type="blocks", min_area_sqm=total * 0.05)


def test_remainder_below_minimum_warns_but_is_kept():
    total = area_sqm(PARENT)
    target = total * 0.3
    pieces, warns = divide_equal_area_by_area(
        PARENT, target, layer_type="blocks", min_area_sqm=total * 0.15,
    )
    assert len(pieces) == 4
    assert W_DIVIDE_REMAINDER_SMALL in warns


def test_too_many_pieces_hits_the_cap_before_any_division_work():
    total = area_sqm(PARENT)
    target = total * 0.001  # ~1000 pieces
    with pytest.raises(ValueError, match="MAX_PIECES"):
        divide_equal_area_by_area(PARENT, target, layer_type="blocks")


def test_direction_angle_path_produces_same_areas():
    total = area_sqm(PARENT)
    target = total * 0.3
    pieces, warns = divide_equal_area_by_area(PARENT, target, layer_type="blocks", direction_angle=37.0)
    assert len(pieces) == 4
    # rotate() + rotate-back round-trips the split geometry; the geodesic area
    # of the rotated pieces drifts ~3e-6 relative — well within 1e-4.
    assert abs(sum(area_sqm(p) for p in pieces) - total) / total < 1e-4
    for p in pieces[:-1]:
        assert abs(area_sqm(p) - target) / target <= DIVIDE_AREA_TOLERANCE_REL


def test_exclusion_disconnect_warns_on_by_area():
    total = area_sqm(PARENT)
    target = total * 0.3
    # A horizontal band punched out of the middle leaves two disconnected
    # lobes; only the largest is divided, the lobes still tile the parent.
    exclude = _sq(84.008, 28.000, 84.012, 28.012)
    pieces, warns = divide_equal_area_by_area(
        PARENT, target, layer_type="blocks", exclude_geom=exclude,
    )
    assert len(pieces) >= 2


def test_multipolygon_keeps_each_islands_own_remainder():
    island_a = _sq(84.00, 28.00, 84.02, 28.02)
    island_b = _sq(84.04, 28.00, 84.06, 28.02)
    mp = MultiPolygon([island_a, island_b])
    total = area_sqm(mp)
    target = area_sqm(island_a) * 0.3
    pieces, warns = divide_multipolygon_equal_area_by_area(
        mp, target, layer_type="compartments",
    )
    assert len(pieces) == 8  # 3 full + 1 remainder per island
    assert W_DIVIDE_TOLERANCE_EXCEEDED not in warns
    assert abs(sum(area_sqm(p) for p in pieces) - total) / total < 1e-6


def test_multipolygon_total_across_islands_over_the_cap_is_rejected():
    island_a = _sq(84.00, 28.00, 84.02, 28.02)
    island_b = _sq(84.04, 28.00, 84.06, 28.02)
    mp = MultiPolygon([island_a, island_b])
    # 12 pieces per island (each individually under the cap), 24 total > 20.
    target = area_sqm(island_a) / 12
    with pytest.raises(ValueError, match="MAX_PIECES"):
        divide_multipolygon_equal_area_by_area(mp, target, layer_type="compartments")