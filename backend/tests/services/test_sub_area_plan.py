"""Sub-areas must be tied to the yearly plan (owner rule 2026-10-08): the service that says who is planned and creates the lines."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from shapely.geometry import box, mapping
from sqlalchemy.orm.attributes import flag_modified

from app.models.forest_block import ForestBlock
from app.models.yearly_activities import ActivitySpatialAssignment, PotentialActivity, ProposedYearlyActivity
from app.services.optimistic_lock import check_and_bump
from app.services import sub_area_plan as sp
from app.services import yearly_plan_service as plan
from tests.services.test_sampling_stratified import _setup_two_equal_blocks


def _sub_area(db, calc, *, category="plantation", geom=None, name="SA", with_id=True, block_id=None):
    geom = geom or box(83.482, 27.497, 83.486, 27.501)  # inside Block-1
    sa = {"name": name, "category": category, "geometry": mapping(geom), "area_hectares": 2.5,
          "is_excluded": category == "private_land"}
    if with_id:
        sa["id"] = str(uuid.uuid4())
    if block_id:
        sa["blockId"] = block_id
    data = dict(calc.result_data or {})
    data["sub_areas"] = [*(data.get("sub_areas") or []), sa]
    calc.result_data = data
    flag_modified(calc, "result_data")
    db.commit()
    return sa


def _master(db, unit="हेक्टर", map_kind="plantation", budget="0"):
    pa = PotentialActivity(progarms="P", activities=f"A-{uuid.uuid4().hex[:6]}", unit=unit, requires_map=False,
                           display_order=0, is_active=True, map_kind=map_kind, yearly_budget=budget)
    db.add(pa)
    db.commit()
    return pa


def _state(db, calc, sa):
    return next(s for s in sp.sub_area_plan_status(db, calc) if s["name"] == sa["name"])


def test_a_new_sub_area_needs_a_plan(db):
    calc = _setup_two_equal_blocks(db)
    sa = _sub_area(db, calc)
    s = _state(db, calc, sa)
    assert s["state"] == sp.NEEDS_PLAN and s["unit_id"] and s["line_ids"] == []
    assert [x["id"] for x in sp.sub_areas_needing_plan(sp.sub_area_plan_status(db, calc))] == [sa["id"]]


def test_only_private_land_and_the_strips_are_exempt_and_office_is_not(db):
    calc = _setup_two_equal_blocks(db)
    private = _sub_area(db, calc, category="private_land", name="P")
    office = _sub_area(db, calc, category="office", name="O")
    assert _state(db, calc, private)["state"] == sp.EXEMPT
    assert _state(db, calc, office)["state"] == sp.NEEDS_PLAN
    fire_line = _sub_area(db, calc, category="fire_line", name="F")
    assert _state(db, calc, fire_line)["state"] == sp.EXEMPT
    # a strip is planned through its own yearly activity (created from the strip), never as a zone needing a plan
    assert sp.SUB_AREA_PLAN_EXEMPT_CATEGORIES == {"private_land", "fire_line", "river_bank"}


def test_a_hectare_activity_starts_at_the_sub_areas_area_and_counts_as_a_plan(db):
    calc = _setup_two_equal_blocks(db)
    sa = _sub_area(db, calc)
    m = _master(db, budget="1000")
    made = sp.create_plan_lines(db, calc, sa["id"], [m.id])
    db.commit()
    assert made[0]["created"]
    line = db.query(ProposedYearlyActivity).filter_by(id=made[0]["line_id"]).one()
    assert float(line.default_quantity) == 2.5 and str(line.sub_area_id) == sa["id"] and line.block_id is not None
    assert line.reviewed_at is not None  # the area is a real number
    assert _state(db, calc, sa)["state"] == sp.PLANNED


def test_a_placeholder_line_does_not_count_as_a_plan(db):
    """Case A of the owner's rule: 'add activity' and typing nothing (1 / Rs 5,000 everywhere) is not a plan."""
    calc = _setup_two_equal_blocks(db)
    sa = _sub_area(db, calc)
    m = _master(db, unit="वटा", budget="5000")  # a count activity: no area to start from -> quantity 1, budget 5000
    sp.create_plan_lines(db, calc, sa["id"], [m.id])
    db.commit()
    assert _state(db, calc, sa)["state"] == sp.NEEDS_PLAN
    # once the user types real numbers it is a plan
    line = db.query(ProposedYearlyActivity).filter_by(sub_area_id=sa["id"]).one()
    check_and_bump(db, "yearly_plan", line.id, None)
    line.default_quantity = 4
    line.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    assert _state(db, calc, sa)["state"] == sp.PLANNED


