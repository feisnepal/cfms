"""Overlap between sibling units is held to a tight tolerance and may not get worse (owner, 2026-10-19: "overlap should not happen").

बनस्खन्डी's units overlapped by 0.27 ha on a 221 ha parent (11 pairs) and every check let it through, because the old tolerance for
all three geometry rules was 0.5 % of the parent (1.1 ha). An overlap is ground two units both claim, so it is held far tighter than
a gap; it is also checked between top-level units; and an edit that makes an existing overlap worse is refused.
"""

from __future__ import annotations

import pytest
from geoalchemy2.shape import from_shape

from app.models.forest_block import ForestBlock
from app.services.forest_units import invariants as inv
from app.services.forest_units.write import structure_write

from . import fixtures
from .test_invariants import _calc, _codes, _row


def _grow_sb2(db, f, x0):
    """SB2 (right half of B1, normally x 5..10) pulled left to x0: an overlap of (5 - x0) x 10 deg2 over SB1 (parent is 100 deg2)."""
    _row(db, f, "SB2").geometry = from_shape(fixtures.rect(x0, 0, 10, 10), srid=4326)
    db.flush()


# ---------------------------------------------------------------- the tolerance
def test_an_overlap_the_old_tolerance_let_through_is_now_a_violation(make_forest, db):
    f = make_forest("F3")
    _grow_sb2(db, f, 4.99)                          # 0.1 % of the parent: under the old 0.5 %, over the new 0.005 %
    assert (inv.CHILDREN_OVERLAP, "B1") in _codes(db, f)


def test_rounding_noise_is_still_not_an_overlap(make_forest, db):
    f = make_forest("F3")
    _grow_sb2(db, f, 4.9999)                        # 0.001 % of the parent: a clip's rounding
    assert (inv.CHILDREN_OVERLAP, "B1") not in _codes(db, f)


def test_a_gap_keeps_its_looser_tolerance(make_forest, db):
    f = make_forest("F3")
    _row(db, f, "SB2").geometry = from_shape(fixtures.rect(5, 0, 9.99, 10), srid=4326)   # 0.1 % short: a sliver, not a fault
    db.flush()
    assert inv.find_violations(db, f.calc_id) == []


def test_the_tolerances_are_far_tighter_for_overlap_than_for_a_gap():
    assert inv.OVERLAP_REL_TOL * 50 <= inv.REL_TOL
    assert inv.OVERLAP_ABS_TOL_HA < inv.ABS_TOL_HA


# ---------------------------------------------------------------- the top level
def test_top_level_units_that_overlap_are_reported(make_forest, db):
    f = make_forest("F1")
    _row(db, f, "B2").geometry = from_shape(fixtures.rect(9.9, 0, 20, 10), srid=4326)   # B2 pulled over B1
    db.flush()
    assert (inv.CHILDREN_OVERLAP, inv.TOP_LEVEL) in _codes(db, f)


def test_clean_top_level_units_are_not_reported(make_forest, db):
    f = make_forest("F1")
    assert (inv.CHILDREN_OVERLAP, inv.TOP_LEVEL) not in _codes(db, f)


def test_the_two_branches_of_a_legacy_mixed_forest_are_not_each_others_siblings(make_forest, db):
    f = make_forest("F5")                            # blocks and compartments side by side: MIXED_BRANCHES, not an overlap
    codes = _codes(db, f)
    assert (inv.MIXED_BRANCHES, "") in codes
    assert (inv.CHILDREN_OVERLAP, inv.TOP_LEVEL) not in codes


# ---------------------------------------------------------------- an edit may not make it worse
def test_an_edit_that_makes_an_existing_overlap_worse_is_refused(make_forest, db):
    f = make_forest("F3")
    calc = _calc(db, f)
    _grow_sb2(db, f, 4.99)
    db.commit()                                      # the forest is already broken, a little
    with pytest.raises(inv.StructureInvariantError) as e:
        with structure_write(db, calc, change="grow the overlap"):
            _grow_sb2(db, f, 4.5)
    assert any(v.code == inv.CHILDREN_OVERLAP for v in e.value.violations)
    db.rollback()


def test_an_edit_that_leaves_an_existing_overlap_alone_goes_through(make_forest, db):
    f = make_forest("F3")
    calc = _calc(db, f)
    _grow_sb2(db, f, 4.99)
    db.commit()
    with structure_write(db, calc, change="rename something"):
        _row(db, f, "B2").color = "#112233"
        db.flush()
    db.commit()


def test_an_edit_that_shrinks_an_overlap_goes_through(make_forest, db):
    f = make_forest("F3")
    calc = _calc(db, f)
    _grow_sb2(db, f, 4.9)
    db.commit()
    with structure_write(db, calc, change="shrink the overlap"):
        _grow_sb2(db, f, 4.99)
    db.commit()
    assert (inv.CHILDREN_OVERLAP, "B1") in _codes(db, f)        # still there, smaller: not locked out, not refused


def test_new_violations_counts_only_growth_beyond_the_margin():
    old = inv.Violation(inv.CHILDREN_OVERLAP, "P", "x", 0.100)
    assert inv.new_violations([old], [inv.Violation(inv.CHILDREN_OVERLAP, "P", "x", 0.1005)]) == []        # 5 m2 of noise
    assert len(inv.new_violations([old], [inv.Violation(inv.CHILDREN_OVERLAP, "P", "x", 0.2)])) == 1
    assert inv.new_violations([old], []) == []
    gap = inv.Violation(inv.CHILDREN_DO_NOT_COVER_PARENT, "P", "x", 1.0)
    assert inv.new_violations([gap], [inv.Violation(inv.CHILDREN_DO_NOT_COVER_PARENT, "P", "x", 5.0)]) == []   # a gap growing is not this rule
    assert len(inv.new_violations([], [old])) == 1
