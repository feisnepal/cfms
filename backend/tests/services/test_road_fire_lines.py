"""FL-4b: roads inside the forest are existing fire lines - ticked by default, additive sources, placed before the boundary strips."""
import uuid

import pytest
from shapely.geometry import LineString, MultiLineString, Point, box, mapping
from sqlalchemy import text

from app.models.workspace_layer import WorkspaceLayer
from app.services import fire_line_service as fls
from app.services import road_sources as rs
from app.services import strip_geometry as sg
from app.services.fieldbook_sequence import UnitIn
from app.services.road_sources import RoadReach
from tests.services.test_fire_line_service import FOREST, H, W, X0, Y0, UNITS, _calc, _fire, cell

OUTER = sg.OUTER_LABEL
ROAD = fls.ROAD_LABEL


def reach(ref="r1", line=None, name="", highway="track", width=None, source="osm"):
    line = line or LineString([(X0 + W * 0.1, Y0 + H * 0.25), (X0 + W * 0.4, Y0 + H * 0.25)])   # inside unit A, ~200 m
    return RoadReach(source, ref, name, highway, width, line)


def roads_of(cands):
    return [c for c in cands if c.source == "road"]


# ---------------------------------------------------------------- parsing and sources
@pytest.mark.parametrize("raw,want", [("4", 4.0), ("3.5 m", 3.5), (6, 6.0), ("4,5", 4.5), (None, None), ("", None), ("wide", None),
                                      ("0.1", None), ("500", None), ("4;6", 4.0)])
def test_the_width_tag_is_read_or_ignored(raw, want):
    assert rs.parse_width(raw) == want


def test_lines_of_joins_connected_pieces_and_ignores_points():
    multi = MultiLineString([[(0, 0), (1, 0)], [(1, 0), (2, 0)], [(5, 5), (6, 5)]])
    out = rs.lines_of(multi)
    assert sorted(round(ln.length) for ln in out) == [1, 2]
    assert rs.lines_of(Point(0, 0)) == [] and rs.lines_of(None) == []


def test_a_failing_source_is_skipped_and_the_others_still_count(db):
    def broken(db, calc, area):
        raise RuntimeError("boom")

    def fine(db, calc, area):
        return [reach("ok")]

    calc = _calc(db, [])
    out = rs.road_reaches(db, calc, FOREST, sources=(broken, fine))
    assert [r.ref for r in out] == ["ok"]


def test_the_forests_own_imported_road_layer_is_a_source(db):
    calc = _calc(db, [])
    layer = WorkspaceLayer(calculation_id=calc.id, name="my roads", purpose="roads", source_format=".geojson", is_draft=False,
                           layer_data={"type": "FeatureCollection", "features": [
                               {"type": "Feature", "geometry": mapping(LineString([(X0 - 0.002, Y0 + H * 0.5), (X0 + W * 0.5, Y0 + H * 0.5)])),
                                "properties": {"name": "Ridge road", "highway": "track", "width": "4"}}]})
    db.add(layer)
    db.commit()
    out = rs._user_roads(db, calc, FOREST)
    assert len(out) == 1 and out[0].source == "user" and out[0].name == "Ridge road" and out[0].width_m == 4.0
    assert FOREST.buffer(1e-9).contains(out[0].line)          # the part outside the forest is gone


def test_the_national_road_layer_may_be_missing(db):
    calc = _calc(db, [])
    assert isinstance(rs._osm_roads(db, calc, FOREST), list)
    present = db.execute(text("SELECT to_regclass('infrastructure.road')")).scalar()
    if not present:
        assert rs._osm_roads(db, calc, FOREST) == []


