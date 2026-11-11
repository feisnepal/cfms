"""Vendored D8 hydrology + Desmet–Govers LS (P6a)."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.operational_plan import soil_erosion as se
from app.services.operational_plan import soil_erosion_d8 as d8
from app.services.operational_plan.soil_erosion_config import DEFAULT_PARAMS


def test_fill_depressions_drains_a_pit():
    dem = np.array(
        [
            [5, 5, 5, 5, 5],
            [5, 3, 3, 3, 5],
            [5, 3, 1, 3, 5],
            [5, 3, 3, 3, 5],
            [5, 5, 5, 5, 5],
        ],
        dtype="float64",
    )
    nod = np.zeros_like(dem, bool)
    f = d8.fill_depressions(dem, nod)
    # the pit centre was 1; after ε-fill it must sit above the rim so it drains
    assert f[2, 2] >= 5.0
    assert np.all(np.isfinite(f))


def test_fill_preserves_nodata_and_edge_values():
    dem = np.array([[2.0, 3.0, 4.0], [1.0, np.nan, 5.0], [0.0, 6.0, 7.0]])
    nod = ~np.isfinite(dem)
    f = d8.fill_depressions(dem, nod)
    assert np.isnan(f[1, 1])
    # a monotone-descending edge cell is unchanged
    assert f[2, 0] == pytest.approx(0.0)


def test_planar_tilt_accumulates_at_the_outlet():
    # elevation increases to the right → water flows left; column 0 is the outlet
    tilt = np.tile(np.arange(8, dtype="float64")[None, :], (5, 1))
    acc, is_diag = d8.contributing_area(tilt, np.zeros_like(tilt, bool))
    col_sum = acc.sum(axis=0)
    assert np.all(np.diff(col_sum) < 0)  # strictly decreasing away from the outlet
    assert acc[:, 0].sum() == pytest.approx(5 * 8)  # every cell drains through col 0
    assert not is_diag.any()  # a pure E–W tilt has no diagonal steps


def test_accumulation_conserves_cells():
    rng = np.random.default_rng(3)
    dem = rng.random((12, 15)) * 10
    nod = np.zeros_like(dem, bool)
    acc, _ = d8.contributing_area(dem, nod)
    # each cell counts itself once; the maximum accumulation cannot exceed n
    assert acc.min() >= 1.0
    assert acc.max() <= dem.size


def test_d8_target_is_downhill():
    rng = np.random.default_rng(9)
    dem = rng.random((10, 10)) * 5
    dem_f = d8.fill_depressions(dem, np.zeros_like(dem, bool))
    tgt, _ = d8.d8(dem_f, np.zeros_like(dem, bool))
    zf = dem_f.ravel()
    for k, t in enumerate(tgt):
        if t >= 0:
            assert zf[t] <= zf[k] + 1e-6  # never routes uphill


# ── Desmet–Govers LS kernel ──────────────────────────────────────────────
def test_desmet_govers_unit_cell_matches_classic_l():
    # a cell with no upslope inflow (acc = 1) and cardinal flow reduces to the
    # classic L = (D / 22.13)^m
    p = DEFAULT_PARAMS
    for slope, d_m in ((2.0, 30.0), (12.0, 30.0), (25.0, 20.0)):
        ls_dg = float(
            se.desmet_govers_ls(
                np.array([1.0]), np.array([slope]), np.array([False]), d_m, p
            )[0]
        )
        m = se._m_exponent(np.array([slope]), p)[0]
        expect = (d_m / 22.13) ** m * float(se.mccool_s(np.array([slope]))[0])
        assert ls_dg == pytest.approx(min(expect, p.ls_cap), rel=1e-6)


def test_desmet_govers_grows_with_contributing_area():
    p = DEFAULT_PARAMS
    ls = se.desmet_govers_ls(
        np.array([1.0, 10.0, 100.0]),
        np.full(3, 15.0),
        np.zeros(3, bool),
        30.0,
        p,
    )
    assert ls[0] < ls[1] < ls[2]


def test_desmet_govers_is_capped():
    p = DEFAULT_PARAMS
    ls = se.desmet_govers_ls(
        np.array([1e6]), np.array([45.0]), np.array([False]), 30.0, p
    )
    assert float(ls[0]) == pytest.approx(p.ls_cap)
