"""SV-1.3 + SV-1.4 — attribute-edit PATCH drops both SFM blobs (blocks.py +
forests.py); SFM-tab ``patch_block`` override reaches the user variant.

SV-1.3 hits the block PATCH /calculations/{id}/blocks/{id} with
``dominant_slope_band`` or ``management_orientation`` changes and verifies that
``result_data`` no longer carries either ``sfm`` or ``sfm_user``. Name-only
patches must NOT drop the blobs.

SV-1.4 hits ``patch_block`` (PATCH /sustainable-fm/blocks/{name}) with an
``override_type_no`` and verifies it refreshes *both* blobs: the stale
``sfm_user`` is dropped, and a fresh ``variant=user`` build carries the same
override (single-sourced in the baseline blob).

    & ..\\venv\\Scripts\\python.exe -m pytest tests/services/test_sfm_variant_patch.py -q
"""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.services.sustainable_fm.sfm_service import (
    SFM_RESULT_KEY,
    SFM_USER_KEY,
    build_sfm,
)


def _calc_with_block(db, user) -> tuple[Calculation, str]:
    c = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        forest_name=f"PATCH SFM {uuid.uuid4().hex[:6]}",
        is_draft=False,
        structure_locked=False,
    )
    db.add(c)
    db.flush()
    blk = ForestBlock(
        calculation_id=c.id,
        name="Patch-1",
        block_name="Patch-1",
        geometry=from_shape(
            Polygon([(84.0, 27.0), (84.02, 27.0), (84.02, 27.02), (84.0, 27.02)]),
            srid=4326,
        ),
        area_hectares=100.0,
        area_sqm=1_000_000.0,
        index=1,
        division_level=1,
    )
    db.add(blk)
    db.commit()
    return c, str(blk.id)


def _reload(db, calc) -> dict:
    db.expire_all()
    c = db.query(Calculation).get(calc.id)
    return c.result_data or {}


def _seed_blobs(calc, db) -> None:
    build_sfm(calc, db)
    build_sfm(calc, db, variant="user")
    assert SFM_RESULT_KEY in (calc.result_data or {})
    assert SFM_USER_KEY in calc.result_data


# ── tests ───────────────────────────────────────────────────────────────────
def test_slope_patch_drops_both(client, db, auth_headers):
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    calc, blk_id = _calc_with_block(db, user)
    _seed_blobs(calc, db)

    r = client.patch(
        f"/api/forests/calculations/{calc.id}/blocks/{blk_id}",
        json={"dominant_slope_band": 3},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert SFM_RESULT_KEY not in _reload(db, calc)
    assert SFM_USER_KEY not in _reload(db, calc)


def test_orientation_patch_drops_both(client, db, auth_headers):
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    calc, blk_id = _calc_with_block(db, user)
    _seed_blobs(calc, db)

    r = client.patch(
        f"/api/forests/calculations/{calc.id}/blocks/{blk_id}",
        json={"management_orientation": "Conservation"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert SFM_RESULT_KEY not in _reload(db, calc)
    assert SFM_USER_KEY not in _reload(db, calc)


def test_slope_null_drops_both(client, db, auth_headers):
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    calc, blk_id = _calc_with_block(db, user)
    _seed_blobs(calc, db)

    r = client.patch(
        f"/api/forests/calculations/{calc.id}/blocks/{blk_id}",
        json={"dominant_slope_band": None},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert SFM_RESULT_KEY not in _reload(db, calc)
    assert SFM_USER_KEY not in _reload(db, calc)


def test_name_only_preserves_blobs(client, db, auth_headers):
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    calc, blk_id = _calc_with_block(db, user)
    _seed_blobs(calc, db)

    r = client.patch(
        f"/api/forests/calculations/{calc.id}/blocks/{blk_id}",
        json={"block_name": "Renamed"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    rd = _reload(db, calc)
    assert SFM_RESULT_KEY in rd
    assert SFM_USER_KEY in rd


# ── SV-1.4: SFM-tab patch_block override reaches the user variant ──────────
def test_patch_block_override_drops_stale_user_blob(client, db, auth_headers):
    """An already-built ``sfm_user`` becomes stale the moment the SFM-tab PATCH
    writes an override — it must be dropped so the next ``variant=user`` build
    carries the override from the baseline blob."""
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    calc, _ = _calc_with_block(db, user)
    _seed_blobs(calc, db)

    r = client.patch(
        f"/api/calculations/{calc.id}/sustainable-fm/blocks/Patch-1",
        json={"override_type_no": 7},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    rd = _reload(db, calc)
    assert SFM_RESULT_KEY in rd  # baseline refreshed (rebuilt by patch_block)
    assert SFM_USER_KEY not in rd  # stale user variant dropped


def test_patch_block_override_reaches_fresh_user_variant(client, db, auth_headers):
    """After the SFM-tab PATCH + a prior user build, a force-rebuilt user
    variant carries the same override as the baseline (single-sourced there)."""
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    calc, _ = _calc_with_block(db, user)
    _seed_blobs(calc, db)

    r = client.patch(
        f"/api/calculations/{calc.id}/sustainable-fm/blocks/Patch-1",
        json={"override_type_no": 7},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["block"]["effective_type_no"] == 7

    sfm = build_sfm(calc, db)
    usr = build_sfm(calc, db, variant="user", force=True)

    for blob in (sfm["blocks"], usr["blocks"]):
        b = next(x for x in blob if x["block_name"] == "Patch-1")
        assert b["override_type_no"] == 7
        assert b["effective_type_no"] == 7
    assert usr["forest_summary"] == sfm["forest_summary"]  # identical roll-up

    rd = _reload(db, calc)
    assert SFM_USER_KEY in rd
    assert rd[SFM_USER_KEY]["blocks"][0]["override_type_no"] == 7


def test_patch_block_override_reaches_first_user_build(client, db, auth_headers):
    """A user variant built for the FIRST time after the SFM-tab PATCH must
    carry the override from the baseline blob (single-sourced there) — an empty
    own-variant carry must not start from scratch."""
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    calc, _ = _calc_with_block(db, user)

    r = client.patch(
        f"/api/calculations/{calc.id}/sustainable-fm/blocks/Patch-1",
        json={"override_type_no": 7},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    sfm = build_sfm(calc, db)
    usr = build_sfm(calc, db, variant="user")  # no prior user blob yet

    assert SFM_USER_KEY in (calc.result_data or {})
    for blob in (sfm["blocks"], usr["blocks"]):
        b = next(x for x in blob if x["block_name"] == "Patch-1")
        assert b["override_type_no"] == 7
        assert b["effective_type_no"] == 7
