"""Hazard & Erosion surfaces as map tiles for the workspace "Analysis maps" group.

The print maps (``thematic_overlay``) and these tiles must show the same thing, so the class edges, the colours and
the inside-the-forest mask come from the same places: ``params.severity_breaks`` + ``classify_severity`` +
``sp.sample_ramp(spec.palette)`` + the grid's ``cf_mask``.

Rules this module keeps:

* **Cache only.** A tile request NEVER computes a hazard grid (a computation takes seconds to minutes and tiles arrive in
  bursts). No cached GeoTIFF for the CURRENT parameters, or one that no longer matches the grid → ``None`` and the
  caller says "not computed yet".
* **Pixels are mapped by hand** (tile pixel → lon/lat → raster cell). This machine's PROJ is broken, so no
  ``rasterio.warp`` / reprojection; the grid is axis-aligned EPSG:4326, which makes the arithmetic exact.
* **Every part of the forest** is shown: the mask is the grid's ``cf_mask``, not one polygon.
"""
from __future__ import annotations

import io
import logging
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

import numpy as np

logger = logging.getLogger(__name__)

TILE_SIZE = 256
# the print map draws its surface at alpha 0.82
DEFAULT_ALPHA = 209
SOIL_SPEC_KEY = "soil__annual_loss"

LAYER_KEYS = ("soil", "lsi", "fs", "prone")
AREAS = ("forest", "user_group")

# The RUSLE factor bands and the ten landslide factor ratings shown on the original tab (read from the same cached
# GeoTIFFs, classed in five quantile bands exactly as the print maps do).
SOIL_FACTORS = {  # key -> (soil band index, print ramp, spec key)
    "f_soil_r": (2, "blues", "soil__factor_r"),
    "f_soil_k": (3, "oranges", "soil__factor_k"),
    "f_soil_ls": (4, "purples", "soil__factor_ls"),
    "f_soil_c": (5, "greens", "soil__factor_c"),
}
LSI_FACTOR_NAMES = (
    "slope", "lithology", "curvature_twi", "dist_drainage", "dist_road",
    "landcover", "landcover_change", "aspect", "rainfall", "soil_texture",
)
LSI_FACTORS = {f"f_lsi_{n}": (3 + i, f"hazard__lsi_factor_{n}") for i, n in enumerate(LSI_FACTOR_NAMES)}
FACTOR_KEYS = tuple(SOIL_FACTORS) + tuple(LSI_FACTORS)
TILE_KEYS = LAYER_KEYS + FACTOR_KEYS  # everything the tile / legend routes serve


class NoUserGroup(Exception):
    """The user-group view was asked for but this forest has no user-group extent."""


def _inside_mask(grid: Any, area: str) -> np.ndarray:
    """Which grid cells the view shows: the forest, or the user group (the print maps' ``__user_group`` variant)."""
    if area == "user_group":
        if getattr(grid, "ug_mask", None) is None or not np.asarray(grid.ug_mask).any():
            raise NoUserGroup()
        return np.asarray(grid.ug_mask, dtype=bool)
    return np.asarray(grid.cf_mask, dtype=bool)

LSI_SPEC_KEY = "hazard__landslide_susceptibility"
FS_SPEC_KEY = "hazard__factor_of_safety"
PRONE_SPEC_KEY = "hazard__landslide_prone_area"


