"""A plan line names the sub-areas its drawn places fall in, derived from the geometry (owner, 2026-10-15)."""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape
from shapely.geometry import box, mapping

from app.models.calculation import Calculation
from app.models.user import User
from app.models.yearly_activities import ActivityDrawnFeature, PotentialActivity, ProposedYearlyActivity
from app.services import yearly_plan_service as plan


def _setup(db, map_kind, features, sub_areas):
    user = User(email=f"sal-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="Sub Area Links")
    db.add(user)
    db.flush()
    calc = Calculation(user_id=user.id, uploaded_filename="x.csv", forest_name="Links CF", result_data={"sub_areas": sub_areas})
    db.add(calc)
    db.flush()
    pa = PotentialActivity(progarms="P", activities="Activity", display_order=0, map_kind=map_kind, requires_map=True)
    db.add(pa)
    db.flush()
    line = ProposedYearlyActivity(calculation_id=calc.id, potential_activity_id=pa.id, default_quantity=1, default_yearly_budget=1)
    db.add(line)
    db.flush()
    for geom in features:
        db.add(
            ActivityDrawnFeature(
                proposed_activity_id=line.id,
                calculation_id=calc.id,
                feature_type="polygon",
                geometry=from_shape(geom, srid=4326),
            )
        )
    db.commit()
    return calc, line


def _sub(name, category, geom):
    return {"id": str(uuid.uuid4()), "name": name, "category": category, "geometry": mapping(geom)}


def test_a_place_inside_a_sub_area_names_it(db):
    nursery_area = _sub("Block A plantation", "plantation", box(85.0, 27.0, 85.01, 27.01))
    calc, line = _setup(db, "plantation", [box(85.002, 27.002, 85.004, 27.004)], [nursery_area])
    got = plan.plan_view(db, calc)[0]["sub_areas"]
    assert [s["name"] for s in got] == ["Block A plantation"]
    assert got[0]["id"] == nursery_area["id"] and got[0]["matches"] is True


def test_the_sub_area_of_the_kinds_category_comes_first(db):
    other = _sub("Pro-poor plot", "pro-poor", box(85.0, 27.0, 85.02, 27.02))
    right = _sub("Z plantation", "plantation", box(85.0, 27.0, 85.02, 27.02))
    calc, _ = _setup(db, "plantation", [box(85.002, 27.002, 85.004, 27.004)], [other, right])
    got = plan.plan_view(db, calc)[0]["sub_areas"]
    assert [s["name"] for s in got] == ["Z plantation", "Pro-poor plot"]
    assert [s["matches"] for s in got] == [True, False]


def test_a_kind_without_a_category_still_links_by_position(db):
    area = _sub("Some sub-area", "protected", box(85.0, 27.0, 85.02, 27.02))
    calc, _ = _setup(db, "nursery", [box(85.002, 27.002, 85.004, 27.004)], [area])
    got = plan.plan_view(db, calc)[0]["sub_areas"]
    assert [s["name"] for s in got] == ["Some sub-area"] and got[0]["matches"] is False


def test_a_place_outside_every_sub_area_has_none(db):
    area = _sub("Far away", "plantation", box(86.0, 28.0, 86.01, 28.01))
    calc, _ = _setup(db, "plantation", [box(85.002, 27.002, 85.004, 27.004)], [area])
    assert plan.plan_view(db, calc)[0]["sub_areas"] == []


def test_two_places_in_two_sub_areas_name_both_once(db):
    a = _sub("Sub 2", "plantation", box(85.0, 27.0, 85.01, 27.01))
    b = _sub("Sub 10", "plantation", box(85.1, 27.1, 85.11, 27.11))
    calc, _ = _setup(
        db, "plantation", [box(85.002, 27.002, 85.004, 27.004), box(85.102, 27.102, 85.104, 27.104), box(85.005, 27.005, 85.006, 27.006)], [b, a]
    )
    got = plan.plan_view(db, calc)[0]["sub_areas"]
    assert [s["name"] for s in got] == ["Sub 2", "Sub 10"]  # natural order, each once


def test_a_line_with_no_places_has_no_sub_areas(db):
    calc, _ = _setup(db, "plantation", [], [_sub("X", "plantation", box(85.0, 27.0, 85.01, 27.01))])
    assert plan.plan_view(db, calc)[0]["sub_areas"] == []
