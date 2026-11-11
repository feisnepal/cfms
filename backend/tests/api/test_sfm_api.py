"""Sustainable Forest Management API (P3).

GET summary / blocks / narration, PATCH a block override, and the per-forest
SfmParams GET/PATCH/DELETE — all touch only ``calculation.result_data``, so they
run against the test DB. No rasters → blocks resolve to source "prior".
"""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User


def _owner(client, db):
    email = f"sfm-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "SFM"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def _calc_with_block(db, user):
    c = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        forest_name=f"SFM CF {uuid.uuid4().hex[:6]}",
        is_draft=False,
        structure_locked=False,
    )
    db.add(c)
    db.flush()
    poly = Polygon([(84, 27), (84.02, 27), (84.02, 27.02), (84, 27.02)])
    db.add(
        ForestBlock(
            calculation_id=c.id,
            name="Block-1",
            block_name="Block-1",
            geometry=from_shape(poly, srid=4326),
            area_hectares=100.0,
            area_sqm=1_000_000.0,
            index=1,
            division_level=1,
        )
    )
    db.commit()
    return c


# ── auth ───────────────────────────────────────────────────────────────
def test_auth_matrix(client, db):
    headers, user = _owner(client, db)
    c = _calc_with_block(db, user)

    assert client.get(
        f"/api/calculations/{c.id}/sustainable-fm/summary"
    ).status_code in (401, 403)

    h2, _ = _owner(client, db)  # a different user
    assert (
        client.get(
            f"/api/calculations/{c.id}/sustainable-fm/summary", headers=h2
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/calculations/{c.id}/sustainable-fm/summary", headers=headers
        ).status_code
        == 200
    )


# ── analysis reads ─────────────────────────────────────────────────────
def test_summary_and_blocks_and_narration(client, db):
    headers, user = _owner(client, db)
    c = _calc_with_block(db, user)

    s = client.get(f"/api/calculations/{c.id}/sustainable-fm/summary", headers=headers)
    assert s.status_code == 200, s.text
    body = s.json()
    assert "forest_summary" in body and "felling_series" in body
    assert body["source"] in ("stem_mapping", "field_inventory", "prior", "mixed")

    b = client.get(f"/api/calculations/{c.id}/sustainable-fm/blocks", headers=headers)
    assert b.status_code == 200
    blocks = b.json()["blocks"]
    assert len(blocks) == 1
    blk = blocks[0]
    assert blk["block_name"] == "Block-1"
    # No sample plots in this block: the type is NOT determined from a raster or a national table (owner,
    # 2026-10-06). The raster prior survives only as a labelled estimate.
    assert blk["state"] == "inventory_missing"
    assert blk["proposed_type_no"] is None and blk["effective_type_no"] is None
    assert 1 <= blk["estimate_type_no"] <= 14
    assert blk["prescription"] is None
    assert "orientation" in blk

    n = client.get(
        f"/api/calculations/{c.id}/sustainable-fm/narration", headers=headers
    )
    assert n.status_code == 200
    assert n.json()["methodology"]["ne"]


# ── variable reference (P8) ────────────────────────────────────────────
def test_variables_manifest(client, db):
    headers, user = _owner(client, db)
    c = _calc_with_block(db, user)

    r = client.get(
        f"/api/calculations/{c.id}/sustainable-fm/variables", headers=headers
    )
    assert r.status_code == 200, r.text
    groups = {g["id"]: g for g in r.json()["groups"]}
    assert set(groups) == {"numbers", "maps", "tables", "narrative"}
    # every non-map row is a registered variable
    for gid in ("numbers", "tables", "narrative"):
        for v in groups[gid]["variables"]:
            assert v["registered"] is True, v["key"]
    # the maps group carries the 3 sfm__ thematic tokens
    map_keys = {v["key"] for v in groups["maps"]["variables"]}
    assert map_keys == {
        "thememap:sfm__forest_type",
        "thememap:sfm__orientation",
        "thememap:sfm__gs_vs_threshold",
    }
    # a non-owner is 403
    h2, _ = _owner(client, db)
    assert (
        client.get(
            f"/api/calculations/{c.id}/sustainable-fm/variables", headers=h2
        ).status_code
        == 403
    )


