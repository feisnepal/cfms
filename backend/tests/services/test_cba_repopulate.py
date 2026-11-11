"""CBA re-populate sync (CBA_MODULE_PLAN.md P2).

Verifies the sync contract: INSERT a new source, UPDATE an existing auto row,
DELETE a stale auto row, and never touch a manual row (``source_link IS NULL``).
Re-running with unchanged data makes no inserts or deletes.
"""

from __future__ import annotations

import uuid

from app.models.cost_benefit import CBABenefitItem, CBACostItem, CostBenefitAnalysis
from app.models.field_inventory import (
    FieldInventoryBlockSummary,
    FieldInventoryCalculation,
)
from app.models.user import User, UserRole
from app.models.yearly_activities import PotentialActivity, ProposedYearlyActivity
from app.models.calculation import Calculation
from app.services.cost_benefit.repopulate import repopulate_scenario
from app.services.optimistic_lock import check_and_bump


def _user(db):
    u = User(
        email=f"cba{uuid.uuid4().hex[:8]}@test.com",
        full_name="CBA Tester",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    return u


def _calc(db, user):
    c = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="cba.csv",
        is_draft=False,
    )
    db.add(c)
    db.flush()
    return c


def _scenario(db, calc):
    s = CostBenefitAnalysis(calculation_id=calc.id, name="Base", is_base_scenario=True)
    db.add(s)
    db.flush()
    return s


def _activity(db, calc, program, name, budget, order=0):
    pa = PotentialActivity(progarms=program, activities=name, display_order=order)
    db.add(pa)
    db.flush()
    pya = ProposedYearlyActivity(
        calculation_id=calc.id,
        potential_activity_id=pa.id,
        default_quantity=1,
        default_yearly_budget=budget,
    )
    db.add(pya)
    db.flush()
    return pya


def _fi_block(db, calc, user, name, *, timber=0, fuelwood=0, carbon=0, fic=None):
    if fic is None:
        fic = FieldInventoryCalculation(
            calculation_id=calc.id, user_id=user.id, uploaded_filename="fi.csv"
        )
        db.add(fic)
        db.flush()
    bs = FieldInventoryBlockSummary(
        field_inventory_calculation_id=fic.id,
        block_name=name,
        total_sample_plots=3,
        tree_timber_m3_per_ha=timber,
        pole_timber_m3_per_ha=0,
        tree_firewood_m3_per_ha=fuelwood,
        pole_firewood_m3_per_ha=0,
        co2_equivalent_tco2_per_ha=carbon,
    )
    db.add(bs)
    db.flush()
    return fic


def test_first_run_inserts_costs_and_benefits(db):
    user = _user(db)
    calc = _calc(db, user)
    scn = _scenario(db, calc)
    _activity(db, calc, "वन संवर्द्धन", "Thinning", 5000, order=1)
    _activity(db, calc, "उद्यम विकास", "Nursery", 8000, order=2)
    _fi_block(db, calc, user, "Block A", timber=50, fuelwood=30, carbon=10)
    db.flush()

    stats = repopulate_scenario(scn.id, db)

    assert stats["inserted"]["costs"] == 2
    assert stats["inserted"]["benefits"] == 3  # timber + fuelwood + carbon
    assert stats["deleted"] == {"costs": 0, "benefits": 0}

    costs = db.query(CBACostItem).filter_by(cba_id=scn.id).all()
    assert all(c.source_link.startswith("activity:") for c in costs)
    thin = next(c for c in costs if c.description == "Thinning")
    assert float(thin.amount_per_year) == 5000.0
    assert float(thin.total_amount) == 50000.0  # 10-year sum
    assert thin.year_from == 1 and thin.year_to == 10
    assert thin.category == "वन संवर्द्धन"

    benefits = db.query(CBABenefitItem).filter_by(cba_id=scn.id).all()
    by_src = {b.source: b for b in benefits}
    assert float(by_src["timber"].quantity) == 50.0
    assert float(by_src["timber"].unit_price) == 8000.0  # FALLBACK_RATES.timber_mixed
    assert float(by_src["timber"].amount_per_year) == 400000.0
    assert float(by_src["carbon"].unit_price) == 3000.0


