"""Elevation as an always-on, read-only unit attribute (RASTER_SOURCES P2.5, RS-2.19).

D51 decided DEM leaves the carve-source list: its "Low/Mid/High" zones are the
forest's own 33rd/67th elevation percentiles, so every forest yields exactly 3
units with no cross-forest meaning, unlike slope bands, which carry real
operational meaning. DEM becomes an attribute instead -- absolute min/mean/max
metres, computed for every unit regardless of which source carved it, in one
statement rather than the one-query-per-piece pattern ``dominant_class`` uses.

Deliberately read-only: the class dropdowns (``dominant_slope_band`` etc.) are
the user's classification; elevation is a measurement, so there is nothing for
the user to set.

DEM's NoData sentinel is -32768 and is **not** registered in the raster
metadata, so an unfiltered ``ST_SummaryStats``/pixel aggregate on
``rasters.dem`` silently averages in NoData and reports elevations around
-21,470 m on a real boundary (verified 2026-09-29, plan rule 14, also guarded
in ``raster_class_vectorize.DEM_VALID_PREDICATE``). Every query here filters
explicitly rather than trusting the raster's own NoData band.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from .raster_coverage import table_exists

DEM_TABLE = "rasters.dem"

# Same bound as raster_class_vectorize.DEM_VALID_PREDICATE, restated here
# rather than imported: that constant is written for interpolation into a
# WHERE clause aliasing the column ``z``, and importing a string tied to a
# specific alias would be more fragile than one line duplicated with a
# comment pointing at the other.
_VALID_ELEVATION = "val > -32000 AND val >= 0 AND val <= 9000"


def dem_available(db: Session) -> bool:
    """Is ``rasters.dem`` installed on this deployment at all?"""
    return table_exists(db, DEM_TABLE)


def compute_elevation_for_blocks(
    db: Session, block_ids: Iterable[Any]
) -> Dict[str, Dict[str, Optional[float]]]:
    """Min/mean/max elevation (m) for each of ``block_ids``, in ONE statement.

    Returns ``{block_id_str: {"elevation_min_m", "elevation_mean_m",
    "elevation_max_m"}}``. A block with no DEM coverage (raster absent, or the
    piece falls entirely outside the raster's extent) is simply absent from
    the result -- callers leave those columns NULL rather than writing zeros.

    One ``CROSS JOIN LATERAL`` per block row, evaluated by Postgres inside a
    single round trip -- this is the "cheaper than the existing pattern"
    decision in RASTER_SOURCES_TRACKER.md P2.5 consequence 4: ``dominant_class``
    fires one ``ST_ValueCount`` query per piece (~30 for a single NASA
    preview); this fires one query total regardless of piece count.
    """
    ids = [str(b) for b in block_ids]
    if not ids or not dem_available(db):
        return {}

    query = text(
        f"""
        SELECT fb.id::text AS block_id,
               MIN(px.val) AS elevation_min,
               AVG(px.val) AS elevation_mean,
               MAX(px.val) AS elevation_max
        FROM public.forest_blocks fb
        CROSS JOIN LATERAL (
            SELECT (ST_PixelAsPolygons(ST_Clip(d.rast, fb.geometry, true), 1)).val AS val
            FROM {DEM_TABLE} d
            WHERE ST_Intersects(d.rast, fb.geometry)
        ) px
        WHERE fb.id = ANY((:ids)::uuid[]) AND {_VALID_ELEVATION}
        GROUP BY fb.id
        """  # noqa: S608 - DEM_TABLE is the module constant, never caller input
    )
    rows = db.execute(query, {"ids": ids}).fetchall()
    return {
        r.block_id: {
            "elevation_min_m": round(r.elevation_min, 1) if r.elevation_min is not None else None,
            "elevation_mean_m": round(r.elevation_mean, 1) if r.elevation_mean is not None else None,
            "elevation_max_m": round(r.elevation_max, 1) if r.elevation_max is not None else None,
        }
        for r in rows
    }


def apply_elevation(db: Session, blocks: Iterable[Any]) -> None:
    """Compute + write elevation onto each of ``blocks`` (``ForestBlock`` ORM
    rows), in place. A no-op (not even a query) when ``blocks`` is empty or
    ``rasters.dem`` is not installed. Does not commit -- the caller's own
    transaction covers it (matches ``commit_blocks``'s single commit at the
    end of its own unit of work).
    """
    rows = list(blocks)
    if not rows:
        return
    stats = compute_elevation_for_blocks(db, [r.id for r in rows])
    for row in rows:
        s = stats.get(str(row.id))
        if s is None:
            continue
        row.elevation_min_m = s["elevation_min_m"]
        row.elevation_mean_m = s["elevation_mean_m"]
        row.elevation_max_m = s["elevation_max_m"]


def _percentile(sorted_vals, p: float) -> float:
    """Linear-interpolated percentile over an already-sorted list (no numpy
    dependency for three numbers)."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (len(sorted_vals) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def assign_relative_elevation_zones(blocks: Iterable[Any]) -> None:
    """Set ``dominant_elevation_zone`` (1=Low, 2=Mid, 3=High) from each unit's
    OWN forest's 33rd/67th elevation-mean percentiles (D51/RS-2.19) -- a
    replacement for the pre-P2.5 mean +/- 1 SD scheme documented on the
    model column, which this decision supersedes. Only meaningful *relative
    to this forest*: comparing zone codes across two different forests is
    exactly the mistake the FRTC/D50 correction warned against, so the value
    is never presented without that caveat (frontend/label concern, not
    this function's).

    Units with no computed ``elevation_mean_m`` (no DEM coverage) are left
    with ``dominant_elevation_zone`` untouched. A forest with fewer than 2
    measured units has no meaningful spread, so every unit gets zone 2 (Mid)
    rather than an arbitrary tertile of one or zero points.
    """
    rows = [b for b in blocks if b.elevation_mean_m is not None]
    if not rows:
        return
    if len(rows) < 2:
        rows[0].dominant_elevation_zone = 2
        return
    means = sorted(float(r.elevation_mean_m) for r in rows)
    p33 = _percentile(means, 1 / 3)
    p67 = _percentile(means, 2 / 3)
    for r in rows:
        m = float(r.elevation_mean_m)
        r.dominant_elevation_zone = 1 if m <= p33 else (2 if m <= p67 else 3)


__all__ = [
    "DEM_TABLE",
    "dem_available",
    "compute_elevation_for_blocks",
    "apply_elevation",
    "assign_relative_elevation_zones",
]
