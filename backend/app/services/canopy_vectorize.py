"""Vectorise `canopy_height5m.tif` into carve candidates for the Auto-Block
`canopy` source (SLOPE_COMPARTMENT_AND_STRATIFIED_SAMPLING_PLAN follow-on).

Unlike slope/aspect (already categorical in their source raster), the TIF
stores raw uint8 metres — this module bins them first, reusing the SAME
4-class breaks already established and shipped in
`analysis.py::_canopy_from_rasterio` ("CFMG forest structure classification
thresholds": 1 m = non-forest, 2-5 m = regeneration, 6-15 m = pole,
>15 m (<=50; values above are sensor noise) = tree) — one canonical canopy
vocabulary across the app, not a second competing scheme.

Source is a FLAT FILE (`CANOPY_TIF_PATH`, imported from `analysis.py` rather
than re-hardcoded here), not `rasters.canopy_height*` (obsolete: empty /
missing / stale — see the standing project memory on this). Vectorization
uses `rasterio.features.shapes`, the same technique already proven in
`operational_plan/landslide_susceptibility.py::_prone_polygon` — the Python
equivalent of PostGIS's `ST_DumpAsPolygons`, needed here because this source
never reaches the database.

Real coverage is patchy (a spaceborne product): every read degrades to an
empty list on a missing file, an unreadable file, or zero valid pixels in
the boundary — never raises.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from shapely.geometry import shape as shapely_shape
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.services.file_processor import calculate_polygon_area_utm
from app.services.geom_generalize import meters_to_deg

logger = logging.getLogger(__name__)

CANOPY_CLASS_LABELS: dict[int, str] = {
    0: "no-data",
    1: "non-forest",
    2: "regeneration",
    3: "pole",
    4: "tree",
}

_DEFAULT_SLIVER_M2 = 1000.0
# Nodata (class 0) regions below this area are treated as sensor speckle /
# coverage gaps and left for the carve pipeline's absorption steps; regions
# at or above it (a river, sandbank, settlement or big cloud/shadow gap) are
# carved as their own "no-data" block so a real feature never silently
# inflates an adjacent forest block's statistics.
_DEFAULT_NODATA_MIN_M2 = 10000.0  # 1 ha
_VALID_MAX_M = 50  # values above this are sensor noise, same cap as analysis.py
# Boundary-smoothing radius (see app/services/geom_generalize.py) — unlike
# slope/aspect, this vectorizer had NO generalization pass at all: each
# polygon traced the exact 5 m canopy_height5m.tif pixel grid, which is
# noisier than the 30 m rasters (single-pixel classification "speckle" is
# common in this spaceborne product). ~1.3x the 5 m pixel: aggressive enough
# to erase the speckle, still small enough that a real canopy strip along a
# stream or ridge survives.
_GEN_RADIUS_DEG = meters_to_deg(6.5)
# Light Douglas-Peucker cleanup after smoothing, to trim the extra vertices
# the round-join buffer round-trip adds — deliberately smaller than the
# smoothing radius itself so it only removes redundant points, not shape.
_SIMPLIFY_DEG = meters_to_deg(2.5)


def _boundary_geojson(calc: Calculation, db: Session) -> dict | None:
    gj = db.execute(
        text("SELECT ST_AsGeoJSON(boundary_geom) FROM calculations WHERE id = :cid"),
        {"cid": str(calc.id)},
    ).scalar()
    return json.loads(gj) if gj else None


def _classify(raw, valid_mask):
    """Vectorised (no per-pixel Python calls — real forests are hundreds of
    thousands of pixels at 5 m resolution): 1 m -> non-forest, 2-5 ->
    regeneration, 6-15 -> pole, 16-50 (valid_mask already excludes 0 and
    >50) -> tree."""
    import numpy as np

    out = np.zeros(raw.shape, dtype="uint8")
    out[valid_mask & (raw == 1)] = 1
    out[valid_mask & (raw >= 2) & (raw <= 5)] = 2
    out[valid_mask & (raw >= 6) & (raw <= 15)] = 3
    out[valid_mask & (raw >= 16)] = 4
    return out


def _refine_piece(poly: Any, boundary_shape: Any) -> Any | None:
    """Generalize one carved polygon the same way the valid-class path did:
    round off the raw pixel-staircase boundary (see geom_generalize.py), then
    light Douglas-Peucker cleanup, then re-clip to the true forest boundary
    as the ABSOLUTE last step (simplify preserves no containment, so doing it
    after the re-clip could silently push a piece back outside). A shape
    narrower than ~2x the smoothing radius everywhere can collapse to empty
    here — that is a correct outcome for this pass, not an error."""
    try:
        smoothed = poly.buffer(_GEN_RADIUS_DEG, join_style="round").buffer(
            -_GEN_RADIUS_DEG, join_style="round"
        )
        if smoothed.is_empty:
            return None
        smoothed = smoothed.simplify(_SIMPLIFY_DEG, preserve_topology=True)
        if smoothed.is_empty:
            return None
        smoothed = smoothed.intersection(boundary_shape)
        if smoothed.is_empty:
            return None
    except Exception:  # noqa: BLE001 -- degenerate geometry, keep the raw shape
        logger.debug("canopy piece smoothing failed, keeping raw shape", exc_info=True)
        smoothed = poly
    return smoothed


def _explode_multiparts(polys: list[Any]) -> list[Any]:
    """Split any multi-part geometry into single-part pieces (mirrors
    `auto_block_service._explode_multiparts`)."""
    out: list[Any] = []
    for g in polys:
        if g.is_empty:
            continue
        if getattr(g, "geom_type", "").startswith("Multi"):
            out.extend(p for p in g.geoms if p is not None and not p.is_empty)
        else:
            out.append(g)
    return out


def canopy_class_pieces(
    calc: Calculation, db: Session, sliver_m2: float | None = None,
    nodata_min_m2: float | None = None, scope_geojson: dict | None = None,
) -> list[tuple[int, Any]]:
    """One ``(class 1-4, shapely_geom)`` pair per contiguous same-class
    canopy-height region inside the forest boundary, plus one ``(class 0,
    geom)`` per contiguous no-data region at or above ``nodata_min_m2``
    (default 1 ha) — a river/sandbank/settlement/sensor-gap patch large
    enough to be a real feature is carved as its own "no-data" piece
    instead of being silently absorbed into a neighbouring forest block.
    Smaller no-data patches stay absorbed (they are sensor speckle / coverage
    gaps). Empty list when the TIF is absent/unreadable or the boundary has
    no valid canopy coverage there (a real, expected gap for parts of this
    product — not an error).

    ``scope_geojson`` (rule 19) replaces the forest boundary for **both** the
    raster window and the final re-clip, so a divide reads one compartment's
    window instead of vectorizing the whole TIF and discarding most of it in
    Python. It is GeoJSON, not WKT, because this source is rasterio rather than
    PostGIS: ``rio_mask`` wants a GeoJSON geometry and a WKT round-trip through
    ``json.loads(shapely_shape(wkt).__geo_interface__)`` would be a pointless
    detour. Passed as a mapping of the shapely scope the callers already hold.
    """
    geojson = scope_geojson if scope_geojson is not None else _boundary_geojson(calc, db)
    if not geojson:
        return []
    boundary_shape = shapely_shape(geojson)
    sliver = float(sliver_m2 or _DEFAULT_SLIVER_M2)
    nodata_min = float(nodata_min_m2 or _DEFAULT_NODATA_MIN_M2)

    try:
        import rasterio
        from rasterio.features import shapes as rio_shapes
        from rasterio.mask import mask as rio_mask

        from app.services.analysis import CANOPY_TIF_PATH

        with rasterio.open(CANOPY_TIF_PATH) as src:
            out_image, out_transform = rio_mask(src, [geojson], crop=True)
        data = out_image[0]
        raw = data.filled(0) if hasattr(data, "filled") else data

        valid_mask = (raw > 0) & (raw <= _VALID_MAX_M)
        if not valid_mask.any():
            return []

        classified = _classify(raw, valid_mask)

        polys_by_class: dict[int, list] = {}
        for geom, val in rio_shapes(
            classified, mask=valid_mask, transform=out_transform
        ):
            cls = int(val)
            if cls < 1 or cls > 4:
                continue
            polys_by_class.setdefault(cls, []).append(shapely_shape(geom))
    except Exception:  # noqa: BLE001 -- missing/unreadable TIF or bad geometry -> empty
        logger.debug("canopy_class_pieces: TIF read failed", exc_info=True)
        return []

    out: list[tuple[int, Any]] = []
    for cls, polys in polys_by_class.items():
        # rasterio.features.shapes already groups 4-connected same-value
        # pixels into one polygon per contiguous region — no separate
        # dissolve step needed (unlike the SQL px->merged->parts path, which
        # has to union explicitly). Each polygon here is already one region.
        for poly in polys:
            if poly.is_empty:
                continue
            try:
                area_sqm, _ = calculate_polygon_area_utm(poly)
            except Exception:  # noqa: BLE001 -- unprojectable sliver, drop it
                continue
            if area_sqm < sliver:
                continue
            smoothed = _refine_piece(poly, boundary_shape)
            if smoothed is None:
                continue
            out.append((cls, smoothed))

    # No-data regions: the complement of the valid pixels, clipped back to
    # the forest boundary. rio_shapes over the mask yields one polygon for
    # the whole 0-valued window (interior no-data + the exterior rim), so
    # each piece must be intersected with the boundary and the interior
    # fragments exploded + area-filtered here to recover the discrete
    # features (a river strip, a sandbank...) as separate pieces.
    if nodata_min > 0 and valid_mask.any():
        try:
            nodata_mask = ~valid_mask
            import numpy as np

            nodata_labeled = np.zeros(raw.shape, dtype="uint8")
            nodata_labeled[nodata_mask] = 1
            for geom, _val in rio_shapes(
                nodata_labeled, mask=nodata_mask, transform=out_transform
            ):
                region = shapely_shape(geom).intersection(boundary_shape)
                for frag in _explode_multiparts([region]):
                    if frag.is_empty:
                        continue
                    try:
                        area_sqm, _ = calculate_polygon_area_utm(frag)
                    except Exception:  # noqa: BLE001 -- unprojectable fragment
                        continue
                    if area_sqm < nodata_min:
                        continue
                    smoothed = _refine_piece(frag, boundary_shape)
                    if smoothed is None:
                        continue
                    out.append((0, smoothed))
        except Exception:  # noqa: BLE001 -- no-data carve is best-effort
            logger.debug("canopy nodata carve failed", exc_info=True)

    return out


def canopy_dominant_class(geom_wkt: str, db: Session) -> int | None:
    """Majority canopy class (1-4) inside one geometry — used to re-derive a
    final OUTPUT piece's classification after the shared carve pipeline
    (hole-fill/dedupe/sliver-absorb/merge) may have altered its geometry from
    the input piece it started as. Mirrors `aspect_dominant_code`'s role
    (and, for slope, `zone_classifier.dominant_slope_band`). ``None`` on any
    failure, missing/unreadable TIF, or no valid pixels in the geometry."""
    if not geom_wkt:
        return None
    gj = db.execute(
        text("SELECT ST_AsGeoJSON(ST_GeomFromText(:wkt, 4326))"), {"wkt": geom_wkt}
    ).scalar()
    if not gj:
        return None
    try:
        import numpy as np
        import rasterio
        from rasterio.mask import mask as rio_mask

        from app.services.analysis import CANOPY_TIF_PATH

        with rasterio.open(CANOPY_TIF_PATH) as src:
            out_image, _ = rio_mask(src, [json.loads(gj)], crop=True)
        data = out_image[0]
        raw = data.filled(0) if hasattr(data, "filled") else data
        valid_mask = (raw > 0) & (raw <= _VALID_MAX_M)
        if not valid_mask.any():
            return None
        classified = _classify(raw, valid_mask)
        classes, counts = np.unique(classified[valid_mask], return_counts=True)
        return int(classes[int(np.argmax(counts))])
    except Exception:  # noqa: BLE001 -- missing/unreadable TIF -> None
        logger.debug("canopy_dominant_class failed", exc_info=True)
        return None


__all__ = ["CANOPY_CLASS_LABELS", "canopy_class_pieces", "canopy_dominant_class"]