def test_second_run_is_idempotent(db):
    user = _user(db)
    calc = _calc(db, user)
    scn = _scenario(db, calc)
    _activity(db, calc, "P", "A1", 5000)
    _fi_block(db, calc, user, "B1", timber=20)
    db.flush()

    repopulate_scenario(scn.id, db)
    stats2 = repopulate_scenario(scn.id, db)

    assert stats2["inserted"] == {"costs": 0, "benefits": 0}
    assert stats2["deleted"] == {"costs": 0, "benefits": 0}
    assert stats2["updated"]["costs"] == 1
    assert stats2["updated"]["benefits"] == 1


def test_manual_rows_are_never_touched(db):
    user = _user(db)
    calc = _calc(db, user)
    scn = _scenario(db, calc)
    _activity(db, calc, "P", "A1", 5000)
    db.flush()

    manual = CBACostItem(
        cba_id=scn.id,
        category="Opportunity cost",
        description="Grazing forgone",
        year_from=1,
        year_to=10,
        amount_per_year=12345,
        source_link=None,
    )
    db.add(manual)
    manual_ben = CBABenefitItem(
        cba_id=scn.id,
        source="eco_tourism",
        description="Homestay fees",
        year_from=2,
        year_to=10,
        amount_per_year=50000,
        source_link=None,
    )
    db.add(manual_ben)
    db.flush()

    repopulate_scenario(scn.id, db)

    still = db.get(CBACostItem, manual.id)
    assert still is not None
    assert float(still.amount_per_year) == 12345.0
    assert still.description == "Grazing forgone"
    assert db.get(CBABenefitItem, manual_ben.id) is not None
    # the auto activity row was added alongside
    assert (
        db.query(CBACostItem)
        .filter_by(cba_id=scn.id)
        .filter(CBACostItem.source_link.isnot(None))
        .count()
        == 1
    )


def test_stale_auto_rows_are_deleted_manual_kept(db):
    user = _user(db)
    calc = _calc(db, user)
    scn = _scenario(db, calc)
    _activity(db, calc, "P", "Keep", 5000)
    a2 = _activity(db, calc, "P", "Drop", 7000)
    db.flush()
    repopulate_scenario(scn.id, db)
    assert db.query(CBACostItem).filter_by(cba_id=scn.id).count() == 2

    # a villager adds a manual row, then activity a2 is removed from the plan
    db.add(
        CBACostItem(
            cba_id=scn.id,
            category="Manual",
            description="kept",
            year_from=1,
            year_to=1,
            amount_per_year=1,
            source_link=None,
        )
    )
    db.delete(db.get(ProposedYearlyActivity, a2.id))
    db.flush()

    stats = repopulate_scenario(scn.id, db)
    assert stats["deleted"]["costs"] == 1

    rows = db.query(CBACostItem).filter_by(cba_id=scn.id).all()
    descs = {r.description for r in rows}
    assert descs == {"Keep", "kept"}  # Drop gone, manual survived


def test_budget_change_updates_amount(db):
    user = _user(db)
    calc = _calc(db, user)
    scn = _scenario(db, calc)
    pya = _activity(db, calc, "P", "A1", 5000)
    db.flush()
    repopulate_scenario(scn.id, db)

    check_and_bump(
        db, "yearly_plan", pya.id, None
    )  # what the API does before it edits a plan line
    pya.default_yearly_budget = 9000
    db.flush()
    repopulate_scenario(scn.id, db)

    row = (
        db.query(CBACostItem)
        .filter_by(cba_id=scn.id, source_link=f"activity:{pya.id}:1-10")
        .one()
    )
    assert float(row.amount_per_year) == 9000.0
    assert float(row.total_amount) == 90000.0


