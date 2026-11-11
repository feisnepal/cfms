"""FS-1a.3 - analysis runs on the leaf view (every unit that is not divided further)."""

from __future__ import annotations

from app.models.calculation import Calculation
from app.services.analysis_polygon_source import PolygonSource
from app.services.block_reconcile_service import reconcile_compartments_from_db


def _names(db, forest):
    calc = db.query(Calculation).filter(Calculation.id == forest.calc_id).first()
    reconcile_compartments_from_db(db, calc)
    return calc, [
        p["name"]
        for p in PolygonSource.for_result_data(calc.result_data).get_polygons()
    ]


def test_undivided_compartment_is_analysed_beside_a_divided_one(make_forest, db):
    """F4: C1 divided into SC1/SC2, C2 not. The old 'deepest level only' rule analysed SC1/SC2 and lost C2."""
    _, names = _names(db, make_forest("F4"))
    assert sorted(names) == ["C2", "SC1", "SC2"]


def test_legacy_mixed_forest_loses_nothing(make_forest, db):
    """F5: block B1 divided into C1/C2 plus a plain block B2 - the whole leaf view, nothing dropped."""
    _, names = _names(db, make_forest("F5"))
    assert sorted(names) == ["B2", "C1", "C2"]


def test_a_flat_compartment_forest_is_unchanged(make_forest, db):
    _, names = _names(db, make_forest("F2"))
    assert names == ["C1", "C2", "C3"]


def test_a_forest_that_is_one_compartment_is_analysed_as_that_compartment(
    make_forest, db
):
    _, names = _names(db, make_forest("F13"))
    assert names == ["C1"]


def test_the_leaf_areas_cover_the_boundary_once(make_forest, db):
    f = make_forest("F4")
    calc, _ = _names(db, f)
    total = sum(c["area_hectares"] for c in calc.result_data["compartments"])
    outer = db.execute(
        __import__("sqlalchemy").text(
            "SELECT ST_Area(boundary_geom::geography)/10000.0 FROM calculations WHERE id=:c"
        ),
        {"c": str(f.calc_id)},
    ).scalar()
    assert abs(total - outer) / outer < 0.005


def test_reconcile_is_idempotent(make_forest, db):
    f = make_forest("F4")
    calc, _ = _names(db, f)
    assert reconcile_compartments_from_db(db, calc) is False
