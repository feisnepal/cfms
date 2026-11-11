"""The same plan built through the facade and through the legacy routes must read identically
everywhere — the operational plan's ya_* variables, the export source and the CBA
(YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.7, §5.8 items 1 and 7)."""

from __future__ import annotations

import json
import uuid

from app.models.calculation import Calculation
from app.models.cost_benefit import CBACostItem, CostBenefitAnalysis
from app.models.user import User
from app.models.yearly_activities import PotentialActivity, ProposedYearlyActivity
from app.services.cost_benefit.repopulate import plan_drift, repopulate_scenario
from app.services.operational_plan.data_collector import _collect_yearly_activities_data

BASE = "/api/yearly-activities"
POINT = json.dumps({"type": "Point", "coordinates": [85.05, 27.44]})


def _login(client, db):
    email = f"par-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Parity Tester"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, db.query(
        User
    ).filter(User.email == email).first()


def _calc(db, user, name):
    calc = Calculation(user_id=user.id, uploaded_filename="p.csv", forest_name=name)
    db.add(calc)
    db.commit()
    return calc


def _scenario(db, calc):
    s = CostBenefitAnalysis(calculation_id=calc.id, name="Base", is_base_scenario=True)
    db.add(s)
    db.commit()
    return s


def _numbers(op):
    """The numeric content of the OP plan variables, without ids."""
    matrix = [
        {
            k: v
            for k, v in row.items()
            if k.startswith("year_") or k.startswith("total_")
        }
        for row in op["plan_matrix"]
    ]
    return (
        op["year_summary"],
        matrix,
        op["total_ten_year_budget"] if "total_ten_year_budget" in op else None,
    )


def _cost(db, scenario):
    db.expire_all()
    (row,) = db.query(CBACostItem).filter_by(cba_id=scenario.id).all()
    return float(row.amount_per_year), float(row.total_amount), row.source_link


def test_a_plan_built_through_the_facade_equals_one_built_through_the_legacy_routes(
    client, db
):
    headers, user = _login(client, db)
    master = PotentialActivity(
        progarms="Prog",
        activities="Nursery construction",
        unit="वटा",
        requires_map=True,
        display_order=0,
    )
    db.add(master)
    db.commit()
    via_facade = _calc(db, user, "Via facade")
    via_legacy = _calc(db, user, "Via legacy")

    # facade: years 1-3, quantity 2, NPR 60,000 a year
    resp = client.post(
        f"{BASE}/calculations/{via_facade.id}/activity-features",
        headers=headers,
        json={
            "potential_activity_id": master.id,
            "feature_type": "point",
            "geometry": POINT,
            "years": [1, 2, 3],
            "quantity": 2,
            "budget": 60000,
        },
    )
    assert resp.status_code == 200, resp.text

    # legacy: the same plan the way the legacy page writes it
    created = client.post(
        f"{BASE}/calculations/{via_legacy.id}/proposed-activities",
        headers=headers,
        json={
            "potential_activity_id": master.id,
            "default_quantity": 2,
            "default_yearly_budget": 60000,
        },
    )
    assert created.status_code == 200, created.text
    for year in range(1, 11):
        on = year <= 3
        r = client.post(
            f"{BASE}/proposed-activities/{created.json()['id']}/year-details",
            headers=headers,
            json={
                "year_number": year,
                "quantity": 2 if on else 0,
                "yearly_budget": 60000 if on else 0,
            },
        )
        assert r.status_code == 200, r.text

    # the operational plan reads them the same
    a = _collect_yearly_activities_data(db, str(via_facade.id))
    b = _collect_yearly_activities_data(db, str(via_legacy.id))
    assert _numbers(a) == _numbers(b)
    assert (
        a["year_summary"][0]["total_budget"] == 60000.0
        and a["year_summary"][3]["total_budget"] == 0.0
    )

    # ... and so does the CBA
    sa, sb = _scenario(db, via_facade), _scenario(db, via_legacy)
    repopulate_scenario(sa.id, db)
    repopulate_scenario(sb.id, db)
    (apy_a, total_a, _k1), (apy_b, total_b, _k2) = _cost(db, sa), _cost(db, sb)
    assert (apy_a, total_a) == (apy_b, total_b) == (60000.0, 180000.0)


def test_deleting_the_last_feature_keeps_the_cba_row_and_its_key(client, db):
    """The CBA keys a cost row by the plan line id: deleting and re-creating the line would look like a
    removed cost and a new one. Keeping the line (D6) keeps the key stable."""
    headers, user = _login(client, db)
    master = PotentialActivity(
        progarms="Prog",
        activities="Plantation",
        unit="हेक्टर",
        requires_map=True,
        display_order=0,
    )
    db.add(master)
    db.commit()
    calc = _calc(db, user, "Stable key")
    fid = client.post(
        f"{BASE}/calculations/{calc.id}/activity-features",
        headers=headers,
        json={
            "potential_activity_id": master.id,
            "feature_type": "point",
            "geometry": POINT,
            "years": [1, 2],
            "quantity": 1,
            "budget": 1000,
        },
    ).json()["feature"]["id"]
    scenario = _scenario(db, calc)
    repopulate_scenario(scenario.id, db)
    before = _cost(db, scenario)

    assert (
        client.delete(
            f"{BASE}/calculations/{calc.id}/activity-features/{fid}", headers=headers
        ).status_code
        == 200
    )

    assert (
        db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).count() == 1
    )
    assert (
        plan_drift(scenario.id, db)["out_of_date"] is False
    )  # nothing the CBA reads has changed
    repopulate_scenario(scenario.id, db)
    assert _cost(db, scenario) == before  # same key, same amounts


def test_the_cba_drift_route_is_read_only_and_reachable(client, db):
    headers, user = _login(client, db)
    master = PotentialActivity(
        progarms="Prog",
        activities="Trail",
        unit="कि.मि.",
        requires_map=True,
        display_order=0,
    )
    db.add(master)
    db.commit()
    calc = _calc(db, user, "Drift route")
    client.post(
        f"{BASE}/calculations/{calc.id}/activity-features",
        headers=headers,
        json={
            "potential_activity_id": master.id,
            "feature_type": "point",
            "geometry": POINT,
            "years": [1],
            "quantity": 1,
            "budget": 500,
        },
    )
    scenario = _scenario(db, calc)

    drift = client.get(f"/api/cba/{scenario.id}/plan-drift", headers=headers)
    assert drift.status_code == 200, drift.text
    assert (
        drift.json()["out_of_date"] is True and len(drift.json()["added"]) == 1
    )  # not populated yet
    assert (
        db.query(CBACostItem).filter_by(cba_id=scenario.id).count() == 0
    )  # and the check wrote nothing

    health = client.get(
        f"{BASE}/calculations/{calc.id}/yearly-plan/health", headers=headers
    ).json()
    assert [i["code"] for i in health["plan_issues"]] == ["CBA_OUT_OF_DATE"]
