"""Re-clip sub-units when their parent's shape is edited (G2, FS-4a.10) -
``app.services.forest_units.operations.reshape``.
"""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services.forest_units.operations.reshape import reclip_children
from app.services.geometry_edit_service import area_sqm


def _make_calc(db):
    user = User(
        email=f"reshape{uuid.uuid4().hex[:8]}@test.com",
        full_name="Reshape Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="reshape.csv",
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


def test_no_children_is_a_cheap_noop(db):
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    result = reclip_children(db, calc, parent.id, box(83.0, 27.0, 83.08, 27.10))
    assert result == {"trimmed": [], "removed": [], "remainder_added": [], "split": []}


def test_child_entirely_inside_the_new_shape_is_untouched(db):
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    # Two children that fully tile the parent (west half / east half) --
    # matching how a real divide creates children, so the parent starts out
    # with no "always-uncovered" ground for the residual check to trip on.
    west_geom = box(83.0, 27.0, 83.05, 27.10)
    east_geom = box(83.05, 27.0, 83.10, 27.10)
    west = _row(db, calc, west_geom, name="B1-SB1", division_level=2, parent=parent)
    east = _row(db, calc, east_geom, name="B1-SB2", division_level=2, parent=parent)

    # New shape shrinks the parent on the east side only.
    new_shape = box(83.0, 27.0, 83.09, 27.10)
    result = reclip_children(db, calc, parent.id, new_shape)

    assert result["removed"] == []
    assert result["remainder_added"] == []
    assert result["trimmed"] == [str(east.id)]  # west untouched, east trimmed
    db.refresh(west)
    db.refresh(east)
    assert to_shape(west.geometry).equals(west_geom)
    assert to_shape(east.geometry).bounds[2] <= 83.09 + 1e-9


def test_removed_ground_trims_a_child(db):
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    # A child that straddles x=83.08 substantially.
    child_geom = box(83.06, 27.02, 83.12, 27.08)
    child = _row(db, calc, child_geom, name="B1-SB1", division_level=2, parent=parent)

    # Parent reshaped to end at x=83.08 -- the part of the child past that
    # edge is ground the edit removed.
    new_shape = box(83.0, 27.0, 83.08, 27.10)
    result = reclip_children(db, calc, parent.id, new_shape)

    assert result["trimmed"] == [str(child.id)]
    assert result["removed"] == []
    db.refresh(child)
    new_geom = to_shape(child.geometry)
    assert new_geom.bounds[2] <= 83.08 + 1e-9  # clipped to the new eastern edge
    assert area_sqm(new_geom) < area_sqm(child_geom)


def test_child_entirely_outside_the_new_shape_is_removed(db):
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    child_geom = box(83.085, 27.02, 83.095, 27.08)  # east side only
    child = _row(db, calc, child_geom, name="B1-SB1", division_level=2, parent=parent)

    # Parent reshaped to only the western half -- nothing of the child survives.
    new_shape = box(83.0, 27.0, 83.05, 27.10)
    result = reclip_children(db, calc, parent.id, new_shape)

    assert result["removed"] == [str(child.id)]
    assert result["trimmed"] == []
    assert db.query(ForestBlock).filter(ForestBlock.id == child.id).first() is None


def test_grandchildren_travel_with_a_removed_child(db):
    """D13, via FS-4a.9's passive_deletes=True cascade: a child dropped
    entirely by the reshape takes its own children with it."""
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    child = _row(
        db, calc, box(83.085, 27.02, 83.095, 27.08),
        name="B1-SB1", division_level=2, parent=parent,
    )
    grandchild = _row(
        db, calc, box(83.086, 27.03, 83.09, 27.06),
        name="B1-SB1-SB1", division_level=3, parent=child,
    )
    new_shape = box(83.0, 27.0, 83.05, 27.10)
    result = reclip_children(db, calc, parent.id, new_shape)

    assert result["removed"] == [str(child.id)]
    assert db.query(ForestBlock).filter(ForestBlock.id == child.id).first() is None
    assert db.query(ForestBlock).filter(ForestBlock.id == grandchild.id).first() is None


def test_grandchildren_are_reclipped_when_a_child_is_trimmed_not_removed(db):
    """A1: a trimmed (not removed) child's own children re-clip to the
    child's NEW shape in the same pass."""
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    child = _row(
        db, calc, box(83.02, 27.02, 83.09, 27.08),
        name="B1-SB1", division_level=2, parent=parent,
    )
    # Grandchild straddles x=83.06, inside the child's original extent.
    grandchild_geom = box(83.055, 27.03, 83.08, 27.06)
    grandchild = _row(
        db, calc, grandchild_geom,
        name="B1-SB1-SB1", division_level=3, parent=child,
    )

    # Parent (and therefore the child, clipped) shrinks to end at x=83.06.
    new_shape = box(83.0, 27.0, 83.06, 27.10)
    result = reclip_children(db, calc, parent.id, new_shape)

    assert str(child.id) in result["trimmed"]
    assert str(grandchild.id) in result["trimmed"]
    db.refresh(grandchild)
    new_gc_geom = to_shape(grandchild.geometry)
    assert new_gc_geom.bounds[2] <= 83.06 + 1e-9
    assert area_sqm(new_gc_geom) < area_sqm(grandchild_geom)


def test_newly_uncovered_ground_becomes_a_remainder_sub_unit(db):
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.05, 27.10))
    child_geom = box(83.0, 27.0, 83.05, 27.10)  # child covers the whole parent
    child = _row(db, calc, child_geom, name="B1-SB1", division_level=2, parent=parent)

    # Parent grows well past what the existing child covers -- 1000x the
    # sliver floor so the new ground is unambiguously a real remainder.
    new_shape = box(83.0, 27.0, 83.10, 27.10)
    result = reclip_children(db, calc, parent.id, new_shape)

    assert result["trimmed"] == []
    assert result["removed"] == []
    assert len(result["remainder_added"]) == 1

    kids = _children_of(db, parent.id)
    assert len(kids) == 2  # original child (unchanged) + the new remainder
    original = next(k for k in kids if k.id == child.id)
    remainder = next(k for k in kids if k.id != child.id)
    assert to_shape(original.geometry).equals(child_geom)
    assert remainder.name  # named via the normal sub-unit serial, not "Remainder ..."
    assert remainder.is_compartment == child.is_compartment
    assert remainder.division_level == child.division_level
    # Together the child + remainder tile the new parent shape (within the
    # same rounding-noise floor the boundary/coverage invariant uses).
    total = area_sqm(to_shape(original.geometry)) + area_sqm(to_shape(remainder.geometry))
    assert abs(total - area_sqm(new_shape)) < 100.0


