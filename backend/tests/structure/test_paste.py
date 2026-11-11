"""Paste into a unit layer (D12, FS-4a.11) -
``app.services.forest_units.operations.paste``.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import box, mapping

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services.forest_units.operations.paste import (
    ERR_LOCKED,
    ERR_NO_USABLE_GEOMETRY,
    ERR_NOT_A_BLOCK,
    ERR_NOT_A_COMPARTMENT,
    ERR_PARENT_NOT_FOUND,
    ERR_SAME_PLACE,
    ERR_STREAM_EMPTY_REQUIRED,
    apply_paste,
    compute_paste,
    preview_paste,
)
from app.services.geometry_edit_service import area_sqm


def _make_calc(db, boundary=None):
    user = User(
        email=f"paste{uuid.uuid4().hex[:8]}@test.com",
        full_name="Paste Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="paste.csv",
        is_draft=False,
        boundary_geom=from_shape(boundary, srid=4326) if boundary is not None else None,
    )
    db.add(calc)
    db.flush()
    return calc


def _row(db, calc, geom, *, name="B1", is_compartment=False, division_level=1, parent=None):
    row = ForestBlock(
        calculation_id=calc.id,
        name=name,
        block_name=name,
        geometry=from_shape(geom, srid=4326),
        area_hectares=round(area_sqm(geom) / 10_000.0, 4),
        area_sqm=round(area_sqm(geom), 2),
        index=0,
        is_compartment=is_compartment,
        division_level=division_level,
        parent_block_id=parent.id if parent is not None else None,
    )
    db.add(row)
    db.flush()
    return row


def _children_of(db, parent_id):
    return db.query(ForestBlock).filter(ForestBlock.parent_block_id == parent_id).all()


BOUNDARY = box(83.0, 27.0, 83.10, 27.10)


def _children_cover_parent(db, parent):
    """Owner rule (2026-10-03): a divided unit's children always tile it -- no gap, no overlap."""
    from shapely.ops import unary_union

    kids = [to_shape(k.geometry) for k in _children_of(db, parent.id)]
    union = unary_union(kids)
    parent_geom = to_shape(parent.geometry)
    assert area_sqm(parent_geom.difference(union)) < 1.0, "a gap is left inside the parent"
    assert area_sqm(union.difference(parent_geom)) < 1.0, "a child sticks out of the parent"
    assert sum(area_sqm(k) for k in kids) - area_sqm(union) < 1.0, "children overlap"


def test_sub_level_paste_under_a_block_creates_a_child(db):
    calc = _make_calc(db, BOUNDARY)
    parent = _row(db, calc, box(83.0, 27.0, 83.05, 27.10), name="Block-1")
    paste_geom = box(83.005, 27.02, 83.02, 27.08)

    result = apply_paste(db, calc, "sub_blocks", str(parent.id), [mapping(paste_geom)])

    assert result["skipped"] == 0
    assert len(result["new_pieces"]) == 1
    # The pasted piece covers only part of the block; the rest becomes a remainder sub-unit so the
    # children still tile the parent (no gap).
    assert len(result["remainder_added"]) == 1
    kids = _children_of(db, parent.id)
    assert len(kids) == 2
    pasted = [k for k in kids if to_shape(k.geometry).equals(paste_geom)]
    assert len(pasted) == 1
    assert pasted[0].is_compartment is False
    assert pasted[0].division_level == 2
    _children_cover_parent(db, parent)


def test_sub_level_paste_inherits_parent_identity_columns(db):
    calc = _make_calc(db, BOUNDARY)
    parent = _row(db, calc, box(83.0, 27.0, 83.05, 27.10), name="Block-1")
    parent.working_circle = "protection"
    db.flush()
    paste_geom = box(83.005, 27.02, 83.02, 27.08)

    apply_paste(db, calc, "sub_blocks", str(parent.id), [mapping(paste_geom)])

    kid = _children_of(db, parent.id)[0]
    assert kid.working_circle == "protection"  # child_inherit_kwargs(parent)


def test_root_level_paste_with_no_existing_units(db):
    calc = _make_calc(db, BOUNDARY)
    paste_geom = box(83.01, 27.01, 83.04, 27.09)

    result = apply_paste(db, calc, "blocks", None, [mapping(paste_geom)])

    assert len(result["new_pieces"]) == 1
    top_level = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id, ForestBlock.parent_block_id.is_(None)
    ).all()
    assert len(top_level) == 1
    assert top_level[0].division_level == 1
    assert top_level[0].is_compartment is False


