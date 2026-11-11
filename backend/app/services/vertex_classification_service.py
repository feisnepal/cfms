"""Vertex classification engine (V-1).

Implements the vertex-edit rule model (`vertex_edit_plan.md` §1).  For a given
polygon feature it classifies every vertex into exactly one of three roles:

  - **shared**:  the vertex lies on the common boundary of two same-level
    units — within ``VERTEX_COINCIDENCE_TOLERANCE_M`` of a same-level neighbour's
    *boundary* (covers both a vertex coincident with a neighbour vertex AND a
    mid-edge vertex lying on a neighbour's edge segment).
  - **shell**:   the vertex lies on the enclosing shell at this level (forest
    boundary for blocks, block shell for compartments, compartment shell for
    sub-compartments).
  - **editable**: shared − shell.  Shell wins (rule 4: *on the enclosing
    shell wins over shared*).

Indices are **flat** over EXTERIOR rings only: for a Polygon its shell, for a
MultiPolygon each part's shell in order, each vertex counted once with the
ring's closing duplicate DROPPED.  Interior rings (holes) are neither
editable nor indexed.  ``frontend/src/lib/vertexClassifier.ts`` mirrors this
exactly and a shared fixture pins the two together
(``tests/fixtures/vertex_contract.json``).

``classify_vertices`` returns ``{"shared": [], "shell": [],
"editable": [], "vertex_count": n}``.  ``ring_of_index``/``coord_at_index``
resolve a flat index back to its ring and coordinate for marker rendering.
"""
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, MultiLineString, Point, shape as to_shapely

from ..core.constants import VERTEX_COINCIDENCE_TOLERANCE_M
from ..services.file_processor import _metres_to_degrees
from ..services.geometry_edit_service import SpatialHashIndex

logger = logging.getLogger(__name__)


# Layers whose editable set is "shared − shell" (Rule B).  The forest
# boundary (Rule A) has no shell of its own and no same-level neighbours —
# it classifies as fully editable when no structural layer exists (the caller
# decides the no-structure gate).
STRUCTURAL_LAYERS = frozenset({"blocks", "compartments", "sub_compartments"})
BOUNDARY_LAYER = "boundary"


def _as_shapely(geom: Any):
    """Coerce GeoJSON dict / shapely geometry to shapely."""
    if geom is None:
        return None
    if isinstance(geom, dict):
        try:
            return to_shapely(geom)
        except Exception:
            logger.exception(
                "geometry unreadable - it is treated as having no vertices, so "
                "none of them can be classified as shared"
            )
            return None
    return geom


def iter_vertices(geometry: Any) -> Iterable[Tuple[int, Tuple[float, float]]]:
    """Yield (flat_index, (x, y)) for every vertex of a Polygon/MultiPolygon.

    Ring order: a Polygon contributes its EXTERIOR ring; a MultiPolygon each
    part's exterior ring, parts in order.  Holes are skipped entirely — they
    are not editable, so indexing them would desync the frontend mirror.
    The closing coordinate of a
    ring (its repeated first point) is DROPPED — it is the same physical
    vertex as index 0, and rendering a second marker there would let one
    corner of a ring be dragged twice.
    """
    g = _as_shapely(geometry)
    if g is None:
        return
    if g.geom_type == "Polygon":
        for i, coord in enumerate(g.exterior.coords[:-1]):
            yield i, tuple(coord)
    elif g.geom_type == "MultiPolygon":
        idx = 0
        for poly in g.geoms:
            for coord in poly.exterior.coords[:-1]:
                yield idx, tuple(coord)
                idx += 1
    # Interior rings (holes) are not editable markers; intentionally skipped.


def _rings_with_index(geometry: Any) -> List[Tuple[int, LineString]]:
    """List of (poly_index, exterior-ring LineString) for a Polygon/MultiPolygon."""
    g = _as_shapely(geometry)
    if g is None:
        return []
    if g.geom_type == "Polygon":
        return [(0, g.exterior)]
    if g.geom_type == "MultiPolygon":
        return [(i, poly.exterior) for i, poly in enumerate(g.geoms)]
    return []


def coord_at_index(geometry: Any, index: int) -> Optional[Tuple[float, float]]:
    """Resolve a flat vertex index back to its (x, y) coordinate."""
    for i, coord in iter_vertices(geometry):
        if i == index:
            return coord
    return None


def ring_of_index(geometry: Any, index: int) -> Optional[Tuple[int, int]]:
    """Resolve a flat vertex index to (poly_index, ring_vertex_index).

    ``ring_vertex_index`` counts vertices within the ring starting at 0
    (not counting the closing duplicate).  Used to build drag deltas per ring.
    """
    g = _as_shapely(geometry)
    if g is None:
        return None
    poly_rings: List[List[Tuple[float, float]]] = []
    if g.geom_type == "Polygon":
        poly_rings = [list(g.exterior.coords[:-1])]
    elif g.geom_type == "MultiPolygon":
        for poly in g.geoms:
            poly_rings.append(list(poly.exterior.coords[:-1]))
    flat = 0
    for pi, ring in enumerate(poly_rings):
        for vi, _coord in enumerate(ring):
            if flat == index:
                return (pi, vi)
            flat += 1
    return None


