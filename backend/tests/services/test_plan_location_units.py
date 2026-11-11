"""The plan view names the forest units a line's places fall in (YEARLY_ACTIVITIES plan §4.4b, YA-4.4):
derived on read, leaf units only, natural order, live places only, and never an error."""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Point, box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.models.yearly_activities import (
    ActivityDrawnFeature,
    ActivitySpatialAssignment,
    PotentialActivity,
    ProposedYearlyActivity,
)
from app.services.plan_health_service import compute_health
from app.services.yearly_plan_service import derive_line_units, plan_view
from datetime import datetime, timezone


@pytest.fixture()
def calc(db):
    user = User(
        email=f"loc{uuid.uuid4().hex[:8]}@test.com",
        full_name="Location Tester",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(user)
    db.flush()
    c = Calculation(
        id=str(uuid.uuid4()), user_id=user.id, uploaded_filename="l.csv", is_draft=False
    )
    db.add(c)
    db.commit()
    return c


def _unit(db, calc, name, west, parent=None):
    row = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        block_name=name,
        geometry=from_shape(box(west, 27.0, west + 0.1, 27.1), srid=4326),
        area_hectares=1.0,
        index=0,
        parent_block_id=parent.id if parent is not None else None,
    )
    db.add(row)
    db.flush()
    return row


def _line(db, calc, requires_map=True):
    master = PotentialActivity(
        progarms="P",
        activities=f"A-{uuid.uuid4().hex[:4]}",
        display_order=0,
        requires_map=requires_map,
        unit="ha",
    )
    db.add(master)
    db.flush()
    line = ProposedYearlyActivity(
        calculation_id=calc.id,
        potential_activity_id=master.id,
        default_quantity=1,
        default_yearly_budget=100,
    )
    db.add(line)
    db.flush()
    return line


def _place(db, calc, line, lon, lat=27.05, deleted=False):
    db.add(
        ActivityDrawnFeature(
            proposed_activity_id=line.id,
            calculation_id=calc.id,
            feature_type="point",
            geometry=from_shape(Point(lon, lat), srid=4326),
            properties={"name": "p"},
            deleted_at=datetime.now(timezone.utc) if deleted else None,
        )
    )


def test_a_line_names_the_leaf_units_its_places_are_in_in_natural_order(db, calc):
    parent = _unit(db, calc, "Block-1", 85.0)  # divided into compartments below
    c2 = _unit(db, calc, "C-2", 85.0, parent=parent)
    _unit(db, calc, "C-10", 85.0, parent=parent)
    other = _unit(db, calc, "C-3", 85.5)
    line = _line(db, calc)
    _place(db, calc, line, 85.05)  # inside the parent and both of its compartments
    _place(db, calc, line, 85.55)  # inside C-3 only
    db.commit()

    row = plan_view(db, calc)[0]

    assert row["location_units"] == [
        "C-2",
        "C-3",
        "C-10",
    ]  # not the parent "Block-1"; C-2 before C-10
    assert row["feature_count"] == 2
    assert c2 and other


def test_a_deleted_place_and_a_place_outside_every_unit_name_nothing(db, calc):
    _unit(db, calc, "C-1", 85.0)
    line = _line(db, calc)
    _place(db, calc, line, 85.05, deleted=True)
    _place(db, calc, line, 80.0)  # outside the forest
    db.commit()

    row = plan_view(db, calc)[0]

    assert row["location_units"] == []
    assert row["feature_count"] == 1  # the live one; it is just not in any unit


def test_a_line_without_places_has_no_units_and_no_query_is_needed(db, calc):
    _unit(db, calc, "C-1", 85.0)
    _line(db, calc, requires_map=False)
    db.commit()

    row = plan_view(db, calc)[0]

    assert row["location_units"] == []
    assert row["location_mode"] == "not_applicable"
    assert derive_line_units(db, calc.id, []) == {}


def test_a_failure_gives_an_empty_answer_and_leaves_the_session_usable(db, calc):
    line = _line(db, calc)
    db.commit()

    # a value that is not a uuid makes the SQL fail: the answer is empty and the transaction survives
    assert derive_line_units(db, calc.id, ["not-a-uuid"]) == {}
    assert db.query(ProposedYearlyActivity).filter_by(id=line.id).count() == 1


# ------------------------------------------------- where an activity applies by ASSIGNMENT (the yearly-activities pages)
def _assign(db, line, kind, block=None, sub_area_id=None):
    db.add(
        ActivitySpatialAssignment(
            proposed_activity_id=line.id,
            block_id=block.id if block is not None else None,
            sub_area_id=sub_area_id,
            assignment_type=kind,
        )
    )


def test_blocks_chosen_for_a_line_without_places_make_its_location_units(db, calc):
    c10 = _unit(db, calc, "C-10", 85.0)
    c2 = _unit(db, calc, "C-2", 85.5)
    line = _line(db, calc)
    _assign(db, line, "block", c10)
    _assign(db, line, "block", c2)
    db.commit()

    row = plan_view(db, calc)[0]

    assert row["location_mode"] == "units"
    assert row["location_units"] == ["C-2", "C-10"]  # natural order
    assert row["feature_count"] == 0


def test_an_all_blocks_assignment_is_the_whole_forest(db, calc):
    line = _line(db, calc)
    _assign(db, line, "all_blocks")
    db.commit()

    row = plan_view(db, calc)[0]

    assert row["location_mode"] == "whole_forest"
    assert row["location_units"] == []


def test_a_line_with_nothing_chosen_still_needs_a_location_and_places_win_over_blocks(
    db, calc
):
    c1 = _unit(db, calc, "C-1", 85.0)
    bare = _line(db, calc)
    drawn = _line(db, calc)
    _assign(db, drawn, "block", c1)
    _place(db, calc, drawn, 85.05)
    db.commit()

    rows = {r["id"]: r for r in plan_view(db, calc)}

    assert rows[str(bare.id)]["location_mode"] == "needs_location"
    assert (
        rows[str(drawn.id)]["location_mode"] == "places"
    )  # a drawn place is the more exact answer
    assert rows[str(drawn.id)]["location_units"] == ["C-1"]


def test_the_plan_check_does_not_ask_for_a_place_when_blocks_were_chosen(db, calc):
    c1 = _unit(db, calc, "C-1", 85.0)
    line = _line(db, calc)
    _assign(db, line, "block", c1)
    db.commit()

    codes = [i["code"] for i in compute_health(db, calc)["items"][0]["issues"]]

    assert "NO_LOCATION" not in codes
