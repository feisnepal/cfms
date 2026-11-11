"""Sub-unit redistribution across replacement pieces (D13, FS-4a.7) -
``app.services.forest_units.operations.reparent``.
"""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services.forest_units.operations.reparent import child_count, redistribute_children
from app.services.geometry_edit_service import area_sqm


def _make_calc(db):
    user = User(
        email=f"reparent{uuid.uuid4().hex[:8]}@test.com",
        full_name="Reparent Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="reparent.csv",
        is_draft=False,
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


# A parent 10x10 (degrees-scaled small, but consistent units throughout), cut into a
# left piece [0,5]x[0,10] and a right piece [5,10]x[0,10].
LEFT = box(83.0, 27.0, 83.05, 27.10)
RIGHT = box(83.05, 27.0, 83.10, 27.10)


def test_a_child_entirely_inside_one_piece_moves_across_unchanged(db):
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    # Sub-block entirely inside the LEFT piece.
    child_geom = box(83.005, 27.02, 83.02, 27.08)
    child = _row(db, calc, child_geom, name="B1-SB1", division_level=2, parent=parent)

    left_row = _row(db, calc, LEFT, name="B1-1")
    right_row = _row(db, calc, RIGHT, name="B1-2")

    created = redistribute_children(
        db, calc, parent.id, [(left_row, LEFT), (right_row, RIGHT)]
    )
    assert len(created) == 1
    new_kids = _children_of(db, left_row.id)
    assert len(new_kids) == 1
    assert new_kids[0].id != child.id  # a NEW row, old one untouched by this call
    assert to_shape(new_kids[0].geometry).equals(child_geom)
    assert _children_of(db, right_row.id) == []


def test_a_child_that_straddles_two_pieces_is_split(db):
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    # Straddles x=83.05 substantially on both sides.
    child_geom = box(83.03, 27.02, 83.07, 27.08)
    _row(db, calc, child_geom, name="B1-SB1", division_level=2, parent=parent)

    left_row = _row(db, calc, LEFT, name="B1-1")
    right_row = _row(db, calc, RIGHT, name="B1-2")

    created = redistribute_children(
        db, calc, parent.id, [(left_row, LEFT), (right_row, RIGHT)]
    )
    assert len(created) == 2
    left_kids = _children_of(db, left_row.id)
    right_kids = _children_of(db, right_row.id)
    assert len(left_kids) == 1 and len(right_kids) == 1
    # Each fragment is clipped to its piece, and together they reconstruct the child.
    total = area_sqm(to_shape(left_kids[0].geometry)) + area_sqm(to_shape(right_kids[0].geometry))
    assert abs(total - area_sqm(child_geom)) < 1.0  # within 1 sqm of the original


def test_a_sliver_overlap_is_absorbed_not_made_its_own_fragment(db):
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    # Almost entirely in the RIGHT piece; a hairline sliver (< 1 ha -- the
    # child spans 0.06 deg ~= 6.6 km in latitude, so the width poking across
    # x=83.05 must be a few metres, not a few tens of metres, to stay under
    # the 1 ha threshold) pokes across x=83.05 into the LEFT piece.
    child_geom = box(83.049995, 27.02, 83.08, 27.08)
    _row(db, calc, child_geom, name="B1-SB1", division_level=2, parent=parent)

    left_row = _row(db, calc, LEFT, name="B1-1")
    right_row = _row(db, calc, RIGHT, name="B1-2")

    created = redistribute_children(
        db, calc, parent.id, [(left_row, LEFT), (right_row, RIGHT)]
    )
    assert len(created) == 1  # the sliver did NOT spawn its own fragment
    assert _children_of(db, left_row.id) == []
    right_kids = _children_of(db, right_row.id)
    assert len(right_kids) == 1
    # The absorbed sliver's area is folded IN, not lost.
    assert area_sqm(to_shape(right_kids[0].geometry)) >= area_sqm(child_geom) - 1.0


def test_grandchildren_are_recursively_redistributed(db):
    """A1: a sub-block that itself has a sub-sub-block must not lose it when
    the sub-block is itself re-homed/split."""
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    sub = _row(
        db, calc, box(83.005, 27.02, 83.02, 27.08),
        name="B1-SB1", division_level=2, parent=parent,
    )
    sub_sub_geom = box(83.008, 27.03, 83.015, 27.06)
    _row(db, calc, sub_sub_geom, name="B1-SB1-SB1", division_level=3, parent=sub)

    left_row = _row(db, calc, LEFT, name="B1-1")
    right_row = _row(db, calc, RIGHT, name="B1-2")

    created = redistribute_children(
        db, calc, parent.id, [(left_row, LEFT), (right_row, RIGHT)]
    )
    # 1 new sub-block (moved unchanged into the left piece) + 1 new sub-sub-block.
    assert len(created) == 2
    new_sub = _children_of(db, left_row.id)
    assert len(new_sub) == 1
    new_sub_sub = _children_of(db, new_sub[0].id)
    assert len(new_sub_sub) == 1
    assert to_shape(new_sub_sub[0].geometry).equals(sub_sub_geom)


def test_no_children_is_a_cheap_noop(db):
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    left_row = _row(db, calc, LEFT, name="B1-1")
    right_row = _row(db, calc, RIGHT, name="B1-2")

    created = redistribute_children(
        db, calc, parent.id, [(left_row, LEFT), (right_row, RIGHT)]
    )
    assert created == []


def test_no_new_pieces_is_a_cheap_noop(db):
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    _row(db, calc, box(83.005, 27.02, 83.02, 27.08), name="B1-SB1", division_level=2, parent=parent)

    created = redistribute_children(db, calc, parent.id, [])
    assert created == []


# ---------------------------------------------------------------------------
# FS-4a.9 -- child_count() (the DELETE endpoints' confirm_children gate) and
# the passive_deletes=True cascade it relies on once confirmed.
# ---------------------------------------------------------------------------

def test_child_count_is_zero_for_a_leaf(db):
    calc = _make_calc(db)
    leaf = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    assert child_count(db, leaf.id) == 0


def test_child_count_counts_direct_children_only(db):
    """child_count is the DIRECT-children count (matching a 409's "here's
    what's immediately below you" message) -- a grandchild is not counted
    at this level, even though it still exists and will still be swept up
    by the real cascade once the caller confirms."""
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    child = _row(
        db, calc, box(83.005, 27.02, 83.02, 27.08),
        name="B1-SB1", division_level=2, parent=parent,
    )
    _row(
        db, calc, box(83.008, 27.03, 83.015, 27.06),
        name="B1-SB1-SB1", division_level=3, parent=child,
    )
    assert child_count(db, parent.id) == 1
    assert child_count(db, child.id) == 1


def test_passive_deletes_cascades_through_every_generation(db):
    """The model-level fix this task adds (`ForestBlock.compartments`
    `passive_deletes=True`): a plain `db.delete(parent)` -- with NO explicit
    redistribution, unlike the cut/merge paths -- must genuinely remove
    every descendant via Postgres's own ON DELETE CASCADE, recursively
    through however many sub-levels exist (A1), not just null their FK."""
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    child = _row(
        db, calc, box(83.005, 27.02, 83.02, 27.08),
        name="B1-SB1", division_level=2, parent=parent,
    )
    grandchild = _row(
        db, calc, box(83.008, 27.03, 83.015, 27.06),
        name="B1-SB1-SB1", division_level=3, parent=child,
    )
    # Captured before the commit below expires these ORM instances --
    # touching an attribute on an expired-and-now-deleted instance raises
    # ObjectDeletedError instead of giving back the old value.
    parent_id, child_id, grandchild_id = parent.id, child.id, grandchild.id

    db.delete(parent)
    db.commit()

    from app.models.forest_block import ForestBlock as FB

    assert db.query(FB).filter(FB.id == parent_id).first() is None
    assert db.query(FB).filter(FB.id == child_id).first() is None
    assert db.query(FB).filter(FB.id == grandchild_id).first() is None
