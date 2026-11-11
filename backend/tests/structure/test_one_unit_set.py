"""FS-1a.16 - every subsystem answers "which units does this forest have?" with the SAME set.

The leaf view of ``forest_units`` (units not divided further; together they cover the forest once) is the one
answer. Before P1a, six subsystems chose six ways and disagreed on any forest that had been divided at mixed depth
or that used compartments: analysis dropped units, sampling counted ground twice, the plan collector returned
nothing, and so on. This test asks each subsystem about the same forests and requires the same names - and that
their areas add up to the forest.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.models.calculation import Calculation
from app.services import demand_supply_service, fieldbook, sampling
from app.services.analysis_polygon_source import PolygonSource
from app.services.block_reconcile_service import (
    reconcile_blocks_from_db,
    reconcile_compartments_from_db,
)
from app.services.field_inventory_dfo_export import _fetch_block_areas as dfo_areas
from app.services.field_inventory_mgmt_data import _fetch_block_areas as mgmt_areas
from app.services.forest_units import queries as fu
from app.services.management_plan_docx import plan_map_service as pms
from app.services.operational_plan import plan_collector
from app.services.report import data_collector as report_dc
from app.services.sustainable_fm.sfm_service import _leaf_units
from app.services.tree_distribution import assign_block_names_to_trees

# Forests whose units tile the boundary (F5 is the legacy mixed forest; A4: it returns the whole leaf view).
KEYS = ["F1", "F2", "F3", "F4", "F5", "F8", "F12", "F13"]


def _outer_ha(db, forest):
    return float(
        db.execute(
            text(
                "SELECT ST_Area(boundary_geom::geography)/10000.0 FROM calculations WHERE id=:c"
            ),
            {"c": str(forest.calc_id)},
        ).scalar()
    )


@pytest.fixture()
def forest_and_calc(make_forest, db):
    def _make(key):
        f = make_forest(key)
        calc = db.query(Calculation).filter(Calculation.id == f.calc_id).first()
        reconcile_blocks_from_db(db, calc)
        reconcile_compartments_from_db(db, calc)
        db.commit()
        return f, calc

    return _make


@pytest.mark.parametrize("key", KEYS)
def test_every_subsystem_sees_the_same_leaf_units(forest_and_calc, db, key):
    f, calc = forest_and_calc(key)
    expected = sorted(f.expect["leaf"])

    seen = {
        "units module": [u.name for u in fu.units(db, f.calc_id, fu.View.LEAF)],
        "analysis": [
            p["name"]
            for p in PolygonSource.for_result_data(calc.result_data).get_polygons()
        ],
        "sampling": [
            u[2] for u in sampling.extract_blocks_from_calculation(db, f.calc_id)
        ],
        "sfm": [u.name for u in _leaf_units(calc, db)],
        "plan collector": [
            v["name"] for v in plan_collector._block_index(db, f.calc_id).values()
        ],
        "zonal / thematic maps": [
            u["name"] for u in pms._get_leaf_units_with_geometry(db, f.calc_id)
        ],
        "demand / supply": list(
            demand_supply_service._fetch_block_areas(db, f.calc_id)
        ),
        "field inventory (mgmt)": list(mgmt_areas(db, f.calc_id)),
        "field inventory (DFO)": list(dfo_areas(db, f.calc_id)),
        "report data": [
            b["name"] for b in report_dc.get_block_data(db, f.calc_id)["blocks"]
        ],
        "report boundary": [
            b["name"] for b in report_dc.get_boundary_info(db, f.calc_id)["blocks"]
        ],
    }
    for who, names in seen.items():
        assert (
            sorted(names) == expected
        ), f"{key}: {who} sees {sorted(names)}, expected {expected}"


@pytest.mark.parametrize("key", KEYS)
def test_the_units_add_up_to_the_forest(forest_and_calc, db, key):
    f, _ = forest_and_calc(key)
    outer = _outer_ha(db, f)
    for who, total in {
        "sampling": sum(
            u[3] for u in sampling.extract_blocks_from_calculation(db, f.calc_id)
        ),
        "demand / supply": sum(
            demand_supply_service._fetch_block_areas(db, f.calc_id).values()
        ),
        "field inventory (mgmt)": sum(mgmt_areas(db, f.calc_id).values()),
        "units module": sum(u.area_ha for u in fu.units(db, f.calc_id, fu.View.LEAF)),
    }.items():
        assert total == pytest.approx(
            outer, rel=0.01
        ), f"{key}: {who} covers {total:.1f} ha of {outer:.1f}"


def test_a_tree_lands_in_the_smallest_unit_that_holds_it(forest_and_calc, db):
    """F4: C1 is divided into SC1/SC2. A tree inside SC2 belongs to SC2, not to its parent C1."""
    from app.services.forest_units import queries

    f, calc = forest_and_calc("F4")
    sc2 = f.unit_geoms["SC2"].representative_point()
    trees = assign_block_names_to_trees(
        [{"geometry": (sc2.x, sc2.y)}],
        calc.result_data,
        db=db,
        calculation_id=f.calc_id,
    )
    assert trees[0]["block_name"] == "SC2"
    assert queries.children_of(db, f.units["C1"])  # sanity: C1 really is divided


def test_fieldbook_unit_type_comes_from_the_stream(forest_and_calc, db):
    f, _ = forest_and_calc("F13")
    resp = fieldbook.generate_fieldbook_points(
        db, f.calc_id, interpolation_distance=0, extract_elevation=False
    )
    assert resp.unit_type == "compartment" and resp.unit_count == 1
