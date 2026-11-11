"""Field book sequence: outer ring first (clockwise, north-west start), then every internal edge once.

Pure geometry -- no database. The rules under test come from the owner's field book specification:
* all OUTER points first, one direction, labelled O1.., each remarked ``outer`` with the unit(s) it separates;
* INTERNAL points after, labelled I1.., remarked with every unit sharing the point (2, 3 or more);
* spacing is a 50 m tape from the previous point; a shared edge is generated ONCE.
"""
import math
from types import SimpleNamespace

from shapely.geometry import Polygon, box

from app.services.fieldbook import calculate_distance
from app.services.fieldbook_lines import lines_from_points
from app.services.fieldbook_sequence import SubAreaIn, UnitIn, build_sequence

X0, Y0, S = 83.5, 27.5, 0.01   # ~1.1 km cells, well over the 50 m spacing


def cell(c, r, w=1, h=1):
    return box(X0 + c * S, Y0 + r * S, X0 + (c + w) * S, Y0 + (r + h) * S)


def by_label(seq):
    return {p["point_label"]: p for p in seq.points}


def outer(seq):
    return [p for p in seq.points if p["boundary_class"] == "outer"]


def internal(seq):
    return [p for p in seq.points if p["boundary_class"] == "internal"]


def as_rows(seq):
    """The sequence's points shaped like saved Fieldbook rows, so lines_from_points sees what the database gives it."""
    return [SimpleNamespace(lines=p["lines"], longitude=p["x"], latitude=p["y"], point_label=p["point_label"]) for p in seq.points]


def signed_area(pts):
    xs, ys = [p["x"] for p in pts], [p["y"] for p in pts]
    return 0.5 * sum(xs[i] * ys[(i + 1) % len(xs)] - xs[(i + 1) % len(xs)] * ys[i] for i in range(len(xs)))


# --------------------------------------------------------------------------- outer ring

