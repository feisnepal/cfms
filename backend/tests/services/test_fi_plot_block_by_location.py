"""field_inventory_service.assign_plot_blocks_by_location — geometry-authoritative
block re-keying.

A sample plot's ``block_name`` is read verbatim from the uploaded sheet, where it
routinely names a since-deleted compartment or holds junk. This pass overwrites it
with the forest unit (compartment, else top-level block) whose polygon actually
contains the plot's GPS point, so every downstream per-unit join lines up with the
current structure.
"""

from __future__ import annotations

import uuid

import pytest
from shapely.geometry import Polygon

from app.models.calculation import Calculation
from app.models.field_inventory import (
    FieldInventoryCalculation,
    FieldInventorySamplePlot,
)
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.services.field_inventory_service import assign_plot_blocks_by_location


NL = 27.5
NS = 83.5


@pytest.fixture()
def owner(db):
    user = User(
        email=f"fiblk-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="FI Block Fixture",
    )
    db.add(user)
    db.flush()
    return user


def _square(x0, y0, size=0.01):
    return Polygon([(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)])


def _calc(db, owner):
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        uploaded_filename="fixture.csv",
        is_draft=False,
        structure_locked=False,
        result_data={},
    )
    db.add(calc)
    db.flush()
    return calc


def _unit(db, calc, geom, name, *, is_compartment=False, index=1, parent=None):
    from geoalchemy2.shape import from_shape
    from app.utils.geometry_utils import calculate_area_geodesic_from_shapely

    _sqm, _ha = calculate_area_geodesic_from_shapely(geom)
    row = ForestBlock(
        calculation_id=calc.id,
        name=name,
        block_name=name,
        geometry=from_shape(geom, srid=4326),
        area_hectares=round(_ha * 0.98, 4),
        index=index,
        is_compartment=is_compartment,
        division_level=1,
        parent_block_id=parent.id if parent is not None else None,
    )
    db.add(row)
    db.flush()
    return row


def _fi_with_plots(db, owner, calc, points, uploaded_name="C-OLD"):
    """`points` items are (lon, lat) or (lon, lat, block_name, plot_number)."""
    fi = FieldInventoryCalculation(
        user_id=owner.id,
        uploaded_filename="fi.csv",
        status="processing",
        calculation_id=calc.id if calc else None,
    )
    db.add(fi)
    db.flush()
    plots = []
    for i, pt in enumerate(points, start=1):
        lon, lat = pt[0], pt[1]
        bn = pt[2] if len(pt) > 2 else uploaded_name
        num = pt[3] if len(pt) > 3 else i
        p = FieldInventorySamplePlot(
            field_inventory_calculation_id=fi.id,
            block_name=bn,
            sample_plot_number=num,
            location=f"SRID=4326;POINT({lon} {lat})",
        )
        db.add(p)
        plots.append(p)
    db.flush()
    return fi, plots


def test_plot_is_rekeyed_to_the_block_that_contains_it(db, owner):
    calc = _calc(db, owner)
    _unit(db, calc, _square(NS, NL), "blocks-1", index=1)
    _unit(db, calc, _square(NS + 0.02, NL), "blocks-2", index=2)
    # both plots uploaded as "C-OLD"; they sit in blocks-1 and blocks-2
    fi, (p1, p2) = _fi_with_plots(
        db, owner, calc, [(NS + 0.005, NL + 0.005), (NS + 0.025, NL + 0.005)]
    )

    assign_plot_blocks_by_location(db, fi.id, fi)

    db.refresh(p1)
    db.refresh(p2)
    assert p1.block_name == "blocks-1"
    assert p2.block_name == "blocks-2"


def test_a_plot_goes_to_the_compartment_not_the_block_it_was_divided_from(db, owner):
    """A block divided into compartments (the compartments' parent) is not a leaf; its plots belong to the
    compartment that holds them (FS-1a.5: the leaf view)."""
    calc = _calc(db, owner)
    block = _unit(db, calc, _square(NS, NL, size=0.05), "blocks-1", index=1)
    _unit(db, calc, _square(NS, NL), "C1", is_compartment=True, index=1, parent=block)
    _unit(
        db, calc, _square(NS + 0.01, NL), "C2", is_compartment=True, index=2, parent=block
    )
    fi, (p1,) = _fi_with_plots(db, owner, calc, [(NS + 0.015, NL + 0.005)])

    assign_plot_blocks_by_location(db, fi.id, fi)

    db.refresh(p1)
    assert p1.block_name == "C2"  # the containing compartment, not "blocks-1"


