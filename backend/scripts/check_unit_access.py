#!/usr/bin/env python
"""Ratchet: nothing but the units module may decide "which units does this forest have" (FS-0.6, I5/I10).

Six subsystems pick a forest's units six different ways (plan: "one unit set"). The cure is a single module,
``app/services/forest_units/``; this gate keeps the rest of the code from growing new ad-hoc ways in while
the readers are migrated onto it, and once they are migrated (FS-1c.9) it holds the count at ZERO.

What it counts, per file, in ``backend/app`` (Python, including raw SQL inside strings) and
``frontend/src`` (numeric-level comparisons only):

  numeric_level     a number compared with the level: ``division_level == 0``, ``division_level <= 1``,
                    ``division_level IN (0, 1)``, ``.division_level.in_(...)``, ``division_level=0``
                    passed as a keyword. Invariant I10: never test depth without the branch, and never
                    write a bare number - ask the module.
  level_ref         any mention of ``division_level`` (attribute, key or SQL column).
  branch_ref        any mention of ``is_compartment``.
  parent_ref        any mention of ``parent_block_id``.
  jsonb_array_read  ``["blocks"]`` / ``.get("blocks"`` / the same for ``compartments`` (the derived cache
                    of the units - readers must use the units module instead).
  jsonb_array_write ``["blocks"] = ...`` / ``["compartments"] = ...`` (only the write funnel may).

It is a heuristic text scan on purpose: an AST cannot see the same column inside a ``text("SELECT ...")``
string, and raw SQL is where the hidden numeric levels live (plan risk "hidden numeric-level SQL").
``jsonb_array_*`` therefore also matches unrelated dicts that happen to have a "blocks" key - the ratchet
only cares that the count does not go UP.

Excluded (allowed to know the columns): ``app/services/forest_units/`` (the module), the ORM model
``app/models/forest_block.py`` (it defines the columns), tests, migrations.

Usage:
    python scripts/check_unit_access.py                 # report the current counts
    python scripts/check_unit_access.py --gate          # exit 1 if any (category, file) count went UP
    python scripts/check_unit_access.py --write-baseline   # record the current counts (after a phase)
    python scripts/check_unit_access.py --zero          # exit 1 unless numeric_level is 0 (FS-1c.9 onward)

The baseline is ``scripts/unit_access_baseline.json``. It may only shrink: lower it in the same change
that migrates a reader.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
BASELINE = Path(__file__).resolve().parent / "unit_access_baseline.json"

# Files / folders allowed to know the columns and the arrays.
ALLOWED_PREFIXES = (
    "backend/app/services/forest_units/",
    "backend/app/models/forest_block.py",
)

CATEGORIES = (
    "numeric_level",
    "level_ref",
    "branch_ref",
    "parent_ref",
    "jsonb_array_read",
    "jsonb_array_write",
)

_CMP = r"(?:==|!=|<>|<=|>=|<|>|=)"
PATTERNS = {
    # division_level <op> <number>  |  <number> <op> division_level  |  division_level IN (…)  |  .in_(
    "numeric_level": re.compile(
        rf"division_level[^=<>!\n]{{0,25}}{_CMP}\s*\d"
        rf"|\d\s*{_CMP}\s*\S{{0,40}}division_level"
        r"|division_level\s+(?:NOT\s+)?IN\s*\("
        r"|division_level\)?\.in_\("
        r"|division_level\s*=\s*\d",
        re.IGNORECASE,
    ),
    "level_ref": re.compile(r"division_level"),
    "branch_ref": re.compile(r"is_compartment"),
    "parent_ref": re.compile(r"parent_block_id"),
    "jsonb_array_read": re.compile(
        r"""(?:\[\s*|\.get\(\s*)['"](?:blocks|compartments)['"]"""
    ),
    "jsonb_array_write": re.compile(
        r"""\[\s*['"](?:blocks|compartments)['"]\s*\]\s*=(?!=)"""
    ),
}
# The frontend gets only the numeric-level check (its other references are display code handled by hand).
FRONTEND_CATEGORIES = ("numeric_level",)


def _files():
    for path in sorted((BACKEND / "app").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path, CATEGORIES
    for ext in ("*.ts", "*.tsx"):
        for path in sorted((REPO / "frontend" / "src").rglob(ext)):
            if (
                "node_modules" in path.parts
                or "__tests__" in path.parts
                or ".test." in path.name
            ):
                continue
            yield path, FRONTEND_CATEGORIES


def scan() -> dict:
    """``{category: {relative_file: count}}`` with zero counts omitted."""
    result = {c: {} for c in CATEGORIES}
    for path, cats in _files():
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith(ALLOWED_PREFIXES):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for cat in cats:
            rx = PATTERNS[cat]
            n = sum(1 for line in lines if rx.search(line))
            if n:
                result[cat][rel] = n
    return result


def _totals(data: dict) -> dict:
    return {c: sum(data.get(c, {}).values()) for c in CATEGORIES}


def load_baseline() -> dict:
    if not BASELINE.exists():
        return {c: {} for c in CATEGORIES}
    return json.loads(BASELINE.read_text(encoding="utf-8"))["counts"]


def write_baseline(data: dict) -> None:
    payload = {
        "_comment": (
            "Ratchet for check_unit_access.py. A count may only go DOWN; lower it in the same change that "
            "migrates the reader. numeric_level must reach 0 at FS-1c.9. Regenerate: "
            "python scripts/check_unit_access.py --write-baseline"
        ),
        "totals": _totals(data),
        "counts": {c: dict(sorted(data[c].items())) for c in CATEGORIES},
    }
    BASELINE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def regressions(current: dict, baseline: dict) -> list[str]:
    out = []
    for cat in CATEGORIES:
        base = baseline.get(cat, {})
        for f, n in sorted(current[cat].items()):
            if n > base.get(f, 0):
                out.append(f"{cat}: {f} has {n} (baseline {base.get(f, 0)})")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--gate", action="store_true", help="fail if any count went up vs the baseline"
    )
    ap.add_argument(
        "--write-baseline", action="store_true", help="record the current counts"
    )
    ap.add_argument(
        "--zero",
        action="store_true",
        help="fail unless numeric_level is 0 (enforcing mode)",
    )
    args = ap.parse_args(argv)

    current = scan()
    totals = _totals(current)

    if args.write_baseline:
        write_baseline(current)
        print("baseline written:", totals)
        return 0

    print("unit-access counts (backend/app + frontend numeric levels):")
    for cat in CATEGORIES:
        print(f"  {cat:18s} {totals[cat]:5d}  in {len(current[cat])} file(s)")

    rc = 0
    if args.gate:
        bad = regressions(current, load_baseline())
        if bad:
            print("\nFAIL - new direct access to units outside the units module:")
            for line in bad:
                print("  " + line)
            print(
                "\nGet the units from app.services.forest_units instead (plan section 3.1)."
            )
            rc = 1
        else:
            print("\nOK - nothing above the baseline.")
    if args.zero and totals["numeric_level"]:
        print(f"\nFAIL - numeric_level must be 0 (found {totals['numeric_level']}):")
        for f, n in sorted(current["numeric_level"].items(), key=lambda kv: -kv[1]):
            print(f"  {n:4d}  {f}")
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
