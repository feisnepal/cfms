"""Block reconciliation service tests (plan BA-1).

Covers `reconcile_blocks_from_db`: DB-authoritative blocks -> reconciled
`result_data.blocks`, preserving JSONB-only per-block keys, idempotency, and
legacy upload-mode fallthrough when no `forest_blocks` rows exist.
"""
import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.services.block_reconcile_service import reconcile_blocks_from_db
from app.services.auto_block_service import commit_blocks


def _uid(db):
    """Return the fixed auth_headers user's id (the shared ordinary user)."""
    u = db.query(User).filter(User.email == "testuser@example.com").first()
    return u.id


def _calc(db, blocks_jsonb=None):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=_uid(db),
        forest_name="Reconcile Forest",
        boundary_geom=shp_wkt.dumps(box(2, 2, 6, 6)),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
        result_data=blocks_jsonb,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _block(db, calc, name, index, area=1.0, geom=None, natural=None):
    block = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        geometry=shp_wkt.dumps(geom if geom is not None else box(2 + index, 2, 3 + index, 4)),
        area_hectares=area,
        index=index,
        natural_name=natural,
        division_level=1,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def _load(db, calc_id):
    db.expire_all()
    return db.query(Calculation).filter(Calculation.id == calc_id).first()


def test_reconciles_five_db_blocks_over_stale_single_jsonb(db, auth_headers):
    # Covers the reported defect: 5 forest_blocks rows, 1 stale JSONB block.
    stale = {
        "total_blocks": 1,
        "blocks": [{"block_index": 0, "block_name": "simpani", "area_hectares": 100.0, "geometry": {}}],
    }
    calc = _calc(db, stale)
    for i in range(1, 6):
        _block(db, calc, f"blocks-{i}", i, area=i * 10.0)

    changed = reconcile_blocks_from_db(db, calc)
    db.commit()

    assert changed is True
    refreshed = _load(db, calc.id)
    blocks = refreshed.result_data["blocks"]
    assert len(blocks) == 5
    assert refreshed.result_data["total_blocks"] == 5
    assert [b["block_name"] for b in blocks] == ["blocks-1", "blocks-2", "blocks-3", "blocks-4", "blocks-5"]
    assert [b["block_index"] for b in blocks] == [1, 2, 3, 4, 5]
    assert [b["area_hectares"] for b in blocks] == [10.0, 20.0, 30.0, 40.0, 50.0]
    # geometry was rebuilt from DB (non-empty), not the stale {}
    assert all(b.get("geometry") for b in blocks)


def test_preserves_jsonb_only_keys_by_id(db, auth_headers):
    stale = {
        "total_blocks": 1,
        "blocks": [{
            "block_id": "11111111-1111-1111-1111-111111111111",
            "block_name": "B1",
            "effective_area_hectares": 42.5,
            "excluded_area_hectares": 3.5,
            "is_fully_excluded": False,
        }],
    }
    calc = _calc(db, stale)
    row = _block(db, calc, "B1", 0, area=50.0,
                 geom=box(2, 2, 4, 4))

    # force the row id to match the JSONB block_id
    row.id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    db.add(row)
    db.commit()

    reconcile_blocks_from_db(db, calc)
    db.commit()

    refreshed = _load(db, calc.id)
    block = refreshed.result_data["blocks"][0]
    assert block["effective_area_hectares"] == 42.5
    assert block["excluded_area_hectares"] == 3.5
    assert block["is_fully_excluded"] is False
    assert block["area_hectares"] == 50.0  # fresh area kept


def test_matches_by_block_name_fallback(db, auth_headers):
    stale = {
        "total_blocks": 1,
        "blocks": [{"block_name": "B7", "effective_area_hectares": 9.9}],
    }
    calc = _calc(db, stale)
    _block(db, calc, "B7", 0, area=33.0)

    reconcile_blocks_from_db(db, calc)
    db.commit()

    refreshed = _load(db, calc.id)
    block = refreshed.result_data["blocks"][0]
    assert block["effective_area_hectares"] == 9.9
    assert block["area_hectares"] == 33.0


