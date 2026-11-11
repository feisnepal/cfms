"""SFM P9 — accept / revert a working-circle proposal.

``PATCH .../sustainable-fm/blocks/{name}`` with ``accept_working_circle`` moves
the management block into (or back out of) the protection working circle:
``forest_blocks.working_circle`` flips, ``build_sfm`` re-yields so the
production area shrinks and the total allowable harvest drops, and a later
``false`` reverses it.
"""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User
from tests.sfm_field_fixture import add_field_inventory


def _owner(client, db):
    email = f"wc-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "WC"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def _calc_two_stem_blocks(db, user):
    c = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        forest_name=f"SFM WC {uuid.uuid4().hex[:6]}",
        is_draft=False,
        structure_locked=False,
    )
    db.add(c)
    db.flush()
    fic = None
    for i, (x0, y0) in enumerate([(84.0, 27.0), (84.03, 27.0)], start=1):
        poly = Polygon(
            [(x0, y0), (x0 + 0.02, y0), (x0 + 0.02, y0 + 0.02), (x0, y0 + 0.02)]
        )
        db.add(
            ForestBlock(
                calculation_id=c.id,
                name=f"Block-{i}",
                block_name=f"Block-{i}",
                geometry=from_shape(poly, srid=4326),
                area_hectares=100.0,
                area_sqm=1_000_000.0,
                index=i,
                division_level=1,
            )
        )
        fic = add_field_inventory(db, c, f"Block-{i}", plots=5, gs_per_ha=250.0, fic_id=fic)
    db.commit()
    return c


def _wc(db, calc_id, block_name):
    return db.execute(
        text(
            "SELECT working_circle FROM forest_blocks "
            "WHERE calculation_id = :cid AND COALESCE(block_name, name) = :bn"
        ),
        {"cid": str(calc_id), "bn": block_name},
    ).scalar()


def test_accept_then_revert_a_working_circle_proposal(client, db):
    headers, user = _owner(client, db)
    c = _calc_two_stem_blocks(db, user)

    # build the classification
    b = client.get(f"/api/calculations/{c.id}/sustainable-fm/blocks", headers=headers)
    assert b.status_code == 200, b.text
    assert len(b.json()["blocks"]) == 2

    before = client.get(
        f"/api/calculations/{c.id}/sustainable-fm/summary", headers=headers
    ).json()["forest_summary"]
    assert before["production_area_ha"] > 0
    prod0 = before["production_area_ha"]
    harvest0 = before["total_annual_harvest_m3"]
    assert _wc(db, c.id, "Block-2") in (None, "production")

    # ── accept ──────────────────────────────────────────────────────────
    r = client.patch(
        f"/api/calculations/{c.id}/sustainable-fm/blocks/Block-2",
        headers=headers,
        json={"accept_working_circle": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["block"]["wc_accept"] is True

    db.expire_all()
    assert _wc(db, c.id, "Block-2") == "protection"

    after = client.get(
        f"/api/calculations/{c.id}/sustainable-fm/summary", headers=headers
    ).json()["forest_summary"]
    # Block-2's 100 ha moved from production → protection
    assert after["production_area_ha"] < prod0
    assert after["protection_area_ha"] >= before["protection_area_ha"] + 90
    # and the total allowable harvest dropped (fewer production blocks)
    assert after["total_annual_harvest_m3"] < harvest0

    # ── revert ──────────────────────────────────────────────────────────
    r2 = client.patch(
        f"/api/calculations/{c.id}/sustainable-fm/blocks/Block-2",
        headers=headers,
        json={"accept_working_circle": False},
    )
    assert r2.status_code == 200
    db.expire_all()
    assert _wc(db, c.id, "Block-2") == "production"

    back = client.get(
        f"/api/calculations/{c.id}/sustainable-fm/summary", headers=headers
    ).json()["forest_summary"]
    assert back["production_area_ha"] == prod0
    assert back["total_annual_harvest_m3"] == harvest0
