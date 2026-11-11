"""Branch coverage for report data_collector `get_inventory_data` (H4.2).

`get_inventory_data` accumulates per-block volume; the `net_volume` accessor
(the float-coercion line H6.2) never ran because no test seeded an
`InventoryTree` against an `InventoryCalculation` and called it.
"""
from __future__ import annotations

import uuid

from app.models.calculation import Calculation
from app.models.inventory import InventoryCalculation, InventoryTree
from app.models.user import User
from app.services.report.data_collector import get_inventory_data


def test_get_inventory_data_accumulates_tree_volume_by_block(db):
    owner = User(
        email=f"dc-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="h", full_name="DC",
    )
    db.add(owner)
    db.flush()

    calc = Calculation(user_id=owner.id, forest_name="DC CF")
    db.add(calc)
    db.flush()

    inv = InventoryCalculation(
        user_id=owner.id, calculation_id=calc.id,
        uploaded_filename="dc-probe.csv", status="validated",
    )
    db.add(inv)
    db.flush()

    for bn, vol in [("Block-1", 12.5), ("Block-1", 7.0), (None, 3.0)]:
        db.add(InventoryTree(
            inventory_calculation_id=inv.id,
            species=f"Shorea robusta {uuid.uuid4().hex[:4]}",
            dia_cm=30, location="SRID=4326;POINT(85.31 27.71)",
            block_name=bn, net_volume=vol,
        ))
    db.commit()

    out = get_inventory_data(db, str(calc.id))
    import json
    json.dumps(out, default=str)  # must not raise on Decimals
    assert out["available"] is True
    assert out["block_summary"]["Block-1"]["count"] == 2
    assert out["block_summary"]["Block-1"]["total_volume"] == 19.5
    assert out["block_summary"]["Unassigned"]["count"] == 1