@dataclass
class Surface:
    """One classed hazard surface, ready to be sliced into tiles."""

    key: str
    cls: np.ndarray  # (H, W) int16 class index, -1 = no data / outside the forest
    bounds: tuple[float, float, float, float]  # minx, miny, maxx, maxy (EPSG:4326)
    colours: list[str]  # '#rrggbb' per class
    breaks: list[float]
    labels_ne: list[str]
    labels_en: list[str]
    ha_by_class: list[float]
    params_hash: str
    cell_m: float
    relative: bool = False  # True when classes are relative to this forest (landslide quantiles)
    area: str = "forest"
    values: Optional[np.ndarray] = field(default=None, repr=False)  # the raw numbers the classes came from
    cell_area_ha: Optional[np.ndarray] = field(default=None, repr=False)
    colour_sig: str = ""  # digest of the user's own colours ("" = system colours): part of every cache key
    _lut: Optional[np.ndarray] = field(default=None, repr=False)

    @property
    def width(self) -> int:
        return int(self.cls.shape[1])

    @property
    def height(self) -> int:
        return int(self.cls.shape[0])


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def surface_from_array(
    key: str,
    values: np.ndarray,
    *,
    bounds: tuple[float, float, float, float],
    inside: np.ndarray,
    cell_area_ha: np.ndarray,
    breaks: list[float],
    colours: list[str],
    labels_ne: list[str],
    labels_en: list[str],
    params_hash: str,
    cell_m: float,
    relative: bool = False,
) -> Surface:
    """Classify ``values`` with the print map's own function and mask them to the forest. Pure: no DB, no files."""
    from app.services.operational_plan import soil_erosion as se

    cls = se.classify_severity(values, breaks).astype("int16")
    cls[~inside] = -1
    ha = [float(cell_area_ha[cls == i].sum()) for i in range(len(colours))]
    return Surface(
        key=key, cls=cls, bounds=bounds, colours=list(colours), breaks=list(breaks), labels_ne=list(labels_ne),
        labels_en=list(labels_en), ha_by_class=ha, params_hash=params_hash, cell_m=cell_m, relative=relative,
        values=np.asarray(values, dtype="float64"), cell_area_ha=np.asarray(cell_area_ha, dtype="float64"),
    )


# ── loading (cache only) ──────────────────────────────────────────────────────────────────────────────────────────
_MEMO: "OrderedDict[tuple, Surface]" = OrderedDict()
_MEMO_MAX = 8
_MEMO_LOCK = threading.Lock()


def _memo_get(k: tuple) -> Optional[Surface]:
    with _MEMO_LOCK:
        s = _MEMO.get(k)
        if s is not None:
            _MEMO.move_to_end(k)
        return s


def _memo_put(k: tuple, s: Surface) -> None:
    with _MEMO_LOCK:
        _MEMO[k] = s
        _MEMO.move_to_end(k)
        while len(_MEMO) > _MEMO_MAX:
            _MEMO.popitem(last=False)


def clear_memo() -> None:
    with _MEMO_LOCK:
        _MEMO.clear()


def _own_colours(db: Any, calculation_id: UUID, key: str) -> dict[str, str]:
    from app.services.operational_plan import user_map_colours as ucm

    return ucm.hazard_overrides(db, calculation_id, key)


def _finish(surface: Surface, ovr: dict[str, str]) -> Surface:
    """Lay the user's own colours over the surface's default ones (same rule as the print maps)."""
    from app.services.operational_plan import user_map_colours as ucm

    surface.colours = ucm.apply(surface.colours, ovr)
    surface.colour_sig = ucm.signature(ovr)
    return surface


def _load_soil(db: Any, calculation_id: UUID, area: str = "forest") -> Optional[Surface]:
    from app.core import semantic_palettes as sp
    from app.services.operational_plan import soil_erosion as se
    from app.services.operational_plan.soil_erosion_config import SEVERITY_LABELS_EN, SEVERITY_LABELS_NE
    from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS

    params = se.resolve_params(db, calculation_id)
    path = se._cache_path(calculation_id, params)  # noqa: SLF001 -- the one place that knows the cache name
    if not path.exists():
        return None
    ovr = _own_colours(db, calculation_id, "soil")
    memo_key = ("soil", area, str(calculation_id), str(path), path.stat().st_mtime_ns, tuple(sorted(ovr.items())))
    hit = _memo_get(memo_key)
    if hit is not None:
        return hit

    grid = se.build_grid(db, calculation_id)
    if not se.cache_matches_grid(path, grid):
        return None  # a file for another grid (user group changed): never draw it on this forest
    import rasterio

    with rasterio.open(path) as ds:
        a = ds.read(1).astype("float64")
    spec = BUILTIN_THEMEMAP_SPECS[SOIL_SPEC_KEY]
    breaks = [float(b) for b in params.severity_breaks]
    surface = surface_from_array(
        "soil", a,
        bounds=tuple(grid.bounds), inside=_inside_mask(grid, area), cell_area_ha=grid.cell_area_ha,
        breaks=breaks, colours=sp.sample_ramp(spec.palette or "reds", len(breaks) + 1),
        labels_ne=list(SEVERITY_LABELS_NE), labels_en=list(SEVERITY_LABELS_EN),
        params_hash=se.params_hash(params), cell_m=float(grid.dx_m),
    )
    surface.area = area
    _finish(surface, ovr)
    _memo_put(memo_key, surface)
    return surface


