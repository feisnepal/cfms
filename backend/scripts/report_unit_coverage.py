"""Read-only report: do a forest's undivided units add up to its boundary? (SL-0)

Owner's rule, 2026-10-03: sub-compartment total = compartment total = forest outer-boundary area,
always. The Sub-compartment / Sub-block layer shows every unit that is not divided further, so for
a healthy forest those units tile the boundary exactly once. This script measures that for every
forest and prints the ones that do not. It never changes anything.

For each forest it reports (geodesic hectares):
  boundary     the forest outer boundary
  units        sum of the undivided, visible units (an unpromoted Auto-Block trial layer is not real
               structure and is left out, same filter as ``forest_units.queries.promoted_or_unlayered``)
  union        area of the units' union (``units`` > ``union`` means units overlap each other)
  outside      part of the units that lies outside the boundary
  gap          part of the boundary no unit covers

Usage (from ``backend/``):

    ../venv/Scripts/python.exe scripts/report_unit_coverage.py [--tolerance-pct 0.5]

Exit status is 0 when every forest matches within the tolerance, 1 otherwise. Repairs are a
per-forest owner decision; never edit the बृन्दाबन forest to make it pass.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

logging.disable(logging.INFO)  # the dev engine echoes every statement

from app.core.database import SessionLocal  # noqa: E402

_QUERY = text(
    """
    WITH leaf AS (
        SELECT b.*
        FROM forest_blocks b
        LEFT JOIN raster_layers r ON r.id = b.raster_layer_id
        WHERE (b.raster_layer_id IS NULL OR r.promoted_as IS NOT NULL)
          AND NOT EXISTS (SELECT 1 FROM forest_blocks c WHERE c.parent_block_id = b.id)
    ),
    agg AS (
        SELECT c.id, c.forest_name, c.boundary_geom,
               count(l.id) AS n_units,
               sum(ST_Area(l.geometry::geography)) AS units_sqm,
               ST_Union(l.geometry) AS u
        FROM calculations c
        JOIN leaf l ON l.calculation_id = c.id
        WHERE c.boundary_geom IS NOT NULL
        GROUP BY c.id, c.forest_name, c.boundary_geom
    )
    SELECT id::text, forest_name, n_units,
           ST_Area(boundary_geom::geography) / 10000.0 AS boundary_ha,
           units_sqm / 10000.0 AS units_ha,
           ST_Area(u::geography) / 10000.0 AS union_ha,
           ST_Area(ST_Difference(u, boundary_geom)::geography) / 10000.0 AS outside_ha,
           ST_Area(ST_Difference(boundary_geom, u)::geography) / 10000.0 AS gap_ha
    FROM agg
    ORDER BY forest_name NULLS LAST, id
    """
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tolerance-pct", type=float, default=0.5)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = db.execute(_QUERY).fetchall()
    finally:
        db.close()

    bad = 0
    print(f"{'status':6} {'forest':24} {'id':8} {'n':>3} {'boundary':>10} {'units':>10} "
          f"{'overlap':>8} {'outside':>8} {'gap':>8}")
    for r in rows:
        boundary, units, union = float(r.boundary_ha), float(r.units_ha), float(r.union_ha)
        outside, gap = float(r.outside_ha), float(r.gap_ha)
        overlap = max(units - union, 0.0)
        tol = boundary * args.tolerance_pct / 100.0
        ok = outside <= tol and gap <= tol and overlap <= tol
        bad += 0 if ok else 1
        print(
            f"{'OK' if ok else 'BAD':6} {(r.forest_name or '(unnamed)')[:24]:24} {r.id[:8]:8} "
            f"{r.n_units:>3} {boundary:>10.2f} {units:>10.2f} {overlap:>8.2f} {outside:>8.2f} {gap:>8.2f}"
        )
    print(f"\n{len(rows)} forest(s) with units, {bad} outside the {args.tolerance_pct}% tolerance.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
