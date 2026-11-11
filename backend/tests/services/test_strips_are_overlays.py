"""FL-2: a strip (fire line) is an overlay - invisible to every consumer that reads sub-area outlines, and exempt from the
no-overlap rule in both directions."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from shapely.geometry import box, mapping

from app.services import sub_area_service as sas

FOREST = box(0, 0, 10, 10)


def _sa(sid, category, geom, **kw):
    return {"id": sid, "name": sid, "category": category, "geometry": mapping(geom), **kw}


def _calc(*subs):
    return SimpleNamespace(id="c1", result_data={"sub_areas": list(subs)}, structure_locked=False)


@pytest.fixture(autouse=True)
def _forest(monkeypatch):
    monkeypatch.setattr(sas, "forest_extent_geometry", lambda db, calc: FOREST)


def test_a_zone_drawn_across_a_strip_keeps_all_its_ground():
    calc = _calc(_sa("fl", "fire_line", box(0, 0, 10, 2)))
    placed = sas.place_sub_area(None, calc, box(0, 1, 10, 5))
    assert placed.geometry.area == pytest.approx(40.0)
    assert placed.overlap_removed is False


def test_a_zone_still_gives_way_to_another_zone():
    calc = _calc(_sa("pl", "plantation", box(0, 0, 10, 2)))
    placed = sas.place_sub_area(None, calc, box(0, 1, 10, 5))
    assert placed.geometry.area == pytest.approx(30.0)
    assert placed.overlap_removed is True


def test_a_strip_may_overlap_a_zone_but_is_still_clipped_to_the_forest():
    calc = _calc(_sa("pl", "plantation", box(0, 0, 10, 10)))
    placed = sas.place_sub_area(None, calc, box(-2, 4, 12, 6), category="fire_line")
    assert placed.geometry.area == pytest.approx(20.0)  # 10 x 2 inside the forest, the zone did not take any of it
    assert placed.clipped_to_forest is True and placed.overlap_removed is False


def test_a_strip_may_overlap_another_strip():
    calc = _calc(_sa("fl1", "fire_line", box(0, 4, 10, 6)))
    placed = sas.place_sub_area(None, calc, box(4, 0, 6, 10), category="fire_line")
    assert placed.geometry.area == pytest.approx(20.0)


def test_detect_overlap_never_reports_a_strip():
    subs = [_sa("fl", "fire_line", box(0, 0, 10, 10)), _sa("pl", "plantation", box(8, 8, 10, 10))]
    conflicts = sas.detect_overlap(mapping(box(0, 0, 10, 10)), subs)
    assert [c["sub_area_id"] for c in conflicts] == ["pl"]


def test_the_field_book_never_reads_a_strip_outline():
    from app.services.fieldbook import extract_subarea_boundaries

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []  # forest_sub_areas is empty, as in production
    calc = _calc(_sa("fl", "fire_line", box(0, 0, 10, 2)), _sa("pl", "plantation", box(3, 3, 6, 6)))
    out = extract_subarea_boundaries(db, calc)
    assert [row[3] for row in out] == ["plantation"]


def test_a_fire_line_alone_does_not_complete_the_area_detail_step(monkeypatch):
    from app.services.operational_plan import prereq_check as pc

    monkeypatch.setattr(pc, "_result_data", lambda db, cid: {"sub_areas": [_sa("fl", "fire_line", FOREST)]})
    assert pc._has_sub_areas(None, "c1") is False
    monkeypatch.setattr(pc, "_result_data", lambda db, cid: {"sub_areas": [_sa("fl", "fire_line", FOREST), _sa("pl", "plantation", FOREST)]})
    assert pc._has_sub_areas(None, "c1") is True


def test_a_strip_is_not_a_neighbour_in_the_edit_checks():
    from app.api.editing import _features_for_store

    calc = _calc(_sa("fl", "fire_line", FOREST), _sa("pl", "plantation", box(1, 1, 2, 2)))
    assert [f["id"] for f in _features_for_store(None, calc, "sub_areas")] == ["pl"]


def test_a_strip_cannot_be_merged_into_a_zone():
    from app.api.editing import _merge_sub_areas

    calc = _calc(_sa("fl", "fire_line", box(0, 0, 10, 2)), _sa("pl", "plantation", box(0, 5, 10, 8)))
    with pytest.raises(HTTPException) as e:
        _merge_sub_areas(None, calc, ["fl", "pl"])
    assert e.value.status_code == 400
