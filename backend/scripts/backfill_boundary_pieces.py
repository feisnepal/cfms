"""One-time backfill: give every existing forest's boundary its per-piece rows.

BOUNDARY_PIECES_PLAN.md D5 / P1. Migration 096 only creates the (empty)
`forest_boundary_pieces` table -- every forest that already has a
`calculations.boundary_geom` today (this includes बृन्दाबन) has zero piece rows
until this runs. For every calculation with a non-null `boundary_geom`, this
decomposes it into its constituent single-part polygons (a plain Polygon
becomes exactly one piece; a MultiPolygon becomes one piece per part) and
inserts one `forest_boundary_pieces` row per part, named "Piece 1"/"Piece
2"/... (D2's default). It never touches `boundary_geom` itself -- that value
is already correct and this script only adds identity beside it.

Idempotent: a calculation that already has >=1 piece row is skipped, so this
is safe to re-run (e.g. after a later run picks up newly-created forests that
had no boundary yet at the time of an earlier pass).

Usage (from `backend/`):

    ../venv/Scripts/python.exe scripts/backfill_boundary_pieces.py            # dry run (default) — prints what it WOULD insert
    ../venv/Scripts/python.exe scripts/backfill_boundary_pieces.py --apply    # actually inserts, commits

Exit status is always 0 on a clean run (this is a report/apply tool, not a
gate); a real error exits 1.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Forest names are Nepali/Devanagari; Windows terminals often default to a
# codepage (cp1252/cp437) that can't encode them, crashing a plain print().
# Force UTF-8 on stdout/stderr so this report always runs to completion.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse  # noqa: E402
import logging  # noqa: E402

logging.disable(logging.INFO)  # the dev engine echoes every statement; a report should be readable

from shapely import wkt as shapely_wkt  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.utils.geometry_utils import calculate_area_geodesic_from_shapely  # noqa: E402


def _parts_of(geom):
    """A Polygon is one piece; a MultiPolygon is one piece per part.
    Anything else (should not happen -- boundary_geom is always a
    Polygon/MultiPolygon by construction) is skipped, reported, not guessed at.
    """
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually insert rows and commit (default: dry run)")
    args = parser.parse_args()

    db = SessionLocal()
    inserted_total = 0
    skipped_already_has_pieces = 0
    skipped_unrecognised_geom_type = 0
    try:
        rows = db.execute(
            text(
                """
                SELECT c.id, c.forest_name, ST_AsText(c.boundary_geom) AS boundary_wkt
                FROM calculations c
                WHERE c.boundary_geom IS NOT NULL
                ORDER BY c.created_at
                """
            )
        ).fetchall()

        print(f"{len(rows)} calculation(s) have a boundary_geom.")

        existing_calc_ids = {
            row[0]
            for row in db.execute(
                text("SELECT DISTINCT calculation_id FROM forest_boundary_pieces")
            ).fetchall()
        }

        for calc_id, forest_name, boundary_wkt in rows:
            if calc_id in existing_calc_ids:
                skipped_already_has_pieces += 1
                continue

            geom = shapely_wkt.loads(boundary_wkt)
            parts = _parts_of(geom)
            if not parts:
                skipped_unrecognised_geom_type += 1
                print(f"  SKIP {calc_id} ({forest_name!r}): unrecognised geometry type {geom.geom_type!r}")
                continue

            for i, part in enumerate(parts, start=1):
                name = f"Piece {i}"
                _, area_ha = calculate_area_geodesic_from_shapely(part)
                if args.apply:
                    db.execute(
                        text(
                            """
                            INSERT INTO forest_boundary_pieces (id, calculation_id, name, geometry, area_hectares, created_at)
                            VALUES (:id, :calculation_id, :name, ST_SetSRID(ST_GeomFromText(:wkt), 4326), :area_hectares, now())
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "calculation_id": str(calc_id),
                            "name": name,
                            "wkt": part.wkt,
                            "area_hectares": area_ha,
                        },
                    )
                inserted_total += 1
            print(f"  {'INSERT' if args.apply else 'WOULD INSERT'} {len(parts)} piece(s) for {calc_id} ({forest_name!r})")

        if args.apply:
            db.commit()
            print(f"\nCommitted. Inserted {inserted_total} piece row(s).")
        else:
            db.rollback()
            print(f"\nDry run — would insert {inserted_total} piece row(s). Re-run with --apply to write them.")

        print(
            f"Skipped: {skipped_already_has_pieces} already had pieces, "
            f"{skipped_unrecognised_geom_type} had an unrecognised geometry type."
        )
        return 0
    except Exception:
        db.rollback()
        logging.disable(logging.NOTSET)
        logging.exception("backfill_boundary_pieces failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
