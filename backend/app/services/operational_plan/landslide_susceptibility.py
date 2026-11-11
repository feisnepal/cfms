"""Landslide Susceptibility Index (LSI) — expert-weighted multi-criteria overlay.

``HOUSEHOLD_VULNERABILITY_ANALYSIS_PLAN.md`` §2.1 / phase P1.

There is **no landslide inventory** in ``cf_db``, so this is a transparent
weighted overlay of reclassed predisposing factors — *relative* susceptibility,
not probability, and unvalidated against mapped failures. Ten factors, each
reclassed to a 1–5 rating, combined as ``LSI = Σ wᵢ·ratingᵢ`` with weights from
:class:`LandslideParams.weights` (``weighted_overlay``) or the principal
eigenvector of :attr:`~LandslideParams.ahp_matrix` (``ahp``). The score is then
reclassed to ``n_classes`` (Very Low → Very High) and the cells at class
``≥ prone_class_min`` are dissolved into the "landslide-prone area" polygon.

Reuses the RUSLE compute grid wholesale (``soil_erosion.build_grid`` /
``GridSpec`` / ``_read_raster_to_grid`` / ``slope_pct_from_dem``) and the
vendored D8 (``soil_erosion_d8.flow_network``) for the contributing area behind
TWI / SPI. Output is a cached multi-band GeoTIFF under
``uploads/hazard_vuln_cache/<calc_id>/lsi_<params_hash>.tif``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from uuid import UUID

import numpy as np

from app.services.operational_plan import soil_erosion as se
from app.services.operational_plan.hazard_vuln_config import (
    LSI_FACTORS,
    HazardVulnParams,
    LandslideParams,
    params_hash,
    resolve_params,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_CACHE_ROOT = Path("uploads/hazard_vuln_cache")

# Random Index for the AHP consistency ratio, Saaty (1980), n = 1..10.
_AHP_RI = (0.0, 0.0, 0.58, 0.90, 1.12, 1.24, 1.32, 1.41, 1.45, 1.49)

# Built-in lithology keyword → rating fallback, applied to geology.geology's
# ``geo_class`` (lower-cased) when it is not matched by params.lithology_ratings.
# Weak Siwalik mudstone/shale is the most landslide-prone; hard crystalline
# rock the least. Longest keys are tried first.
_LITHOLOGY_FALLBACK: tuple[tuple[str, int], ...] = (
    ("upper siwalik", 5),
    ("middle siwalik", 5),
    ("lower siwalik", 4),
    ("siwalik", 5),
    ("mudstone", 5),
    ("shale", 5),
    ("claystone", 5),
    ("siltstone", 4),
    ("phyllite", 4),
    ("schist", 4),
    ("slate", 4),
    ("sandstone", 4),
    ("limestone", 3),
    ("dolomite", 3),
    ("colluvium", 3),
    ("alluvium", 3),
    ("terrace", 3),
    ("recent", 3),
    ("quartzite", 2),
    ("gneiss", 2),
    ("granite", 2),
    ("basic rock", 2),
    ("marble", 2),
)

# ``landuse_yr1984`` values (lower-cased, substring) that count as forest, for
# the deforestation-since-1984 rating bump.
_FOREST_1984_KEYS = ("forest", "वन", "jungle", "tree")

# ESA WorldCover codes that count as forest today (for the same bump).
_ESA_FOREST_CODES = (10, 20)


# ─────────────────────────────────────────────────────────────────────────────
# Pure kernels — no DB, no rasterio
# ─────────────────────────────────────────────────────────────────────────────
def rating_from_breaks(
    values: np.ndarray, breaks: list[float], *, ascending: bool
) -> np.ndarray:
    """Reclass ``values`` to a 1..(len(breaks)+1) rating.

    ``ascending=True``  → higher value ⇒ higher rating (slope, rainfall).
    ``ascending=False`` → lower value ⇒ higher rating (distance-to-drainage).
    NaN in → NaN out.
    """
    v = np.asarray(values, dtype="float64")
    idx = np.zeros(v.shape, dtype="float64")
    for b in breaks:
        idx += v >= b
    rating = idx + 1.0  # 1..len(breaks)+1
    if not ascending:
        rating = (len(breaks) + 2.0) - rating  # mirror
    return np.where(np.isfinite(v), rating, np.nan)


def profile_plan_curvature(
    dem_f: np.ndarray, dx_m: float, dy_m: float
) -> tuple[np.ndarray, np.ndarray]:
    """Profile and plan curvature (1/m) by second-order finite differences
    (Zevenbergen & Thorne 1987 form, simplified). Positive profile curvature =
    convex (accelerating flow); negative plan curvature = convergent."""
    z = np.asarray(dem_f, dtype="float64")
    zy, zx = np.gradient(z, dy_m, dx_m, edge_order=1)
    zyy, zyx = np.gradient(zy, dy_m, dx_m, edge_order=1)
    _, zxx = np.gradient(zx, dy_m, dx_m, edge_order=1)
    p = zx**2 + zy**2
    denom_prof = p * np.sqrt(np.maximum(1.0 + p, 1e-12))
    denom_plan = np.maximum(p, 1e-12) ** 1.5
    with np.errstate(invalid="ignore", divide="ignore"):
        profile = -(zxx * zx**2 + 2.0 * zyx * zx * zy + zyy * zy**2) / np.where(
            denom_prof > 1e-12, denom_prof, np.nan
        )
        plan = -(zxx * zy**2 - 2.0 * zyx * zx * zy + zyy * zx**2) / np.where(
            denom_plan > 1e-12, denom_plan, np.nan
        )
    return profile, plan


def twi(acc_cells: np.ndarray, slope_pct: np.ndarray, cell_m: float) -> np.ndarray:
    """Topographic Wetness Index ``ln(a / tanβ)`` (Beven & Kirkby 1979).
    ``a`` = upslope contributing area per unit contour width ≈ ``acc_cells·cell``.
    ``tanβ`` is floored so ridge cells stay finite."""
    a = np.asarray(acc_cells, dtype="float64") * float(cell_m)
    tanb = np.maximum(np.asarray(slope_pct, dtype="float64") / 100.0, 1e-3)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.log(np.maximum(a, cell_m) / tanb)


def stream_power_index(
    acc_cells: np.ndarray, slope_pct: np.ndarray, cell_m: float
) -> np.ndarray:
    """SPI ``a·tanβ`` — erosive power of concentrated flow."""
    a = np.asarray(acc_cells, dtype="float64") * float(cell_m)
    tanb = np.maximum(np.asarray(slope_pct, dtype="float64") / 100.0, 1e-4)
    return np.maximum(a, cell_m) * tanb


def euclidean_distance_m(mask_true: np.ndarray, cell_m: float) -> np.ndarray:
    """Exact Euclidean distance (m) from every cell to the nearest ``True``
    cell in ``mask_true`` — separable Felzenszwalb & Huttenlocher (2012)
    transform, pure numpy (no scipy on this box). All-``False`` → all ``inf``."""
    m = np.asarray(mask_true, dtype=bool)
    if not m.any():
        return np.full(m.shape, np.inf, dtype="float64")
    big = float(m.size) ** 2 + 1.0
    f = np.where(m, 0.0, big).astype("float64")

    def _dt_1d(row: np.ndarray) -> np.ndarray:
        n = row.shape[0]
        d = np.empty(n, dtype="float64")
        v = np.zeros(n, dtype="int64")
        z = np.empty(n + 1, dtype="float64")
        k = 0
        v[0] = 0
        z[0] = -np.inf
        z[1] = np.inf
        for q in range(1, n):
            s = ((row[q] + q * q) - (row[v[k]] + v[k] * v[k])) / (2.0 * q - 2.0 * v[k])
            while s <= z[k]:
                k -= 1
                s = ((row[q] + q * q) - (row[v[k]] + v[k] * v[k])) / (
                    2.0 * q - 2.0 * v[k]
                )
            k += 1
            v[k] = q
            z[k] = s
            z[k + 1] = np.inf
        k = 0
        for q in range(n):
            while z[k + 1] < q:
                k += 1
            d[q] = (q - v[k]) ** 2 + row[v[k]]
        return d

    tmp = np.apply_along_axis(_dt_1d, 0, f)
    sq = np.apply_along_axis(_dt_1d, 1, tmp)
    return np.sqrt(sq) * float(cell_m)


def ahp_weights(matrix: list[list[float]]) -> tuple[dict[str, float], float]:
    """Principal-eigenvector weights by the geometric-mean method + the Saaty
    consistency ratio. Returns ``({factor: weight}, CR)`` in ``LSI_FACTORS``
    order."""
    a = np.asarray(matrix, dtype="float64")
    n = a.shape[0]
    gm = np.prod(a, axis=1) ** (1.0 / n)
    w = gm / gm.sum()
    aw = a @ w
    lam_max = float(np.mean(aw / w))
    ci = (lam_max - n) / (n - 1) if n > 1 else 0.0
    ri = _AHP_RI[n - 1] if 0 < n <= len(_AHP_RI) else _AHP_RI[-1]
    cr = ci / ri if ri > 0 else 0.0
    return {LSI_FACTORS[i]: float(w[i]) for i in range(n)}, float(cr)


def effective_weights(params: LandslideParams) -> tuple[dict[str, float], float]:
    """The weights the overlay actually uses: normalised :attr:`weights` for
    ``weighted_overlay``; the AHP eigenvector for ``ahp``. Second element is the
    AHP consistency ratio (0.0 for ``weighted_overlay``)."""
    if params.method == "ahp":
        return ahp_weights(params.ahp_matrix)
    total = sum(params.weights.values()) or 1.0
    return {k: v / total for k, v in params.weights.items()}, 0.0


def weighted_overlay(
    ratings: dict[str, np.ndarray], weights: dict[str, float]
) -> np.ndarray:
    """``Σ wᵢ·ratingᵢ`` over the factors present in both dicts. A factor whose
    rating grid is entirely NaN (data absent) is dropped and the remaining
    weights are renormalised, so a missing layer degrades the score rather than
    voiding it."""
    present = [f for f in weights if f in ratings and np.isfinite(ratings[f]).any()]
    if not present:
        any_grid = next(iter(ratings.values()))
        return np.full(any_grid.shape, np.nan)
    wsum = sum(weights[f] for f in present) or 1.0
    shape = ratings[present[0]].shape
    acc = np.zeros(shape, dtype="float64")
    wcov = np.zeros(shape, dtype="float64")
    for f in present:
        r = ratings[f]
        w = weights[f] / wsum
        ok = np.isfinite(r)
        acc[ok] += w * r[ok]
        wcov[ok] += w
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(wcov > 0, acc / wcov, np.nan)
    return out


def classify(
    score: np.ndarray,
    *,
    method: str,
    n_classes: int,
    breaks_fixed: list[float],
    mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """LSI score → 0-based class index (0 = lowest). NaN → -1. ``quantile`` and
    ``equal`` breaks are derived from the values inside ``mask`` (defaults to
    every finite cell)."""
    s = np.asarray(score, dtype="float64")
    finite = np.isfinite(s)
    sel = finite & mask if mask is not None else finite
    out = np.full(s.shape, -1, dtype="int64")
    if not sel.any():
        return out
    vals = s[sel]
    if method == "fixed":
        edges = list(breaks_fixed)
    elif method == "equal":
        lo, hi = float(vals.min()), float(vals.max())
        if hi <= lo:
            out[finite] = 0
            return out
        edges = [lo + (hi - lo) * i / n_classes for i in range(1, n_classes)]
    else:  # quantile
        qs = [100.0 * i / n_classes for i in range(1, n_classes)]
        edges = [float(x) for x in np.percentile(vals, qs)]
        edges = sorted(set(edges)) or [float(vals.mean())]
    cls = np.zeros(s.shape, dtype="int64")
    for e in edges:
        cls += (s >= e).astype("int64")
    out[finite] = np.clip(cls[finite], 0, n_classes - 1)
    return out


def lithology_rating(class_str: Optional[str], params: LandslideParams) -> float:
    """Rating for one ``geology.geology`` unit: an explicit
    ``params.lithology_ratings`` substring wins; else the built-in keyword
    fallback; else ``params.lithology_default_rating``."""
    if not class_str:
        return float(params.lithology_default_rating)
    low = class_str.strip().lower()
    for key in sorted(params.lithology_ratings, key=len, reverse=True):
        if key.lower() in low:
            return float(params.lithology_ratings[key])
    for key, rating in _LITHOLOGY_FALLBACK:
        if key in low:
            return float(rating)
    return float(params.lithology_default_rating)


def texture_rating(texture: Optional[str], params: LandslideParams) -> float:
    """Rating for one ``soil_texture_class`` value (substring, longest key
    first)."""
    if not texture:
        return float(params.soil_texture_default_rating)
    low = texture.strip().lower()
    for key in sorted(params.soil_texture_ratings, key=len, reverse=True):
        if key in low:
            return float(params.soil_texture_ratings[key])
    return float(params.soil_texture_default_rating)


# ─────────────────────────────────────────────────────────────────────────────
# Result container
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class LSIResult:
    grid: "se.GridSpec"
    params: HazardVulnParams
    lsi: np.ndarray  # (h, w) weighted-mean score, ~1..5
    classes: np.ndarray  # (h, w) int, 0..n_classes-1, -1 = no data
    ratings: dict[str, np.ndarray]  # factor → (h, w) 1..5 rating grid
    weights: dict[str, float]  # the weights actually used
    consistency_ratio: float  # AHP CR (0.0 for weighted_overlay)
    prone_area_wkt: Optional[str]  # dissolved class ≥ prone_class_min polygon
    geotiff_path: Path


_LSI_BANDS = ("lsi", "class", *LSI_FACTORS)


# ─────────────────────────────────────────────────────────────────────────────
# DB → rating grids
# ─────────────────────────────────────────────────────────────────────────────
def _rasterise_class_rating(
    db: "Session", grid: "se.GridSpec", sql: str, rate: "callable"
) -> np.ndarray:
    """Rasterise a polygon layer to a rating grid. ``sql`` is a SELECT that
    returns ``(geom_wkb, class_value)`` rows and takes a ``:wkt`` param; each
    class string is mapped through ``rate`` in Python before the burn. All-NaN
    when nothing intersects (the overlay then drops the factor)."""
    from rasterio.features import rasterize
    from shapely import wkb as _wkb
    from sqlalchemy import text

    shapes: list[tuple[object, float]] = []
    try:
        rows = db.execute(text(sql), {"wkt": grid.aoi_wkt}).fetchall()
    except Exception:  # noqa: BLE001 -- layer absent → factor dropped by the overlay
        logger.debug("class-rating layer read failed: %s", sql[:60], exc_info=True)
        return np.full((grid.height, grid.width), np.nan)
    for gb, cls in rows:
        if gb is None:
            continue
        try:
            g = _wkb.loads(bytes(gb))
        except Exception:  # noqa: BLE001
            continue
        if g.is_empty:
            continue
        shapes.append((g, float(rate(cls))))
    if not shapes:
        return np.full((grid.height, grid.width), np.nan)
    return rasterize(
        shapes,
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        fill=np.nan,
        dtype="float64",
        all_touched=True,
    )


def _line_distance_rating(
    db: "Session", grid: "se.GridSpec", sql: str, breaks_m: list[float]
) -> np.ndarray:
    """Rasterise a line layer, Euclidean-distance-transform it, and reclass
    (nearer ⇒ higher rating). ``sql`` returns ``(geom_wkb,)`` rows clipped to
    ``:wkt``. All-NaN when the layer is absent or nothing intersects."""
    from rasterio.features import rasterize
    from shapely import wkb as _wkb
    from sqlalchemy import text

    geoms = []
    try:
        for (gb,) in db.execute(text(sql), {"wkt": grid.aoi_wkt}).fetchall():
            if gb is None:
                continue
            g = _wkb.loads(bytes(gb))
            if g and not g.is_empty:
                geoms.append(g)
    except Exception:  # noqa: BLE001 -- layer absent → factor dropped by the overlay
        logger.debug("distance layer read failed: %s", sql[:60], exc_info=True)
        return np.full((grid.height, grid.width), np.nan)
    if not geoms:
        return np.full((grid.height, grid.width), np.nan)
    burn = rasterize(
        ((g, 1) for g in geoms),
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        fill=0,
        dtype="uint8",
        all_touched=True,
    ).astype(bool)
    dist = euclidean_distance_m(burn, grid.dx_m)  # burn.any() → all finite
    return rating_from_breaks(dist, breaks_m, ascending=False)


def _curv_twi_rating(
    db: "Session", grid: "se.GridSpec", slope_pct: np.ndarray, p: LandslideParams
) -> np.ndarray:
    """Base rating 3, +``twi_bump`` on wet-convergent cells (TWI above the
    ``twi_high_percentile`` of the AOI **and** plan curvature convergent)."""
    dem = se._read_raster_to_grid(db, "rasters.dem", 1, grid, lo=-500, hi=9000)
    nodata = ~np.isfinite(dem)
    from app.services.operational_plan import soil_erosion_d8 as d8

    if grid.width * grid.height <= se._D8_CELL_CAP:
        fn = d8.flow_network(dem, nodata)
        acc = fn["acc"]
        dem_f = fn["dem_f"]
    else:
        logger.warning("LSI: grid over the D8 cap — TWI from local slope only")
        acc = np.ones_like(dem)
        dem_f = dem
    t = twi(acc, slope_pct, grid.dx_m)
    _, plan = profile_plan_curvature(dem_f, grid.dx_m, grid.dy_m)
    rating = np.full(dem.shape, 3.0)
    finite = np.isfinite(t)
    if finite.any():
        hi = np.percentile(t[finite], p.twi_high_percentile)
        convergent = np.isfinite(plan) & (plan < 0)
        rating = np.where(finite & (t >= hi) & convergent, 3.0 + p.twi_bump, rating)
        rating = np.where(
            finite & (t >= hi) & ~convergent, 3.0 + p.twi_bump / 2.0, rating
        )
    rating[~np.isfinite(dem)] = np.nan
    return np.clip(rating, 1.0, 5.0)


def _esa_class_grid(db: "Session", grid: "se.GridSpec") -> np.ndarray:
    esa = se._read_raster_to_grid(db, "rasters.esa_world_cover", 1, grid)
    return np.where(np.isfinite(esa), np.round(esa), -1).astype(np.int64)


def _landcover_class_rating(esa_int: np.ndarray, p: LandslideParams) -> np.ndarray:
    """ESA WorldCover class → ``landcover_ratings`` (forest low, bare high)."""
    rating = np.full(esa_int.shape, float(p.landcover_default_rating))
    for code, r in p.landcover_ratings.items():
        rating[esa_int == code] = float(r)
    rating[esa_int < 0] = np.nan
    return rating


def _landcover_change_rating(
    db: "Session", grid: "se.GridSpec", esa_int: np.ndarray, p: LandslideParams
) -> np.ndarray:
    """A standalone deforestation-since-1984 factor: rating 1 where cover is
    unchanged / still forest, ``1 + landcover_change_bump·<step>`` where
    ``landcover_1984`` was forest and ESA now is not. All-NaN when the 1984
    layer is unavailable (factor then dropped by the overlay)."""

    def _was_forest(v: object) -> float:
        s = str(v or "").lower()
        return 1.0 if any(k in s for k in _FOREST_1984_KEYS) else 0.0

    old_forest = _rasterise_class_rating(
        db,
        grid,
        "SELECT ST_AsBinary(geom), landuse_yr1984 FROM landcover.landcover_1984 "
        "WHERE ST_Intersects(geom, ST_GeomFromText(:wkt, 4326))",
        _was_forest,
    )
    if not np.isfinite(old_forest).any():
        return np.full(esa_int.shape, np.nan)
    now_forest = np.isin(esa_int, _ESA_FOREST_CODES)
    rating = np.where(esa_int >= 0, 1.0, np.nan)
    deforested = (old_forest == 1.0) & ~now_forest & (esa_int >= 0)
    step = 1.0 + 2.0 * float(p.landcover_change_bump)  # bump 1 → rating 3
    rating = np.where(deforested, min(step, 5.0), rating)
    return rating


def _seismic_rating(
    db: "Session", grid: "se.GridSpec", p: LandslideParams
) -> np.ndarray:
    """Magnitude-weighted epicentral density from ``hazards.earthquakes`` within
    ``seismic_radius_km``, min-max reclassed to 1..5. OFF unless
    ``seismic_enabled`` — a point catalogue, not probabilistic ground motion."""
    from sqlalchemy import text

    try:
        rows = db.execute(
            text(
                "SELECT ST_X(geom), ST_Y(geom), mag FROM hazards.earthquakes "
                "WHERE mag >= :mmin AND ST_DWithin("
                "geom::geography, ST_GeomFromText(:wkt, 4326)::geography, :rad)"
            ),
            {
                "mmin": p.seismic_min_magnitude,
                "wkt": grid.aoi_wkt,
                "rad": p.seismic_radius_km * 1000.0,
            },
        ).fetchall()
    except Exception:  # noqa: BLE001
        logger.debug("hazards.earthquakes read failed", exc_info=True)
        return np.full((grid.height, grid.width), np.nan)
    if not rows:
        return np.full((grid.height, grid.width), np.nan)
    jj, ii = np.mgrid[0 : grid.height, 0 : grid.width]
    t = grid.transform
    xs = t.c + (ii + 0.5) * t.a
    ys = t.f + (jj + 0.5) * t.e
    dens = np.zeros((grid.height, grid.width), dtype="float64")
    r_deg = p.seismic_radius_km / 111.32
    for ex, ey, mag in rows:
        d2 = (xs - ex) ** 2 + (ys - ey) ** 2
        dens += float(mag) * np.exp(-d2 / (2.0 * (r_deg / 2.0) ** 2))
    lo, hi = float(dens.min()), float(dens.max())
    if hi <= lo:
        return np.full((grid.height, grid.width), 3.0)
    return 1.0 + 4.0 * (dens - lo) / (hi - lo)


def factor_ratings(
    db: "Session", grid: "se.GridSpec", params: HazardVulnParams
) -> dict[str, np.ndarray]:
    """All ten 1..5 rating grids, keyed by :data:`LSI_FACTORS`. A layer that is
    absent for this forest comes back all-NaN and is dropped by
    :func:`weighted_overlay`."""
    lp = params.landslide
    dem = se._read_raster_to_grid(db, "rasters.dem", 1, grid, lo=-500, hi=9000)
    slope_pct = se.slope_pct_from_dem(dem, grid.dx_m, grid.dy_m)
    slope_deg = np.degrees(np.arctan(slope_pct / 100.0))

    aspect = se._read_raster_to_grid(db, "rasters.aspect", 1, grid, lo=0, hi=9)
    aspect_code = np.where(np.isfinite(aspect), np.round(aspect), -1).astype(np.int64)
    aspect_rating = np.full(aspect_code.shape, 3.0)
    aspect_rating[np.isin(aspect_code, lp.aspect_monsoon_codes)] = (
        3.0 + lp.aspect_monsoon_bump
    )
    aspect_rating[aspect_code < 0] = np.nan

    p_mm = se._read_raster_to_grid(
        db, "rasters.annual_precipitation", 1, grid, lo=0, hi=20000
    )

    esa_int = _esa_class_grid(db, grid)
    tex_rating = _rasterise_class_rating(
        db,
        grid,
        "SELECT ST_AsBinary(m.geom), sg.soil_texture_class "
        "FROM base.mmu m JOIN soil.soilgrids sg ON sg.mmuid = m.mmuid "
        "WHERE ST_Intersects(m.geom, ST_GeomFromText(:wkt, 4326))",
        lambda v: texture_rating(v, lp),
    )
    seismic = (
        _seismic_rating(db, grid, lp)
        if lp.seismic_enabled
        else np.full((grid.height, grid.width), np.nan)
    )

    return {
        "slope": rating_from_breaks(
            slope_deg, lp.slope_rating_breaks_deg, ascending=True
        ),
        "lithology": _rasterise_class_rating(
            db,
            grid,
            "SELECT ST_AsBinary(geom), geo_class FROM geology.geology "
            "WHERE ST_Intersects(geom, ST_GeomFromText(:wkt, 4326))",
            lambda v: lithology_rating(v, lp),
        ),
        "curvature_twi": _curv_twi_rating(db, grid, slope_pct, lp),
        "dist_drainage": _line_distance_rating(
            db,
            grid,
            "SELECT ST_AsBinary(ST_Intersection(shape, ST_GeomFromText(:wkt, 4326))) "
            "FROM river.river84 WHERE ST_Intersects(shape, ST_GeomFromText(:wkt, 4326))",
            lp.dist_drainage_breaks_m,
        ),
        "dist_road": _line_distance_rating(
            db,
            grid,
            "SELECT ST_AsBinary(ST_Intersection(geom, ST_GeomFromText(:wkt, 4326))) "
            "FROM infrastructure.road "
            "WHERE ST_Intersects(geom, ST_GeomFromText(:wkt, 4326))",
            lp.dist_road_breaks_m,
        ),
        "landcover": _landcover_class_rating(esa_int, lp),
        "landcover_change": _landcover_change_rating(db, grid, esa_int, lp),
        "aspect": aspect_rating,
        "rainfall": rating_from_breaks(
            p_mm, lp.rainfall_rating_breaks_mm, ascending=True
        ),
        "soil_texture": tex_rating,
        # seismic is not a LSI_FACTORS key — it is blended post-overlay when
        # enabled (see compute_lsi), so it does not disturb the weight set.
        "_seismic": seismic,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GeoTIFF cache
# ─────────────────────────────────────────────────────────────────────────────
def _cache_path(calculation_id: UUID, params: HazardVulnParams) -> Path:
    return _CACHE_ROOT / str(calculation_id) / f"lsi_{params_hash(params)}.tif"


def clear_cache(calculation_id: UUID) -> None:
    import shutil

    d = _CACHE_ROOT / str(calculation_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def _write_geotiff(
    path: Path,
    grid: "se.GridSpec",
    lsi: np.ndarray,
    classes: np.ndarray,
    ratings: dict[str, np.ndarray],
) -> None:
    import rasterio
    from rasterio.crs import CRS

    path.parent.mkdir(parents=True, exist_ok=True)
    bands = [lsi, classes.astype("float32")] + [
        ratings.get(f, np.full(lsi.shape, np.nan)) for f in LSI_FACTORS
    ]
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
            ds.set_band_description(i, _LSI_BANDS[i - 1])


def _read_geotiff(
    path: Path,
    grid: "se.GridSpec",
    params: HazardVulnParams,
    weights: dict[str, float],
    cr: float,
    prone_wkt: Optional[str],
) -> LSIResult:
    import rasterio

    with rasterio.open(path) as ds:
        b = [ds.read(i).astype("float64") for i in range(1, ds.count + 1)]
    ratings = {f: b[2 + i] for i, f in enumerate(LSI_FACTORS) if 2 + i < len(b)}
    return LSIResult(
        grid, params, b[0], b[1].astype("int64"), ratings, weights, cr, prone_wkt, path
    )


def _prone_polygon(
    classes: np.ndarray, grid: "se.GridSpec", prone_class_min: int
) -> Optional[str]:
    """Dissolve the cells at class ≥ ``prone_class_min`` (1-based) into one
    (multi)polygon WKT, clipped to the CF ∪ UG AOI."""
    from rasterio.features import shapes as rio_shapes
    from shapely.geometry import shape as shp_shape
    from shapely.ops import unary_union

    mask = (classes >= (prone_class_min - 1)) & (classes >= 0)
    if not mask.any():
        return None
    polys = [
        shp_shape(geom)
        for geom, val in rio_shapes(
            mask.astype("uint8"), mask=mask, transform=grid.transform
        )
        if val == 1
    ]
    if not polys:
        return None
    u = unary_union(polys)
    return u.wkt if u and not u.is_empty else None


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────
def compute_lsi(
    db: "Session", calculation_id: UUID, *, force: bool = False
) -> LSIResult:
    """Resolve params, build the RUSLE grid, compute the ten rating grids, the
    weighted LSI, its classes and the landslide-prone polygon; cache a
    multi-band GeoTIFF."""
    params = resolve_params(db, calculation_id)
    lp = params.landslide
    weights, cr = effective_weights(lp)
    grid = se.build_grid(db, calculation_id)
    path = _cache_path(calculation_id, params)

    if path.exists() and not force and se.cache_matches_grid(path, grid):
        try:
            res = _read_geotiff(path, grid, params, weights, cr, None)
            res.prone_area_wkt = _prone_polygon(res.classes, grid, lp.prone_class_min)
            return res
        except Exception:  # noqa: BLE001 -- corrupt cache → recompute
            logger.warning("LSI cache unreadable, recomputing: %s", path)

    ratings = factor_ratings(db, grid, params)
    lsi = weighted_overlay(ratings, weights)

    # seismic (optional) is blended after the weighted overlay so it never
    # perturbs the LSI_FACTORS weight set — a point-catalogue proxy, not PGA.
    seismic = ratings.pop("_seismic", None)
    if lp.seismic_enabled and seismic is not None and np.isfinite(seismic).any():
        w = float(lp.seismic_weight)
        blended = (1.0 - w) * lsi + w * seismic
        lsi = np.where(np.isfinite(lsi) & np.isfinite(seismic), blended, lsi)

    classes = classify(
        lsi,
        method=lp.class_method,
        n_classes=lp.n_classes,
        breaks_fixed=lp.class_breaks_fixed,
        mask=grid.cf_mask if grid.cf_mask is not None else None,
    )
    prone_wkt = _prone_polygon(classes, grid, lp.prone_class_min)
    _write_geotiff(path, grid, lsi, classes, ratings)
    return LSIResult(grid, params, lsi, classes, ratings, weights, cr, prone_wkt, path)


# ─────────────────────────────────────────────────────────────────────────────
# Summaries
# ─────────────────────────────────────────────────────────────────────────────
def _class_summary(
    classes: np.ndarray, area_ha: np.ndarray, mask: np.ndarray, n_classes: int
) -> dict:
    sel = mask & (classes >= 0)
    if not sel.any():
        return {"area_ha": 0.0, "by_class_ha": {}, "by_class_pct": {}, "prone_ha": 0.0}
    cls = classes[sel]
    ar = area_ha[sel]
    tot = float(ar.sum())
    by_ha = {
        i: round(float(ar[cls == i].sum()), 2)
        for i in range(n_classes)
        if (cls == i).any()
    }
    by_pct = {i: round(100.0 * v / tot, 1) for i, v in by_ha.items()}
    return {
        "area_ha": round(tot, 2),
        "by_class_ha": by_ha,
        "by_class_pct": by_pct,
        "mean_class": round(float(cls.mean()) + 1.0, 2),
    }


def zonal_summary(result: LSIResult, units: list[dict]) -> dict[str, dict]:
    """``{unit_name: {area_ha, by_class_ha, by_class_pct, mean_class}}``."""
    from rasterio.features import geometry_mask
    from shapely.geometry import mapping

    g = result.grid
    n = result.params.landslide.n_classes
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
        out[u["name"]] = _class_summary(result.classes, g.cell_area_ha, m, n)
    return out


def aoi_summary(result: LSIResult, mask: np.ndarray) -> dict:
    """Class summary over a boolean AOI mask (``grid.cf_mask`` / ``grid.ug_mask``
    / ``ug_mask & ~cf_mask``)."""
    return _class_summary(
        result.classes,
        result.grid.cell_area_ha,
        mask,
        result.params.landslide.n_classes,
    )


__all__ = [
    "rating_from_breaks",
    "profile_plan_curvature",
    "twi",
    "stream_power_index",
    "euclidean_distance_m",
    "ahp_weights",
    "effective_weights",
    "weighted_overlay",
    "classify",
    "lithology_rating",
    "texture_rating",
    "LSIResult",
    "factor_ratings",
    "compute_lsi",
    "zonal_summary",
    "aoi_summary",
    "clear_cache",
]
