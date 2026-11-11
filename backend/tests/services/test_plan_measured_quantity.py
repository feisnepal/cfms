"""What a line's drawn places measure (YEARLY_ACTIVITIES plan P6, D4): hectares of areas, kilometres of lines, a count
of places — reported beside the numbers so the table can offer to adopt it. Never written by itself."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString, Point, box

from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.models.yearly_activities import (
    ActivityDrawnFeature,
    PotentialActivity,
    ProposedYearlyActivity,
)
from app.services.yearly_plan_service import plan_view


@pytest.fixture()
def calc(db):
    user = User(
        email=f"meas{uuid.uuid4().hex[:8]}@test.com",
        full_name="Measure Tester",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(user)
    db.flush()
    c = Calculation(
        id=str(uuid.uuid4()), user_id=user.id, uploaded_filename="m.csv", is_draft=False
    )
    db.add(c)
    db.commit()
    return c


def _line(db, calc, unit):
    master = PotentialActivity(
        progarms="P",
        activities=f"A-{uuid.uuid4().hex[:4]}",
        display_order=0,
        requires_map=True,
        unit=unit,
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


def _feature(db, calc, line, kind, geometry, deleted=False):
    db.add(
        ActivityDrawnFeature(
            proposed_activity_id=line.id,
            calculation_id=calc.id,
            feature_type=kind,
            geometry=from_shape(geometry, srid=4326),
            properties={"name": "f"},
            deleted_at=datetime.now(timezone.utc) if deleted else None,
        )
    )


def _measured(db, calc):
    return {r["id"]: r["measured_quantity"] for r in plan_view(db, calc)}


def test_hectares_of_the_drawn_areas(db, calc):
    line = _line(db, calc, "हेक्टर")
    _feature(db, calc, line, "polygon", box(85.0, 27.0, 85.001, 27.001))  # ≈ 1 ha
    db.commit()

    value = _measured(db, calc)[str(line.id)]

    assert 0.9 < value < 1.3


def test_kilometres_of_the_drawn_lines(db, calc):
    line = _line(db, calc, "कि.मि.")
    _feature(
        db, calc, line, "line", LineString([(85.0, 27.0), (85.01, 27.0)])
    )  # ≈ 1 km
    db.commit()

    value = _measured(db, calc)[str(line.id)]

    assert 0.95 < value < 1.05


def test_a_count_of_places_and_a_deleted_place_is_not_counted(db, calc):
    line = _line(db, calc, "वटा")
    _feature(db, calc, line, "point", Point(85.0, 27.0))
    _feature(db, calc, line, "point", Point(85.1, 27.0))
    _feature(db, calc, line, "point", Point(85.2, 27.0), deleted=True)
    db.commit()

    assert _measured(db, calc)[str(line.id)] == 2.0


def test_nothing_is_measured_for_a_unit_that_cannot_be_or_for_a_line_without_places(
    db, calc
):
    bundles = _line(db, calc, "आ.अ.")  # "as needed": has to be asked of the person
    _feature(db, calc, bundles, "point", Point(85.0, 27.0))
    bare = _line(db, calc, "हेक्टर")  # no place drawn
    db.commit()

    got = _measured(db, calc)

    assert got[str(bundles.id)] is None
    assert got[str(bare.id)] is None


def test_an_area_unit_with_only_a_point_drawn_measures_nothing_not_zero(db, calc):
    line = _line(db, calc, "हेक्टर")
    _feature(db, calc, line, "point", Point(85.0, 27.0))
    db.commit()

    assert _measured(db, calc)[str(line.id)] is None
