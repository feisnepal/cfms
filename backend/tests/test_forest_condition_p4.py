"""Workspace layer styling P4.5 — `forest_condition` on block features.

`_forest_condition_by_block_name` reads the field-inventory block summaries for
a calculation so the workspace map can offer a one-click "Colour by condition"
categorized renderer. No field inventory → empty map (blocks read grey).
"""
from __future__ import annotations

import uuid

from shapely.geometry import box
from shapely.wkt import dumps as wkt_dumps

from app.api.forests import _forest_condition_by_block_name
from app.models.calculation import Calculation, CalculationStatus
from app.models.field_inventory import FieldInventoryCalculation, FieldInventoryBlockSummary
from app.models.user import User


def _user(db):
    u = User(email=f"cond-{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", full_name="Cond")
    db.add(u)
    db.flush()
    return u


def _calc(db, user):
    calc = Calculation(
        id=uuid.uuid4(), user_id=user.id,
        forest_name=f"Cond CF {uuid.uuid4().hex[:6]}",
        boundary_geom=wkt_dumps(box(0, 0, 10, 10)),
        status=CalculationStatus.PROCESSING, is_draft=True,
    )
    db.add(calc)
    db.flush()
    return calc


def test_no_field_inventory_yields_empty_map(db):
    calc = _calc(db, _user(db))
    assert _forest_condition_by_block_name(db, calc.id) == {}


def test_condition_map_is_keyed_by_block_name(db):
    user = _user(db)
    calc = _calc(db, user)
    fi = FieldInventoryCalculation(
        user_id=user.id, calculation_id=calc.id,
        uploaded_filename="fi.csv", status="completed",
    )
    db.add(fi)
    db.flush()
    for name, cond in [("B1", "Good"), ("B2", "Weak"), ("B3", None)]:
        db.add(FieldInventoryBlockSummary(
            field_inventory_calculation_id=fi.id, block_name=name,
            total_sample_plots=3, forest_condition=cond,
        ))
    db.commit()

    got = _forest_condition_by_block_name(db, calc.id)
    # B3's NULL condition is filtered out
    assert got == {"B1": "Good", "B2": "Weak"}
