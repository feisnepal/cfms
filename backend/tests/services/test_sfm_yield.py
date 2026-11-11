"""SFM yield regulation — match_step + build_series (P3).

``build_series`` needs the 14 seeded prescription rows (migration 082, present in
the test DB) but no ``forest_blocks`` — the working-circle / majority-protected
lookups return empty, so the yield maths run in isolation.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.services.sustainable_fm.prescription import load_prescriptions
from app.services.sustainable_fm.sfm_config import DEFAULT_PARAMS
from app.services.sustainable_fm.yield_regulation import build_series, match_step

P = DEFAULT_PARAMS


# ── match_step ──────────────────────────────────────────────────────────
def test_match_step():
    steps = [
        {"gs_per_ha_min": 200, "gs_per_ha_max": None, "pct": 2.0},
        {"gs_per_ha_min": 150, "gs_per_ha_max": 200, "pct": 1.0},
        {"gs_per_ha_min": None, "gs_per_ha_max": 150, "pct": 0.5},
    ]
    assert match_step(steps, 250.0) == 2.0
    assert match_step(steps, 200.0) == 2.0  # >= min, open top
    assert match_step(steps, 175.0) == 1.0
    assert match_step(steps, 149.9) == 0.5
    assert match_step(steps, 0.0) == 0.5
    assert match_step(None, 100.0) is None
    assert match_step([], 100.0) is None


# ── build_series ───────────────────────────────────────────────────────
def _calc(db, sub_areas=None):
    u = User(
        email=f"y{uuid.uuid4().hex[:8]}@t.com",
        full_name="Y",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=u.id,
        uploaded_filename="y.csv",
        is_draft=False,
        structure_locked=False,
        result_data={"sub_areas": sub_areas or []},
    )
    db.add(calc)
    db.flush()
    return calc


def _block(
    name,
    type_no,
    area_ha,
    gs_ge40_m3,
    *,
    band=1,
    regen=True,
    mother=None,
    source="stem_mapping",
):
    return {
        "block_name": name,
        "area_ha": area_ha,
        "effective_type_no": type_no,
        "_zone": {"slope_band": band},
        "inputs": {
            "gs_ge40_m3": gs_ge40_m3,
            "regen_adequate": regen,
            "mother_trees_per_ha": mother,
            "source": source,
        },
    }


def test_selection_series_matches_guideline_example(db):
    # अनुसूची-5.1: coupe GS40 4000, pct 2 %, C 10 → 800 (one felling area / yr)
    calc = _calc(db)
    pres = load_prescriptions(db)
    # Type 1 adequate: selection, C 10, >200 → 2 %. gs/ha 200 exactly.
    blocks = [_block("B1", 1, 20.0, 4000.0)]  # 4000 / 20 = 200 m3/ha
    series, summary = build_series(blocks, pres, calc, db, P)

    (s,) = series
    assert s["type_no"] == 1 and s["branch"] == "adequate"
    assert s["method"] == "selection_felling_cycle"
    assert s["C"] == 10 and s["N"] == 10
    assert s["pct"] == 2.0
    assert s["annual_harvest_m3"] == pytest.approx(80.0)  # 4000 * 2% == GS40 * pct/100
    assert summary["total_annual_harvest_m3"] == pytest.approx(80.0)
    assert summary["production_area_ha"] == 20.0
    assert summary["dominant_type_no"] == 1


def test_multi_type_forest_sums_per_series(db):
    calc = _calc(db)
    pres = load_prescriptions(db)
    blocks = [
        _block("B1", 1, 100.0, 25000.0),  # type 1, 250 m3/ha → 2 % → 500
        _block(
            "B2", 2, 100.0, 12000.0, band=2
        ),  # type 2, 120 m3/ha → <200 → 0.5 % → 60
    ]
    series, summary = build_series(blocks, pres, calc, db, P)
    by_t = {s["type_no"]: s for s in series}
    assert by_t[1]["annual_harvest_m3"] == pytest.approx(500.0)
    assert by_t[2]["annual_harvest_m3"] == pytest.approx(60.0)
    assert summary["total_annual_harvest_m3"] == pytest.approx(560.0)
    assert summary["type_area_breakdown"] == {"1": 100.0, "2": 100.0}


def test_protection_type_3_yields_zero_and_leaves_production(db):
    calc = _calc(db)
    pres = load_prescriptions(db)
    blocks = [
        _block("B1", 1, 50.0, 10000.0),
        _block("B2", 3, 30.0, 6000.0, band=3),  # type 3 → protection
    ]
    series, summary = build_series(blocks, pres, calc, db, P)
    by_t = {s["type_no"]: s for s in series}
    assert by_t[3]["annual_harvest_m3"] == 0.0
    assert by_t[3]["area_ha"] == 0.0
    assert summary["protection_area_ha"] == 30.0
    assert summary["production_area_ha"] == 50.0
    assert summary["total_annual_harvest_m3"] == by_t[1]["annual_harvest_m3"]


def test_band4_of_a_slope45_type_is_protection(db):
    calc = _calc(db)
    pres = load_prescriptions(db)
    # Type 8 natural pine, band 4 → salvage-only stratum
    blocks = [_block("B1", 8, 40.0, 12000.0, band=4, source="stem_mapping")]
    series, summary = build_series(blocks, pres, calc, db, P)
    assert summary["protection_area_ha"] == 40.0
    assert summary["production_area_ha"] == 0.0
    assert all(s["annual_harvest_m3"] in (0.0, None) for s in series)


def test_prior_only_group_has_no_number(db):
    calc = _calc(db)
    pres = load_prescriptions(db)
    blocks = [_block("B1", 1, 30.0, None, source="prior", regen=None)]
    series, summary = build_series(blocks, pres, calc, db, P)
    (s,) = series
    assert s["annual_harvest_m3"] is None
    assert "इन्भेन्ट्री" in s["note_ne"]
    assert summary["total_annual_harvest_m3"] == 0.0


def test_shelterwood_subtracts_mother_trees(db):
    calc = _calc(db)
    pres = load_prescriptions(db)
    # Type 8 inadequate → shelterwood, R 10. Force branch (ख) with regen=False.
    blocks = [_block("B1", 8, 100.0, 50000.0, regen=False, mother=2.0)]
    series, summary = build_series(blocks, pres, calc, db, P)
    (s,) = series
    assert s["branch"] == "inadequate"
    assert s["method"] == "shelterwood_periodic_block"
    assert s["R"] == 10 and s["N"] == 10
    # pb_gs = 50000/10 = 5000 ; mother = 2/ha * (100/10 ha) * 1.2 m3 = 24 ; (5000-24)/10
    assert s["annual_harvest_m3"] == pytest.approx((5000.0 - 24.0) / 10.0, abs=1e-3)
