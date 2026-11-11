"""Field book lines: the outer points close into a polygon outline; internal edges are open lines.

Owner's rule (2026-10-04): the outer points, joined in order, must look like a polygon (closed). The internal points
are grouped into lines that are NOT closed -- and, because ``I5`` and ``I6`` can be the end of one edge and the start
of a different one, nothing may ever join consecutive internal points just because their numbers are consecutive.
"""
import io
import uuid
from types import SimpleNamespace

import pytest
from shapely.geometry import MultiPolygon, Polygon, box

from app.services.fieldbook import calculate_distance
from app.services.fieldbook_lines import line_is_closed, line_kind, lines_from_points
from app.services.fieldbook_sequence import SubAreaIn, UnitIn, build_sequence

X0, Y0, S = 83.5, 27.5, 0.01
TAPE_M = 50.0


def cell(c, r, w=1, h=1):
    return box(X0 + c * S, Y0 + r * S, X0 + (c + w) * S, Y0 + (r + h) * S)


def as_rows(seq):
    """The sequence's points shaped like saved Fieldbook rows, so lines_from_points sees what the database gives it."""
    return [
        SimpleNamespace(lines=p["lines"], longitude=p["x"], latitude=p["y"], point_label=p["point_label"])
        for p in seq.points
    ]


def grid_2x2(spacing=50):
    units = [UnitIn(1, "A", cell(0, 1)), UnitIn(2, "B", cell(1, 1)), UnitIn(3, "C", cell(0, 0)), UnitIn(4, "D", cell(1, 0))]
    return build_sequence(cell(0, 0, 2, 2), units, [], spacing=spacing)


# --------------------------------------------------------------------------- outer = closed polygon outline

def test_the_outer_points_are_one_closed_line_that_draws_as_the_forest_polygon():
    seq = grid_2x2()
    lines = lines_from_points(as_rows(seq))
    outer = [ln for ln in lines if ln["kind"] == "outer"]
    assert [ln["id"] for ln in outer] == ["O-1"]
    ring = outer[0]
    assert ring["closed"] is True
    assert ring["coordinates"][0] == ring["coordinates"][-1]           # drawn closed: back to the first point
    assert ring["labels"] == [p["point_label"] for p in seq.points if p["boundary_class"] == "outer"]
    # ...and it IS the forest: the polygon the points trace has the forest's area
    assert abs(Polygon(ring["coordinates"]).area - cell(0, 0, 2, 2).area) / cell(0, 0, 2, 2).area < 1e-4


def test_every_outer_point_is_on_the_outer_ring_and_nothing_else_is():
    seq = grid_2x2()
    for p in seq.points:
        if p["boundary_class"] == "outer":
            assert "O-1" in p["lines"]
        else:
            assert not any(line_id.startswith("O-") for line_id in p["lines"])


# --------------------------------------------------------------------------- internal = open lines

def test_internal_lines_are_open_never_closed():
    seq = grid_2x2()
    internal = [ln for ln in lines_from_points(as_rows(seq)) if ln["kind"] == "internal"]
    assert len(internal) == 4
    for ln in internal:
        assert ln["closed"] is False and not line_is_closed(ln["id"])
        assert ln["id"].startswith("I-")
        assert ln["coordinates"][0] != ln["coordinates"][-1], "an internal edge must not loop back on itself"


def test_consecutive_internal_numbers_are_not_joined_when_they_belong_to_different_edges():
    seq = grid_2x2()
    pts = [p for p in seq.points if p["boundary_class"] == "internal"]
    far_pairs = [
        (a, b) for a, b in zip(pts, pts[1:])
        if calculate_distance(a["x"], a["y"], b["x"], b["y"]) > TAPE_M * 1.5
    ]
    assert far_pairs, "the fixture must contain consecutive I-numbers that are NOT neighbours on the ground"
    for a, b in far_pairs:
        shared = set(a["lines"]) & set(b["lines"])
        assert all(abs(a["lines"][i] - b["lines"][i]) != 1 for i in shared), (
            f"{a['point_label']} and {b['point_label']} are not adjacent on the ground and must not be joined"
        )


def test_no_drawn_segment_of_any_line_is_longer_than_one_tape_length():
    seq = grid_2x2()
    for ln in lines_from_points(as_rows(seq)):
        for a, b in zip(ln["coordinates"], ln["coordinates"][1:]):
            assert calculate_distance(a[0], a[1], b[0], b[1]) <= TAPE_M + 0.2, (ln["id"], a, b)


