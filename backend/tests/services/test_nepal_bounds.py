"""Geometry imports must be in Nepal (H-GEO-1).

The service is designed for Nepal and no other area is applicable, so a file
whose coordinates fall outside the country is not unusual data -- it is the
wrong file, or a corrupt one, and processing it produces figures that mean
nothing.

The bounds themselves are not new. `validators/coordinate_detector.py` has
carried them since it was written, for CSV and Excel tree inventory. They were
never wired to geometry import, so a shapefile from anywhere on earth was
accepted in silence. That gap is also how the coordinate cloud behind H-HULL-1
reached the polygon engine and made it run forever: points at 1e-311 are not in
Nepal, and nothing on the geometry path was asking.
"""
from __future__ import annotations

import pytest
from shapely.geometry import Point, Polygon

from app.services.file_processor import (
    NEPAL_BOUNDS_MARGIN_DEG,
    NEPAL_GEOGRAPHIC_BOUNDS,
    validate_geometry_within_nepal,
)

# Kathmandu, and a plausible community forest polygon near it.
KATHMANDU = Point(85.3240, 27.7172)
FOREST = Polygon([(85.30, 27.60), (85.40, 27.60), (85.40, 27.70), (85.30, 27.70)])


class TestRealData:
    def test_a_forest_in_nepal_is_accepted(self):
        validate_geometry_within_nepal([FOREST])

    def test_a_single_point_in_nepal_is_accepted(self):
        validate_geometry_within_nepal([KATHMANDU])

    @pytest.mark.parametrize("lon,lat", [
        (80.1, 26.4),    # far west
        (88.1, 27.5),    # far east
        (84.0, 30.4),    # high north
        (84.0, 26.4),    # southern plains
    ])
    def test_the_corners_of_the_country_are_accepted(self, lon, lat):
        validate_geometry_within_nepal([Point(lon, lat)])

    def test_a_border_forest_just_outside_the_rectangle_is_accepted(self):
        """The bounds are a rectangle drawn around a country that is not one.

        A community forest on the border can legitimately carry vertices
        outside it, and survey error compounds that. Refusing a real Nepali
        forest would be a worse failure than accepting a file from just over
        the line, so the margin exists and is tested rather than assumed.
        """
        b = NEPAL_GEOGRAPHIC_BOUNDS
        validate_geometry_within_nepal([
            Point(b["lon_max"] + NEPAL_BOUNDS_MARGIN_DEG / 2, b["lat_min"]),
        ])


class TestWrongData:
    def test_the_hull_hang_cloud_is_refused(self):
        """The file behind H-HULL-1 never reaches the polygon engine now.

        That defect was fixed inside the engine as well -- a precision floor on
        coordinate magnitudes -- because this check cannot be the only line:
        the engine is also called with synthetic and projected input that this
        function never sees. Two defences, different reasons.
        """
        with pytest.raises(ValueError, match="not in Nepal"):
            validate_geometry_within_nepal([
                Point(14.297163483577762, -2.225073858507e-311),
                Point(-46.85105213901974, 5.218735761043566e-135),
                Point(34.02418080056195, 29.83614090587585),
            ])

    @pytest.mark.parametrize("name,lon,lat", [
        ("London", -0.1276, 51.5072),
        ("New York", -74.0060, 40.7128),
        ("Sydney", 151.2093, -33.8688),
        ("null island", 0.0, 0.0),
    ])
    def test_other_places_are_refused(self, name, lon, lat):
        with pytest.raises(ValueError, match="not in Nepal"):
            validate_geometry_within_nepal([Point(lon, lat)])

    def test_utm_metres_mistaken_for_degrees_are_refused(self):
        """The most likely real cause of this error, and the reason the message
        names it: a file in UTM read as if it were lat/lon.

        Nepal in UTM 45N is around easting 340000, northing 3060000. Read as
        degrees that is nowhere, and the old behaviour was to process it.
        """
        with pytest.raises(ValueError, match="not in Nepal"):
            validate_geometry_within_nepal([Point(340000.0, 3060000.0)])

    def test_the_message_says_what_was_found_and_what_was_expected(self):
        with pytest.raises(ValueError) as exc:
            validate_geometry_within_nepal([Point(-0.1276, 51.5072)])
        message = str(exc.value)
        assert "-0.1276" in message          # what the file contained
        assert "80.0" in message             # what Nepal is
        assert "CRS" in message              # the likely cause


class TestSwappedAxes:
    """Axis order confusion is not the wrong country.

    `workspace.py` already detects and corrects swapped lat/lon at import, and
    it runs AFTER this check. Refusing here would pre-empt a fix the system
    deliberately performs, and a real Nepali file would be rejected for having
    its axes the wrong way round -- which is exactly what
    `test_convert_to_builtin_swapped_point_layer_auto_fixes` caught when this
    check first landed.
    """

    def test_a_swapped_nepali_file_is_allowed_through(self):
        # (27.50, 83.50) is Nepal with the axes reversed: latitude 83.5 is
        # nowhere, but longitude 83.5 / latitude 27.5 is Rukum.
        validate_geometry_within_nepal([
            Point(27.50, 83.50), Point(27.50, 83.60), Point(27.55, 83.55),
        ])

    def test_a_swapped_foreign_file_is_still_refused(self):
        """Swapping London does not make it Nepal."""
        with pytest.raises(ValueError, match="not in Nepal"):
            validate_geometry_within_nepal([Point(51.5072, -0.1276)])


class TestItDoesNotGetInTheWay:
    def test_an_empty_list_is_accepted(self):
        validate_geometry_within_nepal([])

    def test_none_and_empty_geometries_are_ignored(self):
        validate_geometry_within_nepal([None, Polygon(), KATHMANDU])

    def test_only_empty_geometries_is_not_an_error(self):
        """Nothing to judge is not the same as judged and wrong. An empty file
        is `File contains no features`, raised earlier and more clearly."""
        validate_geometry_within_nepal([Polygon(), None])