def _load_landslide_or_fs(db: Any, calculation_id: UUID, key: str, area: str = "forest") -> Optional[Surface]:
    """``lsi`` / ``prone`` (both from the LSI GeoTIFF) and ``fs``. Same classes and colours as ``_compose_hazard_grid``."""
    from app.core import semantic_palettes as sp
    from app.services.operational_plan import hazard_vuln_config as hc
    from app.services.operational_plan import landslide_susceptibility as lsm
    from app.services.operational_plan import slope_stability as fsm
    from app.services.operational_plan import soil_erosion as se
    from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS as SPECS

    params = hc.resolve_params(db, calculation_id)
    path = (fsm._cache_path if key == "fs" else lsm._cache_path)(calculation_id, params)  # noqa: SLF001
    if not path.exists():
        return None
    ovr = _own_colours(db, calculation_id, key)
    memo_key = (key, area, str(calculation_id), str(path), path.stat().st_mtime_ns, tuple(sorted(ovr.items())))
    hit = _memo_get(memo_key)
    if hit is not None:
        return hit
    grid = se.build_grid(db, calculation_id)
    if not se.cache_matches_grid(path, grid):
        return None
    import rasterio

    with rasterio.open(path) as ds:
        b1 = ds.read(1).astype("float64")
        b2 = ds.read(2).astype("float64") if ds.count >= 2 else None
    inside = _inside_mask(grid, area)
    common = dict(
        bounds=tuple(grid.bounds), inside=inside, cell_area_ha=grid.cell_area_ha,
        params_hash=hc.params_hash(params), cell_m=float(grid.dx_m),
    )
    lp = params.landslide
    relative = lp.class_method != "fixed"

    if key == "fs":
        spec = SPECS[FS_SPEC_KEY]
        breaks = [float(v) for v in params.factor_of_safety.fs_class_breaks]
        colours = sp.sample_ramp(spec.palette or "spectral", len(breaks) + 1)
        from app.services.operational_plan.thematic_overlay import _FS_COLOURS

        if len(colours) == len(_FS_COLOURS):
            colours = list(_FS_COLOURS)  # unstable / marginal must stand out (as on the print map)
        surface = surface_from_array(
            "fs", b1, breaks=breaks, colours=colours, labels_ne=list(hc.FS_CLASS_LABELS_NE),
            labels_en=list(hc.FS_CLASS_LABELS_EN), **common,
        )
    else:
        if b2 is None:
            return None
        classes = np.where(np.isfinite(b2) & (b2 >= 0), b2, np.nan)  # -1 = no data, as in LSIResult
        if key == "lsi":
            spec = SPECS[LSI_SPEC_KEY]
            n_cls = len(hc.LSI_CLASS_LABELS_NE)
            breaks = [i + 0.5 for i in range(n_cls - 1)]
            labels_ne, labels_en = list(hc.LSI_CLASS_LABELS_NE), list(hc.LSI_CLASS_LABELS_EN)
            if relative:  # each class holds ~the same area: say which score range it covers in THIS forest
                for i in range(n_cls):
                    sel = (classes == i) & np.isfinite(b1) & inside
                    if sel.any():
                        rng = f" (LSI {b1[sel].min():.1f}–{b1[sel].max():.1f})"
                        labels_ne[i] += rng
                        labels_en[i] += rng
            else:
                e = [0.0, *[float(v) for v in lp.class_breaks_fixed]]
                for i in range(n_cls):
                    rng = f" ({e[i]:g}–{e[i + 1]:g})" if i + 1 < len(e) else f" (≥{e[i]:g})"
                    labels_ne[i] += rng
                    labels_en[i] += rng
            colours = sp.sample_ramp(spec.palette or "spectral_r", len(breaks) + 1)
            surface = surface_from_array(
                "lsi", classes, breaks=breaks, colours=colours, labels_ne=labels_ne, labels_en=labels_en,
                relative=relative, **common,
            )
        else:  # prone: the High+ classes
            spec = SPECS[PRONE_SPEC_KEY]
            arr = np.where(classes >= (lp.prone_class_min - 1), 1.0, 0.0)
            arr = np.where(np.isfinite(classes), arr, np.nan)
            colours = sp.sample_ramp(spec.palette or "reds", 2)
            surface = surface_from_array(
                "prone", arr, breaks=[0.5], colours=colours,
                labels_ne=["कम सापेक्ष संवेदनशीलता", "सापेक्ष रूपमा उच्च संवेदनशील"],
                labels_en=["Lower relative susceptibility", "Relatively high susceptibility"],
                relative=relative, **common,
            )
    surface.area = area
    _finish(surface, ovr)
    _memo_put(memo_key, surface)
    return surface


