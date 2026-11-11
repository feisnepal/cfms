"""What an SFM block IS before it can have a forest type (owner decisions, 2026-10-06).

* A block that has trees MUST have sample plots; its forest type comes from its OWN plots only -- never from a
  neighbouring block, the forest as a whole, a raster, or a national table.
* River, grassland, rangeland, snow and water blocks may have no plots and have no forest type.
* The land class is taken straight from the ESA WorldCover suggestion for the block, and the user may override it.
* 5 or more plots in a block is enough for a firm type; 1-4 plots is "provisional".

Pure decision logic plus one read-only raster query. No writes.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.constants import SFM_MIN_PLOTS_PER_BLOCK

logger = logging.getLogger(__name__)

FOREST = "forest"
LAND_CLASSES = ("forest", "grassland", "rangeland", "river", "water", "snow", "other_nonforest")

# Block states the SFM tab shows
CLASSIFIED = "classified"            # forest, >= SFM_MIN_PLOTS_PER_BLOCK plots: a type from its own plots
PROVISIONAL = "provisional"          # forest, 1..4 plots: a type from its own plots, but too few
INVENTORY_MISSING = "inventory_missing"  # forest, no plots: no type -- the plan cannot be accepted
NON_FOREST = "non_forest"            # not forest land: no type, and no plots expected

# ESA WorldCover class -> land class. Shrubland (20) and mangrove (95) stay "forest": they carry trees and need
# plots. Rangeland has no ESA class, so it is user-set only.
_ESA_TO_CLASS = {
    10: "forest",
    20: "forest",
    30: "grassland",
    40: "other_nonforest",
    50: "other_nonforest",
    60: "other_nonforest",
    70: "snow",
    80: "water",
    90: "other_nonforest",
    95: "forest",
    100: "other_nonforest",
}


def esa_land_class(db: Session, wkt: str) -> tuple[str, Optional[int], Optional[float]]:
    """``(land_class, dominant_esa_code, dominant_pct)`` for a block geometry. Falls back to ``forest`` when the
    raster has no answer: a block is never silently declared non-forest."""
    if not wkt:
        return FOREST, None, None
    try:
        # A SAVEPOINT: if the raster is missing, only this query is undone. A plain `db.rollback()` here would also
        # roll back whatever the caller had pending in the same session.
        with db.begin_nested():
            rows = db.execute(
                text(
                    """
                    SELECT (pvc).value AS code, SUM((pvc).count) AS n
                    FROM (
                        SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) AS pvc
                        FROM rasters.esa_world_cover WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
                    ) s
                    WHERE (pvc).value IS NOT NULL AND (pvc).value > 0
                    GROUP BY code ORDER BY n DESC
                    """
                ),
                {"wkt": wkt},
            ).fetchall()
    except Exception:  # noqa: BLE001 -- raster unavailable: do not guess non-forest
        logger.warning("ESA land-class suggestion unavailable", exc_info=True)
        return FOREST, None, None
    if not rows:
        return FOREST, None, None
    total = float(sum(r.n for r in rows)) or 1.0
    code = int(rows[0].code)
    return _ESA_TO_CLASS.get(code, "forest"), code, round(100.0 * float(rows[0].n) / total, 1)


def block_state(land_class: str, plot_count: int, min_plots: int = SFM_MIN_PLOTS_PER_BLOCK) -> str:
    """The state of a block from its land class and how many sample plots it has."""
    if land_class != FOREST:
        return NON_FOREST
    if plot_count <= 0:
        return INVENTORY_MISSING
    return CLASSIFIED if plot_count >= min_plots else PROVISIONAL


__all__ = [
    "FOREST", "LAND_CLASSES", "CLASSIFIED", "PROVISIONAL", "INVENTORY_MISSING", "NON_FOREST",
    "esa_land_class", "block_state",
]