def test_a_junction_belongs_to_every_line_that_meets_there():
    seq = grid_2x2()
    centre = next(p for p in seq.points if p["junction_degree"] == 4)
    assert len([i for i in centre["lines"] if i.startswith("I-")]) == 4
    lines = {ln["id"]: ln for ln in lines_from_points(as_rows(seq))}
    for line_id in centre["lines"]:
        # the shared point is an END of each edge: the edge is rebuilt with it, not stopped short
        assert centre["point_label"] in (lines[line_id]["labels"][0], lines[line_id]["labels"][-1])
    # the line that first reached it owns it
    assert centre["line_id"] in centre["lines"]


def test_every_internal_edge_runs_from_a_point_that_already_exists():
    seq = grid_2x2()
    for ln in lines_from_points(as_rows(seq)):
        if ln["kind"] != "internal":
            continue
        ends = (ln["labels"][0], ln["labels"][-1])
        by_label = {p["point_label"]: p for p in seq.points}
        # each end is an outer point or a junction -- an edge never stops in the middle of nowhere
        assert all(by_label[e]["boundary_class"] == "outer" or by_label[e]["junction_degree"] >= 3 for e in ends)


# --------------------------------------------------------------------------- the one internal exception

def test_a_free_standing_loop_is_its_own_closed_line():
    unit = cell(0, 0, 3, 3)
    pond = box(X0 + S, Y0 + S, X0 + 2 * S, Y0 + 2 * S)
    seq = build_sequence(unit, [UnitIn(1, "A", unit)], [SubAreaIn("Pond", pond, True, "water")], spacing=0)
    lines = lines_from_points(as_rows(seq))
    loop = [ln for ln in lines if ln["id"].startswith("L-")]
    assert len(loop) == 1 and loop[0]["kind"] == "internal" and loop[0]["closed"] is True
    assert loop[0]["coordinates"][0] == loop[0]["coordinates"][-1]
    assert len(loop[0]["labels"]) == 4                               # the start point is not listed twice
    assert abs(Polygon(loop[0]["coordinates"]).area - pond.area) / pond.area < 1e-4
    # the loop is separate from the open edges and from the outer ring
    assert not (set(loop[0]["labels"]) & set(next(ln for ln in lines if ln["id"] == "O-1")["labels"]))


# --------------------------------------------------------------------------- awkward shapes

def test_a_t_junction_gives_three_open_edges_that_meet_at_one_point():
    units = [UnitIn(1, "A", cell(0, 0, 1, 2)), UnitIn(2, "B", cell(1, 1)), UnitIn(3, "C", cell(1, 0))]
    seq = build_sequence(cell(0, 0, 2, 2), units, [], spacing=0)
    internal = [ln for ln in lines_from_points(as_rows(seq)) if ln["kind"] == "internal"]
    assert len(internal) == 3 and not any(ln["closed"] for ln in internal)
    hub = next(p for p in seq.points if p["junction_degree"] == 3)
    assert all(hub["point_label"] in (ln["labels"][0], ln["labels"][-1]) for ln in internal)


def test_a_hole_in_the_forest_is_its_own_closed_outer_line():
    forest = Polygon(cell(0, 0, 3, 3).exterior.coords, [cell(1, 1).exterior.coords])
    seq = build_sequence(forest, [UnitIn(1, "A", forest)], [], spacing=0)
    outer = [ln for ln in lines_from_points(as_rows(seq)) if ln["kind"] == "outer"]
    assert [ln["id"] for ln in outer] == ["O-1", "O-2"] and all(ln["closed"] for ln in outer)
    assert not any(ln["kind"] == "internal" for ln in lines_from_points(as_rows(seq)))


def test_a_forest_in_two_parts_is_two_closed_rings_with_nothing_drawn_across_the_gap():
    a, b = cell(0, 0), cell(5, 0)
    seq = build_sequence(MultiPolygon([a, b]), [UnitIn(1, "A", a), UnitIn(2, "B", b)], [], spacing=50)
    rings = [ln for ln in lines_from_points(as_rows(seq)) if ln["kind"] == "outer"]
    assert len(rings) == 2 and all(r["closed"] for r in rings)
    assert all(calculate_distance(p[0], p[1], q[0], q[1]) <= TAPE_M + 0.2
               for r in rings for p, q in zip(r["coordinates"], r["coordinates"][1:]))


def test_the_line_perimeter_matches_the_forest_perimeter():
    seq = grid_2x2()
    ring = next(ln for ln in lines_from_points(as_rows(seq)) if ln["id"] == "O-1")
    assert abs(ring["length_m"] - seq.perimeter_m) < 1.0


