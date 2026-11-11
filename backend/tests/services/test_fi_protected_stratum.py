"""_calculate_per_hectare keeps the protection stratum out of the block summary.

Design item #1, increment 2. The per-block growing stock that feeds forest
condition -> MAI -> Annual Allowable Harvest is built from PRODUCTIVE plots
only; protection-stratum plots (zone_type='protected') produce a
growing-stock-only figure recorded separately and never added to AAH.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.models.field_inventory import (
    FieldInventoryCalculation,
    FieldInventoryMeasurement,
    FieldInventorySamplePlot,
)
from app.models.user import User
from app.services.field_inventory_service import FieldInventoryService


@pytest.fixture()
def owner(db):
    user = User(
        email=f"fistratum-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="FI Stratum Fixture",
    )
    db.add(user)
    db.flush()
    return user


def _fi(db, owner):
    """A field inventory with the forest it belongs to (owner's rule, 2026-09-21; migration 092)."""
    from app.models.calculation import Calculation

    forest = Calculation(user_id=owner.id, forest_name=f"FI {uuid.uuid4().hex[:6]}")
    db.add(forest)
    db.flush()
    fi = FieldInventoryCalculation(
        user_id=owner.id, uploaded_filename="fi.csv", status="processing",
        calculation_id=forest.id,
    )
    db.add(fi)
    db.flush()
    return fi


def _plot(db, fi_id, number, zone_type, tree_net_volume):
    p = FieldInventorySamplePlot(
        field_inventory_calculation_id=fi_id,
        block_name="B1",
        sample_plot_number=number,
        location="SRID=4326;POINT(84.05 28.05)",
        zone_type=zone_type,
    )
    db.add(p)
    db.flush()
    db.add(
        FieldInventoryMeasurement(
            sample_plot_id=p.id,
            stand_type="Tree",
            sn=1,
            species_scientific="Shorea robusta",
            dbh_cm=30,
            height_m=18,
            count=1,
            net_volume=tree_net_volume,
            gross_volume=tree_net_volume,
            basal_area_m2=0.07,
            firewood_m3=0,
        )
    )
    db.flush()
    return p


def test_growing_stock_excludes_protected_plots_and_reports_them_separately(db, owner):
    fi = _fi(db, owner)

    # Two productive plots (Tree net vol 5 and 3 m³) + one protected plot (10 m³).
    # tree plot area defaults to 500 m² -> per-ha factor = 10000/500 = 20.
    _plot(db, fi.id, 1, None, 5.0)          # NULL zone_type -> productive
    _plot(db, fi.id, 2, "productive", 3.0)
    _plot(db, fi.id, 3, "protected", 10.0)

    service = FieldInventoryService(db)
    summaries = asyncio.run(service._calculate_per_hectare(fi.id, fi))

    assert len(summaries) == 1
    s = summaries[0]
    # productive: mean(5,3)=4 m³ over 500 m² -> 80 m³/ha
    assert float(s.total_growing_stock_m3_per_ha) == pytest.approx(80.0, abs=1e-3)
    assert s.total_sample_plots == 2
    # protected: 10 m³ over 500 m² -> 200 m³/ha, on 1 plot, reported on the side
    assert float(s.protected_growing_stock_m3_per_ha) == pytest.approx(200.0, abs=1e-3)
    assert s.protected_sample_plots == 1


def test_no_protected_plots_leaves_the_protected_columns_null(db, owner):
    fi = _fi(db, owner)
    _plot(db, fi.id, 1, None, 5.0)
    _plot(db, fi.id, 2, None, 5.0)

    service = FieldInventoryService(db)
    summaries = asyncio.run(service._calculate_per_hectare(fi.id, fi))

    s = summaries[0]
    assert float(s.total_growing_stock_m3_per_ha) == pytest.approx(100.0, abs=1e-3)
    assert s.protected_growing_stock_m3_per_ha is None
    assert s.protected_sample_plots is None


def test_dbh_class_breakdown_excludes_protected_plots(db, owner):
    fi = _fi(db, owner)
    # 2 productive Tree plots (5 m³ each) + 1 protected Tree plot (100 m³).
    _plot(db, fi.id, 1, None, 5.0)
    _plot(db, fi.id, 2, None, 5.0)
    _plot(db, fi.id, 3, "protected", 100.0)

    service = FieldInventoryService(db)
    summaries = asyncio.run(service._calculate_per_hectare(fi.id, fi))
    asyncio.run(service._calculate_dbh_class_breakdown(fi.id, fi, summaries))

    bd = summaries[0].dbh_class_breakdown
    tree_timber = sum(
        v["timber_m3_per_ha"] for v in bd.values() if v["timber_m3_per_ha"]
    )
    # productive only: mean(5,5)=5 m³ over 500 m² -> 100 m³/ha
    # (if the protected 100 m³ plot leaked in it would be ~733)
    assert tree_timber == pytest.approx(100.0, abs=1e-2)


def test_fully_protected_block_still_gets_a_summary_row(db, owner):
    fi = _fi(db, owner)
    _plot(db, fi.id, 1, "protected", 12.0)
    _plot(db, fi.id, 2, "protected", 8.0)

    service = FieldInventoryService(db)
    summaries = asyncio.run(service._calculate_per_hectare(fi.id, fi))

    assert len(summaries) == 1
    s = summaries[0]
    assert s.total_sample_plots == 0
    assert float(s.total_growing_stock_m3_per_ha) == pytest.approx(0.0, abs=1e-6)
    # mean(12,8)=10 m³ over 500 m² -> 200 m³/ha
    assert float(s.protected_growing_stock_m3_per_ha) == pytest.approx(200.0, abs=1e-3)
    assert s.protected_sample_plots == 2
