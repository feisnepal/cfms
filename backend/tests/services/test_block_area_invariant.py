"""Boundary ≡ Blocks area invariant tests (plan BLOCK_BOUNDARY_INVARIANT, E.1).

Covers ``clip_and_validate_block`` (clip to boundary, OUTSIDE_BOUNDARY,
TOPOLOGY_REJECTED overlap) and ``enforce_block_coverage`` (over-coverage
reject, under-coverage remainder auto-fill, no-boundary no-op, last-block
deletion → single remainder = whole boundary, compartments treated same).
"""
import re
import uuid

import pytest
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services import block_area_invariant_service as inv
from app.services.geometry_edit_service import W_TOPOLOGY_REJECTED, area_sqm, next_block_index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _square(x, y, size=0.01):
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def _make_user(db, email=None):
    user = User(
        email=email or f"inv{uuid.uuid4().hex[:8]}@test.com",
        full_name="Invariant Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    return user


def _make_calc(db, boundary=None):
    user = _make_user(db)
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="invariant-test.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    if boundary is not None:
        from geoalchemy2.shape import from_shape
        calc.boundary_geom = from_shape(boundary, srid=4326)
        db.flush()
    return calc


def _add_block(db, calc, geom, level="blocks", name=None, index=None):
    from geoalchemy2.shape import from_shape
    is_comp = level == "compartments"
    if index is None:
        index = next_block_index(db, str(calc.id))
    block = ForestBlock(
        calculation_id=calc.id,
        name=name or f"{'Compartment' if is_comp else 'Block'}-{index}",
        block_name=name or f"{'Compartment' if is_comp else 'Block'}-{index}",
        natural_name=None,
        geometry=from_shape(geom, srid=4326),
        area_hectares=round(area_sqm(geom) / 10000.0, 4),
        area_sqm=round(area_sqm(geom), 2),
        index=index,
        is_compartment=is_comp,
        division_level=1,
    )
    db.add(block)
    db.flush()
    return block


def _total_ha(db, calc, level="blocks"):
    from geoalchemy2.shape import to_shape
    rows = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment.is_(level == "compartments"),
    ).all()
    return sum(area_sqm(to_shape(r.geometry)) / 10000.0 for r in rows if r.geometry)


# ---------------------------------------------------------------------------
# clip_and_validate_block
# ---------------------------------------------------------------------------

def test_clip_trims_outside_portion(db):
    boundary = _square(0, 0, 0.02)
    calc = _make_calc(db, boundary=boundary)
    # Proposed block straddles the boundary edge (left half outside).
    proposed = Polygon([(-0.01, 0), (0.01, 0), (0.01, 0.02), (-0.01, 0.02)])
    clipped, info = inv.clip_and_validate_block(proposed, calc, level="blocks")
    assert clipped is not None and not clipped.is_empty
    assert info["clipped"] is True
    assert info["removed_ha"] > 0
    # Clipped result lies fully inside the boundary.
    assert boundary.covers(clipped)


def test_clip_rejects_fully_outside(db):
    calc = _make_calc(db, boundary=_square(0, 0, 0.02))
    proposed = _square(5, 5, 0.01)  # far away
    with pytest.raises(ValueError, match="OUTSIDE_BOUNDARY"):
        inv.clip_and_validate_block(proposed, calc, level="blocks")


def test_clip_rejects_overlapping_existing_block(db):
    boundary = _square(0, 0, 0.04)
    calc = _make_calc(db, boundary=boundary)
    _add_block(db, calc, _square(0, 0, 0.02), level="blocks")
    proposed = _square(0.005, 0.005, 0.02)  # materially overlaps existing
    existing = [r.geometry for r in db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()]
    with pytest.raises(ValueError, match="TOPOLOGY_REJECTED"):
        inv.clip_and_validate_block(proposed, calc, existing, level="blocks")


def test_clip_accepts_adjacent_no_overlap(db):
    boundary = _square(0, 0, 0.04)
    calc = _make_calc(db, boundary=boundary)
    _add_block(db, calc, _square(0, 0, 0.02), level="blocks")
    proposed = _square(0.02, 0, 0.02)  # adjacent, shares edge only
    existing = [r.geometry for r in db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()]
    clipped, info = inv.clip_and_validate_block(proposed, calc, existing, level="blocks")
    assert clipped is not None and not clipped.is_empty
    assert W_TOPOLOGY_REJECTED not in (info["warnings"] or [])


def test_clip_no_boundary_accepts_as_is(db):
    calc = _make_calc(db, boundary=None)
    proposed = _square(0, 0, 0.01)
    clipped, info = inv.clip_and_validate_block(proposed, calc, level="blocks")
    assert clipped is not None and not clipped.is_empty


