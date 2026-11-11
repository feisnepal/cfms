"""Consequence hook part 2 (D11, FS-1d.5) - ``app.services.forest_units.structure_impact``."""

from __future__ import annotations

from app.models.calculation import Calculation
from app.models.field_inventory import FieldInventoryCalculation, FieldInventorySamplePlot
from app.models.forest_block import ForestBlock
from app.models.inventory import InventoryCalculation, InventoryTree
from app.services.forest_units.structure_impact import reassign_after_structure_change
from app.services.forest_units.write import on_structure_changed

from . import fixtures


def _calc(db, forest):
    return db.query(Calculation).filter(Calculation.id == forest.calc_id).first()


def _trees(db, calc_id):
    """Trees scoped to ONE calculation. ``db.query(InventoryTree).all()`` is
    unscoped, and the plain ``db`` fixture has no per-test rollback -- another
    test's leftover trees (any calc, any test file) are still in the shared
    test database and would otherwise be counted here too."""
    return (
        db.query(InventoryTree)
        .join(
            InventoryCalculation,
            InventoryCalculation.id == InventoryTree.inventory_calculation_id,
        )
        .filter(InventoryCalculation.calculation_id == calc_id)
        .all()
    )


def _plots(db, calc_id):
    return (
        db.query(FieldInventorySamplePlot)
        .join(
            FieldInventoryCalculation,
            FieldInventoryCalculation.id
            == FieldInventorySamplePlot.field_inventory_calculation_id,
        )
        .filter(FieldInventoryCalculation.calculation_id == calc_id)
        .all()
    )


def test_trees_and_plots_get_their_units_unit_id(db, make_forest):
    """F10 already carries trees (two in B1, one in B2) and a plot (in B1) with no
    ``unit_id`` set (pre-095 fixture data). A fresh re-sync assigns each to its
    containing unit."""
    f = make_forest("F10")
    calc = _calc(db, f)

    stats = reassign_after_structure_change(db, calc)
    db.flush()

    assert stats["trees_reassigned"] == 3
    assert stats["plots_reassigned"] == 1

    trees = _trees(db, calc.id)
    by_unit = {str(t.unit_id) for t in trees}
    assert by_unit == {str(f.units["B1"]), str(f.units["B2"])}
    b1_trees = [t for t in trees if str(t.unit_id) == str(f.units["B1"])]
    assert len(b1_trees) == 2

    plots = _plots(db, calc.id)
    assert len(plots) == 1
    assert str(plots[0].unit_id) == str(f.units["B1"])


def test_reshaping_a_unit_clears_trees_that_fall_outside_it(db, make_forest):
    """A tree correctly assigned to B1 must not keep pointing at B1 once B1 is
    reshaped out from under it - it is cleared (NULL), not left stale."""
    f = make_forest("F10")
    calc = _calc(db, f)
    reassign_after_structure_change(db, calc)
    db.flush()

    # Shrink B1 down to a sliver that contains neither tree (2,3) nor (4,5) in the
    # fixture's 0.001-degree frame, but leave B2 untouched.
    tiny = fixtures.rect(0, 0, 1, 1)
    b1_row = db.query(ForestBlock).filter(ForestBlock.id == f.units["B1"]).first()
    from geoalchemy2.shape import from_shape

    b1_row.geometry = from_shape(tiny, srid=4326)
    db.flush()

    stats = reassign_after_structure_change(db, calc)
    db.flush()

    trees = _trees(db, calc.id)
    unassigned = [t for t in trees if t.unit_id is None]
    assert len(unassigned) == 2  # the two trees B1 used to contain
    b2_trees = [t for t in trees if str(t.unit_id) == str(f.units["B2"])]
    assert len(b2_trees) == 1  # untouched
    assert stats["trees_reassigned"] == 1  # only B2's tree matched again


def test_on_structure_changed_calls_the_reassignment(db, make_forest):
    """The funnel-level hook (part 1: mark stale) also runs part 2 - a caller using
    ``on_structure_changed`` directly (not through the full ``structure_write``
    context manager) still gets trees/plots re-synced."""
    f = make_forest("F10")
    calc = _calc(db, f)

    on_structure_changed(db, calc, change="test")
    db.flush()

    trees = _trees(db, calc.id)
    assert trees and all(t.unit_id is not None for t in trees)


def test_a_forest_with_no_inventory_data_is_a_cheap_noop(db, make_forest):
    f = make_forest("F1")
    calc = _calc(db, f)
    stats = reassign_after_structure_change(db, calc)
    assert stats == {"trees_reassigned": 0, "plots_reassigned": 0}
