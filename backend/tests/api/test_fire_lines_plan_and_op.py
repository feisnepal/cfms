"""FL-6: fire lines in the yearly plan (km from the strip's own length) and in the OP (existing vs still to construct)."""
from __future__ import annotations

import pytest
from shapely.geometry import LineString, box, mapping

from app.models.workspace_layer import WorkspaceLayer
from app.models.yearly_activities import ProposedYearlyActivity
from app.services import fire_line_service as fls
from app.services import strip_geometry as sg
from app.services.operational_plan import plan_extras as px
from tests.services.test_fire_line_service import H, W, X0, Y0, _calc
from tests.services.test_sub_area_plan import _master
from tests.test_sampling_add_units import _headers

OUTER = sg.OUTER_LABEL


def url(calc, tail=""):
    return f"/api/calculations/{calc.id}/fire-lines{tail}"


def _strips(calc):
    return [s for s in (calc.result_data or {}).get("sub_areas", []) if s.get("category") == "fire_line"]


@pytest.fixture()
def forest(client, db):
    calc = _calc(db, [("Left", box(X0, Y0, X0 + W / 2, Y0 + H)), ("Right", box(X0 + W / 2, Y0, X0 + W, Y0 + H))])
    db.add(WorkspaceLayer(calculation_id=calc.id, name="roads", purpose="roads", source_format=".geojson", is_draft=False,
                          layer_data={"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": "Ridge track"},
                                      "geometry": mapping(LineString([(X0 + W * 0.1, Y0 + H * 0.25), (X0 + W * 0.4, Y0 + H * 0.25)]))}]}))
    db.commit()
    fls.sync_fire_lines(db, calc.id)
    db.refresh(calc)
    return calc, _headers(client, db, calc)


# ---------------------------------------------------------------- the OP summary (pure)
def strip(name, kind, length_m, ha, units=("Left",)):
    base = {"id": name, "name": name, "category": "fire_line", "length_m": length_m, "area_hectares": ha,
            "blockBreakdown": [{"blockName": u, "area": ha} for u in units]}
    if kind == "road":
        return {**base, "origin": "auto", "source": "road"}
    if kind == "drawn":
        return {**base, "origin": "drawn", "source": "drawn"}
    return {**base, "origin": "auto", "source": "boundary"}


def test_a_forest_whose_fire_lines_were_never_made_has_no_data_to_report():
    assert px.fire_line_summary({}) == {}
    assert px.fire_line_summary({"sub_areas": [{"category": "plantation"}]}) == {}
    assert px.fire_line_summary({"fire_line_status": {"state": "dirty_units"}}) == {}


def test_a_forest_where_every_fire_line_was_unticked_reports_zero_and_an_empty_table():
    out = px.fire_line_summary({"fire_line_status": {"state": "ok"}, "sub_areas": []})
    assert out["fire_line_table"] == [] and out["fire_line_count"] == 0 and out["fire_line_total_km"] == 0


def test_the_summary_splits_what_exists_from_what_is_still_to_construct():
    rd = {"fire_line_status": {"state": "ok"}, "sub_areas": [
        strip("B-C", "boundary", 1000, 0.30), strip("A-B", "boundary", 2000, 0.60, units=("Left", "Right")),
        strip("Ridge track", "road", 500, 0.15), strip("Mine", "drawn", 250, 0.0375)]}
    out = px.fire_line_summary(rd)
    assert out["fire_line_count"] == 4
    assert out["fire_line_existing_km"] == 0.5 and out["fire_line_existing_ha"] == 0.15
    assert out["fire_line_new_km"] == 3.25 and out["fire_line_new_ha"] == 0.94
    assert out["fire_line_total_km"] == 3.75 and out["fire_line_total_ha"] == 1.09
    assert [r["नाम"] for r in out["fire_line_table"]] == ["A-B", "B-C", "Ridge track", "Mine"]     # boundary, roads, drawn
    first = out["fire_line_table"][0]
    assert first["प्रकार"] == px.FIRE_LINE_KINDS["boundary"] and first["एकाइ"] == "Left, Right"
    assert first["लम्बाइ_मि"] == 2000 and first["औसत_चौडाइ_मि"] == 3.0 and first["क्षेत्रफल_हे"] == 0.6
    assert out["fire_line_table"][2]["प्रकार"] == px.FIRE_LINE_KINDS["road"]
    assert set(px.COLUMN_ORDER["fire_line_table"]) == set(first)


def test_the_variables_are_registered():
    from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY

    for key in ("fire_line_table", "fire_line_count", "fire_line_total_km", "fire_line_total_ha", "fire_line_existing_km",
                "fire_line_existing_ha", "fire_line_new_km", "fire_line_new_ha"):
        assert key in VARIABLE_REGISTRY and VARIABLE_REGISTRY[key].source == "plan_extras"


