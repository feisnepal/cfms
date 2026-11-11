"""Shared helper for generalizing raster-derived polygon boundaries.

A polygon vectorised straight off a raster (``ST_DumpAsPolygons`` in
PostGIS, ``rasterio.features.shapes`` in Python) traces the exact pixel
grid, so its boundary is a "staircase" of right-angle steps one pixel wide.
That reads as noisy at any zoom level where individual pixels are visible —
which is most of them, since Auto-Block pieces are typically much smaller
than the whole raster. ``ST_SimplifyPreserveTopology`` / ``shapely.simplify``
alone do **not** fix this: Douglas-Peucker only drops redundant collinear
vertices, it does not round corners, so a staircase simplified at any
tolerance is still a (coarser) staircase.

The fix used here is the standard GIS "buffer round-trip" smoothing trick:
a POSITIVE buffer with round joins, immediately followed by an equal
NEGATIVE buffer, also with round joins.

* The outward pass rounds every convex corner it touches (the "treads"
  sticking out of the staircase).
* The inward pass removes the extra area the outward pass added, while
  GEOS's round join also smooths the concave corners it touches on the way
  back in (the "risers" cut into the staircase).

Net effect: both flavours of staircase corner get rounded, the polygon ends
up close to its original size (buffer-out-then-in is approximately
area-neutral for a smooth shape), and a class boundary that was jagged
along one raster's pixel grid becomes a gentle curve — while the true,
digitized forest boundary is unaffected wherever a caller clips back to it
*after* smoothing (see ``slope_vectorize.draft_protection_polygon``, which
intersects with the boundary only once the smoothed geometry is built).

This is generalization, not reclassification: it only moves the carve line
between two already-decided classes (or, for ``draft_protection_polygon``,
the outline of an already-decided union of bands) by at most one smoothing
radius. It never changes which pixels belong to which class.

Choosing the radius: too small and the staircase is still visible; too
large and a genuinely narrow real feature (a slope band following a
ridge line, a canopy strip along a stream) gets eroded away by the inward
pass, since a shape narrower than ``2 * radius`` everywhere can vanish
entirely under this operation (the caller should treat that outcome — an
empty result — as "this was noise", not an error, matching every other
degrade-to-empty convention in this codebase's raster-generalization
callers). A radius of roughly 0.75-1.5x the source raster's native pixel
size is the usual sweet spot; each caller documents its own choice next to
its own pixel size.
"""

from __future__ import annotations

# Equatorial approximation, matching the existing convention already used
# for `_SIMPLIFY_DEG` in slope_vectorize.py / aspect_vectorize.py before
# this module existed. A smoothing radius does not need to be geodetically
# exact the way an area calculation does -- Nepal's latitude band (~27-30°N)
# makes this a slight over-estimate of true ground distance per degree of
# longitude, which only makes the chosen radius marginally more generous,
# never less.
_M_PER_DEG = 111_320.0


def meters_to_deg(meters: float) -> float:
    """Convert an approximate ground distance in metres to decimal degrees,
    for use as a buffer/simplify tolerance on EPSG:4326 geometry."""
    return float(meters) / _M_PER_DEG


__all__ = ["meters_to_deg"]
