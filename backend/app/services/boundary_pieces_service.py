"""Keep `forest_boundary_pieces` in sync with `calculation.boundary_geom`.

BOUNDARY_PIECES_PLAN.md P2. One function, called from every write path that
touches `boundary_geom` (see the plan's §1 table) right after that write, in
the same transaction. `calculation.boundary_geom` keeps its exact current
meaning (the union of every piece) -- this module only ever adds/updates rows
beside it, never changes what that column means to the 107 files that already
read it.

Piece-identity heuristic (deliberately simple for the first cut -- see plan
D7, true piece-level reshape/delete is a later phase): if the newly-written
geometry decomposes into the SAME NUMBER of parts as the calculation currently
has piece rows, each existing row is updated in place, in insertion order --
this is what lets a plain reshape of an existing piece (or the whole boundary,
when there is only one piece) survive without losing a user-given name. If the
part count differs, every existing piece row is replaced with fresh
"Piece N"-named rows -- going from N pieces to M is inherently a "the set of
pieces changed" action, not an edit of one piece, so there is no correct name
to preserve.
"""
import logging

from geoalchemy2.shape import from_shape
from shapely.geometry.base import BaseGeometry

from ..models.forest_boundary_piece import ForestBoundaryPiece
from ..utils.geometry_utils import calculate_area_geodesic_from_shapely

logger = logging.getLogger(__name__)


def _parts_of(geom: BaseGeometry) -> list:
    """A Polygon is one piece; a MultiPolygon is one piece per part. Anything
    else should not reach here (boundary_geom is always a Polygon/MultiPolygon
    by construction) -- returns [] rather than guessing, and the caller
    decides what an empty part list means for it.
    """
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    return []


def sync_boundary_pieces(db, calc, polygon: BaseGeometry) -> None:
    """Reconcile `calc`'s `forest_boundary_pieces` rows with `polygon` (shapely,
    EPSG:4326 -- the same value just written to `calc.boundary_geom`), by
    decomposing it into its constituent parts. Use this for the single-value
    writers (`persist_boundary` and the other direct `boundary_geom` writers
    in plan §1's table) -- they only ever have the one already-combined value.

    `merge_forest_boundary` should call `sync_boundary_pieces_from_parts`
    instead, with the pieces it received from the user BEFORE `unary_union`:
    a union can fuse two pieces that merely touch or were snapped to the same
    edge, which would silently lose one piece's identity if pieces were
    re-derived from the post-union shape instead.
    """
    parts = _parts_of(polygon)
    if not parts:
        logger.warning(
            "sync_boundary_pieces: unrecognised geometry type %r for calculation %s -- piece rows left untouched",
            getattr(polygon, "geom_type", None), getattr(calc, "id", "?"),
        )
        return
    sync_boundary_pieces_from_parts(db, calc, parts)


def sync_boundary_pieces_from_parts(db, calc, parts: list) -> None:
    """Reconcile `calc`'s `forest_boundary_pieces` rows with `parts` (a list of
    shapely Polygons, EPSG:4326) directly -- see `sync_boundary_pieces` for
    when to prefer this over the single-geometry entry point. Does NOT commit;
    the caller's existing transaction does that, same as every other side
    effect of a boundary write (sub-area re-clip, geometry_version bump, etc.).
    """
    if not parts:
        logger.warning(
            "sync_boundary_pieces_from_parts: called with 0 parts for calculation %s -- piece rows left untouched",
            getattr(calc, "id", "?"),
        )
        return

    existing = (
        db.query(ForestBoundaryPiece)
        .filter(ForestBoundaryPiece.calculation_id == calc.id)
        .order_by(ForestBoundaryPiece.created_at)
        .all()
    )

    if len(existing) == len(parts):
        for row, part in zip(existing, parts):
            _, area_ha = calculate_area_geodesic_from_shapely(part)
            row.geometry = from_shape(part, srid=4326)
            row.area_hectares = round(area_ha, 4)
        return

    for row in existing:
        db.delete(row)
    db.flush()
    for i, part in enumerate(parts, start=1):
        _, area_ha = calculate_area_geodesic_from_shapely(part)
        db.add(
            ForestBoundaryPiece(
                calculation_id=calc.id,
                name=f"Piece {i}",
                geometry=from_shape(part, srid=4326),
                area_hectares=round(area_ha, 4),
            )
        )
