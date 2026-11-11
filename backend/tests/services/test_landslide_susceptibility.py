"""LSI pure kernels (P1) — no DB, no rasterio.

``app.services.operational_plan.landslide_susceptibility``: reclass rules,
curvature / TWI on a synthetic DEM, the exact numpy EDT, AHP eigenvector +
consistency ratio, the missing-layer-tolerant weighted overlay, and the
score → class reclass. Expected values are worked from
``HOUSEHOLD_VULNERABILITY_ANALYSIS_PLAN.md`` §2.1.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.operational_plan import landslide_susceptibility as ls
from app.services.operational_plan.hazard_vuln_config import (
    LSI_FACTORS,
    DEFAULT_PARAMS,
    LandslideParams,
)

LP = DEFAULT_PARAMS.landslide


# ── rating_from_breaks ────────────────────────────────────────────────────
def test_rating_ascending_and_descending():
    v = np.array([5.0, 15.0, 25.0, 35.0, 45.0])
    br = [10.0, 20.0, 30.0, 40.0]
    np.testing.assert_array_equal(
        ls.rating_from_breaks(v, br, ascending=True), [1, 2, 3, 4, 5]
    )
    np.testing.assert_array_equal(
        ls.rating_from_breaks(v, br, ascending=False), [5, 4, 3, 2, 1]
    )


def test_rating_nan_propagates():
    out = ls.rating_from_breaks(
        np.array([np.nan, 25.0]), [10.0, 20.0, 30.0, 40.0], ascending=True
    )
    assert np.isnan(out[0]) and out[1] == 3


# ── EDT ───────────────────────────────────────────────────────────────────
def test_edt_exact_on_single_source():
    m = np.zeros((5, 5), bool)
    m[2, 2] = True
    d = ls.euclidean_distance_m(m, 1.0)
    assert d[2, 2] == 0.0
    np.testing.assert_allclose(d[2], [2, 1, 0, 1, 2])
    assert d[0, 0] == pytest.approx(np.sqrt(8.0))  # (2,2) away


def test_edt_scales_with_cell_size():
    m = np.zeros((4, 4), bool)
    m[0, 0] = True
    d10 = ls.euclidean_distance_m(m, 10.0)
    d1 = ls.euclidean_distance_m(m, 1.0)
    np.testing.assert_allclose(d10, d1 * 10.0)


def test_edt_all_false_is_inf():
    d = ls.euclidean_distance_m(np.zeros((3, 3), bool), 1.0)
    assert np.isinf(d).all()


# ── curvature / TWI on a synthetic DEM ───────────────────────────────────
def test_twi_higher_in_the_valley_than_on_the_ridge():
    # a V-shaped valley along the centre column
    x = np.abs(np.arange(11) - 5)[None, :].repeat(11, 0).astype(float)
    dem = x  # elevation rises away from the centre column
    slope_pct = ls.se.slope_pct_from_dem(dem, 30.0, 30.0)
    # more contributing area in the valley
    acc = np.ones_like(dem)
    acc[:, 5] = 50.0
    t = ls.twi(acc, slope_pct, 30.0)
    assert np.nanmean(t[:, 5]) > np.nanmean(t[:, 0])


def test_plan_curvature_negative_in_a_hollow():
    yy, xx = np.mgrid[0:21, 0:21]
    bowl = ((xx - 10) ** 2 + (yy - 10) ** 2).astype(float)  # convergent hollow
    _, plan = ls.profile_plan_curvature(bowl, 30.0, 30.0)
    # centre region of a bowl is convergent → plan curvature < 0 somewhere near it
    assert np.nanmin(plan[5:16, 5:16]) < 0


def test_spi_grows_with_contributing_area():
    slope = np.full((4, 4), 20.0)
    lo = ls.stream_power_index(np.full((4, 4), 1.0), slope, 30.0)
    hi = ls.stream_power_index(np.full((4, 4), 100.0), slope, 30.0)
    assert (hi > lo).all()


# ── AHP ───────────────────────────────────────────────────────────────────
def test_ahp_consistent_matrix_recovers_weights_cr_zero():
    w = LP.weights
    m = [[w[a] / w[b] for b in LSI_FACTORS] for a in LSI_FACTORS]
    wk, cr = ls.ahp_weights(m)
    assert cr == pytest.approx(0.0, abs=1e-9)
    assert wk["slope"] == pytest.approx(w["slope"], rel=1e-6)
    assert sum(wk.values()) == pytest.approx(1.0)


def test_ahp_inconsistent_matrix_has_positive_cr():
    # several intransitive triples (i≻j, j≻k, but k≻i) → CR clearly above the
    # exact 0.0 of a consistent matrix.
    n = len(LSI_FACTORS)
    m = [[1.0] * n for _ in range(n)]
    for i, j in [(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3)]:
        m[i][j], m[j][i] = 9.0, 1 / 9
    _, cr = ls.ahp_weights(m)
    assert cr > 0.02
    # and a perfectly consistent one is 0
    _, cr0 = ls.ahp_weights([[1.0] * n for _ in range(n)])
    assert cr0 == pytest.approx(0.0, abs=1e-9)


def test_effective_weights_switches_on_method():
    wo, cr0 = ls.effective_weights(LP)
    assert cr0 == 0.0 and sum(wo.values()) == pytest.approx(1.0)
    ahp = LandslideParams(method="ahp")
    wa, cra = ls.effective_weights(ahp)
    assert sum(wa.values()) == pytest.approx(1.0)


# ── weighted_overlay ─────────────────────────────────────────────────────
def test_overlay_drops_all_nan_factor_and_renormalises():
    ratings = {f: np.full((3, 3), 3.0) for f in LSI_FACTORS}
    ratings["aspect"] = np.full((3, 3), np.nan)
    weights = {f: 0.1 for f in LSI_FACTORS}
    out = ls.weighted_overlay(ratings, weights)
    np.testing.assert_allclose(out, 3.0)  # still 3, aspect ignored


def test_overlay_weights_the_factors():
    ratings = {f: np.full((2, 2), 1.0) for f in LSI_FACTORS}
    ratings["slope"] = np.full((2, 2), 5.0)
    weights = {f: 0.0 for f in LSI_FACTORS}
    weights["slope"] = 1.0
    out = ls.weighted_overlay(ratings, weights)
    np.testing.assert_allclose(out, 5.0)


def test_overlay_all_missing_is_nan():
    ratings = {f: np.full((2, 2), np.nan) for f in LSI_FACTORS}
    out = ls.weighted_overlay(ratings, {f: 0.1 for f in LSI_FACTORS})
    assert np.isnan(out).all()


# ── classify ─────────────────────────────────────────────────────────────
def test_classify_quantile_spreads_across_all_classes():
    s = np.arange(100, dtype=float).reshape(10, 10)
    c = ls.classify(s, method="quantile", n_classes=5, breaks_fixed=[], mask=None)
    assert c.min() == 0 and c.max() == 4
    # roughly equal counts per class
    counts = [int((c == i).sum()) for i in range(5)]
    assert all(15 <= n <= 25 for n in counts)


def test_classify_fixed_breaks_and_nan():
    s = np.array([[1.0, 2.5, 4.9, np.nan]])
    c = ls.classify(
        s, method="fixed", n_classes=5, breaks_fixed=[1.8, 2.6, 3.4, 4.2], mask=None
    )
    assert c[0, 0] == 0 and c[0, 1] == 1 and c[0, 2] == 4 and c[0, 3] == -1


def test_classify_equal_interval():
    s = np.linspace(0, 10, 100).reshape(10, 10)
    c = ls.classify(s, method="equal", n_classes=5, breaks_fixed=[], mask=None)
    assert c.min() == 0 and c.max() == 4


# ── lithology / texture rating ──────────────────────────────────────────
def test_lithology_fallback_rates_siwalik_high_and_gneiss_low():
    assert ls.lithology_rating("Lower Siwalik", LP) == 4
    assert ls.lithology_rating("Middle Siwalik1", LP) == 5
    assert ls.lithology_rating("Himal Gneiss", LP) == 2
    assert ls.lithology_rating("Granites", LP) == 2
    assert ls.lithology_rating("Kalikot Formation", LP) == LP.lithology_default_rating
    assert ls.lithology_rating(None, LP) == LP.lithology_default_rating


def test_lithology_explicit_override_wins():
    p = LandslideParams(lithology_ratings={"kalikot": 5})
    assert ls.lithology_rating("Kalikot Formation", p) == 5


def test_texture_rating_substring_longest_first():
    assert ls.texture_rating("Silt Loam", LP) == 4
    assert ls.texture_rating("Sandy Clay Loam", LP) == 3  # "clay loam" key
    assert ls.texture_rating("Loam", LP) == 3
    assert ls.texture_rating(None, LP) == LP.soil_texture_default_rating
