"""RB-2: river banks - 20 m each side of a river, inside the forest area; the same sync, ticking and drawing as the fire line."""
import pytest
from shapely.geometry import LineString, MultiLineString, box, mapping
from sqlalchemy.orm.attributes import flag_modified

from app.core.constants import RIVER_BANK_SIDE_M
from app.core.sub_area_kinds import RIVER_BANK, real_sub_areas
from app.services import fire_line_service as fls
from app.services import river_bank_service as rbs
from app.services import river_sources as rvs
from app.services import strip_geometry as sg
from app.services.fieldbook_sequence import SubAreaIn, UnitIn
from app.services.river_sources import NO_NAME, RiverReach
from tests.services.test_fire_line_service import FOREST, H, UNITS, W, X0, Y0, _calc


def river(name="Jorchhanga Khola", pts=None, source="river84", ref=None):
    pts = pts or [(X0 + W * 0.1, Y0 + H * 0.5), (X0 + W * 0.9, Y0 + H * 0.5)]        # west to east across both halves
    return RiverReach(source, ref or name or "-", name or NO_NAME, LineString(pts))


# ---------------------------------------------------------------- sources
def test_pieces_of_one_river_are_joined_and_an_unnamed_river_has_the_agreed_name():
    rows = [
        ("Khola", LineString([(0, 0), (1, 0)])), ("Khola", LineString([(1, 0), (2, 0)])),     # one river in two rows
        ("Khola", LineString([(5, 5), (6, 5)])),                                              # the same name, elsewhere: its own reach
        (None, LineString([(0, 9), (1, 9)])), ("  ", MultiLineString([[(1, 9), (2, 9)]])),     # no name
    ]
    reaches = rvs._rows_to_reaches("river84", rows)
    assert [(r.name, round(r.line.length)) for r in reaches] == [("Khola", 2), ("Khola", 1), (NO_NAME, 2)]
    assert [r.ref for r in reaches] == ["Khola", "Khola", "-"]
    assert NO_NAME == "नाम नखुलेको खोला"


def test_the_fine_network_is_used_only_when_the_named_rivers_have_nothing(db):
    calc = _calc(db, [])
    named, fine = [river("A", source="river84")], [river("B", source="river_line")]
    assert [r.name for r in rvs.river_reaches(db, calc, FOREST, sources=(lambda d, c, a: named, lambda d, c, a: fine))] == ["A"]
    assert [r.name for r in rvs.river_reaches(db, calc, FOREST, sources=(lambda d, c, a: [], lambda d, c, a: fine))] == ["B"]
    assert rvs.river_reaches(db, calc, FOREST, sources=(lambda d, c, a: [], lambda d, c, a: [])) == []


def test_a_failing_river_source_is_skipped(db):
    def boom(d, c, a):
        raise RuntimeError("no such table")

    calc = _calc(db, [])
    assert [r.name for r in rvs.river_reaches(db, calc, FOREST, sources=(boom, lambda d, c, a: [river("Ok")]))] == ["Ok"]


def test_the_river_layers_may_be_missing(db):
    calc = _calc(db, [])
    assert isinstance(rvs._river84(db, calc, FOREST), list) and isinstance(rvs._river_line(db, calc, FOREST), list)


# ---------------------------------------------------------------- names
def test_the_name_is_the_units_it_runs_through_then_the_river():
    assert rbs.bank_name([], "Khola") == "Khola"
    assert rbs.bank_name(["SC3", "SC4"], "Khola") == "SC3-SC4 (Khola)"
    assert rbs.bank_name(["A", "B", "C", "D", "E"], "Khola") == "A-B-C-… (Khola)"


# ---------------------------------------------------------------- candidates
def test_a_river_across_two_units_has_a_40_metre_bank_named_after_both():
    (c,) = rbs.river_candidates(FOREST, UNITS, [], [river()])[0]
    assert c.name == "A-B-C-… (Jorchhanga Khola)"                                   # it runs through all four units: shortened
    assert c.source == "river" and c.river_name == "Jorchhanga Khola" and c.unit_key == "river:river84:Jorchhanga Khola|1"
    assert c.segment_widths_m == [RIVER_BANK_SIDE_M]
    assert c.area_ha * 10_000 == pytest.approx(c.length_m * 2 * RIVER_BANK_SIDE_M, rel=0.02)


def test_a_river_inside_one_unit_is_named_by_that_unit():
    inside_a = river(pts=[(X0 + W * 0.05, Y0 + H * 0.2), (X0 + W * 0.45, Y0 + H * 0.2)])
    (c,) = rbs.river_candidates(FOREST, UNITS, [], [inside_a])[0]
    assert c.name == "A (Jorchhanga Khola)"


def test_the_bank_never_leaves_the_forest_area():
    edge = river(pts=[(X0 + W * 0.2, Y0 + H * 0.02), (X0 + W * 0.8, Y0 + H * 0.02)])       # ~10 m from the south edge
    (c,) = rbs.river_candidates(FOREST, UNITS, [], [edge])[0]
    metric = sg.Metric.for_geometry(FOREST)
    assert metric.to_m(FOREST).buffer(0.01).contains(c.geometry_m)
    assert c.area_ha * 10_000 < c.length_m * 2 * RIVER_BANK_SIDE_M * 0.8                       # part of it was cut off
    private = box(X0, Y0, X0 + W, Y0 + H * 0.2)
    cut, _ = rbs.river_candidates(FOREST, UNITS, [SubAreaIn("Private", private, True, "private_land")], [edge])
    assert cut == []                                                                          # private land is not forest


