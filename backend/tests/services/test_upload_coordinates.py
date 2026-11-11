"""What a set of coordinates is: degrees, swapped, UTM (and which zone), or unknown (UP-3.1)."""
from __future__ import annotations

import numpy as np
import pytest
from pyproj import Transformer

from app.services.upload.coordinates import diagnose, utm_to_lonlat


def _to_utm(lon, lat, epsg):
    x, y = Transformer.from_crs(4326, epsg, always_xy=True).transform(np.asarray(lon, float), np.asarray(lat, float))
    return x, y


def test_degrees_inside_nepal_are_fine():
    assert diagnose([85.55, 85.57], [27.40, 27.42])["kind"] == "ok"


def test_longitude_and_latitude_the_wrong_way_round_are_recognised():
    assert diagnose([27.40, 27.42], [85.55, 85.57])["kind"] == "swapped"


def test_utm_in_eastern_nepal_is_zone_45_not_44():
    """The old detector read 343500 east as zone 44 from overlapping bounds; transformed, only zone 45 lands in Nepal."""
    d = diagnose([343500, 345500], [3030000, 3032000])
    assert d["kind"] == "utm" and d["epsg"] == 32645 and d["zone"] == 45
    lon, lat = utm_to_lonlat([343500], [3030000], d["epsg"])
    assert 85 < lon[0] < 86 and 27 < lat[0] < 28


def test_utm_near_a_zone_centre_fits_both_zones_so_the_forest_decides():
    """Eastings near 500,000 land in Nepal in zone 44 AND zone 45 (about 81.5 E or 87.5 E): without a reference the answer is 'ambiguous'."""
    x, y = _to_utm([81.5, 81.6], [28.5, 28.6], 32644)
    d = diagnose(x, y)
    assert d["kind"] == "utm_ambiguous" and {c["zone"] for c in d["candidates"]} == {44, 45}
    near_west = diagnose(x, y, reference_bbox=(81.3, 28.3, 81.8, 28.8))  # the forest the file belongs to
    assert near_west["kind"] == "utm" and near_west["zone"] == 44
    near_east = diagnose(x, y, reference_bbox=(87.2, 28.3, 87.8, 28.8))
    assert near_east["kind"] == "utm" and near_east["zone"] == 45


def test_blanks_are_ignored_and_nothing_usable_is_empty():
    assert diagnose([85.55, float("nan")], [27.4, float("nan")])["kind"] == "ok"
    assert diagnose([float("nan")], [float("nan")])["kind"] == "empty"


@pytest.mark.parametrize("xs,ys", [([1, 2], [3, 4]), ([500, 600], [100, 200]), ([200000, 300000], [10, 20])])
def test_other_numbers_are_unknown_not_guessed(xs, ys):
    assert diagnose(xs, ys)["kind"] == "unknown"
