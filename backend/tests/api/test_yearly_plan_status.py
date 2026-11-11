"""Workflow step 15: the owner's "yearly activities are done" mark, and its automatic reopening (owner, 2026-10-15)."""

from __future__ import annotations

import uuid

from app.models.calculation import Calculation
from app.models.user import User
from app.models.yearly_activities import PotentialActivity, ProposedYearlyActivity
from app.services import yearly_plan_status as status
from app.services.optimistic_lock import check_and_bump
from app.services.operational_plan.prereq_check import check
from app.services.operational_plan.workflow_readiness import STEP_PREREQS

BASE = "/api/yearly-activities"


def _login(client, db):
    email = f"ypstatus-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "Status Owner"})
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, db.query(User).filter(User.email == email).first()


def _calc(db, user):
    calc = Calculation(user_id=user.id, uploaded_filename="x.csv", forest_name="Status CF")
    db.add(calc)
    db.flush()
    pa = PotentialActivity(progarms="P", activities="Plantation", display_order=0)
    db.add(pa)
    db.commit()
    return calc, pa


def _add_line(db, calc, pa):
    line = ProposedYearlyActivity(calculation_id=calc.id, potential_activity_id=pa.id, default_quantity=1, default_yearly_budget=10)
    db.add(line)
    db.commit()
    return line


def test_step_15_is_done_only_when_marked():
    assert STEP_PREREQS["yearly"] == ("yearly_activities_done",)


def test_not_done_until_the_owner_says_so(client, db):
    headers, user = _login(client, db)
    calc, pa = _calc(db, user)
    _add_line(db, calc, pa)
    assert check(db, calc.id, ["yearly_activities_done"]).met is False   # activities exist, still not done
    got = client.put(f"{BASE}/calculations/{calc.id}/yearly-plan/status", json={"done": True}, headers=headers)
    assert got.status_code == 200 and got.json()["done"] is True
    assert check(db, calc.id, ["yearly_activities_done"]).met is True
    assert client.get(f"{BASE}/calculations/{calc.id}/yearly-plan/status", headers=headers).json()["done"] is True


def test_done_can_be_switched_off_again(client, db):
    headers, user = _login(client, db)
    calc, _ = _calc(db, user)
    client.put(f"{BASE}/calculations/{calc.id}/yearly-plan/status", json={"done": True}, headers=headers)
    off = client.put(f"{BASE}/calculations/{calc.id}/yearly-plan/status", json={"done": False}, headers=headers).json()
    assert off["done"] is False and off["done_at"] is None and off["reopened_reason"] is None


def test_a_new_line_reopens_a_done_plan(client, db):
    headers, user = _login(client, db)
    calc, pa = _calc(db, user)
    client.put(f"{BASE}/calculations/{calc.id}/yearly-plan/status", json={"done": True}, headers=headers)
    _add_line(db, calc, pa)
    db.expire_all()
    got = status.get_status(db, calc.id)
    assert got["done"] is False and got["reopened_reason"] == "plan_changed"


def test_editing_and_deleting_a_line_also_reopen(client, db):
    headers, user = _login(client, db)
    calc, pa = _calc(db, user)
    line = _add_line(db, calc, pa)
    for change in ("edit", "delete"):
        client.put(f"{BASE}/calculations/{calc.id}/yearly-plan/status", json={"done": True}, headers=headers)
        db.expire_all()
        assert status.get_status(db, calc.id)["done"] is True
        if change == "edit":
            line = db.get(ProposedYearlyActivity, line.id)
            check_and_bump(db, "yearly_plan", line.id, None)  # a plan line is edited through its version, like the API does
            line.default_quantity = 5
        else:
            db.delete(db.get(ProposedYearlyActivity, line.id))
        db.commit()
        db.expire_all()
        assert status.get_status(db, calc.id)["done"] is False, change


def test_only_the_owner_may_read_or_set_it(client, db):
    headers, user = _login(client, db)
    other_headers, _ = _login(client, db)
    calc, _ = _calc(db, user)
    assert client.get(f"{BASE}/calculations/{calc.id}/yearly-plan/status", headers=other_headers).status_code == 404
    assert client.put(f"{BASE}/calculations/{calc.id}/yearly-plan/status", json={"done": True}, headers=other_headers).status_code == 404


def test_a_plan_change_in_another_forest_leaves_this_one_done(client, db):
    headers, user = _login(client, db)
    a, pa = _calc(db, user)
    b, pb = _calc(db, user)
    client.put(f"{BASE}/calculations/{a.id}/yearly-plan/status", json={"done": True}, headers=headers)
    _add_line(db, b, pb)
    db.expire_all()
    assert status.get_status(db, a.id)["done"] is True
