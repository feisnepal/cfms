"""SV-1.2 — dual-variant SFM build (``sfm`` baseline vs ``sfm_user``).

Runs on the migrations-only test DB: no slope / physiography / DEM rasters, so
every block falls back to band 1 + default physiography — but both variants use
the *same* fallback, which is exactly what these tests need. Workspace overrides
come via ``forest_blocks`` columns (``dominant_slope_band``) and must flip only
the edited block, leaving the baseline untouched.

    & ..\\venv\\Scripts\\python.exe -m pytest tests/services/test_sfm_variant_service.py -q
"""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services.sustainable_fm.sfm_service import (
    SFM_BLOCK_VERSION,
    SFM_RESULT_KEY,
    SFM_USER_KEY,
    build_sfm,
    invalidate_sfm,
)


def _user(db) -> User:
    u = User(
        email=f"sfmvar{uuid.uuid4().hex[:8]}@t.com",
        full_name="x",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    return u


from tests.sfm_field_fixture import add_field_inventory  # noqa: E402


def _calc_with_blocks(db, user) -> Calculation:
    c = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        forest_name=f"SFM VAR {uuid.uuid4().hex[:6]}",
        is_draft=False,
        structure_locked=False,
    )
    db.add(c)
    db.flush()
    for i in (1, 2):
        lat = 27.00 + (i - 1) * 0.03
        poly = Polygon([(84.0, lat), (84.02, lat), (84.02, lat + 0.02), (84.0, lat + 0.02)])
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
    db.commit()
    fic = None
    for i in (1, 2):
        fic = add_field_inventory(db, c, f"Block-{i}", plots=5, fic_id=fic)
    db.commit()
    return c


def _same_except_volatile(a: dict, b: dict) -> bool:
    """Structural equality ignoring ``input_token``/``generated_at``."""
    ca, cb = dict(a), dict(b)
    for d in (ca, cb):
        d.pop("input_token", None)
        d.pop("generated_at", None)
    return ca == cb


def _get_block(db, calc, name) -> ForestBlock:
    return (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calc.id, ForestBlock.block_name == name)
        .one()
    )


def _by_name(blobs: dict) -> dict[str, dict]:
    return {b["block_name"]: b for b in blobs["blocks"]}


# ── subtests (plan §6 a–e) ──────────────────────────────────────────────────
def test_no_edits_byte_equal_baseline(db):
    calc = _calc_with_blocks(db, _user(db))
    sfm = build_sfm(calc, db)
    usr = build_sfm(calc, db, variant="user")

    assert {b["block_name"] for b in sfm["blocks"]} == {"Block-1", "Block-2"}
    assert {b["block_name"] for b in usr["blocks"]} == {"Block-1", "Block-2"}
    assert usr["version"] == sfm["version"] == SFM_BLOCK_VERSION
    assert usr["zone_by_block"] == sfm["zone_by_block"]
    assert usr["blocks"] == sfm["blocks"]
    assert usr["felling_series"] == sfm["felling_series"]
    assert usr["forest_summary"] == sfm["forest_summary"]
    assert _same_except_volatile(usr, sfm)


def test_edited_band_changes_only_that_block(db):
    calc = _calc_with_blocks(db, _user(db))
    build_sfm(calc, db)  # persist baseline first
    blk = _get_block(db, calc, "Block-1")
    blk.dominant_slope_band = 4
    db.add(blk)
    db.commit()

    sfm = build_sfm(calc, db)
    usr = build_sfm(calc, db, variant="user")

    assert usr["zone_by_block"]["Block-1"]["slope_band"] == 4
    assert sfm["zone_by_block"]["Block-1"]["slope_band"] == 1  # baseline untouched
    assert usr["zone_by_block"]["Block-2"] == sfm["zone_by_block"]["Block-2"]

    # Block-2's OWN zone/inputs/orientation are untouched by Block-1's edit --
    # that's the invariant this test protects. Since 2026-09-14, band 4 forces
    # Conservation + felling-series exclusion for EVERY type, not just
    # 8/9/10/13 -- so when Block-1 (same effective_type_no as Block-2 in this
    # fixture) leaves the shared production stratum, the *aggregate* felling-
    # series numbers Block-2 reports (felling_series_id, prescription.yield_pct)
    # legitimately shift too, because they're computed over the remaining
    # group. That ripple is expected and is a property of type-grouped yield
    # regulation generally, not something this test is about.
    base_by_name = _by_name(sfm)
    usr_by_name = _by_name(usr)
    unaffected_keys = {"block_name", "effective_type_no", "orientation", "inputs"}
    for key in unaffected_keys:
        assert usr_by_name["Block-2"][key] == base_by_name["Block-2"][key], key


