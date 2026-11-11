"""Re-label already-processed tree inventories with the forest's ACTIVE-stream top-level unit.

Why: before 2026-10-04 `InventoryService._update_tree_spatial_relationships` always labelled a
tree with the plain BLOCK it fell in, even on a compartment forest that still carried stale block
rows (the legacy MIXED shape). The analysis page then showed "Block-3" for trees that sit in
"ब्लक ४". New uploads are fixed at the source; this repairs the ones already stored.

Only `block_id` / `block_name` on trees of COMPARTMENT-stream forests are touched, and only for trees
that fall inside a top-level compartment. Derived data, re-derivable by re-processing.

    python scripts/backfill_inventory_unit_names.py                 # dry run, every forest
    python scripts/backfill_inventory_unit_names.py --calc <uuid>   # dry run, one forest
    python scripts/backfill_inventory_unit_names.py --calc <uuid> --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services.forest_units.mode import forest_stream  # noqa: E402
from app.services.forest_units.model import DEPTH_TOP_COMPARTMENT, Stream  # noqa: E402

# Trees whose stored label differs from the compartment they are actually in.
_CANDIDATES = f"""
    SELECT DISTINCT ON (t.id) t.id AS tree_id, fb.id AS unit_id, fb.name AS unit_name, t.block_name AS old_name
    FROM public.inventory_trees t
    JOIN public.forest_blocks fb
      ON fb.calculation_id = :calc
     AND fb.is_compartment = TRUE
     AND fb.division_level = {DEPTH_TOP_COMPARTMENT}
     AND ST_Intersects(t.location::geometry, fb.geometry)
    WHERE t.inventory_calculation_id = :inv
      AND (t.block_id IS DISTINCT FROM fb.id OR t.block_name IS DISTINCT FROM fb.name)
    ORDER BY t.id, fb.id
"""


_STALE_FILTER = """
    t.inventory_calculation_id = :inv
    AND t.block_id IN (SELECT id FROM public.forest_blocks WHERE calculation_id = :calc AND is_compartment = FALSE)
"""
_STALE_COUNT = "SELECT count(*) FROM public.inventory_trees t WHERE " + _STALE_FILTER
_STALE_RESET = (
    "UPDATE public.inventory_trees t SET block_id = NULL, "
    "block_name = (SELECT COALESCE(NULLIF(c.forest_name, ''), 'Unknown') FROM public.calculations c WHERE c.id = :calc) "
    "WHERE " + _STALE_FILTER
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calc", help="only this calculation (forest) id")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = ap.parse_args()

    db = SessionLocal()
    sql = "SELECT id, calculation_id FROM inventory_calculations WHERE calculation_id IS NOT NULL"
    params = {}
    if args.calc:
        sql += " AND calculation_id = :c"
        params["c"] = args.calc
    total = 0
    for inv in db.execute(text(sql), params).all():
        if forest_stream(db, inv.calculation_id) is not Stream.COMPARTMENT:
            continue
        rows = db.execute(text(_CANDIDATES), {"calc": str(inv.calculation_id), "inv": str(inv.id)}).all()
        # Trees in NO compartment that still point at a stale plain block: back to the placeholder a
        # fresh upload gives them (the forest's own name), instead of a block the map does not show.
        stale = db.execute(text(_STALE_COUNT), {"calc": str(inv.calculation_id), "inv": str(inv.id)}).scalar()
        if not rows and not stale:
            continue
        if stale:
            print(f"forest {inv.calculation_id}: {stale} tree(s) outside every compartment still labelled with a stale block")
            total += stale
            if args.apply:
                db.execute(text(_STALE_RESET), {"calc": str(inv.calculation_id), "inv": str(inv.id)})
                db.commit()
        if not rows:
            continue
        changes = {}
        for r in rows:
            key = (r.old_name, r.unit_name)
            changes[key] = changes.get(key, 0) + 1
        print(f"forest {inv.calculation_id}: {len(rows)} tree(s) to relabel")
        for (old, new), n in sorted(changes.items(), key=lambda kv: -kv[1]):
            print(f"    {old!r} -> {new!r}: {n}")
        total += len(rows)
        if args.apply:
            db.execute(
                text(f"""
                    UPDATE public.inventory_trees t
                    SET block_id = c.unit_id, block_name = c.unit_name
                    FROM ({_CANDIDATES}) c
                    WHERE t.id = c.tree_id
                """),
                {"calc": str(inv.calculation_id), "inv": str(inv.id)},
            )
            db.commit()
    print(("APPLIED" if args.apply else "DRY RUN (nothing written)") + f": {total} tree(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
