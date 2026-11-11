"""FS-4a.5 — equal-area divide across all four unit layers + the two root carves.

The four divide routes a layer may take (see ``app/api/editing.py``,
``divide_equal_areas`` / ``divide_preview``):

  * ROOT divide  (``feature_id`` empty) — carve the forest boundary itself into
    the FIRST set of top-level blocks or compartments. Refused with
    ``BLOCKS_EXIST`` once ANY ``forest_blocks`` row already exists. Sub-units
    cannot be carved from the root.
  * parent-kept carve — ``sub_blocks`` on a top-level block (new engine
    ``operations.divide``); ``compartments`` on a block; ``sub_compartments``
    on a compartment (compartment shim). The parent row is KEPT.
  * self-divide — the selected feature is already of ``layer_type``; the
    generic replace-in-place path splits THAT one, preserving branch/depth.

Assertions cover 200s, the two 400 guard classes, preview-no-persist parity,
parent keeping, depths, and stream/branch integrity via SQL (no reliance on the
unit helper, so the test stays readable against raw rows).
"""
import uuid

from sqlalchemy import text
from shapely.geometry import box
from shapely import wkt as shp_wkt

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock

import pytest

pytestmark = pytest.mark.usefixtures("forget_forests")


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

def _register(client):
    email = f"divide-4layers-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Divide Tester",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _calc(db, user_id, boundary=box(83.0, 27.0, 84.0, 28.0)):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name="Divide All Four Layers",
        boundary_geom=shp_wkt.dumps(boundary),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _row(db, calc, name="Block 1", geom=None, *, is_compartment=False,
         division_level=1, parent_id=None, index=0):
    if geom is None:
        geom = box(83.2, 27.2, 83.8, 27.7)
    row = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        block_name=name,
        geometry=shp_wkt.dumps(geom),
        area_hectares=10.0,
        index=index,
        is_compartment=is_compartment,
        division_level=division_level,
        parent_block_id=parent_id,
        is_locked=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _url(calc_id):
    return f"/api/v1/calculations/{calc_id}/geometry"


def _children_of(db, parent_id):
    rows = db.execute(text(
        """
        SELECT id::text AS id, name, division_level, is_compartment, parent_block_id::text AS parent_block_id
        FROM forest_blocks WHERE parent_block_id = :pid ORDER BY display_order
        """
    ), {"pid": str(parent_id)}).all()
    return rows


def _all_blocks(db, calc_id):
    return db.execute(text(
        """
        SELECT id::text AS id, name, division_level, is_compartment, parent_block_id::text AS parent_block_id
        FROM forest_blocks WHERE calculation_id = :cid ORDER BY index
        """
    ), {"cid": str(calc_id)}).all()


# ---------------------------------------------------------------------------
# ROOT divides — blocks
# ---------------------------------------------------------------------------

def test_root_divide_blocks_carves_top_level_set(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)

    resp = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": "", "count": 3},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["parent_id"] is None
    assert body["split_history_id"] is None
    assert body["trees_reassigned"] == 0
    assert body["boundary_pieces_stored_as"] == "blocks"
    assert body["n_children"] == 3 and len(body["children"]) == 3

    rows = _all_blocks(db, calc.id)
    assert len(rows) == 3
    for r in rows:
        assert r.division_level == 1
        assert r.is_compartment is False
        assert r.parent_block_id is None
    assert sorted(r.name for r in rows) == ["B1", "B2", "B3"]  # system names: B<n>, no forest name


