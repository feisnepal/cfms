"""The virtual root (D6, FS-4a.4) - ``forest_units.operations.virtual_root``."""

from __future__ import annotations

from app.models.calculation import Calculation
from app.services.forest_units.operations.virtual_root import (
    resolve_divide_source,
    virtual_root_source,
)

from . import fixtures


def _calc(db, forest):
    return db.query(Calculation).filter(Calculation.id == forest.calc_id).first()


def test_no_boundary_returns_nothing(db, make_forest):
    """A forest with no boundary at all (never happens via the real create flow,
    but the function must not raise) has no root to divide from."""
    f = make_forest("F0")
    calc = _calc(db, f)
    calc.boundary_geom = None
    db.flush()

    polygon, exclude_geom = virtual_root_source(db, calc)
    assert polygon is None
    assert exclude_geom is None


def test_boundary_only_forest_has_no_units_yet_and_the_root_is_the_boundary(db, make_forest):
    """F0: a boundary with no units yet -- the whole point of the virtual root
    (D6) is that this state needs no phantom whole-forest block to divide from."""
    f = make_forest("F0")
    calc = _calc(db, f)

    polygon, exclude_geom = virtual_root_source(db, calc)
    assert polygon is not None
    assert polygon.equals(f.boundary)
    assert exclude_geom is None  # no protection units exist yet


def test_private_land_is_excluded_from_the_root(db, make_forest):
    """F9: 10% private land -> the root polygon must already be net of it (P3a-1's
    forest_area_geom), not the raw boundary."""
    f = make_forest("F9")
    calc = _calc(db, f)

    polygon, _exclude_geom = virtual_root_source(db, calc)
    assert polygon is not None
    assert polygon.area < f.boundary.area
    # Matches the F9 ratio expectation (10% private -> 90% remains).
    assert polygon.area / f.boundary.area == 0.9 or abs(polygon.area / f.boundary.area - 0.9) < 0.01


def test_existing_protection_units_are_the_exclude_geom(db, make_forest):
    """F8: a protection working-circle unit (P-1) already exists -- a root-level
    divide must punch around it, not slice through it."""
    f = make_forest("F8")
    calc = _calc(db, f)

    polygon, exclude_geom = virtual_root_source(db, calc)
    assert polygon is not None
    assert exclude_geom is not None
    # P-1 is entirely inside the exclude geometry.
    p1_geom = f.unit_geoms["P-1"]
    assert exclude_geom.contains(p1_geom.buffer(-1e-9)) or exclude_geom.intersection(p1_geom).area > p1_geom.area * 0.99


def test_resolve_divide_source_prefers_a_real_parent(db, make_forest):
    """A real parent row's own geometry is used verbatim, with no root exclusion
    applied a second time (D13/G1: that already happened when the parent itself
    was created)."""
    f = make_forest("F1")
    calc = _calc(db, f)
    from app.models.forest_block import ForestBlock

    b1 = db.query(ForestBlock).filter(ForestBlock.id == f.units["B1"]).first()

    polygon, exclude_geom = resolve_divide_source(db, calc, b1)
    assert polygon is not None
    assert polygon.equals(f.unit_geoms["B1"])
    assert exclude_geom is None


def test_resolve_divide_source_falls_back_to_the_root_with_no_parent(db, make_forest):
    f = make_forest("F0")
    calc = _calc(db, f)

    polygon, exclude_geom = resolve_divide_source(db, calc, None)
    assert polygon is not None
    assert polygon.equals(f.boundary)
