"""FS-1b.4 - a representative writer from each category actually goes through the funnel (not just
imports it). Full parity across every operation is FS-4a.22 (P4a); this is the P1b routing check: does
`structure_write` really run and really mark `structure_stale` / bump the clock for these real functions."""

from __future__ import annotations

from app.models.calculation import Calculation, CalculationStatus
from app.services import protection_unit_service


def _calc(db, forest):
    return db.query(Calculation).filter(Calculation.id == forest.calc_id).first()


def test_promote_and_demote_protection_unit_go_through_the_funnel(make_forest, db):
    """protection_unit_service (a writer that never called bump/reconcile via structure_write before P1b).

    F1 holds no downstream data, so the calculation is marked COMPLETED here to give the
    `analysis` domain something real to be stale about — the funnel's stale-mark is now scoped
    to domains that have data (owner 2026-09-29).
    """
    f = make_forest("F1")
    calc = _calc(db, f)
    calc.status = CalculationStatus.COMPLETED
    rd = dict(calc.result_data)
    sub_area = {
        "id": "sa-1",
        "category": "protected",
        "geometry": {
            "type": "Polygon",
            "coordinates": [list(f.unit_geoms["B1"].buffer(-0.001).exterior.coords)],
        },
        "area_hectares": 1.0,
    }
    rd["sub_areas"] = [sub_area]
    calc.result_data = rd
    db.flush()
    before_version = calc.geometry_version or 0

    result = protection_unit_service.promote_subarea_to_unit(db, calc, "sa-1")
    db.commit()

    assert calc.geometry_version == before_version + 1
    assert calc.result_data["structure_stale"]["analysis"] is True
    assert "promote" in calc.result_data["structure_stale"]["change"]
    assert any(b["name"] == result["name"] for b in calc.result_data["blocks"])

    before_version2 = calc.geometry_version
    protection_unit_service.demote_unit_to_subarea(db, calc, result["unit_id"])
    db.commit()

    assert calc.geometry_version == before_version2 + 1
    assert "demote" in calc.result_data["structure_stale"]["change"]
    assert not any(b["name"] == result["name"] for b in calc.result_data["blocks"])
