"""RUSLE factor kernels — hand-worked checks, CRS correctness, NaN propagation.

``app.services.operational_plan.soil_erosion`` P0: pure vectorised kernels, no
DB / rasterio. Expected values below are worked by hand from the equations in
``RUSLE_SOIL_LOSS_IMPLEMENTATION_PLAN.md`` §2 P0-lit.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.services.operational_plan import soil_erosion as se
from app.services.operational_plan.soil_erosion_config import (
    DEFAULT_PARAMS,
    SoilErosionParams,
)

P = DEFAULT_PARAMS


# ── R — rainfall erosivity ──────────────────────────────────────────────────
def test_r_mfi_arnoldus_hand_value():
    # MFI = 60 → R = 0.07969 · 60^1.847
    expect = 0.07969 * 60.0**1.847
    # feed P and concentration so that P·concentration == 60
    r = se.factor_r(p_mm=1200.0, concentration=60.0 / 1200.0, params=P)
    assert r == pytest.approx(expect, rel=1e-6)
    assert expect == pytest.approx(153.2, rel=0.02)  # sanity


def test_r_annual_regression_hand_value():
    params = SoilErosionParams(**{**P.model_dump(), "r_method": "annual_regression"})
    r = se.factor_r(p_mm=2089.0, concentration=None, params=params)
    assert r == pytest.approx(0.35 * 2089.0 + 38.5, rel=1e-9)
    assert float(r) == pytest.approx(769.65, rel=1e-4)


def test_r_method_spread_monsoon():
    # a monsoon-concentrated year: 70 % of rain in one quarter
    q = (1400.0, 400.0, 100.0, 100.0)
    p_mm = sum(q)
    conc = se.seasonality_concentration(*q)
    r_mfi = se.factor_r(p_mm, conc, P)
    r_reg = se.factor_r(
        p_mm,
        None,
        SoilErosionParams(**{**P.model_dump(), "r_method": "annual_regression"}),
    )
    # Arnoldus power form runs several-fold hotter than the temperate regression
    assert float(r_mfi) > 3.0 * float(r_reg)


def test_seasonality_concentration_even_year():
    # equal quarters → Σf_q² = 4·(0.25)² = 0.25 → /3
    assert float(se.seasonality_concentration(500, 500, 500, 500)) == pytest.approx(
        0.25 / 3.0
    )
    # concentrated year has a higher concentration index
    even = se.seasonality_concentration(500, 500, 500, 500)
    conc = se.seasonality_concentration(1700, 100, 100, 100)
    assert float(conc) > float(even)


def test_seasonality_concentration_zero_rain_is_nan():
    assert math.isnan(float(se.seasonality_concentration(0, 0, 0, 0)))


# ── K — soil erodibility (EPIC / Williams) ─────────────────────────────────
def test_k_williams_silt_loam_band():
    # बृन्दाबन-like: sand 35 / silt 44 / clay 21 %, OC 1.22 %
    k = float(se.factor_k_williams(35.0, 44.0, 21.0, 1.22))
    assert 0.02 < k < 0.055  # EPIC K for a silt-rich loam
    assert k == pytest.approx(0.0389, abs=0.003)  # hand value


def test_k_more_silt_is_more_erodible():
    k_silt = float(se.factor_k_williams(20.0, 60.0, 20.0, 1.0))
    k_clay = float(se.factor_k_williams(20.0, 20.0, 60.0, 1.0))
    assert k_silt > k_clay


def test_k_clamped_to_ceiling():
    params = SoilErosionParams(**{**P.model_dump(), "k_ceiling": 0.02})
    k = float(se.factor_k(35.0, 44.0, 21.0, 1.22, params))
    assert k == pytest.approx(0.02)


def test_k_no_texture_is_nan():
    assert math.isnan(float(se.factor_k_williams(0.0, 0.0, 0.0, 1.0)))
    assert math.isnan(float(se.factor_k(0.0, 0.0, 0.0, 1.0, P)))


# ── LS — McCool S × classic USLE L ─────────────────────────────────────────
def test_mccool_s_two_branches_and_monotone():
    s5 = float(se.mccool_s(5.0))  # < 9 % → low branch
    s30 = float(se.mccool_s(30.0))  # ≥ 9 % → high branch
    assert s5 == pytest.approx(10.8 * math.sin(math.atan(0.05)) + 0.03, rel=1e-9)
    assert s30 == pytest.approx(16.8 * math.sin(math.atan(0.30)) - 0.50, rel=1e-9)
    assert s30 > s5 > 0


def test_usle_l_unit_plot_is_one():
    # λ = 22.13 m → L = 1 for every slope band
    for slope in (0.5, 2.0, 4.0, 12.0):
        assert float(se.usle_l(22.13, slope, P)) == pytest.approx(1.0, rel=1e-9)


def test_usle_l_grows_with_length_and_caps():
    # 4× unit plot at slope ≥ 5 % (m = 0.5) → L = 2
    assert float(se.usle_l(4 * 22.13, 10.0, P)) == pytest.approx(2.0, rel=1e-9)
    # a 500 m slope is clipped to the 122 m cap
    capped = float(se.usle_l(500.0, 10.0, P))
    assert capped == pytest.approx((122.0 / 22.13) ** 0.5, rel=1e-9)
    assert capped < float(
        se.usle_l(
            500.0,
            10.0,
            SoilErosionParams(**{**P.model_dump(), "slope_length_cap_m": 305.0}),
        )
    )


def test_factor_ls_combines_l_and_s():
    ls = float(se.factor_ls(slope_pct=10.0, slope_length_m=4 * 22.13, params=P))
    assert ls == pytest.approx(2.0 * float(se.mccool_s(10.0)), rel=1e-9)


# ── slope from DEM — CRS correctness ──────────────────────────────────────
def test_slope_pct_from_dem_needs_metric_spacing():
    """A ramp rising exactly one metric cell-width per column is a 45° (100 %)
    slope. The naïve degree-spacing gradient is off by ~10^4."""
    res_lon = res_lat = 0.00025  # ° ; ~27 m at 28 °N
    mean_lat = 28.0
    dx_m, dy_m = se.metric_cell_size(res_lon, res_lat, mean_lat)
    cols = np.arange(12)
    dem = np.tile(cols * dx_m, (10, 1)).astype("float64")  # rises dx_m per column

    slope_ok = se.slope_pct_from_dem(dem, dx_m, dy_m)
    assert np.allclose(slope_ok, 100.0, atol=0.5)

    slope_naive = se.slope_pct_from_dem(dem, res_lon, res_lat)
    assert np.median(slope_naive) > 10_000.0  # wrong by ~cos·m-per-deg


def test_metric_cell_size_longitude_shrinks_with_latitude():
    dx_eq, _ = se.metric_cell_size(0.001, 0.001, 0.0)
    dx_hi, _ = se.metric_cell_size(0.001, 0.001, 60.0)
    assert dx_hi == pytest.approx(dx_eq * math.cos(math.radians(60.0)), rel=1e-9)


# ── C — cover management ─────────────────────────────────────────────────
def test_c_lookup_by_esa_class():
    cls = np.array([10, 40, 60, 999])
    c = se.factor_c(cls, P)
    assert list(c) == [0.03, 0.21, 0.45, P.c_default]


def test_c_canopy_modifier_reduces_closed_forest():
    # ESA 10 (tree cover), tall closed canopy → C × canopy_c_min_multiplier
    c_closed = se.factor_c(np.array([10]), P, canopy_h_m=np.array([20.0]))[0]
    assert c_closed == pytest.approx(0.03 * P.canopy_c_min_multiplier, rel=1e-9)
    # open canopy → unchanged
    c_open = se.factor_c(np.array([10]), P, canopy_h_m=np.array([3.0]))[0]
    assert c_open == pytest.approx(0.03, rel=1e-9)
    # midway → between the two
    c_mid = se.factor_c(np.array([10]), P, canopy_h_m=np.array([9.0]))[0]
    assert c_open > c_mid > c_closed


def test_c_canopy_modifier_only_touches_forest_classes():
    # ESA 40 (cropland) is not a canopy_modifier_class → C unchanged by canopy
    c = se.factor_c(np.array([40]), P, canopy_h_m=np.array([20.0]))[0]
    assert c == pytest.approx(0.21, rel=1e-9)


def test_c_disturbance_bump_off_by_default():
    dr = np.array([True, True])
    base = se.factor_c(np.array([10, 10]), P, disturbed_recent=dr)
    assert np.all(base == 0.03)  # default bump = 1.0 → no change


def test_c_disturbance_bump_raises_c_on_recent_loss_only():
    from app.services.operational_plan.soil_erosion_config import SoilErosionParams

    params = SoilErosionParams(**{**P.model_dump(), "c_disturbance_bump": 2.5})
    cls = np.array([10, 10, 40])
    dr = np.array([True, False, True])
    c = se.factor_c(cls, params, disturbed_recent=dr)
    assert c[0] == pytest.approx(min(0.03 * 2.5, 1.0))  # bumped
    assert c[1] == pytest.approx(0.03)  # not disturbed
    assert c[2] == pytest.approx(min(0.21 * 2.5, 1.0))  # cropland bumped too
    # never exceeds 1.0
    hi = SoilErosionParams(**{**P.model_dump(), "c_disturbance_bump": 5.0})
    assert se.factor_c(np.array([60]), hi, disturbed_recent=np.array([True]))[0] <= 1.0


# ── P — support practice ────────────────────────────────────────────────
def test_p_cropland_slope_bands():
    cls = np.array([40, 40, 40, 40])
    slope = np.array([5.0, 10.0, 20.0, 30.0])
    p = se.factor_p(cls, slope, P)
    assert list(p) == [0.55, 0.60, 0.95, 1.00]


def test_p_non_cropland_is_default():
    p = se.factor_p(np.array([10, 30, 60]), np.array([5.0, 15.0, 40.0]), P)
    assert np.all(p == P.p_default)


# ── A = R·K·LS·C·P ─────────────────────────────────────────────────────
def test_soil_loss_monotone_in_each_factor():
    base = dict(r=800.0, k=0.03, ls=2.0, c=0.1, p=0.8)
    a0 = float(se.soil_loss(**base))
    for key in base:
        bumped = dict(base)
        bumped[key] = base[key] * 1.5
        assert float(se.soil_loss(**bumped)) > a0


def test_soil_loss_nan_propagates():
    r = np.array([800.0, 800.0, 800.0])
    k = np.array([0.03, np.nan, 0.03])
    a = se.soil_loss(r, k, 2.0, 0.1, 0.8)
    assert math.isnan(float(a[1]))
    assert np.isfinite(a[0]) and np.isfinite(a[2])


def test_soil_loss_never_negative():
    a = se.soil_loss(-5.0, 0.03, 2.0, 0.1, 0.8)  # a negative R can't drive A < 0
    assert float(a) >= 0.0


# ── severity classification ────────────────────────────────────────────
def test_classify_severity_buckets_and_nodata():
    a = np.array([2.0, 7.0, 15.0, 33.0, 60.0, 200.0, np.nan])
    idx = se.classify_severity(a, P.severity_breaks)
    assert list(idx) == [0, 1, 2, 3, 4, 5, -1]


def test_classify_severity_matches_config_scalar_helper():
    for v in (2.0, 7.0, 15.0, 33.0, 60.0, 200.0):
        assert int(se.classify_severity(np.array([v]), P.severity_breaks)[0]) == (
            P.severity_class(v)
        )
