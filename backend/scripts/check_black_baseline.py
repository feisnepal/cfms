#!/usr/bin/env python
"""Black baseline ratchet — NEW files must be formatted; old ones may wait (H4.1).

`ci.yml` ran `black --check app || true`. Removing the suppression outright
turns the build red immediately: **249 of 258 files would be reformatted.**

The obvious alternative — run `black app` once and commit — is worse than it
looks. It rewrites nearly every backend file in a single commit, which makes
`git blame` useless across the whole codebase and guarantees a conflict with
every branch in flight. For a project mid-way through a hardening plan whose
evidence trail is commit hashes, that is a real cost.

So this ratchets on the SET OF FILES rather than a count, which is the only
thing black can be partial about: the 249 known-unformatted files stay as they
are, and a file that is formatted today may not become unformatted tomorrow. A
NEW file must be black-clean from the start, which is the property that actually
matters — the debt stops growing while it is paid down at whatever pace suits.

Reformat a legacy file whenever you are already editing it:

    python -m black app/services/thing.py
    python scripts/check_black_baseline.py --update

`--update` refuses to record a file that has REGRESSED from formatted to
unformatted, so the list can only shrink.

Mirrors `check_ruff_baseline.py` and `frontend/scripts/check-tsc-baseline.mjs`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "black-baseline.json"
TARGET = "app"


def collect() -> set[str]:
    """Files black would reformat, as posix paths relative to `backend/`."""
    proc = subprocess.run(
        [sys.executable, "-m", "black", "--check", TARGET],
        capture_output=True, text=True, cwd=ROOT,
    )
    files: set[str] = set()
    # black reports "would reformat <path>" on stderr, one per line.
    for line in (proc.stderr or "").splitlines():
        line = line.strip()
        if line.startswith("would reformat "):
            raw = line[len("would reformat "):].strip()
            path = Path(raw)
            try:
                path = path.relative_to(ROOT)
            except ValueError:
                pass
            files.add(path.as_posix())
    return files


def load() -> set[str]:
    if not BASELINE.exists():
        return set()
    return set(json.loads(BASELINE.read_text(encoding="utf-8")).get("unformatted", []))


def save(files: set[str]) -> None:
    BASELINE.write_text(json.dumps({
        "_comment": (
            "Files black would reformat. Expected to SHRINK — reformat a file "
            "whenever you are already editing it, then run: "
            "python scripts/check_black_baseline.py --update"
        ),
        "total": len(files),
        "unformatted": sorted(files),
    }, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    """Fail when a file that was formatted stops being formatted."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--update", action="store_true",
                        help="re-record the baseline; refuses to record regressions")
    args = parser.parse_args()

    found = collect()
    known = load()
    regressed = sorted(found - known)
    fixed = sorted(known - found)

    print(f"unformatted files: {len(found)}   baseline: {len(known)}")

    if args.update:
        if not BASELINE.exists():
            save(found)
            print(f"baseline created with {len(found)} unformatted file(s)")
            return 0
        if regressed:
            print("\nRefusing to record a regression — these were formatted and "
                  "are no longer:", file=sys.stderr)
            for path in regressed:
                print(f"  {path}", file=sys.stderr)
            print("\nRun `python -m black` on them instead.", file=sys.stderr)
            return 1
        save(found)
        print(f"baseline updated: {len(known)} -> {len(found)}")
        return 0

    if regressed:
        print(f"\nFAILED: {len(regressed)} file(s) are not black-formatted and "
              f"are not in the baseline:", file=sys.stderr)
        for path in regressed:
            print(f"  {path}", file=sys.stderr)
        print("\nA new file must be formatted from the start. Run:\n"
              f"  python -m black {' '.join(regressed[:3])}", file=sys.stderr)
        return 1

    if fixed:
        print(f"\n{len(fixed)} file(s) formatted since the baseline. "
              f"Run --update to lock that in.")

    print("passed — no newly unformatted files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
