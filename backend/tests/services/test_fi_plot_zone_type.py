"""field_inventory_service.assign_plot_zone_types -- protected-area stratification.

Design item #1: a sample plot is tagged `protected` when it falls inside a
`category='protected'` sub-area of the parent forest, else `productive`. When
the forest has no protected sub-areas nothing is stratified and `zone_type`
stays NULL (consumers read NULL as productive).
"""
from __future__ import annotations

import uuid

import pytest

from app.models.calculation import Calculation
from app.models.field_inventory import FieldInventoryCalculation, FieldInventorySamplePlot
from app.models.user import User
from app.services.field_inventory_service import assign_plot_zone_types


@pytest.fixture()
def owner(db):
    user = User(
        email=f"fizone-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="FI Zone Fixture",
    )
    db.add(user)
    db.flush()
    return user


def _square(x0, y0, x1, y1):
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def _parent_calc(db, owner, sub_areas):
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        uploaded_filename="fixture.csv",
        is_draft=False,
        structure_locked=False,
        result_data={"sub_areas": sub_areas},
    )
    db.add(calc)
    db.flush()
    return calc


def _fi_with_plots(db, owner, parent_calc, points):
    fi = FieldInventoryCalculation(
        user_id=owner.id,
        uploaded_filename="fi.csv",
        status="processing",
        calculation_id=parent_calc.id if parent_calc else None,
    )
    db.add(fi)
    db.flush()
    plots = []
    for i, (lon, lat) in enumerate(points, start=1):
        p = FieldInventorySamplePlot(
            field_inventory_calculation_id=fi.id,
            block_name="Block-1",
            sample_plot_number=i,
            location=f"SRID=4326;POINT({lon} {lat})",
        )
        db.add(p)
        plots.append(p)
    db.flush()
    return fi, plots


def test_tags_plots_inside_a_protected_sub_area(db, owner):
    protected = _square(84.02, 28.02, 84.05, 28.05)
    parent = _parent_calc(db, owner, [
        {"name": "Sacred grove", "category": "protected", "geometry": protected},
    ])
    fi, (inside, outside) = _fi_with_plots(
        db, owner, parent,
        [(84.03, 28.03), (84.10, 28.10)],  # inside protected, well outside
    )

    assign_plot_zone_types(db, fi.id, fi)

    db.refresh(inside)
    db.refresh(outside)
    assert inside.zone_type == "protected"
    assert outside.zone_type == "productive"


def test_no_protected_sub_areas_leaves_zone_type_null(db, owner):
    parent = _parent_calc(db, owner, [
        {"name": "Plantation", "category": "plantation", "geometry": _square(84.0, 28.0, 84.1, 28.1)},
    ])
    fi, (p1, p2) = _fi_with_plots(db, owner, parent, [(84.03, 28.03), (84.2, 28.2)])

    assign_plot_zone_types(db, fi.id, fi)

    db.refresh(p1)
    db.refresh(p2)
    assert p1.zone_type is None
    assert p2.zone_type is None


def test_excluded_protected_sub_area_is_ignored(db, owner):
    parent = _parent_calc(db, owner, [
        {
            "name": "Excluded patch",
            "category": "protected",
            "isExcluded": True,
            "geometry": _square(84.0, 28.0, 84.1, 28.1),
        },
    ])
    fi, (p1,) = _fi_with_plots(db, owner, parent, [(84.05, 28.05)])

    assign_plot_zone_types(db, fi.id, fi)

    db.refresh(p1)
    assert p1.zone_type is None  # nothing to stratify against


# `test_no_parent_calculation_is_a_safe_noop` was removed on 2026-09-21: a field inventory can no longer exist
# without a forest (owner's rule, migration 092 -- `calculation_id` is NOT NULL), so that situation cannot occur.
