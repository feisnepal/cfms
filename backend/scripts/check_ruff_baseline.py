#!/usr/bin/env python
"""Ruff baseline ratchet — fail on NEW lint errors, not the known ones (H4.1).

`ci.yml` ran `ruff check app || true`, suppressed since Phase 1 on the stated
grounds that the codebase "carries pre-existing debt from the Code Quality
audit (bare-excepts, a number of F821 undefined-name findings)".

It carries no *style* debt. Every violation ruff reports on this codebase is a
pyflakes **error**: undefined names, unused variables, redefinitions, shadowed
imports. `F821` in particular means the name does not exist at runtime, and 36
of them turned out to be live bugs — a distance column that was always empty, a
restore feature that restored nothing, an append path that returned 500. They
survived because the one tool that could see them was told to always exit 0.

So this replaces the suppression rather than deleting it outright: 279 known
findings cannot be fixed in one change, but not one more may be added.

Deliberately mirrors `frontend/scripts/check-tsc-baseline.mjs`, which does the
same job for TypeScript — same baseline shape, same `--update` flag, same
"expected to SHRINK" contract. A second convention for the same idea would be
one convention too many.

**What counts as "the same error": FILE + RULE, with a count.** Not line
numbers, not message text. A line number moves whenever anything above it is
edited, and keying on it would produce constant false "new error" failures until
somebody switched the gate off. The trade is that swapping one `F841` for
another inside the same file goes unnoticed; that is worth it for a gate people
leave on.

Usage:
    python scripts/check_ruff_baseline.py            # gate
    python scripts/check_ruff_baseline.py --update   # re-record (refuses growth)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "ruff-baseline.json"
TARGET = "app"

LINE = re.compile(r"^(?P<file>[^:]+):\d+:\d+:\s+(?P<code>[A-Z]+[0-9]+)\b")


def collect() -> Counter[str]:
    """Current findings, keyed `path|CODE` with posix separators."""
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", TARGET, "--output-format", "concise"],
        capture_output=True, text=True, cwd=ROOT,
    )
    found: Counter[str] = Counter()
    for raw in proc.stdout.splitlines():
        match = LINE.match(raw.strip())
        if match:
            path = match.group("file").replace("\\", "/")
            found[f"{path}|{match.group('code')}"] += 1
    return found


def load() -> dict:
    if not BASELINE.exists():
        return {"total": 0, "errors": {}}
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def save(found: Counter[str]) -> None:
    BASELINE.write_text(json.dumps({
        "_comment": (
            "Known ruff findings, keyed file|RULE. Expected to SHRINK. "
            "Regenerate with: python scripts/check_ruff_baseline.py --update"
        ),
        "total": sum(found.values()),
        "errors": dict(sorted(found.items())),
    }, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    """Compare current ruff findings against the recorded baseline."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--update", action="store_true",
                        help="re-record the baseline; refuses to record growth")
    args = parser.parse_args()

    found = collect()
    baseline = load()
    known: dict[str, int] = baseline.get("errors", {})

    worse = {
        key: (count, known.get(key, 0))
        for key, count in found.items()
        if count > known.get(key, 0)
    }
    better = {
        key: (found.get(key, 0), count)
        for key, count in known.items()
        if found.get(key, 0) < count
    }

    total_now, total_was = sum(found.values()), baseline.get("total", 0)
    print(f"ruff findings: {total_now}   baseline: {total_was}")

    if args.update:
        # Seeding: with no baseline on disk every finding reads as growth, and
        # the guard below would refuse to write the very first one. Record it.
        if not BASELINE.exists():
            save(found)
            print(f"baseline created with {total_now} known finding(s)")
            return 0
        if worse:
            print("\nRefusing to record growth — the baseline may only shrink:",
                  file=sys.stderr)
            for key, (now, was) in sorted(worse.items()):
                print(f"  {key}: {was} -> {now}", file=sys.stderr)
            print("\nFix these, or record them deliberately by editing "
                  "ruff-baseline.json by hand.", file=sys.stderr)
            return 1
        save(found)
        print(f"baseline updated: {total_was} -> {total_now}")
        return 0

    if worse:
        print(f"\nFAILED: {len(worse)} new ruff finding(s):", file=sys.stderr)
        for key, (now, was) in sorted(worse.items()):
            path, code = key.rsplit("|", 1)
            print(f"  {path}  {code}: {was} -> {now}", file=sys.stderr)
        print("\nFix them, or run --update if they are deliberate.",
              file=sys.stderr)
        return 1

    if better:
        fixed = sum(was - now for now, was in better.values())
        print(f"\n{fixed} finding(s) fixed since the baseline. "
              f"Run --update to lock that in so they cannot come back.")

    print("passed — no new ruff findings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
