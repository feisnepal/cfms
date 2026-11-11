"""Protection Working Circle P0 — reconcile carries `working_circle`.

`forest_blocks.working_circle` (migration 074) must survive into the
`result_data` unit dicts that analysis and the OP builder read, and it is
IDENTITY — always taken fresh from the DB row, never preserved from a stale
JSONB snapshot.
"""
from __future__ import annotations

import uuid

from shapely.geometry import box
from shapely.wkt import dumps as wkt_dumps

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.services.block_reconcile_service import (
    _IDENTITY_KEYS,
    reconcile_blocks_from_db,
    reconcile_compartments_from_db,
)


def _user(db):
    u = User(
        email=f"wc-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x", full_name="WC",
    )
    db.add(u)
    db.flush()
    return u


def _calc(db, user, stale_units_key="blocks"):
    calc = Calculation(
        id=uuid.uuid4(), user_id=user.id,
        forest_name=f"WC CF {uuid.uuid4().hex[:6]}",
        boundary_geom=wkt_dumps(box(0, 0, 10, 10)),
        status=CalculationStatus.PROCESSING, is_draft=True,
        # stale snapshot deliberately says every unit is 'protection' — reconcile
        # must overwrite it from the DB, not keep it.
        result_data={
            stale_units_key: [
                {"block_id": "stale", "block_name": "stale", "working_circle": "protection"}
            ],
        },
    )
    db.add(calc)
    db.flush()
    return calc


def test_working_circle_is_an_identity_key():
    assert "working_circle" in _IDENTITY_KEYS


def test_reconcile_blocks_carries_working_circle(db):
    user = _user(db)
    calc = _calc(db, user)
    kinds = ["production", "protection", "production"]
    for i, wc in enumerate(kinds, start=1):
        db.add(ForestBlock(
            id=uuid.uuid4(), calculation_id=calc.id, name=f"B{i}", block_name=f"B{i}",
            geometry=wkt_dumps(box(i, 0, i + 1, 2)), area_hectares=10.0 * i, index=i,
            division_level=1, working_circle=wc,
        ))
    db.commit()

    changed = reconcile_blocks_from_db(db, calc)
    assert changed is True

    got = {b["block_name"]: b["working_circle"] for b in calc.result_data["blocks"]}
    assert got == {"B1": "production", "B2": "protection", "B3": "production"}


def test_reconcile_compartments_carries_working_circle_and_keeps_protection_unit(db):
    user = _user(db)
    calc = _calc(db, user, stale_units_key="compartments")
    parent = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="B1",
        geometry=wkt_dumps(box(0, 0, 6, 4)), area_hectares=100.0, index=0,
        division_level=1, is_compartment=False,
    )
    db.add(parent)
    db.flush()
    for i, wc in enumerate(["production", "production", "protection"], start=1):
        db.add(ForestBlock(
            id=uuid.uuid4(), calculation_id=calc.id, name=f"C{i}", block_name=f"C{i}",
            geometry=wkt_dumps(box(i - 1, 0, i, 2)), area_hectares=10.0, index=i,
            division_level=1, is_compartment=True, parent_block_id=parent.id,
            working_circle=wc,
        ))
    db.commit()

    changed = reconcile_compartments_from_db(db, calc)
    assert changed is True

    comps = calc.result_data["compartments"]
    got = {c["block_name"]: c["working_circle"] for c in comps}
    assert got == {"C1": "production", "C2": "production", "C3": "protection"}
    # the protection unit is still a compartment analysis will run over
    assert any(c["working_circle"] == "protection" for c in comps)
    assert calc.result_data["total_compartments"] == 3


def test_stale_working_circle_is_overwritten_not_preserved(db):
    """A DB row flips to production; the stale JSONB said protection — reconcile wins."""
    user = _user(db)
    calc = _calc(db, user)
    row = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="B1", block_name="B1",
        geometry=wkt_dumps(box(0, 0, 2, 2)), area_hectares=10.0, index=1,
        division_level=1, working_circle="protection",
    )
    db.add(row)
    db.commit()
    reconcile_blocks_from_db(db, calc)
    assert calc.result_data["blocks"][0]["working_circle"] == "protection"

    row.working_circle = "production"
    db.commit()
    reconcile_blocks_from_db(db, calc)
    assert calc.result_data["blocks"][0]["working_circle"] == "production"
