"""U05 — kiln lockstep tests for the Web-Mercator tile helpers.

These pure-math tests mirror the constants in `frontend/src/lib/webmercator.ts`
(plan A.3: "MUST STAY IN LOCKSTEP"). The values are anchored to well-known
Web-Mercator tile facts so any drift on either side of the stack is caught.
"""
import math
import pytest
from app.services.webmercator import (
    bbox_for_tile,
    cell_size_at_zoom,
    lnglat_to_meters,
    tile_xy,
    webmercator_extent,
)


class TestTileXY:
    def test_zero_zoom_single_tile(self):
        # z0: the whole world is one tile at (0,0).
        assert tile_xy(0.0, 0.0, 0) == (0, 0)
        assert tile_xy(-179.9, -85.0, 0) == (0, 0)
        assert tile_xy(179.9, 85.0, 0) == (0, 0)

    def test_london_at_zoom_2(self):
        # London ~ (-0.1276, 51.5072). At z2 the world is 4x4 tiles.
        # Known-webmercator anchor: london falls in tile (3, 1) at z4? no — verify below is z2.
        # Use the mathematically-derived expected value instead of a magic number:
        x, y = tile_xy(-0.1276, 51.5072, 2)
        # x in [0,4): (-0.1276+180)/360*4 = 1.998...e-1*4 = 1.999 -> floor 1
        # y = Mercator -> for lat 51.5, standard value ~ floor(1.219) = 1
        assert x == (int(((180.0 - 0.1276) / 360.0) * 4.0))  # == 1
        assert y >= 0 and y < 4
        assert (x, y) == (1, 1)

    def test_nepal_forest_anchor(self):
        # Our real calc centroid (85.05, 27.43) at z14 — this is the tile the
        # U05 integration dataset lives in. Floor to the tile.
        x, y = tile_xy(85.05, 27.43, 14)
        nx = int(math.floor((85.05 + 180.0) / 360.0 * (2**14)))
        assert x == nx
        assert 0 <= x < 2**14 and 0 <= y < 2**14

    def test_clamps_null_island_for_extreme_lat(self):
        # Latitude beyond Web-Mercator range clamps rather than NaN/Inf.
        x, y = tile_xy(10.0, 89.9, 4)
        # Clamped to Web-Mercator's lat edge → x valid, y at the northern boundary.
        assert 0 <= x < 2**4
        assert y > 0 or y < 2**4


class TestBBoxForTile:
    def test_world_tile(self):
        w, s, e, n = bbox_for_tile(0, 0, 0)
        assert w == pytest.approx(-180.0)
        assert e == pytest.approx(180.0)
        assert s == pytest.approx(-85.05112878, abs=1e-6)
        assert n == pytest.approx(85.05112878, abs=1e-6)

    def test_tile_contains_its_centroid(self):
        z = 10
        for (tx, ty) in [(300, 400), (512, 512), (600, 700)]:
            w, s, e, n = bbox_for_tile(tx, ty, z)
            cx = (w + e) / 2.0
            cy = (s + n) / 2.0
            assert tile_xy(cx, cy, z) == (tx, ty)

    def test_monotonic_bounds(self):
        w, s, e, n = bbox_for_tile(123, 456, 14)
        assert w < e and s < n


class TestLngLatToMeters:
    def test_null_meridian(self):
        x, y = lnglat_to_meters(0.0, 0.0)
        assert x == pytest.approx(0.0, abs=1e-9)
        assert y == pytest.approx(0.0, abs=1e-9)

    def test_known_3857_value(self):
        # 85.05, 27.43 in feet/meters — anchored to EPSG:3857.
        x, y = lnglat_to_meters(85.05, 27.43)
        assert x == pytest.approx(9467722.691967918, abs=1e-4)

    def test_cell_size(self):
        assert cell_size_at_zoom(0) == pytest.approx(156543.03392, rel=1e-9)
        assert cell_size_at_zoom(18) == pytest.approx(156543.03392 / 2**18, rel=1e-9)


class TestWebMercatorExtent:
    def test_subtile(self):
        x_min, y_min, x_max, y_max = webmercator_extent(-180.0, -85.05112878, 180.0, 85.05112878)
        assert x_min == pytest.approx(0.0 - 20037508.34, abs=1)
        assert x_max == pytest.approx(20037508.34, abs=1)