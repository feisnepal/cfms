"""Branch coverage for `process_inventory_simple` pipeline (H4.2).

The pipeline's post-store lines (capturing `row_errors`, logging the store
result, and persisting `row_errors` on the inventory record) never ran. Driving
the real end-to-end flow with GDAL/PostGIS would be heavy, so the leaf services
are stubbed while the genuine orchestration code runs against a small dataframe.
"""
from __future__ import annotations

import asyncio
import uuid

import pandas as pd

from app.models.calculation import Calculation
from app.models.inventory import InventoryCalculation
from app.services.inventory import InventoryService


def _seed(db):
    from app.models.user import User

    user = User(
        email=f"inv-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Inv Tester",
    )
    db.add(user)
    db.flush()
    c = Calculation(user_id=user.id, forest_name=f"Inv CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.flush()
    inv = InventoryCalculation(
        user_id=user.id, calculation_id=c.id,
        uploaded_filename="trees.csv", status="queued",
    )
    db.add(inv)
    db.commit()
    return c, inv


def _df():
    return pd.DataFrame({
        "species": ["Shorea robusta", "Shorea robusta"],
        "dia_cm": [12.0, 25.0],
        "height_m": [10.0, 15.0],
        "longitude": [81.0, 81.5],
        "latitude": [28.0, 28.2],
    })


def test_process_inventory_simple_captures_row_errors(db, monkeypatch):
    _c, inv = _seed(db)
    svc = InventoryService(db)

    async def fake_convert(self, df, *a, **k):
        return df

    async def fake_store(self, *a, **k):
        return {"row_errors": ["bad row"], "inserted_count": 1}

    async def fake_count(self, *a, **k):
        return 0

    async def fake_summary(self, *a, **k):
        return {k: 0 for k in (
            "total_trees", "mother_trees_count", "felling_trees_count",
            "seedling_count", "total_volume_m3", "total_net_volume_m3",
            "total_net_volume_cft", "total_firewood_m3", "total_firewood_chatta")}

    monkeypatch.setattr(InventoryService, "_convert_species_to_scientific", fake_convert)
    monkeypatch.setattr(InventoryService, "calculate_tree_volumes",
                        lambda self, df, *a, **k: df)
    monkeypatch.setattr(InventoryService, "_store_trees_simple", fake_store)
    monkeypatch.setattr(InventoryService, "_identify_mother_trees_postgis", fake_count)
    monkeypatch.setattr(InventoryService, "_update_tree_spatial_relationships", fake_count)
    monkeypatch.setattr(InventoryService, "_calculate_summary_from_db", fake_summary)

    from app.services.optimistic_lock import check_and_bump
    check_and_bump(db, "inventory", inv.id, 0)

    summary = asyncio.run(svc.process_inventory_simple(inv.id, _df()))
    assert summary["total_trees"] == 0

    db.refresh(inv)
    assert inv.row_errors == ["bad row"]
    assert inv.status == "completed"
