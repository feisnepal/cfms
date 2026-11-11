"""P3 of the yearly-activities plan: adding an activity to the plan without drawing a place
(`POST /calculations/{id}/yearly-plan`) — the wizard's path for an activity that needs no map, for
"applies to the whole forest" and for "decide the place later" (YEARLY_ACTIVITIES_WORKSPACE_PLAN §4.4, §4.4b)."""

from __future__ import annotations

import uuid

from app.models.calculation import Calculation
from app.models.user import User
from app.models.yearly_activities import PotentialActivity

BASE = "/api/yearly-activities"


def _login(client, db):
    email = f"add-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Add Tester"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def _calc(db, user):
    calc = Calculation(user_id=user.id, uploaded_filename="x.csv", forest_name="Add CF")
    db.add(calc)
    db.commit()
    return calc


def _master(db, name="Training", unit="पटक", requires_map=False, active=True):
    pa = PotentialActivity(
        progarms="Program",
        activities=name,
        unit=unit,
        requires_map=requires_map,
        display_order=0,
        is_active=active,
    )
    db.add(pa)
    db.commit()
    return pa


def _post(client, headers, calc, body):
    return client.post(
        f"{BASE}/calculations/{calc.id}/yearly-plan", headers=headers, json=body
    )


def _health(client, headers, calc):
    resp = client.get(
        f"{BASE}/calculations/{calc.id}/yearly-plan/health", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _year(line, n):
    return next(y for y in line["years"] if y["year"] == n)


def test_a_non_map_activity_is_added_reviewed_with_the_chosen_years(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)

    resp = _post(
        client,
        headers,
        calc,
        {
            "potential_activity_id": master.id,
            "years": [1, 2, 3],
            "quantity": "4",
            "budget": "25000",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created_plan_line"] is True and body["unit"] == "पटक"
    line = body["plan_line"]
    assert line["reviewed_at"] is not None
    assert line["planned_years"] == [1, 2, 3]
    assert float(_year(line, 2)["quantity"]) == 4.0
    assert float(_year(line, 2)["budget"]) == 25000.0
    # a year left out is an explicit "nothing planned"
    assert float(_year(line, 5)["quantity"]) == 0.0
    # a line the person typed is not flagged; a non-map activity is never asked for a place
    health = _health(client, headers, calc)
    assert health["items"][0]["state"] == "ready", health
    assert health["items"][0]["issues"] == []


def test_a_zero_budget_is_real(client, db):
    """Voluntary work: budget 0 is accepted and the year still counts as planned by its quantity."""
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db, name="Volunteer day")

    resp = _post(
        client,
        headers,
        calc,
        {
            "potential_activity_id": master.id,
            "years": [1],
            "quantity": "1",
            "budget": "0",
        },
    )

    assert resp.status_code == 200, resp.text
    line = resp.json()["plan_line"]
    assert line["planned_years"] == [1]
    assert float(line["total_budget"]) == 0.0


def test_different_numbers_each_year(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)

    resp = _post(
        client,
        headers,
        calc,
        {
            "potential_activity_id": master.id,
            "years": [1, 2],
            "quantity": "2",
            "budget": "10000",
            "year_values": [{"year": 2, "quantity": "5", "budget": "40000"}],
        },
    )

    assert resp.status_code == 200, resp.text
    line = resp.json()["plan_line"]
    assert float(_year(line, 1)["budget"]) == 10000.0
    assert float(_year(line, 2)["quantity"]) == 5.0
    assert float(_year(line, 2)["budget"]) == 40000.0
    assert float(line["total_budget"]) == 50000.0


def test_applies_to_the_whole_forest_clears_the_need_for_a_location(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db, name="Boundary marking", unit="कि.मि.", requires_map=True)

    # decide later: a mappable activity with no place is asked for one
    later = _post(
        client,
        headers,
        calc,
        {
            "potential_activity_id": master.id,
            "years": [1],
            "quantity": "3",
            "budget": "9000",
        },
    )
    assert later.status_code == 200, later.text
    assert later.json()["plan_line"]["location_mode"] == "needs_location"
    assert any(
        i["code"] == "NO_LOCATION"
        for i in _health(client, headers, calc)["items"][0]["issues"]
    )

    # the same activity, answered "applies to the whole forest"
    again = _post(
        client,
        headers,
        calc,
        {"potential_activity_id": master.id, "years": [1], "whole_forest": True},
    )
    assert again.status_code == 200, again.text
    assert again.json()["created_plan_line"] is False
    assert again.json()["plan_line"]["location_mode"] == "whole_forest"
    assert not any(
        i["code"] == "NO_LOCATION"
        for i in _health(client, headers, calc)["items"][0]["issues"]
    )


def test_an_activity_already_in_the_plan_keeps_its_numbers(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)
    first = _post(
        client,
        headers,
        calc,
        {
            "potential_activity_id": master.id,
            "years": [1],
            "quantity": "2",
            "budget": "8000",
        },
    )
    assert first.status_code == 200

    second = _post(
        client,
        headers,
        calc,
        {
            "potential_activity_id": master.id,
            "years": [1, 2],
            "quantity": "9",
            "budget": "99999",
        },
    )

    assert second.status_code == 200, second.text
    body = second.json()
    assert body["created_plan_line"] is False
    assert body["plan_line"]["id"] == first.json()["plan_line"]["id"]
    assert float(_year(body["plan_line"], 1)["budget"]) == 8000.0
    assert body["plan_line"]["planned_years"] == [1]
    plan = client.get(
        f"{BASE}/calculations/{calc.id}/yearly-plan", headers=headers
    ).json()
    assert len(plan["lines"]) == 1  # never a duplicate


def test_unknown_or_switched_off_activities_are_refused(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    off = _master(db, name="Switched off", active=False)

    assert (
        _post(client, headers, calc, {"potential_activity_id": 987654}).status_code
        == 404
    )
    assert (
        _post(client, headers, calc, {"potential_activity_id": off.id}).status_code
        == 404
    )


def test_values_are_validated(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)

    for bad in (
        {"years": [0]},
        {"years": [11]},
        {"quantity": "0"},
        {"quantity": "-1"},
        {"budget": "-5"},
        {"year_values": [{"year": 12, "quantity": "1"}]},
    ):
        resp = _post(client, headers, calc, {"potential_activity_id": master.id, **bad})
        assert resp.status_code == 422, (bad, resp.text)
    plan = client.get(
        f"{BASE}/calculations/{calc.id}/yearly-plan", headers=headers
    ).json()
    assert plan["lines"] == []  # nothing was created by a refused request


def test_only_the_owner_can_add_to_a_plan(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)
    other_headers, _other = _login(client, db)

    resp = _post(client, other_headers, calc, {"potential_activity_id": master.id})

    assert resp.status_code == 404
    plan = client.get(
        f"{BASE}/calculations/{calc.id}/yearly-plan", headers=headers
    ).json()
    assert plan["lines"] == []


def test_replaying_the_same_request_does_not_add_it_twice(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)
    headers = {**headers, "Idempotency-Key": f"k-{uuid.uuid4().hex}"}
    body = {
        "potential_activity_id": master.id,
        "years": [1],
        "quantity": "1",
        "budget": "100",
    }

    first = _post(client, headers, calc, body)
    second = _post(client, headers, calc, body)

    assert first.status_code == second.status_code == 200
    assert first.json()["plan_line"]["id"] == second.json()["plan_line"]["id"]
    plan = client.get(
        f"{BASE}/calculations/{calc.id}/yearly-plan", headers=headers
    ).json()
    assert len(plan["lines"]) == 1
