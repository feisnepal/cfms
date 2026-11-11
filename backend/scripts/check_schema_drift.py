"""Schema-drift ratchet — fail on NEW model/migration divergence (task H1.11).

Why a ratchet rather than a clean gate
--------------------------------------
`alembic check` reports 221 differences between the models and a database built
from the migration chain. That is real, pre-existing drift: 84 indexes the
migrations create that no model declares, 24 columns likewise, 22 indexes
declared but never created, plus type, comment and constraint mismatches
accumulated across 84 revisions.

While that number is non-zero, `alembic check` cannot gate anything — a new
divergence is indistinguishable from the existing 221. Driving it to zero means
reconciling every model against the chain, and not always in the models' favour:
`boundary_disputes.forest_1_boundary` is declared `Geometry` but is `text` in
BOTH production and a fresh build, so the correct fix there is a migration, not
a model edit. That work needs judgement per case, not a sweep.

So: snapshot what is known, and fail on anything new. Same approach the plan
takes for lint (task 4.1). The baseline is expected to SHRINK; this script
reports when it does and refuses to let it grow.

Usage
-----
    python scripts/check_schema_drift.py            # compare against baseline
    python scripts/check_schema_drift.py --update   # re-snapshot (only to shrink)

Requires DATABASE_URL to point at a database built by `alembic upgrade head`.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

BACKEND = pathlib.Path(__file__).resolve().parent.parent
BASELINE = BACKEND / "alembic_drift_baseline.txt"

# "Detected sequence named 'x_id_seq' ... assuming SERIAL and omitting" is an
# informational note, not a difference — alembic logs it and moves on.
INFORMATIONAL = re.compile(r"Detected sequence named .* assuming SERIAL and omitting")


def collect() -> set[str]:
    """Run `alembic check` and return the set of reported differences."""
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=BACKEND, capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    found = set()
    for line in out.splitlines():
        if "Detected" not in line or INFORMATIONAL.search(line):
            continue
        # Strip the log prefix so the baseline is stable across log formats.
        found.add(line[line.index("Detected"):].strip())
    if not found and "Target database is not up to date" in out:
        sys.exit("Database is not at head — run `alembic upgrade head` first.")
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update", action="store_true",
                    help="Re-snapshot the baseline. Refuses to grow it.")
    args = ap.parse_args()

    current = collect()
    baseline = set()
    if BASELINE.exists():
        baseline = {l.strip() for l in BASELINE.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.startswith("#")}

    added = sorted(current - baseline)
    removed = sorted(baseline - current)

    if args.update:
        # Growth is refused once a baseline exists — that is the ratchet. The
        # very first snapshot is necessarily "growth" from nothing, so it is
        # allowed; every later one must shrink or hold.
        if added and BASELINE.exists():
            print("Refusing to update: the baseline would GROW by "
                  f"{len(added)} entries. Fix the drift instead:")
            for a in added[:20]:
                print(f"  + {a}")
            return 1
        BASELINE.write_text(
            "# Known model/migration drift (task H1.11). Expected to shrink.\n"
            "# Regenerate with: python scripts/check_schema_drift.py --update\n"
            + "\n".join(sorted(current)) + "\n", encoding="utf-8")
        print(f"Baseline updated: {len(current)} known differences "
              f"({len(removed)} resolved).")
        return 0

    if removed:
        print(f"{len(removed)} known difference(s) resolved — "
              "re-snapshot with --update:")
        for r in removed[:10]:
            print(f"  - {r}")
        print()

    if added:
        print(f"NEW schema drift: {len(added)} difference(s) not in the baseline.")
        print("A model changed without a matching migration, or vice versa.\n")
        for a in added:
            print(f"  + {a}")
        return 1

    print(f"No new schema drift ({len(current)} known differences).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