def boundary_of(geom: Any) -> Optional[Any]:
    """The boundary (edge linework) of a polygon geometry.

    Used for both shared detection (neighbour boundary) and shell detection
    (parent boundary): point-to-line distance within tolerance.
    """
    g = _as_shapely(geom)
    if g is None:
        return None
    try:
        b = g.boundary
        return b if b is not None and not b.is_empty else None
    except Exception:
        logger.exception(
            "boundary extraction failed - no vertex of this geometry can be "
            "matched against a neighbour"
        )
        return None


class VertexClassifier:
    """Classifies vertices of one feature against same-level neighbours + shell."""

    def __init__(
        self,
        layer_type: str,
        same_level_features: Sequence[Any],
        parent_shell: Any = None,
        tolerance_m: float = VERTEX_COINCIDENCE_TOLERANCE_M,
    ):
        self.layer_type = layer_type
        self.parent_shell = _as_shapely(parent_shell)
        self.tol_deg = _metres_to_degrees(tolerance_m)
        # Grid index of same-level neighbour boundaries (bbox pre-filter).
        self.index = SpatialHashIndex()
        for feat in same_level_features:
            geom = feat.get("geometry") if isinstance(feat, dict) else feat
            g = _as_shapely(geom)
            if g is None:
                continue
            b = boundary_of(g)
            if b is None:
                continue
            fid = feat.get("id") if isinstance(feat, dict) else getattr(feat, "id", None)
            self.index.insert(str(fid or "n"), b)

    def _is_on_boundary(self, pt: Point, boundary: Any) -> bool:
        try:
            return pt.distance(boundary) <= self.tol_deg
        except Exception:
            # False means "not on the boundary", which marks a shared vertex as
            # unshared - and an unshared vertex is locked against editing.
            logger.exception(
                "boundary proximity test failed - the vertex is classified as "
                "unshared, and so will be locked"
            )
            return False

    def _is_on_parent_shell(self, pt: Point) -> bool:
        if self.parent_shell is None:
            return False
        b = boundary_of(self.parent_shell)
        if b is None:
            return False
        return self._is_on_boundary(pt, b)

    def classify(self, geometry: Any) -> Dict[str, List[int]]:
        g = _as_shapely(geometry)
        if g is None:
            return {"shared": [], "shell": [], "editable": [], "vertex_count": 0}

        if self.layer_type == BOUNDARY_LAYER:
            # Rule A: the forest boundary has no shell and no same-level
            # neighbours — fully editable (caller gates on no-structure).
            verts = [i for i, _ in iter_vertices(g)]
            return {"shared": [], "shell": [], "editable": verts, "vertex_count": len(verts)}

        shared: List[int] = []
        shell: List[int] = []

        for i, coord in iter_vertices(g):
            pt = Point(coord)
            if self._is_on_parent_shell(pt):
                shell.append(i)
            # shared: within tolerance of a same-level neighbour's boundary
            # (independent of shell — a junction on the shell is BOTH).
            is_shared = False
            for cand in self.index.neighbor_candidates(pt):
                if self._is_on_boundary(pt, cand):
                    is_shared = True
                    break
            if is_shared:
                shared.append(i)

        editable = [i for i in shared if i not in shell]
        return {
            "shared": shared,
            "shell": shell,
            "editable": editable,
            "vertex_count": len([i for i, _ in iter_vertices(g)]),
        }


def classify_vertices(
    geometry: Any,
    layer_type: str,
    same_level_features: Sequence[Any],
    parent_shell: Any = None,
    tolerance_m: float = VERTEX_COINCIDENCE_TOLERANCE_M,
) -> Dict[str, List[int]]:
    """Classify every vertex of ``geometry`` (single-shot convenience).

    Args:
        geometry: GeoJSON dict or shapely Polygon/MultiPolygon to classify.
        layer_type: one of ``boundary``, ``blocks``, ``compartments``,
            ``sub_compartments``.
        same_level_features: iterable of same-level sibling features (the
            edited feature itself should be EXCLUDED).  Each item is a dict
            (``{"id", "geometry"}``) or a shapely geometry.
        parent_shell: the enclosing shell geometry (blocks → boundary geom;
            compartments → parent block; sub-compartments → parent
            compartment).  ``None`` → no shell (only the boundary layer).
        tolerance_m: point-on-line tolerance in metres (default
            ``VERTEX_COINCIDENCE_TOLERANCE_M``).  NOT the neighbour search
            radius ``MAX_EDGE_TOLERANCE_M`` — see that constant's note.

    Returns:
        ``{"shared": [flat indices], "shell": [flat indices],
        "editable": [flat indices], "vertex_count": n}``.
    """
    return VertexClassifier(
        layer_type=layer_type,
        same_level_features=list(same_level_features),
        parent_shell=parent_shell,
        tolerance_m=tolerance_m,
    ).classify(geometry)