# ---------------------------------------------------------------- candidates with roads
def test_a_road_inside_a_unit_is_a_ticked_candidate_of_its_own_and_the_boundary_strips_are_unchanged():
    base, _ = fls.candidates(FOREST, UNITS, [])
    cands, rep = fls.candidates(FOREST, UNITS, [], roads=[reach("77", name="Ridge track")])
    (road,) = roads_of(cands)
    assert road.name == "Ridge track" and road.unit_key == "road:osm:77|1" and road.source == "road" and road.highway == "track"
    assert road.area_ha * 10_000 == pytest.approx(road.length_m * 3.0, rel=0.03)           # no width tag: the fire-line width
    assert sorted(c.name for c in cands if c.source == "boundary") == sorted(c.name for c in base)
    assert rep["road_reaches"] == 1 and rep["road_candidates"] == 1


def test_the_osm_width_tag_sets_the_road_strip_width():
    (road,) = roads_of(fls.candidates(FOREST, UNITS, [], roads=[reach(width=6.0)])[0])
    assert road.segment_widths_m == [3.0] * (len(road.segment_widths_m))
    assert road.area_ha * 10_000 == pytest.approx(road.length_m * 6.0, rel=0.03)


def test_an_unnamed_road_is_named_by_its_class_and_a_repeat_is_numbered():
    a = reach("1", highway="path")
    b = reach("2", line=LineString([(X0 + W * 0.1, Y0 + H * 0.1), (X0 + W * 0.4, Y0 + H * 0.1)]), highway="path")
    names = [c.name for c in roads_of(fls.candidates(FOREST, UNITS, [], roads=[a, b])[0])]
    assert names == [f"{ROAD} (path)", f"{ROAD} (path) (2)"]


def test_a_stub_of_road_at_the_edge_is_not_a_fire_line():
    stub = reach("s", line=LineString([(X0 + W * 0.1, Y0 + H * 0.25), (X0 + W * 0.1 + 0.00005, Y0 + H * 0.25)]))   # ~5 m
    assert roads_of(fls.candidates(FOREST, UNITS, [], roads=[stub])[0]) == []


def test_a_road_along_a_boundary_takes_the_ground_so_the_boundary_strip_is_trimmed_and_nothing_is_counted_twice():
    shared = LineString([(X0 + W / 2, Y0), (X0 + W / 2, Y0 + H / 2)])                       # the A-B edge
    base, _ = fls.candidates(FOREST, UNITS, [])
    cands, _ = fls.candidates(FOREST, UNITS, [], roads=[reach("edge", line=shared, width=3.0)])
    assert "A-B" not in [c.name for c in cands]                                             # the 3 m road covers the 3 m strip
    assert len(roads_of(cands)) == 1
    union = sg.combined_area_ha([c.geometry_m for c in cands])
    assert sum(c.area_ha for c in cands) == pytest.approx(union, rel=1e-3)
    assert union == pytest.approx(sg.combined_area_ha([c.geometry_m for c in base]), rel=0.02)   # the same ground, now existing


def test_a_narrow_road_leaves_the_rest_of_the_boundary_strip_to_construct():
    shared = LineString([(X0 + W / 2, Y0), (X0 + W / 2, Y0 + H / 2)])
    cands, _ = fls.candidates(FOREST, UNITS, [], roads=[reach("edge", line=shared, width=1.0)])
    (road,) = roads_of(cands)
    left = [c for c in cands if c.source == "boundary" and c.name.startswith("A-B")]
    # the 3 m boundary strip minus the 1 m road down its middle: 2 m of it is still to be constructed (1 m each side)
    assert left and sum(c.area_ha for c in left) * 10_000 == pytest.approx(road.length_m * 2.0, rel=0.1)


def test_the_first_source_keeps_the_ground_where_two_describe_one_road():
    line = LineString([(X0 + W * 0.1, Y0 + H * 0.25), (X0 + W * 0.4, Y0 + H * 0.25)])
    user = reach("u1", line=line, source="user", name="Mine")
    osm = reach("o1", line=line, source="osm", name="OSM copy")
    cands, _ = fls.candidates(FOREST, UNITS, [], roads=[user, osm])
    assert [c.name for c in roads_of(cands)] == ["Mine"]                                    # the copy has nothing left


