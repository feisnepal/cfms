"""Connectivity Sediment Delivery Ratio (P6c)."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.operational_plan import soil_erosion_d8 as d8
from app.services.operational_plan import soil_erosion_sdr as sdrm
from app.services.operational_plan.soil_erosion_config import (
    DEFAULT_PARAMS,
    SoilErosionParams,
)

P = SoilErosionParams(**{**DEFAULT_PARAMS.model_dump(), "sdr_enabled": True})


def _hillslope(h=10, w=6):
    """A planar slope draining down (row 0 high → row h-1 low)."""
    dem = np.tile(np.arange(h, 0, -1, dtype="float64")[:, None], (1, w))
    return dem


def test_stream_mask_combines_river_and_accumulation():
    acc = np.array([[1, 1, 1], [1, 900, 1], [1, 1, 1]], dtype="float64")
    riv = np.zeros((3, 3), bool)
    riv[0, 0] = True
    m = sdrm._stream_mask(riv, acc, P)  # threshold default 500
    assert m[0, 0]  # river pixel
    assert m[1, 1]  # accumulation ≥ 500
    assert not m[2, 2]


def test_stream_mask_falls_back_to_accumulation_only():
    acc = np.full((3, 3), 1.0)
    acc[1, 1] = 1000
    m = sdrm._stream_mask(None, acc, P)
    assert m[1, 1] and not m[0, 0]


def test_sdr_is_bounded_and_streams_get_sdr_max():
    dem = _hillslope()
    flow = d8.flow_network(dem, np.zeros_like(dem, bool))
    slope = np.full(dem.shape, 20.0)
    c = np.full(dem.shape, 0.1)
    river = np.zeros(dem.shape, bool)
    river[-1, :] = True  # the bottom row is the stream
    sdr = sdrm.sdr_field(slope, c, flow, river, 30.0, P)
    fin = np.isfinite(sdr)
    assert sdr[fin].min() >= 0.0
    assert sdr[fin].max() <= P.sdr_max + 1e-9
    assert np.allclose(sdr[-1, :], P.sdr_max)  # stream cells


def test_denser_cover_lowers_sdr():
    dem = _hillslope()
    flow = d8.flow_network(dem, np.zeros_like(dem, bool))
    slope = np.full(dem.shape, 20.0)
    river = np.zeros(dem.shape, bool)
    river[-1, :] = True

    bare = sdrm.sdr_field(slope, np.full(dem.shape, 0.4), flow, river, 30.0, P)
    dense = sdrm.sdr_field(slope, np.full(dem.shape, 0.01), flow, river, 30.0, P)
    # compare the interior hillslope cells (exclude the stream row)
    b = np.nanmean(bare[:-1])
    d = np.nanmean(dense[:-1])
    assert b > d


def test_d_dn_topo_pass_sums_along_the_path():
    # a 1-column strip draining straight down to a stream at the last cell
    n = 5
    tgt = np.array([1, 2, 3, 4, -1])  # each cell → the next; last is the stream
    is_diag = np.zeros(n, bool)
    stream = np.array([False, False, False, False, True])
    resist = np.array([2.0, 2.0, 2.0, 2.0, 0.0])
    dem_f = np.arange(n, 0, -1, dtype="float64")  # descending → path order
    d_dn = sdrm._d_dn(tgt, is_diag, stream, resist, 10.0, np.zeros(n, bool), dem_f)
    assert d_dn[4] == 0.0  # stream
    assert d_dn[3] == pytest.approx(10.0 * 2.0)  # one step from the stream
    assert d_dn[2] == pytest.approx(2 * 10.0 * 2.0)  # two steps
    assert d_dn[0] == pytest.approx(4 * 10.0 * 2.0)


def test_sdr_disabled_by_default():
    assert DEFAULT_PARAMS.sdr_enabled is False
