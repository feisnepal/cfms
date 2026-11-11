"""Read-only report of forests whose units break the structure rules (see ``app/services/forest_units/invariants.py``).

Owner rules: a forest has blocks OR compartments, never both; the sub-units of a unit lie inside it, never overlap and
together cover it. This script looks for the forests that break them and prints what it finds. It never changes anything.

Besides the rules the funnel enforces, it prints one advisory line per forest: how the undivided (leaf) units compare with
the forest's outer boundary (hectares each, and the difference). Owner rule 2026-10-03: they are equal.

Usage (from ``backend/``):

    ../venv/Scripts/python.exe scripts/report_unit_structure.py            # every forest
    ../venv/Scripts/python.exe scripts/report_unit_structure.py <calc-id>  # one forest
    ../venv/Scripts/python.exe scripts/report_unit_structure.py --gate     # exit 1 on any violation (CI)

Exit status is 0 when nothing is found (or without ``--gate``), 1 otherwise.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services.forest_units import invariants  # noqa: E402

_LEAF_VS_BOUNDARY = text(
    """
    SELECT c.forest_name,
           ST_Area(c.boundary_geom::geography) / 10000.0 AS boundary_ha,
           COALESCE((SELECT SUM(ST_Area(b.geometry::geography)) FROM forest_blocks b
                     WHERE b.calculation_id = c.id AND b.child_count = 0), 0) / 10000.0 AS leaf_ha
    FROM calculations c WHERE c.id = :cid
    """
)


def main(argv: list[str]) -> int:
    logging.disable(logging.CRITICAL)
    gate = "--gate" in argv
    ids = [a for a in argv if not a.startswith("--")]
    db = SessionLocal()
    try:
        if ids:
            calcs = [(i, None) for i in ids]
        else:
            calcs = [(str(r[0]), r[1]) for r in db.execute(text("SELECT id, forest_name FROM calculations ORDER BY created_at"))]
        broken = 0
        for cid, name in calcs:
            vs = invariants.find_violations(db, cid)
            row = db.execute(_LEAF_VS_BOUNDARY, {"cid": cid}).first()
            label = (name or (row.forest_name if row else None) or "").encode("ascii", "replace").decode()
            if not vs and not (row and row.boundary_ha):
                continue
            advisory = ""
            if row and row.boundary_ha:
                diff = row.leaf_ha - row.boundary_ha
                advisory = f"  [leaf units {row.leaf_ha:.2f} ha vs boundary {row.boundary_ha:.2f} ha: {diff:+.2f}]"
            if vs:
                broken += 1
                print(f"{cid}  {label}{advisory}")
                for v in vs:
                    print(f"    {v.code:<30} {v.unit or '(forest)':<18} {v.message}")
            else:
                print(f"{cid}  {label}  ok{advisory}")
        print(f"\n{broken} forest(s) break a structure rule of {len(calcs)} checked.")
        return 1 if (gate and broken) else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
