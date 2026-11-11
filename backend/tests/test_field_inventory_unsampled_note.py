"""P8 - the field-inventory note that names the unsampled units.

This is the surface where most users meet the defect: they open the inventory,
count 21 blocks where the forest has 24, and nothing explains the gap. The
tests pin that the note NAMES the units, because a bare count is what the
feature exists to replace.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.field_inventory import (
    FieldInventoryBlockSummary,
    FieldInventoryCalculation,
)
from app.models.forest_block import ForestBlock
from app.models.user import User, UserStatus

M_LAT, M_LON = 110_900.0, 98_000.0
LON0, LAT0 = 84.0, 28.5


def _m_box(x, y, w, h):
    return box(
        LON0 + x / M_LON,
        LAT0 + y / M_LAT,
        LON0 + (x + w) / M_LON,
        LAT0 + (y + h) / M_LAT,
    )


# Two sound 2 ha units, and three sub-MMU slivers that were never sampled - the
# shape of the real b67f9e1c case (21 summarised of 24 leaf units).
UNITS = [
    ("BIG-1", _m_box(0, 0, 200, 100), 2.0, True),
    ("BIG-2", _m_box(200, 0, 200, 100), 2.0, True),
    ("SLIVER-A", _m_box(200, 100, 18, 10), 0.018, False),
    ("SLIVER-B", _m_box(220, 100, 10, 6), 0.006, False),
    ("SLIVER-C", _m_box(240, 100, 12, 8), 0.0096, False),
]


@pytest.fixture
def inventory(db, auth_headers):
    from app.models.user import User as U

    owner = db.query(U).filter(U.email == "testuser@example.com").first()
    assert owner is not None

    calc = Calculation(
        id=uuid.uuid4(),
        user_id=owner.id,
        forest_name="P8 note fixture",
        result_data={"area_hectares": 4.03},
    )
    db.add(calc)
    db.flush()
    fi = FieldInventoryCalculation(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        user_id=owner.id,
        uploaded_filename="p8-note-fixture.csv",
        status="completed",
    )
    db.add(fi)
    db.flush()
    for i, (name, geom, area, sampled) in enumerate(UNITS):
        db.add(
            ForestBlock(
                id=uuid.uuid4(),
                calculation_id=calc.id,
                name=name,
                block_name=name,
                geometry=from_shape(geom, srid=4326),
                area_hectares=area,
                index=i,
                is_compartment=False,
                division_level=1,
            )
        )
        if sampled:
            db.add(
                FieldInventoryBlockSummary(
                    id=uuid.uuid4(),
                    field_inventory_calculation_id=fi.id,
                    block_name=name,
                    total_sample_plots=5,
                )
            )
    db.commit()
    try:
        yield fi
    finally:
        db.query(Calculation).filter(Calculation.id == calc.id).delete(
            synchronize_session=False
        )
        db.commit()


def _get(client, fi, **params):
    resp = client.get(
        f"/api/field-inventory/{fi.id}/unsampled-units",
        headers=params.pop("headers"),
        params=params or None,
    )
    return resp


def test_note_names_every_unsampled_unit(client, inventory, auth_headers):
    resp = _get(client, inventory, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["read_only"] is True
    assert body["total_units"] == 5
    assert body["summarised_units"] == 2
    names = sorted(u["block_name"] for u in body["unsampled_units"])
    assert names == ["SLIVER-A", "SLIVER-B", "SLIVER-C"], (
        "the note must NAME the units - a bare count is what this replaces"
    )


def test_summarised_units_are_not_listed(client, inventory, auth_headers):
    body = _get(client, inventory, headers=auth_headers).json()
    assert "BIG-1" not in [u["block_name"] for u in body["unsampled_units"]]
    assert "BIG-2" not in [u["block_name"] for u in body["unsampled_units"]]


def test_each_named_unit_carries_a_reason(client, inventory, auth_headers):
    body = _get(client, inventory, headers=auth_headers).json()
    for unit in body["unsampled_units"]:
        assert unit["band"] == "sub_mmu"
        assert unit["reason"], "a named unit without a reason is just a name"
        assert "MMU" in unit["reason"]


def test_summary_counts_add_up(client, inventory, auth_headers):
    body = _get(client, inventory, headers=auth_headers).json()
    s = body["summary"]
    assert s["total"] == 3
    assert s["sub_mmu"] == 3
    assert s["total"] == s["sub_mmu"] + s["review"] + s["ok"]


def test_the_two_surfaces_agree_on_bands(client, inventory, auth_headers):
    """The note and the sampling review must not disagree about a unit."""
    note = _get(client, inventory, headers=auth_headers).json()
    note_bands = {u["block_name"]: u["band"] for u in note["unsampled_units"]}

    review = client.get(
        f"/api/v1/calculations/{inventory.calculation_id}/unit-size-review",
        headers=auth_headers,
    )
    assert review.status_code == 200, review.text
    review_bands = {c["block_name"]: c["band"] for c in review.json()["candidates"]}

    for name, band in note_bands.items():
        assert review_bands[name] == band, f"{name} is {band} here and {review_bands[name]} there"


def test_review_pct_is_overridable(client, inventory, auth_headers):
    resp = _get(client, inventory, headers=auth_headers, review_pct=90.0)
    assert resp.status_code == 200
    body = resp.json()
    # At 90% of 4.03 ha (3.63 ha) the 2 ha units are still 'ok', so the slivers
    # stay sub_mmu - but the boundary is honoured, and the value is echoed.
    assert body["review_pct"] == 90.0


def test_out_of_range_review_pct_is_rejected(client, inventory, auth_headers):
    assert _get(client, inventory, headers=auth_headers, review_pct=150.0).status_code == 422


def test_unknown_inventory_is_404(client, auth_headers):
    resp = client.get(
        f"/api/field-inventory/{uuid.uuid4()}/unsampled-units", headers=auth_headers
    )
    assert resp.status_code == 404


def test_the_endpoint_changes_nothing(client, db, inventory, auth_headers):
    """Read-only, asserted: two calls leave the inventory untouched."""
    summaries_before = db.query(FieldInventoryBlockSummary).filter(
        FieldInventoryBlockSummary.field_inventory_calculation_id == inventory.id
    ).count()
    for _ in range(2):
        assert _get(client, inventory, headers=auth_headers).status_code == 200
    assert (
        db.query(FieldInventoryBlockSummary)
        .filter(
            FieldInventoryBlockSummary.field_inventory_calculation_id == inventory.id
        )
        .count()
        == summaries_before
    )
    assert inventory.status == "completed"
