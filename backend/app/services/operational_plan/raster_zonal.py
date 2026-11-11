"""Per-unit zonal statistics over the ``rasters.*`` PostGIS tables (S9 / P6z).

``thematic_overlay._render`` calls :func:`per_unit_zonal` when a spec's
``source == "raster_zonal"``; it returns ``{unit_name: {<measure keys>}}``
shaped for ``_numeric_series`` / ``_categorical_colours`` / ``_composition``.

Every raster in this project is EPSG:4326 and so is ``forest_blocks.geometry``
(verified), so the clip is a plain ``ST_Clip(rast, :wkt::geometry)`` with no
reprojection. Each unit's queries run inside a ``SAVEPOINT`` so a raster that
does not cover a unit cannot poison the render transaction.

No migration. Read-only. The reference-page preview uses synthetic values from
``_thememap_fixture`` — this module is only reached for a real forest.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.forest_types import (
    get_forest_health,
    get_forest_type_class,
    get_nasa_forest_quality,
)

logger = logging.getLogger(__name__)

# logical name -> (schema.table, valid value range). The DEM/canopy/AGB NoData
# sentinels are NOT registered in PostGIS band metadata, so ``true`` on
# ST_SummaryStats does not exclude them — we filter by a physical range instead.
_CONT: dict[str, tuple[str, tuple[float, float]]] = {
    "dem": ("rasters.dem", (-500.0, 9000.0)),
    "canopy": ("rasters.canopy_height5x15", (0.0, 80.0)),
    "agb": ("rasters.agb_2022_nepal", (0.0, 2000.0)),
}
# vector layer for the "accessibility" (distance-to-road) measure
_ROAD_TABLE = "infrastructure.road"
# logical name -> (schema.table, band) for categorical rasters (ST_ValueCount)
_CAT: dict[str, tuple[str, int]] = {
    # Owner decision 2026-09-29: rasters.slope_regulation is the authoritative
    # slope-class table. It is what core/constants.py documents the 1-4 classes
    # from, what TileService.RASTER_TABLES renders, and what
    # auto_block_service.vectorize_slope already reads — this registry was the
    # only place still on rasters.slope, so the OP map drew its slope
    # statistics from a different raster than the slope map beside it.
    "slope": ("rasters.slope_regulation", 1),
    "aspect": ("rasters.aspect", 1),
    "landcover": ("rasters.esa_world_cover", 1),
    # Owner decision 2026-09-29: labels come from core.forest_types, the same
    # vocabulary the tile renderer uses, so the OP map and the map cannot
    # disagree. The former local FOREST_TYPE_LABELS had 10 species names and
    # could not label 6 of the 12 codes this raster actually carries.
    "forest_type": ("rasters.forest_type", 1),
    # satellite forest-health class raster. This is an integer CLASS raster
    # (verified in the dev DB: values 0,1,2,3,4,5 — 0 = NoData), so it belongs
    # here, not in _CONT: averaging class codes 1..5 produces a number that
    # means nothing ("mean health 3.4" has no class). A unit is described by
    # its DOMINANT class plus the class shares, not by a mean.
    "forest_health": ("rasters.nepal_forest_health", 1),
    # NASA forest quality (verified: 0,1,2,3 — 0 = NoData). Was in NEITHER
    # _CONT nor _CAT, so it could not render on an OP thematic map at all.
    "nasa_quality": ("rasters.nasa_forest_2020", 1),
}

# rasters.slope categorical codes → CFMG class + a representative degree value
SLOPE_LABELS = {1: "gentle", 2: "moderate", 3: "steep", 4: "very_steep"}
SLOPE_LABELS_NE = {
    "gentle": "मन्द",
    "moderate": "मध्यम",
    "steep": "भिरालो",
    "very_steep": "अति भिरालो",
}
_SLOPE_DEG = {1: 5.0, 2: 15.0, 3: 25.0, 4: 35.0}
# oranges-ramp hexes — mirrors semantic_palettes.CATEGORICAL["slope_class"]
_SLOPE_HEX = {1: "#fdbe85", 2: "#fd8d3c", 3: "#e6550d", 4: "#a63603"}

# rasters.aspect categorical codes 1..8 → compass + math-convention arrow angle
COMPASS_8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
COMPASS_8_NE = {
    "N": "उत्तर",
    "NE": "उत्तरपूर्व",
    "E": "पूर्व",
    "SE": "दक्षिणपूर्व",
    "S": "दक्षिण",
    "SW": "दक्षिणपश्चिम",
    "W": "पश्चिम",
    "NW": "उत्तरपश्चिम",
}


def aspect_angle_deg(code: int) -> float:
    """Matplotlib-convention angle (0°=East, CCW) for aspect code 1..8 (1=N)."""
    return (90.0 - (int(code) - 1) * 45.0) % 360.0


# rasters.forest_type labels deliberately live in core.forest_types
# (FRTC_FOREST_TYPES), NOT here. This module used to keep its own
# FOREST_TYPE_LABELS dict of 10 species names, which was a third vocabulary
# alongside core.forest_types and the frontend legend — and it could not label
# 6 of the 12 codes the raster actually carries. Owner decision 2026-09-29.


# ── SQL helpers (one unit polygon at a time, guarded by a savepoint) ──────
def _summary_mean_minmax(db: Session, wkt: str, table: str, lo: float, hi: float):
    """(mean, min, max, count) over the unit for a continuous raster, keeping
    only pixels in the physical range ``[lo, hi]`` — the NoData sentinels of
    these rasters are not registered in PostGIS band metadata."""
    q = text(
        f"""
        SELECT
            SUM((pvc).value * (pvc).count) / NULLIF(SUM((pvc).count), 0) AS mean,
            MIN((pvc).value) AS lo, MAX((pvc).value) AS hi, SUM((pvc).count) AS n
        FROM (
            SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) AS pvc
            FROM {table}
            WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
        ) s
        WHERE (pvc).value IS NOT NULL AND (pvc).value BETWEEN :lo AND :hi
        """
    )
    row = db.execute(q, {"wkt": wkt, "lo": lo, "hi": hi}).first()
    if not row or row[3] in (None, 0):
        return None
    return float(row[0]), float(row[1]), float(row[2]), int(row[3])


def _canopy_summary_from_tif(wkt: str):
    """(mean, min, max, count) of tree height over the unit, read straight from
    the 5 m ``canopy_height5m.tif`` (uint8, metres, 0 = NoData).

    The PostGIS ``rasters.canopy_height*`` tables are obsolete — this TIF is the
    tree-height source. Returns ``None`` (caller falls back to PostGIS) if the
    file is missing / unreadable or the unit has no valid pixels.
    """
    try:
        import numpy as np
        import rasterio
        from rasterio.mask import mask as rio_mask
        from shapely import wkt as _swkt
        from shapely.geometry import mapping

        from app.services.analysis import CANOPY_TIF_PATH

        geom = mapping(_swkt.loads(wkt))
        with rasterio.open(CANOPY_TIF_PATH) as src:
            arr, _ = rio_mask(src, [geom], crop=True, filled=False)
        data = arr[0]
        valid = data.compressed() if hasattr(data, "compressed") else data.flatten()
        valid = valid[(valid > 0) & (valid <= 80)]
        if valid.size == 0:
            return None
        return (
            float(valid.mean()),
            float(valid.min()),
            float(valid.max()),
            int(valid.size),
        )
    except Exception:  # noqa: BLE001 -- fall back to the PostGIS table
        logger.debug("canopy TIF read failed", exc_info=True)
        return None


def _max_interior_road_distance_m(db: Session, wkt: str) -> "float | None":
    """Largest nearest-road distance (m) over 30 random interior points — a
    signal-bearing proxy for how far the worst-served part of the unit is from
    a road. Deterministic (fixed seed). KNN `<->` + the `&&` box use the GiST
    index on ``infrastructure.road``."""
    q = text(
        f"""
        WITH pts AS (
            SELECT (ST_Dump(
                ST_GeneratePoints(ST_GeomFromText(:wkt, 4326), 30, 42)
            )).geom AS g
        )
        SELECT max(d) FROM (
            SELECT (
                SELECT ST_Distance(pts.g::geography, r.geom::geography)
                FROM {_ROAD_TABLE} r
                WHERE ST_Expand(pts.g, 0.08) && r.geom
                ORDER BY r.geom <-> pts.g
                LIMIT 1
            ) AS d
            FROM pts
        ) x
        """  # noqa: S608 -- _ROAD_TABLE is a hardcoded identifier, not user input
    )
    row = db.execute(q, {"wkt": wkt}).first()
    return float(row[0]) if row and row[0] is not None else None


def hydro_lines_for_forest(db: Session, calculation_id) -> list:
    """Shapely geometries from ``river.river84`` that touch the forest, for the
    drainage / river-network map. Clipped to a small buffer of the boundary so
    a stub of each river shows past the edge for context."""
    try:
        from geoalchemy2.shape import to_shape

        q = text(
            """
            SELECT ST_AsBinary(
                ST_Intersection(r.shape, ST_Buffer(c.boundary_geom, 0.004))
            ) AS g,
            r."river name" AS nm
            FROM river.river84 r, public.calculations c
            WHERE c.id = :cid AND ST_Intersects(r.shape, c.boundary_geom)
            """
        )
        from shapely import wkb as _wkb

        out = []
        for gb, nm in db.execute(q, {"cid": str(calculation_id)}):
            if gb is None:
                continue
            try:
                g = _wkb.loads(bytes(gb))
                if g and not g.is_empty:
                    out.append((g, (nm or "").strip()))
            except Exception:  # noqa: BLE001
                continue
        return out
    except Exception:  # noqa: BLE001 -- no hydrology layer → an empty map
        logger.debug("river84 lookup failed", exc_info=True)
        return []


def has_road_layer(db: Session, boundary_wkt: str) -> bool:
    try:
        q = text(
            f"SELECT 1 FROM {_ROAD_TABLE} r "  # noqa: S608 -- constant identifier
            "WHERE ST_Expand(ST_GeomFromText(:wkt, 4326), 0.1) && r.geom LIMIT 1"
        )
        return db.execute(q, {"wkt": boundary_wkt}).first() is not None
    except Exception:  # noqa: BLE001
        return False


def has_hydro_layer(db: Session, boundary_wkt: str) -> bool:
    try:
        q = text(
            "SELECT 1 FROM river.river84 r "
            "WHERE ST_Intersects(r.shape, ST_GeomFromText(:wkt, 4326)) LIMIT 1"
        )
        return db.execute(q, {"wkt": boundary_wkt}).first() is not None
    except Exception:  # noqa: BLE001
        return False


def _value_counts(db: Session, wkt: str, table: str) -> dict[int, int]:
    """{raster_value: pixel_count} over the unit, aggregated across tiles."""
    q = text(
        f"""
        SELECT (pvc).value AS v, SUM((pvc).count) AS n
        FROM (
            SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) AS pvc
            FROM {table}
            WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
        ) s
        WHERE (pvc).value IS NOT NULL AND (pvc).value <> 0
        GROUP BY (pvc).value
        """
    )
    out: dict[int, int] = {}
    for v, n in db.execute(q, {"wkt": wkt}).fetchall():
        try:
            out[int(round(float(v)))] = int(n)
        except (TypeError, ValueError):
            continue
    return out


def _guarded(db: Session, fn, *a):
    """Run *fn* inside a SAVEPOINT; a raster/geometry error yields None."""
    try:
        with db.begin_nested():
            return fn(db, *a)
    except Exception:  # noqa: BLE001 -- a non-covering raster must not 500 the map
        logger.debug("zonal query failed", exc_info=True)
        return None


# ── per-measure record builders ─────────────────────────────────────────
def _pct(counts: dict) -> dict:
    tot = sum(counts.values()) or 1
    return {k: round(100.0 * n / tot, 2) for k, n in counts.items()}


def _dominant(counts: dict):
    return max(counts, key=counts.get) if counts else None


def _categorical_raster_rec(db: Session, wkt: str, key: str, getter, stem: str) -> dict:
    """Per-unit record for one categorical raster: dominant class + the class
    shares, keyed by the class's EN name.

    The shape is the one ``_categorical_colours`` / ``_composition`` already
    read for landcover: ``{<stem>_dominant: <EN name>}`` plus one
    ``<EN name>: pct`` per class (composition components) and a
    ``_<stem>_glyph`` list of ``(NP name, pct, hex)``.

    ``getter`` maps a raster code to a ``core.forest_types`` record, so labels
    and hexes come from the one vocabulatory SSOT rather than a local dict —
    that is what keeps a legend and a zonal record from drifting apart.
    """
    c = _guarded(db, _value_counts, wkt, _CAT[key][0]) or {}
    if not c:
        return {}
    pct = _pct(c)
    rec: dict = {f"{stem}_dominant": getter(_dominant(c)).name_en}
    for code, pctv in pct.items():
        rec[getter(code).name_en] = pctv
    rec[f"_{stem}_glyph"] = [
        (getter(code).name_np, pct[code], getter(code).color_hex)
        for code in sorted(c, key=c.get, reverse=True)
    ]
    return rec


def _rec_for_measure(db: Session, wkt: str, measure: str) -> dict:
    """Build the per-unit value record for one S9 measure. Keys match what
    ``_numeric_series`` / ``_categorical_colours`` / ``_composition`` read."""
    m = measure or ""

    if m in ("elevation_mean", "elevation_range"):
        tbl, (lo_r, hi_r) = _CONT["dem"]
        s = _guarded(db, _summary_mean_minmax, wkt, tbl, lo_r, hi_r)
        if not s:
            return {}
        mean, lo, hi, _ = s
        return {"elevation_mean": round(mean, 1), "elevation_range": round(hi - lo, 1)}

    if m == "canopy_mean":
        # Tree height comes from canopy_height5m.tif; the PostGIS
        # rasters.canopy_height* tables are obsolete. PostGIS is the fallback.
        s = _canopy_summary_from_tif(wkt)
        if not s:
            tbl, (lo_r, hi_r) = _CONT["canopy"]
            s = _guarded(db, _summary_mean_minmax, wkt, tbl, lo_r, hi_r)
        return {"canopy_mean": round(s[0], 2)} if s else {}

    if m == "biomass_mean":
        tbl, (lo_r, hi_r) = _CONT["agb"]
        s = _guarded(db, _summary_mean_minmax, wkt, tbl, lo_r, hi_r)
        return {"biomass_mean": round(s[0], 1)} if s else {}

    if m in ("slope_mean", "slope_dominant", "slope_classes"):
        c = _guarded(db, _value_counts, wkt, _CAT["slope"][0]) or {}
        c = {k: v for k, v in c.items() if 1 <= k <= 4}
        if not c:
            return {}
        tot = sum(c.values())
        pct = _pct(c)
        rec = {
            "slope_mean": round(sum(_SLOPE_DEG[k] * n for k, n in c.items()) / tot, 1),
            "slope_dominant": SLOPE_LABELS[_dominant(c)],
        }
        for k, pctv in pct.items():
            rec[SLOPE_LABELS[k]] = pctv  # composition components
        rec["_slope_glyph"] = [
            (SLOPE_LABELS_NE[SLOPE_LABELS[k]], pct.get(k, 0.0), _SLOPE_HEX[k])
            for k in (1, 2, 3, 4)
        ]
        return rec

    if m in ("landcover_dominant", "landcover_classes"):
        from app.core.forest_types import get_esa_land_cover

        c = _guarded(db, _value_counts, wkt, _CAT["landcover"][0]) or {}
        if not c:
            return {}
        pct = _pct(c)
        rec = {"landcover_dominant": get_esa_land_cover(_dominant(c)).name_en}
        for k, pctv in pct.items():
            rec[get_esa_land_cover(k).name_en] = pctv
        rec["_landcover_glyph"] = [
            (get_esa_land_cover(k).name_np, pct[k], get_esa_land_cover(k).color_hex)
            for k in sorted(c, key=c.get, reverse=True)
        ]
        return rec

    if m in ("forest_type_dominant", "forest_type_classes"):
        return _categorical_raster_rec(
            db, wkt, "forest_type", get_forest_type_class, "forest_type"
        )

    if m in ("forest_health_dominant", "forest_health_classes"):
        return _categorical_raster_rec(
            db, wkt, "forest_health", get_forest_health, "forest_health"
        )

    if m in ("nasa_quality_dominant", "nasa_quality_classes"):
        return _categorical_raster_rec(
            db, wkt, "nasa_quality", get_nasa_forest_quality, "nasa_quality"
        )

    if m == "accessibility":
        # per-unit access = how far the *remotest* interior point is from a road
        # (infrastructure.road). Min-distance-to-road is ~0 for every unit where
        # HOTOSM has dense coverage, so it carries no signal — sample 30 interior
        # points and take the largest nearest-road distance (metres).
        d = _guarded(db, _max_interior_road_distance_m, wkt)
        return {"accessibility": round(float(d), 0)} if d is not None else {}

    if m in ("aspect_dominant", "aspect_bins", "aspect_vector"):
        c = _guarded(db, _value_counts, wkt, _CAT["aspect"][0]) or {}
        c = {k: v for k, v in c.items() if 1 <= k <= 8}
        if not c:
            return {}
        dom = _dominant(c)
        _ASPECT_HEX = {
            "N": "#4575b4",
            "NE": "#74add1",
            "E": "#abd9e9",
            "SE": "#e0f3f8",
            "S": "#fee090",
            "SW": "#fdae61",
            "W": "#f46d43",
            "NW": "#d73027",
        }
        rec = {"aspect_dominant": COMPASS_8[dom - 1]}
        bins = {COMPASS_8[k - 1]: pctv for k, pctv in _pct(c).items()}
        rec["_aspect_bins"] = {d: bins.get(d, 0.0) for d in COMPASS_8}
        rec["_aspect_angle_deg"] = aspect_angle_deg(dom)
        rec["_aspect_glyph"] = [
            (COMPASS_8_NE[d], rec["_aspect_bins"][d], _ASPECT_HEX[d]) for d in COMPASS_8
        ]
        return rec

    return {}


# ── entry point ─────────────────────────────────────────────────────────
def per_unit_zonal(db: Session, units: list[dict], spec) -> dict[str, dict]:
    """``{unit_name: {measure_key: value, ...}}`` for an S9 raster-zonal spec.

    *units* is the list of ``{"name", "geometry" (shapely)}`` dicts already
    resolved by ``thematic_overlay._render``.
    """
    measure = getattr(spec, "measure", "") or ""
    out: dict[str, dict] = {}
    for u in units:
        geom = u.get("geometry")
        if geom is None or geom.is_empty:
            continue
        try:
            wkt = geom.wkt
        except Exception:  # noqa: BLE001
            continue
        out[u["name"]] = _rec_for_measure(db, wkt, measure)
    return out


def coverage_available(db: Session, boundary_wkt: str) -> bool:
    """True if the DEM raster covers the forest — the ``raster_zonal`` prereq."""
    try:
        q = text(
            "SELECT 1 FROM rasters.dem "
            "WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326)) LIMIT 1"
        )
        return db.execute(q, {"wkt": boundary_wkt}).first() is not None
    except Exception:  # noqa: BLE001
        return False


__all__ = [
    "per_unit_zonal",
    "coverage_available",
    "aspect_angle_deg",
    "SLOPE_LABELS",
    "COMPASS_8",
    "FOREST_TYPE_LABELS",
]
