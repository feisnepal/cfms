"""The fire-line and river-bank opsmaps show the strips made in the sub-areas layer, not only features drawn on activities."""
from types import SimpleNamespace
from uuid import uuid4

from app.services.operational_plan import plan_collector as pc
from app.services.operational_plan.thematic_map_spec import BUILTIN_OPSMAP_SPECS

LINE = {"type": "LineString", "coordinates": [[85.0, 27.0], [85.01, 27.0]]}
POLY = {"type": "Polygon", "coordinates": [[[85.0, 27.0], [85.01, 27.0], [85.01, 27.001], [85.0, 27.0]]]}


class _Db:
    def __init__(self, sub_areas):
        self._sub = sub_areas

    def query(self, *_a):
        return SimpleNamespace(filter=lambda *_f: SimpleNamespace(first=lambda: ({"sub_areas": self._sub},)))


SUBS = [
    {"id": "a", "category": "fire_line", "name": "F1", "geometry": POLY, "centerline": LINE},
    {"id": "b", "category": "river_bank", "name": "R1", "geometry": POLY},
    {"id": "c", "category": "protected", "name": "P", "geometry": POLY},
]


def test_a_fire_line_is_drawn_as_its_centreline_and_a_river_bank_as_its_polygon():
    fl = pc._stored_strips(_Db(SUBS), uuid4(), kind="fire_line")
    rb = pc._stored_strips(_Db(SUBS), uuid4(), kind="river_bank")
    assert [(f["kind"], f["geometry"].geom_type) for f in fl] == [("fire_line", "LineString")]
    assert [(f["kind"], f["geometry"].geom_type) for f in rb] == [("river_bank", "Polygon")]


def test_a_zone_is_never_taken_for_a_strip_and_a_plan_year_has_none():
    assert {f["kind"] for f in pc._stored_strips(_Db(SUBS), uuid4())} == {"fire_line", "river_bank"}
    assert pc._stored_strips(_Db(SUBS), uuid4(), year=3) == []
    assert pc._stored_strips(_Db(SUBS), uuid4(), kind="plantation") == []


def test_both_maps_are_registered_and_ask_for_the_strips():
    assert BUILTIN_OPSMAP_SPECS["feature__fire_lines"].requires == ["fire_line_features"]
    assert BUILTIN_OPSMAP_SPECS["feature__river_banks"].requires == ["river_bank_features"]