def test_management_orientation_override_updates_orientation_only(db):
    """SV-1.2 wiring: the user variant honours ``forest_blocks.management_orientation``
    for the edited block only; baseline and every other block are untouched."""
    calc = _calc_with_blocks(db, _user(db))
    build_sfm(calc, db)
    blk = _get_block(db, calc, "Block-1")
    blk.management_orientation = "west"
    db.add(blk)
    db.commit()

    sfm = build_sfm(calc, db)
    usr = build_sfm(calc, db, variant="user")

    assert usr["blocks"][0]["block_name"] == "Block-1"
    assert usr["blocks"][0]["orientation"] == "west"
    assert sfm["blocks"][0]["orientation"] != "west"  # baseline unaffected
    if sfm["blocks"][0]["orientation"] is not None:
        assert usr["blocks"][0]["orientation"] != sfm["blocks"][0]["orientation"]
    assert usr["blocks"][1] == sfm["blocks"][1]  # Block-2 identical


def test_caches_are_independent(db):
    calc = _calc_with_blocks(db, _user(db))
    first = build_sfm(calc, db, variant="user")
    assert first["input_token"].endswith("|user")

    # served from cache → identical content AND the same generated_at (no rebuild)
    second = build_sfm(calc, db, variant="user")
    assert second == first
    assert second["generated_at"] == first["generated_at"]

    baseline = build_sfm(calc, db)
    assert baseline["input_token"] == first["input_token"].removesuffix("|user")

    rebuilt_user = build_sfm(calc, db, variant="user", force=True)
    assert rebuilt_user["generated_at"] != first["generated_at"]  # force rebuilt
    assert calc.result_data[SFM_RESULT_KEY] == baseline  # baseline blob untouched
    assert calc.result_data[SFM_USER_KEY] == rebuilt_user
    assert (calc.result_data[SFM_USER_KEY]["input_token"] or "").endswith("|user")


def test_user_blob_absent_until_variant_requested(db):
    calc = _calc_with_blocks(db, _user(db))
    build_sfm(calc, db)
    assert SFM_USER_KEY not in (calc.result_data or {})
    build_sfm(calc, db, variant="user")
    assert set(calc.result_data) >= {SFM_RESULT_KEY, SFM_USER_KEY}


def test_carry_forward_from_same_variant_only(db):
    """A prior blob in one variant carries its overrides when *that* variant is
    force-rebuilt; the other variant still reads the same overrides for its own
    force-rebuild (per-block override parity), with no cross-variant cache hit."""
    calc = _calc_with_blocks(db, _user(db))
    _seed_override_blob(db, calc, SFM_RESULT_KEY)
    _seed_override_blob(db, calc, SFM_USER_KEY)

    sfm = build_sfm(calc, db, force=True)
    usr = build_sfm(calc, db, variant="user", force=True)

    for key, blob in ((SFM_RESULT_KEY, sfm), (SFM_USER_KEY, usr)):
        b2 = next(x for x in blob["blocks"] if x["block_name"] == "Block-2")
        assert b2["override_type_no"] == 4  # carried from its own prior blob
        assert b2["override_crown_density_pct"] == 82
        b1 = next(x for x in blob["blocks"] if x["block_name"] == "Block-1")
        assert b1["override_type_no"] is None
    assert calc.result_data[SFM_RESULT_KEY] == sfm
    assert calc.result_data[SFM_USER_KEY] == usr


def _seed_override_blob(db, calc, key: str) -> None:
    """Plant a prior blob with a Block-2 override (as the PATCH path would leave
    it) so a force rebuild has something to carry forward."""
    prior = build_sfm(calc, db, variant=("user" if key == SFM_USER_KEY else "baseline"))
    rd = dict(calc.result_data or {})
    b2 = next(b for b in prior["blocks"] if b["block_name"] == "Block-2")
    b2.update(
        override_type_no=4,
        override_crown_density_pct=82,
        override_origin="natural",
    )
    prior["blocks"] = prior["blocks"]
    rd[key] = prior
    calc.result_data = rd
    db.add(calc)
    db.commit()


def test_invalidate_drops_both(db):
    calc = _calc_with_blocks(db, _user(db))
    build_sfm(calc, db)
    build_sfm(calc, db, variant="user")
    assert set(calc.result_data) >= {SFM_RESULT_KEY, SFM_USER_KEY}
    invalidate_sfm(calc.id, db)
    assert SFM_RESULT_KEY not in calc.result_data
    assert SFM_USER_KEY not in calc.result_data
    assert build_sfm(calc, db)["blocks"]  # rebuilds cleanly