def test_root_divide_blocks_refuses_once_units_exist(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    _row(db, calc, name="Block 1")

    resp = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": ""},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["message"] == "BLOCKS_EXIST"


def test_root_divide_blocks_preview_no_persist(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)

    resp = client.post(
        f"{_url(calc.id)}/divide-preview",
        headers=headers,
        json={"layer_type": "blocks", "feature_id": "", "count": 3},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["total_pieces"] == 3
    assert len(body["pieces"]) == 3
    assert body["pieces"][0]["name"] == "B1"
    assert body["parent_id"] is None
    # preview must not persist a single row
    assert len(_all_blocks(db, calc.id)) == 0


# ---------------------------------------------------------------------------
# ROOT divides — compartments
# ---------------------------------------------------------------------------

def test_root_divide_compartments_carves_top_level_set(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)

    resp = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "compartments", "feature_id": "", "count": 3},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["n_children"] == 3 and len(body["children"]) == 3

    rows = _all_blocks(db, calc.id)
    assert len(rows) == 3
    for r in rows:
        assert r.division_level == 1
        assert r.is_compartment is True
        assert r.parent_block_id is None
    assert sorted(r.name for r in rows) == ["C1", "C2", "C3"]


def test_root_divide_compartments_refuses_once_units_exist(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    _row(db, calc, name="Block 1")

    resp = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "compartments", "feature_id": ""},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["message"] == "BLOCKS_EXIST"


def test_root_divide_sub_units_refused(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)

    for layer in ("sub_blocks", "sub_compartments"):
        resp = client.post(
            f"{_url(calc.id)}/divide-equal-areas",
            headers=headers,
            json={"layer_type": layer, "feature_id": ""},
        )
        assert resp.status_code == 400, (layer, resp.text)
        assert "Sub-units cannot be carved from the forest root" in resp.text
        resp = client.post(
            f"{_url(calc.id)}/divide-preview",
            headers=headers,
            json={"layer_type": layer, "feature_id": ""},
        )
        assert resp.status_code == 400, (layer, resp.text)


# ---------------------------------------------------------------------------
# sub_blocks — parent-kept carve from a top-level block
# ---------------------------------------------------------------------------

def test_sub_blocks_divide_from_top_level_block_parent_kept(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _row(db, calc, name="Block 1")

    resp = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "sub_blocks", "feature_id": str(block.id), "count": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["parent_id"] == str(block.id)
    assert body["n_children"] == 2 and len(body["children"]) == 2

    # parent row KEPT, with sub-blocks hanging off it
    before = _all_blocks(db, calc.id)
    assert len(before) == 3  # 1 parent + 2 children
    parent = [r for r in before if r.id == str(block.id)]
    assert len(parent) == 1
    kids = _children_of(db, block.id)
    assert len(kids) == 2
    for k in kids:
        assert k.division_level == 2
        assert k.is_compartment is False
    assert sorted(k.name for k in kids) == ["Block 1-SB1", "Block 1-SB2"]


def test_sub_blocks_divide_preview_matches_commit_names(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _row(db, calc, name="Block 1")

    resp = client.post(
        f"{_url(calc.id)}/divide-preview",
        headers=headers,
        json={"layer_type": "sub_blocks", "feature_id": str(block.id), "count": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["total_pieces"] == 2
    assert body["parent_id"] == str(block.id)
    assert sorted(p["name"] for p in body["pieces"]) == ["Block 1-SB1", "Block 1-SB2"]

    # commit the SAME request -> names must match the preview labels exactly
    resp = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "sub_blocks", "feature_id": str(block.id), "count": 2},
    )
    assert resp.status_code == 200, resp.text
    names = {p["name"] for p in body["pieces"]}
    assert names == {k.name for k in _children_of(db, block.id)}


def test_sub_blocks_self_divide_preserves_branch_and_depth(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _row(db, calc, name="Block 1")
    sub = _row(db, calc, name="Block 1-SB1", division_level=2, parent_id=block.id, index=1)

    resp = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "sub_blocks", "feature_id": str(sub.id), "count": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["n_children"] == 2

    rows = _all_blocks(db, calc.id)
    assert len(rows) == 3  # parent + 2 self-divided pieces; original sub deleted
    assert str(sub.id) not in {r.id for r in rows}
    for r in rows:
        if r.id == str(block.id):
            continue
        assert r.is_compartment is False
        assert r.division_level == 2
        assert r.parent_block_id == str(block.id)


def test_sub_blocks_self_divide_preview_labelled(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _row(db, calc, name="Block 1")
    sub = _row(db, calc, name="Block 1-SB1", division_level=2, parent_id=block.id, index=1)

    resp = client.post(
        f"{_url(calc.id)}/divide-preview",
        headers=headers,
        json={"layer_type": "sub_blocks", "feature_id": str(sub.id), "count": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["total_pieces"] == 2
    assert body["parent_id"] == str(sub.id)
    assert body["pieces"][0]["name"].startswith("Block 1-SB1-")
    assert len(_all_blocks(db, calc.id)) == 2  # nothing persisted


def test_sub_blocks_divide_refuses_on_compartment_parent(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    comp = _row(db, calc, name="C1", is_compartment=True, division_level=1)

    resp = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "sub_blocks", "feature_id": str(comp.id), "count": 2},
    )
    assert resp.status_code == 400, resp.text
    assert "sub-divide a block" in resp.text


# ---------------------------------------------------------------------------
# compartments / sub_compartments — parent-kept shim still intact
# ---------------------------------------------------------------------------

def test_compartments_from_block_parent_kept(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _row(db, calc, name="Block 1")

    resp = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "compartments", "feature_id": str(block.id), "count": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parent_id"] == str(block.id)

    rows = _all_blocks(db, calc.id)
    assert len(rows) == 3  # parent kept + 2 children
    kids = _children_of(db, block.id)
    assert len(kids) == 2
    for k in kids:
        assert k.is_compartment is True
        assert k.division_level == 1


def test_sub_compartments_from_compartment_parent_kept(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _row(db, calc, name="Block 1")
    comp = _row(db, calc, name="C1", is_compartment=True, division_level=1,
                parent_id=block.id, index=1)

    resp = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "sub_compartments", "feature_id": str(comp.id), "count": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parent_id"] == str(comp.id)

    rows = _all_blocks(db, calc.id)
    assert len(rows) == 4  # block + parent comp + 2 sub-comps
    kids = _children_of(db, comp.id)
    assert len(kids) == 2
    for k in kids:
        assert k.is_compartment is True
        assert k.division_level == 2
    assert sorted(k.name for k in kids) == ["C1-SC1", "C1-SC2"]


def test_compartments_divide_refuses_same_parent_twice(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    block = _row(db, calc, name="Block 1")

    first = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "compartments", "feature_id": str(block.id), "count": 2},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={"layer_type": "compartments", "feature_id": str(block.id), "count": 2},
    )
    assert second.status_code == 400, second.text
    assert "DIVISION_ONCE_ONLY" in second.text


# ---------------------------------------------------------------------------
# self-divide of a unit that HAS sub-units (D13, FS-4a.7) — end-to-end through
# the real endpoint; the geometric redistribution itself is covered in depth
# by tests/structure/test_reparent.py.
# ---------------------------------------------------------------------------

def test_self_dividing_a_block_redistributes_its_sub_blocks(client, db):
    """``forest_blocks.parent_block_id`` is ON DELETE CASCADE -- without D13's
    redistribution, self-dividing Block 1 would silently destroy its
    sub-block along with it."""
    from shapely.geometry import box

    headers, uid = _register(client)
    calc = _calc(db, uid, boundary=box(83.0, 27.0, 83.10, 27.10))
    block = _row(db, calc, name="Block 1", geom=box(83.0, 27.0, 83.10, 27.10))
    sub = _row(
        db, calc, name="Block 1-SB1", geom=box(83.005, 27.02, 83.02, 27.08),
        is_compartment=False, division_level=2, parent_id=block.id, index=1,
    )

    resp = client.post(
        f"{_url(calc.id)}/divide-equal-areas",
        headers=headers,
        json={
            "layer_type": "blocks",
            "feature_id": str(block.id),
            "count": 2,
            "direction": "vertical",
        },
    )
    assert resp.status_code == 200, resp.text

    rows = _all_blocks(db, calc.id)
    assert str(block.id) not in {r.id for r in rows}  # the old parent is gone
    assert str(sub.id) not in {r.id for r in rows}  # the OLD sub-block row is gone too
    new_blocks = [r for r in rows if r.parent_block_id is None]
    assert len(new_blocks) == 2  # the two new top-level pieces
    new_subs = [r for r in rows if r.parent_block_id is not None]
    # The sub-block survived (re-homed, possibly split) -- not cascade-deleted
    # into nothing.
    assert len(new_subs) >= 1
    for s in new_subs:
        assert s.parent_block_id in {r.id for r in new_blocks}
        assert s.division_level == 2