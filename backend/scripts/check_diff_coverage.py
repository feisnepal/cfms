#!/usr/bin/env python
"""Diff coverage — changed lines must be ≥85% covered (H4.2 / S1-22).

The total-coverage ratchet (`check_coverage_baseline.py`) cannot catch this on
its own: a 50-line change to a 2,000-line file can drop that file from 90% to
40% covered and barely move the project-wide total. The regression is
invisible in the number everyone watches and stays invisible until someone
happens to open that specific file.

So this looks at the diff, not the tree. For every line a change *adds* --
`git diff`'s `+` lines, against the merge-base with `--base` -- it asks
whether `coverage.xml` marked that line as hit. Deleted lines have nothing to
measure; unchanged lines are the total-coverage gate's job, not this one's.

Deliberately no new dependency. `diff-cover` on PyPI does this job, but the
project's own convention (see `check-tsc-baseline.mjs`, `perf-budget-gate.mjs`)
is a small script over general tooling when the general tool pulls in a
dependency for one gate -- and the intersection of a unified diff with a
Cobertura XML's `<line number hits>` table is about sixty lines either way.

A changed line that coverage.xml does not mention at all (a comment, a blank
line, an import) is not "uncovered" -- it was never executable, so it is
excluded from the denominator entirely rather than counted against the 85%.

Usage:
    python scripts/check_diff_coverage.py                  # vs merge-base with master
    python scripts/check_diff_coverage.py --base HEAD~3     # vs a specific ref
    python scripts/check_diff_coverage.py --run-tests       # regenerate coverage.xml first
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COVERAGE_XML = ROOT / "coverage.xml"
THRESHOLD_PERCENT = 85.0
STALE_AFTER_SECONDS = 3600

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")


def run_tests_with_coverage() -> None:
    print("Running the suite with coverage (this takes a while)...")
    subprocess.run(
        [
            sys.executable, "-m", "pytest", "tests/", "-q",
            "--ignore=tests/test_op_api.py", "--timeout=300",
            "--cov=app", "--cov-report=xml",
        ],
        cwd=ROOT,
    )


def changed_lines_by_file(base: str) -> dict[str, set[int]]:
    """Added-line numbers per Python file changed since `base`.

    Uses the merge-base, not `base` directly -- `git diff master...HEAD`
    behaviour -- so a branch that is behind master is diffed against where it
    forked, not against master's later, unrelated commits.
    """
    merge_base = subprocess.run(
        ["git", "merge-base", base, "HEAD"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()

    # --relative: `git diff` reports paths from the top of the working tree
    # regardless of cwd (pathspecs ARE cwd-relative; the *output* paths are
    # not, unless told to be) -- without this every path came back prefixed
    # `backend/app/...` and matched nothing in coverage.xml, which is rooted
    # at `backend/` because that is where `--cov=app` runs. Caught by running
    # this against a real commit before trusting it against CI.
    diff = subprocess.run(
        ["git", "diff", "--unified=0", "--relative", merge_base, "HEAD", "--", "app/*.py"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout

    result: dict[str, set[int]] = {}
    current_file: str | None = None
    next_line = 0

    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:]
            if path == "/dev/null":
                current_file = None  # file was deleted; nothing to gate
            else:
                # "b/app/services/foo.py" -> "app/services/foo.py"
                current_file = path.split("/", 1)[1] if path.startswith("b/") else path
            continue
        if line.startswith("@@"):
            m = HUNK_HEADER.match(line)
            if m:
                next_line = int(m.group("start"))
            continue
        if current_file is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            result.setdefault(current_file, set()).add(next_line)
            next_line += 1
        elif not line.startswith("-"):
            next_line += 1

    return result


def coverage_hits_by_file() -> dict[str, dict[int, int]]:
    """`{relative_path: {line_number: hit_count}}` from coverage.xml.

    Cobertura paths are relative to the `--cov` root (`app/`), and posix-style
    even on Windows -- normalised to match `git diff`'s `app/...` paths.
    """
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
    out: dict[str, dict[int, int]] = {}
    for cls in root.iter("class"):
        filename = cls.attrib["filename"].replace("\\", "/")
        if not filename.startswith("app/"):
            filename = f"app/{filename}"
        lines_el = cls.find("lines")
        hits = {
            int(line.attrib["number"]): int(line.attrib["hits"])
            for line in (lines_el if lines_el is not None else [])
        }
        out[filename] = hits
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default="master",
                        help="ref to diff against (default: master)")
    parser.add_argument("--run-tests", action="store_true",
                        help="regenerate coverage.xml before checking")
    args = parser.parse_args()

    if args.run_tests:
        run_tests_with_coverage()

    changed = changed_lines_by_file(args.base)
    if not changed:
        print("no changed Python lines under app/ — nothing to check.")
        return 0

    hits_by_file = coverage_hits_by_file()

    covered = 0
    total = 0
    uncovered: list[str] = []

    for path, lines in sorted(changed.items()):
        file_hits = hits_by_file.get(path)
        if file_hits is None:
            # Not in coverage.xml at all -- e.g. a file with no executable
            # code coverage.py tracked (a pure-typing stub, __init__.py with
            # only imports). Nothing to measure; not a violation.
            continue
        for line_no in sorted(lines):
            if line_no not in file_hits:
                continue  # not an executable line (comment, blank, etc.)
            total += 1
            if file_hits[line_no] > 0:
                covered += 1
            else:
                uncovered.append(f"{path}:{line_no}")

    if total == 0:
        print("no changed lines were executable — nothing to check.")
        return 0

    percent = round(covered / total * 100, 1)
    print(f"diff coverage: {covered}/{total} changed lines covered ({percent}%)   "
          f"threshold: {THRESHOLD_PERCENT}%")

    if percent < THRESHOLD_PERCENT:
        print(f"\nFAILED: {len(uncovered)} changed line(s) not covered by any test:",
              file=sys.stderr)
        for loc in uncovered[:25]:
            print(f"  {loc}", file=sys.stderr)
        if len(uncovered) > 25:
            print(f"  ... and {len(uncovered) - 25} more", file=sys.stderr)
        return 1

    print("passed — changed lines meet the 85% threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
