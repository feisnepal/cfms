#!/usr/bin/env python
"""Force a partial calculation, so H3.5's fail-fast gate can be seen (S2-37).

Why a script is needed at all
----------------------------
You cannot reach this by clicking. The gate fires when a single unit throws
during analysis, and every ordinary path through the UI produces units that
analyse fine. That is exactly why the defect survived: the only way to witness
`completed` written over partial data was to be unlucky in production, on a
document with regulatory standing.

`analysis.py` deliberately continues past a failed unit -- one bad block must
not discard the other forty-nine -- and that resilience was kept. What changed
in H3.5 is that a result carrying any `analysis_error` now raises
`PartialCalculationError`, so the pipeline records FAILED with a reason instead
of `completed`.

How it forces the failure
-------------------------
`CFMS_FORCE_BLOCK_FAILURE=<block name>` makes `analyze_block_geometry` raise for
that block, and only when `settings.DEBUG` is true. It is the backend twin of
the frontend's `?__crash=1` hook (H3.8): the boundary of last resort cannot be
tested without something that deliberately trips it.

**Nothing here writes to your data.** The script does not modify the
calculation; it reads the current state, tells you what to run, and then reports
what happened. Running the calculation itself is your action, in the UI.

Usage:
    python scripts/trigger_partial_calculation.py --list
    python scripts/trigger_partial_calculation.py --calculation <uuid>
    python scripts/trigger_partial_calculation.py --calculation <uuid> --check
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GREEN, RED, YELLOW, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def _session():
    from app.core.database import SessionLocal

    return SessionLocal()


def list_candidates() -> int:
    """Calculations that have blocks to break."""
    from sqlalchemy import text

    with _session() as db:
        rows = db.execute(text("""
            SELECT c.id, c.forest_name, c.status,
                   (SELECT count(*) FROM forest_blocks b WHERE b.calculation_id = c.id) AS blocks
            FROM calculations c
            WHERE (SELECT count(*) FROM forest_blocks b WHERE b.calculation_id = c.id) > 1
            ORDER BY c.created_at DESC
            LIMIT 10
        """)).fetchall()

    if not rows:
        print(f"{YELLOW}No calculation has more than one block. The point of this test is that")
        print(f"the OTHER blocks still analyse, so you need at least two.{OFF}")
        return 1

    print(f"{DIM}Calculations with blocks (most recent first):{OFF}\n")
    for r in rows:
        print(f"  {r[0]}  {str(r[1])[:34]:36s} {str(r[2]):12s} {r[3]} blocks")
    print(f"\nThen: python scripts/trigger_partial_calculation.py --calculation <id>")
    return 0


def show_instructions(calc_id: str) -> int:
    from sqlalchemy import text

    with _session() as db:
        blocks = db.execute(text("""
            SELECT block_name FROM forest_blocks
            WHERE calculation_id = :c ORDER BY index NULLS LAST, block_name
        """), {"c": calc_id}).fetchall()

    if not blocks:
        print(f"{RED}No blocks on calculation {calc_id}.{OFF}")
        return 1

    victim = blocks[0][0]
    print(f"{DIM}Calculation {calc_id} has {len(blocks)} blocks.{OFF}\n")
    print(f"Break exactly one: {GREEN}{victim}{OFF}  "
          f"(the other {len(blocks) - 1} must still analyse — that is the point)\n")
    print("1. Stop the backend.")
    print("2. Start it with the hook set. PowerShell:\n")
    print(f'     $env:CFMS_FORCE_BLOCK_FAILURE = "{victim}"')
    print("     .\\start_all.bat\n")
    print("   (DEBUG must be true in backend/.env, or the hook is inert.)\n")
    print("3. In the UI, run the calculation for this forest.")
    print("4. Then, to see the verdict:\n")
    print(f"     python scripts/trigger_partial_calculation.py --calculation {calc_id} --check\n")
    print(f"{YELLOW}Afterwards: unset CFMS_FORCE_BLOCK_FAILURE and restart, or every")
    print(f"run of this forest will keep failing.{OFF}")
    return 0


def check(calc_id: str) -> int:
    """Did the pipeline refuse to call it completed?"""
    from sqlalchemy import text

    from app.services.calculation_integrity import failed_units, partial_failure_reason

    with _session() as db:
        row = db.execute(text("""
            SELECT status, error_message, result_data FROM calculations WHERE id = :c
        """), {"c": calc_id}).first()

    if row is None:
        print(f"{RED}No such calculation.{OFF}")
        return 1

    status, error_message, result_data = row[0], row[1], row[2]
    failures = failed_units(result_data)
    reason = partial_failure_reason(result_data)

    print(f"{DIM}Calculation {calc_id}{OFF}")
    print(f"  status          : {status}")
    print(f"  failed units    : {len(failures)}")
    for f in failures[:5]:
        print(f"      - {f['name']}: {f['error'][:90]}")
    print(f"  error_message   : {str(error_message)[:160]}")

    ok = True
    if not failures:
        print(f"\n{YELLOW}No unit carries an analysis_error, so the hook did not fire.")
        print(f"Check that DEBUG is true and CFMS_FORCE_BLOCK_FAILURE matched a block name.{OFF}")
        return 2

    # The assertion that matters, and the one the defect would fail.
    if str(status).lower().endswith("completed"):
        print(f"\n{RED}FAIL — status is COMPLETED with {len(failures)} failed unit(s).")
        print(f"That is the defect H3.5 exists to prevent: a partial result "
              f"indistinguishable from a whole one.{OFF}")
        ok = False
    else:
        print(f"\n{GREEN}PASS — status is {status}, not completed.{OFF}")

    # Partial results must SURVIVE. Failing loudly and discarding the work would
    # be its own defect: somebody has to be able to see which block broke.
    total = sum(len(result_data.get(k, []))
                for k in ("blocks", "compartments", "sub_compartments")
                if isinstance(result_data.get(k), list)) if result_data else 0
    if total and total > len(failures):
        print(f"{GREEN}PASS — partial results kept: {total} units stored, "
              f"{total - len(failures)} analysed successfully.{OFF}")
    else:
        print(f"{RED}FAIL — the successful units were not preserved.{OFF}")
        ok = False

    if reason and error_message and reason[:40] in str(error_message):
        print(f"{GREEN}PASS — the recorded reason names the broken units.{OFF}")
    else:
        print(f"{YELLOW}NOTE — error_message does not obviously carry the unit names.{OFF}")

    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true", help="calculations with blocks to break")
    ap.add_argument("--calculation", help="calculation id to work with")
    ap.add_argument("--check", action="store_true", help="report the verdict after a run")
    args = ap.parse_args()

    if args.list or not args.calculation:
        return list_candidates()
    if args.check:
        return check(args.calculation)
    return show_instructions(args.calculation)


if __name__ == "__main__":
    raise SystemExit(main())