def test_a_forest_line_assigned_to_the_sub_area_also_counts(db):
    calc = _setup_two_equal_blocks(db)
    sa = _sub_area(db, calc)
    unit_id = _state(db, calc, sa)["unit_id"]
    m = _master(db, budget="1000")
    line, _c, _r = plan.get_or_create_line(db, calc.id, m.id, numbers=plan.PlanNumbers(quantity=3))
    db.add(ActivitySpatialAssignment(proposed_activity_id=line.id, block_id=unit_id, sub_area_id=sa["id"], assignment_type="sub_area"))
    db.commit()
    assert _state(db, calc, sa)["state"] == sp.PLANNED


def test_creating_the_same_line_twice_gives_one_line(db):
    calc = _setup_two_equal_blocks(db)
    sa = _sub_area(db, calc)
    m = _master(db, budget="1000")
    first = sp.create_plan_lines(db, calc, sa["id"], [m.id])
    second = sp.create_plan_lines(db, calc, sa["id"], [m.id])
    db.commit()
    assert first[0]["line_id"] == second[0]["line_id"] and second[0]["created"] is False
    assert db.query(ProposedYearlyActivity).filter_by(sub_area_id=sa["id"]).count() == 1


def test_a_sub_area_in_no_unit_cannot_be_planned_and_is_named(db):
    calc = _setup_two_equal_blocks(db)
    sa = _sub_area(db, calc, geom=box(10, 10, 10.001, 10.001), name="Far")
    assert _state(db, calc, sa)["state"] == sp.NO_UNIT
    assert sa["id"] in [x["id"] for x in sp.sub_areas_needing_plan(sp.sub_area_plan_status(db, calc))]
    with pytest.raises(ValueError):
        sp.create_plan_lines(db, calc, sa["id"], [_master(db).id])


def test_a_sub_area_without_a_proper_id_is_reported_not_skipped(db):
    calc = _setup_two_equal_blocks(db)
    sa = _sub_area(db, calc, with_id=False, name="NoId")
    assert _state(db, calc, sa)["state"] == sp.NO_ID


def test_a_stored_unit_that_no_longer_exists_falls_back_to_the_overlap(db):
    calc = _setup_two_equal_blocks(db)
    sa = _sub_area(db, calc, block_id=str(uuid.uuid4()), name="Stale")
    block1 = db.query(ForestBlock).filter_by(calculation_id=calc.id, name="Block-1").one()
    assert _state(db, calc, sa)["unit_id"] == str(block1.id)


def test_suggestions_follow_the_category_and_unknown_categories_have_none(db):
    m = _master(db, map_kind="agroforestry_area")
    ids = [a["id"] for a in sp.suggested_activities(db, "agroforestry")]
    assert m.id in ids
    assert sp.suggested_activities(db, "no-such-category") == []
    for cat in ("protected", "tree_strata", "wildlife_corridor", "office"):
        assert sp.SUB_AREA_ACTIVITY_SUGGESTIONS[cat]


def test_a_sub_area_dropped_by_a_boundary_change_leaves_its_plan_lines_forest_wide(db):
    from app.services.sub_area_reclip_service import reclip_sub_areas_to_boundary

    calc = _setup_two_equal_blocks(db)
    sa = _sub_area(db, calc)
    m = _master(db, budget="1000")
    sp.create_plan_lines(db, calc, sa["id"], [m.id])
    db.commit()
    result = reclip_sub_areas_to_boundary(db, calc, box(83.50, 27.500, 83.51, 27.505))  # the boundary no longer contains it
    db.commit()
    assert result["dropped"] == ["SA"] and result["plan_lines_kept"] == 1
    line = db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id).one()
    assert line.sub_area_id is None and line.block_id is None


def test_orphaned_links_are_found_and_the_normal_flows_leave_none(db):
    calc = _setup_two_equal_blocks(db)
    sa = _sub_area(db, calc)
    m = _master(db, budget="1000")
    made = sp.create_plan_lines(db, calc, sa["id"], [m.id])
    db.commit()
    mine = lambda: [o for o in sp.orphaned_sub_area_links(db) if o["calculation_id"] == str(calc.id)]  # noqa: E731
    assert mine() == []
    # the sub-area vanishes WITHOUT the delete flow (what the report exists to catch)
    data = dict(calc.result_data)
    data["sub_areas"] = []
    calc.result_data = data
    flag_modified(calc, "result_data")
    db.commit()
    assert [(o["line_id"], o["via"]) for o in mine()] == [(made[0]["line_id"], "line")]
    # the proper flow clears it
    sp.release_sub_areas(db, calc.id, [sa["id"]], "delete")
    db.commit()
    assert mine() == []