# ---------------------------------------------------------------------------
# enforce_block_coverage
# ---------------------------------------------------------------------------

def test_enforce_under_coverage_adds_remainder(db):
    boundary = _square(0, 0, 0.03)
    calc = _make_calc(db, boundary=boundary)
    _add_block(db, calc, _square(0, 0, 0.02), level="blocks")
    res = inv.enforce_block_coverage(db, calc, level="blocks")
    assert res["remainder_added"] is True
    assert res["gap_ha"] > 0
    assert abs(_total_ha(db, calc) - res["boundary_ha"]) < 0.5


def test_enforce_over_coverage_rejects(db):
    boundary = _square(0, 0, 0.02)
    calc = _make_calc(db, boundary=boundary)
    # Two overlapping blocks that exceed the boundary area.
    _add_block(db, calc, _square(-0.005, -0.005, 0.02), level="blocks")
    _add_block(db, calc, _square(0.005, 0.005, 0.02), level="blocks")
    with pytest.raises(ValueError, match="TOPOLOGY_REJECTED"):
        inv.enforce_block_coverage(db, calc, level="blocks")


def test_enforce_full_coverage_noop(db):
    boundary = _square(0, 0, 0.02)
    calc = _make_calc(db, boundary=boundary)
    _add_block(db, calc, boundary, level="blocks")
    res = inv.enforce_block_coverage(db, calc, level="blocks")
    assert res["remainder_added"] is False
    assert abs(_total_ha(db, calc) - res["boundary_ha"]) < 0.5


def test_enforce_no_boundary_noop(db):
    calc = _make_calc(db, boundary=None)
    res = inv.enforce_block_coverage(db, calc, level="blocks")
    assert res["remainder_added"] is False
    assert res["boundary_ha"] == 0.0


def test_enforce_deleting_last_block_remains_boundary(db):
    boundary = _square(0, 0, 0.02)
    calc = _make_calc(db, boundary=boundary)
    b = _add_block(db, calc, boundary, level="blocks")
    db.delete(b)
    db.flush()
    res = inv.enforce_block_coverage(db, calc, level="blocks")
    assert res["remainder_added"] is True
    assert abs(_total_ha(db, calc) - res["boundary_ha"]) < 0.5


def test_enforce_under_coverage_with_disjoint_gap_adds_one_row_per_piece(db):
    """2026-09-12 live bug: a merge (or any edit) that leaves TWO separate
    uncovered regions used to get exactly the same MultiPolygon-in-one-row
    corruption as महाभारत Compartment-13 -- `_explode_multipart` split the
    gap into its real disjoint pieces, then `unary_union(parts)` promptly
    fused them back together (a no-op for touching pieces, but for
    genuinely disjoint ones it just rebuilds the MultiPolygon) before
    handing it to a single ForestBlock row. Once the single-part-geometry
    ORM guard shipped, that started raising instead of silently persisting
    -- surfacing as a 500 on an otherwise perfectly legitimate merge of two
    adjoining compartments. One remainder row per real gap piece is the fix."""
    boundary = _square(0, 0, 0.06)
    calc = _make_calc(db, boundary=boundary)
    # A middle strip covers the centre, leaving disjoint gaps on either side.
    middle = Polygon([(0.02, 0), (0.04, 0), (0.04, 0.06), (0.02, 0.06)])
    _add_block(db, calc, middle, level="compartments")

    res = inv.enforce_block_coverage(db, calc, level="compartments")

    assert res["remainder_added"] is True
    rows = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment.is_(True),
    ).all()
    # 1 middle strip + 2 remainder pieces (left gap, right gap) = 3 rows,
    # every one a plain Polygon -- never one row bundling both gaps.
    assert len(rows) == 3
    from geoalchemy2.shape import to_shape
    for r in rows:
        assert to_shape(r.geometry).geom_type == "Polygon"
    assert abs(_total_ha(db, calc, "compartments") - res["boundary_ha"]) < 0.5


def test_enforce_compartments_treated_same(db):
    boundary = _square(0, 0, 0.03)
    calc = _make_calc(db, boundary=boundary)
    _add_block(db, calc, _square(0, 0, 0.02), level="compartments")
    res = inv.enforce_block_coverage(db, calc, level="compartments")
    assert res["remainder_added"] is True
    assert abs(_total_ha(db, calc, "compartments") - res["boundary_ha"]) < 0.5
    rows = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment.is_(True),
    ).all()
    assert len(rows) == 2
    assert any(re.fullmatch(r"C\d+", r.name) for r in rows)  # the remainder is C<N>
