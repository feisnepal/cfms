"""RB-4: the river-bank routes (same handlers as the fire line) and the OP's river-bank variables."""
from __future__ import annotations

import pytest
from shapely.geometry import LineString, box, mapping

from app.services import fire_line_service as fls
from app.services import river_bank_service as rbs
from app.services import river_sources as rvs
from app.services import strip_geometry as sg
from app.services.operational_plan import plan_extras as px
from app.services.river_sources import RiverReach
from tests.services.test_fire_line_service import H, W, X0, Y0, _calc
from tests.test_sampling_add_units import _headers


def url(calc, tail=""):
    return f"/api/calculations/{calc.id}/river-banks{tail}"


def _river():
    return RiverReach("river84", "Jorchhanga Khola", "Jorchhanga Khola",
                      LineString([(X0 + W * 0.1, Y0 + H * 0.5), (X0 + W * 0.9, Y0 + H * 0.5)]))


@pytest.fixture()
def forest(client, db, monkeypatch):
    monkeypatch.setattr(rvs, "SOURCES", (lambda d, c, a: [_river()],))
    calc = _calc(db, [("Left", box(X0, Y0, X0 + W / 2, Y0 + H)), ("Right", box(X0 + W / 2, Y0, X0 + W, Y0 + H))])
    rbs.sync_river_banks(db, calc.id)
    fls.sync_fire_lines(db, calc.id)
    db.refresh(calc)
    return calc, _headers(client, db, calc)


def drawn(widths=20.0, extra=None):
    line = LineString([(X0 + W * 0.05, Y0 + H * 0.2), (X0 + W * 0.3, Y0 + H * 0.2), (X0 + W * 0.45, Y0 + H * 0.3)])
    return {"centerline": mapping(line), "widths_m": widths, **(extra or {})}


# ---------------------------------------------------------------- the routes
def test_the_list_shows_the_bank_and_only_banks(client, forest):
    calc, h = forest
    body = client.get(url(calc), headers=h).json()
    assert body["kind"] == "river_bank" and body["status"]["state"] == "ok"
    (row,) = body["rows"]
    assert row["name"] == "Left-Right (Jorchhanga Khola)" and row["group"] == "river" and row["ticked"] and row["river_name"] == "Jorchhanga Khola"
    assert set(body["totals"]) == {"river"}
    fire = client.get(f"/api/calculations/{calc.id}/fire-lines", headers=h).json()
    assert fire["kind"] == "fire_line" and all(r["group"] != "river" for r in fire["rows"])           # the lists do not mix


def test_unticking_and_ticking_a_bank(client, forest):
    calc, h = forest
    key = client.get(url(calc), headers=h).json()["rows"][0]["unit_key"]
    off = client.post(url(calc, "/decisions"), json={"changes": [{"unit_key": key, "included": False}]}, headers=h).json()
    assert off["totals"] == {} and off["rows"][0]["ticked"] is False and off["rows"][0]["strip_id"] is None
    assert client.post(url(calc, "/regenerate"), json={}, headers=h).json()["totals"] == {}
    on = client.post(url(calc, "/decisions"), json={"changes": [{"unit_key": key, "included": True}]}, headers=h).json()
    assert on["totals"]["river"]["count"] == 1 and on["rows"][0]["strip_id"]


def test_a_bank_decision_never_touches_the_fire_lines(client, forest):
    calc, h = forest
    before = client.get(f"/api/calculations/{calc.id}/fire-lines", headers=h).json()["totals"]
    key = client.get(url(calc), headers=h).json()["rows"][0]["unit_key"]
    client.post(url(calc, "/decisions"), json={"changes": [{"unit_key": key, "included": False}]}, headers=h)
    assert client.get(f"/api/calculations/{calc.id}/fire-lines", headers=h).json()["totals"] == before


