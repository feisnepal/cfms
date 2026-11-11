"""Promote a protected sub-area to a P-N protection unit, and demote it back.

PROTECTION_WORKING_CIRCLE_PLAN.md P3.
"""
from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import box, mapping

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.services.geometry_edit_service import area_sqm
from app.services.protection_unit_service import (
    demote_unit_to_subarea,
    promote_subarea_to_unit,
)


def _seed(db, *, locked=False):
    user = User(email=f"pu-{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", full_name="PU")
    db.add(user)
    db.flush()

    block_geom = box(84.00, 28.00, 84.02, 28.02)          # ~2 km square
    sa_geom = box(84.004, 28.004, 84.010, 28.016)         # a slab wholly inside
    sub_area = {
        "id": str(uuid.uuid4()),
        "name": "Sacred grove",
        "category": "protected",
        "geometry": mapping(sa_geom),
        "area_hectares": round(area_sqm(sa_geom) / 10000.0, 4),
    }
    calc = Calculation(
        id=uuid.uuid4(), user_id=user.id, forest_name="PU CF",
        boundary_geom=from_shape(block_geom, srid=4326),
        status=CalculationStatus.PROCESSING, is_draft=True,
        structure_locked=locked,
        result_data={"blocks": [{"block_id": "b1", "block_name": "B1",
                                 "area_hectares": round(area_sqm(block_geom) / 10000.0, 4),
                                 "geometry": mapping(block_geom)}],
                     "sub_areas": [sub_area]},
    )
    db.add(calc)
    db.flush()
    block = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="B1", block_name="B1",
        geometry=from_shape(block_geom, srid=4326),
        area_hectares=round(area_sqm(block_geom) / 10000.0, 4),
        area_sqm=round(area_sqm(block_geom), 2), index=0, division_level=1,
    )
    db.add(block)
    db.commit()
    return calc, block, sub_area, area_sqm(block_geom), area_sqm(sa_geom)


def test_promote_then_demote_round_trips(db):
    calc, block, sub_area, gross, sa_area = _seed(db)

    res = promote_subarea_to_unit(db, calc, sub_area["id"])
    db.commit()

    # a P-1 protection unit exists, geometry = the sub-area
    unit = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id, ForestBlock.working_circle == "protection"
    ).one()
    assert unit.name == "P-1" and unit.block_name == "P-1"
    assert area_sqm(to_shape(unit.geometry)) == pytest.approx(sa_area, rel=0.02)

    # the block was carved: area ~= gross - sub-area
    db.refresh(block)
    assert area_sqm(to_shape(block.geometry)) == pytest.approx(gross - sa_area, rel=0.03)

    # the overlay is gone; reconciled result_data carries the unit
    assert calc.result_data["sub_areas"] == []
    wc = {b["block_name"]: b.get("working_circle") for b in calc.result_data["blocks"]}
    assert wc.get("P-1") == "protection"
    assert str(unit.id) in calc.result_data["protection_unit_snapshots"]

    # ── demote ──
    demote_unit_to_subarea(db, calc, str(unit.id))
    db.commit()

    assert db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id, ForestBlock.working_circle == "protection"
    ).count() == 0
    db.refresh(block)
    assert area_sqm(to_shape(block.geometry)) == pytest.approx(gross, rel=0.01)
    cats = [sa["category"] for sa in calc.result_data["sub_areas"]]
    assert cats == ["protected"]
    assert str(unit.id) not in calc.result_data.get("protection_unit_snapshots", {})


def test_promote_refuses_non_protected(db):
    calc, block, sub_area, *_ = _seed(db)
    calc.result_data["sub_areas"][0]["category"] = "plantation"
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(calc, "result_data")
    db.commit()
    with pytest.raises(ValueError, match="NOT_PROTECTED"):
        promote_subarea_to_unit(db, calc, sub_area["id"])


def test_promote_refuses_when_structure_locked(db):
    calc, block, sub_area, *_ = _seed(db, locked=True)
    with pytest.raises(ValueError, match="STRUCTURE_LOCKED"):
        promote_subarea_to_unit(db, calc, sub_area["id"])


def test_next_protection_index_counts_per_calc(db):
    calc, block, sub_area, *_ = _seed(db)
    promote_subarea_to_unit(db, calc, sub_area["id"])
    db.commit()
    from app.services.protection_unit_service import next_protection_index
    assert next_protection_index(db, calc.id) == 2


