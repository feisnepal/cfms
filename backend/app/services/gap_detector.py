"""Neighbour-overlap AND neighbour-gap detection for a proposed forest boundary.

Complements ``overlap_resolver`` (which clips/snaps OVERLAPS so a new forest
never claims an adjoining community forest's land). This module additionally
detects, per adjoining forest:

  - the OVERLAP polygon  (proposed ∩ neighbour) and its area,
  - the GAP polygon      (the unclaimed band lying BETWEEN the proposed
                          boundary and the neighbour's boundary) and its area,
  - the gap SHAPE         ``ribbon`` (long slender sliver - looks like part of a
                          community forest) vs ``island`` (compact blob - looks
                          like private land) vs ``mixed``,
  - the gap SIZE class    ``small`` / ``medium`` / ``large``.

It is the geometric engine the boundary-overlap preview feeds on.  No
mutations, no DB access, no owner filtering - the caller hands in the
neighbourhood already gathered across all owners (``_get_nearby_forests``) and
consumes the returned per-neighbour relationships for the UI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from shapely.geometry import Polygon
from shapely.validation import make_valid

from ..core.constants import SQM_PER_HA

logger = __import__("logging").getLogger(__name__)


def _utm_transformers(geom):
    """Return (fwd, inv) transform callables between 4326 and ``geom``'s UTM zone."""
    from pyproj import Transformer
    from ..core.geo import calculate_utm_epsg

    c = geom.centroid
    epsg = calculate_utm_epsg(c.x, c.y)
    fwd = Transformer.from_crs(4326, epsg, always_xy=True).transform
    inv = Transformer.from_crs(epsg, 4326, always_xy=True).transform
    return fwd, inv


def _to_utm(geom):
    """Project a 4326 lon/lat geometry to its local UTM zone (metres)."""
    from shapely.ops import transform as _t

    fwd, _ = _utm_transformers(geom)
    return _t(fwd, geom)


def _medial_width_from_utm(g) -> float:
    """Twice the largest inward erosion a metric polygon survives = corridor width.

    A bounding-box short side over-reads for bent/curved strips (an L-shaped 50 m
    corridor has a huge bbox).
    """
    if g is None or g.is_empty or g.area <= 0:
        return 0.0
    lo, hi = 0.0, max(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1]) / 2.0 + 1.0
    for _ in range(24):  # ~1e-6 m precision over any realistic gap
        mid = (lo + hi) / 2.0
        if g.buffer(-mid).is_empty:
            hi = mid
        else:
            lo = mid
    return round(hi * 2.0, 2)


def _medial_width_m(gap_poly) -> float:
    """Medial width (m) of a 4326 gap polygon — projects to UTM first."""
    if gap_poly is None or gap_poly.is_empty:
        return 0.0
    try:
        return _medial_width_from_utm(_to_utm(gap_poly))
    except Exception:  # pragma: no cover - defensive
        logger.warning(
            "medial-width computation failed for a gap polygon - treated "
            "as width 0", exc_info=True,
        )
        return 0.0


def classify_gap_action(
    gap_shape: str,
    width_m: float,
    gap_ha: float,
    adjacent: bool,
    params: "GapParams",
) -> str:
    """Map a detected gap to a handling action — see GAP_HANDLING_PLAN.md.

    ``snap``   sliver, close automatically onto the shared edge.
    ``absorb`` ribbon within the width + area caps, pre-ticked to merge into
               the uploaded forest.
    ``offer``  ribbon over a cap, or an island/blob (possible private land) —
               shown un-ticked for a deliberate choice.
    ``report`` too wide / non-adjacent — listed only, no control.
    """
    if not adjacent or gap_shape == "none":
        return "report"
    if width_m <= params.sliver_width_m:
        return "snap"
    if width_m > params.large_size_m:
        return "report"
    if (
        gap_shape == "ribbon"
        and width_m <= params.absorb_max_width_m
        and gap_ha <= params.absorb_max_ha
    ):
        return "absorb"
    return "offer"


# ~1 m of latitude in degrees. Used ONLY to turn the metre `adjacency` gate into
# a degree tolerance for the corridor search, which stays in 4326 (native lon/lat
# where the polygons are clean and the convex-hull algorithm is well-behaved —
# projecting first introduces numerical slivers between edge-sharing forests).
# Every AREA / WIDTH / SHAPE / SIZE figure is measured on the UTM projection.
DEG_PER_M = 1.0 / 111_320.0

#: A gap strip thinner than this (m, medial) is a projection/topology artifact
#: between two forests that really share an edge — not a gap. Discarded.
_MIN_GAP_WIDTH_M = 0.5