def test_a_road_outside_the_forest_area_is_clipped_away():
    private = box(X0, Y0, X0 + W * 0.5, Y0 + H * 0.5)
    from app.services.fieldbook_sequence import SubAreaIn

    cands, _ = fls.candidates(FOREST, UNITS, [SubAreaIn("Private", private, True, "private_land")], roads=[reach("p")])
    metric = sg.Metric.for_geometry(FOREST)
    for c in roads_of(cands):
        assert c.geometry_m.intersection(metric.to_m(private)).area < 1.0


# ---------------------------------------------------------------- the database sync
def _with_road_layer(db, calc, name="Ridge road"):
    db.add(WorkspaceLayer(calculation_id=calc.id, name="roads", purpose="roads", source_format=".geojson", is_draft=False,
                          layer_data={"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": name},
                                      "geometry": mapping(LineString([(X0 + W * 0.1, Y0 + H * 0.25), (X0 + W * 0.4, Y0 + H * 0.25)]))}]}))
    db.commit()


def test_sync_creates_the_road_as_a_ticked_fire_line_and_unticking_is_remembered(db):
    calc = _calc(db, [("Left", box(X0, Y0, X0 + W / 2, Y0 + H)), ("Right", box(X0 + W / 2, Y0, X0 + W, Y0 + H))])
    _with_road_layer(db, calc)
    out = fls.sync_fire_lines(db, calc.id)
    db.refresh(calc)
    road = next(s for s in _fire(calc) if s.get("source") == "road")
    assert out["state"] == "synced" and road["name"] == "Ridge road" and road["origin"] == "auto" and road["unit_key"].startswith("road:user:")
    assert fls.sync_fire_lines(db, calc.id)["state"] == "unchanged"

    rd = fls.with_decision(dict(calc.result_data), road["unit_key"], included=False)
    rd["sub_areas"] = [s for s in rd["sub_areas"] if s["id"] != road["id"]]
    calc.result_data = rd
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(calc, "result_data")
    db.commit()
    again = fls.sync_fire_lines(db, calc.id)
    db.refresh(calc)
    assert again["created"] == 0 and not [s for s in _fire(calc) if s.get("source") == "road"]


def test_a_road_added_later_is_picked_up_by_the_next_sync(db):
    calc = _calc(db, [("Left", box(X0, Y0, X0 + W / 2, Y0 + H)), ("Right", box(X0 + W / 2, Y0, X0 + W, Y0 + H))])
    fls.sync_fire_lines(db, calc.id)
    db.refresh(calc)
    assert not [s for s in _fire(calc) if s.get("source") == "road"]
    _with_road_layer(db, calc, name="New track")
    out = fls.sync_fire_lines(db, calc.id)
    db.refresh(calc)
    assert out["created"] == 1 and [s["name"] for s in _fire(calc) if s.get("source") == "road"] == ["New track"]


def test_the_parts_of_a_strip_cut_by_roads_are_numbered_along_the_line_not_by_size():
    forest_unit = [UnitIn(1, "F", FOREST)]
    cross = lambda x, ref: reach(ref, line=LineString([(X0 + W * x, Y0 - 0.0002), (X0 + W * x, Y0 + H * 0.3)]), width=4.0)
    cands, _ = fls.candidates(FOREST, forest_unit, [], roads=[cross(0.2, "a"), cross(0.5, "b"), cross(0.8, "c")])
    outer = [c for c in cands if c.source == "boundary"]
    assert len(outer) >= 3                                         # the bottom edge is cut by three roads
    keys = [c.unit_key for c in outer]
    assert keys[0].endswith("|1") and all("~" in k for k in keys[1:])
    metric = sg.Metric.for_geometry(FOREST)
    line = metric.to_m(outer[0].centerline)                        # every part of the piece shares its centerline
    along = [round(line.project(c.geometry_m.centroid)) for c in outer]
    assert along == sorted(along)