def test_line_helpers():
    assert line_kind("O-2") == "outer" and line_kind("I-7") == "internal" and line_kind("L-1") == "internal"
    assert line_is_closed("O-1") and line_is_closed("L-3") and not line_is_closed("I-4")
    assert lines_from_points([]) == []
    assert lines_from_points([SimpleNamespace(lines=None, longitude=1, latitude=1, point_label="O1")]) == []


# --------------------------------------------------------------------------- through the database and the exports

def test_saved_points_carry_their_lines_and_rebuild_the_same_lines(db):
    from tests.services.test_fieldbook_generation import _gen, _points, _two_blocks
    calc = _two_blocks(db, name="Lines CF")
    _gen(db, calc, spacing=50.0)
    rows = _points(db, calc.id)
    assert all(r.line_id for r in rows) and all(r.lines for r in rows)
    lines = {ln["id"]: ln for ln in lines_from_points(rows)}
    assert lines["O-1"]["closed"] and lines["O-1"]["coordinates"][0] == lines["O-1"]["coordinates"][-1]
    internal = [ln for ln in lines.values() if ln["kind"] == "internal"]
    assert internal and not any(ln["closed"] for ln in internal)


def test_geojson_draws_the_outer_ring_closed_and_the_internal_edge_open(db):
    from app.services.export import export_fieldbook_geojson
    from tests.services.test_fieldbook_generation import _gen, _two_blocks
    calc = _two_blocks(db, name="Lines CF")
    _gen(db, calc, spacing=50.0)
    feats = export_fieldbook_geojson(db, calc.id)["features"]

    points = [f for f in feats if f["properties"]["layer"] == "point"]
    lines = [f for f in feats if f["properties"]["layer"] == "line"]
    assert points and lines and all(f["geometry"]["type"] == "Point" for f in points)
    assert all(f["geometry"]["type"] == "LineString" for f in lines)

    ring = next(f for f in lines if f["properties"]["line_id"] == "O-1")
    assert ring["properties"]["closed"] is True and ring["properties"]["kind"] == "outer"
    assert ring["geometry"]["coordinates"][0] == ring["geometry"]["coordinates"][-1]

    edges = [f for f in lines if f["properties"]["kind"] == "internal"]
    assert edges
    for f in edges:
        assert f["properties"]["closed"] is False
        assert f["geometry"]["coordinates"][0] != f["geometry"]["coordinates"][-1]


def test_gpx_has_a_route_per_line_and_only_the_outer_one_is_closed(db):
    import xml.etree.ElementTree as ET
    from app.services.export import export_fieldbook_gpx
    from tests.services.test_fieldbook_generation import _gen, _two_blocks
    calc = _two_blocks(db, name="Lines CF")
    _gen(db, calc, spacing=50.0)
    root = ET.fromstring(export_fieldbook_gpx(db, calc.id))
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    routes = {r.find("g:name", ns).text: [(p.get("lat"), p.get("lon")) for p in r.findall("g:rtept", ns)] for r in root.findall("g:rte", ns)}
    assert "O-1" in routes and any(k.startswith("I-") for k in routes)
    assert routes["O-1"][0] == routes["O-1"][-1]                         # closed outline
    for name, pts in routes.items():
        if name.startswith("I-"):
            assert pts[0] != pts[-1]                                      # open


def test_excel_lines_sheet_says_which_lines_close(db):
    from openpyxl import load_workbook
    from app.services.export import export_fieldbook_excel
    from tests.services.test_fieldbook_generation import _gen, _two_blocks
    calc = _two_blocks(db, name="Lines CF")
    _gen(db, calc, spacing=50.0)
    ws = load_workbook(io.BytesIO(export_fieldbook_excel(db, calc.id)))["Lines"]
    rows = {r[0].value: [c.value for c in r] for r in ws.iter_rows(min_row=2)}
    assert rows["O-1"][2] == "closed (polygon outline)"
    seq = rows["O-1"][7]
    assert seq.startswith("O1 → O2") and seq.endswith("→ O1")            # the ring comes back to its start
    internal = [v for k, v in rows.items() if k.startswith("I-")]
    assert internal and all(v[2] == "open (not closed)" for v in internal)
    assert all(v[7].split(" → ")[0] != v[7].split(" → ")[-1] for v in internal)


def test_csv_has_a_line_column(db):
    import csv
    from app.services.export import export_fieldbook_csv
    from tests.services.test_fieldbook_generation import _gen, _two_blocks
    calc = _two_blocks(db, name="Lines CF")
    _gen(db, calc, spacing=50.0)
    rows = list(csv.reader(io.StringIO(export_fieldbook_csv(db, calc.id).decode("utf-8"))))
    col = rows[0].index("रेखा (Line)")
    assert rows[1][col] == "O-1"
    assert any(r[col].startswith("I-") for r in rows[1:])
