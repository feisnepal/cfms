"""reconcile_compartments_from_db — stale-snapshot clearing.

When a forest was divided into compartments in the workspace and those
compartments were later deleted, ``result_data['compartments']`` could linger.
``PolygonSource.for_result_data`` picks compartment mode purely from that array
being non-empty, so analysis kept running per-(deleted-)compartment. The
reconcile now clears the stale array for a workspace-managed forest, while a
pure upload-mode snapshot (no ``forest_blocks`` rows) is preserved.
"""

import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.services.block_reconcile_service import reconcile_compartments_from_db


@pytest.fixture()
def owner(db):
    user = User(
        email=f"comprec-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Compartment Reconcile Fixture",
    )
    db.add(user)
    db.flush()
    return user


def _calc(db, owner, result_data, *, blocks_cleared=False):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=owner.id,
        forest_name="Compartment Reconcile Forest",
        boundary_geom=shp_wkt.dumps(box(2, 2, 6, 6)),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
        result_data=result_data,
        blocks_cleared_by_user=blocks_cleared,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _block(db, calc, name, index, *, is_compartment=False, division_level=1):
    row = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        geometry=shp_wkt.dumps(box(2 + index, 2, 3 + index, 4)),
        area_hectares=1.0,
        index=index,
        is_compartment=is_compartment,
        division_level=division_level,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


_STALE = {
    "blocks": [{"block_name": "blocks-1", "id": "b1"}],
    "compartments": [
        {"compartment_code": "C1", "id": "c1"},
        {"compartment_code": "C2", "id": "c2"},
    ],
    "total_compartments": 2,
    "polygon_type": "compartment",
}


def test_stale_compartments_cleared_when_block_rows_exist(db, owner):
    calc = _calc(db, owner, dict(_STALE))
    _block(db, calc, "blocks-1", 0)  # a real block row, no compartment rows

    changed = reconcile_compartments_from_db(db, calc)

    assert changed is True
    assert calc.result_data["compartments"] == []
    assert calc.result_data["total_compartments"] == 0
    assert calc.result_data["polygon_type"] == "block"


def test_stale_compartments_cleared_when_blocks_cleared_by_user(db, owner):
    calc = _calc(
        db, owner, dict(_STALE), blocks_cleared=True
    )  # no forest_blocks rows at all

    changed = reconcile_compartments_from_db(db, calc)

    assert changed is True
    assert calc.result_data["compartments"] == []
    assert calc.result_data["polygon_type"] == "block"


def test_pure_upload_mode_snapshot_is_preserved(db, owner):
    calc = _calc(db, owner, dict(_STALE))  # no forest_blocks rows, not user-cleared

    changed = reconcile_compartments_from_db(db, calc)

    assert changed is False
    assert [c["compartment_code"] for c in calc.result_data["compartments"]] == [
        "C1",
        "C2",
    ]
    assert calc.result_data["polygon_type"] == "compartment"


def test_noop_when_no_compartments_and_not_compartment_mode(db, owner):
    calc = _calc(db, owner, {"blocks": [{"block_name": "blocks-1"}]})
    _block(db, calc, "blocks-1", 0)

    assert reconcile_compartments_from_db(db, calc) is False


def test_real_compartment_rows_still_rebuild(db, owner):
    calc = _calc(db, owner, {"blocks": [], "compartments": []})
    _block(db, calc, "C1", 0, is_compartment=True, division_level=1)
    _block(db, calc, "C2", 1, is_compartment=True, division_level=1)

    changed = reconcile_compartments_from_db(db, calc)

    assert changed is True
    assert [c["name"] for c in calc.result_data["compartments"]] == ["C1", "C2"]
    assert calc.result_data["polygon_type"] == "compartment"
