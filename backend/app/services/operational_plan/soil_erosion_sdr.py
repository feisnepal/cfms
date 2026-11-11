"""Sediment Delivery Ratio (SDR) — how much gross RUSLE soil loss reaches the
stream network (P6c).

RUSLE gives *gross on-site* detachment; only a fraction is delivered downslope
to a channel. This is an InVEST-style connectivity SDR (Borselli et al. 2008;
Vigiak et al. 2012; Hamel et al. 2015 — the InVEST SDR model):

    IC_i  = log10( D_up_i / D_dn_i )
    D_up_i = W_i · S_i · √A_i                         (upslope, local terms)
    D_dn_i = Σ_{path i→stream}  d_k / (W_k · S_k)     (downslope, along the D8 path)
    SDR_i = SDR_max / (1 + exp((IC_0 − IC_i) / k))

``W`` is the cover-management factor C (dense cover ⇒ large D_dn ⇒ low SDR ⇒
the forest disconnects sediment from the stream), floored at ``sdr_w_floor``.
Stream cells = rasterised ``river.river84`` ∪ (D8 accumulation ≥
``sdr_channel_accum_cells``). Reuses the D8 network from ``soil_erosion_d8``.

Opt-in via ``params.sdr_enabled`` (default False); pure numpy, no new deps.
"""

from __future__ import annotations

import numpy as np

from app.services.operational_plan.soil_erosion_config import SoilErosionParams


def _stream_mask(
    river_grid: np.ndarray, acc: np.ndarray, params: SoilErosionParams
) -> np.ndarray:
    """Bool grid of channel cells: any rasterised river84 pixel, plus cells whose
    D8 contributing area exceeds the channel-initiation threshold."""
    riv = np.asarray(river_grid, dtype=bool) if river_grid is not None else None
    ch = np.isfinite(acc) & (acc >= float(params.sdr_channel_accum_cells))
    return ch if riv is None else (riv | ch)


def _d_dn(
    tgt: np.ndarray,
    is_diag: np.ndarray,
    stream_flat: np.ndarray,
    resist: np.ndarray,
    cell_m: float,
    nodata_flat: np.ndarray,
    dem_f_flat: np.ndarray,
) -> np.ndarray:
    """Downslope component D_dn per cell: Σ d_k/(W_k·S_k) along the D8 path to the
    first stream cell. Single O(n) pass in **ascending** filled-elevation order —
    a cell's D8 target is always lower, so its D_dn is already final when reached.
    ``resist`` is ``1/(W·S)`` per cell (flat). Reaching the grid edge without a
    stream just terminates the sum (sediment leaves the AOI)."""
    n = tgt.size
    diag_len = cell_m * np.sqrt(2.0)
    d_dn = np.full(n, np.nan, dtype="float64")
    order = np.argsort(
        np.where(np.isfinite(dem_f_flat), dem_f_flat, np.inf), kind="stable"
    )
    for idx in order:
        if nodata_flat[idx]:
            continue
        if stream_flat[idx]:
            d_dn[idx] = 0.0
            continue
        step = diag_len if is_diag[idx] else cell_m
        t = tgt[idx]
        downstream = 0.0 if (t < 0 or stream_flat[t] or nodata_flat[t]) else d_dn[t]
        d_dn[idx] = step * resist[idx] + (
            downstream if np.isfinite(downstream) else 0.0
        )
    return d_dn


def sdr_field(
    slope_pct: np.ndarray,
    c_factor: np.ndarray,
    flow: dict,
    river_grid: np.ndarray | None,
    cell_m: float,
    params: SoilErosionParams,
) -> np.ndarray:
    """Per-cell SDR (0–``sdr_max``). ``flow`` is ``soil_erosion_d8.flow_network``'s
    dict. NaN where slope / C / routing is undefined."""
    h, w = slope_pct.shape
    acc = flow["acc"]
    tgt = flow["tgt"]
    is_diag = flow["is_diag"]

    s = np.clip(np.tan(np.arctan(np.asarray(slope_pct) / 100.0)), 1e-4, None)
    wfac = np.clip(np.asarray(c_factor, dtype="float64"), params.sdr_w_floor, 1.0)
    a_m2 = np.clip((acc - 1.0), 0.0, None) * (cell_m * cell_m) + cell_m * cell_m

    with np.errstate(invalid="ignore", divide="ignore"):
        d_up = wfac * s * np.sqrt(a_m2)
        resist = 1.0 / (wfac * s)

    nodata = ~np.isfinite(slope_pct) | ~np.isfinite(c_factor)
    stream = _stream_mask(river_grid, acc, params)
    d_dn = _d_dn(
        tgt,
        is_diag,
        stream.ravel(),
        resist.ravel(),
        cell_m,
        nodata.ravel(),
        flow["dem_f"].ravel(),
    ).reshape(h, w)

    with np.errstate(invalid="ignore", divide="ignore"):
        ic = np.log10(d_up / d_dn)
        sdr = params.sdr_max / (1.0 + np.exp((params.sdr_ic0 - ic) / params.sdr_k))

    sdr = np.where(stream, params.sdr_max, sdr)  # sediment in a channel is delivered
    sdr = np.where(
        np.isfinite(sdr) & ~nodata, np.clip(sdr, 0.0, params.sdr_max), np.nan
    )
    return sdr


__all__ = ["sdr_field"]