def test_a_tiny_uncovered_sliver_is_not_remaindered(db):
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.05, 27.10))
    child_geom = box(83.0, 27.0, 83.05, 27.10)
    child = _row(db, calc, child_geom, name="B1-SB1", division_level=2, parent=parent)

    # New ground sliver well under the 1 ha sliver floor.
    new_shape = box(83.0, 27.0, 83.050001, 27.10)
    result = reclip_children(db, calc, parent.id, new_shape)

    assert result["remainder_added"] == []
    assert _children_of(db, parent.id) == [child]


def test_a_child_pinched_into_two_disjoint_pieces_is_split_not_unioned(db):
    """Regression test for the exact bug reported live (2026-09-23):
    `ensure_single_polygon` raised `MultiPartFeatureError` ("2 disjoint
    substantial parts... but only one row is being created for it") because
    the old code here unioned a reshape-pinched child's disjoint remnants
    back into one MultiPolygon and handed it to a single row's `.geometry`.
    They must become two rows instead."""
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    # A child spanning the full width, along the bottom of the parent.
    child_geom = box(83.0, 27.00, 83.10, 27.02)
    child = _row(db, calc, child_geom, name="B1-SB1", division_level=2, parent=parent)

    # New parent shape excludes the middle third entirely (west blob + east
    # blob) -- the child, spanning the gap, is pinched into two disjoint
    # substantial pieces.
    new_parent_geom = box(83.0, 27.0, 83.03, 27.10).union(box(83.07, 27.0, 83.10, 27.10))

    result = reclip_children(db, calc, parent.id, new_parent_geom)

    assert result["removed"] == []
    assert result["trimmed"] == []
    assert len(result["split"]) == 2

    # The old child row is gone, replaced by two single-Polygon rows.
    assert db.query(ForestBlock).filter(ForestBlock.id == child.id).first() is None
    split_rows = (
        db.query(ForestBlock)
        .filter(ForestBlock.id.in_(result["split"]))
        .all()
    )
    assert len(split_rows) == 2
    for row in split_rows:
        assert row.parent_block_id == parent.id
        geom = to_shape(row.geometry)
        assert geom.geom_type == "Polygon"
        assert area_sqm(geom) > 10_000.0  # each piece clears the 1 ha viable-unit floor


def test_grandchildren_follow_the_correct_split_piece(db):
    calc = _make_calc(db)
    parent = _row(db, calc, box(83.0, 27.0, 83.10, 27.10))
    child_geom = box(83.0, 27.00, 83.10, 27.02)
    child = _row(db, calc, child_geom, name="B1-SB1", division_level=2, parent=parent)
    # Grandchild sits entirely within what will become the WEST split piece.
    grandchild_geom = box(83.005, 27.005, 83.02, 27.015)
    grandchild = _row(
        db, calc, grandchild_geom, name="B1-SB1-SB1", division_level=3, parent=child,
    )

    new_parent_geom = box(83.0, 27.0, 83.03, 27.10).union(box(83.07, 27.0, 83.10, 27.10))
    result = reclip_children(db, calc, parent.id, new_parent_geom)

    assert len(result["split"]) == 3  # 2 split pieces of the child + 1 re-homed grandchild
    # The old grandchild row is replaced (its parent, `child`, was itself replaced).
    assert db.query(ForestBlock).filter(ForestBlock.id == grandchild.id).first() is None

    # The grandchild's new home is a child of one of the two split pieces,
    # with its geometry preserved unchanged (it sat entirely inside one piece).
    split_ids = set(result["split"])
    new_grandchild = (
        db.query(ForestBlock)
        .filter(ForestBlock.parent_block_id.in_(split_ids))
        .first()
    )
    assert new_grandchild is not None
    assert to_shape(new_grandchild.geometry).equals(grandchild_geom)


def test_compartment_branch_remainder_uses_compartment_naming(db):
    calc = _make_calc(db)
    parent = _row(
        db, calc, box(83.0, 27.0, 83.05, 27.10),
        name="C1", is_compartment=True, division_level=1,
    )
    child_geom = box(83.0, 27.0, 83.05, 27.10)
    _row(
        db, calc, child_geom, name="C1-SC1",
        is_compartment=True, division_level=2, parent=parent,
    )

    new_shape = box(83.0, 27.0, 83.10, 27.10)
    result = reclip_children(db, calc, parent.id, new_shape)

    assert len(result["remainder_added"]) == 1
    kids = _children_of(db, parent.id)
    remainder = next(k for k in kids if str(k.id) == result["remainder_added"][0])
    assert remainder.is_compartment is True
    assert "-SC" in remainder.name
