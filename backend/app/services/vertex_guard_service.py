"""Server-side locked-vertex guard (VR-3).

Until now the vertex rules lived only in the browser: `vertexEditMask` hid the
markers a user was not allowed to grab, and that was the whole enforcement.
Anything not going through those markers — undo/redo, a retried request, a
stale tab, a second client, curl — could move a locked vertex and the API
would store it.  The classification engine written in V-1 was never called.

This module makes the server the authority.  Given the geometry a request
wants to store, it re-derives the classification from what is ACTUALLY in the
database and refuses the write when a locked vertex was touched:

  * a vertex classified ``shell`` moved, or
  * a ``shell`` vertex disappeared, or
  * a vertex was introduced ON the shell.

Rule A (the forest boundary is editable only while no structural feature
exists) is enforced here too, since it is the same class of question.

The comparison is deliberately tolerant.  A coordinate makes the round trip
PostGIS → GeoJSON → Leaflet ``LatLng`` → JSON → shapely and picks up
micro-degree drift on the way, so "unchanged" means *within
``VERTEX_MOVE_EPSILON_M`` (1 mm)*, not bitwise equal.  That is three orders of
magnitude below the 1 m classification tolerance and far below any edit a
person could mean — see the note beside the constants.
"""
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..core.constants import VERTEX_COINCIDENCE_TOLERANCE_M, VERTEX_MOVE_EPSILON_M
from .vertex_classification_service import (
    BOUNDARY_LAYER,
    STRUCTURAL_LAYERS,
    _as_shapely,
    classify_vertices,
    iter_vertices,
)

logger = logging.getLogger(__name__)

VERTEX_LOCKED = "VERTEX_LOCKED"
BOUNDARY_LOCKED_BY_STRUCTURE = "BOUNDARY_LOCKED_BY_STRUCTURE"

#: Metres per degree of latitude — the same flat approximation the rest of the
#: geometry stack uses (`_metres_to_degrees`, `pointSegmentDistanceM`).
_M_PER_DEG = 111_320.0


