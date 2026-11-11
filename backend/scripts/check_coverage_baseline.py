#!/usr/bin/env python
"""Coverage ratchet — total line coverage may not decrease (H4.2 / S1-22).

`ci.yml` has measured coverage since H1.7 -- `--cov=app --cov-report=xml`,
published as an artifact on every run -- and said explicitly why it went no
further: "measure, do not gate. A threshold set before a baseline exists is a
guess; gating lands in task 4.2." A baseline now exists. This is that gate.

Same shape as `check_ruff_baseline.py` and `check_black_baseline.py`: record
what is true today, fail only on regression from there, and let `--update`
lock in improvement. A gate that demanded some fixed number today would be a
guess dressed up as a standard; a gate that can only get stricter is not.

Companion: `check_diff_coverage.py` covers the other half of H4.2 -- that
changed lines specifically meet 85%, which this total-line ratchet cannot see
on its own. A file can drop from 90% to 40% covered and still leave the
project-wide total looking fine if the file is small; the diff gate is what
catches that at the moment the regression is introduced, not years later when
someone finally looks at that file.

Usage:
    python scripts/check_coverage_baseline.py             # gate, reuses coverage.xml if fresh
    python scripts/check_coverage_baseline.py --run-tests  # regenerate coverage.xml first
    python scripts/check_coverage_baseline.py --update     # re-record; refuses to record a drop
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COVERAGE_XML = ROOT / "coverage.xml"
BASELINE = ROOT / "coverage-baseline.json"

# Coverage from a run that skipped real chunks of the suite is worse than no
# number at all -- it would ratchet in a false floor that a full run could
# never clear. Anyone gating on a coverage.xml older than this must have
# regenerated it deliberately in the same sitting.
STALE_AFTER_SECONDS = 3600


def run_tests_with_coverage() -> None:
    """Regenerate coverage.xml via the same invocation CI uses."""
    print("Running the suite with coverage (this takes a while)...")
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", "tests/", "-q",
            "--ignore=tests/test_op_api.py", "--timeout=300",
            "--cov=app", "--cov-report=xml", "--cov-report=term",
        ],
        cwd=ROOT,
    )
    # pytest's exit code reflects test failures, not coverage collection --
    # coverage.xml is written either way as long as the run reached teardown.
    # A crash before that leaves no file, and the check below catches it.
    if proc.returncode not in (0, 1):
        sys.exit(f"pytest exited {proc.returncode} -- coverage.xml is unreliable")


def read_total_percent() -> float:
    if not COVERAGE_XML.exists():
        sys.exit(
            "coverage.xml not found. Run with --run-tests, or run pytest with "
            "--cov=app --cov-report=xml first."
        )
    age = time.time() - COVERAGE_XML.stat().st_mtime
    if age > STALE_AFTER_SECONDS:
        sys.exit(
            f"coverage.xml is {age / 60:.0f} minutes old -- refusing to gate on a "
            f"stale run. Re-run with --run-tests."
        )
    root = ET.parse(COVERAGE_XML).getroot()
    line_rate = float(root.attrib["line-rate"])
    return round(line_rate * 100, 2)


def load_baseline() -> float | None:
    if not BASELINE.exists():
        return None
    return json.loads(BASELINE.read_text(encoding="utf-8"))["total_percent"]


def save_baseline(percent: float) -> None:
    BASELINE.write_text(
        json.dumps(
            {
                "_comment": (
                    "Total line coverage (H4.2 / S1-22). May only go up. "
                    "Regenerate with: python scripts/check_coverage_baseline.py --update"
                ),
                "total_percent": percent,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run-tests", action="store_true",
                        help="regenerate coverage.xml before checking")
    parser.add_argument("--update", action="store_true",
                        help="re-record the baseline; refuses to record a drop")
    args = parser.parse_args()

    if args.run_tests:
        run_tests_with_coverage()

    current = read_total_percent()
    baseline = load_baseline()

    print(f"total coverage: {current}%   baseline: "
          f"{baseline if baseline is not None else '(none recorded)'}%")

    if args.update:
        if baseline is not None and current < baseline:
            print(
                f"\nRefusing to record a drop: {baseline}% -> {current}%. "
                "Coverage fell -- that needs fixing, not baselining over.",
                file=sys.stderr,
            )
            return 1
        save_baseline(current)
        verb = "created" if baseline is None else "updated"
        print(f"baseline {verb}: {current}%")
        return 0

    if baseline is None:
        print(
            "\nNo baseline recorded yet. Run --update once to seed it "
            "(refuses nothing on first run).",
            file=sys.stderr,
        )
        return 1

    if current < baseline:
        print(
            f"\nFAILED: coverage dropped {baseline}% -> {current}%.",
            file=sys.stderr,
        )
        print(
            "Cover the code your change added, or run --update if the drop "
            "is deliberate (e.g. deleting a heavily-tested module).",
            file=sys.stderr,
        )
        return 1

    if current > baseline:
        print(f"\nCoverage rose {baseline}% -> {current}%. "
              f"Run --update to lock that in so it cannot silently come back down.")

    print("passed — coverage has not dropped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
