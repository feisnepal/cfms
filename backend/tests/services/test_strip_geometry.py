"""FL-3: the pure strip geometry (no database)."""
import random

import pytest
from shapely.geometry import LineString, MultiPolygon, Polygon, box

from app.services import strip_geometry as sg
from app.services.strip_geometry import OUTER_LABEL, Stretch


# ---------------------------------------------------------------- the strip
def test_a_straight_strip_is_length_times_both_sides():
    poly = sg.strip_polygon(LineString([(0, 0), (100, 0)]), 1.5)
    assert poly.area == pytest.approx(100 * 3.0)


def test_each_segment_can_have_its_own_width():
    poly = sg.strip_polygon(LineString([(0, 0), (50, 0), (100, 0)]), [1.0, 2.0])
    assert poly.area == pytest.approx(50 * 2.0 + 50 * 4.0)
    assert poly.bounds[1] == pytest.approx(-2.0) and poly.bounds[3] == pytest.approx(2.0)


def test_a_bend_with_one_width_is_the_ordinary_round_buffer():
    line = LineString([(0, 0), (50, 0), (50, 50)])
    expect = line.buffer(2.0, cap_style="flat", join_style="round")
    assert sg.strip_polygon(line, 2.0).symmetric_difference(expect).area < 0.5


def test_a_bend_only_adds_the_narrower_segments_join_fill():
    poly = sg.strip_polygon(LineString([(0, 0), (50, 0), (50, 50)]), [1.0, 4.0])
    allowed = LineString([(0, 0), (50, 0)]).buffer(1.0, cap_style="flat").union(
        LineString([(50, 0), (50, 50)]).buffer(4.0, cap_style="flat")
    )
    # the only part outside the two flat-ended rectangles is the narrower segment's join disc on the outside of the bend
    # (a quarter disc of radius 1 = pi/4); nothing of the wider width bulges past the wider segment
    assert poly.difference(allowed).area <= 3.14159 / 4 + 1e-3
    assert poly.bounds[2] == pytest.approx(54.0)


def test_a_closed_ring_is_a_loop():
    ring = LineString([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])
    poly = sg.strip_polygon(ring, 1.5)
    assert poly.area == pytest.approx(400 * 3.0, rel=0.01)
    assert len(poly.interiors) == 1  # a ring of ground, not a disc


def test_bad_widths_and_lines_are_refused():
    line = LineString([(0, 0), (10, 0), (20, 0)])
    with pytest.raises(ValueError):
        sg.strip_polygon(line, [1.0])  # 2 segments, 1 width
    with pytest.raises(ValueError):
        sg.strip_polygon(line, 0)
    with pytest.raises(ValueError):
        sg.strip_polygon(line, [1.0, -1.0])


# ---------------------------------------------------------------- clipping
def test_a_strip_on_the_outer_boundary_keeps_only_its_inside_half():
    forest = box(0, 0, 100, 100)
    strip = sg.strip_polygon(LineString([(0, 0), (0, 100)]), 1.5)
    assert sg.clip_to_area(strip, forest).area == pytest.approx(100 * 1.5)


def test_a_strip_wholly_outside_is_nothing():
    assert sg.clip_to_area(box(200, 200, 210, 210), box(0, 0, 100, 100)) is None


def test_the_forest_area_is_the_boundary_minus_private_land():
    area = sg.forest_area(box(0, 0, 100, 100), [box(0, 0, 10, 10), None])
    assert area.area == pytest.approx(10_000 - 100)
    strip = sg.strip_polygon(LineString([(0, 5), (50, 5)]), 1.5)
    assert sg.clip_to_area(strip, area).area == pytest.approx(strip.area - 10 * 3.0)


# ---------------------------------------------------------------- trimming and figures
def test_trimming_makes_the_areas_add_up_to_the_union():
    a, b, c = box(0, 0, 10, 10), box(5, 0, 15, 10), box(0, 5, 15, 15)
    out = sg.trim_same_kind([a, b, c])
    assert out[0].area == pytest.approx(100)
    assert sum(g.area for g in out) == pytest.approx(a.union(b).union(c).area)
    assert len(out) == 3