def _env_float(key: str, default: float) -> float:
    return float(os.environ.get(key, str(default)))


@dataclass
class GapParams:
    #: Max width (m) of a band that still counts as one shared-edge adjacency
    #: rather than "two separate forests".  Neighbours whose nearest edges sit
    #: within this are retained for gap analysis; further ones are dropped.
    adjacency_m: float = field(
        default_factory=lambda: _env_float("BOUNDARY_ADJACENCY_M", 25.0)
    )
    #: Bounding-box aspect ratio above which a gap is classified a ribbon.
    ribbon_ratio: float = field(
        default_factory=lambda: _env_float("BOUNDARY_RIBBON_RATIO", 3.0)
    )
    #: Linear extent (m) below which a gap is "small", above which "large".
    small_size_m: float = field(
        default_factory=lambda: _env_float("BOUNDARY_GAP_SMALL_M", 30.0)
    )
    large_size_m: float = field(
        default_factory=lambda: _env_float("BOUNDARY_GAP_LARGE_M", 300.0)
    )
    #: A gap remnant smaller than this (ha) is dropped - matches the fragment
    #: floor the overlap resolver applies to clipped remnants.
    min_fragment_ha: float = field(
        default_factory=lambda: _env_float("BOUNDARY_MIN_FRAGMENT_HA", 0.1)
    )
    #: Medial width (m) at or below which a gap is a survey-noise sliver and is
    #: snapped onto the shared edge automatically.
    sliver_width_m: float = field(
        default_factory=lambda: _env_float("BOUNDARY_GAP_SLIVER_WIDTH_M", 5.0)
    )
    #: Ribbon gaps up to this medial width (m) are pre-ticked to absorb into the
    #: uploaded forest; wider ribbons are only offered.
    absorb_max_width_m: float = field(
        default_factory=lambda: _env_float("BOUNDARY_GAP_ABSORB_MAX_WIDTH_M", 50.0)
    )
    #: Absorb is also capped by area (ha) - a very long thin ribbon can still be
    #: large; above this the user must opt in.
    absorb_max_ha: float = field(
        default_factory=lambda: _env_float("BOUNDARY_GAP_ABSORB_MAX_HA", 5.0)
    )


@dataclass
class NeighbourRelation:
    """One adjoining forest's overlap + gap relationship to the proposed boundary."""

    id: str
    name: Optional[str]
    name_np: Optional[str]
    overlap_polygon: Optional[Polygon]  # proposed ∩ neighbour (None if none)
    overlap_ha: float
    gap_polygon: Optional[Polygon]  # unclaimed band between (None if none)
    gap_ha: float
    gap_shape: str  # "none" | "ribbon" | "island" | "mixed"
    gap_size: str  # "none" | "small" | "medium" | "large"
    adjacent: bool
    gap_width_m: float = 0.0  # medial (narrow) width of the gap strip
    gap_action: str = "report"  # "snap" | "absorb" | "offer" | "report"


def _classify_height_width(gap: Polygon) -> tuple:
    minx, miny, maxx, maxy = gap.bounds
    width = max(maxx - minx, 1e-9)
    height = max(maxy - miny, 1e-9)
    return width, height


def _shape_of(gap: Polygon, ribbon_ratio: float) -> str:
    """Classify a gap polygon by elongation.

    ``long_side / short_side >= ribbon_ratio`` -> a long slender sliver, the
    signature of a strip that belongs to a community forest (``ribbon``).

    ``long_side / short_side <= compact_ratio`` -> roughly equidimensional, the
    signature of a compact patch that may be private land (``island``).

    Anything between the two is ``mixed``.
    """
    if gap.is_empty:
        return "none"
    width, height = _classify_height_width(gap)
    long_side, short_side = max(width, height), min(width, height)
    ratio = long_side / max(short_side, 1e-12)
    if ratio >= ribbon_ratio:
        return "ribbon"
    if ratio <= _COMPACT_RATIO:
        return "island"
    return "mixed"


#: Below this ``long/short`` ratio a gap is considered compact (island-like).
#: 1.5 separates a clearly elongated sliver from a roughly square patch.
_COMPACT_RATIO = 1.5


def _size_of(width_m: float, small_m: float, large_m: float) -> str:
    """Classify a gap by its true corridor width (metres).

    ``width_m`` is the medial width (``_medial_width_from_utm``), not a bbox
    extent — a bent / L-shaped strip has a bbox far wider than the strip itself.
    """
    if width_m <= 0:
        return "none"
    if width_m < small_m:
        return "small"
    if width_m > large_m:
        return "large"
    return "medium"


