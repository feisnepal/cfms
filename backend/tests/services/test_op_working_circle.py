"""OP data collector — a protection working-circle unit is out of AAH.

PROTECTION_WORKING_CIRCLE_PLAN.md P1. A `working_circle='protection'` unit
keeps a full field-inventory summary (growing stock, condition) but:
  - its MAI / AAH are 0 and it is absent from fi_mai_table / fi_aah_table;
  - it is out of the production weighted grand total and ti_total_aah;
  - its growing stock is reported via fi_protection_units + the protection
    totals, never as harvestable stock.

`_fetch_block_effective_areas` is stubbed per test so the ESA raster path
(which the toy geometries can't satisfy) is not exercised.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.calculation import Calculation
from app.models.field_inventory import FieldInventoryCalculation, FieldInventoryBlockSummary
from app.models.user import User
from app.services.operational_plan import data_collector as dc


@pytest.fixture()
def owner(db):
    u = User(email=f"wc-op-{uuid.uuid4().hex[:10]}@example.com", hashed_password="h", full_name="WC OP")
    db.add(u)
    db.flush()
    return u


def _seed(db, monkeypatch, owner, units):
    """units: [{name, plots, gs, wc, area}] -> calc.result_data['blocks'] with
    working_circle + matching FieldInventoryBlockSummary rows. Stubs the area
    fetchers to exactly the seeded units (no raster)."""
    areas = {u["name"]: u.get("area", 10.0) for u in units}
    monkeypatch.setattr(dc, "_fetch_block_effective_areas", lambda db, cid: dict(areas))
    monkeypatch.setattr(dc, "_fetch_block_protected_areas", lambda db, cid: {})
    monkeypatch.setattr(dc, "_fetch_species_block_breakdown", lambda db, fid, ba: [])

    calc = Calculation(
        user_id=owner.id, forest_name="WC OP CF",
        result_data={
            "blocks": [
                {"block_id": u["name"], "block_name": u["name"],
                 "area_hectares": u.get("area", 10.0),
                 "working_circle": u.get("wc", "production")}
                for u in units
            ],
        },
    )
    db.add(calc)
    db.flush()
    fi = FieldInventoryCalculation(
        user_id=owner.id, calculation_id=calc.id, uploaded_filename="fi.csv",
        status="completed", total_sample_plots=sum(u["plots"] for u in units),
        total_blocks=len(units),
    )
    db.add(fi)
    db.flush()
    for u in units:
        db.add(FieldInventoryBlockSummary(
            field_inventory_calculation_id=fi.id, block_name=u["name"],
            total_sample_plots=u["plots"], total_growing_stock_m3_per_ha=u["gs"],
            forest_condition="Moderate", regeneration_condition="Moderate", mai_percent=3.0,
        ))
    db.commit()
    return calc


def test_protection_unit_excluded_from_mai_aah_and_grand_total(db, monkeypatch, owner):
    calc = _seed(db, monkeypatch, owner, [
        {"name": "C1", "plots": 5, "gs": 100.0, "wc": "production"},
        {"name": "C2", "plots": 5, "gs": 120.0, "wc": "production"},
        {"name": "P1", "plots": 3, "gs": 90.0, "wc": "protection"},
    ])
    out = dc.get_field_inventory_data(db, str(calc.id))

    rows = {r["block_name"]: r for r in out["fi_block_summaries"]
            if r.get("block_name") and r["block_name"] != "Grand Total (Weighted)"}
    assert rows["P1"]["working_circle"] == "protection"
    assert rows["P1"]["mai_total_m3_per_ha"] == 0
    assert rows["P1"]["aah_total_m3_per_ha"] == 0
    assert rows["P1"]["total_growing_stock_m3_per_ha"] == 90.0   # real stock kept
    assert rows["P1"]["forest_condition"] == "Moderate"          # real condition kept
    assert rows["C1"]["working_circle"] == "production"
    assert rows["C1"]["aah_total_m3_per_ha"] > 0

    assert {r["block_name"] for r in out["fi_mai_table"]} == {"C1", "C2", "Grand Total (Weighted)"}
    assert "P1" not in {r["block_name"] for r in out["fi_aah_table"]}

    # weighted grand growing stock over production only: (100*5 + 120*5)/10 = 110
    assert out["fi_growing_stock_m3_per_ha"] == pytest.approx(110.0, abs=1e-2)

    assert out["fi_has_protected_stratum"] is True
    pu = {u["unit_name"]: u for u in out["fi_protection_units"]}
    assert pu["P1"]["growing_stock_m3_per_ha"] == 90.0
    assert pu["P1"]["sample_plots"] == 3
    assert "P1" in {r["block_name"] for r in out["fi_protected_stratum_table"]}


def test_ti_totals_are_production_only(db, monkeypatch, owner):
    calc = _seed(db, monkeypatch, owner, [
        {"name": "C1", "plots": 5, "gs": 100.0, "wc": "production", "area": 10.0},
        {"name": "P1", "plots": 2, "gs": 80.0, "wc": "protection", "area": 5.0},
    ])
    fi = dc.get_field_inventory_data(db, str(calc.id))
    ti = dc._compute_total_inventory(fi)

    assert ti["ti_available"] is True
    assert ti["ti_production_area_ha"] == pytest.approx(10.0, abs=1e-3)
    assert ti["ti_protection_working_circle_area_ha"] == pytest.approx(5.0, abs=1e-3)
    assert ti["ti_effective_area_ha"] == pytest.approx(15.0, abs=1e-3)
    # growing stock total over production only: fi_growing_stock (100) × 10 ha
    assert ti["ti_total_growing_stock_m3"] == pytest.approx(1000.0, abs=1e-1)
    assert ti["ti_total_aah_m3_per_year"] > 0
    # protection stock reported on its own: 80 m³/ha × 5 ha = 400
    assert ti["ti_protected_growing_stock_m3"] == pytest.approx(400.0, abs=1e-1)