def _load_factor(db: Any, calculation_id: UUID, key: str, area: str) -> Optional[Surface]:
    """One factor band, five quantile classes of the band itself (``_quantile_breaks``), as on the print map."""
    from app.core import semantic_palettes as sp
    from app.services.operational_plan import hazard_vuln_config as hc
    from app.services.operational_plan import landslide_susceptibility as lsm
    from app.services.operational_plan import soil_erosion as se
    from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS as SPECS
    from app.services.operational_plan.thematic_overlay import _quantile_breaks

    if key in SOIL_FACTORS:
        band, ramp, spec_key = SOIL_FACTORS[key]
        params = se.resolve_params(db, calculation_id)
        path = se._cache_path(calculation_id, params)  # noqa: SLF001
        ph = se.params_hash(params)
    else:
        band, spec_key = LSI_FACTORS[key]
        ramp = SPECS[spec_key].palette or "oranges"
        params = hc.resolve_params(db, calculation_id)
        path = lsm._cache_path(calculation_id, params)  # noqa: SLF001
        ph = hc.params_hash(params)
    if not path.exists():
        return None
    ovr = _own_colours(db, calculation_id, key)
    memo_key = (key, area, str(calculation_id), str(path), path.stat().st_mtime_ns, tuple(sorted(ovr.items())))
    hit = _memo_get(memo_key)
    if hit is not None:
        return hit
    grid = se.build_grid(db, calculation_id)
    if not se.cache_matches_grid(path, grid):
        return None
    import rasterio

    with rasterio.open(path) as ds:
        if ds.count < band:
            return None
        arr = ds.read(band).astype("float64")
    breaks = _quantile_breaks(arr, 5) if np.isfinite(arr).any() else [0.0]
    surface = surface_from_array(
        key, arr, bounds=tuple(grid.bounds), inside=_inside_mask(grid, area), cell_area_ha=grid.cell_area_ha,
        breaks=breaks, colours=sp.sample_ramp(ramp, len(breaks) + 1), labels_ne=[], labels_en=[],
        params_hash=ph, cell_m=float(grid.dx_m),
    )
    surface.area = area
    _finish(surface, ovr)
    _memo_put(memo_key, surface)
    return surface


def load_surface(db: Any, calculation_id: UUID, key: str, area: str = "forest") -> Optional[Surface]:
    """The cached, classed surface for ``key``, or ``None`` when it has not been computed (or its cache is stale)."""
    if area not in AREAS:
        raise ValueError(f"unknown area: {area}")
    if key == "soil":
        return _load_soil(db, calculation_id, area)
    if key in ("lsi", "fs", "prone"):
        return _load_landslide_or_fs(db, calculation_id, key, area)
    if key in FACTOR_KEYS:
        return _load_factor(db, calculation_id, key, area)
    raise ValueError(f"unknown hazard layer: {key}")


