"""Read-only report of data that outlived its forest (work package FD, FD-13).

Owner's rule, 2026-09-21: if a forest is deleted, all data associated with it is deleted. This script
looks for the ways that rule can be broken and prints what it finds. It never changes anything.

It checks:
  1. every foreign key to ``calculations`` -- anything that is not ``ON DELETE CASCADE``;
  2. every table with a ``calculation_id`` column -- rows with a NULL or a dangling forest id
     (the documented exceptions in ``app/core/forest_delete_rules.py`` are listed separately, because
     they are kept on purpose);
  3. per-forest folders on disk (``uploads/maps_cache``, ``soil_erosion_cache``, ``hazard_vuln_cache``)
     whose forest no longer exists;
  4. yearly-plan lines / assignments that point at a sub-area which no longer exists.

Usage (from ``backend/``):

    ../venv/Scripts/python.exe scripts/report_orphans.py

Exit status is 0 when nothing but documented exceptions is found, 1 otherwise.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging  # noqa: E402

from sqlalchemy import text  # noqa: E402

logging.disable(
    logging.INFO
)  # the dev engine echoes every statement; a report should be readable

from app.core.database import SessionLocal  # noqa: E402
from app.core.forest_delete_rules import FOREST_DELETE_EXCEPTIONS  # noqa: E402

_RULES = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}


def main() -> int:
    problems = 0
    db = SessionLocal()
    try:
        print("== 1. Foreign keys to calculations that do not cascade")
        rows = db.execute(
            text(
                """
            SELECT c.conrelid::regclass::text, a.attname, c.confdeltype
            FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            WHERE c.contype = 'f' AND c.confrelid = 'public.calculations'::regclass AND c.confdeltype <> 'c'
            ORDER BY 1, 2
        """
            )
        ).fetchall()
        for table, col, rule in rows:
            print(f"   LEAK  {table}.{col} is {_RULES[rule]}")
        problems += len(rows)
        if not rows:
            print("   none")

        print("== 2. Rows with no forest, or a forest that is gone")
        tables = [
            r[0]
            for r in db.execute(
                text(
                    "SELECT DISTINCT table_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = 'calculation_id' ORDER BY 1"
                )
            ).fetchall()
        ]
        kept_on_purpose = []
        found_any = False
        for table in tables:
            n_null, n_dangling = db.execute(
                text(
                    f"SELECT count(*) FILTER (WHERE calculation_id IS NULL), "
                    f"count(*) FILTER (WHERE calculation_id IS NOT NULL AND NOT EXISTS "
                    f"(SELECT 1 FROM public.calculations x WHERE x.id = t.calculation_id)) "
                    f'FROM public."{table}" t'
                )
            ).one()
            if not (n_null or n_dangling):
                continue
            if table in FOREST_DELETE_EXCEPTIONS:
                kept_on_purpose.append((table, n_null, n_dangling))
                continue
            found_any = True
            problems += 1
            print(
                f"   LEAK  {table}: {n_null} with no forest, {n_dangling} with a forest that no longer exists"
            )
        if not found_any:
            print("   none")
        for table, n_null, n_dangling in kept_on_purpose:
            print(
                f"   (kept on purpose) {table}: {n_null} with no forest, {n_dangling} dangling -- "
                f"{FOREST_DELETE_EXCEPTIONS[table][:70]}..."
            )

        print("== 3. Per-forest folders on disk whose forest is gone")
        from app.services.management_plan_docx.plan_map_service import MAP_CACHE_DIR
        from app.services.operational_plan.landslide_susceptibility import (
            _CACHE_ROOT as HAZARD_ROOT,
        )
        from app.services.operational_plan.soil_erosion import _CACHE_ROOT as SOIL_ROOT

        live = {
            str(r[0])
            for r in db.execute(text("SELECT id FROM public.calculations")).fetchall()
        }
        stray = []
        for root in (Path(MAP_CACHE_DIR), Path(SOIL_ROOT), Path(HAZARD_ROOT)):
            if root.is_dir():
                stray += [
                    str(p) for p in root.iterdir() if p.is_dir() and p.name not in live
                ]
        for p in stray:
            print(f"   LEAK  {p}")
        problems += len(stray)
        if not stray:
            print("   none")
        print("== 4. Yearly-plan links to a sub-area that no longer exists")
        from app.services.sub_area_plan import orphaned_sub_area_links

        dangling = orphaned_sub_area_links(db)
        for d in dangling:
            print(f"   LEAK  forest {d['calculation_id']}: plan line {d['line_id']} ({d['via']}) -> sub-area {d['sub_area_id']}")
        problems += len(dangling)
        if not dangling:
            print("   none")
    finally:
        db.close()

    print("\nRESULT:", "clean" if problems == 0 else f"{problems} leak(s) found")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
