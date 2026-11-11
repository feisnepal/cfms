"""Estimate a block's crown density where the OP metadata gives no measured
value (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P10, follow-on).

Two sources, chosen by ``SfmParams.crown_density_estimate_source``:

* ``"canopy"`` — the fraction of the block's ``canopy_height5m.tif`` pixels that
  carry woody vegetation (height ≥ 2 m; value 1 = non-forest, 0 = NoData).
* ``"esa"`` — the tree-cover fraction from ``rasters.esa_world_cover`` (pixel
  value 10 = tree cover), via ``ST_ValueCount(ST_Clip(...))``.

Both degrade to ``None`` (→ the caller falls back to ``crown_density_default``)
when the raster is absent, does not cover the forest, or the read fails — the
per-block override on the SFM tab is always the final word.

``"none"`` (the default) never calls in here, so P1 behaviour is unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

CANOPY_TIF_PATH = r"D:\forest_management\canopy_height5m.tif"
_WOODY_MIN_M = 2  # uint8 metres; 1 == non-forest, 0 == NoData


def _canopy_crown_pct(geojson: dict) -> Optional[int]:
    """% of the polygon's canopy pixels with height ≥ ``_WOODY_MIN_M``."""
    try:
        import numpy as np
        import rasterio
        from rasterio.mask import mask as rio_mask

        with rasterio.open(CANOPY_TIF_PATH) as src:
            out, _ = rio_mask(src, [geojson], crop=True)
        data = out[0]
        valid = data.compressed() if hasattr(data, "mask") else data.flatten()
        valid = valid[(valid > 0) & (valid <= 50)]  # drop NoData + spikes
        if valid.size == 0:
            return None
        woody = int((valid >= _WOODY_MIN_M).sum())
        return int(round(100.0 * woody / valid.size))
    except Exception:  # noqa: BLE001 -- a missing / unreadable TIF → no estimate
        logger.debug("canopy crown-density read failed", exc_info=True)
        return None


def _esa_crown_pct(geom_wkt: str, db: Session) -> Optional[int]:
    """Tree-cover fraction from ``rasters.esa_world_cover`` (value 10)."""
    try:
        # SAVEPOINT: a missing rasters.esa_world_cover (bare test DB) must roll
        # back just this, not poison the caller's transaction.
        with db.begin_nested():
            row = db.execute(
                text(
                    "WITH b AS (SELECT ST_GeomFromText(:wkt, 4326) AS geom), "
                    "px AS ("
                    "  SELECT (ST_ValueCount("
                    "    ST_Clip(rast, b.geom, 0.0, true), 1, true)).* "
                    "  FROM rasters.esa_world_cover, b "
                    "  WHERE ST_Intersects(rast, b.geom)"
                    ") "
                    "SELECT "
                    "  COALESCE(SUM(count) FILTER (WHERE value = 10), 0) AS tree, "
                    "  COALESCE(SUM(count), 0) AS total "
                    "FROM px"
                ),
                {"wkt": geom_wkt},
            ).first()
        if not row or not row.total:
            return None
        return int(round(100.0 * float(row.tree) / float(row.total)))
    except Exception:  # noqa: BLE001 -- raster absent / no coverage → no estimate
        logger.debug("ESA crown-density read failed", exc_info=True)
        return None


def estimate_crown_density(geom_wkt: str, source: str, db: Session) -> Optional[int]:
    """Crown-density % for one block, or ``None`` when it cannot be estimated."""
    if not geom_wkt or source not in ("canopy", "esa"):
        return None
    if source == "esa":
        return _esa_crown_pct(geom_wkt, db)
    # canopy — needs a GeoJSON geometry for the rasterio clip
    try:
        gj = db.execute(
            text("SELECT ST_AsGeoJSON(ST_GeomFromText(:wkt, 4326))"),
            {"wkt": geom_wkt},
        ).scalar()
    except Exception:  # noqa: BLE001
        logger.debug("wkt→geojson failed for canopy estimate", exc_info=True)
        return None
    if not gj:
        return None
    return _canopy_crown_pct(json.loads(gj))


__all__ = ["estimate_crown_density"]
