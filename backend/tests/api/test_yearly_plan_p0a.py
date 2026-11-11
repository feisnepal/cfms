"""P0a of the yearly-activities plan: zero years are real, owner-only routes, and the OP data
cache clears on every plan write (YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.4, §5.8, F9, F12, D9, D17).
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.models.calculation import Calculation
from app.models.op_data_cache import OpDataCache
from app.models.user import User, UserRole
from app.models.yearly_activities import (
    ActivityDrawnFeature,
    ActivitySpatialAssignment,
    ActivityYearDetail,
    PotentialActivity,
    ProposedYearlyActivity,
)

BASE = "/api/yearly-activities"


def _login(client, db, role=None):
    email = f"p0a-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "P0a"},
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


def _plan_line(db, user, default_quantity=1, default_budget=1000):
    calc = Calculation(user_id=user.id, uploaded_filename="x.csv", forest_name="P0a CF")
    db.add(calc)
    db.flush()
    pa = PotentialActivity(progarms="Program", activities="Nursery", display_order=0)
    db.add(pa)
    db.flush()
    line = ProposedYearlyActivity(
        calculation_id=calc.id,
        potential_activity_id=pa.id,
        default_quantity=default_quantity,
        default_yearly_budget=default_budget,
    )
    db.add(line)
    db.commit()
    return calc, line


def _year(db, line, year, quantity=None, budget=None):
    row = ActivityYearDetail(
        proposed_activity_id=line.id,
        year_number=year,
        quantity=quantity,
        yearly_budget=budget,
    )
    db.add(row)
    db.commit()
    return row


# --------------------------------------------------------------------- zero years (YA-0a.1/2)
def test_a_year_of_zero_quantity_and_zero_budget_can_be_saved_and_read_back(client, db):
    headers, user = _login(client, db)
    calc, line = _plan_line(db, user)

    resp = client.post(
        f"{BASE}/proposed-activities/{line.id}/year-details",
        headers=headers,
        json={"year_number": 4, "quantity": 0, "yearly_budget": 0},
    )
    assert resp.status_code == 200, resp.text  # was 422: quantity/budget had to be > 0
    body = resp.json()
    assert float(body["quantity"]) == 0 and float(body["yearly_budget"]) == 0

    resp = client.patch(
        f"{BASE}/proposed-activities/{line.id}/year-details/{body['id']}",
        headers=headers,
        json={"quantity": 0, "yearly_budget": 250},
    )
    assert resp.status_code == 200, resp.text
    assert (
        float(resp.json()["quantity"]) == 0
        and float(resp.json()["yearly_budget"]) == 250
    )


def test_a_negative_amount_is_still_refused(client, db):
    headers, user = _login(client, db)
    _calc, line = _plan_line(db, user)
    resp = client.post(
        f"{BASE}/proposed-activities/{line.id}/year-details",
        headers=headers,
        json={"year_number": 2, "quantity": -1, "yearly_budget": 10},
    )
    assert resp.status_code == 422


def test_the_default_budget_of_a_plan_line_may_be_zero_but_not_the_default_quantity(
    client, db
):
    headers, user = _login(client, db)
    calc, line = _plan_line(db, user)
    pa2 = PotentialActivity(
        progarms="Program", activities="Volunteer patrol", display_order=1
    )
    db.add(pa2)
    db.commit()

    ok = client.post(
        f"{BASE}/calculations/{calc.id}/proposed-activities",
        headers=headers,
        json={
            "potential_activity_id": pa2.id,
            "default_quantity": 4,
            "default_yearly_budget": 0,
        },
    )
    assert ok.status_code == 200, ok.text  # D17: a wholly voluntary activity
    assert float(ok.json()["default_yearly_budget"]) == 0

    bad = client.post(
        f"{BASE}/calculations/{calc.id}/proposed-activities",
        headers=headers,
        json={
            "potential_activity_id": pa2.id,
            "default_quantity": 0,
            "default_yearly_budget": 5,
        },
    )
    assert bad.status_code == 422  # the default quantity stays > 0


def test_totals_treat_a_stored_zero_as_zero_not_as_the_default(client, db):
    headers, user = _login(client, db)
    calc, line = _plan_line(db, user, default_quantity=2, default_budget=1000)
    _year(db, line, 1, quantity=0, budget=0)  # explicit "not planned"
    _year(db, line, 2, quantity=2, budget=500)  # override

    listed = client.get(
        f"{BASE}/calculations/{calc.id}/proposed-activities", headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert float(listed.json()[0]["total_budget_10_years"]) == 0 + 500 + 8 * 1000

    summary = client.get(
        f"{BASE}/calculations/{calc.id}/summary", headers=headers
    ).json()
    assert summary["by_year"]["1"] == 0  # was 1000: 0 is falsy, so the default was used
    assert summary["by_year"]["2"] == 500
    assert summary["by_year"]["3"] == 1000
    assert float(summary["total_budget_10_years"]) == 0 + 500 + 8 * 1000


# ------------------------------------------------------------------------- ownership (YA-0a.7)
def _owned_fixtures(db, owner):
    calc, line = _plan_line(db, owner)
    detail = _year(db, line, 1, quantity=1, budget=10)
    assignment = ActivitySpatialAssignment(
        proposed_activity_id=line.id, assignment_type="all_blocks"
    )
    feature = ActivityDrawnFeature(
        proposed_activity_id=line.id,
        calculation_id=calc.id,
        feature_type="point",
        geometry="SRID=4326;POINT(85.05 27.44)",
        properties={"name": "spot", "years": [1]},
    )
    db.add_all([assignment, feature])
    db.commit()
    return calc, line, detail, assignment, feature


def _routes(line, detail, assignment, feature):
    a = f"{BASE}/proposed-activities/{line.id}"
    point = json.dumps({"type": "Point", "coordinates": [85.05, 27.44]})
    # destructive calls last, so the owner's run does not delete what a later call needs
    return [
        ("get", f"{a}/spatial", None),
        ("post", f"{a}/spatial", {"assignment_type": "all_blocks"}),
        ("get", f"{a}/drawn-features", None),
        (
            "post",
            f"{a}/drawn-features",
            {"feature_type": "point", "geometry": point, "properties": {}},
        ),
        (
            "patch",
            f"{a}/drawn-features/{feature.id}",
            {"properties": {"name": "renamed"}},
        ),
        ("post", f"{a}/drawn-features/{feature.id}/copy", {"target_year": 2}),
        ("get", f"{a}/year-details", None),
        (
            "post",
            f"{a}/year-details",
            {"year_number": 5, "quantity": 1, "yearly_budget": 1},
        ),
        ("patch", f"{a}/year-details/{detail.id}", {"quantity": 3}),
        ("delete", f"{a}/spatial/{assignment.id}", None),
        ("delete", f"{a}/drawn-features/{feature.id}", None),
        ("delete", f"{a}/year-details/{detail.id}", None),
    ]


@pytest.mark.parametrize("intruder_role", [UserRole.USER, UserRole.SUPER_ADMIN])
def test_every_per_activity_route_is_404_for_anyone_but_the_owner(
    client, db, intruder_role
):
    """F12 + D9: a user who knows an activity's UUID must not read or change another forest's
    plan — and a super-admin gets the same 404 (owner only)."""
    _owner_headers, owner = _login(client, db)
    _calc, line, detail, assignment, feature = _owned_fixtures(db, owner)
    intruder_headers, _ = _login(client, db, role=intruder_role)

    for method, url, body in _routes(line, detail, assignment, feature):
        resp = getattr(client, method)(
            url, headers=intruder_headers, **({"json": body} if body else {})
        )
        assert resp.status_code == 404, (method, url, resp.status_code, resp.text)

    # nothing was changed
    db.expire_all()
    assert (
        db.query(ActivityYearDetail).filter_by(proposed_activity_id=line.id).count()
        == 1
    )
    assert (
        db.query(ActivitySpatialAssignment)
        .filter_by(proposed_activity_id=line.id)
        .count()
        == 1
    )
    assert (
        db.query(ActivityDrawnFeature).filter_by(proposed_activity_id=line.id).count()
        == 1
    )
    assert db.get(ActivityYearDetail, detail.id).quantity == 1


def test_the_owner_still_reaches_every_route(client, db):
    owner_headers, owner = _login(client, db)
    _calc, line, detail, assignment, feature = _owned_fixtures(db, owner)
    for method, url, body in _routes(line, detail, assignment, feature):
        resp = getattr(client, method)(
            url, headers=owner_headers, **({"json": body} if body else {})
        )
        assert resp.status_code == 200, (method, url, resp.status_code, resp.text)


# ---------------------------------------------------------------- OP data cache (YA-0a.11)
def _seed_cache(db, calc):
    db.merge(
        OpDataCache(
            calculation_id=calc.id, data={"_cache_version": 0, "sentinel": True}
        )
    )
    db.commit()


def _cache_present(db, calc):
    db.expire_all()
    return (
        db.query(OpDataCache).filter(OpDataCache.calculation_id == calc.id).count() == 1
    )


def test_the_op_cache_drops_when_a_year_row_is_created(client, db):
    headers, user = _login(client, db)
    calc, line = _plan_line(db, user)
    _seed_cache(db, calc)
    resp = client.post(
        f"{BASE}/proposed-activities/{line.id}/year-details",
        headers=headers,
        json={"year_number": 3, "quantity": 0, "yearly_budget": 0},
    )
    assert resp.status_code == 200, resp.text
    assert not _cache_present(
        db, calc
    )  # the year rows feed the OP's ya_* and cba_* variables


def test_the_op_cache_drops_when_a_year_row_is_updated(client, db):
    headers, user = _login(client, db)
    calc, line = _plan_line(db, user)
    detail = _year(db, line, 3, quantity=1, budget=10)
    _seed_cache(db, calc)
    resp = client.patch(
        f"{BASE}/proposed-activities/{line.id}/year-details/{detail.id}",
        headers=headers,
        json={"yearly_budget": 99},
    )
    assert resp.status_code == 200, resp.text
    assert not _cache_present(db, calc)


def test_the_op_cache_drops_when_a_year_row_is_deleted(client, db):
    headers, user = _login(client, db)
    calc, line = _plan_line(db, user)
    detail = _year(db, line, 3, quantity=1, budget=10)
    _seed_cache(db, calc)
    resp = client.delete(
        f"{BASE}/proposed-activities/{line.id}/year-details/{detail.id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert not _cache_present(db, calc)


def test_the_op_cache_drops_when_a_spatial_assignment_is_created_or_deleted(client, db):
    headers, user = _login(client, db)
    calc, line = _plan_line(db, user)
    _seed_cache(db, calc)
    created = client.post(
        f"{BASE}/proposed-activities/{line.id}/spatial",
        headers=headers,
        json={"assignment_type": "all_blocks"},
    )
    assert created.status_code == 200, created.text
    assert not _cache_present(db, calc)

    _seed_cache(db, calc)
    deleted = client.delete(
        f"{BASE}/proposed-activities/{line.id}/spatial/{created.json()['id']}",
        headers=headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert not _cache_present(db, calc)


# ------------------------------------------------------------- zero-year matrix (YA-0a.8)
# One plan whose years cover (quantity, budget) in {(5,5), (5,0), (0,5), (0,0), NULL} is run through
# every server-side consumer; each must treat each year identically. (The legacy CSV is built in the
# browser and is covered by the frontend tests.)
_MATRIX = {  # year -> (quantity, budget) on the year row; years 6-10 have no row at all
    1: (5, 5),  # planned and funded
    2: (5, 0),  # planned, no cost
    3: (0, 5),  # funded, no countable output
    4: (0, 0),  # NOT planned
    5: (None, None),  # a row with no values -> the line's defaults (2 x 1000)
}
_DEFAULT_QTY, _DEFAULT_BUDGET = 2, 1000


def _expected_budget(year):
    if year in _MATRIX and _MATRIX[year][1] is not None:
        return _MATRIX[year][1]
    return _DEFAULT_BUDGET


def _expected_planned(year):
    qty, bud = _MATRIX.get(year, (None, None))
    qty = _DEFAULT_QTY if qty is None else qty
    bud = _DEFAULT_BUDGET if bud is None else bud
    return qty > 0 or bud > 0


def _matrix_plan(db, user):
    calc, line = _plan_line(
        db, user, default_quantity=_DEFAULT_QTY, default_budget=_DEFAULT_BUDGET
    )
    for year, (qty, bud) in _MATRIX.items():
        db.add(
            ActivityYearDetail(
                proposed_activity_id=line.id,
                year_number=year,
                quantity=qty,
                yearly_budget=bud,
            )
        )
    db.add(
        ActivityDrawnFeature(
            proposed_activity_id=line.id,
            calculation_id=calc.id,
            feature_type="point",
            geometry="SRID=4326;POINT(85.05 27.44)",
            properties={"name": "spot"},
        )
    )
    db.commit()
    return calc, line


def test_every_server_consumer_reads_the_zero_year_matrix_the_same_way(client, db):
    headers, user = _login(client, db)
    calc, line = _matrix_plan(db, user)
    years = range(1, 11)
    budget = {y: _expected_budget(y) for y in years}
    planned = [y for y in years if _expected_planned(y)]
    total = sum(budget.values())
    assert planned == [1, 2, 3, 5, 6, 7, 8, 9, 10] and total == 6010  # the table itself

    # 1. the proposed-activities list
    listed = client.get(
        f"{BASE}/calculations/{calc.id}/proposed-activities", headers=headers
    ).json()
    assert float(listed[0]["total_budget_10_years"]) == total

    # 2. /summary
    summary = client.get(
        f"{BASE}/calculations/{calc.id}/summary", headers=headers
    ).json()
    assert {int(k): v for k, v in summary["by_year"].items()} == {
        y: float(b) for y, b in budget.items()
    }
    assert float(summary["total_budget_10_years"]) == total

    # 3. the operational plan's ya_* variables
    from app.services.operational_plan.data_collector import (
        _collect_yearly_activities_data,
    )

    op = _collect_yearly_activities_data(db, str(calc.id))
    by_year = {r["year"]: r for r in op["year_summary"]}
    for y in years:
        assert by_year[y]["total_budget"] == float(budget[y]), y
        assert by_year[y]["activity_count"] == (1 if _expected_planned(y) else 0), y

    # 4. the plan-map collector (the opsmap maps)
    from app.services.operational_plan import plan_collector

    slots = plan_collector.by_year(db, calc.id)
    for y in years:
        assert slots[y]["budget"] == float(budget[y]), y
        assert slots[y]["activity_count"] == (1 if _expected_planned(y) else 0), y

    # 5. the map service: a feature belongs to the years its activity is planned
    from app.services.management_plan_docx.plan_map_service import (
        _get_activity_features,
    )

    for y in years:
        found = _get_activity_features(db, calc.id, year=y)
        assert (len(found) == 1) == _expected_planned(y), y
    assert _get_activity_features(db, calc.id)[0]["years"] == planned

    # 6. CBA re-populate: one cost row per run of equal yearly budgets (D28) - years 1, 3 and 5-10 -
    #    and the rows add up to the true ten-year total
    from app.models.cost_benefit import CBACostItem, CostBenefitAnalysis
    from app.services.cost_benefit.repopulate import repopulate_scenario

    scenario = CostBenefitAnalysis(
        calculation_id=calc.id, name="Base", is_base_scenario=True
    )
    db.add(scenario)
    db.commit()
    repopulate_scenario(scenario.id, db)
    costs = (
        db.query(CBACostItem)
        .filter_by(cba_id=scenario.id)
        .order_by(CBACostItem.year_from)
        .all()
    )
    assert [(c.year_from, c.year_to, float(c.amount_per_year)) for c in costs] == [
        (1, 1, 5.0),
        (3, 3, 5.0),
        (5, 10, 1000.0),
    ]  # the 0-budget years 2 and 4 make no row
    assert sum(float(c.total_amount) for c in costs) == total
