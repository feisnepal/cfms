"""Area model core (FS-3a1.1, D8 / C4 / C6').

Canonical geometry shells + area figures for a forest, matching the owner's definitions
(plan Appendix B, decisions D8/C4/C6'):

    outer boundary        the drawn boundary
    private land          NOT forest -- every ``private_land`` sub-area, regardless of
                           its ``isExcluded`` flag (owner Q4, F7: today the flag gates
                           deduction; FS-3.3 makes this the one rule everywhere else --
                           this module does not replicate the old flag-gated behaviour)
    total forest area  =  outer boundary - private land
    protected forest   =  union of ``protected`` sub-areas and protection working-circle
                           units, counted ONCE (F8: an overlap between the two must not
                           double-deduct), clipped to the total forest area
    effective area     =  tree-cover part of (total forest area - protected forest)

Today the word "effective area" means three different things across the codebase
(``result_data['effective_area_hectares']`` is actually the TOTAL FOREST AREA; Table 5's
``effective_area_ha`` is the true effective area; ``in_effective_area`` on tiles is a
point-in-net-geometry test). This module does not rename any of those call sites --
FS-3a1 builds the function, callers migrate in P3/P3a-2. Lean L1: no aliases.

Pure Shapely + a thin DB loader (``calc.boundary_geom`` + ``calc.result_data['sub_areas']``
+ the unit rows via ``forest_units.queries``). Branch-generic throughout (I10): a
protection unit is found by ``working_circle == 'protection'``, never by
``is_compartment`` or a depth test. Area is measured with
``geometry_edit_service.area_sqm`` (geodesic -- the "existing UTM helper").

Tree cover: production reads the ESA WorldCover raster (mirrors
``tree_cover_analysis.calculate_block_tree_cover_areas``'s query, generalised from a list
of blocks to one arbitrary geometry); tests pass ``tree_cover_ratio`` explicitly since the
test database carries no raster.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from geoalchemy2.shape import to_shape
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...core.sub_area_kinds import PROTECTION_SUB_AREA_CATEGORIES
from ...models.calculation import Calculation
from ..geometry_edit_service import area_sqm
from . import queries as unit_queries

logger = logging.getLogger(__name__)

_SQM_PER_HA = 10_000.0
_ESA_TREE_COVER_VALUE = 10


def _sub_area_geoms(calc: Calculation, category: str) -> list:
    """Every sub-area of ``category``, geometry only, regardless of ``isExcluded``."""
    rd = calc.result_data if isinstance(calc.result_data, dict) else {}
    out = []
    for sa in rd.get("sub_areas") or []:
        if sa.get("category") != category:
            continue
        raw = sa.get("geometry")
        if not isinstance(raw, dict):
            continue
        try:
            geom = shape(raw)
        except Exception:  # noqa: BLE001 -- a bad sub-area geometry must not break the area model
            logger.warning(
                "[area_model] skipping unparseable %s sub-area", category, exc_info=True
            )
            continue
        if geom is not None and not geom.is_empty:
            out.append(geom)
    return out


def _union(geoms: list) -> Optional[BaseGeometry]:
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return None
    try:
        return unary_union(geoms)
    except Exception:  # noqa: BLE001 -- a bad geometry must not break the area model
        logger.warning("[area_model] union failed", exc_info=True)
        return geoms[0]


def outer_boundary_geom(calc: Calculation) -> Optional[BaseGeometry]:
    """The drawn boundary. ``None`` only when the forest has no boundary at all."""
    if getattr(calc, "boundary_geom", None) is None:
        return None
    return to_shape(calc.boundary_geom)


def private_land_geom(calc: Calculation) -> Optional[BaseGeometry]:
    """Union of every ``private_land`` sub-area. NOT forest."""
    return _union(_sub_area_geoms(calc, "private_land"))


def forest_area_geom(calc: Calculation) -> Optional[BaseGeometry]:
    """Total forest area = outer boundary - private land."""
    outer = outer_boundary_geom(calc)
    if outer is None:
        return None
    private = private_land_geom(calc)
    if private is None:
        return outer
    try:
        return outer.difference(private)
    except Exception:  # noqa: BLE001 -- a bad private-land geometry must not break the shell
        logger.warning("[area_model] boundary - private_land failed", exc_info=True)
        return outer


def protection_unit_geoms(db: Session, calc: Calculation) -> list:
    """Geometry of every leaf unit on the protection working circle, whichever branch
    this forest uses (I10: ``working_circle`` decides, never ``is_compartment``)."""
    out = []
    try:
        for row in unit_queries.unit_rows(db, calc.id, unit_queries.View.LEAF):
            if (row.working_circle or "production") != "protection":
                continue
            if row.geometry is not None:
                out.append(to_shape(row.geometry))
    except Exception:  # noqa: BLE001 -- no unit rows (upload-mode forest) -> no protection units
        logger.warning("[area_model] protection-unit lookup failed", exc_info=True)
    return out


def protected_forest_geom(db: Session, calc: Calculation) -> Optional[BaseGeometry]:
    """Union of the protection sub-areas (``protected`` zones and the river bank: ``PROTECTION_SUB_AREA_CATEGORIES``) and protection
    working-circle units, counted ONCE (a river bank over a protected zone is not deducted twice), clipped to the total forest area (protection can never claim ground the
    forest itself does not have -- e.g. inside private land)."""
    geoms = [g for cat in PROTECTION_SUB_AREA_CATEGORIES for g in _sub_area_geoms(calc, cat)] + protection_unit_geoms(db, calc)
    union = _union(geoms)
    if union is None:
        return None
    forest = forest_area_geom(calc)
    if forest is None:
        return union
    try:
        return union.intersection(forest)
    except Exception:  # noqa: BLE001 -- a bad geometry must not break the shell
        logger.warning("[area_model] protected ∩ forest_area failed", exc_info=True)
        return union


def effective_geom(db: Session, calc: Calculation) -> Optional[BaseGeometry]:
    """The unprotected part of the total forest area. There is no "which trees"
    polygon -- tree cover is applied as a ratio at the area level (``area_figures``),
    not clipped out of this geometry pixel-by-pixel."""
    forest = forest_area_geom(calc)
    if forest is None:
        return None
    protected = protected_forest_geom(db, calc)
    if protected is None:
        return forest
    try:
        return forest.difference(protected)
    except Exception:  # noqa: BLE001 -- a bad geometry must not break the shell
        logger.warning("[area_model] forest_area - protected failed", exc_info=True)
        return forest


def _ha(geom: Optional[BaseGeometry]) -> float:
    return round(area_sqm(geom) / _SQM_PER_HA, 4) if geom is not None else 0.0


def _tree_cover_ratio_for_geom(db: Session, geom: Optional[BaseGeometry]) -> float:
    """Production tree-cover ratio for an arbitrary geometry: the ESA WorldCover
    value=10 pixel fraction, mirroring ``tree_cover_analysis.calculate_block_tree_cover_areas``'s
    query but for one ad-hoc geometry rather than a list of named blocks. SAVEPOINT-guarded
    (a missing/non-covering raster must not poison the caller's transaction); degrades to
    ``0.0`` -- callers that need a different fallback pass ``tree_cover_ratio`` explicitly."""
    if geom is None or geom.is_empty:
        return 0.0
    try:
        with db.begin_nested():
            result = db.execute(
                text(
                    """
                WITH boundary AS (SELECT ST_GeomFromText(:wkt, 4326) AS geom),
                clipped AS (
                    SELECT ST_Clip(rast, b.geom, 0.0, true) AS clipped_rast
                    FROM rasters.esa_world_cover, boundary b
                    WHERE ST_Intersects(rast, b.geom)
                ),
                counts AS (
                    SELECT (ST_ValueCount(clipped_rast, 1, true)).*
                    FROM clipped
                    WHERE clipped_rast IS NOT NULL
                )
                SELECT
                    SUM(count) FILTER (WHERE value = :tree_value) AS tree_px,
                    SUM(count) FILTER (WHERE value > 0) AS total_px
                FROM counts
            """
                ),
                {"wkt": geom.wkt, "tree_value": _ESA_TREE_COVER_VALUE},
            ).first()
    except Exception:  # noqa: BLE001 -- no raster coverage -> no ratio, never fail the caller
        logger.warning("[area_model] tree-cover raster query failed", exc_info=True)
        return 0.0
    if result is None or not result.total_px:
        return 0.0
    return float(result.tree_px or 0) / float(result.total_px)


@dataclass
class AreaFigures:
    outer_ha: float
    private_ha: float
    total_forest_ha: float
    protected_ha: float
    effective_ha: float
    tree_cover_ratio: float


def area_figures(
    db: Session, calc: Calculation, *, tree_cover_ratio: Optional[float] = None
) -> AreaFigures:
    """The canonical area figures (FS-3a1.2 naming) for one forest.

    ``tree_cover_ratio``: pass explicitly in tests (the test database carries no ESA
    raster); omit in production to read it from the raster over the unprotected total
    forest area.

    Every figure below is derived ARITHMETICALLY from independently-measured pieces
    (``outer_ha``, ``private_ha``, ``protected_ha``), never by re-measuring a difference/
    intersection geometry's own area. Geodesic area of ``A.difference(B)`` and
    ``area(A) - area(B)`` are mathematically equal but not bit-identical (each goes
    through its own re-projection), so "measure the difference geometry directly" drifts
    from "subtract two independently-measured areas" by a few parts in a million --
    enough to fail an exact check between the two. Deriving every figure the same way
    (subtraction) makes them agree by construction, not by coincidence.
    """
    outer = outer_boundary_geom(calc)
    private = private_land_geom(calc)
    protected = protected_forest_geom(db, calc)

    outer_ha = _ha(outer)
    private_ha = _ha(private)
    total_forest_ha = round(outer_ha - private_ha, 4)
    protected_ha = _ha(protected)
    unprotected_ha = max(total_forest_ha - protected_ha, 0.0)

    if tree_cover_ratio is None:
        tree_cover_ratio = _tree_cover_ratio_for_geom(db, effective_geom(db, calc))

    return AreaFigures(
        outer_ha=outer_ha,
        private_ha=private_ha,
        total_forest_ha=total_forest_ha,
        protected_ha=protected_ha,
        effective_ha=round(unprotected_ha * tree_cover_ratio, 4),
        tree_cover_ratio=round(tree_cover_ratio, 4),
    )