def test_trimming_keeps_the_order_and_marks_a_swallowed_piece():
    out = sg.trim_same_kind([box(0, 0, 10, 10), box(2, 2, 4, 4), None])
    assert out[0].area == pytest.approx(100) and out[1] is None and out[2] is None


def test_explode_gives_single_parts_largest_first_and_drops_noise():
    multi = MultiPolygon([box(0, 0, 1, 1), box(10, 0, 14, 4), Polygon([(20, 0), (20.001, 0), (20, 0.001)])])
    assert [round(p.area) for p in sg.explode(multi)] == [16, 1]
    assert sg.explode(None) == []


def test_two_kinds_are_reported_in_full_and_combined_once():
    fire, river = [box(0, 0, 100, 10)], [box(50, 0, 150, 10)]       # 1000 m2 each, 500 m2 shared
    assert sg.area_ha(fire[0]) == pytest.approx(0.1)
    assert sg.overlap_ha(fire[0], river[0]) == pytest.approx(0.05)
    assert sg.combined_area_ha(fire, river) == pytest.approx(0.15)
    assert sg.combined_area_ha([], []) == 0.0


def test_length_and_empty_geometry():
    assert sg.length_m(LineString([(0, 0), (30, 40)])) == pytest.approx(50)
    assert sg.length_m(None) == 0.0 and sg.area_ha(None) == 0.0


# ---------------------------------------------------------------- the metric CRS
def test_wgs_round_trip_and_area_in_the_forests_utm_zone():
    wgs = box(85.30, 27.70, 85.31, 27.71)
    m = sg.Metric.for_geometry(wgs)
    assert m.epsg == 32645
    metric = m.to_m(wgs)
    assert metric.area == pytest.approx(985.0 * 1106.0, rel=0.01)  # 0.01 deg lon x 0.01 deg lat at 27.7 N
    assert m.to_wgs(metric).symmetric_difference(wgs).area < 1e-12


# ---------------------------------------------------------------- centerlines
def S(pair, coords, line, order):
    return Stretch(tuple(pair), tuple(coords), line, order)


def test_one_shared_edge_broken_at_a_junction_is_one_piece():
    pieces = sg.build_pieces([
        S(("SC14", "SC15"), [(0, 0), (40, 0)], "I-1", 1),
        S(("SC14", "SC15"), [(40, 0), (70, 0)], "I-2", 1),
    ])
    assert len(pieces) == 1 and pieces[0].length == pytest.approx(70)
    assert pieces[0].lines == {"I-1", "I-2"}


def test_the_stretches_are_joined_whichever_way_they_point():
    pieces = sg.build_pieces([
        S(("A", "B"), [(0, 0), (40, 0)], "I-1", 1),
        S(("A", "B"), [(70, 0), (40, 0)], "I-2", 1),  # points back toward the first
    ])
    assert len(pieces) == 1 and pieces[0].length == pytest.approx(70)


def test_separate_stretches_of_one_pair_stay_separate_and_are_numbered():
    pieces = sg.build_pieces([
        S(("SC1", "SC2"), [(0, 0), (40, 0)], "I-1", 1),
        S(("SC1", "SC2"), [(500, 0), (560, 0)], "I-9", 1),
    ])
    assert sg.piece_names(pieces) == ["SC1-SC2", "SC1-SC2 (2)"]


def test_a_three_way_node_is_not_a_continuation():
    pieces = sg.build_pieces([
        S(("A", "B"), [(0, 0), (40, 0)], "I-1", 1),
        S(("A", "B"), [(40, 0), (80, 0)], "I-2", 1),
        S(("A", "B"), [(40, 0), (40, 50)], "I-3", 1),
    ])
    assert len(pieces) == 3


def test_a_tiny_stretch_goes_into_the_longer_neighbour_on_its_line_and_takes_its_pair():
    pieces = sg.build_pieces([
        S(("P1", "P2"), [(0, 0), (100, 0)], "I-7", 1),
        S(("P3", "P4"), [(100, 0), (104, 0)], "I-7", 2),   # 4 m
        S(("P5", "P6"), [(104, 0), (154, 0)], "I-7", 3),
    ])
    assert [(p.pair, round(p.length)) for p in pieces] == [(("P1", "P2"), 104), (("P5", "P6"), 50)]


