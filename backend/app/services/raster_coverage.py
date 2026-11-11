"""Can this forest actually be carved from a given raster layer? (RS-0.4)

Every national raster in ``rasters.*`` is optional infrastructure: it may not be
imported on a given deployment at all, and even when it is, a forest near the
edge of the country's extent can fall outside it. The natural-feature carve
(``RS-2`` onward) is built on four of these, and a carve that starts without
knowing this is a slow opaque ``ST_Intersects`` failure deep inside a vectorize
call rather than an immediate, explainable "this layer isn't available here".

The two existing coverage gates both look at exactly one table:

* ``operational_plan/prereq_check._has_raster_coverage`` -> ``rasters.dem``
* ``operational_plan/raster_zonal.coverage_available``    -> ``rasters.dem``

so "ESA WorldCover is not installed" is invisible until something slower breaks.
This module answers the question for **any** layer in ``TileService.RASTER_TABLES``,
and keeps the two failure modes apart, which is the part that matters when
debugging: a raster that is *not installed* needs a different fix from one that
is installed but does not *cover* this forest.

Safety: the layer name is resolved through the ``RASTER_TABLES`` mapping and the
table name is then re-checked against that mapping's values. No caller-supplied
string ever reaches the SQL text -- the only interpolated fragment is a name that
was already a key of the service's own catalog. This mirrors the guard
``TileService._query_raster_tile`` already applies before it builds its query.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from .tile_service import TileService

# The raster column every table in RASTER_TABLES is known to expose. Verified
# against the live schema: all of them carry `rast` (several also carry a
# `filename`), so this is the one column name that can be used unconditionally.
_RASTER_COLUMN = "rast"


class UnknownRasterLayer(ValueError):
    """The requested layer is not in ``TileService.RASTER_TABLES``.

    Distinct from a layer whose table is missing: an unknown key is a client
    mistake (a typo, or a layer this deployment does not serve), while a missing
    table is a deployment gap. Callers map the two to different responses.
    """


def known_layers() -> tuple[str, ...]:
    """Every layer key this probe can answer for, in catalog order."""
    return tuple(TileService.RASTER_TABLES)


def raster_table_for(layer: str) -> str:
    """Map a catalog layer key to its table, or raise :class:`UnknownRasterLayer`."""
    table = TileService.RASTER_TABLES.get(layer)
    if table is None:
        raise UnknownRasterLayer(layer)
    return table


def table_exists(db: Session, table: str) -> bool:
    """Is this raster table actually present in the database?

    ``to_regclass`` is used rather than catching the failure of a real query so
    that "not installed" costs one catalogue lookup instead of one failed
    raster-index scan, and so it can be reported as a value rather than an error.
    """
    if table not in TileService.RASTER_TABLES.values():
        # Belt and braces: a name that never came from the catalog never reaches
        # SQL, even if a future caller tries to pass one in.
        raise UnknownRasterLayer(table)
    row = db.execute(text("SELECT to_regclass(:t)"), {"t": table}).first()
    return bool(row and row[0])


def raster_coverage(
    db: Session, boundary_wkt: Optional[str], layer: str
) -> Dict[str, Any]:
    """Does ``layer`` cover the forest described by ``boundary_wkt``?

    Returns::

        {
            "layer":        the catalog key that was asked for,
            "table":        the table it maps to,
            "table_present": whether that table is installed,
            "covered":      whether the table exists AND a row in it intersects
                           the forest. This is the single value callers should
                           branch on; the two fields above explain *why* it is
                           False, which is the part that tells an operator
                           whether to import a raster or to move the forest.
            "tile_count":   how many rows of the table intersect the forest
                           (the same ``ST_Intersects`` the tile query uses), or
                           0 when there is nothing to count,
        }

    A missing boundary is reported as "not covered" with ``tile_count`` 0 rather
    than raised: the probe is a diagnostic, and "you have no boundary yet" is a
    perfectly good answer to "can you carve this?".
    """
    table = raster_table_for(layer)

    result: Dict[str, Any] = {
        "layer": layer,
        "table": table,
        "table_present": False,
        "covered": False,
        "tile_count": 0,
        "has_boundary": bool(boundary_wkt),
    }

    if not table_exists(db, table):
        return result
    result["table_present"] = True

    if not boundary_wkt:
        return result

    # The table name is a catalog value, never caller input (see module docstring).
    sql = text(
        f"SELECT COUNT(*) FROM {table} r "  # noqa: S608 - catalog-interpolated
        f"WHERE ST_Intersects(r.{_RASTER_COLUMN}, ST_GeomFromText(:wkt, 4326))"
    )
    count = db.execute(sql, {"wkt": boundary_wkt}).scalar()
    result["tile_count"] = int(count or 0)
    result["covered"] = result["tile_count"] > 0
    return result


__all__ = [
    "UnknownRasterLayer",
    "known_layers",
    "raster_table_for",
    "table_exists",
    "raster_coverage",
]
