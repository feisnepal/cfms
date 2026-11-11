"""Read-only snapshot of how the app picks the units of every REAL forest (FS-0.5, live half).

The synthetic fixtures prove a phase on invented forests; this proves it did not change what the owner's real
forests (बृन्दाबन, चुरे, छिमेकी, बादल) return. It runs the same probes as ``tests/structure/golden.py`` against
``cf_db`` and writes one JSON file. Run it before and after each phase and compare.

It never changes anything: the connection is opened with ``default_transaction_read_only=on`` (the database
itself refuses a write), and the session is rolled back at the end.

Usage (from ``backend/``):

    ../venv/Scripts/python.exe scripts/structure_snapshot.py --out C:/Users/Admin/forest_backups/structure_before_P1a.json
    ../venv/Scripts/python.exe scripts/structure_snapshot.py --compare C:/Users/Admin/forest_backups/structure_before_P1a.json

``--compare`` re-snapshots and prints every probe whose answer differs from the saved file (exit 1 if any).
Forests are matched by name, never by id, so the output is stable across a re-import.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.disable(logging.INFO)  # the dev engine echoes every statement

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models.calculation import Calculation  # noqa: E402
from tests.structure import golden  # noqa: E402


def take_snapshot() -> dict:
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )
    db = sessionmaker(bind=engine)()
    out = {}
    try:
        for calc in (
            db.query(Calculation)
            .order_by(Calculation.forest_name, Calculation.created_at)
            .all()
        ):
            name = calc.forest_name or f"(unnamed {str(calc.id)[:8]})"
            key = name if name not in out else f"{name} [{str(calc.id)[:8]}]"
            out[key] = golden.snapshot(db, calc)
    finally:
        db.rollback()
        db.close()
        engine.dispose()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", help="write the snapshot to this file")
    ap.add_argument("--compare", help="compare a fresh snapshot with this saved one")
    args = ap.parse_args()

    current = take_snapshot()

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"snapshot of {len(current)} forest(s) written to {args.out}")

    if args.compare:
        saved = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        rc = 0
        for name in sorted(set(saved) | set(current)):
            if name not in saved or name not in current:
                print(f"{name}: present in only one snapshot")
                rc = 1
                continue
            unexpected, _ = golden.diff(saved[name], current[name], name, {"cells": {}})
            for probe, was, now in unexpected:
                print(
                    f"{name} / {probe}:\n  was {json.dumps(was, ensure_ascii=False)}\n  now {json.dumps(now, ensure_ascii=False)}"
                )
                rc = 1
        print("no differences" if rc == 0 else "DIFFERENCES FOUND")
        return rc

    if not args.out:
        print(json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