def test_a_plot_reaches_the_sub_compartment_that_holds_it(db, owner):
    """FS-1a.5: with C1 divided into SC1/SC2 the plot goes to SC2, not to its parent C1 (which used to win
    because it comes first in the list and contains the point)."""
    calc = _calc(db, owner)
    c1 = _unit(db, calc, _square(NS, NL, size=0.02), "C1", is_compartment=True, index=1)
    _unit(db, calc, _square(NS, NL), "SC1", is_compartment=True, index=2, parent=c1)
    _unit(
        db, calc, _square(NS + 0.01, NL), "SC2", is_compartment=True, index=3, parent=c1
    )
    fi, (p1,) = _fi_with_plots(db, owner, calc, [(NS + 0.015, NL + 0.005)])

    assign_plot_blocks_by_location(db, fi.id, fi)

    db.refresh(p1)
    assert p1.block_name == "SC2"


def test_plot_just_outside_is_snapped_to_nearest_unit(db, owner):
    calc = _calc(db, owner)
    _unit(db, calc, _square(NS, NL), "blocks-1", index=1)
    # ~0.001° (~100 m) east of the block's edge — inside the snap tolerance
    fi, (p1,) = _fi_with_plots(db, owner, calc, [(NS + 0.011, NL + 0.005)])

    assign_plot_blocks_by_location(db, fi.id, fi)

    db.refresh(p1)
    assert p1.block_name == "blocks-1"


def test_far_outside_plot_keeps_its_uploaded_label(db, owner):
    calc = _calc(db, owner)
    _unit(db, calc, _square(NS, NL), "blocks-1", index=1)
    # swapped lat/lon → nowhere near the forest
    fi, (p1,) = _fi_with_plots(
        db, owner, calc, [(NL, NS)], uploaded_name="Panchpokhari"
    )

    assign_plot_blocks_by_location(db, fi.id, fi)

    db.refresh(p1)
    assert p1.block_name == "Panchpokhari"


def test_no_forest_blocks_is_a_safe_noop(db, owner):
    calc = _calc(db, owner)
    fi, (p1,) = _fi_with_plots(
        db, owner, calc, [(NS + 0.005, NL + 0.005)], uploaded_name="nan"
    )

    assign_plot_blocks_by_location(db, fi.id, fi)

    db.refresh(p1)
    assert p1.block_name == "nan"


def test_colliding_plot_numbers_are_renumbered_not_dropped(db, owner):
    """The (fi, block_name, plot_number) unique key: two plots the sheet filed
    under different blocks with the SAME number both land in blocks-1 — keep
    both, renumber the second."""
    calc = _calc(db, owner)
    _unit(db, calc, _square(NS, NL, size=0.03), "blocks-1", index=1)
    fi, (p1, p2) = _fi_with_plots(
        db,
        owner,
        calc,
        [
            (NS + 0.005, NL + 0.005, "C5", 42),
            (NS + 0.010, NL + 0.010, "C7", 42),
        ],
    )

    assign_plot_blocks_by_location(db, fi.id, fi)

    db.refresh(p1)
    db.refresh(p2)
    assert p1.block_name == "blocks-1"
    assert p2.block_name == "blocks-1"
    assert {p1.sample_plot_number, p2.sample_plot_number} == {42, 43}
    # both survived
    assert (
        db.query(FieldInventorySamplePlot)
        .filter(FieldInventorySamplePlot.field_inventory_calculation_id == fi.id)
        .count()
        == 2
    )


# `test_no_parent_calculation_is_a_safe_noop` was removed on 2026-09-21: a field inventory can no longer exist
# without a forest (owner's rule, migration 092 -- `calculation_id` is NOT NULL), so that situation cannot occur.
