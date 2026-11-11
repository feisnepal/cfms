"""BLOCK_BOUNDARY_INVARIANT endpoint tests (plan E.2–E.7).

Covers the API-level behavior of the boundary≡blocks invariant:
  - E.2 cut-polygon: cut pieces keep total area; uncovered boundary is
    auto-filled as a Remainder Block (invariant warning surfaced).
  - E.7 draw (POST /calculations/{id}/blocks/draw): new block is clipped to
    the boundary; fully-outside → 400 OUTSIDE_BOUNDARY; material overlap →
    409 TOPOLOGY_REJECTED; gap after draw → remainder auto-added.
  - E.4 delete-block: deleting a block opens a gap that is auto-filled as a
    Remainder Block so total block area == boundary area.
"""
import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import box
from sqlalchemy import text

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _register(client):
    email = f"invariant-api-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Invariant API",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _calc(db, user_id, boundary=box(2, 2, 6, 6)):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name="Invariant Forest",
        boundary_geom=shp_wkt.dumps(boundary),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _block(db, calc, geom, name="Block 1", index=0, **kwargs):
    block = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        geometry=shp_wkt.dumps(geom),
        area_hectares=1.0,
        index=index,
        **kwargs,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def _blocks(db, calc):
    return db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment.isnot(True),
        ForestBlock.division_level == 1,
    ).all()


def _total_block_area_deg2(db, calc):
    from geoalchemy2.shape import to_shape
    rows = _blocks(db, calc)
    return sum(to_shape(r.geometry).area for r in rows if r.geometry)


# ---------------------------------------------------------------------------
# E.7 — draw a new block
# ---------------------------------------------------------------------------

