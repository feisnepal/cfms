"""SFM build_sfm / get_sfm / invalidate_sfm (P2). Uses the test DB."""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from tests.sfm_field_fixture import add_field_inventory
from app.services.sustainable_fm import sfm_service as svc
from app.services.sustainable_fm.sfm_service import build_sfm, get_sfm, invalidate_sfm


# ── fixtures ─────────────────────────────────────────────────────────────
def _calc_with_stem_block(db, *, group="Shorea robusta"):
    u = User(
        email=f"p2{uuid.uuid4().hex[:8]}@t.com",
        full_name="P2",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=u.id,
        uploaded_filename="p2.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    poly = Polygon([(84, 27), (84.02, 27), (84.02, 27.02), (84, 27.02)])
    block = ForestBlock(
        calculation_id=calc.id,
        name="Block-1",
        block_name="Block-1",
        geometry=from_shape(poly, srid=4326),
        area_hectares=100.0,
        area_sqm=1_000_000.0,
        index=1,
        division_level=1,
    )
    db.add(block)
    db.flush()

    add_field_inventory(db, calc, "Block-1", species=group, plots=5)
    db.flush()
    return calc, block


# ── build ───────────────────────────────────────────────────────────────
def test_build_shape(db):
    calc, _ = _calc_with_stem_block(db)
    sfm = build_sfm(calc, db)
    assert sfm["version"] == 1
    assert sfm["params_hash"] and sfm["input_token"]
    assert sfm["source"] == "field_inventory"
    # P3 second pass fills these
    assert isinstance(sfm["felling_series"], list) and sfm["felling_series"]
    assert sfm["forest_summary"].get("dominant_type_no") in range(1, 15)
    assert set(sfm["zone_by_block"]) == {"Block-1"}

    (b,) = sfm["blocks"]
    assert b["block_name"] == "Block-1"
    assert b["proposed_type_no"] in range(1, 15)
    assert b["effective_type_no"] == b["proposed_type_no"]
    assert b["override_type_no"] is None
    assert b["prescription"] is not None  # P3 fills it
    assert b["prescription"]["type_no"] == b["effective_type_no"]
    assert b["inputs"]["dominant_group"] == "SAL"


def test_orientation_justification_names_the_full_reasoning_chain(db):
    """Owner request, 2026-09-15 ("we need every detail... the logic... the
    decision"): the read-only justification must trace species -> zone ->
    slope band -> forest type (by name) -> the rule that produced the final
    orientation, not just a terse one-clause label."""
    calc, _ = _calc_with_stem_block(db)
    sfm = build_sfm(calc, db)
    (b,) = sfm["blocks"]

    just_en = b["orientation_justification_en"]
    just_ne = b["orientation_justification_ne"]
    assert just_en and just_ne

    # Species (dominant_group is "SAL" for this fixture).
    assert "SAL" in just_en
    assert "dominant" in just_en
    # Zone + altitude clause.
    assert "zone" in just_en
    # Slope band clause.
    assert "slope band" in just_en
    # Type reference (by number) + its real name, not just the number alone.
    type_no = b["effective_type_no"]
    assert f"type {type_no}" in just_en
    assert b["prescription"]["type_name_en"] not in ("", None)
    assert b["prescription"]["type_name_en"] in just_en
    # The base-orientation label the type carries in अनुसूची-१.
    assert "base:" in just_en
    # Nepali mirrors the same structure with real Devanagari content.
    assert f"सि.नं. {type_no}" in just_ne
    assert "भिरालो वर्ग" in just_ne


def test_build_persists_sqlalchemy_safe(db):
    calc, _ = _calc_with_stem_block(db)
    build_sfm(calc, db)
    db.expire_all()
    fresh = db.get(Calculation, calc.id)
    assert isinstance(fresh.result_data, dict)
    assert "sfm" in fresh.result_data
    assert fresh.result_data["sfm"]["blocks"][0]["block_name"] == "Block-1"


def test_cache_hit_skips_reclassify(db, monkeypatch):
    calc, _ = _calc_with_stem_block(db)
    build_sfm(calc, db)

    calls = {"n": 0}
    real = svc.classify

    def _spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(svc, "classify", _spy)
    out = get_sfm(calc, db)
    assert calls["n"] == 0  # served from cache
    assert out["source"] == "field_inventory"


def test_force_rebuilds(db, monkeypatch):
    calc, _ = _calc_with_stem_block(db)
    build_sfm(calc, db)
    calls = {"n": 0}
    real = svc.classify
    monkeypatch.setattr(
        svc,
        "classify",
        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1) or real(*a, **k)),
    )
    build_sfm(calc, db, force=True)
    assert calls["n"] == 1


def test_geometry_version_bump_invalidates_cache(db, monkeypatch):
    calc, _ = _calc_with_stem_block(db)
    build_sfm(calc, db)

    calc.geometry_version = (calc.geometry_version or 0) + 1
    db.add(calc)
    db.commit()

    calls = {"n": 0}
    real = svc.classify
    monkeypatch.setattr(
        svc,
        "classify",
        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1) or real(*a, **k)),
    )
    get_sfm(calc, db)
    assert calls["n"] == 1  # token changed → rebuilt


def test_override_carried_forward(db):
    calc, _ = _calc_with_stem_block(db)
    sfm = build_sfm(calc, db)
    proposed = sfm["blocks"][0]["proposed_type_no"]

    # user override, written SQLAlchemy-safe
    nd = dict(calc.result_data)
    nd["sfm"] = dict(nd["sfm"])
    nd["sfm"]["blocks"] = [dict(nd["sfm"]["blocks"][0], override_type_no=13)]
    calc.result_data = nd
    db.add(calc)
    db.commit()

    rebuilt = build_sfm(calc, db, force=True)
    b = rebuilt["blocks"][0]
    assert b["override_type_no"] == 13
    assert b["effective_type_no"] == 13
    assert b["proposed_type_no"] == proposed  # proposal itself unchanged


def test_invalidate_then_rebuild(db):
    calc, _ = _calc_with_stem_block(db)
    build_sfm(calc, db)
    assert "sfm" in calc.result_data

    invalidate_sfm(calc.id, db)
    db.expire_all()
    fresh = db.get(Calculation, calc.id)
    assert "sfm" not in (fresh.result_data or {})

    again = get_sfm(fresh, db)
    assert again["source"] == "field_inventory"


def test_invalidate_is_noop_without_sfm(db):
    calc, _ = _calc_with_stem_block(db)
    invalidate_sfm(calc.id, db)  # must not raise
    invalidate_sfm(uuid.uuid4(), db)  # unknown calc → no-op


def test_prior_source_when_no_inventory(db):
    calc, _ = _calc_with_stem_block(db)
    # drop the sample-plot inventory: the block now has no plots of its own
    db.execute(
        text("DELETE FROM field_inventory_calculations WHERE calculation_id = :c"),
        {"c": str(calc.id)},
    )
    db.commit()
    sfm = build_sfm(calc, db, force=True)
    assert sfm["source"] == "prior"
    blk = sfm["blocks"][0]
    # forest land without plots: no type (the raster prior survives only as a labelled estimate), plan not valid
    assert blk["state"] == "inventory_missing"
    assert blk["effective_type_no"] is None and blk["proposed_type_no"] is None
    assert blk["needs_review"] is True
    assert sfm["forest_summary"]["inventory_gaps"][0]["block_name"] == "Block-1"