def test_paste_takes_ground_from_an_overlapping_sibling(db):
    calc = _make_calc(db, BOUNDARY)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10), name="Block-1")
    sib = _row(
        db, calc, box(83.0, 27.0, 83.06, 27.10),
        name="Block-1-SB1", division_level=2, parent=parent,
    )
    # Overlaps the eastern part of `sib`.
    paste_geom = box(83.04, 27.0, 83.08, 27.10)

    result = apply_paste(db, calc, "sub_blocks", str(parent.id), [mapping(paste_geom)])

    assert result["absorbed"] == []
    assert len(result["trimmed"]) == 1
    db.refresh(sib)
    new_sib_geom = to_shape(sib.geometry)
    # `sib` shrank -- it no longer reaches the pasted shape's territory.
    assert new_sib_geom.bounds[2] <= 83.04 + 1e-9
    assert area_sqm(new_sib_geom) < area_sqm(box(83.0, 27.0, 83.06, 27.10))
    kids = _children_of(db, parent.id)
    assert len(kids) == 3  # sib (trimmed) + the new pasted piece + a remainder completing the parent
    _children_cover_parent(db, parent)


def test_paste_absorbs_a_sibling_trimmed_below_the_sliver_floor(db):
    calc = _make_calc(db, BOUNDARY)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10), name="Block-1")
    sib = _row(
        db, calc, box(83.0, 27.0, 83.06, 27.10),
        name="Block-1-SB1", division_level=2, parent=parent,
    )
    # Overlaps ALMOST the whole sibling -- a sliver under the 1 ha floor
    # would be left behind if not absorbed.
    paste_geom = box(83.000001, 27.0, 83.08, 27.10)

    result = apply_paste(db, calc, "sub_blocks", str(parent.id), [mapping(paste_geom)])

    assert result["trimmed"] == []
    assert len(result["absorbed"]) == 1
    assert db.query(ForestBlock).filter(ForestBlock.id == sib.id).first() is None
    kids = _children_of(db, parent.id)
    # the pasted piece (grown to cover the absorbed sliver too) + a remainder completing the parent
    assert len(kids) == 2
    _children_cover_parent(db, parent)


def test_grandchildren_of_an_absorbed_sibling_are_cascade_removed(db):
    """D13, via FS-4a.9's passive_deletes=True: a sibling fully absorbed by
    the paste takes its own children with it."""
    calc = _make_calc(db, BOUNDARY)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10), name="Block-1")
    sib = _row(
        db, calc, box(83.0, 27.0, 83.06, 27.10),
        name="Block-1-SB1", division_level=2, parent=parent,
    )
    grandchild = _row(
        db, calc, box(83.01, 27.02, 83.02, 27.08),
        name="Block-1-SB1-SB1", division_level=3, parent=sib,
    )
    paste_geom = box(83.000001, 27.0, 83.08, 27.10)

    apply_paste(db, calc, "sub_blocks", str(parent.id), [mapping(paste_geom)])

    assert db.query(ForestBlock).filter(ForestBlock.id == sib.id).first() is None
    assert db.query(ForestBlock).filter(ForestBlock.id == grandchild.id).first() is None


def test_same_place_paste_is_refused(db):
    calc = _make_calc(db, BOUNDARY)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10), name="Block-1")
    sib_geom = box(83.0, 27.0, 83.05, 27.10)
    _row(db, calc, sib_geom, name="Block-1-SB1", division_level=2, parent=parent)

    with pytest.raises(ValueError, match=ERR_SAME_PLACE.split(":")[0]):
        compute_paste(db, calc, "sub_blocks", str(parent.id), [mapping(sib_geom)])


def test_cross_stream_paste_refused_when_the_other_branch_has_rows(db):
    calc = _make_calc(db, BOUNDARY)
    _row(db, calc, box(83.0, 27.0, 83.10, 27.10), name="Block-1", is_compartment=False)

    with pytest.raises(ValueError, match=ERR_STREAM_EMPTY_REQUIRED.split(":")[0]):
        compute_paste(db, calc, "compartments", None, [mapping(box(83.01, 27.01, 83.04, 27.09))])