class LockedVertexError(Exception):
    """A write touched a vertex the rules lock.  Carries the offending indices."""

    def __init__(self, code: str, message: str, indices: Optional[List[int]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.indices = indices or []


def _distance_m(a: Sequence[float], b: Sequence[float]) -> float:
    """Planar metre distance between two lon/lat pairs (metre-scale accurate)."""
    import math

    dx = (a[0] - b[0]) * _M_PER_DEG * math.cos(math.radians((a[1] + b[1]) / 2.0))
    dy = (a[1] - b[1]) * _M_PER_DEG
    return math.hypot(dx, dy)


def _coords(geometry: Any) -> List[Tuple[float, float]]:
    """Flat vertex list in the VR-2 index space (exterior rings, no closing dup)."""
    return [coord for _, coord in iter_vertices(geometry)]


def _nearest_distance_m(point: Sequence[float], pool: Sequence[Sequence[float]]) -> float:
    if not pool:
        return float("inf")
    return min(_distance_m(point, q) for q in pool)


def diff_vertices(
    stored: Any,
    submitted: Any,
    epsilon_m: float = VERTEX_MOVE_EPSILON_M,
) -> Dict[str, List[int]]:
    """Which stored vertices were disturbed by ``submitted``?

    Position-independent on purpose: a request may legitimately insert or drop
    a vertex elsewhere in the ring, which renumbers everything after it, so
    comparing index-for-index would flag the whole tail as moved.  Instead each
    stored vertex asks "is there still a submitted vertex within epsilon of
    me?" — that is exactly the question the lock rules care about.

    Returns stored-geometry indices under:
      ``moved``   — no submitted vertex remains at this position;
      ``added``   — submitted indices with no stored vertex at that position.
    """
    stored_pts = _coords(stored)
    submitted_pts = _coords(submitted)

    moved = [
        i for i, p in enumerate(stored_pts)
        if _nearest_distance_m(p, submitted_pts) > epsilon_m
    ]
    added = [
        j for j, q in enumerate(submitted_pts)
        if _nearest_distance_m(q, stored_pts) > epsilon_m
    ]
    return {"moved": moved, "added": added}


def assert_no_locked_vertex_change(
    stored_geometry: Any,
    submitted_geometry: Any,
    layer_type: str,
    same_level_features: Sequence[Any],
    parent_shell: Any,
    epsilon_m: float = VERTEX_MOVE_EPSILON_M,
) -> None:
    """Raise :class:`LockedVertexError` when the write disturbs a locked vertex.

    ``stored_geometry`` must come from the DATABASE, never from the request —
    the whole point is that the client's view of what is locked is not trusted.
    """
    if layer_type not in STRUCTURAL_LAYERS:
        return  # boundary has its own gate; sub_areas / imported are unruled
    stored = _as_shapely(stored_geometry)
    submitted = _as_shapely(submitted_geometry)
    if stored is None or submitted is None:
        return

    classification = classify_vertices(
        stored,
        layer_type,
        list(same_level_features),
        parent_shell=parent_shell,
    )
    shell = set(classification.get("shell", []))
    if not shell:
        return  # nothing is locked on this feature

    delta = diff_vertices(stored, submitted, epsilon_m=epsilon_m)
    disturbed = sorted(shell.intersection(delta["moved"]))
    if disturbed:
        raise LockedVertexError(
            VERTEX_LOCKED,
            "This vertex sits on the outer boundary and cannot be moved or removed.",
            disturbed,
        )

    # A vertex INTRODUCED on the shell is equally forbidden: it becomes a new
    # locked vertex the client never had, and lets the shell be reshaped by
    # addition rather than by movement.
    if delta["added"] and parent_shell is not None:
        shell_boundary = _as_shapely(parent_shell)
        boundary = getattr(shell_boundary, "boundary", None) if shell_boundary else None
        if boundary is not None and not boundary.is_empty:
            from shapely.geometry import Point

            tol_deg = VERTEX_COINCIDENCE_TOLERANCE_M / _M_PER_DEG
            submitted_pts = _coords(submitted)
            on_shell = [
                j for j in delta["added"]
                if Point(submitted_pts[j]).distance(boundary) <= tol_deg
            ]
            if on_shell:
                raise LockedVertexError(
                    VERTEX_LOCKED,
                    "A vertex cannot be added on the outer boundary.",
                    sorted(on_shell),
                )


def has_structural_features(db, calc) -> bool:
    """Does this calculation hold any block / compartment / sub-compartment?

    Rule A's gate: the forest boundary is editable only while the answer is No.
    """
    from ..models.forest_block import ForestBlock

    return (
        db.query(ForestBlock.id)
        .filter(ForestBlock.calculation_id == calc.id)
        .first()
        is not None
    )


#: Symmetric-difference area (m²) below which two boundaries are "the same
#: shape".  Sits above round-trip float noise and below the 1 m coincidence
#: tolerance the rest of the rule model uses, so an idempotent re-save passes
#: while any reshape a person could intend does not.
BOUNDARY_SHAPE_EPSILON_M2 = 1.0


def boundary_shape_changed(stored: Any, submitted: Any) -> bool:
    """Is this a boundary RESHAPE, or the same shape sent again?

    Compared TOPOLOGICALLY, by symmetric-difference area.  Coordinate-wise
    comparison is wrong here: shapely's ``box()`` starts its ring at a
    different corner than a hand-written GeoJSON ring, so ``equals_exact``
    reported a plain re-save as a reshape and blocked idempotent writes.

    Lives in the guard because BOTH boundary routes need it, and the last time
    two routes each carried their own copy of a rule, only one of them was
    actually enforcing it.
    """
    a = _as_shapely(stored)
    b = _as_shapely(submitted)
    if a is None or b is None:
        return True
    try:
        if a.equals(b):
            return False
        # Degrees² → m² with the same flat approximation used elsewhere.
        diff_deg2 = a.symmetric_difference(b).area
        return diff_deg2 * (_M_PER_DEG ** 2) > BOUNDARY_SHAPE_EPSILON_M2
    except Exception:  # pragma: no cover - defensive
        # True means "the shape changed", the conservative answer: the guard
        # refuses the edit rather than letting an unverified one through.
        logger.exception(
            "boundary shape comparison failed - treating the boundary as "
            "changed, so the edit will be refused"
        )
        return True


def assert_boundary_editable(db, calc) -> None:
    """Raise :class:`LockedVertexError` when Rule A locks the boundary.

    Moving a boundary vertex while blocks exist desynchronises the blocks'
    outer edge from the boundary they are supposed to tile, which the coverage
    invariant would then have to repair.  Refuse instead.
    """
    if has_structural_features(db, calc):
        raise LockedVertexError(
            BOUNDARY_LOCKED_BY_STRUCTURE,
            "The forest boundary is locked because blocks or compartments exist. "
            "Edit those instead, or remove them first.",
        )


__all__ = [
    "BOUNDARY_LOCKED_BY_STRUCTURE",
    "LockedVertexError",
    "VERTEX_LOCKED",
    "assert_boundary_editable",
    "assert_no_locked_vertex_change",
    "diff_vertices",
    "has_structural_features",
]
