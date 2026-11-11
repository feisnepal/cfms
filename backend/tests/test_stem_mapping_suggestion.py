"""Shelterwood: where to do stem mapping (owner rule, 2026-10-12) - the unit with the most volume of trees of 40 cm DBH and above."""
from __future__ import annotations

import uuid

import pytest

from app.models.field_inventory import FieldInventoryBlockSummary, FieldInventoryCalculation
from app.services.sustainable_fm import stem_mapping_suggestion as svc

BD_RICH = {  # a lot of mature stock
    "4_10": {"count_per_ha": 99, "timber_m3_per_ha": 1},
    "10_20": {"count_per_ha": 40, "timber_m3_per_ha": 8},
    "20_30": {"count_per_ha": 20, "timber_m3_per_ha": 14},
    "30_40": {"count_per_ha": 10, "timber_m3_per_ha": 12},
    "40_50": {"count_per_ha": 8, "timber_m3_per_ha": 30},
    "60_plus": {"count_per_ha": 4, "timber_m3_per_ha": 40},
}
BD_POOR = {  # many young trees, little mature stock
    "10_20": {"count_per_ha": 200, "timber_m3_per_ha": 50},
    "20_30": {"count_per_ha": 80, "timber_m3_per_ha": 60},
    "40_50": {"count_per_ha": 1, "timber_m3_per_ha": 5},
}


def test_the_three_ranges_give_trees_and_volume_separately_and_ignore_trees_under_10_cm():
    r = svc.ranges_from_breakdown(BD_RICH)
    assert r["from10_to40"] == {"count_per_ha": 70.0, "volume_m3_per_ha": 34.0}
    assert r["from40"] == {"count_per_ha": 12.0, "volume_m3_per_ha": 70.0}
    assert r["from10"] == {"count_per_ha": 82.0, "volume_m3_per_ha": 104.0}  # the 4-10 cm class (99 trees) is not counted


def test_an_unreadable_breakdown_is_none_not_zero():
    assert svc.ranges_from_breakdown(None) is None
    assert svc.ranges_from_breakdown({}) is None
    assert svc.ranges_from_breakdown({"weird": {"count_per_ha": 5}}) is None


def test_the_highest_volume_of_40_cm_and_above_is_marked_even_if_another_unit_has_more_total_stock():
    rows = [
        {"block_name": "poor", "ranges": svc.ranges_from_breakdown(BD_POOR)},
        {"block_name": "rich", "ranges": svc.ranges_from_breakdown(BD_RICH)},
        {"block_name": "no data", "ranges": None},
    ]
    out = svc.rank(rows)
    assert [r["block_name"] for r in out] == ["rich", "poor", "no data"]
    assert [r["suggested"] for r in out] == [True, False, False]
    assert out[1]["ranges"]["from10"]["volume_m3_per_ha"] > out[0]["ranges"]["from10"]["volume_m3_per_ha"]


def test_nothing_is_suggested_when_no_unit_has_trees_of_40_cm_and_above():
    out = svc.rank([{"block_name": "a", "ranges": {"from40": {"volume_m3_per_ha": 0.0}}}, {"block_name": "b", "ranges": None}])
    assert not any(r["suggested"] for r in out)


@pytest.fixture()
def forest(db):
    from app.models.calculation import Calculation
    from app.models.user import User

    owner = User(email=f"sw-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="Shelterwood")
    db.add(owner)
    db.flush()
    c = Calculation(user_id=owner.id, forest_name=f"SW {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.flush()
    fi = FieldInventoryCalculation(user_id=owner.id, calculation_id=c.id, uploaded_filename="f.csv", status="completed")
    db.add(fi)
    db.flush()
    for name, bd in (("C1", BD_POOR), ("C2", BD_RICH), ("C3", BD_RICH)):
        db.add(FieldInventoryBlockSummary(field_inventory_calculation_id=fi.id, block_name=name, total_sample_plots=3, dbh_class_breakdown=bd))
    db.commit()
    return c


def _sfm(method="shelterwood_periodic_block"):
    return {
        "felling_series": [{"id": 5, "method": method}, {"id": 9, "method": "selection_felling_cycle"}],
        "blocks": [
            {"block_name": "C1", "area_ha": 10, "felling_series_id": 5},
            {"block_name": "C2", "area_ha": 12, "felling_series_id": 5},
            {"block_name": "C3", "area_ha": 8, "felling_series_id": 9},  # a selection series: not part of the shelterwood ranking
        ],
    }


def test_only_the_units_of_a_shelterwood_series_are_ranked_and_the_best_is_suggested(db, forest):
    out = svc.build_suggestion(forest, db, sfm=_sfm())
    assert out["applies"] is True
    assert [r["block_name"] for r in out["rows"]] == ["C2", "C1"]
    assert out["suggested"] == "C2"
    assert out["rows"][0]["plot_count"] == 3 and out["rows"][0]["has_inventory"] is True


def test_it_does_not_apply_when_no_series_uses_shelterwood(db, forest):
    out = svc.build_suggestion(forest, db, sfm=_sfm(method="selection_felling_cycle"))
    assert out == {"applies": False, "series": [], "rows": [], "suggested": None}


def test_a_unit_without_an_inventory_is_listed_but_never_suggested(db, forest):
    sfm = _sfm()
    sfm["blocks"].append({"block_name": "C9", "area_ha": 5, "felling_series_id": 5})
    out = svc.build_suggestion(forest, db, sfm=sfm)
    last = out["rows"][-1]
    assert last["block_name"] == "C9" and last["has_inventory"] is False and last["suggested"] is False


def test_the_endpoint_serves_the_ranking_to_the_owner_and_refuses_everyone_else(client, db, monkeypatch):
    from app.models.calculation import Calculation
    from tests.integration.test_user_group_journey import _register

    headers, uid = _register(client)
    c = Calculation(user_id=uid, forest_name=f"SW API {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.flush()
    fi = FieldInventoryCalculation(user_id=uid, calculation_id=c.id, uploaded_filename="f.csv", status="completed")
    db.add(fi)
    db.flush()
    db.add(FieldInventoryBlockSummary(field_inventory_calculation_id=fi.id, block_name="C2", total_sample_plots=2, dbh_class_breakdown=BD_RICH))
    db.commit()
    monkeypatch.setattr("app.services.sustainable_fm.sfm_service.get_sfm", lambda calc, db_: {
        "felling_series": [{"id": 5, "method": "shelterwood_periodic_block"}],
        "blocks": [{"block_name": "C2", "area_ha": 12, "felling_series_id": 5}],
    })
    r = client.get(f"/api/calculations/{c.id}/sustainable-fm/stem-mapping-suggestion", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applies"] and body["suggested"] == "C2" and body["rows"][0]["ranges"]["from40"]["volume_m3_per_ha"] == 70.0

    other, _ = _register(client)
    assert client.get(f"/api/calculations/{c.id}/sustainable-fm/stem-mapping-suggestion", headers=other).status_code in (403, 404)