def test_cross_stream_paste_allowed_when_the_other_branch_is_empty(db):
    calc = _make_calc(db, BOUNDARY)
    # Nothing exists yet -- either branch's first paste is allowed.
    result = apply_paste(
        db, calc, "compartments", None, [mapping(box(83.01, 27.01, 83.04, 27.09))]
    )
    assert len(result["new_pieces"]) == 1
    row = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).first()
    assert row.is_compartment is True


def test_sub_blocks_under_a_compartment_parent_refused(db):
    calc = _make_calc(db, BOUNDARY)
    parent = _row(
        db, calc, box(83.0, 27.0, 83.05, 27.10), name="C1", is_compartment=True
    )
    with pytest.raises(ValueError, match=ERR_NOT_A_BLOCK.split(":")[0]):
        compute_paste(db, calc, "sub_blocks", str(parent.id), [mapping(box(83.005, 27.02, 83.02, 27.08))])


def test_sub_compartments_under_a_block_parent_refused(db):
    calc = _make_calc(db, BOUNDARY)
    parent = _row(db, calc, box(83.0, 27.0, 83.05, 27.10), name="Block-1")
    with pytest.raises(ValueError, match=ERR_NOT_A_COMPARTMENT.split(":")[0]):
        compute_paste(db, calc, "sub_compartments", str(parent.id), [mapping(box(83.005, 27.02, 83.02, 27.08))])


def test_locked_parent_refused(db):
    calc = _make_calc(db, BOUNDARY)
    parent = _row(db, calc, box(83.0, 27.0, 83.05, 27.10), name="Block-1")
    parent.is_locked = True
    db.flush()
    with pytest.raises(ValueError, match=ERR_LOCKED.split(":")[0]):
        compute_paste(db, calc, "sub_blocks", str(parent.id), [mapping(box(83.005, 27.02, 83.02, 27.08))])


def test_missing_parent_refused(db):
    calc = _make_calc(db, BOUNDARY)
    with pytest.raises(ValueError, match=ERR_PARENT_NOT_FOUND.split(":")[0]):
        compute_paste(db, calc, "sub_blocks", str(uuid.uuid4()), [mapping(box(83.005, 27.02, 83.02, 27.08))])


def test_no_usable_geometry_refused(db):
    calc = _make_calc(db, BOUNDARY)
    parent = _row(db, calc, box(83.0, 27.0, 83.05, 27.10), name="Block-1")
    # Entirely outside the parent shell.
    with pytest.raises(ValueError, match=ERR_NO_USABLE_GEOMETRY.split(":")[0]):
        compute_paste(db, calc, "sub_blocks", str(parent.id), [mapping(box(90.0, 30.0, 90.01, 30.01))])


def test_preview_does_not_persist(db):
    calc = _make_calc(db, BOUNDARY)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10), name="Block-1")
    sib = _row(
        db, calc, box(83.0, 27.0, 83.06, 27.10),
        name="Block-1-SB1", division_level=2, parent=parent,
    )
    paste_geom = box(83.04, 27.0, 83.08, 27.10)

    result = preview_paste(db, calc, "sub_blocks", str(parent.id), [mapping(paste_geom)])

    assert len(result["new_pieces"]) == 1
    assert len(result["trimmed"]) == 1
    # Nothing actually changed on disk.
    db.refresh(sib)
    assert to_shape(sib.geometry).equals(box(83.0, 27.0, 83.06, 27.10))
    assert _children_of(db, parent.id) == [sib]


def test_preview_and_apply_produce_the_same_pieces(db):
    calc = _make_calc(db, BOUNDARY)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10), name="Block-1")
    _row(
        db, calc, box(83.0, 27.0, 83.06, 27.10),
        name="Block-1-SB1", division_level=2, parent=parent,
    )
    paste_geom = box(83.04, 27.0, 83.08, 27.10)

    preview = preview_paste(db, calc, "sub_blocks", str(parent.id), [mapping(paste_geom)])
    applied = apply_paste(db, calc, "sub_blocks", str(parent.id), [mapping(paste_geom)])

    assert preview["new_pieces"][0]["area_hectares"] == applied["new_pieces"][0]["area_hectares"]
    assert preview["trimmed"][0]["area_hectares"] == applied["trimmed"][0]["area_hectares"]
