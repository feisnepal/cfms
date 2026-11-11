"""Tests for stratum_spec -- SFM §16 stratum classification."""

from __future__ import annotations

import uuid

import app.services.sustainable_fm.stratum_spec as mod
from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services.sustainable_fm.stratum_spec import (
    MIN_SAMPLES_PER_UNIT,
    STRATA,
    STRATUM_FLOOR_PCT,
    STRATUM_PLOT_SQM,
    classify_calc_units,
    stratum_for_unit,
)


# ── helpers ──────────────────────────────────────────────────────────────

def _user(db):
    u = User(
        email=f"strat{uuid.uuid4().hex[:8]}@t.com",
        full_name="S",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    return u


def _calc(db, sub_areas=None, sfm_blocks=None):
    u = _user(db)
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=u.id,
        uploaded_filename="s.csv",
        is_draft=False,
        structure_locked=False,
        result_data={
            "sub_areas": sub_areas or [],
            "sfm": {"blocks": sfm_blocks or []},
        },
    )
    db.add(calc)
    db.flush()
    return calc


def _block(db, calc_id, name, wc="production", mgmt_orientation=None):
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Polygon

    poly = Polygon([(84.0, 27.0), (84.02, 27.0), (84.02, 27.02), (84.0, 27.02)])
    b = ForestBlock(
        calculation_id=calc_id,
        name=name,
        block_name=name,
        geometry=from_shape(poly, srid=4326),
        area_hectares=10.0,
        index=1,
        working_circle=wc,
        management_orientation=mgmt_orientation,
    )
    db.add(b)
    db.flush()
    return b


# ── pure stratum_for_unit tests (no DB) ─────────────────────────────────

def test_stratum_protected_majority_wins_over_orientation():
    """majorityProtected sub-area + orientation Production → protection."""
    sub = [{"type": "protection"}]
    sentinel_wkt = "POLYGON((0 0,1 0,1 1,0 1,0 0))"

    orig = mod.classify_block_by_majority_area
    try:
        mod.classify_block_by_majority_area = lambda wkt, sa: True
        assert stratum_for_unit("B1", sentinel_wkt, "production", "Production", sub) == "protection"
    finally:
        mod.classify_block_by_majority_area = orig


def test_stratum_working_circle_protection_wins_over_orientation():
    """wc=protection + orientation Production → protection."""
    assert stratum_for_unit("B1", None, "protection", "Production", []) == "protection"


def test_stratum_orientation_protection():
    """No protected majority, wc=production, orientation=Protection → protection."""
    assert stratum_for_unit("B1", None, "production", "Protection", []) == "protection"


def test_stratum_orientation_conservation():
    """No protected, wc=production, orientation=Conservation → conservation."""
    assert stratum_for_unit("B1", None, "production", "Conservation", []) == "conservation"


def test_stratum_orientation_production():
    """No protected, wc=production, orientation=Production → production."""
    assert stratum_for_unit("B1", None, "production", "Production", []) == "production"


def test_stratum_orientation_none_defaults_production():
    """None/missing orientation + production wc → production."""
    assert stratum_for_unit("B1", None, "production", None, []) == "production"
    assert stratum_for_unit("B1", None, None, None, None) == "production"


def test_stratum_for_unit_missing_sub_areas():
    """sub_areas=None or empty → skip majority check, fall through to wc/orientation."""
    assert stratum_for_unit("B1", "POLYGON((0 0))", "production", None, None) == "production"
    assert stratum_for_unit("B1", "POLYGON((0 0))", "production", None, []) == "production"
    # wc=protection still works when sub_areas is empty
    assert stratum_for_unit("B1", "POLYGON((0 0))", "protection", None, []) == "protection"
    assert stratum_for_unit("B1", "POLYGON((0 0))", "protection", None, None) == "protection"


# ── constant-table tests ────────────────────────────────────────────────

def test_stratum_floor_table():
    assert STRATUM_FLOOR_PCT == {"production": 2.0, "conservation": 1.0, "protection": 0.5}


def test_stratum_plot_size_table():
    assert STRATUM_PLOT_SQM == {"production": 500, "conservation": 500, "protection": 100}


def test_stratum_min_samples_floor():
    assert MIN_SAMPLES_PER_UNIT == 5


def test_strata_tuple():
    assert STRATA == ("production", "conservation", "protection")


# ── classify_calc_units (DB-aware) ──────────────────────────────────────

def test_classify_calc_units_orientation_from_blocks(db):
    calc = _calc(db)
    _block(db, calc.id, "B1", wc="production", mgmt_orientation="Conservation")
    _block(db, calc.id, "B2", wc="production", mgmt_orientation="Protection")
    _block(db, calc.id, "B3", wc="production", mgmt_orientation="Production")

    units = [
        (1, None, "B1", 10.0),
        (2, None, "B2", 20.0),
        (3, None, "B3", 15.0),
    ]
    result = classify_calc_units(db, calc.id, units)
    assert result["B1"] == "conservation"
    assert result["B2"] == "protection"
    assert result["B3"] == "production"


def test_classify_calc_units_wc_protection_overrides_orientation(db):
    calc = _calc(db)
    _block(db, calc.id, "B1", wc="protection", mgmt_orientation="Production")

    units = [(1, None, "B1", 10.0)]
    result = classify_calc_units(db, calc.id, units)
    assert result["B1"] == "protection"


def test_classify_calc_units_sfm_orientation_fallback(db):
    """When management_orientation is NULL, fall back to SFM result_data orientation."""
    sfm_blocks = [{"block_name": "B1", "orientation": "Conservation"}]
    calc = _calc(db, sfm_blocks=sfm_blocks)
    _block(db, calc.id, "B1", wc="production", mgmt_orientation=None)

    units = [(1, None, "B1", 10.0)]
    result = classify_calc_units(db, calc.id, units)
    assert result["B1"] == "conservation"


def test_classify_calc_units_defaults_production(db):
    calc = _calc(db)
    _block(db, calc.id, "B1", wc="production", mgmt_orientation=None)

    units = [(1, None, "B1", 10.0)]
    result = classify_calc_units(db, calc.id, units)
    assert result["B1"] == "production"


def test_classify_calc_units_missing_calc_returns_production(db):
    """Non-existent calculation_id → all units default to production."""
    units = [(1, None, "B1", 10.0)]
    result = classify_calc_units(db, str(uuid.uuid4()), units)
    assert result["B1"] == "production"
