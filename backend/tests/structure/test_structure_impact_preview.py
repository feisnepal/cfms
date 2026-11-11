"""Impact-preview endpoint (FS-4a.15, last task of P4a §11.2) -
``app.services.forest_units.structure_impact.preview_structure_change``.
"""

from __future__ import annotations

import uuid

from shapely.geometry import mapping
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.field_inventory import FieldInventoryCalculation, FieldInventorySamplePlot
from app.models.forest_block import ForestBlock
from app.models.inventory import InventoryCalculation
from app.models.sampling import SamplingDesign
from app.models.user import User
from app.services.forest_units.structure_impact import (
    preview_structure_change,
    reassign_after_structure_change,
)

from . import fixtures
from .fixtures import X0, Y0, rect


def _calc(db, forest):
    return db.query(Calculation).filter(Calculation.id == forest.calc_id).first()


def test_a_forest_with_no_inventory_data_is_a_cheap_noop(db, make_forest):
    f = make_forest("F1")
    calc = _calc(db, f)
    result = preview_structure_change(db, calc, feature_ids=[])
    assert result == {
        "affected_unit_ids": [],
        "trees": {"at_risk": 0, "stays": 0, "moves": 0, "unassigned": 0},
        "plots": {"at_risk": 0, "stays": 0, "moves": 0, "unassigned": 0},
        "sampling_designs_affected": 0,
        "stale_domains": ["analysis", "sampling", "field_inventory"],
    }


def test_new_geometry_that_still_covers_everyone_means_everyone_stays(db, make_forest):
    f = make_forest("F10")
    calc = _calc(db, f)
    reassign_after_structure_change(db, calc)  # give trees/plots their unit_id first
    db.flush()

    b1_geom = rect(0, 0, 10, 10)  # B1's own shape, unchanged -- a no-op "reshape"
    result = preview_structure_change(
        db, calc, feature_ids=[str(f.units["B1"])], new_geometry=mapping(b1_geom)
    )
    assert result["trees"] == {"at_risk": 2, "stays": 2, "moves": 0, "unassigned": 0}
    assert result["plots"] == {"at_risk": 1, "stays": 1, "moves": 0, "unassigned": 0}
    # B2's tree was never at risk -- B2 was not in feature_ids.
    assert result["sampling_designs_affected"] == 1  # F10 seeds one
    assert result["stale_domains"] == ["analysis", "sampling", "field_inventory"]


def test_a_shrunk_new_geometry_splits_stays_and_unassigned(db, make_forest):
    f = make_forest("F10")
    calc = _calc(db, f)
    reassign_after_structure_change(db, calc)
    db.flush()

    # Covers only the first tree's point (2,3), not the second tree (4,5) or
    # the plot (3,4) -- clearly outside this box's corner, not touching it --
    # B2 doesn't reach this x-range either, so neither falls back onto
    # another existing unit.
    tiny = rect(1.5, 2.5, 2.5, 3.5)
    result = preview_structure_change(
        db, calc, feature_ids=[str(f.units["B1"])], new_geometry=mapping(tiny)
    )
    assert result["trees"] == {"at_risk": 2, "stays": 1, "moves": 0, "unassigned": 1}
    assert result["plots"] == {"at_risk": 1, "stays": 0, "moves": 0, "unassigned": 1}


def test_no_new_geometry_reports_unassigned_when_nothing_else_covers_the_point(db, make_forest):
    f = make_forest("F10")
    calc = _calc(db, f)
    reassign_after_structure_change(db, calc)
    db.flush()

    # No new_geometry at all -- as if B1 were simply deleted/merged away.
    # B2 doesn't reach B1's territory, so nothing picks these up.
    result = preview_structure_change(db, calc, feature_ids=[str(f.units["B1"])])
    assert result["trees"] == {"at_risk": 2, "stays": 0, "moves": 0, "unassigned": 2}
    assert result["plots"] == {"at_risk": 1, "stays": 0, "moves": 0, "unassigned": 1}


def test_no_new_geometry_reports_moves_when_another_unit_already_covers_the_point(db):
    """A custom scenario (F10's B1/B2 are disjoint, no case there ever
    resolves to `moves`): two OVERLAPPING top-level blocks, a tree in the
    overlap. Removing the first (no new_geometry) picks the tree up under
    the second, still-existing block -- `moves`, not `unassigned`."""
    user = User(email=f"sip-{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", full_name="SIP")
    db.add(user)
    db.flush()

    from geoalchemy2.shape import from_shape
    from app.services.geometry_edit_service import area_sqm

    outer = rect(0, 0, 20, 10)
    a_geom = rect(0, 0, 12, 10)   # west-leaning block
    b_geom = rect(8, 0, 20, 10)   # east-leaning block, overlaps A in x=[8,12]

    calc = Calculation(
        id=uuid.uuid4(), user_id=user.id, forest_name="SIP Overlap CF",
        boundary_geom=from_shape(outer, srid=4326),
        status="processing", is_draft=True,
    )
    db.add(calc)
    db.flush()
    block_a = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="A", block_name="A",
        geometry=from_shape(a_geom, srid=4326),
        area_hectares=round(area_sqm(a_geom) / 10000.0, 4), area_sqm=round(area_sqm(a_geom), 2),
        index=0, division_level=1,
    )
    block_b = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="B", block_name="B",
        geometry=from_shape(b_geom, srid=4326),
        area_hectares=round(area_sqm(b_geom) / 10000.0, 4), area_sqm=round(area_sqm(b_geom), 2),
        index=1, division_level=1,
    )
    db.add_all([block_a, block_b])
    db.flush()

    inv = InventoryCalculation(
        user_id=user.id, calculation_id=calc.id, uploaded_filename="trees.csv", status="completed",
    )
    db.add(inv)
    db.flush()
    # A point in the A/B overlap, x=10 (0.01 deg from X0).
    db.execute(
        text(
            "INSERT INTO public.inventory_trees (id, inventory_calculation_id, species, dia_cm, location, unit_id) "
            "VALUES (:id, :inv, 'Shorea robusta', 25.0, ST_GeomFromText(:loc, 4326), :unit)"
        ),
        {"id": str(uuid.uuid4()), "inv": str(inv.id), "loc": f"POINT({X0 + 0.010} {Y0 + 0.005})", "unit": str(block_a.id)},
    )
    db.commit()

    result = preview_structure_change(db, calc, feature_ids=[str(block_a.id)])
    assert result["trees"] == {"at_risk": 1, "stays": 0, "moves": 1, "unassigned": 0}


def test_no_sampling_design_reports_zero(db, make_forest):
    f = make_forest("F1")  # no downstream data
    calc = _calc(db, f)
    assert db.query(SamplingDesign).filter(SamplingDesign.calculation_id == calc.id).count() == 0
    result = preview_structure_change(db, calc, feature_ids=[])
    assert result["sampling_designs_affected"] == 0
