"""Repair: give every unit made by an edit on an Auto-Block layer's unit that layer's id.

Before 2026-10-03, divide / cut / merge / paste on a unit that belonged to an Auto-Block layer made new rows
with NO layer (``raster_layer_id`` NULL). Those rows read as legacy structure: demoting the layer left them
visible as orphans, and the layer could no longer be promoted ("This forest already has blocks/compartments
created before layers existed"). New code now hands the layer down (``CHILD_INHERITED_COLUMNS``); this
script fixes rows that already exist.

A row is repaired when it has no layer and sits BELOW a row that has one (walking ``parent_block_id`` up to the
nearest layered ancestor). A top-level unit with no layered ancestor is left alone -- nothing says which layer
it belonged to (it is reported, not changed).

Dry run by default; nothing is written without ``--apply``. ``--apply`` writes a JSON file of every row it
changed, and ``--rollback FILE`` puts the layer id back to NULL for exactly those rows.

Usage (from ``backend/``):

    python scripts/backfill_layer_descendants.py                     # report only
    python scripts/backfill_layer_descendants.py --apply             # repair + write the undo file
    python scripts/backfill_layer_descendants.py --rollback FILE     # undo a previous --apply
    python scripts/backfill_layer_descendants.py --calc <calculation id> [--apply]   # one forest only
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

logging.disable(logging.INFO)

from app.core.database import SessionLocal  # noqa: E402

_FIND = """
WITH RECURSIVE t AS (
    SELECT id, raster_layer_id AS layer
    FROM forest_blocks
    WHERE raster_layer_id IS NOT NULL
    UNION ALL
    SELECT c.id, t.layer
    FROM forest_blocks c
    JOIN t ON c.parent_block_id = t.id
    WHERE c.raster_layer_id IS NULL
)
SELECT b.id::text AS id, b.calculation_id::text AS calc, b.name, b.division_level,
       t.layer::text AS layer, l.name AS layer_name, l.promoted_as
FROM t
JOIN forest_blocks b ON b.id = t.id
JOIN raster_layers l ON l.id = t.layer
WHERE b.raster_layer_id IS NULL
  AND (CAST(:calc AS text) IS NULL OR b.calculation_id::text = CAST(:calc AS text))
ORDER BY b.calculation_id, b.division_level, b.name
"""

_ORPHAN_TOP = """
SELECT b.calculation_id::text, count(*)
FROM forest_blocks b
WHERE b.raster_layer_id IS NULL AND b.parent_block_id IS NULL
  AND EXISTS (SELECT 1 FROM raster_layers l WHERE l.calculation_id = b.calculation_id)
GROUP BY b.calculation_id
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback", metavar="FILE")
    ap.add_argument("--calc", metavar="ID")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.rollback:
            data = json.loads(Path(args.rollback).read_text(encoding="utf-8"))
            ids = [r["id"] for r in data["rows"]]
            for i in ids:
                db.execute(text("UPDATE forest_blocks SET raster_layer_id = NULL WHERE id = CAST(:i AS uuid)"), {"i": i})
            db.commit()
            print(f"rolled back {len(ids)} row(s) to no layer")
            return 0

        rows = db.execute(text(_FIND), {"calc": args.calc}).fetchall()
        if not rows:
            print("nothing to repair: no layer-less unit sits below a layered one")
        for r in rows:
            state = r.promoted_as or "trial (demoted)"
            print(f"  calc {r.calc[:8]}  {r.name:<12} depth {r.division_level}  -> layer '{r.layer_name}' [{state}]")
        print(f"{len(rows)} row(s) would be tagged with their ancestor's layer")

        tops = db.execute(text(_ORPHAN_TOP)).fetchall()
        if tops:
            print("note: forests with layers AND layer-less top-level units (left alone, nothing says which layer):")
            for c, n in tops:
                print(f"  calc {c[:8]}: {n} top-level unit(s) with no layer")

        if not args.apply:
            print("dry run -- nothing written (use --apply)")
            return 0
        if not rows:
            return 0

        undo = {
            "written": datetime.now().isoformat(timespec="seconds"),
            "rows": [{"id": r.id, "calc": r.calc, "layer": r.layer, "name": r.name} for r in rows],
        }
        undo_path = Path(f"backfill_layer_descendants_undo_{datetime.now():%Y%m%d_%H%M%S}.json")
        undo_path.write_text(json.dumps(undo, indent=2), encoding="utf-8")
        for r in rows:
            db.execute(
                text("UPDATE forest_blocks SET raster_layer_id = CAST(:l AS uuid) WHERE id = CAST(:i AS uuid) AND raster_layer_id IS NULL"),
                {"l": r.layer, "i": r.id},
            )
        db.commit()
        print(f"repaired {len(rows)} row(s); undo file: {undo_path.resolve()}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
