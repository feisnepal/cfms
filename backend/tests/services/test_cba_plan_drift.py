"""The read-only CBA drift check (YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.8 item 5): it tells the user when
the yearly plan has moved on from the cost-benefit scenario — and writes nothing."""

from __future__ import annotations

import uuid

from app.models.calculation import Calculation
from app.models.cost_benefit import CBACostItem, CostBenefitAnalysis
from app.models.user import User, UserRole
from app.models.yearly_activities import PotentialActivity, ProposedYearlyActivity
from app.services.cost_benefit.repopulate import plan_drift, repopulate_scenario
from app.services.optimistic_lock import check_and_bump


def _setup(db):
    user = User(
        email=f"drift{uuid.uuid4().hex[:8]}@test.com",
        full_name="Drift Tester",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()), user_id=user.id, uploaded_filename="d.csv", is_draft=False
    )
    db.add(calc)
    db.flush()
    scenario = CostBenefitAnalysis(
        calculation_id=calc.id, name="Base", is_base_scenario=True
    )
    db.add(scenario)
    db.commit()
    return calc, scenario


def _line(db, calc, name, budget):
    master = PotentialActivity(progarms="Prog", activities=name, display_order=0)
    db.add(master)
    db.flush()
    line = ProposedYearlyActivity(
        calculation_id=calc.id,
        potential_activity_id=master.id,
        default_quantity=1,
        default_yearly_budget=budget,
    )
    db.add(line)
    db.commit()
    return line


def _rows(db, scenario):
    db.expire_all()
    return sorted(
        (c.source_link, float(c.amount_per_year), float(c.total_amount))
        for c in db.query(CBACostItem).filter_by(cba_id=scenario.id)
    )


def test_right_after_a_repopulate_there_is_no_drift_and_the_check_writes_nothing(db):
    calc, scenario = _setup(db)
    _line(db, calc, "Nursery", 1000)
    repopulate_scenario(scenario.id, db)
    before = _rows(db, scenario)

    drift = plan_drift(scenario.id, db)

    assert drift == {"out_of_date": False, "added": [], "removed": [], "changed": []}
    assert _rows(db, scenario) == before


def test_a_plan_edit_shows_up_as_a_change_and_the_check_still_writes_nothing(db):
    calc, scenario = _setup(db)
    line = _line(db, calc, "Nursery", 1000)
    repopulate_scenario(scenario.id, db)
    before = _rows(db, scenario)

    check_and_bump(
        db, "yearly_plan", line.id, None
    )  # what the API does before it edits a line
    line.default_yearly_budget = 4000
    db.commit()
    drift = plan_drift(scenario.id, db)

    assert drift["out_of_date"] is True
    assert (
        drift["changed"] == [f"activity:{line.id}:1-10"]
        and drift["added"] == []
        and drift["removed"] == []
    )
    assert (
        _rows(db, scenario) == before
    )  # nothing was updated: the user decides when to Update
    repopulate_scenario(scenario.id, db)
    assert plan_drift(scenario.id, db)["out_of_date"] is False  # and Update clears it


def test_a_new_and_a_deleted_plan_line_are_seen(db):
    calc, scenario = _setup(db)
    gone = _line(db, calc, "Gone", 500)
    repopulate_scenario(scenario.id, db)
    added = _line(db, calc, "Added", 700)
    db.delete(gone)
    db.commit()

    drift = plan_drift(scenario.id, db)

    assert drift["added"] == [f"activity:{added.id}:1-10"]
    assert drift["removed"] == [
        f"activity:{gone.id}:1-10"
    ]  # a "modified since" check could not see this


def test_a_manual_row_is_not_part_of_the_drift_and_the_session_stays_usable(db):
    calc, scenario = _setup(db)
    _line(db, calc, "Nursery", 1000)
    db.add(
        CBACostItem(
            cba_id=scenario.id,
            category="Other",
            description="Hand-entered",
            year_from=1,
            year_to=10,
            amount_per_year=5,
            total_amount=50,
            source_link=None,
        )
    )
    db.commit()
    repopulate_scenario(scenario.id, db)

    assert plan_drift(scenario.id, db)["out_of_date"] is False
    scenario.name = "Renamed after the check"  # the session is still healthy after the rolled-back savepoint
    db.commit()
    db.expire_all()
    assert db.get(CostBenefitAnalysis, scenario.id).name == "Renamed after the check"
