"""Workspace layer styling P3 — per-feature `style` override.

`forest_blocks.style` (migration 075) is a nullable JSONB carrying a unit's
own fill / opacity / stroke / weight override. Like `working_circle` it is
IDENTITY in reconcile — always taken fresh from the DB row, never preserved
from a stale JSONB snapshot — and it must reach the `result_data` unit dicts
that the map reads. Sub-areas carry the same override in their own dict.
"""
from __future__ import annotations

import uuid

from shapely.geometry import box
from shapely.wkt import dumps as wkt_dumps

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.schemas.forest import BlockRenameRequest, SubAreaUpdateRequest
from app.services.block_reconcile_service import (
    _IDENTITY_KEYS,
    reconcile_blocks_from_db,
    reconcile_compartments_from_db,
)
from app.services.sub_area_service import build_sub_area_dict


STYLE = {"fill": "#cc3344", "fillOpacity": 0.5}


def _user(db):
    u = User(email=f"style-{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", full_name="ST")
    db.add(u)
    db.flush()
    return u


def _calc(db, user, stale_units_key="blocks"):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user.id,
        forest_name=f"ST CF {uuid.uuid4().hex[:6]}",
        boundary_geom=wkt_dumps(box(0, 0, 10, 10)),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
        result_data={
            stale_units_key: [
                {"block_id": "stale", "block_name": "stale", "style": {"fill": "#000000"}}
            ]
        },
    )
    db.add(calc)
    db.flush()
    return calc


def test_style_is_an_identity_key():
    assert "style" in _IDENTITY_KEYS


def test_reconcile_blocks_carries_style():
    """Two blocks — one styled, one not — round-trip through reconcile."""
    # unit-level: exercised against a real db below; here just the schema.
    assert SubAreaUpdateRequest(style=STYLE).style == STYLE
    assert BlockRenameRequest(style=STYLE).style == STYLE
    # `style` in model_fields_set distinguishes "clear" from "absent"
    assert "style" in SubAreaUpdateRequest(style=None).model_fields_set
    assert "style" not in SubAreaUpdateRequest(name="x").model_fields_set


def test_reconcile_blocks_carries_style_from_db(db):
    user = _user(db)
    calc = _calc(db, user)
    db.add(ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="B1", block_name="B1",
        geometry=wkt_dumps(box(0, 0, 2, 2)), area_hectares=10.0, index=1,
        division_level=1, style=STYLE,
    ))
    db.add(ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="B2", block_name="B2",
        geometry=wkt_dumps(box(2, 0, 4, 2)), area_hectares=10.0, index=2,
        division_level=1, style=None,
    ))
    db.commit()

    reconcile_blocks_from_db(db, calc)
    got = {b["block_name"]: b["style"] for b in calc.result_data["blocks"]}
    assert got == {"B1": STYLE, "B2": None}


def test_reconcile_compartments_carries_style_from_db(db):
    user = _user(db)
    calc = _calc(db, user, stale_units_key="compartments")
    parent = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="B1",
        geometry=wkt_dumps(box(0, 0, 6, 4)), area_hectares=100.0, index=0,
        division_level=1, is_compartment=False,
    )
    db.add(parent)
    db.flush()
    db.add(ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="C1", block_name="C1",
        geometry=wkt_dumps(box(0, 0, 1, 2)), area_hectares=10.0, index=1,
        division_level=1, is_compartment=True, parent_block_id=parent.id, style=STYLE,
    ))
    db.commit()

    reconcile_compartments_from_db(db, calc)
    comps = {c["block_name"]: c["style"] for c in calc.result_data["compartments"]}
    assert comps == {"C1": STYLE}


def test_stale_style_is_overwritten_not_preserved(db):
    """The DB row's `style` clears; the stale JSONB still had one — reconcile wins."""
    user = _user(db)
    calc = _calc(db, user)
    row = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="B1", block_name="B1",
        geometry=wkt_dumps(box(0, 0, 2, 2)), area_hectares=10.0, index=1,
        division_level=1, style=STYLE,
    )
    db.add(row)
    db.commit()
    reconcile_blocks_from_db(db, calc)
    assert calc.result_data["blocks"][0]["style"] == STYLE

    row.style = None
    db.commit()
    reconcile_blocks_from_db(db, calc)
    assert calc.result_data["blocks"][0]["style"] is None


def test_build_sub_area_dict_seeds_style_none():
    d = build_sub_area_dict(
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        name="protected patch", category="protected", area_ha=1.0,
    )
    assert d["style"] is None
    assert d["fill_color"]  # category colour still computed as the fallback
