"""Specification of the area model ``app.services.forest_units.area_model`` (FS-3a1.1, built).

The owner's definitions (plan Appendix B, decisions D8 / C4 / C6'):

    outer boundary        the drawn boundary
    private land          NOT forest
    total forest area  =  outer boundary - private land
    protected forest   =  union of `protected` sub-areas and protection working-circle units,
                          counted ONCE, inside the total forest area
    effective area     =  tree-cover part of (total forest area - protected forest)

Today the word "effective area" means three different things (``result_data['effective_area_hectares']`` is
the TOTAL FOREST AREA; Table 5's ``effective_area_ha`` is the EFFECTIVE area; ``in_effective_area`` in
tiles is a point-in-net-geometry test). See plan Appendix D (the rename table).

Tree cover is passed in (``tree_cover_ratio``) because the test database has no ESA raster -
production reads the raster.
"""

from __future__ import annotations

import pytest


def _figures(db, forest, **kw):
    from app.services.forest_units.area_model import (
        area_figures,
    )  # noqa: F401 -- import IS the test

    from app.models.calculation import Calculation

    calc = db.query(Calculation).filter(Calculation.id == forest.calc_id).first()
    return area_figures(db, calc, **kw)


def test_hundred_ten_ninety_by_ratio(make_forest, db):
    f = make_forest("F9")
    a = _figures(db, f, tree_cover_ratio=f.expect["tree_cover_ratio"])
    r = f.expect["ratios"]
    assert a.private_ha / a.outer_ha == pytest.approx(r["private"], rel=0.01)
    assert a.total_forest_ha / a.outer_ha == pytest.approx(r["total_forest"], rel=0.01)
    assert a.protected_ha / a.outer_ha == pytest.approx(r["protected"], rel=0.01)
    assert a.effective_ha / a.outer_ha == pytest.approx(r["effective"], rel=0.01)


def test_protected_forest_counts_the_union_once(make_forest, db):
    """F8: protection unit P-1 (80 of 200 grid units) and protected sub-area PROT (48) overlap by 24 -> the union is
    104, not 128. Deducting both would double-count the overlap."""
    f = make_forest("F8")
    a = _figures(db, f, tree_cover_ratio=1.0)
    assert a.protected_ha / a.outer_ha == pytest.approx(104 / 200, rel=0.01)
    assert a.effective_ha / a.outer_ha == pytest.approx(1 - 104 / 200, rel=0.01)


def test_every_private_land_parcel_is_deducted(make_forest, db):
    """F7 (owner Q4, 2026-09-21): EVERY ``private_land`` sub-area leaves the forest area, whether or not it
    carries the ``isExcluded`` flag - PL_UNFLAGGED included. (Today the flag decides; FS-3.3 makes it one rule.)
    """
    f = make_forest("F7")
    a = _figures(db, f, tree_cover_ratio=1.0)
    from sqlalchemy import text

    subs = db.execute(
        text("SELECT result_data->'sub_areas' FROM calculations WHERE id = :c"),
        {"c": str(f.calc_id)},
    ).scalar()
    private_ha = sum(
        s["area_hectares"] for s in subs if s["category"] == "private_land"
    )
    assert any(
        not s["isExcluded"] for s in subs
    )  # sanity: PL_UNFLAGGED is unflagged and still counts
    assert a.private_ha == pytest.approx(private_ha, rel=0.01)
    assert a.total_forest_ha == pytest.approx(a.outer_ha - a.private_ha, rel=1e-6)


def test_shells(make_forest, db):
    """Two shells: the outer boundary, and the forest area (boundary - private land)."""
    from app.services.forest_units import area_model  # noqa: F401

    f = make_forest("F9")
    from app.models.calculation import Calculation

    calc = db.query(Calculation).filter(Calculation.id == f.calc_id).first()
    outer = area_model.outer_boundary_geom(calc)
    forest = area_model.forest_area_geom(calc)
    assert forest.area < outer.area
    assert forest.area / outer.area == pytest.approx(0.90, rel=0.01)