# ── tiles ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _png(rgba: np.ndarray) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=False)
    return buf.getvalue()


_EMPTY_TILE: Optional[bytes] = None


def empty_tile() -> bytes:
    global _EMPTY_TILE
    if _EMPTY_TILE is None:
        _EMPTY_TILE = _png(np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8))
    return _EMPTY_TILE


def _lut(surface: Surface, alpha: int) -> np.ndarray:
    return np.array([(*_hex_rgb(c), alpha) for c in surface.colours], dtype=np.uint8)


def render_tile(surface: Surface, z: int, x: int, y: int, alpha: int = DEFAULT_ALPHA) -> bytes:
    """One 256×256 PNG; transparent where the surface has no cell (outside the forest or no data)."""
    n = 2.0 ** z
    minx, miny, maxx, maxy = surface.bounds
    # tile extent in lon/lat — skip the work when it cannot touch the surface
    t_lon0, t_lon1 = x / n * 360.0 - 180.0, (x + 1) / n * 360.0 - 180.0
    t_lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    t_lat0 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    if t_lon1 < minx or t_lon0 > maxx or t_lat1 < miny or t_lat0 > maxy:
        return empty_tile()

    centre = (np.arange(TILE_SIZE) + 0.5) / TILE_SIZE
    lon = (x + centre) / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * (y + centre) / n))))
    col = np.floor((lon - minx) / (maxx - minx) * surface.width).astype(np.int64)
    row = np.floor((maxy - lat) / (maxy - miny) * surface.height).astype(np.int64)
    ok_c = (col >= 0) & (col < surface.width)
    ok_r = (row >= 0) & (row < surface.height)
    if not ok_c.any() or not ok_r.any():
        return empty_tile()
    cls = surface.cls[np.clip(row, 0, surface.height - 1)[:, None], np.clip(col, 0, surface.width - 1)[None, :]]
    cls = np.where(ok_r[:, None] & ok_c[None, :], cls, -1)
    sel = cls >= 0
    if not sel.any():
        return empty_tile()
    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    rgba[sel] = _lut(surface, alpha)[cls[sel]]
    return _png(rgba)


# ── legend ────────────────────────────────────────────────────────────────────────────────────────────────────────
def legend(surface: Surface) -> dict[str, Any]:
    """The classes this forest actually has, with area and share — the workspace legend is dynamic."""
    total = sum(surface.ha_by_class) or 0.0
    if total <= 0:  # cached but empty (e.g. the factor of safety is switched off): not "not computed"
        return {"state": "no_data", "key": surface.key}
    edges = [0.0, *surface.breaks]
    rows = []
    for i, ha in enumerate(surface.ha_by_class):
        if ha <= 0:
            continue
        hi = surface.breaks[i] if i < len(surface.breaks) else None
        rows.append({
            "index": i,
            "color": surface.colours[i],
            "label_ne": surface.labels_ne[i] if i < len(surface.labels_ne) else "",
            "label_en": surface.labels_en[i] if i < len(surface.labels_en) else "",
            "from": edges[i],
            "to": hi,
            "area_ha": round(ha, 2),
            "share_pct": round(100.0 * ha / total, 1) if total else 0.0,
        })
    return {
        "state": "ready",
        "key": surface.key,
        "area": surface.area,
        "relative": surface.relative,
        "params_hash": surface.params_hash,
        "custom_colours": bool(surface.colour_sig),
        "cell_m": round(surface.cell_m, 1),
        "total_ha": round(total, 2),
        "classes": rows,
    }