def test_promote_from_a_sub_block_nests_the_unit_under_the_same_parent(db):
    """FS-4a.14: before this fix, a promoted unit was ALWAYS created
    top-level (parent_block_id=None) even when the protected sub-area sat
    inside a SUB-block, producing an inconsistent (depth, ancestry) pair —
    a unit claiming depth 2 with no parent at all. The promoted unit must
    become a SIBLING of whatever it was carved out of: same parent, same
    depth, same branch."""
    user = User(email=f"pu-{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", full_name="PU")
    db.add(user)
    db.flush()

    block_geom = box(84.00, 28.00, 84.02, 28.02)
    sub_block_geom = box(84.00, 28.00, 84.01, 28.02)  # west half of the block
    sa_geom = box(84.002, 28.004, 84.006, 28.016)  # a slab wholly inside the sub-block
    sub_area = {
        "id": str(uuid.uuid4()),
        "name": "Sacred grove",
        "category": "protected",
        "geometry": mapping(sa_geom),
        "area_hectares": round(area_sqm(sa_geom) / 10000.0, 4),
    }
    calc = Calculation(
        id=uuid.uuid4(), user_id=user.id, forest_name="PU Sub-block CF",
        boundary_geom=from_shape(block_geom, srid=4326),
        status=CalculationStatus.PROCESSING, is_draft=True,
        result_data={"sub_areas": [sub_area]},
    )
    db.add(calc)
    db.flush()
    block = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="B1", block_name="B1",
        geometry=from_shape(block_geom, srid=4326),
        area_hectares=round(area_sqm(block_geom) / 10000.0, 4),
        area_sqm=round(area_sqm(block_geom), 2), index=0, division_level=1,
    )
    db.add(block)
    db.flush()
    sub_block = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="B1-SB1", block_name="B1-SB1",
        geometry=from_shape(sub_block_geom, srid=4326),
        area_hectares=round(area_sqm(sub_block_geom) / 10000.0, 4),
        area_sqm=round(area_sqm(sub_block_geom), 2), index=1, division_level=2,
        parent_block_id=block.id,
    )
    db.add(sub_block)
    db.commit()

    promote_subarea_to_unit(db, calc, sub_area["id"])
    db.commit()

    unit = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id, ForestBlock.working_circle == "protection"
    ).one()
    assert unit.name == "P-1"
    # A protection unit is a PEER of whatever it was carved from, at the
    # SAME hierarchical rank -- same parent, same depth -- not a further
    # subdivision of it (matches the pre-existing top-level behaviour:
    # promoting from a top-level block makes another top-level unit
    # alongside it, never a child of that block).
    assert unit.parent_block_id == sub_block.parent_block_id == block.id
    assert unit.division_level == sub_block.division_level == 2
    assert unit.is_compartment is False

    # Every unit whose geometry overlapped the sub-area is clipped, not just
    # the carved-from one -- the top-level block's own geometry still fully
    # covered the sub-block's territory (a parent-kept carve never hollows
    # the parent row out), so it shrinks too.
    db.refresh(sub_block)
    db.refresh(block)
    assert area_sqm(to_shape(sub_block.geometry)) < area_sqm(sub_block_geom)
    assert area_sqm(to_shape(block.geometry)) < area_sqm(block_geom)

    # Demote is the exact inverse regardless of the unit's depth/parent --
    # both clipped units (block and sub_block) are restored.
    demote_unit_to_subarea(db, calc, str(unit.id))
    db.commit()
    assert db.query(ForestBlock).filter(ForestBlock.id == unit.id).first() is None
    db.refresh(sub_block)
    db.refresh(block)
    assert area_sqm(to_shape(sub_block.geometry)) == pytest.approx(area_sqm(sub_block_geom), rel=0.01)
    assert area_sqm(to_shape(block.geometry)) == pytest.approx(area_sqm(block_geom), rel=0.01)


def test_promote_from_a_sub_compartment_carries_the_compartment_branch(db):
    """FS-4a.14: the same generalisation on the compartment branch -- a
    protected sub-area inside a sub-compartment promotes to a unit that is
    itself a compartment (is_compartment=True), sibling of the
    sub-compartment (same parent, same depth)."""
    user = User(email=f"pu-{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", full_name="PU")
    db.add(user)
    db.flush()

    comp_geom = box(84.00, 28.00, 84.02, 28.02)
    sub_comp_geom = box(84.00, 28.00, 84.01, 28.02)
    sa_geom = box(84.002, 28.004, 84.006, 28.016)
    sub_area = {
        "id": str(uuid.uuid4()),
        "name": "Sacred grove",
        "category": "protected",
        "geometry": mapping(sa_geom),
        "area_hectares": round(area_sqm(sa_geom) / 10000.0, 4),
    }
    calc = Calculation(
        id=uuid.uuid4(), user_id=user.id, forest_name="PU Sub-compartment CF",
        boundary_geom=from_shape(comp_geom, srid=4326),
        status=CalculationStatus.PROCESSING, is_draft=True,
        result_data={"sub_areas": [sub_area]},
    )
    db.add(calc)
    db.flush()
    comp = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="C1", block_name="C1",
        geometry=from_shape(comp_geom, srid=4326),
        area_hectares=round(area_sqm(comp_geom) / 10000.0, 4),
        area_sqm=round(area_sqm(comp_geom), 2), index=0, division_level=1,
        is_compartment=True,
    )
    db.add(comp)
    db.flush()
    sub_comp = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="C1-SC1", block_name="C1-SC1",
        geometry=from_shape(sub_comp_geom, srid=4326),
        area_hectares=round(area_sqm(sub_comp_geom) / 10000.0, 4),
        area_sqm=round(area_sqm(sub_comp_geom), 2), index=1, division_level=2,
        is_compartment=True, parent_block_id=comp.id,
    )
    db.add(sub_comp)
    db.commit()

    promote_subarea_to_unit(db, calc, sub_area["id"])
    db.commit()

    unit = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id, ForestBlock.working_circle == "protection"
    ).one()
    assert unit.is_compartment is True
    assert unit.parent_block_id == sub_comp.parent_block_id == comp.id
    assert unit.division_level == sub_comp.division_level == 2


def test_get_calculation_blocks_reports_working_circle(db):
    """The map's blocks layer must carry working_circle so it can style a
    protection unit distinctly (PROTECTION_WORKING_CIRCLE_PLAN.md P5-display)."""
    calc, block, sub_area, *_ = _seed(db)
    promote_subarea_to_unit(db, calc, sub_area["id"])
    db.commit()

    from app.api.forests import get_calculation_blocks

    owner = db.query(User).filter(User.id == calc.user_id).one()
    resp = get_calculation_blocks(calc.id, current_user=owner, db=db)

    circles = {b.name: b.working_circle for b in resp.blocks}
    assert circles["B1"] == "production"
    assert circles["P-1"] == "protection"