def _gap_between(
    proposed: Polygon, neighbour: Polygon, adjacency: float
) -> Optional[Polygon]:
    """Return the unclaimed band between ``proposed`` and ``neighbour``.

    Runs in native 4326 lon/lat (``adjacency`` is a degree tolerance); the
    caller measures the returned strip on a UTM projection.

    The corridor between two close, non-overlapping polygons is exactly:

        ``convex_hull(proposed ∪ neighbour) − proposed − neighbour``

    (the convex hull of both, minus the two polygons, leaves the strip between
    their facing edges).  It is further restricted to land within ``adjacency``
    of BOTH boundaries, so hull-fill around concave parts is not mistaken for a
    gap.  The largest remaining component is returned.
    """
    if adjacency <= 0 or proposed.is_empty or neighbour.is_empty:
        return None

    # Case (c): the pair can OVERLAP along part of the shared frontage and GAP
    # along another part (e.g. top + bottom overlap, centre gap).  The overlap is
    # resolved by clipping upstream, so here we subtract whatever the neighbour
    # already owns and look for the gap against the REMAINING proposed edge.
    trimmed_for_overlap = False
    if proposed.intersection(neighbour).area > 0:
        proposed = proposed.difference(neighbour)
        if proposed.is_empty:
            return None
        if not proposed.is_valid:
            proposed = make_valid(proposed)
        if proposed.geom_type == "MultiPolygon":
            # The gap corridor is evaluated against one facing edge; keep the
            # largest remaining piece.
            proposed = max(proposed.geoms, key=lambda p: p.area)
        trimmed_for_overlap = True

    # The two forests must actually be ADJACENT (their facing edges within the
    # adjacency band); otherwise the convex-hull corridor is just the long gap
    # between two unrelated forests, which is not a shared-boundary puzzle.
    if proposed.distance(neighbour) > adjacency:
        return None

    hull = proposed.union(neighbour).convex_hull
    if hull.is_empty:
        return None

    corridor = hull.difference(proposed.union(neighbour))
    if corridor.is_empty:
        return None
    if not corridor.is_valid:
        corridor = make_valid(corridor)

    if corridor.geom_type == "MultiPolygon":
        parts = list(corridor.geoms)
    else:
        parts = [corridor]

    nbuf = neighbour.buffer(adjacency) if trimmed_for_overlap else None
    kept: List[Polygon] = []
    for part in parts:
        if part.is_empty:
            continue
        near_both = (
            part.distance(proposed) <= adjacency
            and part.distance(neighbour) <= adjacency
        )
        if not near_both:
            continue
        if trimmed_for_overlap:
            # After subtracting the neighbour, the convex-hull corridor also
            # contains any RE-ENTRANT NOTCH of the trimmed proposal (bounded by
            # its own two edges, not by the neighbour).  A genuine
            # between-forests gap instead hugs the neighbour's edge — most of its
            # area sits within the adjacency band of the neighbour.
            if part.area <= 0 or part.intersection(nbuf).area / part.area < 0.6:
                continue
        kept.append(part)

    if not kept:
        return None
    kept.sort(key=lambda p: p.area, reverse=True)
    return kept[0]