def test_the_collector_puts_the_stored_fire_lines_in_plan_extras(db, forest):
    calc, _ = forest
    out = px.collect_plan_extras(db, str(calc.id), {})
    assert out["fire_line_count"] == len(_strips(calc)) and out["fire_line_existing_km"] > 0 and out["fire_line_new_km"] > 0
    assert any(r["प्रकार"] == px.FIRE_LINE_KINDS["road"] for r in out["fire_line_table"])


# ---------------------------------------------------------------- the yearly plan
def test_the_plan_options_are_the_fire_line_activities(client, db, forest):
    calc, h = forest
    km = _master(db, unit="कि.मि.", map_kind="fire_line")
    _master(db, unit="हेक्टर", map_kind="plantation")
    ids = [a["id"] for a in client.get(url(calc, "/plan-options"), headers=h).json()["activities"]]
    assert km.id in ids and len(ids) >= 1


def test_planning_the_fire_lines_starts_each_at_its_own_length_in_km(client, db, forest):
    calc, h = forest
    km = _master(db, unit="कि.मि.", map_kind="fire_line", budget="1000")
    r = client.post(url(calc, "/plan"), json={"potential_activity_id": km.id}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    boundary = [s for s in _strips(calc) if s.get("source") != "road"]
    assert body["created"] == len(boundary) and body["skipped_roads"] == 1 and body["no_unit"] == []
    lines = db.query(ProposedYearlyActivity).filter(ProposedYearlyActivity.calculation_id == calc.id).all()
    assert len(lines) == len(boundary)
    for line in lines:
        strip_ = next(s for s in boundary if str(s["id"]) == str(line.sub_area_id))
        assert float(line.default_quantity) == pytest.approx(strip_["length_m"] / 1000.0, abs=0.006)       # the plan and the map agree (a plan quantity keeps two decimals: 10 m)


def test_planning_twice_changes_nothing_and_roads_can_be_included(client, db, forest):
    calc, h = forest
    km = _master(db, unit="कि.मि.", map_kind="fire_line")
    client.post(url(calc, "/plan"), json={"potential_activity_id": km.id}, headers=h)
    again = client.post(url(calc, "/plan"), json={"potential_activity_id": km.id}, headers=h).json()
    assert again["created"] == 0 and again["existing"] >= 1
    with_roads = client.post(url(calc, "/plan"), json={"potential_activity_id": km.id, "include_roads": True}, headers=h).json()
    assert with_roads["created"] == 1 and with_roads["skipped_roads"] == 0                                   # just the road, now


def test_only_the_chosen_fire_lines_are_planned(client, db, forest):
    calc, h = forest
    km = _master(db, unit="कि.मि.", map_kind="fire_line")
    pick = next(s for s in _strips(calc) if s.get("source") != "road")
    out = client.post(url(calc, "/plan"), json={"potential_activity_id": km.id, "strip_ids": [pick["id"]]}, headers=h).json()
    assert out["created"] == 1 and out["strips"] == 1


def test_the_fire_line_plan_table_of_the_op_reads_them(client, db, forest):
    calc, h = forest
    km = _master(db, unit="कि.मि.", map_kind="fire_line")
    client.post(url(calc, "/plan"), json={"potential_activity_id": km.id}, headers=h)
    table = px.fire_line_plan(px.plan_lines(db, str(calc.id)), ["2083/84"] * 10)
    assert table and sum(float(r["परिमाण_कि.मी"]) for r in table if r.get("आ.व.")) > 0


def test_a_missing_activity_is_a_friendly_404(client, forest):
    calc, h = forest
    r = client.post(url(calc, "/plan"), json={"potential_activity_id": 987654}, headers=h)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"


def test_planning_needs_the_owner_and_an_unlocked_structure(client, db, forest):
    calc, h = forest
    km = _master(db, unit="कि.मि.", map_kind="fire_line")
    calc.structure_locked = True
    db.commit()
    assert client.post(url(calc, "/plan"), json={"potential_activity_id": km.id}, headers=h).status_code == 423
    assert client.get(url(calc, "/plan-options")).status_code in (401, 403)


def test_the_table_keeps_its_column_order_after_the_database_reorders_the_keys():
    import json

    from app.services.operational_plan.table_columns import ordered_headers

    rd = {"fire_line_status": {"state": "ok"}, "sub_areas": [strip("A-B", "boundary", 2000, 0.6)]}
    row = px.fire_line_summary(rd)["fire_line_table"][0]
    scrambled = json.loads(json.dumps(dict(sorted(row.items(), key=lambda kv: (len(kv[0].encode()), kv[0].encode()))), ensure_ascii=False))
    assert list(scrambled) != px.COLUMN_ORDER["fire_line_table"]
    assert ordered_headers("fire_line_table", [scrambled]) == px.COLUMN_ORDER["fire_line_table"]