def test_zeroing_an_activitys_budget_removes_its_auto_cost_row_but_not_a_manual_one(db):
    """The auto row used to be kept at its old amount: the key was marked "current" before the
    zero-budget skip, so the delete sweep never saw it (YEARLY_ACTIVITIES plan §5.8 item 3).
    """
    from app.models.yearly_activities import ActivityYearDetail

    user = _user(db)
    calc = _calc(db, user)
    scenario = _scenario(db, calc)
    line = _activity(db, calc, "Prog", "Nursery", budget=1000)
    manual = CBACostItem(
        cba_id=scenario.id,
        category="Other",
        description="Hand-entered cost",
        year_from=1,
        year_to=10,
        amount_per_year=50,
        total_amount=500,
        source_link=None,
    )
    db.add(manual)
    db.flush()

    repopulate_scenario(scenario.id, db)
    auto = (
        db.query(CBACostItem)
        .filter_by(cba_id=scenario.id, source_link=f"activity:{line.id}:1-10")
        .one()
    )
    assert float(auto.amount_per_year) == 1000.0

    # the user zeroes the activity's budget everywhere (default and every year row)
    check_and_bump(db, "yearly_plan", line.id, None)
    line.default_yearly_budget = 0
    for year in range(1, 11):
        db.add(
            ActivityYearDetail(
                proposed_activity_id=line.id,
                year_number=year,
                quantity=1,
                yearly_budget=0,
            )
        )
    db.flush()

    stats = repopulate_scenario(scenario.id, db)

    left = db.query(CBACostItem).filter_by(cba_id=scenario.id).all()
    assert [c.source_link for c in left] == [
        None
    ]  # the auto row is gone; the manual row survives
    assert left[0].description == "Hand-entered cost"
    assert stats["deleted"]["costs"] == 1


# --------------------------------------------------------------- D28: one row per run of equal budgets
def _year_rows(db, line, budgets):
    """Give a plan line explicit year rows: ``budgets`` = {year: budget}, every other year 0."""
    from app.models.yearly_activities import ActivityYearDetail

    for year in range(1, 11):
        db.add(
            ActivityYearDetail(
                proposed_activity_id=line.id,
                year_number=year,
                quantity=1 if budgets.get(year, 0) else 0,
                yearly_budget=budgets.get(year, 0),
            )
        )
    db.flush()


def _cost_rows(db, scn):
    db.expire_all()
    return (
        db.query(CBACostItem)
        .filter_by(cba_id=scn.id)
        .order_by(CBACostItem.year_from)
        .all()
    )


def test_a_campaign_budgeted_for_years_1_to_3_is_one_row_for_years_1_to_3(db):
    """Averaging put NPR 60,000 for Years 1-3 in as 18,000 over ten years: the same total, but the
    discounting saw the money spent later and lighter than it is."""
    user = _user(db)
    calc = _calc(db, user)
    scn = _scenario(db, calc)
    line = _activity(db, calc, "P", "Nursery", 1)
    _year_rows(db, line, {1: 60000, 2: 60000, 3: 60000})

    repopulate_scenario(scn.id, db)

    (row,) = _cost_rows(db, scn)
    assert (row.year_from, row.year_to) == (1, 3)
    assert float(row.amount_per_year) == 60000.0 and float(row.total_amount) == 180000.0
    assert row.source_link == f"activity:{line.id}:1-3"


def test_the_same_amount_in_two_separate_stretches_is_two_rows(db):
    user = _user(db)
    calc = _calc(db, user)
    scn = _scenario(db, calc)
    line = _activity(db, calc, "P", "Road", 1)
    _year_rows(db, line, {1: 500, 3: 500})  # year 2 is 0: it ends the run

    repopulate_scenario(scn.id, db)

    assert [
        (c.year_from, c.year_to, float(c.amount_per_year)) for c in _cost_rows(db, scn)
    ] == [
        (1, 1, 500.0),
        (3, 3, 500.0),
    ]


