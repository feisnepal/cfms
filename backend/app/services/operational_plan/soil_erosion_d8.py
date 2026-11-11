"""Vendored pure-numpy D8 hydrology for the Desmet & Govers (1996) LS factor (P6).

`richdem` has no reliable cp311 Windows wheel (last release 0.3.4, 2021), so this
is a compact self-contained implementation:

* :func:`fill_depressions` — Priority-Flood + ε (Barnes, Lehman & Mulla 2014):
  every non-NoData cell ends with a monotone downhill path to the grid edge.
* :func:`d8` — steepest-descent pointer (8-neighbour), vectorised.
* :func:`flow_accum_cells` — contributing cell count, one pass in descending
  filled-elevation order.
* :func:`contributing_area` — the orchestrator ``build_grid`` calls: DEM (metric
  spacing) → filled → D8 → accumulation, returning ``(acc_cells, is_diag)``.

Screening-grade: the ε-fill routes flats/pits to the edge with a negligible
gradient, which is adequate for a RUSLE LS surface and avoids a full flat
resolution pass. All arrays are ``float64`` / ``int64``; NoData is ``NaN`` in.
"""

from __future__ import annotations

import heapq

import numpy as np

# 8-neighbour offsets and their planar distances (in cell units)
_NB = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
_DIAG = (True, False, True, False, False, True, False, True)


def fill_depressions(
    dem: np.ndarray, nodata: np.ndarray, eps: float = 1e-3
) -> np.ndarray:
    """Priority-Flood + ε. ``dem`` is elevation (m), ``nodata`` a bool mask.
    Returns a filled copy where every valid cell drains to the edge."""
    h, w = dem.shape
    out = np.full((h, w), np.inf, dtype="float64")
    closed = nodata.copy()
    pq: list[tuple[float, int, int]] = []

    def _push(i: int, j: int) -> None:
        if not closed[i, j]:
            closed[i, j] = True
            heapq.heappush(pq, (float(dem[i, j]), i, j))

    for i in range(h):
        _push(i, 0)
        _push(i, w - 1)
    for j in range(w):
        _push(0, j)
        _push(h - 1, j)

    while pq:
        e, i, j = heapq.heappop(pq)
        out[i, j] = e
        for di, dj in _NB:
            ni, nj = i + di, j + dj
            if 0 <= ni < h and 0 <= nj < w and not closed[ni, nj]:
                closed[ni, nj] = True
                heapq.heappush(pq, (max(float(dem[ni, nj]), e + eps), ni, nj))
    out[nodata] = np.nan
    return out


def d8(dem_f: np.ndarray, nodata: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Steepest-descent D8 pointer over the filled DEM.

    Returns ``(target_flat, is_diag)`` — ``target_flat[k]`` is the flat index of
    cell *k*'s downslope neighbour (or ``-1`` for NoData / a cell with no lower
    neighbour), ``is_diag`` True where that step is diagonal."""
    h, w = dem_f.shape
    n = h * w
    z = dem_f  # (h, w)
    best_slope = np.full((h, w), -np.inf, dtype="float64")
    best_k = np.full((h, w), -1, dtype="int64")

    for k, (di, dj) in enumerate(_NB):
        shifted = np.full((h, w), np.nan, dtype="float64")
        si0, si1 = max(0, -di), h - max(0, di)
        sj0, sj1 = max(0, -dj), w - max(0, dj)
        ti0, ti1 = max(0, di), h - max(0, -di)
        tj0, tj1 = max(0, dj), w - max(0, -dj)
        shifted[si0:si1, sj0:sj1] = z[ti0:ti1, tj0:tj1]
        dist = np.sqrt(2.0) if _DIAG[k] else 1.0
        slope = (z - shifted) / dist
        take = np.isfinite(slope) & (slope > best_slope)
        best_slope = np.where(take, slope, best_slope)
        best_k = np.where(take, k, best_k)

    tgt = np.full(n, -1, dtype="int64")
    is_diag = np.zeros(n, dtype=bool)
    ii, jj = np.mgrid[0:h, 0:w]
    valid = (best_k.ravel() >= 0) & (best_slope.ravel() > 0) & (~nodata.ravel())
    kflat = best_k.ravel()
    di = np.array([o[0] for o in _NB])
    dj = np.array([o[1] for o in _NB])
    dgd = np.array(_DIAG)
    tk = np.where(valid, kflat, 0)
    ni = ii.ravel() + di[tk]
    nj = jj.ravel() + dj[tk]
    tgt = np.where(valid, ni * w + nj, -1)
    is_diag = np.where(valid, dgd[tk], False)
    return tgt, is_diag


def flow_accum_cells(
    tgt: np.ndarray, dem_f: np.ndarray, nodata: np.ndarray
) -> np.ndarray:
    """Contributing cell count per cell (self + everything upslope), routed once
    in descending filled-elevation order so each cell is finalised before its
    outlet consumes it."""
    h, w = dem_f.shape
    acc = np.ones(h * w, dtype="float64")
    acc[nodata.ravel()] = 0.0
    z = np.where(np.isfinite(dem_f), dem_f, -np.inf).ravel()
    order = np.argsort(z, kind="stable")[::-1]  # high → low
    for idx in order:
        t = tgt[idx]
        if t >= 0:
            acc[t] += acc[idx]
    return acc.reshape(h, w)


def flow_network(dem: np.ndarray, nodata: np.ndarray) -> dict:
    """DEM → filled → D8 → accumulation, once. Returns
    ``{"dem_f", "tgt" (flat pointer, -1 = outlet), "is_diag" (flat), "acc" (h,w)}``
    so callers that need the routing (SDR downslope walk) and the accumulation
    share one pass."""
    dem_f = fill_depressions(dem, nodata)
    tgt, is_diag = d8(dem_f, nodata)
    acc = flow_accum_cells(tgt, dem_f, nodata)
    acc[nodata] = np.nan
    return {"dem_f": dem_f, "tgt": tgt, "is_diag": is_diag, "acc": acc}


def contributing_area(
    dem: np.ndarray, nodata: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """DEM → filled → D8 → accumulation. Returns ``(acc_cells (h,w), is_diag (h,w))``
    — ``acc_cells`` includes the cell itself (≥ 1 on valid cells)."""
    fn = flow_network(dem, nodata)
    return fn["acc"], fn["is_diag"].reshape(dem.shape)


__all__ = [
    "fill_depressions",
    "d8",
    "flow_accum_cells",
    "flow_network",
    "contributing_area",
]