def test_a_tiny_stretch_with_no_neighbour_is_removed():
    pieces = sg.build_pieces([
        S(("A", "B"), [(0, 0), (100, 0)], "I-1", 1),
        S(("C", "D"), [(300, 0), (305, 0)], "I-2", 1),
    ])
    assert [p.pair for p in pieces] == [("A", "B")]


def test_a_tiny_stretch_is_never_merged_into_another_line():
    pieces = sg.build_pieces([
        S(("A", "B"), [(0, 0), (100, 0)], "I-1", 1),
        S(("C", "D"), [(100, 0), (105, 0)], "I-2", 1),  # touches I-1's end, but it is a different line
    ])
    assert [p.pair for p in pieces] == [("A", "B")] and pieces[0].length == pytest.approx(100)


def test_merging_can_make_two_pieces_of_one_pair_adjacent_and_they_are_joined():
    pieces = sg.build_pieces([
        S(("P1", "P2"), [(0, 0), (50, 0)], "I-1", 1),
        S(("X", "Y"), [(50, 0), (53, 0)], "I-1", 2),     # 3 m, between two stretches of P1-P2
        S(("P1", "P2"), [(53, 0), (93, 0)], "I-1", 3),
    ])
    assert len(pieces) == 1 and pieces[0].pair == ("P1", "P2") and pieces[0].length == pytest.approx(93)


def test_the_minimum_length_is_the_constant_and_can_be_overridden():
    stretch = [S(("A", "B"), [(0, 0), (9, 0)], "I-1", 1)]
    assert sg.build_pieces(stretch) == []                        # 9 m < 10 m
    assert len(sg.build_pieces(stretch, min_length_m=5)) == 1


def test_the_result_does_not_depend_on_the_input_order():
    base = [
        S(("A", "B"), [(0, 0), (60, 0)], "I-1", 1),
        S(("A", "B"), [(60, 0), (90, 0)], "I-2", 1),
        S(("C", "D"), [(0, 50), (80, 50)], "I-3", 1),
        S(("C", "E"), [(80, 50), (83, 50)], "I-3", 2),
        S(("E", "F"), [(83, 50), (150, 50)], "I-3", 3),
    ]
    want = [(p.pair, round(p.length, 3)) for p in sg.build_pieces(base)]
    for seed in range(5):
        shuffled = base[:]
        random.Random(seed).shuffle(shuffled)
        assert [(p.pair, round(p.length, 3)) for p in sg.build_pieces(shuffled)] == want


# ---------------------------------------------------------------- names
def test_natural_order_and_the_outer_label_goes_last():
    assert sg.pair_label(("SC10", "SC2")) == "SC2-SC10"
    assert sg.pair_label((OUTER_LABEL, "SC1")) == f"SC1-{OUTER_LABEL}"
    assert sg.natural_key("SC2") < sg.natural_key("SC10")


# ---------------------------------------------------------------- one border drawn twice
def test_a_border_the_field_book_lists_twice_is_one_piece():
    """Each unit draws the shared edge with its own vertices: two chains between the same junctions, every node degree 4."""
    pieces = sg.build_pieces([
        S(("SC1", "SC2"), [(0, 0), (50, 0), (100, 0)], "I-1", 1),
        S(("SC1", "SC2"), [(0, 0), (30, 0.3), (70, -0.2), (100, 0)], "I-2", 1),
        S(("SC1", "SC2"), [(100, 0), (150, 0)], "I-3", 1),
    ])
    assert len(pieces) == 1
    assert pieces[0].line.length == pytest.approx(150, abs=1.0)


def test_two_different_borders_between_the_same_junctions_are_not_collapsed():
    """A unit that wraps round another can meet it twice between the same two nodes: far apart, not a duplicate (they ring up)."""
    pieces = sg.build_pieces([
        S(("SC1", "SC2"), [(0, 0), (50, 0), (100, 0)], "I-1", 1),
        S(("SC1", "SC2"), [(0, 0), (50, 40), (100, 0)], "I-2", 1),
    ])
    assert sum(p.line.length for p in pieces) == pytest.approx(100 + 2 * (50**2 + 40**2) ** 0.5, abs=1.0)
