"""One workspace feature = one row = one selectable shape on the map.

`ForestBlock` and `ForestSubArea` rows are the things a user clicks on the
map, or a row in the attribute table — they must always be in exact 1:1
correspondence. A row whose `geometry` is a MultiPolygon breaks that: it
draws as several disjoint shapes but is one row, so clicking any one of them
selects all of them, and the attribute table shows only one row for what
looks like several features (or vice versa: several attribute rows fight
over the same click target if a MultiPolygon leaks into a layer keyed by a
single id). This is exactly the corruption pattern found in महाभारत
Compartment-13 (2026-09-12): a cut/divide operation bundled 2 real polygons
plus 16 degenerate numerical-noise slivers into one MultiPolygon row.

Any code path that persists a *single* feature (one `ForestBlock` row, one
`ForestSubArea` row) must hand this module a genuinely single-part geometry.
A caller that legitimately produces N disjoint pieces from one input (a cut,
a divide, an Auto-Block commit, a boundary-to-blocks split) must explode
first and create one row per piece — `explode_and_filter_slivers` is the
shared helper for that. `ensure_single_polygon` is the last-line invariant
guard, wired into the ORM models themselves (see the `@validates('geometry')`
hooks in `forest_block.py` / `forest_sub_area.py`) so a future write path
that skips the explode step fails loudly at commit time instead of silently
persisting corrupt data.
"""
import logging
from typing import Any, List

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.validation import make_valid

from .geometry_utils import calculate_area_geodesic_from_shapely

logger = logging.getLogger(__name__)

# Same floor used across the auto-block/cut/divide pipelines: a fragment
# under this many m^2 is floating-point residue from a buffer/union/
# intersection op (thousandths of a m^2, sometimes with real perimeter), not
# a real piece of ground — never persisted as a row of its own.
DEGENERATE_SLIVER_M2 = 1.0


class MultiPartFeatureError(ValueError):
    """A single-feature write was handed >1 substantial disjoint polygon.

    The caller needs to create one row per part (see
    `explode_and_filter_slivers`) instead of collapsing them into one
    MultiPolygon row.
    """


def _area_m2(geom) -> float:
    try:
        sqm, _ = calculate_area_geodesic_from_shapely(geom)
        return float(sqm or 0.0)
    except Exception:
        logger.warning(
            "geodesic area failed - falling back to a planar approximation "
            "that overstates area", exc_info=True,
        )
        return float(geom.area) * (111_320.0 ** 2)


def strip_degenerate_holes(poly: Polygon, min_area_m2: float = DEGENERATE_SLIVER_M2) -> Polygon:
    """Drop any interior ring (hole) under `min_area_m2` — the interior-ring
    counterpart of the exterior-part filtering the rest of this module does.

    A buffer round-trip on an already-complex polygon (found live,
    2026-09-12: the merge "point-touch glue" on a महाभारत compartment that
    had already been through several prior merges) can leave sub-mm²
    interior rings as pure numerical noise from `make_valid`'s repair — each
    with a handful of real vertices and therefore a real (if tiny)
    perimeter, so it still renders as a visible seam/notch on the map
    despite enclosing no real area, even though the polygon itself is
    perfectly valid and simple (no self-intersection at all — this is not
    the multi-part/self-touch problem the rest of this module guards
    against, so it wasn't caught by any existing check).
    """
    if not poly.interiors:
        return poly
    kept = [ring for ring in poly.interiors if _area_m2(Polygon(ring)) >= min_area_m2]
    if len(kept) == len(poly.interiors):
        return poly
    return Polygon(poly.exterior, kept)


def _polygon_parts(geom) -> List[Polygon]:
    """Recursively pull every `Polygon` out of `geom`, dropping `Point`/
    `LineString`/`LinearRing` members.

    `shapely.validation.make_valid` on a self-touching or near-degenerate
    geometry (exactly what independent per-piece smoothing can leave along
    a shared boundary before a merge) does not always return a `Polygon` or
    `MultiPolygon` — it can return a `GeometryCollection` mixing the real
    polygon with a zero-area `LineString`/`Point` repair remnant. That
    remnant is geometric noise from the repair itself, not a piece of
    ground, and dropping it here (rather than only handling `MultiPolygon`)
    is what lets a genuinely-adjoining merge succeed instead of raising.

    Every extracted `Polygon` also gets `strip_degenerate_holes` applied —
    the same repair pass that can leave a stray exterior remnant can equally
    leave a degenerate interior ring on an otherwise perfectly valid part.
    """
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [strip_degenerate_holes(geom)]
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        parts: List[Polygon] = []
        for part in geom.geoms:
            parts.extend(_polygon_parts(part))
        return parts
    return []


def explode_and_filter_slivers(
    raw_pieces: List[Any], min_area_m2: float = DEGENERATE_SLIVER_M2
) -> List[Polygon]:
    """Explode any MultiPolygon/GeometryCollection in `raw_pieces` into its
    constituent polygons and drop anything under `min_area_m2` as
    numerical noise.

    Use this whenever a code path legitimately produces N pieces from one
    input and must persist one row per real piece.
    """
    flat: List[Polygon] = []
    for p in raw_pieces:
        if p is None or p.is_empty:
            continue
        p = make_valid(p)
        for part in _polygon_parts(p):
            if _area_m2(part) < min_area_m2:
                continue
            flat.append(part)
    return flat


def ensure_single_polygon(geom, min_area_m2: float = DEGENERATE_SLIVER_M2) -> Polygon:
    """Collapse degenerate-sliver noise around `geom` automatically, but
    raise `MultiPartFeatureError` if it genuinely contains more than one
    substantial disjoint part.

    This is the guard a single-row write path should call right before
    persisting — it silently fixes the "one real polygon + noise slivers"
    shape (the common accidental byproduct of a buffer/union op), and fails
    loudly on the "actually N real pieces" shape, which is a bug at the
    call site, not something a single-value guard can repair by itself.

    The already-correct, overwhelmingly common case (a plain single
    `Polygon` with no holes) returns `geom` itself, unchanged, with no
    `make_valid`/area/WKB round-trip on every ordinary write — this guard
    exists to catch Multi* bundling, not to re-run the sliver-floor policies
    each pipeline already applies to its own single-polygon output before
    persisting. A polygon that does carry holes always gets
    `strip_degenerate_holes` checked (cheap: an empty `.interiors` short-
    circuits immediately), since a degenerate hole can appear on an
    otherwise perfectly valid, single-part polygon — the fast path above
    would otherwise never see it.
    """
    if isinstance(geom, Polygon) and not geom.is_empty:
        return strip_degenerate_holes(geom, min_area_m2)
    parts = explode_and_filter_slivers([geom], min_area_m2)
    if not parts:
        raise ValueError(
            "geometry has no substantial area after removing degenerate "
            f"slivers (< {min_area_m2} m^2)"
        )
    if len(parts) > 1:
        areas = sorted((round(_area_m2(p), 2) for p in parts), reverse=True)
        raise MultiPartFeatureError(
            f"geometry has {len(parts)} disjoint substantial parts "
            f"(areas m^2: {areas}) but only one row is being created for "
            "it -- explode into one row per part (see "
            "explode_and_filter_slivers) instead of persisting them as one "
            "MultiPolygon row"
        )
    return parts[0]
