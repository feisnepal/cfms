"""The overlap resolver (``forest_units.overlap_repair``): the SMALLER sibling keeps the contested ground."""
from shapely.geometry import MultiPolygon, box
from shapely.ops import unary_union

from app.services.forest_units.overlap_repair import Unit, overlap_area, resolve


def unit(i, name, geom):
    return Unit(i, name, geom, geom.area)          # degrees2 stand in for hectares: only the ORDER matters here


def apply(units, changes):
    new = {c.id: c.geometry for c in changes}
    return [Unit(u.id, u.name, new.get(u.id, u.geom), new.get(u.id, u.geom).area) for u in units]


def test_disjoint_siblings_need_nothing():
    assert resolve([unit(1, "A", box(0, 0, 1, 1)), unit(2, "B", box(1, 0, 2, 1))]) == []


def test_the_smaller_keeps_the_ground_and_the_larger_gives_it_up():
    small, big = unit(1, "small", box(0, 0, 1, 1)), unit(2, "big", box(0.5, 0, 3, 1))
    (ch,) = resolve([big, small])                       # order of the input does not matter
    assert ch.name == "big" and ch.lost_to == ["small"] and ch.parts_dropped == 0
    assert ch.geometry.equals(box(1, 0, 3, 1))


def test_no_ground_is_lost_and_none_is_left_twice():
    units = [unit(1, "a", box(0, 0, 2, 2)), unit(2, "b", box(1, 1, 4, 4)), unit(3, "c", box(3, 0, 5, 3))]
    before = unary_union([u.geom for u in units])
    after = apply(units, resolve(units))
    assert overlap_area(after) < 1e-12
    assert unary_union([u.geom for u in after]).symmetric_difference(before).area < 1e-12


def test_a_three_way_overlap_goes_to_the_smallest_only():
    a, b, c = unit(1, "a", box(0, 0, 4, 4)), unit(2, "b", box(0, 0, 5, 5)), unit(3, "c", box(0, 0, 6, 6))
    after = {u.name: u.geom for u in apply([a, b, c], resolve([a, b, c]))}
    assert after["a"].equals(box(0, 0, 4, 4))
    assert after["b"].area == box(0, 0, 5, 5).area - box(0, 0, 4, 4).area
    assert after["c"].area == box(0, 0, 6, 6).area - box(0, 0, 5, 5).area


def test_a_cut_that_splits_a_unit_reports_the_new_fragment():
    big = unit(2, "big", box(0, 0, 10, 4))
    wall = unit(1, "wall", box(4, -1, 5, 5))            # cuts the big one in two
    (ch,) = resolve([big, wall])
    assert ch.parts_dropped == 1 and len(ch.fragments) == 1
    assert ch.geometry.geom_type == "Polygon" and ch.geometry.area > ch.fragments[0].area


def test_a_unit_that_was_already_in_two_parts_keeps_them():
    two = MultiPolygon([box(0, 0, 10, 4), box(20, 0, 21, 1)])
    big = unit(2, "big", two)
    small = unit(1, "small", box(0, 0, 1, 1))
    (ch,) = resolve([big, small])
    assert ch.parts_dropped == 0 and ch.geometry.geom_type == "MultiPolygon" and len(ch.geometry.geoms) == 2


def test_a_unit_swallowed_whole_is_left_for_a_person():
    small, big = unit(1, "small", box(0, 0, 5, 5)), unit(2, "big", box(1, 1, 2, 2))
    # "big" is bigger by the stand-in area only if its area is larger; make it so
    big = Unit(2, "big", box(1, 1, 2, 2), 99.0)
    assert resolve([small, big]) == []
