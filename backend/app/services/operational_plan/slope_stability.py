"""Infinite-slope Factor of Safety (FS) — a saturated-monsoon scenario.

``HOUSEHOLD_VULNERABILITY_ANALYSIS_PLAN.md`` §2.2 / phase P2.

``FS = [c' + (γ − m·γ_w)·z·cos²β·tanφ'] / [γ·z·sinβ·cosβ]``  (Hammond et al.
1992, LISA). This is a **scenario**, not a probability: regolith depth ``z`` is
the one genuinely assumed parameter (constant, or a slope-thinning linear
model), and the pore-pressure ratio ``m`` is set to a wet-season value
(optionally raised in the topographically-wet cells). Everything is reported
as *"under a saturated-monsoon scenario, assuming a {depth} m regolith and
m = {m}"*.

Reuses the RUSLE compute grid (``soil_erosion.build_grid`` / ``GridSpec`` /
``_read_raster_to_grid`` / ``_read_mmu_to_grid`` / ``slope_pct_from_dem``), the
vendored D8 (``soil_erosion_d8.flow_network``) and the LSI module's
``twi`` / ``_rasterise_class_rating`` helpers. Output is a cached multi-band
GeoTIFF under ``uploads/hazard_vuln_cache/<calc_id>/fs_<params_hash>.tif``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from uuid import UUID

import numpy as np

from app.services.operational_plan import landslide_susceptibility as ls
from app.services.operational_plan import soil_erosion as se
from app.services.operational_plan.hazard_vuln_config import (
    FS_CLASS_LABELS_EN,
    FS_CLASS_LABELS_NE,
    FactorOfSafetyParams,
    HazardVulnParams,
    params_hash,
    resolve_params,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_CACHE_ROOT = Path("uploads/hazard_vuln_cache")
_FS_CAP = 10.0  # store a finite ceiling; flat ground → FS ≈ _FS_CAP → "stable"
_FS_BANDS = ("fs", "class", "instability", "z_m", "m", "c_kpa", "phi_deg", "gamma")


# ─────────────────────────────────────────────────────────────────────────────
# Pure kernels — no DB, no rasterio
# ─────────────────────────────────────────────────────────────────────────────
def soil_depth_m(slope_deg: np.ndarray, p: FactorOfSafetyParams) -> np.ndarray:
    """Regolith depth (m). ``constant`` → a flat sheet; ``slope_linear`` →
    ``z0 − k·slope°`` clamped to ``[depth_min_m, depth_max_m]`` (Saulnier et al.
    1997 — soil thins on steep noses, deepens in hollows)."""
    s = np.asarray(slope_deg, dtype="float64")
    if p.soil_depth_model == "constant":
        z = np.full(s.shape, float(p.depth_constant_m))
    else:
        z = float(p.depth_slope_z0_m) - float(p.depth_slope_k) * s
        z = np.clip(z, p.depth_min_m, p.depth_max_m)
    return np.where(np.isfinite(s), z, np.nan)


def saturation_ratio(
    twi: Optional[np.ndarray], p: FactorOfSafetyParams, shape: tuple[int, int]
) -> np.ndarray:
    """Pore-pressure ratio ``m = h_w / z`` (0 dry .. 1 saturated). Constant
    ``saturation_ratio_m`` unless ``saturation_twi_varied`` — then it ramps
    linearly from ``saturation_twi_low`` at the AOI's 5th TWI percentile to
    ``saturation_twi_high`` at the 95th (hollows wetter than noses)."""
    base = float(p.saturation_ratio_m)
    if not p.saturation_twi_varied or twi is None:
        return np.full(shape, base)
    t = np.asarray(twi, dtype="float64")
    fin = np.isfinite(t)
    if not fin.any():
        return np.full(shape, base)
    lo, hi = np.percentile(t[fin], [5, 95])
    if hi <= lo:
        return np.full(shape, base)
    frac = np.clip((t - lo) / (hi - lo), 0.0, 1.0)
    m = p.saturation_twi_low + frac * (p.saturation_twi_high - p.saturation_twi_low)
    # keep the AOI mean near the requested `saturation_ratio_m`
    m = m * (base / max(np.nanmean(m[fin]), 1e-6))
    m = np.clip(m, 0.0, 1.0)
    return np.where(fin, m, base)


def factor_of_safety(
    slope_deg: np.ndarray,
    c_kpa: np.ndarray,
    phi_deg: np.ndarray,
    gamma_kn_m3: np.ndarray,
    z_m: np.ndarray,
    m: np.ndarray,
    gamma_w_kn_m3: float,
) -> np.ndarray:
    """Infinite-slope FS (Hammond et al. 1992). Flat ground (β → 0) has a zero
    denominator → FS is capped at :data:`_FS_CAP`. NaN in any input → NaN out."""
    beta = np.radians(np.asarray(slope_deg, dtype="float64"))
    c = np.asarray(c_kpa, dtype="float64")
    tanphi = np.tan(np.radians(np.asarray(phi_deg, dtype="float64")))
    g = np.asarray(gamma_kn_m3, dtype="float64")
    z = np.asarray(z_m, dtype="float64")
    mm = np.clip(np.asarray(m, dtype="float64"), 0.0, 1.0)

    sinb, cosb = np.sin(beta), np.cos(beta)
    denom = g * z * sinb * cosb
    numer = c + (g - mm * gamma_w_kn_m3) * z * cosb**2 * tanphi
    with np.errstate(invalid="ignore", divide="ignore"):
        fs = np.where(denom > 1e-9, numer / denom, _FS_CAP)
    fs = np.clip(fs, 0.0, _FS_CAP)
    ok = (
        np.isfinite(beta)
        & np.isfinite(c)
        & np.isfinite(tanphi)
        & np.isfinite(g)
        & np.isfinite(z)
    )
    return np.where(ok, fs, np.nan)


def classify_fs(fs: np.ndarray, breaks: list[float]) -> np.ndarray:
    """FS → 0 unstable (< breaks[0]) / 1 marginal / 2 stable (≥ breaks[1]).
    NaN → -1."""
    f = np.asarray(fs, dtype="float64")
    cls = np.zeros(f.shape, dtype="int64")
    for b in breaks:
        cls += (f >= b).astype("int64")
    return np.where(np.isfinite(f), cls, -1)


def instability_index(fs: np.ndarray, kind: str) -> np.ndarray:
    """``inv_fs`` → ``1/FS`` (higher = less stable, ~0.1..∞ clamped to 10);
    ``sinmap_si`` → FS clipped to the SINMAP reporting range [0, 2] (equals FS
    for a single deterministic scenario)."""
    f = np.asarray(fs, dtype="float64")
    if kind == "sinmap_si":
        return np.where(np.isfinite(f), np.clip(f, 0.0, 2.0), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        inv = np.where(f > 1e-6, 1.0 / f, 10.0)
    return np.where(np.isfinite(f), np.clip(inv, 0.0, 10.0), np.nan)


def scenario_note(p: FactorOfSafetyParams, depth_mean_m: float) -> tuple[str, str]:
    """The bilingual sentence every FS figure / table carries."""
    ne = (
        f"पहिरो स्थायित्व (Factor of Safety) मनसुनी संतृप्त परिदृश्यमा गणना गरिएको — "
        f"रेगोलिथ गहिराइ ~{depth_mean_m:.1f} मि., छिद्र-दाब अनुपात m = {p.saturation_ratio_m:.2f}। "
        f"यो सम्भाव्यता होइन, एक परिदृश्य हो।"
    )
    en = (
        f"Factor of Safety computed under a saturated-monsoon scenario — "
        f"assumed regolith depth ~{depth_mean_m:.1f} m, pore-pressure ratio "
        f"m = {p.saturation_ratio_m:.2f}. This is a scenario, not a probability."
    )
    return ne, en


# ─────────────────────────────────────────────────────────────────────────────
# Result container
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class FSResult:
    grid: "se.GridSpec"
    params: HazardVulnParams
    fs: np.ndarray  # (h, w) Factor of Safety, 0.._FS_CAP
    classes: np.ndarray  # (h, w) 0 unstable / 1 marginal / 2 stable / -1 nodata
    instability: np.ndarray  # (h, w) 1/FS or SINMAP SI
    z_m: np.ndarray  # (h, w) assumed regolith depth
    m: np.ndarray  # (h, w) pore-pressure ratio used
    geotiff_path: Path
    scenario: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# DB → grids
# ─────────────────────────────────────────────────────────────────────────────
def _texture_c_phi_grids(
    db: "Session", grid: "se.GridSpec", p: FactorOfSafetyParams
) -> tuple[np.ndarray, np.ndarray]:
    """``(c'_texture kPa, φ' deg)`` from ``soil.soilgrids.soil_texture_class``
    (rasterised by MMU polygon). Longest substring key wins; unmatched → the
    configured defaults."""
    sql = (
        "SELECT ST_AsBinary(m.geom), sg.soil_texture_class "
        "FROM base.mmu m JOIN soil.soilgrids sg ON sg.mmuid = m.mmuid "
        "WHERE ST_Intersects(m.geom, ST_GeomFromText(:wkt, 4326))"
    )

    def _lookup(table: dict[str, float], default: float, v: object) -> float:
        s = str(v or "").strip().lower()
        if not s:
            return float(default)
        for key in sorted(table, key=len, reverse=True):
            if key in s:
                return float(table[key])
        return float(default)

    c = ls._rasterise_class_rating(
        db,
        grid,
        sql,
        lambda v: _lookup(p.cohesion_by_texture_kpa, p.cohesion_default_kpa, v),
    )
    phi = ls._rasterise_class_rating(
        db,
        grid,
        sql,
        lambda v: _lookup(p.friction_by_texture_deg, p.friction_default_deg, v),
    )
    # NaN (no soil polygon) → the defaults, so FS is defined everywhere the DEM is
    c = np.where(np.isfinite(c), c, p.cohesion_default_kpa)
    phi = np.where(np.isfinite(phi), phi, p.friction_default_deg)
    return c, phi


def _root_cohesion_grid(
    db: "Session", grid: "se.GridSpec", p: FactorOfSafetyParams
) -> np.ndarray:
    """Root-reinforcement cohesion (kPa) added to c′, by ESA WorldCover class
    (Sidle & Ochiai 2006). Classes not listed → 0."""
    esa = se._read_raster_to_grid(db, "rasters.esa_world_cover", 1, grid)
    esa_int = np.where(np.isfinite(esa), np.round(esa), -1).astype(np.int64)
    out = np.zeros(esa_int.shape, dtype="float64")
    for code, kpa in p.root_cohesion_by_esa_class.items():
        out[esa_int == code] = float(kpa)
    return out


def _gamma_grid(
    db: "Session", grid: "se.GridSpec", p: FactorOfSafetyParams
) -> np.ndarray:
    """Soil unit weight γ (kN m⁻³). ``bulk_density`` → ``9.81·BD`` from
    ``soil.soilgrids.bulk_density_kg_dm3`` (dry bulk density; a documented
    screening assumption), falling back to ``gamma_default_kn_m3`` where the
    join is empty. ``constant`` → ``gamma_default_kn_m3`` everywhere."""
    if p.unit_weight_source == "constant":
        return np.full((grid.height, grid.width), float(p.gamma_default_kn_m3))
    d = se._read_mmu_to_grid(
        db,
        grid,
        "SELECT ST_AsText(m.geom), sg.bulk_density_kg_dm3 "
        "FROM base.mmu m JOIN soil.soilgrids sg ON sg.mmuid = m.mmuid "
        "WHERE ST_Intersects(m.geom, ST_GeomFromText(:wkt, 4326))",
        ["bd"],
    )
    bd = d["bd"]
    gamma = 9.81 * bd
    return np.where(np.isfinite(gamma), gamma, p.gamma_default_kn_m3)


def _twi_grid(db: "Session", grid: "se.GridSpec", slope_pct: np.ndarray):
    """AOI TWI for the wetness-varied ``m``. ``None`` if the grid is over the
    D8 cap (then ``m`` is flat)."""
    if grid.width * grid.height > se._D8_CELL_CAP:
        logger.warning("FS: grid over the D8 cap — m held flat (no TWI variation)")
        return None
    from app.services.operational_plan import soil_erosion_d8 as d8

    dem = se._read_raster_to_grid(db, "rasters.dem", 1, grid, lo=-500, hi=9000)
    fn = d8.flow_network(dem, ~np.isfinite(dem))
    return ls.twi(fn["acc"], slope_pct, grid.dx_m)


# ─────────────────────────────────────────────────────────────────────────────
# GeoTIFF cache
# ─────────────────────────────────────────────────────────────────────────────
def _cache_path(calculation_id: UUID, params: HazardVulnParams) -> Path:
    return _CACHE_ROOT / str(calculation_id) / f"fs_{params_hash(params)}.tif"


def clear_cache(calculation_id: UUID) -> None:
    import shutil

    d = _CACHE_ROOT / str(calculation_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def _write_geotiff(path: Path, grid: "se.GridSpec", bands: list[np.ndarray]) -> None:
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
        crs=CRS.from_wkt(se._WGS84_WKT),
        nodata=float("nan"),
        compress="deflate",
    ) as ds:
        for i, arr in enumerate(bands, start=1):
            ds.write(np.asarray(arr, dtype="float32"), i)
            ds.set_band_description(i, _FS_BANDS[i - 1])


def _read_geotiff(
    path: Path, grid: "se.GridSpec", params: HazardVulnParams, scenario: dict
) -> FSResult:
    import rasterio

    with rasterio.open(path) as ds:
        b = [ds.read(i).astype("float64") for i in range(1, ds.count + 1)]
    return FSResult(
        grid, params, b[0], b[1].astype("int64"), b[2], b[3], b[4], path, scenario
    )


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────
def compute_fs(db: "Session", calculation_id: UUID, *, force: bool = False) -> FSResult:
    """Resolve params, build the RUSLE grid, evaluate the infinite-slope FS
    under the monsoon scenario, classify it, and cache a multi-band GeoTIFF.
    Returns a fully-``NaN`` surface (still cached) when
    ``factor_of_safety.enabled`` is False."""
    params = resolve_params(db, calculation_id)
    fp = params.factor_of_safety
    path = _cache_path(calculation_id, params)
    grid = se.build_grid(db, calculation_id)

    dem = se._read_raster_to_grid(db, "rasters.dem", 1, grid, lo=-500, hi=9000)
    slope_pct = se.slope_pct_from_dem(dem, grid.dx_m, grid.dy_m)
    slope_deg = np.degrees(np.arctan(slope_pct / 100.0))

    if not fp.enabled:
        nan = np.full((grid.height, grid.width), np.nan)
        scenario = {"enabled": False}
        _write_geotiff(path, grid, [nan] * len(_FS_BANDS))
        return FSResult(
            grid,
            params,
            nan,
            np.full_like(nan, -1, dtype="int64"),
            nan,
            nan,
            nan,
            path,
            scenario,
        )

    twi = _twi_grid(db, grid, slope_pct)
    m = saturation_ratio(twi, fp, (grid.height, grid.width))
    z = soil_depth_m(slope_deg, fp)
    c_tex, phi = _texture_c_phi_grids(db, grid, fp)
    c_total = c_tex + _root_cohesion_grid(db, grid, fp)
    gamma = _gamma_grid(db, grid, fp)

    fs = factor_of_safety(slope_deg, c_total, phi, gamma, z, m, fp.gamma_w_kn_m3)
    classes = classify_fs(fs, fp.fs_class_breaks)
    inst = instability_index(fs, fp.instability_index)

    depth_mean = float(np.nanmean(z)) if np.isfinite(z).any() else fp.depth_constant_m
    note_ne, note_en = scenario_note(fp, depth_mean)
    scenario = {
        "enabled": True,
        "soil_depth_model": fp.soil_depth_model,
        "depth_mean_m": round(depth_mean, 2),
        "saturation_ratio_m": fp.saturation_ratio_m,
        "saturation_twi_varied": fp.saturation_twi_varied and twi is not None,
        "instability_index": fp.instability_index,
        "fs_class_breaks": list(fp.fs_class_breaks),
        "note_ne": note_ne,
        "note_en": note_en,
    }

    if path.exists() and not force and se.cache_matches_grid(path, grid):
        try:
            return _read_geotiff(path, grid, params, scenario)
        except Exception:  # noqa: BLE001 -- corrupt cache → fall through & rewrite
            logger.warning("FS cache unreadable, recomputing: %s", path)

    _write_geotiff(
        path, grid, [fs, classes.astype("float32"), inst, z, m, c_total, phi, gamma]
    )
    return FSResult(grid, params, fs, classes, inst, z, m, path, scenario)


# ─────────────────────────────────────────────────────────────────────────────
# Summaries
# ─────────────────────────────────────────────────────────────────────────────
def _fs_summary(classes: np.ndarray, area_ha: np.ndarray, mask: np.ndarray) -> dict:
    sel = mask & (classes >= 0)
    if not sel.any():
        return {
            "area_ha": 0.0,
            "unstable_ha": 0.0,
            "marginal_ha": 0.0,
            "stable_ha": 0.0,
            "unstable_pct": 0.0,
            "marginal_pct": 0.0,
        }
    cls = classes[sel]
    ar = area_ha[sel]
    tot = float(ar.sum())
    unstable = float(ar[cls == 0].sum())
    marginal = float(ar[cls == 1].sum())
    stable = float(ar[cls == 2].sum())
    return {
        "area_ha": round(tot, 2),
        "unstable_ha": round(unstable, 2),
        "marginal_ha": round(marginal, 2),
        "stable_ha": round(stable, 2),
        "unstable_pct": round(100.0 * unstable / tot, 1),
        "marginal_pct": round(100.0 * marginal / tot, 1),
    }


def zonal_summary(result: FSResult, units: list[dict]) -> dict[str, dict]:
    """``{unit_name: {area_ha, unstable_ha, marginal_ha, stable_ha, …}}``."""
    from rasterio.features import geometry_mask
    from shapely.geometry import mapping

    g = result.grid
    out: dict[str, dict] = {}
    for u in units:
        geom = u.get("geometry")
        if geom is None or geom.is_empty:
            continue
        mk = geometry_mask(
            [mapping(geom)],
            (g.height, g.width),
            g.transform,
            invert=True,
            all_touched=True,
        )
        out[u["name"]] = _fs_summary(result.classes, g.cell_area_ha, mk)
    return out


def aoi_summary(result: FSResult, mask: np.ndarray) -> dict:
    """FS-class summary over a boolean AOI mask."""
    return _fs_summary(result.classes, result.grid.cell_area_ha, mask)


def class_label(idx: int, lang: str = "ne") -> str:
    labels = FS_CLASS_LABELS_NE if lang == "ne" else FS_CLASS_LABELS_EN
    return labels[idx] if 0 <= idx < len(labels) else str(idx)


__all__ = [
    "soil_depth_m",
    "saturation_ratio",
    "factor_of_safety",
    "classify_fs",
    "instability_index",
    "scenario_note",
    "FSResult",
    "compute_fs",
    "zonal_summary",
    "aoi_summary",
    "class_label",
    "clear_cache",
]