# ── per-unit summaries (the workspace's labels and attribute-table columns) ───────────────────────────────────────────
def _unit_mask(geom: Any, surface: Surface) -> Optional[np.ndarray]:
    """Cells of the surface grid whose centre lies inside ``geom`` (every part of it)."""
    from rasterio.features import geometry_mask
    from rasterio.transform import from_bounds
    from shapely.geometry import mapping

    if geom is None or geom.is_empty:
        return None
    minx, miny, maxx, maxy = surface.bounds
    transform = from_bounds(minx, miny, maxx, maxy, surface.width, surface.height)
    return geometry_mask([mapping(geom)], (surface.height, surface.width), transform, invert=True, all_touched=False)


def unit_summary(surface: Surface, units: list[dict]) -> dict[str, dict]:
    """``{unit name: {...}}`` — what each hazard map says about a block / compartment, from the CACHED surface:

    * ``soil``  → ``mean`` (t/ha/yr, area-weighted) and ``severe_pct``
    * ``lsi``   → ``dominant`` (class index + labels) and ``high_pct`` (High and above, relative to the forest)
    * ``fs``    → ``unstable_pct`` and ``unsafe_pct`` (unstable + marginal; what the print map labels)
    * ``prone`` → ``high_pct``

    A unit with no valid cell is left out. Shares are by AREA within the unit's valid cells."""
    out: dict[str, dict] = {}
    for u in units:
        m = _unit_mask(u.get("geometry"), surface)
        if m is None:
            continue
        sel = m & (surface.cls >= 0)
        if not sel.any():
            continue
        area = surface.cell_area_ha[sel] if surface.cell_area_ha is not None else np.ones(int(sel.sum()))
        total = float(area.sum()) or 1.0
        cls = surface.cls[sel]

        def share(mask: np.ndarray) -> float:
            return round(100.0 * float(area[mask].sum()) / total, 1)

        row: dict[str, Any] = {"area_ha": round(total, 2)}
        if surface.key == "soil":
            v = surface.values[sel]
            ok = np.isfinite(v)
            row["mean"] = round(float(np.average(v[ok], weights=area[ok])), 1) if ok.any() else None
            row["severe_pct"] = share(cls >= 4)  # Severe and Very severe
        elif surface.key == "lsi":
            by = [float(area[cls == i].sum()) for i in range(len(surface.colours))]
            dom = int(np.argmax(by))
            row["dominant"] = {
                "index": dom,
                "label_en": surface.labels_en[dom].split(" (")[0],
                "label_ne": surface.labels_ne[dom].split(" (")[0],
            }
            row["high_pct"] = share(cls >= 3)
        elif surface.key == "fs":
            row["unstable_pct"] = share(cls == 0)
            row["unsafe_pct"] = share(cls <= 1)
        elif surface.key == "prone":
            row["high_pct"] = share(cls == 1)
        out[u["name"]] = row
    return out


def all_unit_summaries(db: Any, calculation_id: UUID, units: list[dict]) -> dict[str, Any]:
    """Every cached layer's per-unit summary in one response: ``{"layers": {key: {unit: {...}}}, "missing": [keys]}``.
    Cache only, like the tiles; a layer that is not computed is listed under ``missing``."""
    layers: dict[str, dict] = {}
    missing: list[str] = []
    for key in LAYER_KEYS:
        surface = load_surface(db, calculation_id, key)
        if surface is None:
            missing.append(key)
            continue
        layers[key] = unit_summary(surface, units)
    return {"layers": layers, "missing": missing}


def units_for_summary(db: Any, calculation_id: UUID) -> list[dict]:
    """Every unit the workspace labels: the LEAF units plus the TOP-LEVEL ones, so a block that is divided into
    sub-blocks still gets its own summary (a leaf-only list left it with just its name)."""
    from app.services.forest_units import queries as q

    seen: dict[str, dict] = {}
    for view in (q.View.LEAF, q.View.TOP_LEVEL):
        for u in q.units(db, calculation_id, view):
            if str(u.id) in seen:
                continue
            try:
                geom = u.shape
            except Exception as e:  # noqa: BLE001 -- one bad geometry must not drop the other units
                logger.warning("hazard summary: unit %s has no usable shape: %s", u.name, e)
                continue
            seen[str(u.id)] = {"id": str(u.id), "name": u.name or "", "geometry": geom}
    return list(seen.values())