def detect_relations(
    proposed_geom: dict,
    neighbours: list,
    params: Optional[GapParams] = None,
) -> List[NeighbourRelation]:
    """Per-neighbour overlap + gap detection.

    Parameters
    ----------
    proposed_geom : dict
        GeoJSON geometry dict (Polygon or MultiPolygon) for the proposed boundary.
    neighbours : list
        Adjoining forests; each needs a ``boundary_geom`` (shapely/geoalchemy)
        attribute, plus ``id`` / ``forest_name`` / ``name`` / ``name_np``.
    params : GapParams, optional
        Overridable parameters; defaults to ``GapParams()``.

    Returns
    -------
    list[NeighbourRelation]
        One entry per neighbour that OVERLAPS or shares an ADJACENT edge with
        the proposed boundary (truly separate forests are omitted).
    """
    if params is None:
        params = GapParams()

    if isinstance(proposed_geom, dict):
        from shapely.geometry import shape as _shape

        if not proposed_geom or not proposed_geom.get("type"):
            return []
        try:
            poly = _shape(proposed_geom)
        except Exception:  # pragma: no cover - defensive
            logger.warning(
                "gap detection: proposed_geom could not be parsed as a "
                "shapely geometry - reporting no gaps", exc_info=True,
            )
            return []
    else:
        poly = proposed_geom
    if poly is None or poly.is_empty:
        return []
    if not poly.is_valid:
        poly = make_valid(poly)

    # The corridor search stays in 4326 (clean rectangles, well-behaved convex
    # hull). Every AREA / WIDTH / SHAPE / SIZE figure is measured on the local
    # UTM projection so it is true metres — bare degree maths over-reads
    # east-west by ~12% at Nepal's latitude.
    from shapely.ops import transform as _t

    try:
        _fwd, _ = _utm_transformers(poly)
    except Exception:  # pragma: no cover - defensive
        logger.exception("gap-detector: projection failed; no relations reported")
        return []

    def _utm(g):
        gm = _t(_fwd, g)
        return gm if gm.is_valid else make_valid(gm)

    adjacency_deg = params.adjacency_m * DEG_PER_M

    results: List[NeighbourRelation] = []
    for f in neighbours:
        geom = getattr(f, "boundary_geom", None) or getattr(f, "geometry", None)
        if geom is None:
            continue
        try:
            if hasattr(geom, "__geo_interface__"):
                from shapely.geometry import shape as _shape

                eg = _shape(geom.__geo_interface__)
            elif isinstance(geom, dict):
                from shapely.geometry import shape as _shape

                eg = _shape(geom)
            else:
                # geoalchemy2 WKBElement (or a raw WKB bytes/hex): materialise
                # into a shapely shape before any geometric method is called.
                from shapely import wkb
                from geoalchemy2 import WKBElement

                if isinstance(geom, WKBElement):
                    eg = wkb.loads(bytes(geom.data))
                elif isinstance(geom, (bytes, bytearray)):
                    eg = wkb.loads(bytes(geom))
                else:
                    # fallback: try the SQLAlchemy geometry helper
                    from geoalchemy2.shape import to_shape as _to_shape

                    eg = _to_shape(geom)
            if not eg.is_valid:
                eg = make_valid(eg)
            if eg.is_empty:
                continue
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "gap-detector: skipping neighbour %s: %s", getattr(f, "id", "?"), exc
            )
            continue

        fid = str(getattr(f, "id", ""))
        name = str(getattr(f, "forest_name", getattr(f, "name", "")) or "") or None
        name_np = str(getattr(f, "name_np", "") or "") or None

        # -- overlap (measured in metres) ------------------------------------
        overlap_polygon = None
        overlap_ha = 0.0
        try:
            inter = poly.intersection(eg)
            if not inter.is_empty:
                overlap_polygon = inter if inter.geom_type == "Polygon" else None
                if inter.geom_type == "MultiPolygon":
                    # proposed crosses the neighbour in several places — report
                    # the largest piece for the overlay, the combined area below.
                    biggest = max(inter.geoms, key=lambda g: g.area)
                    if biggest.geom_type == "Polygon":
                        overlap_polygon = biggest
                overlap_ha = _utm(inter).area / SQM_PER_HA
        except Exception:  # pragma: no cover - defensive
            logger.exception("gap-detector: overlap measurement failed for %s", fid)

        # -- gap: search in 4326, measure in metres -------------------------
        gap_polygon = _gap_between(poly, eg, adjacency_deg)
        gap_ha = 0.0
        gap_shape = "none"
        gap_size = "none"
        gap_width_m = 0.0
        gap_action = "report"
        if gap_polygon is not None:
            gap_m = _utm(gap_polygon)
            gap_ha = gap_m.area / SQM_PER_HA
            gap_width_m = _medial_width_from_utm(gap_m)
            if gap_width_m < _MIN_GAP_WIDTH_M:
                # A projection/topology sliver between two forests that really
                # share an edge — not a gap.
                gap_polygon = None
            elif gap_ha >= params.min_fragment_ha:
                gap_shape = _shape_of(gap_m, params.ribbon_ratio)
                gap_size = _size_of(
                    gap_width_m, params.small_size_m, params.large_size_m
                )
                gap_action = classify_gap_action(
                    gap_shape, gap_width_m, gap_ha, True, params
                )
            else:
                # Below the fragment floor -> pure survey noise, snap it shut.
                gap_action = "snap"

        adjacent = overlap_ha > 0 or gap_polygon is not None
        if not adjacent:
            continue

        results.append(
            NeighbourRelation(
                id=fid,
                name=name,
                name_np=name_np,
                overlap_polygon=overlap_polygon,
                overlap_ha=round(overlap_ha, 4),
                gap_polygon=gap_polygon,
                gap_ha=round(gap_ha, 4),
                gap_shape=gap_shape,
                gap_size=gap_size,
                adjacent=adjacent,
                gap_width_m=round(gap_width_m, 2),
                gap_action=gap_action,
            )
        )

    return results


__all__ = [
    "GapParams",
    "NeighbourRelation",
    "detect_relations",
    "classify_gap_action",
]
