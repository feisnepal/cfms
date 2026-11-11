"""FL-4: fire-line candidates from the field book's lines, and keeping the stored strips in step (option B: all created, the
user unticks)."""
import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box, mapping, shape
from sqlalchemy.orm.attributes import flag_modified

from app.core import constants
from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.services import fire_line_service as fls
from app.services import strip_geometry as sg
from app.services.fieldbook_sequence import SubAreaIn, UnitIn
from tests.services.test_sampling_stratified import _user

X0, Y0, W, H = 85.30, 27.70, 0.0068, 0.0044  # about 670 m x 490 m near Kathmandu
OUTER = sg.OUTER_LABEL


def cell(i, j):
    return box(X0 + i * W / 2, Y0 + j * H / 2, X0 + (i + 1) * W / 2, Y0 + (j + 1) * H / 2)


FOREST = box(X0, Y0, X0 + W, Y0 + H)
UNITS = [UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", cell(1, 0)), UnitIn(3, "C", cell(0, 1)), UnitIn(4, "D", cell(1, 1))]


def names(cands):
    return sorted(c.name for c in cands)


# ---------------------------------------------------------------- candidates
def test_a_2x2_forest_has_four_internal_pairs_and_four_outer_stretches():
    cands, rep = fls.candidates(FOREST, UNITS, [])
    assert names(cands) == sorted(["A-B", "A-C", "B-D", "C-D"] + [f"{u}-{OUTER}" for u in "ABCD"])
    assert rep["unresolved_legs"] == 0
    assert len({c.unit_key for c in cands}) == len(cands)


def test_internal_strips_are_three_metres_wide_and_outer_ones_keep_the_inside_half():
    cands, _ = fls.candidates(FOREST, UNITS, [])
    by = {c.name: c for c in cands}
    assert by["A-C"].area_ha * 10_000 == pytest.approx(by["A-C"].length_m * 3.0, rel=0.03)
    # an outer stretch: 1.5 m inside only (the cut-away half lies outside the forest)
    outer = by[f"A-{OUTER}"]
    assert outer.area_ha * 10_000 == pytest.approx(outer.length_m * 1.5, rel=0.03)


def test_pieces_of_the_same_kind_never_overlap_so_the_areas_add_up():
    cands, _ = fls.candidates(FOREST, UNITS, [])
    union = sg.combined_area_ha([c.geometry_m for c in cands])
    assert sum(c.area_ha for c in cands) == pytest.approx(union, rel=1e-3)


def test_a_sub_area_inside_one_unit_gets_its_own_named_strip():
    island = box(X0 + W * 0.1, Y0 + H * 0.1, X0 + W * 0.3, Y0 + H * 0.3)
    cands, _ = fls.candidates(FOREST, UNITS, [SubAreaIn("Plantation 1", island, False, "plantation")])
    assert "A (Plantation 1)" in names(cands)
    assert len(cands) == 9


def test_private_land_is_not_fire_lined_into_the_neighbours_ground():
    private = box(X0, Y0, X0 + W * 0.2, Y0 + H * 0.2)       # a corner of the forest that is not forest
    cands, _ = fls.candidates(FOREST, UNITS, [SubAreaIn("Private", private, True, "private_land")])
    metric = sg.Metric.for_geometry(FOREST)
    pm = metric.to_m(private)
    for c in cands:
        assert c.geometry_m.intersection(pm).area < 1.0


def test_the_unit_key_does_not_change_when_nothing_changes():
    a, _ = fls.candidates(FOREST, UNITS, [])
    b, _ = fls.candidates(FOREST, list(reversed(UNITS)), [])
    assert sorted(c.unit_key for c in a) == sorted(c.unit_key for c in b)


# ---------------------------------------------------------------- the pure sync plan
def _factory():
    metric = sg.Metric.for_geometry(FOREST)
    return fls.entry_factory(metric, UNITS, {}, now="2026-10-19T00:00:00+00:00")


AREA = FOREST


def _plan(existing, cands, decisions=None, area=AREA):
    return fls.plan_sync(existing, cands, decisions or {}, area, _factory())


@pytest.fixture(scope="module")
def cands():
    return fls.candidates(FOREST, UNITS, [])[0]


def test_everything_is_created_on_the_first_run(cands):
    out, rep = _plan([], cands)
    assert rep["created"] == 8 and len(out) == 8
    assert all(e["category"] == "fire_line" and e["origin"] == "auto" and e["unit_key"] for e in out)
    assert all(e["isExcluded"] is False for e in out)


def test_a_second_run_changes_nothing(cands):
    first, _ = _plan([], cands)
    second, rep = _plan(first, cands)
    assert rep == {"created": 0, "updated": 0, "dropped": 0, "kept_edited": 0, "reclipped": 0}
    assert [e["id"] for e in second] == [e["id"] for e in first]


def test_an_unticked_name_is_not_created_and_a_stored_one_is_removed(cands):
    key = next(c.unit_key for c in cands if c.name == "A-B")
    out, rep = _plan([], cands, {key: "exclude"})
    assert rep["created"] == 7 and "A-B" not in [e["name"] for e in out]
    stored, _ = _plan([], cands)
    out, rep = _plan(stored, cands, {key: "exclude"})
    assert rep["dropped"] == 1 and len(out) == 7


def test_ticking_again_puts_it_back(cands):
    key = next(c.unit_key for c in cands if c.name == "A-B")
    rd = fls.with_decision({}, key, included=False)
    assert rd[fls.DECISIONS_KEY] == {key: "exclude"}
    assert fls.with_decision(rd, key, included=True)[fls.DECISIONS_KEY] == {}
    out, rep = _plan([], cands, rd[fls.DECISIONS_KEY])
    assert rep["created"] == 7


def test_a_moved_unedited_strip_follows_its_candidate_and_keeps_its_id(cands):
    stored, _ = _plan([], cands)
    moved = [dict(c) for c in cands[:0]]  # noqa: F841
    shifted = []
    for c in cands:
        n = fls.Candidate(**{**c.__dict__})
        if c.name == "A-B":
            n.geometry = shape(mapping(c.geometry))
            n.geometry = type(n.geometry)(n.geometry.exterior.coords) if n.geometry.geom_type == "Polygon" else n.geometry
            from shapely.affinity import translate
            n.geometry = translate(n.geometry, xoff=0.00001)
            n.geometry_m = c.geometry_m
        shifted.append(n)
    out, rep = _plan(stored, shifted)
    assert rep["updated"] == 1 and rep["created"] == 0
    old = next(e for e in stored if e["name"] == "A-B")
    new = next(e for e in out if e["name"] == "A-B")
    assert new["id"] == old["id"] and new["geometry"] != old["geometry"]


def test_an_edited_strip_is_left_alone_but_clipped_to_the_forest(cands):
    stored, _ = _plan([], cands)
    target = next(e for e in stored if e["name"] == "A-C")
    edited = dict(target)
    g = shape(target["geometry"])
    from shapely.affinity import scale
    edited["geometry"] = mapping(scale(g, xfact=1.0, yfact=1.2, origin="center"))     # the user stretched it
    out, rep = _plan([e if e is not target else edited for e in stored], cands)
    assert fls.is_edited(edited) is True
    assert rep["kept_edited"] == 1 and rep["updated"] == 0
    kept = next(e for e in out if e["id"] == target["id"])
    assert shape(kept["geometry"]).difference(AREA).area < 1e-12     # nothing outside the forest


def test_a_name_the_user_typed_is_kept_and_a_generated_one_follows(cands):
    stored, _ = _plan([], cands)
    typed = [dict(e, name="Ridge fire line") if e["name"] == "A-B" else e for e in stored]
    renamed = [fls.Candidate(**{**c.__dict__, "name": c.name + "!"}) for c in cands]
    out, _ = _plan(typed, renamed)
    names_out = {e["id"]: e["name"] for e in out}
    typed_id = next(e["id"] for e in typed if e["name"] == "Ridge fire line")
    assert names_out[typed_id] == "Ridge fire line"
    assert all(n.endswith("!") for i, n in names_out.items() if i != typed_id)


def test_a_drawn_strip_is_never_regenerated_only_clipped(cands):
    stored, _ = _plan([], cands)
    drawn = {"id": "drawn-1", "name": "Mine", "category": "fire_line", "origin": "drawn",
             "geometry": mapping(box(X0 - 0.001, Y0 + H * 0.4, X0 + W * 0.5, Y0 + H * 0.45))}
    out, rep = _plan([drawn, *stored], cands)
    mine = next(e for e in out if e["id"] == "drawn-1")
    assert mine["name"] == "Mine" and rep["reclipped"] == 1
    assert shape(mine["geometry"]).bounds[0] >= X0 - 1e-12                    # the part outside the forest is gone


def test_an_auto_strip_without_a_candidate_is_dropped_unless_it_was_edited(cands):
    stored, _ = _plan([], cands)
    gone = [e for e in stored if e["name"] != "D-" + OUTER]
    out, rep = _plan(stored, [c for c in cands if c.name != "D-" + OUTER])
    assert rep["dropped"] == 1 and len(out) == 7
    edited = [dict(e, edited=True) if e["name"] == "D-" + OUTER else e for e in stored]
    out, rep = _plan(edited, [c for c in cands if c.name != "D-" + OUTER])
    assert rep["kept_edited"] == 1 and len(out) == 8
    assert gone


def test_other_sub_areas_pass_through_untouched(cands):
    zone = {"id": "z", "name": "P", "category": "plantation", "geometry": mapping(cell(0, 0))}
    out, _ = _plan([zone], cands)
    assert out[0] is zone


def test_a_duplicate_key_is_collapsed(cands):
    stored, _ = _plan([], cands)
    out, rep = _plan([*stored, dict(stored[0], id="dup")], cands)
    assert rep["dropped"] == 1 and len(out) == 8


# ---------------------------------------------------------------- the database shell
def _calc(db, blocks):
    user = _user(db)
    calc = Calculation(id=uuid.uuid4(), user_id=user.id, forest_name="Fire Forest",
                       boundary_geom=shp_wkt.dumps(FOREST), is_draft=True, result_data={})
    db.add(calc)
    for i, (name, geom) in enumerate(blocks):
        db.add(ForestBlock(id=uuid.uuid4(), calculation_id=calc.id, name=name, block_name=name, compartment_code=None,
                           geometry=shp_wkt.dumps(geom), area_hectares=10.0, index=i, is_compartment=False, division_level=1))
    db.commit()
    return calc


def _fire(calc):
    return [s for s in (calc.result_data or {}).get("sub_areas", []) if s.get("category") == "fire_line"]


def test_sync_creates_the_fire_lines_then_skips_when_nothing_changed(db):
    calc = _calc(db, [("Left", box(X0, Y0, X0 + W / 2, Y0 + H)), ("Right", box(X0 + W / 2, Y0, X0 + W, Y0 + H))])
    first = fls.sync_fire_lines(db, calc.id)
    assert first["state"] == "synced" and first["created"] == 3          # Left-Right, Left-outer, Right-outer
    db.refresh(calc)
    assert sorted(s["name"] for s in _fire(calc)) == sorted(["Left-Right", f"Left-{OUTER}", f"Right-{OUTER}"])
    assert calc.result_data["sub_areas_count"] == 3
    assert calc.result_data[fls.STATUS_KEY]["state"] == "ok"
    assert fls.sync_fire_lines(db, calc.id)["state"] == "unchanged"
    forced = fls.sync_fire_lines(db, calc.id, force=True)
    assert forced["created"] == 0 and forced["updated"] == 0 and forced["dropped"] == 0


def test_a_deleted_fire_line_stays_deleted(db):
    calc = _calc(db, [("Left", box(X0, Y0, X0 + W / 2, Y0 + H)), ("Right", box(X0 + W / 2, Y0, X0 + W, Y0 + H))])
    fls.sync_fire_lines(db, calc.id)
    db.refresh(calc)
    victim = next(s for s in _fire(calc) if s["name"] == "Left-Right")
    rd = fls.with_decision(dict(calc.result_data), victim["unit_key"], included=False)
    rd["sub_areas"] = [s for s in rd["sub_areas"] if s["id"] != victim["id"]]
    calc.result_data = rd
    flag_modified(calc, "result_data")
    db.commit()
    out = fls.sync_fire_lines(db, calc.id)
    db.refresh(calc)
    assert out["created"] == 0 and "Left-Right" not in [s["name"] for s in _fire(calc)]


def test_overlapping_units_create_nothing_and_say_why(db, monkeypatch):
    calc = _calc(db, [("Left", box(X0, Y0, X0 + W * 0.6, Y0 + H)), ("Right", box(X0 + W * 0.4, Y0, X0 + W, Y0 + H))])
    out = fls.sync_fire_lines(db, calc.id)
    db.refresh(calc)
    assert out["state"] == "dirty_units" and out["overlap_m2"] > 0
    assert _fire(calc) == []
    assert calc.result_data[fls.STATUS_KEY]["state"] == "dirty_units"
    # the same inputs are not retried until something changes
    assert fls.sync_fire_lines(db, calc.id)["state"] == "unchanged"


def test_a_locked_structure_is_left_alone(db):
    calc = _calc(db, [("Left", box(X0, Y0, X0 + W / 2, Y0 + H)), ("Right", box(X0 + W / 2, Y0, X0 + W, Y0 + H))])
    calc.structure_locked = True
    db.commit()
    assert fls.sync_fire_lines(db, calc.id)["state"] == "locked"
    db.refresh(calc)
    assert _fire(calc) == []


def test_a_forest_without_units_gets_one_boundary_fire_line(db):
    # extract_blocks_from_calculation falls back to the boundary as a single unit
    calc = _calc(db, [])
    assert fls.sync_fire_lines(db, calc.id)["state"] == "synced"
    db.refresh(calc)
    assert [s["name"].endswith(OUTER) for s in _fire(calc)] == [True]


def test_a_forest_without_a_boundary_is_skipped(db):
    calc = _calc(db, [])
    calc.boundary_geom = None
    db.commit()
    assert fls.sync_fire_lines(db, calc.id)["state"] == "no_inputs"


def test_the_guard_constants_are_sane():
    assert 0 < constants.STRIP_MAX_UNIT_OVERLAP_FRACTION < 0.01
    assert 0 < constants.STRIP_MAX_UNRESOLVED_FRACTION < 0.2


def test_edges_that_do_not_line_up_create_nothing_and_say_why(db, monkeypatch):
    """When the same shared edge would come out as many small pieces (slivers between the neighbours), nothing is made."""
    calc = _calc(db, [("Left", box(X0, Y0, X0 + W / 2, Y0 + H)), ("Right", box(X0 + W / 2, Y0, X0 + W, Y0 + H))])
    real = fls.candidates

    def shattered(*a, **kw):
        cands, rep = real(*a, **kw)
        return cands, {**rep, "pieces": 40, "pair_groups": 5}            # 8 pieces per pair

    monkeypatch.setattr(fls, "candidates", shattered)
    out = fls.sync_fire_lines(db, calc.id)
    db.refresh(calc)
    assert out["state"] == "fragmented_edges" and out["pieces"] == 40 and out["pairs"] == 5
    assert _fire(calc) == [] and calc.result_data[fls.STATUS_KEY]["state"] == "fragmented_edges"
    assert constants.STRIP_MAX_PIECES_PER_PAIR == 2.0


def test_a_clean_forest_is_about_one_piece_per_pair():
    cands, rep = fls.candidates(FOREST, UNITS, [])
    assert rep["pieces"] == rep["pair_groups"] == 8


# ---------------------------------------------------------------- neighbouring edges that do not quite line up
def _wiggle(poly, metres, shift_x=0.0):
    """The polygon with its vertices nudged by ``metres`` (a few centimetres to decimetres) the way real units are."""
    from shapely.geometry import Polygon

    d = metres / 111_320.0
    pts = [(x + shift_x, y + (d if i % 2 else -d)) for i, (x, y) in enumerate(list(poly.exterior.coords)[:-1])]
    return Polygon(pts)


def test_snap_pulls_a_vertex_onto_the_neighbours_edge():
    a, b = cell(0, 0), cell(1, 0)
    mid = [(X0 + W / 2 + 0.1 / 111_320.0, Y0 + H / 4)]       # b gets an extra vertex 10 cm off a's straight east edge
    from shapely.geometry import Polygon
    b2 = Polygon(list(b.exterior.coords)[:2] + mid + list(b.exterior.coords)[2:])
    out = {u.name: u for u in fls.snap_units(FOREST, [UnitIn(1, "A", a), UnitIn(2, "B", b2)])}
    assert out["B"].polygon.exterior.distance(a.exterior) == pytest.approx(0, abs=1e-9)
    assert out["A"].polygon.equals(a)


def test_snap_leaves_a_unit_alone_when_it_would_change_its_area():
    far = cell(0, 0)
    out = fls.snap_units(FOREST, [UnitIn(1, "A", far)], tol_m=500.0)
    assert out[0].polygon.area == pytest.approx(far.area, rel=0.001)


def test_sloppy_neighbouring_edges_still_give_about_one_piece_per_pair():
    units = [UnitIn(1, "A", cell(0, 0)), UnitIn(2, "B", _wiggle(cell(1, 0), 0.1)),
             UnitIn(3, "C", _wiggle(cell(0, 1), 0.15)), UnitIn(4, "D", _wiggle(cell(1, 1), 0.1))]
    cands, report = fls.candidates(FOREST, units, [])
    assert report["pair_groups"] > 0
    assert report["pieces"] <= constants.STRIP_MAX_PIECES_PER_PAIR * report["pair_groups"]
