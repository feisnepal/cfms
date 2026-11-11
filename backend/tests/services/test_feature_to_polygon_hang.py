"""The point cloud that made feature_to_polygon run forever (H-HULL-1).

Found by the Hypothesis property test in this directory, and kept here as a
FIXED case. A property test finds a defect once, on a seed nobody records; a
regression test proves it stays fixed on every run.

What it was: 39 points mixing ordinary magnitudes (~1e1) with near-zero ones
(down to 5e-324). `feature_to_polygon` never returned -- one core pinned, no
exception, no output. It is reachable from the shapefile / GeoJSON import path,
so an uploaded file could wedge a worker indefinitely, and on a bad Hypothesis
seed it also killed the whole CI test job (pytest-timeout uses the thread
method on Windows, which aborts the run rather than failing one test).

Why the existing defences missed it: `_concave_hull` carries careful fallbacks,
and every one of them hangs off `except Exception`. A call that never returns
raises nothing, so it walked past the guard, the convex-hull fallback and the
warning about enclosing more ground than the points do. A hang is not an
exception -- which is why the fix runs before the work instead of around it.
"""
from __future__ import annotations

import pytest
from shapely.geometry import Point

from app.services.file_processor import (
    COORD_PRECISION_FLOOR,
    PolygonizeConfig,
    _sanitize_coordinate_magnitudes,
    feature_to_polygon,
)

# Captured verbatim from the falsifying run. Do not "tidy" these numbers: the
# extreme dynamic range between them IS the test.
HANGING_CLOUD = [
    (-23.084408448857456, 19.55024910995712),
    (-27.578026681292027, -32.21251857816767),
    (0.0001, 28.939909018590384),
    (-1e-05, 19.482682989244722),
    (-8.168763976171021e-16, 2.00001),
    (17.551305063006538, 24.88939221764373),
    (4.0, 33.69436319040685),
    (25.0, -49.0),
    (-14.443986578948333, 31.37143214486973),
    (41.605094784461414, 21.92893874796175),
    (20.213918185216684, -27.137764233670374),
    (1.9784893099419634, -1.1656143232933437e-277),
    (2.0, -21.62222534496307),
    (4.697011326074576e-173, -9.841335918132979e-111),
    (0.0, -39.929185140074104),
    (32.10789081891237, -49.0),
    (11.396986606603853, 4.6111026533274914e-237),
    (21.453639151469687, -4.7886536181799614e-54),
    (2.1990437104265167e-30, -22.19766906275355),
    (6.009976945246088, 19.78811015042949),
    (4.0005843682225e-99, -19.910870298362866),
    (16.512706610379283, 0.0),
    (-4.397273829277011e-246, -0.0),
    (-2.562619175383105e-291, -2.00001),
    (-20.408855440671964, -2.152545485753456e-303),
    (-27.022326936449563, -5e-324),
    (3.900651779306951e-14, 27.6585189349357),
    (-2.6722917032102955e-221, 45.0),
    (35.993863390496344, 36.219771848296105),
    (-32.36479802974754, -2.061171074364111),
    (41.86705515952795, -20.69462887720969),
    (-6.981437547973775e-295, -22.521923079703527),
    (-38.810291575572094, -8.080054062013275),
    (-9.94512268313862, -26.64536006521207),
    (-4.5852795265799545e-132, 19.482682989244722),
    (1.4406356767678972, 0.0009),
    (-21.886131697212647, 15.80657759073641),
    (-2.00001, 50.0),
    (-47.975646911808354, 9.486)
]


@pytest.mark.timeout(60)
@pytest.mark.parametrize("alpha", [0.0, 0.4, 0.9])
def test_the_cloud_that_used_to_hang_now_completes(alpha):
    """Before the fix this never returned, at every alpha.

    The timeout marker is the assertion that matters. Without it a regression
    here would not fail the test -- it would hang the suite, which is exactly
    how the defect presented in the first place.
    """
    points = [Point(x, y) for x, y in HANGING_CLOUD]
    cfg = PolygonizeConfig(allow_point_hull=True, alpha=alpha, island_cluster_m=500000.0)

    result, _warnings = feature_to_polygon(points, [{}] * len(points), cfg)

    assert result, "the engine returned no features for a 39-point cloud"
    for geom, _attrs in result:
        assert geom.is_valid
        assert not geom.is_empty


class TestTheSanitizer:
    def test_sub_precision_values_are_snapped(self):
        tiny = COORD_PRECISION_FLOOR / 10
        cleaned, changed = _sanitize_coordinate_magnitudes([Point(tiny, 5.0)])
        assert changed == 1
        assert cleaned[0].x == 0.0
        assert cleaned[0].y == 5.0

    def test_ordinary_coordinates_are_untouched(self):
        """It must not perturb real data.

        Nepal is roughly lon 80.0-88.3, lat 26.3-30.5, and a metre is about
        1e-5 degrees -- five orders of magnitude above the floor.
        """
        original = Point(84.124, 28.3949)
        cleaned, changed = _sanitize_coordinate_magnitudes([original])
        assert changed == 0
        assert cleaned[0].equals_exact(original, 0.0)

    def test_projected_coordinates_are_untouched(self):
        """The engine also sees UTM metres, so this cannot be a degrees-only rule."""
        original = Point(456789.0, 3086543.0)
        cleaned, changed = _sanitize_coordinate_magnitudes([original])
        assert changed == 0
        assert cleaned[0].equals_exact(original, 0.0)

    def test_an_empty_or_missing_geometry_is_passed_through(self):
        from shapely.geometry import Polygon

        cleaned, changed = _sanitize_coordinate_magnitudes([None, Polygon()])
        assert changed == 0
        assert cleaned[0] is None