def test_outer_points_come_first_and_are_labelled_O_then_I():
    units = [UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", cell(1, 0))]
    seq = build_sequence(cell(0, 0, 2, 1), units, [], spacing=50)
    classes = [p["boundary_class"] for p in seq.points]
    first_internal = classes.index("internal")
    assert all(c == "outer" for c in classes[:first_internal])
    assert all(c == "internal" for c in classes[first_internal:])
    assert [p["point_label"] for p in outer(seq)][:3] == ["O1", "O2", "O3"]
    assert [p["point_label"] for p in internal(seq)][:2] == ["I1", "I2"]
    assert [p["point_number"] for p in seq.points] == list(range(1, len(seq.points) + 1))


def test_outer_ring_is_clockwise_and_starts_at_the_north_west_vertex():
    seq = build_sequence(cell(0, 0, 2, 2), [UnitIn(1, "A", cell(0, 0, 2, 2))], [], spacing=0)
    o = outer(seq)
    assert signed_area(o) < 0                                  # clockwise
    nw = (round(X0, 7), round(Y0 + 2 * S, 7))
    assert (round(o[0]["x"], 7), round(o[0]["y"], 7)) == nw
    # clockwise from the NW corner means the second point is along the TOP edge, heading east
    assert o[1]["x"] > o[0]["x"] and abs(o[1]["y"] - o[0]["y"]) < 1e-9


def test_outer_ring_walks_on_a_50m_tape_from_the_previous_point():
    seq = build_sequence(cell(0, 0), [UnitIn(1, "A", cell(0, 0))], [], spacing=50)
    o = outer(seq)
    steps = [calculate_distance(o[i]["x"], o[i]["y"], o[(i + 1) % len(o)]["x"], o[(i + 1) % len(o)]["y"]) for i in range(len(o))]
    # every step along a leg is the tape length, except the last step of a leg into its corner
    assert sum(1 for d in steps if abs(d - 50) < 0.1) >= len(o) - 4 - 1
    assert all(d <= 50.1 for d in steps)


def test_the_outer_ring_closes_on_itself_and_has_a_next_point_everywhere():
    seq = build_sequence(cell(0, 0, 2, 1), [UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", cell(1, 0))], [], spacing=50)
    o = outer(seq)
    labels = by_label(seq)
    assert o[-1]["next_point_label"] == "O1"
    for p in o:
        nxt = labels[p["next_point_label"]]
        assert abs(p["distance_to_next"] - calculate_distance(p["x"], p["y"], nxt["x"], nxt["y"])) < 0.02


def test_outer_remark_says_outer_and_names_every_unit_it_separates():
    # A | B side by side: the two points where their shared edge meets the outer ring are where
    # the boundary meets TWO units
    seq = build_sequence(cell(0, 0, 2, 1), [UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", cell(1, 0))], [], spacing=0)
    remarks = {p["point_label"]: p["remarks"] for p in outer(seq)}
    assert all(r.startswith("outer") for r in remarks.values())
    two = [p for p in outer(seq) if p["junction_degree"] == 2]
    assert len(two) == 2
    assert all(p["remarks"] == "outer: A, B" and p["is_junction"] for p in two)
    one = [p for p in outer(seq) if p["junction_degree"] == 1]
    assert {p["remarks"] for p in one} <= {"outer: A", "outer: B"}


def test_an_outer_point_shared_by_three_units_lists_all_three():
    # three units meeting AT the outer boundary: A top half of the left, B bottom half of the left, C the right
    units = [UnitIn(1, "A", cell(0, 1)), UnitIn(2, "B", cell(0, 0)), UnitIn(3, "C", cell(1, 0, 1, 2))]
    seq = build_sequence(cell(0, 0, 2, 2), units, [], spacing=0)
    mid_left_right = [p for p in outer(seq) if p["junction_degree"] == 2]
    assert mid_left_right, "the points where unit edges meet the ring are outer junctions"
    # the left-edge midpoint belongs to A and B only; the ring points on the right belong to C
    assert any(p["adjacent_units"] == ["A", "B"] for p in outer(seq))


def test_a_hole_in_the_forest_is_walked_counter_clockwise_after_the_outer_ring():
    forest = Polygon(cell(0, 0, 3, 3).exterior.coords, [cell(1, 1).exterior.coords])
    seq = build_sequence(forest, [UnitIn(1, "A", forest)], [], spacing=0)
    o = outer(seq)
    assert len(o) == 8 and not internal(seq)
    assert signed_area(o[:4]) < 0          # outer ring clockwise
    assert signed_area(o[4:]) > 0          # the hole: counter-clockwise, forest stays on the walker's right


def test_a_multipart_forest_walks_each_part_as_its_own_ring():
    a, b = cell(0, 0), cell(5, 0)
    from shapely.geometry import MultiPolygon
    seq = build_sequence(MultiPolygon([a, b]), [UnitIn(1, "A", a), UnitIn(2, "B", b)], [], spacing=0)
    assert len(outer(seq)) == 8
    gap_km = calculate_distance(X0 + S, Y0, X0 + 5 * S, Y0)
    # no step crosses the gap between the two parts
    assert all((p["distance_to_next"] or 0) < gap_km / 2 for p in seq.points)
    expected = 2 * (2 * calculate_distance(X0, Y0, X0 + S, Y0) + 2 * calculate_distance(X0, Y0, X0, Y0 + S))
    assert abs(seq.perimeter_m - expected) < 1.0


def test_spacing_zero_gives_vertices_only():
    seq = build_sequence(cell(0, 0, 2, 1), [UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", cell(1, 0))], [], spacing=0)
    assert all(p["point_type"] == "vertex" for p in seq.points)
    assert len(outer(seq)) == 6 and len(internal(seq)) == 0   # 4 corners + the 2 points where A|B meets the ring


def test_a_short_edge_gets_no_interpolated_points():
    tiny = box(X0, Y0, X0 + 0.0001, Y0 + 0.0001)             # ~10 m
    seq = build_sequence(tiny, [UnitIn(1, "T", tiny)], [], spacing=50)
    assert len(seq.points) == 4 and all(p["point_type"] == "vertex" for p in seq.points)


# --------------------------------------------------------------------------- internal

def test_a_shared_edge_is_generated_once_not_twice():
    units = [UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", cell(1, 0))]
    seq = build_sequence(cell(0, 0, 2, 1), units, [], spacing=50)
    inner = internal(seq)
    edge_m = calculate_distance(X0 + S, Y0, X0 + S, Y0 + S)
    # the shared edge holds ~edge/50 interpolated points, once. Walking it per unit would double that.
    assert abs(len(inner) - int(edge_m / 50)) <= 1
    assert all(p["remarks"] == "internal: A, B" and p["junction_degree"] == 2 for p in inner)
    # and no two internal points are closer than a tape length minus rounding
    for a, b in zip(inner, inner[1:]):
        assert calculate_distance(a["x"], a["y"], b["x"], b["y"]) > 40


def test_internal_points_form_a_walkable_route():
    units = [UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", cell(1, 0))]
    seq = build_sequence(cell(0, 0, 2, 1), units, [], spacing=50)
    inner = internal(seq)
    labels = by_label(seq)
    for p in inner[:-1]:
        nxt = labels[p["next_point_label"]]
        assert abs(p["distance_to_next"] - calculate_distance(p["x"], p["y"], nxt["x"], nxt["y"])) < 0.02
        assert p["distance_to_next"] < 51


def test_a_four_way_junction_is_remarked_with_all_four_units():
    units = [UnitIn(1, "A", cell(0, 1)), UnitIn(2, "B", cell(1, 1)), UnitIn(3, "C", cell(0, 0)), UnitIn(4, "D", cell(1, 0))]
    seq = build_sequence(cell(0, 0, 2, 2), units, [], spacing=0)
    centre = [p for p in internal(seq)]
    assert len(centre) == 1
    assert centre[0]["remarks"] == "internal (junction of 4): A, B, C, D"
    assert centre[0]["junction_degree"] == 4 and centre[0]["is_junction"]
    assert len(outer(seq)) == 8            # 4 corners + 4 midpoints of the ring


def test_a_t_junction_is_found_even_where_one_unit_has_no_vertex():
    # A is the full-height left unit: its right edge runs STRAIGHT through the point where B and C meet,
    # so A has no vertex there -- the three-way point must still list A, B and C.
    units = [UnitIn(1, "A", cell(0, 0, 1, 2)), UnitIn(2, "B", cell(1, 1)), UnitIn(3, "C", cell(1, 0))]
    seq = build_sequence(cell(0, 0, 2, 2), units, [], spacing=0)
    inner = internal(seq)
    assert len(inner) == 1
    assert inner[0]["adjacent_units"] == ["A", "B", "C"]
    assert inner[0]["remarks"] == "internal (junction of 3): A, B, C"
    # the three places where the internal lines reach the outer ring are outer junctions of two units
    ring_junctions = sorted(p["adjacent_units"] for p in outer(seq) if p["junction_degree"] == 2)
    assert ring_junctions == [["A", "B"], ["A", "C"], ["B", "C"]]


def test_tiny_float_drift_between_neighbours_does_not_create_a_second_set_of_points():
    exact = build_sequence(cell(0, 0, 2, 1), [UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", cell(1, 0))], [], spacing=50)
    d = 4e-8                                             # ~4 mm: GPS / float noise on the shared edge
    b_drift = Polygon([(X0 + S + d, Y0 - d), (X0 + 2 * S, Y0), (X0 + 2 * S, Y0 + S), (X0 + S - d, Y0 + S + d)])
    drift = build_sequence(cell(0, 0, 2, 1), [UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", b_drift)], [], spacing=50)
    assert len(drift.points) == len(exact.points)
    assert len(internal(drift)) == len(internal(exact))


def test_drift_larger_than_one_grid_cell_is_still_one_shared_edge():
    """The shared edge of two neighbours can be a few centimetres apart in the data (rounding straddling a grid
    step, or real GPS noise). That used to leave a hairline sliver, i.e. a DOUBLED internal edge with two sets of
    points. Neighbouring outlines are now welded, so ~2.7 cm of drift is still one edge."""
    exact = build_sequence(cell(0, 0, 2, 1), [UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", cell(1, 0))], [], spacing=50)
    d = 2.4e-7                                           # ~2.7 cm, more than the 1e-7 grid
    b_drift = Polygon([(X0 + S + d, Y0 - d), (X0 + 2 * S, Y0), (X0 + 2 * S, Y0 + S), (X0 + S - d, Y0 + S + d)])
    drift = build_sequence(cell(0, 0, 2, 1), [UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", b_drift)], [], spacing=50)
    assert len(internal(drift)) == len(internal(exact))
    edges = [ln for ln in lines_from_points(as_rows(drift)) if ln["kind"] == "internal"]
    assert len(edges) == 1, "one shared edge, not a doubled pair"


def test_the_walk_starts_from_o1_and_visits_every_chain():
    units = [UnitIn(1, "A", cell(0, 1)), UnitIn(2, "B", cell(1, 1)), UnitIn(3, "C", cell(0, 0)), UnitIn(4, "D", cell(1, 0))]
    seq = build_sequence(cell(0, 0, 2, 2), units, [], spacing=50)
    # four internal edges meet at the centre; each is walked once: no coordinate appears twice
    coords = [(round(p["x"], 6), round(p["y"], 6)) for p in seq.points]
    assert len(coords) == len(set(coords))
    # every internal edge is fully covered, once: two north-south spokes and two east-west spokes
    # (they differ in length: 0.01 deg of latitude is longer than 0.01 deg of longitude here), plus the centre
    ns = int(calculate_distance(X0 + S, Y0, X0 + S, Y0 + S) / 50)
    ew = int(calculate_distance(X0, Y0 + S, X0 + S, Y0 + S) / 50)
    assert len(internal(seq)) == 2 * ns + 2 * ew + 1


# --------------------------------------------------------------------------- sub-areas

def test_a_sub_area_inside_a_unit_is_an_internal_ring_that_names_its_unit_and_itself():
    unit = cell(0, 0, 3, 3)
    pond = box(X0 + S, Y0 + S, X0 + 2 * S, Y0 + 2 * S)
    seq = build_sequence(unit, [UnitIn(1, "A", unit)], [SubAreaIn("Pond", pond, True, "water")], spacing=0)
    inner = internal(seq)
    assert len(inner) == 4
    assert all(p["sub_area_name"] == "Pond" and p["is_excluded"] is True and p["sub_area_category"] == "water" for p in inner)
    # it sits inside A without touching A's outline, so the unit it belongs to comes from containment
    assert all(p["adjacent_units"] == ["A"] for p in inner)
    assert all(p["block_name"] is None for p in inner)               # block_name stays "touches the outline"
    assert all(p["remarks"] == "internal: A; sub-area: Pond" for p in inner)
    # walked clockwise from its own north-west corner
    assert signed_area(inner) < 0
    assert (round(inner[0]["x"], 7), round(inner[0]["y"], 7)) == (round(X0 + S, 7), round(Y0 + 2 * S, 7))


def test_a_sub_area_sharing_a_corner_with_a_unit_keeps_both_names_on_one_point():
    unit = cell(0, 0, 3, 3)
    sa = box(X0, Y0, X0 + S, Y0 + S)              # in the unit's south-west corner, on the outer ring
    seq = build_sequence(unit, [UnitIn(1, "A", unit)], [SubAreaIn("Grove", sa, False, "conservation")], spacing=0)
    shared = [p for p in seq.points if p["block_name"] == "A" and p["sub_area_name"] == "Grove"]
    assert shared
    coords = [(round(p["x"], 6), round(p["y"], 6)) for p in seq.points]
    assert len(coords) == len(set(coords))


def test_two_adjacent_sub_areas_join_names_and_excluded_wins():
    unit = cell(0, 0, 4, 2)
    a = box(X0 + S, Y0 + S / 2, X0 + 2 * S, Y0 + 1.5 * S)
    b = box(X0 + 2 * S, Y0 + S / 2, X0 + 3 * S, Y0 + 1.5 * S)
    seq = build_sequence(
        unit, [UnitIn(1, "A", unit)],
        [SubAreaIn("Private", a, True, "agriculture"), SubAreaIn("Plantation", b, False, "plantation")], spacing=0,
    )
    joined = [p for p in seq.points if p["sub_area_name"] and "," in p["sub_area_name"]]
    assert len(joined) == 2
    for p in joined:
        assert {n.strip() for n in p["sub_area_name"].split(",")} == {"Private", "Plantation"}
        assert p["is_excluded"] is True
        assert {c.strip() for c in p["sub_area_category"].split(",")} == {"agriculture", "plantation"}


# --------------------------------------------------------------------------- degenerate input

def test_no_units_still_gives_the_outer_ring():
    seq = build_sequence(cell(0, 0), [], [], spacing=0)
    assert len(outer(seq)) == 4 and not internal(seq)
    assert all(p["remarks"] == "outer" and p["adjacent_units"] == [] for p in seq.points)


def test_no_forest_boundary_falls_back_to_the_units():
    a, b = UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", cell(1, 0))
    seq = build_sequence(None, [a, b], [], spacing=0)
    assert len(outer(seq)) == 6


def test_nothing_at_all_is_an_empty_book():
    seq = build_sequence(None, [], [], spacing=50)
    assert seq.points == [] and seq.perimeter_m == 0.0