import pytest  # noqa: E402


@pytest.mark.parametrize(
    "budgets",
    [
        {y: 1000 for y in range(1, 11)},  # flat
        {1: 60000, 2: 60000, 3: 60000},  # a campaign
        {1: 100, 2: 200, 3: 300, 4: 300, 6: 50},  # rising, then a gap
        {y: 10 * y for y in range(1, 11)},  # every year different
        {2: 7.5, 3: 7.5, 9: 7.5, 10: 7.5},  # decimals, two stretches
    ],
)
def test_the_rows_reproduce_the_budget_of_every_year_exactly(db, budgets):
    """Timing fidelity + conservation: laid over the plan years, the rows give back each year's budget,
    and their totals add up to the plan line's ten-year total."""
    user = _user(db)
    calc = _calc(db, user)
    scn = _scenario(db, calc)
    line = _activity(db, calc, "P", "Anything", 1)
    _year_rows(db, line, budgets)

    repopulate_scenario(scn.id, db)

    rows = _cost_rows(db, scn)
    by_year = {y: 0.0 for y in range(1, 11)}
    for c in rows:
        for y in range(c.year_from, c.year_to + 1):
            by_year[y] += float(c.amount_per_year)
    assert by_year == {y: float(budgets.get(y, 0)) for y in range(1, 11)}
    assert round(sum(float(c.total_amount) for c in rows), 2) == round(
        sum(budgets.values()), 2
    )


def test_an_old_averaged_row_is_replaced_and_a_manual_row_is_left_alone(db):
    user = _user(db)
    calc = _calc(db, user)
    scn = _scenario(db, calc)
    line = _activity(db, calc, "P", "Nursery", 1)
    _year_rows(db, line, {1: 60000, 2: 60000, 3: 60000})
    db.add_all(
        [
            # what the previous scheme wrote: one row averaged over ten years
            CBACostItem(
                cba_id=scn.id,
                category="P",
                description="Nursery",
                year_from=1,
                year_to=10,
                amount_per_year=18000,
                total_amount=180000,
                source_link=f"activity:{line.id}",
            ),
            CBACostItem(
                cba_id=scn.id,
                category="Other",
                description="Hand-entered",
                year_from=1,
                year_to=10,
                amount_per_year=50,
                total_amount=500,
                source_link=None,
            ),
        ]
    )
    db.flush()

    stats = repopulate_scenario(scn.id, db)

    keys = sorted(str(c.source_link) for c in _cost_rows(db, scn))
    assert keys == sorted(
        ["None", f"activity:{line.id}:1-3"]
    )  # the averaged row is gone
    assert stats["deleted"]["costs"] == 1 and stats["inserted"]["costs"] == 1


def test_a_locked_row_named_like_an_activity_is_warned_about_never_deleted(db):
    """A user "locked" the averaged auto row (it became manual). The activity now comes back as new
    automatic rows, so it would be counted twice: say so, and never delete the user's row.
    """
    user = _user(db)
    calc = _calc(db, user)
    scn = _scenario(db, calc)
    line = _activity(db, calc, "P", "Nursery", 1000)
    db.add(
        CBACostItem(
            cba_id=scn.id,
            category="P",
            description="Nursery",
            year_from=1,
            year_to=10,
            amount_per_year=1000,
            total_amount=10000,
            source_link=None,
        )
    )
    db.flush()

    stats = repopulate_scenario(scn.id, db)

    assert len(stats["warnings"]) == 1 and "Nursery" in stats["warnings"][0]
    descriptions = [(c.description, c.source_link is None) for c in _cost_rows(db, scn)]
    assert ("Nursery", True) in descriptions  # the manual row survives
    assert any(
        sl is False for _d, sl in descriptions
    )  # and the automatic row exists beside it
    assert line.id  # (the activity itself is unchanged)
