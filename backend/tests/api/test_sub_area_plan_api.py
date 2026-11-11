"""Sub-areas tied to the yearly plan, through the API: status, planning, deleting, health and the issue gate (owner rule 2026-10-08)."""
from __future__ import annotations

import pytest

from app.models.operational_plan import OperationalPlan
from app.models.yearly_activities import ProposedYearlyActivity
from tests.services.test_sampling_stratified import _setup_two_equal_blocks
from tests.services.test_sub_area_plan import _master, _sub_area
from tests.test_sampling_add_units import _headers

YP = "/api/yearly-activities"


def _state(client, h, calc):
    r = client.get(f"{YP}/calculations/{calc.id}/sub-areas/plan-status", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def forest(client, db):
    calc = _setup_two_equal_blocks(db)
    return calc, _headers(client, db, calc)


def test_status_lists_the_sub_area_with_suggestions(client, db, forest):
    calc, h = forest
    sa = _sub_area(db, calc)
    m = _master(db, map_kind="plantation")
    body = _state(client, h, calc)
    assert body["needs_plan"] == 1
    item = body["sub_areas"][0]
    assert item["id"] == sa["id"] and item["state"] == "needs_plan" and m.id in [s["id"] for s in item["suggestions"]]


def test_planning_a_sub_area_ties_it_to_the_plan(client, db, forest):
    calc, h = forest
    sa = _sub_area(db, calc)
    m = _master(db, budget="1000")
    r = client.post(f"{YP}/calculations/{calc.id}/sub-areas/{sa['id']}/plan", json={"potential_activity_ids": [m.id]}, headers=h)
    assert r.status_code == 200, r.text
    assert _state(client, h, calc)["needs_plan"] == 0
    # a bad activity and an unknown sub-area are friendly errors
    assert client.post(f"{YP}/calculations/{calc.id}/sub-areas/{sa['id']}/plan", json={"potential_activity_ids": [-5]}, headers=h).status_code == 404
    assert client.post(f"{YP}/calculations/{calc.id}/sub-areas/{sa['id'][:-1]}0/plan", json={"potential_activity_ids": [m.id]}, headers=h).status_code == 404


def test_plan_all_with_suggestions_skips_those_with_none(client, db, forest):
    calc, h = forest
    _master(db, budget="1000")
    _sub_area(db, calc, name="Good")
    _sub_area(db, calc, category="no-such-category", name="Odd")
    r = client.post(f"{YP}/calculations/{calc.id}/sub-areas/plan-suggested", headers=h)
    assert r.status_code == 200, r.text
    assert [p["name"] for p in r.json()["planned"]] == ["Good"] and [s["name"] for s in r.json()["skipped"]] == ["Odd"]


def test_health_blocks_while_a_sub_area_has_no_plan_and_stops_when_planned_or_private(client, db, forest):
    calc, h = forest
    sa = _sub_area(db, calc)
    _sub_area(db, calc, category="private_land", name="Mine")
    r = client.get(f"{YP}/calculations/{calc.id}/yearly-plan/health", headers=h)
    issue = next(i for i in r.json()["plan_issues"] if i["code"] == "SUB_AREA_NO_PLAN")
    assert issue["severity"] == "blocking" and issue["params"]["count"] == 1
    m = _master(db, budget="1000")
    client.post(f"{YP}/calculations/{calc.id}/sub-areas/{sa['id']}/plan", json={"potential_activity_ids": [m.id]}, headers=h)
    r = client.get(f"{YP}/calculations/{calc.id}/yearly-plan/health", headers=h)
    assert "SUB_AREA_NO_PLAN" not in [i["code"] for i in r.json()["plan_issues"]]


def test_the_plan_cannot_be_submitted_until_every_sub_area_is_planned(client, db, forest):
    calc, h = forest
    sa = _sub_area(db, calc)
    plan = OperationalPlan(calculation_id=calc.id, forest_name="F", sections={}, plan_metadata={})
    db.add(plan)
    db.commit()
    url = f"/api/operational-plans/{plan.id}/submissions"
    r = client.post(url, json={"submitted_to": "DFO"}, headers=h)
    assert r.status_code == 409, r.text
    assert "no activity plan" in r.json()["detail"]["message"] and r.json()["detail"]["message_np"]
    m = _master(db, budget="1000")
    client.post(f"{YP}/calculations/{calc.id}/sub-areas/{sa['id']}/plan", json={"potential_activity_ids": [m.id]}, headers=h)
    assert client.post(url, json={"submitted_to": "DFO"}, headers=h).status_code != 409


def _delete(client, h, calc, sa_id, **params):
    return client.delete(f"/api/forests/calculations/{calc.id}/sub-areas/{sa_id}", params=params, headers=h)


def _planned(client, db, h, calc, sa):
    m = _master(db, budget="1000")
    client.post(f"{YP}/calculations/{calc.id}/sub-areas/{sa['id']}/plan", json={"potential_activity_ids": [m.id]}, headers=h)
    return m


def test_deleting_a_planned_sub_area_asks_first(client, db, forest):
    calc, h = forest
    sa = _sub_area(db, calc)
    _planned(client, db, h, calc, sa)
    r = _delete(client, h, calc, sa["id"])
    assert r.status_code == 409 and r.json()["detail"]["lines"] and r.json()["detail"]["message_np"]
    assert db.query(ProposedYearlyActivity).filter_by(sub_area_id=sa["id"]).count() == 1  # nothing happened


def test_deleting_with_delete_removes_the_lines(client, db, forest):
    calc, h = forest
    sa = _sub_area(db, calc)
    _planned(client, db, h, calc, sa)
    assert _delete(client, h, calc, sa["id"], plan_lines="delete").status_code == 200
    assert db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).count() == 0


def test_deleting_with_keep_leaves_forest_wide_lines(client, db, forest):
    calc, h = forest
    sa = _sub_area(db, calc)
    m = _planned(client, db, h, calc, sa)
    assert _delete(client, h, calc, sa["id"], plan_lines="keep").status_code == 200
    line = db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).one()
    assert line.sub_area_id is None and line.block_id is None and line.potential_activity_id == m.id


def test_an_unplanned_sub_area_deletes_without_asking_and_delete_all_asks_too(client, db, forest):
    calc, h = forest
    plain = _sub_area(db, calc, name="Plain")
    assert _delete(client, h, calc, plain["id"]).status_code == 200
    sa = _sub_area(db, calc, name="Tied")
    _planned(client, db, h, calc, sa)
    url = f"/api/forests/calculations/{calc.id}/sub-areas"
    assert client.delete(url, headers=h).status_code == 409
    assert client.delete(url, params={"plan_lines": "delete"}, headers=h).status_code == 200
    assert db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).count() == 0
