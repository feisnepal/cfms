"""The structure invariants (``app.services.forest_units.invariants``) and the guard in ``structure_write``.

Owner rules: a forest has blocks OR compartments, never both (परिक्षण वन kept Block-1..8 beside its compartments, and nothing
noticed); and the sub-units of a unit lie inside it, never overlap and together cover it.
"""

from __future__ import annotations

import pytest
from geoalchemy2.shape import from_shape

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.services.forest_units import invariants as inv
from app.services.forest_units.write import structure_write

from . import fixtures


def _calc(db, forest):
    return db.query(Calculation).filter(Calculation.id == forest.calc_id).first()


def _row(db, forest, name):
    return db.query(ForestBlock).filter(ForestBlock.id == forest.units[name]).one()


def _codes(db, forest):
    return {(v.code, v.unit) for v in inv.find_violations(db, forest.calc_id)}


@pytest.mark.parametrize("key", ["F1", "F2", "F3", "F4"])
def test_a_clean_forest_has_no_violations(make_forest, db, key):
    assert inv.find_violations(db, make_forest(key).calc_id) == []


def test_a_mixed_forest_is_reported(make_forest, db):
    f = make_forest("F5")  # the legacy mixed forest: blocks and compartments together
    assert (inv.MIXED_BRANCHES, "") in _codes(db, f)


def test_children_that_leave_the_parent_uncovered_are_reported(make_forest, db):
    f = make_forest("F3")
    sb2 = _row(db, f, "SB2")
    sb2.geometry = from_shape(fixtures.rect(5, 0, 7, 10), srid=4326)  # SB2 shrunk: B1 is no longer covered
    db.flush()
    assert (inv.CHILDREN_DO_NOT_COVER_PARENT, "B1") in _codes(db, f)


def test_children_that_overlap_are_reported(make_forest, db):
    f = make_forest("F3")
    sb2 = _row(db, f, "SB2")
    sb2.geometry = from_shape(fixtures.rect(3, 0, 10, 10), srid=4326)  # SB2 grown over SB1
    db.flush()
    assert (inv.CHILDREN_OVERLAP, "B1") in _codes(db, f)


def test_a_child_outside_its_parent_is_reported(make_forest, db):
    f = make_forest("F3")
    sb2 = _row(db, f, "SB2")
    sb2.geometry = from_shape(fixtures.rect(5, 0, 14, 10), srid=4326)  # SB2 pokes into B2
    db.flush()
    assert (inv.CHILD_OUTSIDE_PARENT, "B1") in _codes(db, f)


def test_a_sliver_inside_the_tolerance_is_not_a_violation(make_forest, db):
    f = make_forest("F3")
    sb2 = _row(db, f, "SB2")
    sb2.geometry = from_shape(fixtures.rect(5, 0, 9.999, 10), srid=4326)  # 0.01% short of B1
    db.flush()
    assert inv.find_violations(db, f.calc_id) == []


def test_a_stale_child_count_is_reported(make_forest, db):
    f = make_forest("F3")
    _row(db, f, "B1").child_count = 0  # B1 really has SB1 and SB2: the DBG fault
    db.flush()
    assert (inv.CHILD_COUNT_STALE, "B1") in _codes(db, f)


def test_an_edit_that_forgets_the_child_count_is_healed_not_refused(make_forest, db):
    """Several writers add a sub-unit without updating the parent's count; the funnel rebuilds it, so the edit goes through and
    the count is right afterwards."""
    f = make_forest("F3")
    calc = _calc(db, f)
    with structure_write(db, calc, change="forget to update the count"):
        _row(db, f, "B1").child_count = 5  # wrong: B1 really has two sub-blocks
        db.flush()
    db.commit()
    assert _row(db, f, "B1").child_count == 2
    assert inv.find_violations(db, f.calc_id) == []


# ── the guard in the write funnel ────────────────────────────────────────────────────────────


def _stray_block(calc, geom):
    return ForestBlock(
        calculation_id=calc.id, name="Stray", block_name="Stray", geometry=from_shape(geom, srid=4326),
        area_hectares=1.0, index=99, is_compartment=False, division_level=1,
    )


def test_an_edit_that_adds_a_second_branch_is_refused(make_forest, db):
    """The Block-1..8 case: a compartment forest must not be given block-branch units beside its compartments."""
    f = make_forest("F2")
    calc = _calc(db, f)
    with pytest.raises(inv.StructureInvariantError) as e:
        with structure_write(db, calc, change="add a block to a compartment forest"):
            db.add(_stray_block(calc, f.boundary.buffer(-0.001)))
            db.flush()
    assert e.value.http_status == 409 and e.value.error_code == "structure_invariant_violated"
    assert inv.MIXED_BRANCHES in {v.code for v in e.value.violations}
    db.rollback()
    assert db.query(ForestBlock).filter(ForestBlock.calculation_id == f.calc_id, ForestBlock.name == "Stray").count() == 0


def test_switching_branch_in_one_edit_is_allowed(make_forest, db):
    """Replacing the old units with the other branch in the SAME edit never shows a mixed forest at the end."""
    f = make_forest("F1")  # blocks B1, B2
    calc = _calc(db, f)
    with structure_write(db, calc, change="switch to compartments"):
        for name in ("B1", "B2"):
            db.delete(_row(db, f, name))
        db.flush()
        for i, (x0, x1) in enumerate(((0, 10), (10, 20)), start=1):
            db.add(ForestBlock(
                calculation_id=calc.id, name=f"C{i}", block_name=f"C{i}",
                geometry=from_shape(fixtures.rect(x0, 0, x1, 10), srid=4326), area_hectares=1.0,
                index=i, is_compartment=True, division_level=1,
            ))
        db.flush()
    db.commit()
    assert inv.find_violations(db, f.calc_id) == []


def test_an_edit_that_breaks_the_tiling_is_refused(make_forest, db):
    f = make_forest("F3")
    calc = _calc(db, f)
    with pytest.raises(inv.StructureInvariantError) as e:
        with structure_write(db, calc, change="shrink a sub-block"):
            _row(db, f, "SB2").geometry = from_shape(fixtures.rect(5, 0, 7, 10), srid=4326)
            db.flush()
    assert inv.CHILDREN_DO_NOT_COVER_PARENT in {v.code for v in e.value.violations}
    db.rollback()


def test_a_forest_that_was_already_broken_can_still_be_edited(make_forest, db):
    """Only a NEW violation is refused: the legacy mixed forest is not locked out of every later edit."""
    f = make_forest("F5")
    calc = _calc(db, f)
    assert (inv.MIXED_BRANCHES, "") in _codes(db, f)
    with structure_write(db, calc, change="harmless"):
        _row(db, f, "B2").color = "#112233"
        db.flush()
    db.commit()


def test_a_clean_edit_passes_through(make_forest, db):
    f = make_forest("F3")
    calc = _calc(db, f)
    with structure_write(db, calc, change="rename"):
        _row(db, f, "SB1").natural_name = "Dharung Khola"
        db.flush()
    db.commit()
    assert inv.find_violations(db, f.calc_id) == []
