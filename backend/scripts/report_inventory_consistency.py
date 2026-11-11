"""Read-only report of forests whose stored field inventory no longer matches their units (see
``app/services/field_inventory_consistency.py``). It never changes anything and never computes the inventory.

Usage (from ``backend/``):

    ../venv/Scripts/python.exe scripts/report_inventory_consistency.py            # every forest that has an inventory
    ../venv/Scripts/python.exe scripts/report_inventory_consistency.py <calc-id>  # one forest
    ../venv/Scripts/python.exe scripts/report_inventory_consistency.py --gate     # exit 1 when any ERROR is found (CI)

Warnings (a unit with no plot) are printed but never fail the gate: the inventory is incomplete there, not wrong.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services import field_inventory_consistency as fic  # noqa: E402


def main(argv: list[str]) -> int:
    logging.disable(logging.CRITICAL)
    gate = "--gate" in argv
    ids = [a for a in argv if not a.startswith("--")]
    db = SessionLocal()
    try:
        if ids:
            calcs = [(i, "") for i in ids]
        else:
            calcs = [(str(r[0]), r[1] or "") for r in db.execute(text(
                "SELECT c.id, c.forest_name FROM calculations c "
                "WHERE EXISTS (SELECT 1 FROM field_inventory_calculations f WHERE f.calculation_id = c.id) ORDER BY c.created_at"))]
        bad = 0
        for cid, name in calcs:
            found = fic.check(db, cid)
            label = name.encode("ascii", "replace").decode()
            if not found:
                print(f"{cid}  {label}  ok")
                continue
            if fic.has_errors(found):
                bad += 1
            print(f"{cid}  {label}")
            for f in found:
                print(f"    {f.severity:<8} {f.code:<22} {f.unit:<16} {f.message}")
        print(f"\n{bad} forest(s) with an inventory problem of {len(calcs)} checked.")
        return 1 if (gate and bad) else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
