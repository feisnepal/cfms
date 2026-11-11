"""RB-3: the river bank is a protection area (owner, 2026-10-19) - not productive. It reaches the area model, Table 5, the sampling
stratum and the field-inventory plot zone through ONE definition, ``PROTECTION_SUB_AREA_CATEGORIES``; a fire line reaches none of
them."""
import uuid

import pytest
from shapely.geometry import box, mapping
from sqlalchemy.orm.attributes import flag_modified

from app.core.sub_area_kinds import PROTECTION_SUB_AREA_CATEGORIES, is_protection_category, zones_and_protection
from app.models.calculation import Calculation
from app.services.forest_units.area_model import area_figures
from app.services.tree_cover_analysis import calculate_block_area_details
from tests.services.test_block_area_detail_assignment import _FakeDB
from tests.services.test_fire_line_service import FOREST, H, W, X0, Y0, _calc


def entry(category, geom, name=None, **kw):
    return {"id": str(uuid.uuid4()), "name": name or category, "category": category, "geometry": mapping(geom),
            "isExcluded": category == "private_land", "blockBreakdown": [], **kw}


def with_subs(db, calc, *subs):
    rd = dict(calc.result_data or {})
    rd["sub_areas"] = list(subs)
    calc.result_data = rd
    flag_modified(calc, "result_data")
    db.commit()
    return calc


# a band across the middle of the forest: 20% of its height, full width
BAND = box(X0, Y0 + H * 0.4, X0 + W, Y0 + H * 0.6)
HALF = box(X0, Y0, X0 + W, Y0 + H * 0.5)


def _calc_one(db):
    return _calc(db, [("All", FOREST)])


# ---------------------------------------------------------------- the one definition
def test_one_definition_of_protection():
    assert PROTECTION_SUB_AREA_CATEGORIES == ("protected", "river_bank")
    assert is_protection_category("river_bank") and is_protection_category("protected")
    assert not is_protection_category("fire_line") and not is_protection_category("plantation")
    subs = [{"category": c} for c in ("plantation", "fire_line", "river_bank", "protected", "private_land")]
    assert [s["category"] for s in zones_and_protection(subs)] == ["plantation", "river_bank", "protected", "private_land"]


# ---------------------------------------------------------------- the area model
def test_a_river_bank_is_protected_forest_and_leaves_the_effective_area(db):
    calc = with_subs(db, _calc_one(db), entry("river_bank", BAND))
    a = area_figures(db, calc, tree_cover_ratio=1.0)
    assert a.protected_ha / a.outer_ha == pytest.approx(0.2, rel=0.02)
    assert a.effective_ha / a.outer_ha == pytest.approx(0.8, rel=0.02)


def test_a_fire_line_changes_no_area_figure(db):
    calc = with_subs(db, _calc_one(db), entry("fire_line", BAND))
    a = area_figures(db, calc, tree_cover_ratio=1.0)
    assert a.protected_ha == 0 and a.effective_ha == pytest.approx(a.outer_ha, rel=1e-6)


def test_a_river_bank_over_a_protected_zone_is_counted_once(db):
    calc = with_subs(db, _calc_one(db), entry("protected", HALF), entry("river_bank", BAND))
    a = area_figures(db, calc, tree_cover_ratio=1.0)
    union = HALF.union(BAND).area / FOREST.area                                  # 0.5 + 0.1 (the part of the band above the half)
    assert a.protected_ha / a.outer_ha == pytest.approx(union, rel=0.02)
    assert a.protected_ha / a.outer_ha < 0.5 + 0.2                                # not the sum


def test_the_bank_cannot_claim_private_land(db):
    private = box(X0, Y0 + H * 0.4, X0 + W, Y0 + H * 0.5)                         # the lower half of the band is private
    calc = with_subs(db, _calc_one(db), entry("private_land", private), entry("river_bank", BAND))
    a = area_figures(db, calc, tree_cover_ratio=1.0)
    assert a.protected_ha / a.outer_ha == pytest.approx(0.1, rel=0.03)            # only the half of the band that is forest


# ---------------------------------------------------------------- Table 5
UNITS = [{"block_name": "C1", "area_hectares": 100.0, "geometry": mapping(box(84.00, 28.00, 84.10, 28.10))},
         {"block_name": "C2", "area_hectares": 100.0, "geometry": mapping(box(84.10, 28.00, 84.20, 28.10))}]
BANK_IN_C1 = box(84.00, 28.02, 84.10, 28.04)
ZONE_IN_C1 = box(84.00, 28.03, 84.10, 28.06)


def details(*subs):
    return {d["block_name"]: d for d in calculate_block_area_details(_FakeDB(), UNITS, [entry(*s) if isinstance(s, tuple) else s for s in subs])}


def test_table_5_counts_a_river_bank_as_protected_area():
    d = details(("river_bank", BANK_IN_C1, "Bank"))
    assert d["C1"]["protected_area_ha"] > 15 and d["C2"]["protected_area_ha"] == 0


def test_table_5_ignores_a_fire_line():
    assert details(("fire_line", BANK_IN_C1, "Line")) == details()                # every column, every unit: as if it were not there


def test_table_5_counts_protected_ground_once_where_a_bank_and_a_protected_zone_overlap():
    both = details(("protected", ZONE_IN_C1, "Z"), ("river_bank", BANK_IN_C1, "B"))["C1"]["protected_area_ha"]
    zone = details(("protected", ZONE_IN_C1, "Z"))["C1"]["protected_area_ha"]
    bank = details(("river_bank", BANK_IN_C1, "B"))["C1"]["protected_area_ha"]
    assert both < zone + bank - 1.0                                               # the overlap is not added twice
    assert both == pytest.approx(details(("protected", box(84.00, 28.02, 84.10, 28.06), "U"))["C1"]["protected_area_ha"], rel=0.01)


# ---------------------------------------------------------------- sampling and the field-inventory plot zone
def test_a_unit_mostly_on_the_bank_is_a_protected_stratum_unit():
    from shapely import wkt

    from app.services.guideline_sampling import classify_block_by_majority_area

    unit = box(0, 0, 1, 1)
    bank = {"category": "river_bank", "isExcluded": False, "geometry": mapping(box(0, 0, 1, 0.8))}
    line = {"category": "fire_line", "isExcluded": False, "geometry": mapping(box(0, 0, 1, 0.8))}
    assert classify_block_by_majority_area(wkt.dumps(unit), [bank]) is True
    assert classify_block_by_majority_area(wkt.dumps(unit), [line]) is False


def test_the_protected_zone_summary_includes_the_bank_but_not_the_fire_line(db):
    from app.services.guideline_sampling import detect_protected_zones

    calc = with_subs(db, _calc_one(db), entry("river_bank", BAND, "Bank", area_hectares=2.0), entry("fire_line", BAND, "Line", area_hectares=1.0))
    info = detect_protected_zones(calc)
    assert info["has_protected"] is True and info["protected_zone_names"] == ["Bank"]


def test_plots_on_a_bank_are_in_the_protected_zone(db):
    from app.services.field_inventory_service import protected_polygon_for_calc

    calc = with_subs(db, _calc_one(db), entry("river_bank", BAND), entry("fire_line", HALF))
    poly = protected_polygon_for_calc(db, calc.id)
    assert poly is not None
    assert poly.intersects(box(X0, Y0 + H * 0.45, X0 + W * 0.1, Y0 + H * 0.55)) and not poly.intersects(box(X0, Y0, X0 + W * 0.1, Y0 + H * 0.1))
    assert protected_polygon_for_calc(db, with_subs(db, _calc_one(db), entry("fire_line", HALF)).id) is None
