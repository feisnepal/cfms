"""RUSLE soil-loss — the factor maths.

``RUSLE_SOIL_LOSS_IMPLEMENTATION_PLAN.md`` §2 (P0 / P1).

**P0 (this cut): pure, vectorised kernels.** Every function here takes plain
floats or ``numpy`` arrays and a resolved
:class:`~app.services.operational_plan.soil_erosion_config.SoilErosionParams`,
and returns the same shape. No DB, no ``rasterio``, no I/O — so each factor is
unit-tested against a hand-worked value (``tests/services/test_soil_erosion_factors.py``).
``NaN`` propagates: a NaN in any input yields NaN in ``A``.

**P1: the grid + DB plumbing** — ``build_grid`` (DEM-aligned grid over the
CF ∪ user-group bbox, latitude-corrected per-cell area, CF / UG masks),
``_read_raster_to_grid`` (per-tile ``ST_AsGDALRaster`` → ``rasterio.merge`` →
pure-numpy nearest resample onto the grid; **never** ``ST_Union`` in SQL and
**never** ``rasterio.warp.reproject`` — this machine's ``PROJ_LIB`` points at an
old PostGIS ``proj.db``, so all CRS work is avoided; everything is EPSG:4326),
``_read_mmu_to_grid`` (``base.mmu`` ⋈ soil/climate → ``rasterio.features.rasterize``),
``factor_R/K/LS/C/P`` wrappers, ``compute_soil_loss`` (→ cached 6-band GeoTIFF +
an in-memory :class:`SoilLossResult`), and ``zonal_summary`` / ``aoi_summary``
(``geometry_mask`` over the in-memory array — no file round-trip, no CRS).

RUSLE:  ``A = R · K · LS · C · P``  (t ha⁻¹ yr⁻¹)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from uuid import UUID

import numpy as np

from app.services.operational_plan.soil_erosion_config import (
    SoilErosionParams,
    params_hash,
    resolve_params,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# WGS84 metres-per-degree of latitude (mean). Longitude scales by cos(lat).
_M_PER_DEG = 111_320.0

# EPSG:4326 as a WKT string — CRS.from_epsg(4326) hits proj.db (broken on this
# box); CRS.from_wkt does not. Used only to georeference the output GeoTIFF.
_WGS84_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
)

# rasters.dem native pixel size (deg) — the analysis grid resolution.
_GRID_RES_DEG = 0.00026949

_CACHE_ROOT = Path("uploads/soil_erosion_cache")


# ─────────────────────────────────────────────────────────────────────────────
# Geometry / CRS helpers
# ─────────────────────────────────────────────────────────────────────────────
def metric_cell_size(
    res_lon_deg: float, res_lat_deg: float, mean_lat_deg: float
) -> tuple[float, float]:
    """(dx_m, dy_m) for a cell of an EPSG:4326 grid at ``mean_lat_deg``.

    A naïve ``numpy.gradient`` on a lat/lon DEM measures elevation change per
    *degree*, which is directionally biased (1° lon ≈ 98 km vs 1° lat ≈ 111 km
    at 28 °N) — every slope/LS/area computation must go through this.
    """
    dy_m = abs(res_lat_deg) * _M_PER_DEG
    dx_m = abs(res_lon_deg) * _M_PER_DEG * np.cos(np.radians(mean_lat_deg))
    return float(dx_m), float(dy_m)


def cell_area_ha(dx_m: float, dy_m: float) -> float:
    """Area of one grid cell in hectares (for the ``Σ A·area`` total)."""
    return (dx_m * dy_m) / 10_000.0


def slope_pct_from_dem(dem: np.ndarray, dx_m: float, dy_m: float) -> np.ndarray:
    """Percent slope from an elevation array with **metric** cell spacing.

    ``dem`` is ``[row, col]`` = ``[y (lat, N→S or S→N), x (lon)]``. NoData must
    already be NaN. Returns ``100 · |∇z|`` (rise / run × 100).
    """
    dem = np.asarray(dem, dtype="float64")
    # np.gradient varargs are the spacing per axis, in axis order (rows, cols).
    dz_dy, dz_dx = np.gradient(dem, dy_m, dx_m, edge_order=1)
    return 100.0 * np.sqrt(dz_dx**2 + dz_dy**2)


# ─────────────────────────────────────────────────────────────────────────────
# R — rainfall erosivity
# ─────────────────────────────────────────────────────────────────────────────
def seasonality_concentration(q1, q2, q3, q4):
    """``(Σ f_q²) / 3`` from the four quarterly precip totals, where
    ``f_q = q_i / Σq`` (annual fraction in quarter *q*).

    Under ``mfi_from_quarters="even_split"`` this is exactly the multiplier that
    turns annual precip ``P`` into the Modified Fournier Index:
    ``MFI = Σ_{months} (P·f_m)² / P = P · Σ_m f_m²`` and, splitting each quarter
    evenly over its 3 months, ``Σ_m f_m² = Σ_q 3·(f_q/3)² = (Σ_q f_q²)/3``.
    """
    q1, q2, q3, q4 = (np.asarray(x, dtype="float64") for x in (q1, q2, q3, q4))
    total = q1 + q2 + q3 + q4
    with np.errstate(invalid="ignore", divide="ignore"):
        f = np.stack([q1, q2, q3, q4]) / total
        out = np.sum(f**2, axis=0) / 3.0
    return np.where(total > 0, out, np.nan)


def mfi_from_p(p_mm, concentration) -> np.ndarray:
    """Modified Fournier Index for the ``even_split`` reconstruction:
    ``MFI = P · concentration`` (see :func:`seasonality_concentration`)."""
    return np.asarray(p_mm, dtype="float64") * np.asarray(
        concentration, dtype="float64"
    )


def factor_r(p_mm, concentration, params: SoilErosionParams) -> np.ndarray:
    """Rainfall erosivity R (MJ·mm·ha⁻¹·h⁻¹·yr⁻¹).

    ``p_mm`` — mean annual precipitation per cell.
    ``concentration`` — from :func:`seasonality_concentration`; only read when
    ``params.r_method == "mfi"`` (pass ``None`` / zeros for the regression).
    """
    p = np.asarray(p_mm, dtype="float64")
    if params.r_method == "annual_regression":
        c = params.annual_reg_coeffs
        r = c.a * p + c.b
    else:  # "mfi" — Arnoldus (1980) power form
        c = params.mfi_arnoldus_coeffs
        mfi = mfi_from_p(p, concentration)
        with np.errstate(invalid="ignore"):
            r = c.a * np.power(mfi, c.b)
    return np.clip(r, 0.0, None)


# ─────────────────────────────────────────────────────────────────────────────
# K — soil erodibility  (EPIC / Williams; Sharpley & Williams 1990)
# ─────────────────────────────────────────────────────────────────────────────
def factor_k_williams(sand_pct, silt_pct, clay_pct, oc_pct) -> np.ndarray:
    """SI K (t·h·MJ⁻¹·mm⁻¹). Inputs are percentages; ``oc_pct`` is organic
    *carbon* % (= ``organic_carbon_g_kg`` / 10)."""
    san = np.asarray(sand_pct, dtype="float64")
    sil = np.asarray(silt_pct, dtype="float64")
    cla = np.asarray(clay_pct, dtype="float64")
    oc = np.asarray(oc_pct, dtype="float64")
    sn1 = 1.0 - san / 100.0

    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        f_csand = 0.2 + 0.3 * np.exp(-0.0256 * san * (1.0 - sil / 100.0))
        f_cl_si = np.power(sil / (cla + sil), 0.3)
        f_orgc = 1.0 - (0.25 * oc) / (oc + np.exp(3.72 - 2.95 * oc))
        f_hisand = 1.0 - (0.7 * sn1) / (sn1 + np.exp(-5.51 + 22.9 * sn1))
        k = f_csand * f_cl_si * f_orgc * f_hisand * 0.1317

    # a soil row with no texture (sand+silt+clay ≈ 0) → NaN, not a bogus number
    bad = ~np.isfinite(k) | ((san + sil + cla) <= 0)
    return np.where(bad, np.nan, k)


def factor_k(
    sand_pct, silt_pct, clay_pct, oc_pct, params: SoilErosionParams
) -> np.ndarray:
    """K by ``params.k_method``, clamped to ``[k_floor, k_ceiling]``."""
    if params.k_method == "wischmeier":  # pragma: no cover - P6
        raise NotImplementedError(
            "k_method='wischmeier' is not wired until a later phase"
        )
    k = factor_k_williams(sand_pct, silt_pct, clay_pct, oc_pct)
    return np.where(np.isnan(k), np.nan, np.clip(k, params.k_floor, params.k_ceiling))


# ─────────────────────────────────────────────────────────────────────────────
# LS — slope length & steepness  (v1: McCool 1987 S × classic USLE L)
# ─────────────────────────────────────────────────────────────────────────────
def mccool_s(slope_pct) -> np.ndarray:
    """Slope steepness factor S (McCool et al. 1987). Two-branch at 9 % slope
    (≈ 5.14°, ``tanθ = 0.09``)."""
    s_pct = np.asarray(slope_pct, dtype="float64")
    theta = np.arctan(s_pct / 100.0)
    sin_t = np.sin(theta)
    low = 10.8 * sin_t + 0.03
    high = 16.8 * sin_t - 0.50
    return np.where(s_pct < 9.0, low, high)


def _m_exponent(slope_pct: np.ndarray, params: SoilErosionParams) -> np.ndarray:
    m = params.ls_m_exponent_by_slope
    out = np.full(np.shape(slope_pct), m["gt5"], dtype="float64")
    out = np.where(slope_pct < 5.0, m["3to5"], out)
    out = np.where(slope_pct < 3.0, m["1to3"], out)
    out = np.where(slope_pct < 1.0, m["lt1"], out)
    return out


def usle_l(slope_length_m, slope_pct, params: SoilErosionParams) -> np.ndarray:
    """Classic USLE slope-length factor ``L = (λ / 22.13)^m`` with λ capped at
    ``params.slope_length_cap_m`` and *m* from the slope-band table."""
    lam = np.clip(
        np.asarray(slope_length_m, dtype="float64"), 0.0, params.slope_length_cap_m
    )
    m = _m_exponent(np.asarray(slope_pct, dtype="float64"), params)
    with np.errstate(invalid="ignore"):
        return np.power(lam / 22.13, m)


def factor_ls(slope_pct, slope_length_m, params: SoilErosionParams) -> np.ndarray:
    """LS = L · S with the classic capped-length L (``ls_method="moore_burch"``).

    ``ls_method="desmet_govers"`` uses :func:`desmet_govers_ls` instead — it
    needs the D8 contributing area, so ``factor_ls_grid`` dispatches; this scalar
    entry point always uses the capped-length L.
    """
    s = mccool_s(slope_pct)
    l = usle_l(slope_length_m, slope_pct, params)
    return np.clip(l * s, 0.0, params.ls_cap)


def desmet_govers_ls(
    acc_cells, slope_pct, is_diag, cell_m: float, params: SoilErosionParams
) -> np.ndarray:
    """LS = L_DG · S, where L_DG is the Desmet & Govers (1996) unit-contributing-
    area form:

        L = [(A_in + D²)^(m+1) − A_in^(m+1)] / [D^(m+2) · x^m · 22.13^m]

    ``acc_cells`` — D8 contributing cell count (self + upslope);
    ``A_in`` = (acc_cells − 1)·D² is the area entering the cell.
    ``x`` = 1 (cardinal inflow) or √2 (diagonal), from the D8 pointer.
    ``m`` from the slope-band table (same as the classic L). S is McCool 1987.
    """
    acc = np.asarray(acc_cells, dtype="float64")
    sp = np.asarray(slope_pct, dtype="float64")
    d = float(cell_m)
    a_in = np.clip((acc - 1.0) * d * d, 0.0, None)
    m = _m_exponent(sp, params)
    x = np.where(np.asarray(is_diag, dtype=bool), np.sqrt(2.0), 1.0)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        num = np.power(a_in + d * d, m + 1.0) - np.power(a_in, m + 1.0)
        den = np.power(d, m + 2.0) * np.power(x, m) * np.power(22.13, m)
        l_dg = num / den
    l_dg = np.where(np.isfinite(l_dg), l_dg, np.nan)
    return np.clip(l_dg * mccool_s(sp), 0.0, params.ls_cap)


# ─────────────────────────────────────────────────────────────────────────────
# C — cover management
# ─────────────────────────────────────────────────────────────────────────────
def _canopy_multiplier(canopy_h_m: np.ndarray, params: SoilErosionParams) -> np.ndarray:
    """1.0 at an open canopy (≤ ``canopy_open_height_m``), falling linearly to
    ``canopy_c_min_multiplier`` at a closed canopy (≥ ``canopy_closed_height_m``).
    Where canopy height is unknown (NaN / ≤ 0) → 1.0 (no reduction)."""
    h = np.asarray(canopy_h_m, dtype="float64")
    span = params.canopy_closed_height_m - params.canopy_open_height_m
    t = np.clip((h - params.canopy_open_height_m) / span, 0.0, 1.0)
    mult = 1.0 + t * (params.canopy_c_min_multiplier - 1.0)
    return np.where(np.isfinite(h) & (h > 0), mult, 1.0)


# Hansen GFC lossyear encoding: value = (year − 2000); latest band is 2023.
_HANSEN_LATEST_YEAR = 23


def factor_c(
    esa_class, params: SoilErosionParams, canopy_h_m=None, disturbed_recent=None
) -> np.ndarray:
    """Cover-management factor C from the ESA WorldCover class, optionally
    modulated by canopy height on the forest/shrub classes and bumped on cells
    that lost forest recently (``disturbed_recent`` bool array, P6b)."""
    cls = np.asarray(esa_class)
    c = np.full(cls.shape, params.c_default, dtype="float64")
    for code, cval in params.c_by_esa_class.items():
        c = np.where(cls == code, cval, c)

    if params.canopy_modifier_enabled and canopy_h_m is not None:
        mult = _canopy_multiplier(canopy_h_m, params)
        forest = np.isin(cls, np.asarray(params.canopy_modifier_classes))
        c = np.where(forest, c * mult, c)

    if params.c_disturbance_bump > 1.0 and disturbed_recent is not None:
        c = np.where(
            np.asarray(disturbed_recent, dtype=bool),
            np.clip(c * params.c_disturbance_bump, 0.0, 1.0),
            c,
        )
    return c


# ─────────────────────────────────────────────────────────────────────────────
# P — support practice
# ─────────────────────────────────────────────────────────────────────────────
def factor_p(esa_class, slope_pct, params: SoilErosionParams) -> np.ndarray:
    """P = ``p_default`` everywhere except cropland, where it follows the
    slope-band table (terracing ≈ contouring in the Nepal mid-hills)."""
    cls = np.asarray(esa_class)
    s = np.asarray(slope_pct, dtype="float64")
    p = np.full(cls.shape, params.p_default, dtype="float64")

    cropland = np.isin(cls, np.asarray(params.p_cropland_esa_classes))
    # bands are (slope_upper_pct, P) ascending; walk from the top down so the
    # first (lowest) matching band wins.
    for upper, pval in reversed(params.p_cropland_slope_bands):
        p = np.where(cropland & (s < upper), pval, p)
    return p


# ─────────────────────────────────────────────────────────────────────────────
# A = R · K · LS · C · P  +  severity classification
# ─────────────────────────────────────────────────────────────────────────────
def soil_loss(r, k, ls, c, p) -> np.ndarray:
    """Annual soil loss A (t ha⁻¹ yr⁻¹). NaN in any factor → NaN out."""
    a = (
        np.asarray(r, dtype="float64")
        * np.asarray(k, dtype="float64")
        * np.asarray(ls, dtype="float64")
        * np.asarray(c, dtype="float64")
        * np.asarray(p, dtype="float64")
    )
    return np.clip(a, 0.0, None)


def classify_severity(a, breaks) -> np.ndarray:
    """0-based severity class per cell; ``-1`` where A is NaN. ``N`` breaks →
    classes ``0 … N``."""
    a = np.asarray(a, dtype="float64")
    idx = np.zeros(a.shape, dtype="int16")
    for brk in breaks:
        idx = idx + (a >= brk).astype("int16")
    return np.where(np.isnan(a), np.int16(-1), idx)


# ─────────────────────────────────────────────────────────────────────────────
# P1 — grid + DB plumbing
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class GridSpec:
    """The analysis grid: an axis-aligned EPSG:4326 raster covering the CF ∪
    user-group extent at ``rasters.dem`` native resolution."""

    transform: "object"  # affine.Affine
    width: int
    height: int
    mean_lat: float
    dx_m: float
    dy_m: float
    cell_area_ha: np.ndarray  # (h, w) — latitude-corrected
    bounds: tuple[float, float, float, float]
    aoi_wkt: str  # CF ∪ UG polygon, for the raster clips
    cf_mask: np.ndarray  # (h, w) bool — inside the CF boundary
    ug_mask: Optional[np.ndarray]  # (h, w) bool — inside the user-group extent


@dataclass
class SoilLossResult:
    grid: GridSpec
    params: SoilErosionParams
    a: np.ndarray  # (h, w) soil loss  t ha⁻¹ yr⁻¹
    r: np.ndarray
    k: np.ndarray
    ls: np.ndarray
    c: np.ndarray
    p: np.ndarray
    geotiff_path: Path
    sdr: Optional[np.ndarray] = None  # (h, w) 0–sdr_max — P6c, None when disabled
    delivered: Optional[np.ndarray] = None  # (h, w) a·sdr  t ha⁻¹ yr⁻¹


def _user_group_geom(db: "Session", calculation_id: UUID):
    """Shapely geometry of the user group (the UNION of every polygon), or ``None``."""
    from sqlalchemy import text

    row = db.execute(
        text(
            "SELECT ST_AsText(ST_Union(extent_geometry)) FROM user_group_extents "
            "WHERE calculation_id = :cid AND extent_geometry IS NOT NULL"
        ),
        {"cid": str(calculation_id)},
    ).first()
    if not row or not row[0]:
        return None
    from shapely import wkt as _wkt

    try:
        g = _wkt.loads(row[0])
        return g if g and not g.is_empty else None
    except Exception:  # noqa: BLE001
        return None


def build_grid(db: "Session", calculation_id: UUID) -> GridSpec:
    """DEM-aligned grid over the CF boundary ∪ user-group extent."""
    from rasterio.features import geometry_mask
    from rasterio.transform import from_origin
    from shapely.geometry import mapping
    from shapely.ops import unary_union

    from app.services.management_plan_docx import plan_map_service as pms

    boundary = pms._get_forest_geometry(db, calculation_id)
    if boundary is None or boundary.is_empty:
        raise ValueError(f"calculation {calculation_id} has no boundary geometry")
    ug = _user_group_geom(db, calculation_id)

    aoi = unary_union([g for g in (boundary, ug) if g is not None])
    minx, miny, maxx, maxy = aoi.bounds
    res = _GRID_RES_DEG
    width = max(1, int(np.ceil((maxx - minx) / res)))
    height = max(1, int(np.ceil((maxy - miny) / res)))
    transform = from_origin(minx, maxy, res, res)
    mean_lat = (miny + maxy) / 2.0
    dx_m, dy_m = metric_cell_size(res, res, mean_lat)

    # per-row latitude-corrected cell area (h, w)
    row_lat = maxy - (np.arange(height) + 0.5) * res
    row_dx_m = res * _M_PER_DEG * np.cos(np.radians(row_lat))
    area_ha = np.repeat((row_dx_m * dy_m / 10_000.0)[:, None], width, axis=1)

    cf_mask = geometry_mask(
        [mapping(boundary)], (height, width), transform, invert=True, all_touched=True
    )
    ug_mask = (
        geometry_mask(
            [mapping(ug)], (height, width), transform, invert=True, all_touched=True
        )
        if ug is not None
        else None
    )
    return GridSpec(
        transform=transform,
        width=width,
        height=height,
        mean_lat=mean_lat,
        dx_m=dx_m,
        dy_m=dy_m,
        cell_area_ha=area_ha,
        bounds=(minx, miny, maxx, maxy),
        aoi_wkt=aoi.wkt,
        cf_mask=cf_mask,
        ug_mask=ug_mask,
    )


def _resample_nearest(src: np.ndarray, src_transform, grid: GridSpec) -> np.ndarray:
    """Nearest-neighbour resample a same-CRS (EPSG:4326) source array onto the
    grid — pure numpy, no ``rasterio.warp.reproject`` (this box's PROJ is broken).
    Continuous rasters lose no meaningful detail (the grid ≈ DEM native res);
    categorical rasters (ESA) *require* nearest anyway."""
    jj, ii = np.mgrid[0 : grid.height, 0 : grid.width]
    t = grid.transform
    xs = t.c + (ii + 0.5) * t.a + (jj + 0.5) * t.b
    ys = t.f + (ii + 0.5) * t.d + (jj + 0.5) * t.e
    inv = ~src_transform
    cs = inv.a * xs + inv.b * ys + inv.c
    rs = inv.d * xs + inv.e * ys + inv.f
    ci = np.floor(cs).astype(np.int64)
    ri = np.floor(rs).astype(np.int64)
    sh, sw = src.shape
    valid = (ci >= 0) & (ci < sw) & (ri >= 0) & (ri < sh)
    out = np.full((grid.height, grid.width), np.nan, dtype="float64")
    out[valid] = src[ri[valid], ci[valid]]
    return out


def _read_raster_to_grid(
    db: "Session",
    table: str,
    band: int,
    grid: GridSpec,
    *,
    lo: float | None = None,
    hi: float | None = None,
) -> np.ndarray:
    """Fetch every ``{table}`` tile that intersects the AOI **whole** (no
    ``ST_Clip`` — clipping to the polygon leaves NaN halos along the boundary
    for coarse rasters), ``rasterio.merge`` them, then nearest-resample onto
    ``grid``. NoData (the band's own + the physical ``[lo, hi]`` range) → NaN.
    Never unions rasters in SQL, never reprojects."""
    from rasterio.io import MemoryFile
    from rasterio.merge import merge
    from sqlalchemy import text

    q = text(
        f"""
        SELECT ST_AsGDALRaster(r.rast, 'GTiff')
        FROM {table} r
        WHERE ST_Intersects(r.rast, ST_GeomFromText(:wkt, 4326))
        """  # noqa: S608 -- table is a hardcoded identifier
    )
    mfs, dss = [], []
    try:
        for (gb,) in db.execute(q, {"wkt": grid.aoi_wkt}):
            if gb is None:
                continue
            mf = MemoryFile(bytes(gb))
            mfs.append(mf)
            dss.append(mf.open())
        if not dss:
            return np.full((grid.height, grid.width), np.nan)
        mosaic, mtrans = merge(dss)
        src = mosaic[band - 1].astype("float64")
        nd = dss[0].nodata
        if nd is not None:
            src[src == nd] = np.nan
        if lo is not None:
            src[(src < lo) | (src > hi)] = np.nan
        return _resample_nearest(src, mtrans, grid)
    finally:
        for d in dss:
            d.close()
        for m in mfs:
            m.close()


def _read_mmu_to_grid(
    db: "Session", grid: GridSpec, join_sql: str, value_cols: list[str]
) -> dict[str, np.ndarray]:
    """Rasterise per-MMU attribute columns onto the grid. ``join_sql`` selects
    ``m.geom`` + the ``value_cols`` from ``base.mmu`` joined to a soil/climate
    table, filtered to the AOI."""
    from rasterio.features import rasterize
    from shapely import wkt as _wkt
    from sqlalchemy import text

    rows = db.execute(text(join_sql), {"wkt": grid.aoi_wkt}).fetchall()
    shapes: dict[str, list] = {c: [] for c in value_cols}
    for row in rows:
        try:
            geom = _wkt.loads(row[0])
        except Exception:  # noqa: BLE001
            continue
        if geom.is_empty:
            continue
        for i, col in enumerate(value_cols, start=1):
            v = row[i]
            if v is None:
                continue
            try:
                shapes[col].append((geom, float(v)))
            except (TypeError, ValueError):
                continue
    out: dict[str, np.ndarray] = {}
    for col in value_cols:
        if not shapes[col]:
            out[col] = np.full((grid.height, grid.width), np.nan)
            continue
        out[col] = rasterize(
            shapes[col],
            out_shape=(grid.height, grid.width),
            transform=grid.transform,
            fill=np.nan,
            dtype="float64",
            all_touched=True,
        )
    return out


def _read_canopy_to_grid(grid: GridSpec) -> np.ndarray:
    """Canopy height (m) from ``canopy_height5m.tif`` (uint8, 0 = NoData) onto
    the grid. Returns an all-NaN grid if the file is unreadable."""
    try:
        import rasterio
        from rasterio.windows import from_bounds

        from app.services.analysis import CANOPY_TIF_PATH

        minx, miny, maxx, maxy = grid.bounds
        with rasterio.open(CANOPY_TIF_PATH) as ds:
            win = from_bounds(minx, miny, maxx, maxy, ds.transform)
            arr = ds.read(1, window=win, boundless=True, fill_value=0).astype("float64")
            wt = ds.window_transform(win)
        arr[(arr <= 0) | (arr > 80)] = np.nan
        return _resample_nearest(arr, wt, grid)
    except (
        Exception
    ):  # noqa: BLE001 -- canopy is optional; C falls back to the class value
        logger.debug("canopy TIF read failed", exc_info=True)
        return np.full((grid.height, grid.width), np.nan)


def _read_streams_to_grid(db: "Session", grid: GridSpec) -> "np.ndarray | None":
    """Rasterise ``river.river84`` lines that touch the AOI onto the grid (bool).
    ``None`` if no river layer / nothing intersects — the SDR channel mask then
    falls back to the flow-accumulation threshold alone."""
    try:
        from rasterio.features import rasterize
        from shapely import wkb as _wkb
        from sqlalchemy import text

        rows = db.execute(
            text(
                "SELECT ST_AsBinary(ST_Intersection(r.shape, "
                "ST_GeomFromText(:wkt, 4326))) "
                "FROM river.river84 r "
                "WHERE ST_Intersects(r.shape, ST_GeomFromText(:wkt, 4326))"
            ),
            {"wkt": grid.aoi_wkt},
        ).fetchall()
        geoms = []
        for (gb,) in rows:
            if gb is None:
                continue
            g = _wkb.loads(bytes(gb))
            if g and not g.is_empty:
                geoms.append(g)
        if not geoms:
            return None
        arr = rasterize(
            ((g, 1) for g in geoms),
            out_shape=(grid.height, grid.width),
            transform=grid.transform,
            fill=0,
            dtype="uint8",
            all_touched=True,
        )
        return arr.astype(bool)
    except Exception:  # noqa: BLE001 -- no hydro layer → threshold-only channels
        logger.debug("river84 rasterise failed", exc_info=True)
        return None


# ── factor wrappers (read data, call the P0 kernels) ───────────────────────
def factor_r_grid(
    db: "Session", grid: GridSpec, params: SoilErosionParams
) -> np.ndarray:
    p_mm = _read_raster_to_grid(
        db, "rasters.annual_precipitation", 1, grid, lo=0, hi=20000
    )
    conc = None
    if params.r_method == "mfi":
        q = (
            "SELECT ST_AsText(m.geom), cl.precip_wettest_quarter_mm, "
            "cl.precip_driest_quarter_mm, cl.precip_warmest_quarter_mm, "
            "cl.precip_coldest_quarter_mm "
            'FROM base.mmu m JOIN climate."world climate" cl ON cl.mmuid = m.mmuid '
            "WHERE ST_Intersects(m.geom, ST_GeomFromText(:wkt, 4326))"
        )
        qd = _read_mmu_to_grid(db, grid, q, ["q_wet", "q_dry", "q_warm", "q_cold"])
        conc = seasonality_concentration(
            qd["q_wet"], qd["q_dry"], qd["q_warm"], qd["q_cold"]
        )
    return factor_r(p_mm, conc, params)


def factor_k_grid(
    db: "Session", grid: GridSpec, params: SoilErosionParams
) -> np.ndarray:
    q = (
        "SELECT ST_AsText(m.geom), sg.sand_percent, sg.silt_percent, "
        "sg.clay_percent, sg.organic_carbon_g_kg "
        "FROM base.mmu m JOIN soil.soilgrids sg ON sg.mmuid = m.mmuid "
        "WHERE ST_Intersects(m.geom, ST_GeomFromText(:wkt, 4326))"
    )
    d = _read_mmu_to_grid(db, grid, q, ["sand", "silt", "clay", "oc_gkg"])
    return factor_k(d["sand"], d["silt"], d["clay"], d["oc_gkg"] / 10.0, params)


# above this many grid cells the Priority-Flood heap loop gets slow (~10s+);
# desmet_govers falls back to moore_burch and logs it. The GeoTIFF is cached.
_D8_CELL_CAP = 6_000_000


def factor_ls_grid(
    db: "Session", grid: GridSpec, params: SoilErosionParams
) -> tuple[np.ndarray, np.ndarray]:
    """Returns ``(LS, slope_pct)`` — slope is reused by the P factor."""
    dem = _read_raster_to_grid(db, "rasters.dem", 1, grid, lo=-500, hi=9000)
    slope_pct = slope_pct_from_dem(dem, grid.dx_m, grid.dy_m)

    if params.ls_method == "desmet_govers":
        if grid.width * grid.height > _D8_CELL_CAP:
            logger.warning(
                "soil-loss: grid %dx%d over the D8 cap — LS falls back to "
                "moore_burch for this forest",
                grid.width,
                grid.height,
            )
        else:
            from app.services.operational_plan import soil_erosion_d8 as d8

            nodata = ~np.isfinite(dem)
            acc, is_diag = d8.contributing_area(dem, nodata)
            ls = desmet_govers_ls(acc, slope_pct, is_diag, grid.dx_m, params)
            # D8 leaves the grid-edge / outlet cells NaN — backfill with the
            # capped-length LS so the map has no interior holes.
            fallback = factor_ls(
                slope_pct, np.full_like(slope_pct, params.slope_length_cap_m), params
            )
            ls = np.where(np.isfinite(ls), ls, fallback)
            return ls, slope_pct

    # moore_burch (v1): no flow accumulation → hillslope length = the cap.
    slope_len = np.full_like(slope_pct, params.slope_length_cap_m)
    return factor_ls(slope_pct, slope_len, params), slope_pct


def factor_c_grid(
    db: "Session", grid: GridSpec, params: SoilErosionParams
) -> tuple[np.ndarray, np.ndarray]:
    """Returns ``(C, esa_class)`` — the ESA raster is reused by the P factor."""
    esa = _read_raster_to_grid(db, "rasters.esa_world_cover", 1, grid)
    canopy = _read_canopy_to_grid(grid) if params.canopy_modifier_enabled else None
    esa_int = np.where(np.isnan(esa), -1, np.round(esa)).astype(np.int32)

    disturbed = None
    if params.c_disturbance_bump > 1.0:
        ly = _read_raster_to_grid(db, "rasters.nepal_lossyear", 1, grid, lo=0, hi=99)
        thresh = _HANSEN_LATEST_YEAR - params.c_disturbance_recent_years
        disturbed = np.isfinite(ly) & (ly > 0) & (ly >= thresh)

    return (
        factor_c(esa_int, params, canopy_h_m=canopy, disturbed_recent=disturbed),
        esa_int,
    )


def factor_p_grid(
    esa_int: np.ndarray, slope_pct: np.ndarray, params: SoilErosionParams
):
    return factor_p(esa_int, slope_pct, params)


# ── orchestration + cache ─────────────────────────────────────────────────
def _cache_path(calculation_id: UUID, params: SoilErosionParams) -> Path:
    return _CACHE_ROOT / str(calculation_id) / f"{params_hash(params)}.tif"


def cache_matches_grid(path: Path, grid: "GridSpec") -> bool:
    """A cached GeoTIFF is only valid for the grid it was computed on. The grid follows the forest AND the
    user group, so drawing, cutting or deleting a user-group polygon changes it; a cache of the old shape then
    fails with "operands could not be broadcast together" and the whole hazard chapter reports no data."""
    try:
        import rasterio

        with rasterio.open(path) as ds:
            return ds.width == grid.width and ds.height == grid.height
    except Exception:  # noqa: BLE001 -- unreadable cache counts as not matching: recompute
        return False


def clear_cache(calculation_id: UUID) -> None:
    """Drop every cached soil-loss GeoTIFF for a calculation (call from the
    analysis / field-inventory cache-invalidation hooks)."""
    import shutil

    d = _CACHE_ROOT / str(calculation_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


_BAND_NAMES = ("soil_loss", "R", "K", "LS", "C", "P", "SDR", "delivered")


def _write_geotiff(path: Path, grid: GridSpec, bands: list[np.ndarray]) -> None:
    import rasterio
    from rasterio.crs import CRS

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=grid.height,
        width=grid.width,
        count=len(bands),
        dtype="float32",
        transform=grid.transform,
        crs=CRS.from_wkt(_WGS84_WKT),
        nodata=float("nan"),
        compress="deflate",
    ) as ds:
        for i, arr in enumerate(bands, start=1):
            ds.write(arr.astype("float32"), i)
            ds.set_band_description(i, _BAND_NAMES[i - 1])


def _read_geotiff(
    path: Path, grid: GridSpec, params: SoilErosionParams
) -> SoilLossResult:
    import rasterio

    with rasterio.open(path) as ds:
        n = ds.count
        b = [ds.read(i).astype("float64") for i in range(1, n + 1)]
    sdr = b[6] if n >= 8 else None
    delivered = b[7] if n >= 8 else None
    return SoilLossResult(
        grid, params, b[0], b[1], b[2], b[3], b[4], b[5], path, sdr, delivered
    )


def compute_soil_loss(
    db: "Session", calculation_id: UUID, *, force: bool = False
) -> SoilLossResult:
    """Resolve the per-forest parameters, build the grid, compute
    ``A = R·K·LS·C·P`` and cache a 6-band GeoTIFF
    (``uploads/soil_erosion_cache/<calc_id>/<params_hash>.tif``)."""
    params = resolve_params(db, calculation_id)
    path = _cache_path(calculation_id, params)
    grid = build_grid(db, calculation_id)
    if path.exists() and not force and cache_matches_grid(path, grid):
        try:
            return _read_geotiff(path, grid, params)
        except Exception:  # noqa: BLE001 -- a corrupt cache file → recompute
            logger.warning("soil-loss cache unreadable, recomputing: %s", path)

    r = factor_r_grid(db, grid, params)
    k = factor_k_grid(db, grid, params)
    ls, slope_pct = factor_ls_grid(db, grid, params)
    c, esa_int = factor_c_grid(db, grid, params)
    p = factor_p_grid(esa_int, slope_pct, params)
    a = soil_loss(r, k, ls, c, p)

    bands = [a, r, k, ls, c, p]
    sdr = delivered = None
    if params.sdr_enabled and grid.width * grid.height <= _D8_CELL_CAP:
        from app.services.operational_plan import soil_erosion_d8 as _d8
        from app.services.operational_plan import soil_erosion_sdr as _sdr

        dem = _read_raster_to_grid(db, "rasters.dem", 1, grid, lo=-500, hi=9000)
        flow = _d8.flow_network(dem, ~np.isfinite(dem))
        rivers = _read_streams_to_grid(db, grid)
        sdr = _sdr.sdr_field(slope_pct, c, flow, rivers, grid.dx_m, params)
        delivered = np.where(np.isfinite(a) & np.isfinite(sdr), a * sdr, np.nan)
        bands += [sdr, delivered]
    elif params.sdr_enabled:
        logger.warning(
            "soil-loss: grid %dx%d over the D8 cap — SDR skipped for this forest",
            grid.width,
            grid.height,
        )

    _write_geotiff(path, grid, bands)
    return SoilLossResult(grid, params, a, r, k, ls, c, p, path, sdr, delivered)


# ── summaries ─────────────────────────────────────────────────────────────
def _summary(a: np.ndarray, area_ha: np.ndarray, mask: np.ndarray, breaks) -> dict:
    sel = mask & np.isfinite(a)
    if not sel.any():
        return {
            "mean": None,
            "total_t_yr": 0.0,
            "area_ha": 0.0,
            "pct_by_severity": {},
        }
    vals = a[sel]
    areas = area_ha[sel]
    cls = classify_severity(vals, breaks)
    n_classes = len(breaks) + 1
    tot_area = float(areas.sum())
    pct = {
        i: round(100.0 * float(areas[cls == i].sum()) / tot_area, 1)
        for i in range(n_classes)
        if (cls == i).any()
    }
    return {
        "mean": round(float(np.average(vals, weights=areas)), 2),
        "total_t_yr": round(float((vals * areas).sum()), 1),
        "area_ha": round(tot_area, 2),
        "pct_by_severity": pct,
    }


def zonal_summary(result: SoilLossResult, units: list[dict]) -> dict[str, dict]:
    """``{unit_name: {mean, total_t_yr, area_ha, pct_by_severity}}`` — per
    block / compartment. ``units`` is the list from
    ``thematic_overlay._units_with_geometry`` (``name`` + shapely ``geometry``)."""
    from rasterio.features import geometry_mask
    from shapely.geometry import mapping

    g = result.grid
    out: dict[str, dict] = {}
    for u in units:
        geom = u.get("geometry")
        if geom is None or geom.is_empty:
            continue
        m = geometry_mask(
            [mapping(geom)],
            (g.height, g.width),
            g.transform,
            invert=True,
            all_touched=True,
        )
        out[u["name"]] = _summary(
            result.a, g.cell_area_ha, m, result.params.severity_breaks
        )
    return out


def aoi_summary(result: SoilLossResult, mask: np.ndarray) -> dict:
    """Summary over a boolean AOI mask (``grid.cf_mask``, ``grid.ug_mask``, or
    e.g. ``ug_mask & ~cf_mask`` for the settlement-land-outside-the-forest row)."""
    return _summary(
        result.a, result.grid.cell_area_ha, mask, result.params.severity_breaks
    )


__all__ = [
    "metric_cell_size",
    "cell_area_ha",
    "slope_pct_from_dem",
    "seasonality_concentration",
    "mfi_from_p",
    "factor_r",
    "factor_k_williams",
    "factor_k",
    "mccool_s",
    "usle_l",
    "factor_ls",
    "factor_c",
    "factor_p",
    "soil_loss",
    "classify_severity",
    "GridSpec",
    "SoilLossResult",
    "build_grid",
    "compute_soil_loss",
    "zonal_summary",
    "aoi_summary",
    "clear_cache",
]