def test_drawing_a_river_line_makes_a_bank_with_the_widths_given(client, forest):
    calc, h = forest
    p = client.post(url(calc, "/preview"), json=drawn([10.0, 25.0]), headers=h).json()
    assert p["segment_widths_m"] == [10.0, 25.0] and p["area_ha"] > 0 and p["parts"] == 1
    first = client.post(url(calc), json=drawn(20.0, {"name": "My stream", "client_id": "r-1"}), headers=h)
    assert first.status_code == 201, first.text
    assert client.post(url(calc), json=drawn(20.0, {"name": "My stream", "client_id": "r-1"}), headers=h).json()["replayed"] is True
    listed = client.get(url(calc), headers=h).json()
    assert [d["name"] for d in listed["drawn"]] == ["My stream"] and listed["totals"]["drawn"]["count"] == 1
    sid = listed["drawn"][0]["strip_id"]
    narrow = listed["drawn"][0]["area_ha"]
    r = client.patch(url(calc, f"/{sid}/widths"), json={"widths_m": [40.0, 40.0]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["area_ha"] == pytest.approx(narrow * 2, rel=0.1)


def test_a_bank_cannot_be_widened_through_the_fire_line_route(client, forest):
    calc, h = forest
    sid = client.get(url(calc), headers=h).json()["rows"][0]["strip_id"]
    r = client.patch(f"/api/calculations/{calc.id}/fire-lines/{sid}/widths", json={"widths_m": 5.0}, headers=h)
    assert r.status_code == 404


def test_the_same_guards_apply(client, db, forest):
    calc, h = forest
    assert client.get(url(calc)).status_code in (401, 403)
    calc.structure_locked = True
    db.commit()
    assert client.get(url(calc), headers=h).status_code == 200
    assert client.post(url(calc), json=drawn(), headers=h).status_code == 423
    assert client.post(url(calc, "/regenerate"), json={}, headers=h).status_code == 423


# ---------------------------------------------------------------- the OP
def bank(name, river, length_m, ha, units=("Left",)):
    return {"id": name, "name": name, "category": "river_bank", "river_name": river, "length_m": length_m, "area_hectares": ha,
            "blockBreakdown": [{"blockName": u, "area": ha} for u in units]}


def test_never_generated_has_no_data_and_generated_with_none_is_zero():
    assert px.river_bank_summary({}) == {}
    assert px.river_bank_summary({"river_bank_status": {"state": "no_inputs"}}) == {}
    z = px.river_bank_summary({"river_bank_status": {"state": "ok"}, "sub_areas": []})
    assert z["river_bank_table"] == [] and z["river_bank_count"] == 0 and z["river_bank_total_ha"] == 0
    assert z["fire_line_river_bank_combined_ha"] == 0.0


def test_the_table_and_the_totals():
    rd = {"river_bank_status": {"state": "ok"}, "sub_areas": [
        bank("Z-1", "Zeta Khola", 1000, 4.0, ("Left", "Right")), bank("A-1", "Alpha Khola", 2000, 8.0)]}
    out = px.river_bank_summary(rd)
    assert [r["खोला"] for r in out["river_bank_table"]] == ["Alpha Khola", "Zeta Khola"]
    first = out["river_bank_table"][0]
    assert first["लम्बाइ_मि"] == 2000 and first["औसत_चौडाइ_मि"] == 40.0 and first["क्षेत्रफल_हे"] == 8.0
    assert out["river_bank_table"][1]["एकाइ"] == "Left, Right"
    assert out["river_bank_count"] == 2 and out["river_bank_total_km"] == 3.0 and out["river_bank_total_ha"] == 12.0
    assert set(px.COLUMN_ORDER["river_bank_table"]) == set(first)


def _square_ha(x_off, y_off, size_deg=0.001):
    return box(X0 + x_off, Y0 + y_off, X0 + x_off + size_deg, Y0 + y_off + size_deg)


def test_fire_lines_and_river_banks_together_count_their_overlap_once():
    a, b = _square_ha(0, 0), _square_ha(0.0005, 0)                   # two squares sharing half their width
    rd = {"river_bank_status": {"state": "ok"}, "sub_areas": [
        bank("B", "K", 100, 1.0) | {"geometry": mapping(b)},
        {"id": "f", "category": "fire_line", "length_m": 100, "area_hectares": 1.0, "geometry": mapping(a)}]}
    out = px.river_bank_summary(rd)
    metric = sg.Metric.for_geometry(a)
    each, union = sg.area_ha(metric.to_m(a)), sg.area_ha(metric.to_m(a.union(b)))
    assert out["fire_line_river_bank_combined_ha"] == pytest.approx(union, abs=0.01)
    assert out["fire_line_river_bank_overlap_ha"] == pytest.approx(2 * each - union, abs=0.01)


def test_the_variables_are_registered_and_the_collector_fills_them(db, forest):
    from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY

    for key in ("river_bank_table", "river_bank_count", "river_bank_total_km", "river_bank_total_ha",
                "fire_line_river_bank_combined_ha", "fire_line_river_bank_overlap_ha"):
        assert key in VARIABLE_REGISTRY and VARIABLE_REGISTRY[key].source == "plan_extras"
    calc, _ = forest
    out = px.collect_plan_extras(db, str(calc.id), {})
    assert out["river_bank_count"] == 1 and out["river_bank_table"][0]["खोला"] == "Jorchhanga Khola"
    assert out["fire_line_river_bank_combined_ha"] >= out["river_bank_total_ha"] - 0.01
