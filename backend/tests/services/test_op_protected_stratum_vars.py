"""OP field-inventory data exposes the protection stratum (design item #1, increment 3).

`get_field_inventory_data` now surfaces the protection-stratum growing stock
(recorded on the block summary by increment 2) as its own variables, clearly
marked as excluded from the Annual Allowable Harvest. The MAI / AAH tables
themselves are unchanged — they already read the productive-only growing
stock.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.calculation import Calculation
from app.models.field_inventory import FieldInventoryCalculation, FieldInventoryBlockSummary
from app.models.user import User
from app.services.operational_plan.data_collector import get_field_inventory_data


@pytest.fixture()
def owner(db):
    u = User(
        email=f"opstratum-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="h", full_name="OP Stratum",
    )
    db.add(u)
    db.flush()
    return u


def _seed(db, owner, summaries):
    calc = Calculation(user_id=owner.id, forest_name="Stratum CF")
    db.add(calc)
    db.flush()
    fi = FieldInventoryCalculation(
        user_id=owner.id, calculation_id=calc.id,
        uploaded_filename="fi.csv", status="completed",
        total_sample_plots=sum(s["total_sample_plots"] for s in summaries),
        total_blocks=len(summaries),
    )
    db.add(fi)
    db.flush()
    for s in summaries:
        db.add(FieldInventoryBlockSummary(
            field_inventory_calculation_id=fi.id,
            block_name=s["block_name"],
            total_sample_plots=s["total_sample_plots"],
            total_growing_stock_m3_per_ha=s["gs"],
            protected_growing_stock_m3_per_ha=s.get("prot_gs"),
            protected_sample_plots=s.get("prot_plots"),
            forest_condition="Moderate",
            mai_percent=3.0,
        ))
    db.commit()
    return calc


def test_protection_stratum_surfaced_and_excluded_from_aah(db, owner):
    calc = _seed(db, owner, [
        {"block_name": "B1", "total_sample_plots": 4, "gs": 80.0, "prot_gs": 200.0, "prot_plots": 1},
        {"block_name": "B2", "total_sample_plots": 6, "gs": 120.0, "prot_gs": 150.0, "prot_plots": 3},
    ])

    out = get_field_inventory_data(db, str(calc.id))
    assert out["available"] is True

    assert out["fi_has_protected_stratum"] is True
    assert out["fi_protected_sample_plots"] == 4  # 1 + 3
    # weighted by protected plot count: (200*1 + 150*3) / 4 = 162.5
    assert out["fi_protected_growing_stock_m3_per_ha"] == pytest.approx(162.5, abs=1e-2)
    assert "कटान" in out["fi_protected_stratum_note"]  # names the AAH exclusion

    table = out["fi_protected_stratum_table"]
    assert [r["block_name"] for r in table] == ["B1", "B2", "जम्मा (भारित)"]
    assert table[-1]["protected_sample_plots"] == 4

    # MAI/AAH still computed from the productive growing stock, untouched.
    aah = out["fi_aah_table"]
    assert aah and all("protected" not in k for row in aah for k in row)


def test_no_protection_stratum_defaults_are_clean(db, owner):
    calc = _seed(db, owner, [
        {"block_name": "B1", "total_sample_plots": 5, "gs": 90.0},
    ])
    out = get_field_inventory_data(db, str(calc.id))
    assert out["fi_has_protected_stratum"] is False
    assert out["fi_protected_sample_plots"] == 0
    assert out["fi_protected_growing_stock_m3_per_ha"] == 0
    assert out["fi_protected_stratum_note"] == ""
    assert out["fi_protected_stratum_table"] == []