def test_draw_block_persists_and_leaves_no_gap(client, db):
    """Drawing a block that exactly covers the boundary → no remainder."""
    headers, uid = _register(client)
    calc = _calc(db, uid)
    db.expire_all()

    geom = {
        "type": "Polygon",
        "coordinates": [[[2.0, 2.0], [6.0, 2.0], [6.0, 6.0], [2.0, 6.0], [2.0, 2.0]]],
    }
    resp = client.post(
        f"/api/v1/calculations/{calc.id}/blocks/draw",
        headers=headers,
        json={"level": "blocks", "name": "My Block", "geometry": geom},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["block"]["name"] == "My Block"
    assert body["clipped"] is False
    # Full coverage → no remainder block.
    assert body["invariant"]["remainder_added"] is False
    blocks = _blocks(db, calc)
    assert len(blocks) == 1


def test_draw_block_clips_to_boundary_and_remains_coverage(client, db):
    """A drawn block bigger than the boundary is clipped; gap is remaindered."""
    headers, uid = _register(client)
    calc = _calc(db, uid)
    db.expire_all()

    # Drawn block is half inside, half outside the boundary (x 1..5, y 2..6).
    geom = {
        "type": "Polygon",
        "coordinates": [[[1.0, 2.0], [5.0, 2.0], [5.0, 6.0], [1.0, 6.0], [1.0, 2.0]]],
    }
    resp = client.post(
        f"/api/v1/calculations/{calc.id}/blocks/draw",
        headers=headers,
        json={"level": "blocks", "geometry": geom},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["clipped"] is True
    assert body["removed_ha"] > 0
    # Clipped part covers x 2..5 of the boundary → gap x 5..6 → remainder added.
    assert body["invariant"]["remainder_added"] is True
    assert len(_blocks(db, calc)) == 2


def test_draw_block_fully_outside_boundary_rejected(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    db.expire_all()

    geom = {
        "type": "Polygon",
        "coordinates": [[[20.0, 20.0], [21.0, 20.0], [21.0, 21.0], [20.0, 21.0], [20.0, 20.0]]],
    }
    resp = client.post(
        f"/api/v1/calculations/{calc.id}/blocks/draw",
        headers=headers,
        json={"level": "blocks", "geometry": geom},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "OUTSIDE_BOUNDARY"
    assert len(_blocks(db, calc)) == 0


def test_draw_block_overlapping_existing_rejected(client, db):
    """A drawn block that materially overlaps an existing block → 409."""
    headers, uid = _register(client)
    calc = _calc(db, uid)
    _block(db, calc, box(2, 2, 4, 4), name="Existing", index=0)
    db.expire_all()

    geom = {
        "type": "Polygon",
        "coordinates": [[[3.0, 3.0], [5.0, 3.0], [5.0, 5.0], [3.0, 5.0], [3.0, 3.0]]],
    }
    resp = client.post(
        f"/api/v1/calculations/{calc.id}/blocks/draw",
        headers=headers,
        json={"level": "blocks", "geometry": geom},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "TOPOLOGY_REJECTED"
    # No new block persisted.
    assert len(_blocks(db, calc)) == 1


def test_draw_block_bad_level_rejected(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    geom = {
        "type": "Polygon",
        "coordinates": [[[2.0, 2.0], [3.0, 2.0], [3.0, 3.0], [2.0, 3.0], [2.0, 2.0]]],
    }
    resp = client.post(
        f"/api/v1/calculations/{calc.id}/blocks/draw",
        headers=headers,
        json={"level": "sub_areas", "geometry": geom},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "BAD_LEVEL"


# ---------------------------------------------------------------------------
# E.2 — cut-polygon invariant (uncovered area auto-filled)
# ---------------------------------------------------------------------------

def test_cut_polygon_uncovered_area_becomes_remainder(client, db):
    """After cutting a partial block, the uncovered boundary becomes a
    Remainder Block so total block area == boundary area."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    block = _block(db, calc, geom=box(2.5, 2.5, 5.5, 5.5))
    db.expire_all()

    cut = {"type": "LineString", "coordinates": [[3.0, 2.0], [3.0, 6.0]]}
    resp = client.post(
        f"/api/v1/calculations/{calc.id}/geometry/cut-polygon",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": str(block.id), "cut_line": cut},
    )
    assert resp.status_code == 200, resp.text
    # 2 pieces + 1 remainder block.
    assert len(_blocks(db, calc)) == 3
    warnings = resp.json()["warnings"]
    assert "REMAINDER_BLOCK_ADDED" in warnings
    # Invariant holds: Σ block areas ≈ boundary area.
    boundary_area = 4.0 * 4.0
    total = _total_block_area_deg2(db, calc)
    assert abs(total - boundary_area) < 0.01


# ---------------------------------------------------------------------------
# E.4 — delete-block invariant (gap auto-filled)
# ---------------------------------------------------------------------------

def test_delete_block_gap_becomes_remainder(client, db):
    """Deleting one of two blocks covering the boundary → remainder fills gap."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    a = _block(db, calc, geom=box(2, 2, 4, 6), name="Block A", index=0)
    _block(db, calc, geom=box(4, 2, 6, 6), name="Block B", index=1)
    db.expire_all()

    resp = client.delete(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{a.id}",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    blocks = _blocks(db, calc)
    # 1 remaining block (B) + 1 remainder block (covering A's area).
    assert len(blocks) == 2
    assert all(r.name for r in blocks)
    # Invariant holds.
    boundary_area = 4.0 * 4.0
    total = _total_block_area_deg2(db, calc)
    assert abs(total - boundary_area) < 0.01


def test_delete_block_via_forests_router(client, db):
    """The legacy /forests delete-block route also enforces the invariant."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    a = _block(db, calc, geom=box(2, 2, 4, 6), name="Block A", index=0)
    _block(db, calc, geom=box(4, 2, 6, 6), name="Block B", index=1)
    db.expire_all()

    resp = client.delete(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{a.id}",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text
    blocks = _blocks(db, calc)
    assert len(blocks) == 2
    boundary_area = 4.0 * 4.0
    total = _total_block_area_deg2(db, calc)
    assert abs(total - boundary_area) < 0.01


# ---------------------------------------------------------------------------
# BL-2 — deleting the LAST block is a deliberate clear, not a gap
# (GAP_HANDLING_PLAN.md, "Block Lifecycle Decoupling", 2026-08-29)
# ---------------------------------------------------------------------------

def test_delete_sole_block_leaves_zero_and_sets_flag(client, db):
    """Deleting the only block (covers the whole boundary) must NOT self-heal
    via a Remainder Block — it must leave zero blocks and record
    blocks_cleared_by_user, via the /blocks router."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    solo = _block(db, calc, geom=box(2, 2, 6, 6), name="Solo Block", index=0)
    db.expire_all()

    resp = client.delete(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{solo.id}",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    assert _blocks(db, calc) == []
    db.expire_all()
    refreshed = db.query(Calculation).filter(Calculation.id == calc.id).first()
    assert refreshed.blocks_cleared_by_user is True


def test_delete_sole_block_via_forests_router_leaves_zero_and_sets_flag(client, db):
    """Same behaviour through the duplicate /forests router, the one the
    frontend actually calls."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    solo = _block(db, calc, geom=box(2, 2, 6, 6), name="Solo Block", index=0)
    db.expire_all()

    resp = client.delete(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{solo.id}",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    assert _blocks(db, calc) == []
    db.expire_all()
    refreshed = db.query(Calculation).filter(Calculation.id == calc.id).first()
    assert refreshed.blocks_cleared_by_user is True


def test_delete_block_with_subblocks_requires_confirm(client, db):
    """FS-4a.9 (D13): a block with sub-blocks below it refuses to delete
    without confirm_children=true (409, count in the detail)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    a = _block(db, calc, geom=box(2, 2, 4, 6), name="Block A", index=0)
    _block(db, calc, geom=box(4, 2, 6, 6), name="Block B", index=1)
    sub = _block(
        db, calc, geom=box(2, 2, 3, 6), name="Block A-SB1", index=2,
        division_level=2, parent_block_id=a.id,
    )
    a_id, sub_id = a.id, sub.id
    db.expire_all()

    resp = client.delete(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{a_id}",
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "blocks.has_children_confirm_required"
    assert detail["count"] == 1

    # The refused delete leaves both the block and its sub-block intact.
    db.expire_all()
    assert db.query(ForestBlock).filter(ForestBlock.id == a_id).first() is not None
    assert db.query(ForestBlock).filter(ForestBlock.id == sub_id).first() is not None


def test_delete_block_with_subblocks_confirm_cascades(client, db):
    """FS-4a.9: confirm_children=true genuinely removes the sub-block along
    with its parent (`passive_deletes=True` lets Postgres's own
    ON DELETE CASCADE fire instead of the ORM nulling the FK first)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    a = _block(db, calc, geom=box(2, 2, 4, 6), name="Block A", index=0)
    _block(db, calc, geom=box(4, 2, 6, 6), name="Block B", index=1)
    sub = _block(
        db, calc, geom=box(2, 2, 3, 6), name="Block A-SB1", index=2,
        division_level=2, parent_block_id=a.id,
    )
    # Captured before the endpoint's commit expires these ORM instances --
    # touching an attribute on an expired-and-now-deleted instance raises
    # ObjectDeletedError instead of giving back the old value.
    a_id, sub_id = a.id, sub.id
    db.expire_all()

    resp = client.delete(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{a_id}?confirm_children=true",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    db.expire_all()
    assert db.query(ForestBlock).filter(ForestBlock.id == a_id).first() is None
    assert db.query(ForestBlock).filter(ForestBlock.id == sub_id).first() is None


def test_delete_block_without_subblocks_needs_no_confirm(client, db):
    """FS-4a.9: a childless block deletes fine with no confirm_children param
    at all -- pins that the new guard doesn't regress the common case
    already covered by test_delete_block_gap_becomes_remainder."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    a = _block(db, calc, geom=box(2, 2, 4, 6), name="Block A", index=0)
    _block(db, calc, geom=box(4, 2, 6, 6), name="Block B", index=1)
    db.expire_all()

    resp = client.delete(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{a.id}",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text


def test_delete_block_with_subblocks_requires_confirm_via_forests_router(client, db):
    """FS-4a.9: same guard on the duplicate /forests router, kept in
    lockstep with /blocks (see blocks-forests-duplicate-routers memory)."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    a = _block(db, calc, geom=box(2, 2, 4, 6), name="Block A", index=0)
    _block(db, calc, geom=box(4, 2, 6, 6), name="Block B", index=1)
    sub = _block(
        db, calc, geom=box(2, 2, 3, 6), name="Block A-SB1", index=2,
        division_level=2, parent_block_id=a.id,
    )
    a_id, sub_id = a.id, sub.id
    db.expire_all()

    resp = client.delete(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{a_id}",
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "blocks.has_children_confirm_required"

    resp2 = client.delete(
        f"/api/v1/forests/calculations/{calc.id}/blocks/{a_id}?confirm_children=true",
        headers=headers,
    )
    assert resp2.status_code == 204, resp2.text
    db.expire_all()
    assert db.query(ForestBlock).filter(ForestBlock.id == sub_id).first() is None


def test_delete_all_blocks_bulk_sets_flag(client, db):
    """The bulk 'delete all blocks' endpoint (already zero-remainder) also
    records the deliberate clear."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    _block(db, calc, geom=box(2, 2, 4, 6), name="Block A", index=0)
    _block(db, calc, geom=box(4, 2, 6, 6), name="Block B", index=1)
    db.expire_all()

    resp = client.delete(
        f"/api/v1/forests/calculations/{calc.id}/blocks",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted_count"] == 2

    assert _blocks(db, calc) == []
    db.expire_all()
    refreshed = db.query(Calculation).filter(Calculation.id == calc.id).first()
    assert refreshed.blocks_cleared_by_user is True


def test_partial_delete_still_remainders_and_leaves_flag_unset(client, db):
    """Sanity check: a delete that leaves >=1 block behind is unchanged —
    still remainder-filled, and does NOT set the opt-out flag."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    a = _block(db, calc, geom=box(2, 2, 4, 6), name="Block A", index=0)
    _block(db, calc, geom=box(4, 2, 6, 6), name="Block B", index=1)
    db.expire_all()

    resp = client.delete(
        f"/api/v1/blocks/calculations/{calc.id}/blocks/{a.id}",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    assert len(_blocks(db, calc)) == 2  # Block B + remainder
    db.expire_all()
    refreshed = db.query(Calculation).filter(Calculation.id == calc.id).first()
    assert refreshed.blocks_cleared_by_user is False


def test_create_single_block_clears_flag(client, db):
    """BL-4: explicit reimport ("Import Block from Forest Boundary") clears
    blocks_cleared_by_user, via the /forests router the frontend calls."""
    headers, uid = _register(client)
    calc = _calc(db, uid, box(2, 2, 6, 6))
    calc.blocks_cleared_by_user = True
    db.commit()
    db.expire_all()

    resp = client.post(
        f"/api/v1/forests/calculations/{calc.id}/create-single-block",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert len(_blocks(db, calc)) == 1

    db.expire_all()
    refreshed = db.query(Calculation).filter(Calculation.id == calc.id).first()
    assert refreshed.blocks_cleared_by_user is False
