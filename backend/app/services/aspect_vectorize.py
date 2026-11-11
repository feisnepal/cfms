"""Vectorise ``rasters.aspect`` into carve candidates for the Auto-Block
`aspect` source (SLOPE_COMPARTMENT_AND_STRATIFIED_SAMPLING_PLAN follow-on).

Delegates to ``app/services/raster_class_vectorize.py::class_pieces`` — the one
implementation now shared with slope, NASA, NDVI, ESA and DEM (RS-1.7). Only the
aspect-specific facts live here, in ``ASPECT_CLASSES``: the table, the 1-8 code
set, and the 30 m pixel that sizes the smoothing radius.

``rasters.aspect`` is already categorical (8BUI, values 0-8), the same as
``slope_regulation`` is already categorical (1-4) — no binning needed here,
unlike canopy height (see ``canopy_vectorize.py``).

Value 0 (flat / no dominant direction) is treated as no-data and excluded,
matching the existing convention in ``analysis.py::analyze_aspect`` (its
``aspect_map`` and ``val BETWEEN 1 AND 8`` filter) — this module reuses that
same 1-8 -> N/NE/E/SE/S/SW/W/NW scheme rather than inventing a second one.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.services.raster_class_vectorize import (
    ASPECT_CLASSES,
    class_pieces,
    dominant_code,
)

# English abbreviation only — matches analysis.py::analyze_aspect's aspect_map
# verbatim (that function has no Nepali label either).
ASPECT_LABELS: dict[int, str] = {
    1: "N",
    2: "NE",
    3: "E",
    4: "SE",
    5: "S",
    6: "SW",
    7: "W",
    8: "NW",
}

# Standard 8-point compass bearing range each band covers, 45° wide,
# centred on the cardinal/intercardinal direction (owner report, 2026-10-01:
# the attribute table should show the bearing range alongside the compass
# label, same request as slope's degree range). N straddles 360°/0°.
ASPECT_DEGREE_RANGE: dict[int, str] = {
    1: "337.5–360° / 0–22.5°",
    2: "22.5–67.5°",
    3: "67.5–112.5°",
    4: "112.5–157.5°",
    5: "157.5–202.5°",
    6: "202.5–247.5°",
    7: "247.5–292.5°",
    8: "292.5–337.5°",
}

_DEFAULT_SLIVER_M2 = 1000.0
# The geometry pipeline (CTE shape, smoothing, simplify, re-clip-last, sliver
# filter, SAVEPOINT degrade) now lives once in
# ``app/services/raster_class_vectorize.py`` and is shared with slope, NASA,
# NDVI, ESA and DEM. ``ASPECT_CLASSES`` carries the only aspect-specific facts:
# the table, the 1-8 code set, and the 30 m pixel that sizes the smoothing
# radius. Values were verified identical before this delegation (RS-1.2/1.7).


def aspect_class_pieces(
    calc: Calculation,
    db: Session,
    sliver_m2: float | None = None,
    scope_wkt: str | None = None,
) -> list[tuple[int, Any]]:
    """One ``(aspect_code, shapely_geom)`` pair per contiguous same-direction
    region inside ``scope_wkt`` (or the forest boundary when no scope is given)
    — carve candidates for the Auto-Block `aspect` source. Empty list when the
    raster is absent or does not cover that area (SAVEPOINT-guarded, never
    raises)."""
    return class_pieces(
        calc,
        db,
        ASPECT_CLASSES,
        sliver_m2=sliver_m2 if sliver_m2 is not None else _DEFAULT_SLIVER_M2,
        scope_wkt=scope_wkt,
    )


def aspect_dominant_code(geom_wkt: str, db: Session) -> int | None:
    """Majority aspect code (1-8) inside one geometry — used to re-derive a
    final OUTPUT piece's classification after the shared carve pipeline
    (hole-fill/dedupe/sliver-absorb/merge) may have altered its geometry from
    the input piece it started as. Mirrors
    `sustainable_fm.zone_classifier.dominant_slope_band`'s role for slope.
    SAVEPOINT-guarded; ``None`` on any failure or no coverage."""
    return dominant_code(geom_wkt, db, ASPECT_CLASSES)


__all__ = ["ASPECT_LABELS", "ASPECT_DEGREE_RANGE", "aspect_class_pieces", "aspect_dominant_code"]