def test_a_tributary_is_trimmed_against_the_river_so_the_areas_add_up():
    main = river("Main")
    trib = river("Trib", pts=[(X0 + W * 0.5, Y0 + H * 0.1), (X0 + W * 0.5, Y0 + H * 0.5)])   # joins the main river
    cands, _ = rbs.river_candidates(FOREST, UNITS, [], [main, trib])
    union = sg.combined_area_ha([c.geometry_m for c in cands])
    assert sum(c.area_ha for c in cands) == pytest.approx(union, rel=1e-3)
    assert len(cands) == 2 and cands[0].river_name == "Main"


def test_a_stub_of_river_at_the_edge_is_dropped():
    stub = river(pts=[(X0 + W * 0.1, Y0 + H * 0.5), (X0 + W * 0.1 + 0.00005, Y0 + H * 0.5)])
    assert rbs.river_candidates(FOREST, UNITS, [], [stub])[0] == []


def test_two_reaches_with_the_same_units_and_river_are_numbered():
    a = river(pts=[(X0 + W * 0.05, Y0 + H * 0.2), (X0 + W * 0.2, Y0 + H * 0.2)])
    b = river(pts=[(X0 + W * 0.25, Y0 + H * 0.2), (X0 + W * 0.4, Y0 + H * 0.2)])
    names = [c.name for c in rbs.river_candidates(FOREST, UNITS, [], [a, b])[0]]
    assert names == ["A (Jorchhanga Khola)", "A (Jorchhanga Khola) (2)"]


# ---------------------------------------------------------------- the database sync
@pytest.fixture()
def one_river(monkeypatch):
    monkeypatch.setattr(rvs, "SOURCES", (lambda db, calc, area: [river()],))


def _banks(calc):
    return [s for s in (calc.result_data or {}).get("sub_areas", []) if s.get("category") == RIVER_BANK]


def _two_units(db):
    return _calc(db, [("Left", box(X0, Y0, X0 + W / 2, Y0 + H)), ("Right", box(X0 + W / 2, Y0, X0 + W, Y0 + H))])


def test_sync_creates_the_bank_with_its_river_and_skips_when_unchanged(db, one_river):
    calc = _two_units(db)
    out = rbs.sync_river_banks(db, calc.id)
    db.refresh(calc)
    (bank,) = _banks(calc)
    assert out["state"] == "synced" and out["created"] == 1
    assert bank["name"] == "Left-Right (Jorchhanga Khola)" and bank["river_name"] == "Jorchhanga Khola"
    assert bank["origin"] == "auto" and bank["source"] == "river" and bank["isExcluded"] is False
    assert {b["blockName"] for b in bank["blockBreakdown"]} == {"Left", "Right"}
    assert calc.result_data[fls.RIVER_KIND.status_key]["state"] == "ok"
    assert calc.result_data[fls.RIVER_KIND.catalogue_key][0]["river_name"] == "Jorchhanga Khola"
    assert rbs.sync_river_banks(db, calc.id)["state"] == "unchanged"
    assert fls.sync_fire_lines(db, calc.id)["state"] == "synced"                       # the other kind is independent
    db.refresh(calc)
    assert len(_banks(calc)) == 1                                                       # and does not touch the bank
    assert all(s["category"] != RIVER_BANK for s in real_sub_areas(calc.result_data["sub_areas"]))


def test_an_unticked_bank_stays_unticked(db, one_river):
    calc = _two_units(db)
    rbs.sync_river_banks(db, calc.id)
    db.refresh(calc)
    key = _banks(calc)[0]["unit_key"]
    fls.apply_decisions(db, calc.id, [{"unit_key": key, "included": False}], fls.RIVER_KIND)
    db.refresh(calc)
    assert _banks(calc) == [] and calc.result_data[fls.RIVER_KIND.decisions_key] == {key: "exclude"}
    assert rbs.sync_river_banks(db, calc.id, force=True)["created"] == 0
    fls.apply_decisions(db, calc.id, [{"unit_key": key, "included": True}], fls.RIVER_KIND)
    db.refresh(calc)
    assert len(_banks(calc)) == 1


def test_overlapping_units_do_not_stop_a_river_bank(db, one_river):
    calc = _calc(db, [("Left", box(X0, Y0, X0 + W * 0.6, Y0 + H)), ("Right", box(X0 + W * 0.4, Y0, X0 + W, Y0 + H))])
    assert fls.sync_fire_lines(db, calc.id)["state"] == "dirty_units"                  # the fire line refuses ...
    assert rbs.sync_river_banks(db, calc.id)["state"] == "synced"                      # ... the bank only needs the boundary
    db.refresh(calc)
    assert len(_banks(calc)) == 1


def test_a_forest_without_a_river_has_none_and_says_so(db, monkeypatch):
    monkeypatch.setattr(rvs, "SOURCES", (lambda db, calc, area: [],))
    calc = _two_units(db)
    assert rbs.sync_river_banks(db, calc.id)["created"] == 0
    db.refresh(calc)
    assert _banks(calc) == [] and calc.result_data[fls.RIVER_KIND.status_key]["state"] == "ok"


def test_an_edited_bank_is_left_alone_by_a_regenerate(db, one_river):
    calc = _two_units(db)
    rbs.sync_river_banks(db, calc.id)
    db.refresh(calc)
    rd = dict(calc.result_data)
    rd["sub_areas"] = [dict(s, edited=True) if s["category"] == RIVER_BANK else s for s in rd["sub_areas"]]
    calc.result_data = rd
    flag_modified(calc, "result_data")
    db.commit()
    out = rbs.sync_river_banks(db, calc.id, force=True)
    assert out["kept_edited"] == 1 and out["created"] == 0
