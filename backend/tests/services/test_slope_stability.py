"""Infinite-slope Factor of Safety kernels (P2) — no DB, no rasterio.

``app.services.operational_plan.slope_stability``: the FS equation at
limit equilibrium, its monotonic responses to m / z / root cohesion, the
regolith-depth models, the wetness-varied m, and the class / instability
reclass. Worked from ``HOUSEHOLD_VULNERABILITY_ANALYSIS_PLAN.md`` §2.2.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.operational_plan import slope_stability as ss
from app.services.operational_plan.hazard_vuln_config import (
    DEFAULT_PARAMS,
    FactorOfSafetyParams,
)

FP = DEFAULT_PARAMS.factor_of_safety
GW = FP.gamma_w_kn_m3


def _arr(x):
    return np.full((2, 2), float(x))


# ── factor_of_safety ─────────────────────────────────────────────────────
def test_fs_is_one_at_limit_equilibrium():
    # c' = 0, φ' = β, m = 0  →  numer = γz cos²β tanβ = denom  →  FS = 1
    beta = 25.0
    fs = ss.factor_of_safety(
        _arr(beta), _arr(0.0), _arr(beta), _arr(18.0), _arr(1.5), _arr(0.0), GW
    )
    np.testing.assert_allclose(fs, 1.0, rtol=1e-9)


def test_fs_falls_as_pore_pressure_rises():
    a = dict(
        slope_deg=_arr(30),
        c_kpa=_arr(5),
        phi_deg=_arr(30),
        gamma_kn_m3=_arr(18),
        z_m=_arr(1.5),
    )
    dry = ss.factor_of_safety(**a, m=_arr(0.0), gamma_w_kn_m3=GW)
    wet = ss.factor_of_safety(**a, m=_arr(0.9), gamma_w_kn_m3=GW)
    assert (wet < dry).all()


def test_fs_falls_as_regolith_deepens_when_cohesive():
    a = dict(
        slope_deg=_arr(30),
        c_kpa=_arr(8),
        phi_deg=_arr(28),
        gamma_kn_m3=_arr(18),
        m=_arr(0.7),
        gamma_w_kn_m3=GW,
    )
    shallow = ss.factor_of_safety(**a, z_m=_arr(0.8))
    deep = ss.factor_of_safety(**a, z_m=_arr(3.0))
    assert (deep < shallow).all()


def test_fs_rises_with_root_cohesion():
    a = dict(
        slope_deg=_arr(32),
        phi_deg=_arr(28),
        gamma_kn_m3=_arr(18),
        z_m=_arr(1.5),
        m=_arr(0.7),
        gamma_w_kn_m3=GW,
    )
    bare = ss.factor_of_safety(**a, c_kpa=_arr(3.0))
    rooted = ss.factor_of_safety(**a, c_kpa=_arr(3.0 + 3.0))
    assert (rooted > bare).all()


def test_fs_flat_ground_is_capped_stable():
    fs = ss.factor_of_safety(
        _arr(0.0), _arr(5), _arr(30), _arr(18), _arr(1.5), _arr(0.7), GW
    )
    np.testing.assert_allclose(fs, ss._FS_CAP)


def test_fs_nan_input_propagates():
    fs = ss.factor_of_safety(
        np.array([[np.nan, 30.0]]),
        _arr(5)[:1],
        _arr(30)[:1],
        _arr(18)[:1],
        _arr(1.5)[:1],
        _arr(0.7)[:1],
        GW,
    )
    assert np.isnan(fs[0, 0]) and np.isfinite(fs[0, 1])


# ── classify_fs / instability_index ─────────────────────────────────────
def test_classify_fs_three_classes_and_nan():
    fs = np.array([[0.8, 1.0, 1.3, 1.5, 2.4, np.nan]])
    c = ss.classify_fs(fs, [1.0, 1.5])
    np.testing.assert_array_equal(c, [[0, 1, 1, 2, 2, -1]])


def test_instability_index_forms():
    fs = np.array([[0.5, 1.0, 2.0, np.nan]])
    inv = ss.instability_index(fs, "inv_fs")
    np.testing.assert_allclose(inv[0, :3], [2.0, 1.0, 0.5])
    assert np.isnan(inv[0, 3])
    si = ss.instability_index(np.array([[0.3, 1.2, 5.0]]), "sinmap_si")
    np.testing.assert_allclose(si[0], [0.3, 1.2, 2.0])  # clipped to [0, 2]


# ── soil_depth_m ─────────────────────────────────────────────────────────
def test_soil_depth_constant():
    z = ss.soil_depth_m(
        np.array([[0.0, 45.0]]),
        FactorOfSafetyParams(soil_depth_model="constant", depth_constant_m=1.5),
    )
    np.testing.assert_allclose(z, 1.5)


def test_soil_depth_slope_linear_thins_and_clamps():
    p = FactorOfSafetyParams(
        soil_depth_model="slope_linear",
        depth_slope_z0_m=2.5,
        depth_slope_k=0.03,
        depth_min_m=0.5,
        depth_max_m=3.0,
    )
    z = ss.soil_depth_m(np.array([[0.0, 30.0, 80.0]]), p)
    assert z[0, 0] == pytest.approx(2.5)  # 2.5 - 0
    assert z[0, 1] == pytest.approx(2.5 - 0.9)  # 30° → 1.6
    assert z[0, 2] == pytest.approx(0.5)  # clamped to depth_min_m


# ── saturation_ratio ────────────────────────────────────────────────────
def test_saturation_constant_when_not_varied():
    p = FactorOfSafetyParams(saturation_ratio_m=0.6, saturation_twi_varied=False)
    m = ss.saturation_ratio(np.zeros((3, 3)), p, (3, 3))
    np.testing.assert_allclose(m, 0.6)


def test_saturation_twi_varied_ramps_and_keeps_mean():
    p = FactorOfSafetyParams(
        saturation_ratio_m=0.7,
        saturation_twi_varied=True,
        saturation_twi_low=0.4,
        saturation_twi_high=1.0,
    )
    twi = np.linspace(1.0, 20.0, 100).reshape(10, 10)
    m = ss.saturation_ratio(twi, p, (10, 10))
    assert m.min() < m.max()  # it varies
    assert m.argmin() < m.argmax()  # wetter where TWI higher
    assert np.mean(m) == pytest.approx(0.7, abs=0.05)  # mean held near base
    assert (m >= 0).all() and (m <= 1).all()


def test_saturation_twi_none_falls_back_to_constant():
    p = FactorOfSafetyParams(saturation_ratio_m=0.55, saturation_twi_varied=True)
    m = ss.saturation_ratio(None, p, (2, 2))
    np.testing.assert_allclose(m, 0.55)


# ── scenario_note ───────────────────────────────────────────────────────
def test_scenario_note_bilingual_and_mentions_scenario():
    ne, en = ss.scenario_note(FP, depth_mean_m=1.7)
    assert "1.7" in en and "scenario" in en.lower()
    assert "परिदृश्य" in ne
