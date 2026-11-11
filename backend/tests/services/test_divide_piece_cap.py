"""MAX_DIVIDE_PIECES cap (user report, 2026-09-13: "if user enters a large
number it may get hanged" for equal-area division) — pure-logic tests against
the shared service functions every divide path (boundary/blocks/compartments/
sub_compartments, self-divide, fresh child carve, single- and multi-island)
funnels through, so one guard at this choke point covers all of them.
"""
from __future__ import annotations

import pytest
from shapely.geometry import MultiPolygon, Polygon

from app.services.geometry_edit_service import (
    MAX_DIVIDE_PIECES,
    divide_equal_area,
    divide_multipolygon_equal_area,
)


def _sq(x0, y0, x1, y1):
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])


PARENT = _sq(84.00, 28.00, 84.02, 28.02)


def test_strips_at_the_cap_succeeds():
    pieces, warns = divide_equal_area(PARENT, layer_type="blocks", method="strips", n=MAX_DIVIDE_PIECES)
    assert len(pieces) == MAX_DIVIDE_PIECES


def test_strips_over_the_cap_is_rejected_before_any_division_work():
    with pytest.raises(ValueError, match="maximum is 20"):
        divide_equal_area(PARENT, layer_type="blocks", method="strips", n=MAX_DIVIDE_PIECES + 1)


def test_strips_a_huge_count_is_rejected_immediately_not_hung():
    with pytest.raises(ValueError, match="maximum is 20"):
        divide_equal_area(PARENT, layer_type="blocks", method="strips", n=100_000)


def test_grid_rows_times_cols_over_the_cap_is_rejected():
    # 5 x 5 = 25 > 20 — rejected even though each dimension looks modest.
    with pytest.raises(ValueError, match="maximum is 20"):
        divide_equal_area(PARENT, layer_type="blocks", method="grid", rows=5, cols=5)


def test_grid_rows_times_cols_at_the_cap_succeeds():
    pieces, warns = divide_equal_area(PARENT, layer_type="blocks", method="grid", rows=4, cols=5)
    assert len(pieces) == 20


def test_multipolygon_total_across_islands_over_the_cap_is_rejected():
    """Each island's own share can be individually small while the SUM
    (what actually gets persisted) exceeds the cap."""
    parts = MultiPolygon([_sq(0, 0, 1, 1), _sq(2, 0, 3, 1), _sq(4, 0, 5, 1)])
    counts = [8, 8, 8]  # each under the cap, sum = 24 > 20
    with pytest.raises(ValueError, match="maximum is 20"):
        divide_multipolygon_equal_area(parts, counts, layer_type="compartments", method="strips")


def test_multipolygon_total_across_islands_at_the_cap_succeeds():
    parts = MultiPolygon([_sq(0, 0, 1, 1), _sq(2, 0, 3, 1)])
    counts = [10, 10]
    pieces, warns = divide_multipolygon_equal_area(parts, counts, layer_type="compartments", method="strips")
    assert len(pieces) == 20


def test_multipolygon_grid_multiplies_by_island_count_before_capping():
    """The grid method applies the same rows x cols to EVERY island
    regardless of `counts`, so the true total is len(parts) * rows * cols."""
    parts = MultiPolygon([_sq(0, 0, 1, 1), _sq(2, 0, 3, 1), _sq(4, 0, 5, 1)])
    counts = [1, 1, 1]
    with pytest.raises(ValueError, match="maximum is 20"):
        divide_multipolygon_equal_area(
            parts, counts, layer_type="compartments", method="grid", rows=3, cols=3,
        )