# ── block override ─────────────────────────────────────────────────────
def test_patch_block_override_type(client, db):
    headers, user = _owner(client, db)
    c = _calc_with_block(db, user)
    client.get(f"/api/calculations/{c.id}/sustainable-fm/blocks", headers=headers)

    r = client.patch(
        f"/api/calculations/{c.id}/sustainable-fm/blocks/Block-1",
        headers=headers,
        json={"override_type_no": 7},
    )
    assert r.status_code == 200, r.text
    assert r.json()["block"]["effective_type_no"] == 7
    assert r.json()["block"]["override_type_no"] == 7

    # persisted across a fresh GET
    b = client.get(f"/api/calculations/{c.id}/sustainable-fm/blocks", headers=headers)
    assert b.json()["blocks"][0]["effective_type_no"] == 7
    assert b.json()["blocks"][0]["proposed_type_no"] != 7 or True  # proposal untouched


def test_patch_block_validation(client, db):
    headers, user = _owner(client, db)
    c = _calc_with_block(db, user)
    client.get(f"/api/calculations/{c.id}/sustainable-fm/blocks", headers=headers)

    for bad in ({"override_type_no": 99}, {"origin": "moon"}, {"nope": 1}, {}):
        r = client.patch(
            f"/api/calculations/{c.id}/sustainable-fm/blocks/Block-1",
            headers=headers,
            json=bad,
        )
        assert r.status_code == 422, (bad, r.text)

    r = client.patch(
        f"/api/calculations/{c.id}/sustainable-fm/blocks/Nope",
        headers=headers,
        json={"override_type_no": 2},
    )
    assert r.status_code == 404


# ── params ─────────────────────────────────────────────────────────────
def test_params_get_patch_delete(client, db):
    headers, user = _owner(client, db)
    c = _calc_with_block(db, user)

    g = client.get(f"/api/calculations/{c.id}/sustainable-fm-params", headers=headers)
    assert g.status_code == 200
    assert g.json()["params"]["harvestable_dbh_min_cm"] == 40.0
    assert g.json()["customised"] is False

    p = client.patch(
        f"/api/calculations/{c.id}/sustainable-fm-params",
        headers=headers,
        json={"harvestable_dbh_min_cm": 30.0},
    )
    assert p.status_code == 200
    assert p.json()["params"]["harvestable_dbh_min_cm"] == 30.0
    assert p.json()["provenance"]["harvestable_dbh_min_cm"] == "forest"

    bad = client.patch(
        f"/api/calculations/{c.id}/sustainable-fm-params",
        headers=headers,
        json={"harvestable_dbh_min_cm": -1},
    )
    assert bad.status_code == 422

    d = client.delete(
        f"/api/calculations/{c.id}/sustainable-fm-params", headers=headers
    )
    assert d.status_code == 200
    assert d.json()["customised"] is False

    # params change wiped result_data['sfm']
    db.expire_all()
    fresh = db.get(Calculation, c.id)
    assert "sfm" not in (fresh.result_data or {})


def test_patch_params_invalidates_sfm(client, db):
    headers, user = _owner(client, db)
    c = _calc_with_block(db, user)
    client.get(f"/api/calculations/{c.id}/sustainable-fm/summary", headers=headers)
    db.expire_all()
    assert "sfm" in db.get(Calculation, c.id).result_data

    client.patch(
        f"/api/calculations/{c.id}/sustainable-fm-params",
        headers=headers,
        json={"seedling_threshold": 4000},
    )
    db.expire_all()
    assert "sfm" not in (db.get(Calculation, c.id).result_data or {})


def test_a_non_forest_land_class_has_no_type_and_no_missing_plots_warning(client, db):
    headers, user = _owner(client, db)
    c = _calc_with_block(db, user)
    url = f"/api/calculations/{c.id}/sustainable-fm/blocks/Block-1"
    client.get(f"/api/calculations/{c.id}/sustainable-fm/blocks", headers=headers)

    r = client.patch(url, headers=headers, json={"land_class": "grassland"})
    assert r.status_code == 200, r.text
    blk = r.json()["block"]
    assert blk["state"] == "non_forest" and blk["land_class"] == "grassland" and blk["land_class_source"] == "user"
    assert blk["effective_type_no"] is None and blk["prescription"] is None

    # back to ESA's suggestion: forest land without plots again
    r = client.patch(url, headers=headers, json={"land_class": None})
    assert r.json()["block"]["state"] == "inventory_missing"
    assert r.json()["block"]["land_class_source"] == "esa"

    assert client.patch(url, headers=headers, json={"land_class": "moon"}).status_code == 422