def test_no_db_rows_leaves_jsonb_untouched(db, auth_headers):
    stale = {"total_blocks": 1, "blocks": [{"block_name": "simp", "area_hectares": 12.0}]}
    calc = _calc(db, stale)

    changed = reconcile_blocks_from_db(db, calc)
    db.commit()

    assert changed is False
    refreshed = _load(db, calc.id)
    assert refreshed.result_data["blocks"][0]["block_name"] == "simp"


def test_idempotent_second_call_returns_false(db, auth_headers):
    calc = _calc(db, None)
    for i in range(3):
        _block(db, calc, f"B{i}", i)

    first = reconcile_blocks_from_db(db, calc)
    db.commit()
    second = reconcile_blocks_from_db(db, calc)
    db.commit()

    assert first is True
    assert second is False


def test_stale_geometry_not_overwritten(db, auth_headers):
    stale = {
        "total_blocks": 1,
        "blocks": [{
            "id": "22222222-2222-2222-2222-222222222222",
            "block_name": "BX",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]},
        }],
    }
    calc = _calc(db, stale)
    row = _block(db, calc, "BX", 0, geom=box(2, 2, 3, 3))
    row.id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    db.add(row)
    db.commit()

    reconcile_blocks_from_db(db, calc)
    db.commit()

    refreshed = _load(db, calc.id)
    from shapely.geometry import shape as shply
    geom = shply(refreshed.result_data["blocks"][0]["geometry"])
    assert geom.bounds[0] >= 1.9  # not the stale origin near 0,0


def test_get_calculation_returns_reconciled_five_blocks(client, db, auth_headers):
    # BA-2: the legacy GET endpoint must expose the DB-authoritative blocks even
    # when the JSONB snapshot is stale (1 block) -- the reported 1-vs-5 defect.
    stale = {
        "total_blocks": 1,
        "blocks": [{"block_index": 0, "block_name": "simpani", "area_hectares": 100.0, "geometry": {}}],
    }
    calc = _calc(db, stale)
    for i in range(1, 6):
        _block(db, calc, f"blocks-{i}", i, area=i * 10.0)

    # snapshot updated_at before the read-triggered reconciliation
    before = calc.updated_at

    resp = client.get(f"/api/forests/calculations/{calc.id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rd = body["result_data"]
    assert rd["total_blocks"] == 5
    assert len(rd["blocks"]) == 5
    assert [b["block_name"] for b in rd["blocks"]] == [
        "blocks-1", "blocks-2", "blocks-3", "blocks-4", "blocks-5",
    ]

    # idempotency: a second GET must not write (reconcile returned False) -> no
    # updated_at change from this request.
    db.expire_all()
    fresh = db.query(Calculation).filter(Calculation.id == calc.id).first()
    assert fresh.result_data["total_blocks"] == 5
    after = fresh.updated_at
    resp2 = client.get(f"/api/forests/calculations/{calc.id}", headers=auth_headers)
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["result_data"]["total_blocks"] == 5
    db.expire_all()
    fresh2 = db.query(Calculation).filter(Calculation.id == calc.id).first()
    assert fresh2.updated_at == after
    assert fresh2.updated_at >= before


def test_auto_block_commit_reconciles_result_data_without_manual_call(db, auth_headers):
    # BA-4: a workspace block mutation (auto_block commit) must reconcile the
    # JSONB snapshot automatically -- no separate manual reconcile call needed.
    from shapely.geometry import box as _box

    stale = {"total_blocks": 1, "blocks": [{"block_name": "stale", "area_hectares": 1.0}]}
    calc = _calc(db, stale)

    created = commit_blocks(db, calc, [
        {"index": 0, "name": "NewBlock", "geometry": _box(2, 2, 4, 4)},
    ])
    db.refresh(calc)

    assert len(created) == 1
    rd = calc.result_data
    assert rd["total_blocks"] == 1
    assert len(rd["blocks"]) == 1
    assert rd["blocks"][0]["block_name"] == "NewBlock"
    assert rd["blocks"][0]["block_id"] == created[0]["id"]
    assert rd["blocks"][0]["geometry"]  # real geometry persisted, not the stale snapshot

