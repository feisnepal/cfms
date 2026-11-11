"""Vectorise ``rasters.slope_regulation`` into a digitizing aid for `protected`
sub-areas (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P11, follow-on).

Nothing here is authoritative — the user's hand-edited polygon is. This module
only turns the raw 4-value slope raster (< 19° / 19–31° / 31–45° / > 45°, the
guideline's §15.2 zonation) into:

* :func:`slope_class_polygons` — a GeoJSON FeatureCollection (one feature per
  band), simplified and sliver-cleaned, for a read-only map overlay. Cached in
  ``result_data['sfm']['slope_class_polygons']`` (dropped with the rest of
  ``sfm`` by the P2 invalidation hooks).
* :func:`draft_protection_polygon` — the union of the steep bands (≥ ``min_band``)
  clipped to the forest, as an **editable draft** the user trims against the
  §23.2 felling-plot exclusion checklist and then saves through the normal
  sub-area path.
* :func:`slope_profile` — ``{dominant_band, area_pct_by_band}`` for any geometry
  (thin wrapper over ``zone_classifier.dominant_slope_band``).

Every DB read is SAVEPOINT-guarded — a missing / non-covering
``rasters.slope_regulation`` degrades to an empty result, never an exception.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any, Optional

from shapely.geometry import shape
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.services.geom_generalize import meters_to_deg
from app.services.raster_class_vectorize import SLOPE_CLASSES, class_pieces
from app.services.sustainable_fm.sfm_config import SfmParams
from app.services.sustainable_fm.zone_classifier import (
    _ALLOWED_SLOPE_TABLES,
    dominant_slope_band,
)

logger = logging.getLogger(__name__)

BAND_LABELS: dict[int, tuple[str, str]] = {
    1: ("< १९°", "< 19°"),
    2: ("१९–३१°", "19–31°"),
    3: ("३१–४५°", "31–45°"),
    4: ("> ४५°", "> 45°"),
}
_SIMPLIFY_DEG = 0.00013  # ≈ half a 30 m pixel at Nepal latitudes
# Boundary-smoothing radius (see app/services/geom_generalize.py for the
# "buffer round-trip" technique this feeds): ~0.75x the 30 m
# slope_regulation/aspect pixel. Large enough to round the raster staircase,
# small enough that a real slope band running along a ridge line survives.
_GEN_RADIUS_DEG = meters_to_deg(22.0)


def _slope_table(params: SfmParams) -> str:
    t = params.slope_regulation_table
    return t if t in _ALLOWED_SLOPE_TABLES else "rasters.slope_regulation"


def _boundary_wkt(calc: Calculation, db: Session) -> Optional[str]:
    return db.execute(
        text("SELECT ST_AsText(boundary_geom) FROM calculations WHERE id = :cid"),
        {"cid": str(calc.id)},
    ).scalar()


def slope_class_polygons(
    calc: Calculation, db: Session, params: SfmParams
) -> dict[str, Any]:
    """GeoJSON FeatureCollection — one simplified, sliver-cleaned polygon per
    slope band present inside the forest boundary. Empty ``features`` when the
    raster is absent or does not cover the forest."""
    empty = {"type": "FeatureCollection", "features": []}
    bwkt = _boundary_wkt(calc, db)
    if not bwkt:
        return empty
    table = _slope_table(params)
    sliver = float(params.slope_vector_sliver_m2 or 1000.0)

    # per-band: dump pixel polygons → union (merges every same-band touching
    # piece) → dump back → drop the pieces still < sliver_m2 (genuinely isolated
    # within their band) → union the survivors → simplify.
    q = text(
        f"""
        WITH b AS (SELECT ST_GeomFromText(:wkt, 4326) AS geom),
        px AS (
            SELECT (ST_DumpAsPolygons(ST_Clip(r.rast, b.geom), 1)).*
            FROM {table} r, b
            WHERE ST_Intersects(r.rast, b.geom)
        ),
        merged AS (
            SELECT val::int AS band, ST_Union(geom) AS geom
            FROM px WHERE val BETWEEN 1 AND 4 GROUP BY val
        ),
        parts AS (
            SELECT band, (ST_Dump(geom)).geom AS geom FROM merged
        ),
        kept AS (
            SELECT band, geom FROM parts
            WHERE ST_Area(geom::geography) >= :sliver
        )
        SELECT band,
               -- Re-clip to the true forest boundary AFTER smoothing AND
               -- simplify, as the ABSOLUTE LAST step: ST_Intersection is the
               -- only one of these three operations that is guaranteed never
               -- to produce area outside its second argument.
               -- ST_SimplifyPreserveTopology does NOT give that guarantee —
               -- it approximates the boundary curve, which can bulge a few
               -- metres past the true edge — so simplifying AFTER the
               -- boundary clip (the bug this replaces) could silently push a
               -- piece back outside the forest boundary by up to `:tol`.
               ST_AsGeoJSON(
                 ST_Intersection(
                   ST_SimplifyPreserveTopology(
                     ST_Buffer(ST_Buffer(ST_Union(geom), :smooth, 'join=round'),
                               -:smooth, 'join=round'),
                     :tol
                   ),
                   (SELECT geom FROM b)
                 )
               ) AS gj,
               SUM(ST_Area(geom::geography)) / 10000.0 AS area_ha
        FROM kept GROUP BY band ORDER BY band
        """  # noqa: S608 -- table constrained to _ALLOWED_SLOPE_TABLES
    )
    try:
        with db.begin_nested():
            rows = db.execute(
                q,
                {
                    "wkt": bwkt,
                    "sliver": sliver,
                    "tol": _SIMPLIFY_DEG,
                    "smooth": _GEN_RADIUS_DEG,
                },
            ).fetchall()
    except Exception:  # noqa: BLE001 -- raster optional / no coverage → empty
        logger.debug("slope_class_polygons: %s unavailable", table, exc_info=True)
        return empty

    feats = []
    for r in rows:
        if not r.gj:
            continue
        ne, en = BAND_LABELS.get(int(r.band), (str(r.band), str(r.band)))
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "band": int(r.band),
                    "label_ne": ne,
                    "label_en": en,
                    "area_ha": round(float(r.area_ha or 0.0), 3),
                },
                "geometry": json.loads(r.gj),
            }
        )
    return {"type": "FeatureCollection", "features": feats}


def slope_class_pieces(
    calc: Calculation, db: Session, params: SfmParams, scope_wkt: Optional[str] = None
) -> list[tuple[int, Any]]:
    """One ``(band, shapely_geom)`` pair per **contiguous** same-band slope
    region inside the forest boundary — carve candidates for automatic
    compartment generation along slope-class breaks (Auto-Block, slope
    source). Unlike :func:`slope_class_polygons`, which unions every
    same-band piece into one feature for a read-only overlay, a carve needs
    each contiguous region as its own candidate — the same shape individual
    MMU tiles are for the river/ridge source in ``auto_block_service.py``.

    Empty list when the raster is absent or does not cover the forest (same
    SAVEPOINT-guarded degrade as every other function in this module).

    RS-1.7: the pipeline is delegated to
    ``app/services/raster_class_vectorize.py::class_pieces`` so slope, aspect,
    NASA, NDVI, ESA and DEM share one implementation. ``SLOPE_CLASSES`` carries
    the slope-specific facts (table, bands 1-4, 30 m pixel) and the values were
    verified identical before delegating. ``slope_class_polygons`` keeps its own
    query on purpose: it unions each band into ONE feature and smooths that
    union, which is a different output shape from a list of carve candidates."""
    return class_pieces(
        calc,
        db,
        replace(SLOPE_CLASSES, table=_slope_table(params)),
        sliver_m2=params.slope_vector_sliver_m2,
        scope_wkt=scope_wkt,
    )


def draft_protection_polygon(
    calc: Calculation, db: Session, params: SfmParams, min_band: int
) -> Optional[dict[str, Any]]:
    """Union of the slope bands ≥ ``min_band`` inside the forest, simplified.
    A **draft** GeoJSON geometry (not persisted); ``None`` when nothing qualifies."""
    min_band = max(1, min(4, int(min_band)))
    bwkt = _boundary_wkt(calc, db)
    if not bwkt:
        return None
    table = _slope_table(params)
    sliver = float(params.slope_vector_sliver_m2 or 1000.0)
    q = text(
        f"""
        WITH b AS (SELECT ST_GeomFromText(:wkt, 4326) AS geom),
        px AS (
            SELECT (ST_DumpAsPolygons(ST_Clip(r.rast, b.geom), 1)).*
            FROM {table} r, b
            WHERE ST_Intersects(r.rast, b.geom)
        ),
        steep AS (
            SELECT (ST_Dump(ST_Union(px.geom))).geom AS geom
            FROM px WHERE px.val BETWEEN :mb AND 4
        ),
        kept AS (
            SELECT steep.geom AS geom FROM steep
            WHERE ST_Area(steep.geom::geography) >= :sliver
        ),
        u AS (SELECT ST_Union(kept.geom) AS geom FROM kept)
        -- Re-clip to the boundary as the ABSOLUTE LAST step, AFTER simplify
        -- (see the fuller comment in slope_class_polygons — simplify does
        -- not guarantee containment).
        SELECT ST_AsGeoJSON(
                 ST_Intersection(
                   ST_SimplifyPreserveTopology(
                     ST_Buffer(ST_Buffer(u.geom, :smooth, 'join=round'),
                               -:smooth, 'join=round'),
                     :tol
                   ),
                   b.geom
                 )
               ) AS gj
        FROM u, b
        WHERE u.geom IS NOT NULL
        """  # noqa: S608 -- table constrained to _ALLOWED_SLOPE_TABLES
    )
    try:
        with db.begin_nested():
            row = db.execute(
                q,
                {
                    "wkt": bwkt,
                    "mb": min_band,
                    "sliver": sliver,
                    "tol": _SIMPLIFY_DEG,
                    "smooth": _GEN_RADIUS_DEG,
                },
            ).first()
    except Exception:  # noqa: BLE001 -- raster optional / no coverage → None
        logger.debug("draft_protection_polygon: %s unavailable", table, exc_info=True)
        return None
    if not row or not row.gj:
        return None
    geom = json.loads(row.gj)
    if not geom.get("coordinates"):
        return None
    return geom


def slope_profile(geom_wkt: str, db: Session, params: SfmParams) -> dict[str, Any]:
    """``{dominant_band, area_pct_by_band}`` for one geometry. Reuses
    ``zone_classifier.dominant_slope_band`` (same SAVEPOINT-guarded read)."""
    if not geom_wkt:
        return {"dominant_band": None, "area_pct_by_band": {}}
    band, pct = dominant_slope_band(geom_wkt, db, params)
    return {
        "dominant_band": band,
        "area_pct_by_band": {str(k): v for k, v in pct.items()},
    }


__all__ = [
    "BAND_LABELS",
    "slope_class_polygons",
    "slope_class_pieces",
    "draft_protection_polygon",
    "slope_profile",
]
