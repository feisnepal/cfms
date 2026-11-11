"""P0b of the yearly-activities plan: the calculation-scoped facade
(YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.1, §4.7, §5.5, D9, D15)."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.op_data_cache import OpDataCache
from app.models.user import User, UserRole
from app.models.yearly_activities import (
    ActivityDrawnFeature,
    ActivityYearDetail,
    PotentialActivity,
    ProposedYearlyActivity,
)
from app.services import yearly_plan_service as plan

BASE = "/api/yearly-activities"
POINT = json.dumps({"type": "Point", "coordinates": [85.05, 27.44]})
SQUARE = json.dumps(
    {
        "type": "Polygon",
        "coordinates": [
            [
                [85.0, 27.0],
                [85.001, 27.0],
                [85.001, 27.001],
                [85.0, 27.001],
                [85.0, 27.0],
            ]
        ],
    }
)


def _login(client, db, role=None):
    email = f"fac-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Facade Tester"},
    )
    if role is not None:
        user = db.query(User).filter(User.email == email).first()
        user.role = role
        db.commit()
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def _calc(db, user):
    calc = Calculation(
        user_id=user.id, uploaded_filename="x.csv", forest_name="Facade CF"
    )
    db.add(calc)
    db.commit()
    return calc


def _master(db, name="Nursery", unit="वटा", requires_map=True, budget=None):
    pa = PotentialActivity(
        progarms="Program",
        activities=name,
        unit=unit,
        requires_map=requires_map,
        yearly_budget=budget,
        display_order=0,
    )
    db.add(pa)
    db.commit()
    return pa


def _draw(client, headers, calc, master, **extra):
    body = {
        "potential_activity_id": master.id,
        "feature_type": "point",
        "geometry": POINT,
        **extra,
    }
    return client.post(
        f"{BASE}/calculations/{calc.id}/activity-features", headers=headers, json=body
    )


def _placeholder_line(db, calc, master):
    """A line as the legacy "add activity" wrote it: 1 x 5,000 in every year."""
    line = ProposedYearlyActivity(
        calculation_id=calc.id,
        potential_activity_id=master.id,
        default_quantity=1,
        default_yearly_budget=5000,
    )
    db.add(line)
    db.flush()
    for y in range(1, 11):
        db.add(
            ActivityYearDetail(
                proposed_activity_id=line.id,
                year_number=y,
                quantity=1,
                yearly_budget=5000,
            )
        )
    db.commit()
    return line


def _years(db, line):
    db.expire_all()
    return {
        r.year_number: (float(r.quantity), float(r.yearly_budget))
        for r in db.query(ActivityYearDetail).filter_by(proposed_activity_id=line.id)
    }


# ------------------------------------------------------------------ create: one transaction
def test_drawing_a_place_creates_the_line_all_ten_year_rows_and_the_feature_together(
    client, db
):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)

    resp = _draw(
        client, headers, calc, master, years=[1, 2, 3], quantity=2, budget=60000
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created_plan_line"] is True and body["created_year_rows"] == list(
        range(1, 11)
    )
    line = db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).one()
    rows = _years(db, line)
    assert (
        rows[1] == rows[2] == rows[3] == (2.0, 60000.0)
    )  # the chosen years at the entered values
    assert all(
        rows[y] == (0.0, 0.0) for y in range(4, 11)
    )  # the others: explicit "not planned"
    assert (
        line.reviewed_at is not None
    )  # the user typed the numbers, so the line is created reviewed
    assert (
        db.query(ActivityDrawnFeature).filter_by(proposed_activity_id=line.id).count()
        == 1
    )
    assert body["feature"]["properties"]["years"] == [1, 2, 3]
    assert body["plan_line"]["planned_years"] == [1, 2, 3]


def test_a_raw_draw_creates_the_line_unreviewed_and_never_writes_a_placeholder(
    client, db
):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)  # no default budget in the master list
    resp = _draw(client, headers, calc, master)
    assert resp.status_code == 200, resp.text
    line = db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).one()
    assert line.reviewed_at is None
    assert float(line.default_yearly_budget) == 0  # not 5,000: nothing is invented (D3)


def test_a_second_place_for_the_same_activity_reuses_the_line(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)
    first = _draw(client, headers, calc, master, quantity=1, budget=100).json()
    second = _draw(client, headers, calc, master).json()
    assert second["created_plan_line"] is False
    assert (
        second["feature"]["proposed_activity_id"]
        == first["feature"]["proposed_activity_id"]
    )
    assert (
        db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).count() == 1
    )


def test_a_feature_in_an_unplanned_year_is_refused_unless_the_caller_says_plan_it_too(
    client, db
):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)
    _draw(client, headers, calc, master, years=[1], quantity=1, budget=500)

    refused = _draw(client, headers, calc, master, years=[4])
    assert refused.status_code == 422
    assert refused.json()["detail"] == {"code": "YEAR_NOT_PLANNED", "years": [4]}

    allowed = _draw(client, headers, calc, master, years=[4], plan_years=True)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["planned_years_added"] == [4]
    line = db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).one()
    assert _years(db, line)[4] == (1.0, 500.0)  # the line's defaults


def test_the_measured_quantity_follows_the_activitys_unit(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    hectares = _master(db, "Plantation", unit="हेक्टर")
    resp = client.post(
        f"{BASE}/calculations/{calc.id}/activity-features",
        headers=headers,
        json={
            "potential_activity_id": hectares.id,
            "feature_type": "polygon",
            "geometry": SQUARE,
        },
    )
    assert resp.status_code == 200, resp.text
    assert (
        1.0 < float(resp.json()["measured_quantity"]) < 2.0
    )  # 0.001 x 0.001 deg near 27N is ~1.1 ha
    assert resp.json()["unit"] == "हेक्टर"
    each = _master(db, "Nursery 2", unit="वटा")
    assert float(_draw(client, headers, calc, each).json()["measured_quantity"]) == 1.0
    asked = _master(db, "Other", unit="आ.अ.")
    assert (
        _draw(client, headers, calc, asked).json()["measured_quantity"] is None
    )  # must be asked


def test_losing_the_get_or_create_race_reuses_the_winners_line(client, db):
    """Two requests both find no line and both insert. The partial unique index rejects the second
    insert and it re-reads the winner's row. The race is simulated deterministically: the first
    lookup is made to miss although the line exists, exactly what the loser of the race sees.
    """
    _headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)
    winner, created, _rows = plan.get_or_create_line(
        db, calc.id, master.id, numbers=None, years=[1]
    )
    db.commit()
    assert created is True

    real = plan._forest_level_line
    calls = {"n": 0}

    def missing_the_first_time(session, calculation_id, potential_activity_id):
        calls["n"] += 1
        return (
            None
            if calls["n"] == 1
            else real(session, calculation_id, potential_activity_id)
        )

    plan._forest_level_line = missing_the_first_time
    try:
        loser, created_again, rows = plan.get_or_create_line(
            db, calc.id, master.id, numbers=None, years=[1]
        )
        db.commit()
    finally:
        plan._forest_level_line = real

    assert created_again is False and rows == []
    assert loser.id == winner.id
    assert (
        db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).count() == 1
    )


def test_the_unique_index_itself_refuses_a_second_forest_level_line(client, db):
    from sqlalchemy.exc import IntegrityError

    _headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)
    db.add(
        ProposedYearlyActivity(
            calculation_id=calc.id,
            potential_activity_id=master.id,
            default_quantity=1,
            default_yearly_budget=0,
        )
    )
    db.commit()
    db.add(
        ProposedYearlyActivity(
            calculation_id=calc.id,
            potential_activity_id=master.id,
            default_quantity=2,
            default_yearly_budget=0,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --------------------------------------------------------------------------- delete / edit
def test_deleting_the_last_feature_keeps_the_plan_line_unless_asked(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)
    fid = _draw(client, headers, calc, master, quantity=1, budget=10).json()["feature"][
        "id"
    ]

    kept = client.delete(
        f"{BASE}/calculations/{calc.id}/activity-features/{fid}", headers=headers
    )
    assert kept.status_code == 200 and kept.json()["plan_line_removed"] is False
    assert (
        db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).count() == 1
    )  # D6
    db.expire_all()
    assert db.get(ActivityDrawnFeature, fid).deleted_at is not None  # soft delete

    fid2 = _draw(client, headers, calc, master).json()["feature"]["id"]
    gone = client.delete(
        f"{BASE}/calculations/{calc.id}/activity-features/{fid2}?remove_plan_line=true",
        headers=headers,
    )
    assert gone.json()["plan_line_removed"] is True
    assert (
        db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).count() == 0
    )


def test_editing_a_feature_changes_its_name_years_and_symbol(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)
    fid = _draw(
        client, headers, calc, master, years=[1, 2], quantity=1, budget=10
    ).json()["feature"]["id"]
    resp = client.patch(
        f"{BASE}/calculations/{calc.id}/activity-features/{fid}",
        headers=headers,
        json={"name": "Ward 3 nursery", "years": [2], "kind": "nursery"},
    )
    assert resp.status_code == 200, resp.text
    props = resp.json()["properties"]
    assert (
        props["name"] == "Ward 3 nursery"
        and props["years"] == [2]
        and props["kind"] == "nursery"
    )
    assert resp.json()["kind"] == "nursery"
    bad = client.patch(
        f"{BASE}/calculations/{calc.id}/activity-features/{fid}",
        headers=headers,
        json={"kind": "no-such-kind"},
    )
    assert bad.status_code == 422


def test_a_feature_can_move_to_another_activity(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    a, b = _master(db, "A"), _master(db, "B")
    fid = _draw(client, headers, calc, a, quantity=1, budget=10).json()["feature"]["id"]
    resp = client.patch(
        f"{BASE}/calculations/{calc.id}/activity-features/{fid}",
        headers=headers,
        json={"potential_activity_id": b.id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["activity_name"] == "B"
    assert (
        db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).count() == 2
    )


# ------------------------------------------------------------------ PUT: all-or-nothing + lock
def test_a_stale_version_is_a_409_with_both_versions_and_nothing_changes(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    line = _placeholder_line(db, calc, _master(db))
    url = f"{BASE}/calculations/{calc.id}/yearly-plan/{line.id}"

    ok = client.put(
        url,
        headers=headers,
        json={"years": [{"year": 1, "budget": 80000}], "expected_version": 1},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["plan_line"]["version"] == 2

    stale = client.put(
        url,
        headers=headers,
        json={"years": [{"year": 2, "budget": 1}], "expected_version": 1},
    )
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["your_version"] == 1 and detail["current_version"] == 2
    assert _years(db, line)[2][1] != 1.0  # the refused edit changed nothing


def test_a_bad_year_in_the_body_changes_nothing(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    line = _placeholder_line(db, calc, _master(db))
    resp = client.put(
        f"{BASE}/calculations/{calc.id}/yearly-plan/{line.id}",
        headers=headers,
        json={"years": [{"year": 1, "budget": 99}, {"year": 11, "budget": 5}]},
    )
    assert resp.status_code == 422
    assert _years(db, line)[1] == (1.0, 5000.0)  # all or nothing


# ------------------------------------------------------------ first-value + reviewed rules
def test_the_first_value_typed_fills_the_years_still_at_the_starting_value(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    line = _placeholder_line(db, calc, _master(db))
    url = f"{BASE}/calculations/{calc.id}/yearly-plan/{line.id}"

    resp = client.put(
        url, headers=headers, json={"years": [{"year": 1, "budget": 80000}]}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["filled_years"] == list(range(2, 11))
    rows = _years(db, line)
    assert all(rows[y][1] == 80000.0 for y in range(1, 11))
    assert all(
        rows[y][0] == 1.0 for y in range(1, 11)
    )  # quantity was not typed: untouched
    view = resp.json()["plan_line"]
    assert view["default_yearly_budget"] == 80000.0
    # only the budget was typed: the quantity is still a starting value, so the line is NOT reviewed
    assert view["reviewed_at"] is None and view["placeholder_fields"] == ["quantity"]

    second = client.put(
        url, headers=headers, json={"years": [{"year": 1, "quantity": 3}]}
    )
    assert second.json()["filled_years"] == list(range(2, 11))
    assert (
        second.json()["plan_line"]["reviewed_at"] is not None
    )  # both fields now changed
    assert second.json()["plan_line"]["placeholder_fields"] == []


def test_undo_puts_back_the_numbers_and_the_not_reviewed_state_exactly(client, db):
    """The Plan table's Undo sends the earlier values back (all ten years + the defaults) with `unreview`."""
    headers, user = _login(client, db)
    calc = _calc(db, user)
    line = _placeholder_line(db, calc, _master(db))
    url = f"{BASE}/calculations/{calc.id}/yearly-plan/{line.id}"
    before = client.get(f"{BASE}/calculations/{calc.id}/yearly-plan", headers=headers).json()["lines"][0]
    assert before["reviewed_at"] is None

    # type BOTH fields once: fills every other year, and the line becomes reviewed
    edited = client.put(
        url,
        headers=headers,
        json={"years": [{"year": 1, "quantity": 3, "budget": 80000}], "expected_version": before["version"]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["filled_years"] == list(range(2, 11))
    after = edited.json()["plan_line"]
    assert after["reviewed_at"] is not None and after["default_yearly_budget"] == 80000.0

    undone = client.put(
        url,
        headers=headers,
        json={
            "default_quantity": before["default_quantity"],
            "default_yearly_budget": before["default_yearly_budget"],
            "years": [{"year": y["year"], "quantity": y["quantity"], "budget": y["budget"]} for y in before["years"]],
            "expected_version": after["version"],
            "unreview": True,
        },
    )

    assert undone.status_code == 200, undone.text
    back = undone.json()["plan_line"]
    assert undone.json()["filled_years"] == []  # ten explicit years: the first-value rule does not fire again
    assert back["reviewed_at"] is None  # the flag an edit had set is cleared again
    assert back["default_quantity"] == before["default_quantity"]
    assert back["default_yearly_budget"] == before["default_yearly_budget"]
    assert [(y["quantity"], y["budget"]) for y in back["years"]] == [(y["quantity"], y["budget"]) for y in before["years"]]
    assert back["placeholder_fields"] == before["placeholder_fields"]  # both flagged again, as they were


def test_unreview_alone_never_leaves_real_numbers_unreviewed(client, db):
    """`unreview` clears the flag, but a line whose numbers are both real is marked reviewed again by the same rule."""
    headers, user = _login(client, db)
    calc = _calc(db, user)
    line = _placeholder_line(db, calc, _master(db))
    url = f"{BASE}/calculations/{calc.id}/yearly-plan/{line.id}"
    real = client.put(url, headers=headers, json={"years": [{"year": 1, "quantity": 3, "budget": 80000}]}).json()["plan_line"]

    again = client.put(url, headers=headers, json={"unreview": True, "expected_version": real["version"]})

    assert again.status_code == 200, again.text
    assert again.json()["plan_line"]["reviewed_at"] is not None


def test_a_changed_year_and_a_zero_are_never_overwritten_by_the_first_value(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    line = _placeholder_line(db, calc, _master(db))
    db.query(ActivityYearDetail).filter_by(
        proposed_activity_id=line.id, year_number=2
    ).update({"yearly_budget": 7000})
    db.query(ActivityYearDetail).filter_by(
        proposed_activity_id=line.id, year_number=3
    ).update({"quantity": 0, "yearly_budget": 0})
    db.commit()

    resp = client.put(
        f"{BASE}/calculations/{calc.id}/yearly-plan/{line.id}",
        headers=headers,
        json={"years": [{"year": 1, "budget": 80000}]},
    )
    rows = _years(db, line)
    assert rows[2][1] == 7000.0  # a year the user changed
    assert rows[3] == (0.0, 0.0)  # a 0 / 0 year
    assert 2 not in resp.json()["filled_years"] and 3 not in resp.json()["filled_years"]
    assert all(rows[y][1] == 80000.0 for y in range(4, 11))


def test_a_reviewed_line_and_a_line_with_real_numbers_are_never_filled(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    reviewed = _placeholder_line(db, calc, _master(db, "Reviewed"))
    client.post(
        f"{BASE}/calculations/{calc.id}/yearly-plan/{reviewed.id}/confirm",
        headers=headers,
    )
    resp = client.put(
        f"{BASE}/calculations/{calc.id}/yearly-plan/{reviewed.id}",
        headers=headers,
        json={"years": [{"year": 1, "budget": 9}]},
    )
    assert resp.json()["filled_years"] == []
    assert _years(db, reviewed)[2] == (1.0, 5000.0)

    # the live "2 x 5,000,000 in every year" shape, never reviewed: nothing is at the starting value
    real = ProposedYearlyActivity(
        calculation_id=calc.id,
        potential_activity_id=_master(db, "Real").id,
        default_quantity=2,
        default_yearly_budget=5_000_000,
    )
    db.add(real)
    db.commit()
    resp = client.put(
        f"{BASE}/calculations/{calc.id}/yearly-plan/{real.id}",
        headers=headers,
        json={"years": [{"year": 1, "budget": 4}]},
    )
    assert resp.json()["filled_years"] == []


def test_the_default_can_be_edited_and_confirm_marks_a_line_reviewed(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    line = _placeholder_line(db, calc, _master(db))
    base = f"{BASE}/calculations/{calc.id}/yearly-plan/{line.id}"
    filled = client.put(
        base, headers=headers, json={"default_yearly_budget": 250}
    ).json()
    assert filled["filled_years"] == list(
        range(1, 11)
    )  # the default edit fills the untouched years
    assert all(v[1] == 250.0 for v in _years(db, line).values())

    confirmed = client.post(f"{base}/confirm", headers=headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["plan_line"]["reviewed_at"] is not None


# ---------------------------------------------------- legacy routes take the same lock
def test_a_year_edit_through_the_legacy_routes_bumps_the_plan_lines_version(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    line = _placeholder_line(db, calc, _master(db))
    row = (
        db.query(ActivityYearDetail)
        .filter_by(proposed_activity_id=line.id, year_number=1)
        .one()
    )
    resp = client.patch(
        f"{BASE}/proposed-activities/{line.id}/year-details/{row.id}",
        headers=headers,
        json={"yearly_budget": 12},
    )
    assert resp.status_code == 200, resp.text
    db.expire_all()
    assert db.get(ProposedYearlyActivity, line.id).version == 2
    stale = client.patch(
        f"{BASE}/proposed-activities/{line.id}/year-details/{row.id}",
        headers=headers,
        json={"yearly_budget": 13, "expected_version": 1},
    )
    assert stale.status_code == 409


def test_a_mappable_activity_can_be_marked_as_applying_to_the_whole_forest(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    line = _placeholder_line(db, calc, _master(db))
    resp = client.patch(
        f"{BASE}/proposed-activities/{line.id}",
        headers=headers,
        json={"assign_to_all_blocks": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assign_to_all_blocks"] is True
    plan_resp = client.get(
        f"{BASE}/calculations/{calc.id}/yearly-plan", headers=headers
    ).json()
    assert plan_resp["lines"][0]["location_mode"] == "whole_forest"


def test_creating_the_same_activity_twice_through_the_legacy_route_is_a_400_not_a_duplicate(
    client, db
):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)
    body = {
        "potential_activity_id": master.id,
        "default_quantity": 1,
        "default_yearly_budget": 0,
    }
    first = client.post(
        f"{BASE}/calculations/{calc.id}/proposed-activities", headers=headers, json=body
    )
    assert first.status_code == 200
    again = client.post(
        f"{BASE}/calculations/{calc.id}/proposed-activities", headers=headers, json=body
    )
    assert (
        again.status_code == 400
    )  # the NULL-block comparison used to let this through
    assert (
        db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).count() == 1
    )


# ----------------------------------------------------------------- owner only, audit, cache
@pytest.mark.parametrize("role", [UserRole.USER, UserRole.SUPER_ADMIN])
def test_the_facade_is_owner_only(client, db, role):
    owner_headers, owner = _login(client, db)
    calc = _calc(db, owner)
    master = _master(db)
    fid = _draw(client, owner_headers, calc, master, quantity=1, budget=1).json()[
        "feature"
    ]["id"]
    line = db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).one()
    intruder, _ = _login(client, db, role=role)
    base = f"{BASE}/calculations/{calc.id}"
    calls = [
        (
            "post",
            f"{base}/activity-features",
            {
                "potential_activity_id": master.id,
                "feature_type": "point",
                "geometry": POINT,
            },
        ),
        ("patch", f"{base}/activity-features/{fid}", {"name": "x"}),
        ("delete", f"{base}/activity-features/{fid}", None),
        ("get", f"{base}/yearly-plan", None),
        ("put", f"{base}/yearly-plan/{line.id}", {"years": [{"year": 1, "budget": 1}]}),
        ("post", f"{base}/yearly-plan/{line.id}/confirm", None),
    ]
    for method, url, body in calls:
        resp = getattr(client, method)(
            url, headers=intruder, **({"json": body} if body else {})
        )
        assert resp.status_code == 404, (method, url, resp.status_code)
    db.expire_all()
    assert db.get(ActivityDrawnFeature, fid).deleted_at is None


def test_the_facade_writes_audit_rows_and_drops_the_op_cache(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    master = _master(db)
    db.merge(OpDataCache(calculation_id=calc.id, data={"_cache_version": 0}))
    db.commit()

    resp = _draw(client, headers, calc, master, quantity=1, budget=1)
    assert resp.status_code == 200, resp.text

    db.expire_all()
    assert db.query(OpDataCache).filter_by(calculation_id=calc.id).count() == 0
    audits = db.execute(
        text(
            "SELECT operation, layer_type FROM geometry_audits WHERE calculation_id = :c"
        ),
        {"c": str(calc.id)},
    ).fetchall()
    assert ("CREATE", "activity_features") in [tuple(a) for a in audits]
