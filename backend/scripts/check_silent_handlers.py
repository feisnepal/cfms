#!/usr/bin/env python
"""Find exception handlers that discard the error — gate G-QUAL-1 (H3.4 · S2-37).

The audit counted 669 broad `except Exception` handlers, of which 171 neither
logged, re-raised, nor captured anything. This script finds them with the AST
rather than a regex, because the question it turns on — *does this handler body
do anything with the exception* — is not answerable line by line. The audit's
own count used a four-line window and undercounted as a result.

Why this class matters more than its size suggests. In a geospatial pipeline a
swallowed exception does not produce an error; it produces **a plausible-looking
wrong number**. The dominant shape here is a `shapely` parse or overlay inside a
loop that `continue`s on failure: one feature silently leaves the union, the
area sum is quietly short, and an operational plan with regulatory standing
carries the difference with nothing anywhere saying so.

Every broad handler must resolve to one of three things:

* **it raises** — the failure invalidates the result, so the caller must see it
* **it logs** — a fallback is legitimate, but the failure has to be visible
* **it is justified** — genuinely ignorable, marked `# noqa: BLE001` on the
  `except` line with a reason after the code

The third is deliberately the same marker `ruff` uses. When H4.1's ratchet lets
`BLE001` and `S110` be enforced, every justification written for this gate is
already the suppression ruff wants, and the reason text travels with it.

What counts as "it logs" is broad on purpose — any `logger.*` call, `print`, or
a Sentry `capture_*`. A handler that logs badly is a different problem from one
that says nothing at all, and only the second is invisible.

Usage:
    python scripts/check_silent_handlers.py            # report
    python scripts/check_silent_handlers.py --gate     # exit 1 on any offender
    python scripts/check_silent_handlers.py --list     # every offender, with shape
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

SCAN_DIR = "app"

# Anything that makes the failure observable. `print` is included because the
# print->logging migration is unfinished; a `print` is poor logging, not silence.
# `report_dropped` is `app.core.dropped`'s rate-limited reporter — the answer for
# the many handlers that skip one record inside a loop, where a plain
# `logger.warning` would flood rather than inform.
LOG_CALLS = {
    "debug", "info", "warning", "warn", "error", "exception", "critical", "log",
    "capture_exception", "capture_message", "print", "report_dropped",
}

# `# noqa: BLE001` / `# noqa: BLE001, S110` / `# noqa:BLE001 -- reason`.
# Ruff tolerates free text after the codes, so the reason rides along in the
# same comment rather than needing a second convention.
NOQA_RE = re.compile(r"#\s*noqa:\s*([A-Z]+[0-9]+(?:\s*,\s*[A-Z]+[0-9]+)*)", re.I)
JUSTIFY_CODES = {"BLE001", "S110", "S112"}


@dataclass
class Handler:
    """One `except` clause and what it does about the exception it caught."""

    file: Path
    line: int
    caught: str
    logs: bool
    raises: bool
    justified: bool
    reason: str
    shape: str

    @property
    def silent(self) -> bool:
        """Caught something broad and did nothing observable or deliberate."""
        return not (self.logs or self.raises or self.justified)


def _caught(handler: ast.ExceptHandler) -> str | None:
    """The broad name this handler catches, or None if it is specific.

    A tuple counts if any member is broad — `except (ValueError, Exception)`
    catches everything, whatever the first member suggests.
    """
    if handler.type is None:
        return "bare"
    names: list[str] = []
    for node in ast.walk(handler.type):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
    for broad in ("BaseException", "Exception"):
        if broad in names:
            return broad
    return None


def _signals(body: list[ast.stmt]) -> tuple[bool, bool]:
    """Does this handler body log, and does it raise?

    Nested scopes are walked deliberately: a handler whose only action is to
    schedule a callback that logs is still saying something, and the false
    negative of ignoring it is worse than the false positive of counting it.
    """
    logs = raises = False
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Raise):
                raises = True
            elif isinstance(node, ast.Call):
                func = node.func
                name = (
                    func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name)
                    else ""
                )
                if name in LOG_CALLS:
                    logs = True
    return logs, raises


def _shape(body: list[ast.stmt]) -> str:
    """A one-word description of what the handler does, for the report."""
    if len(body) == 1:
        first = body[0]
        if isinstance(first, ast.Pass):
            return "pass"
        if isinstance(first, ast.Continue):
            return "continue"
        if isinstance(first, ast.Break):
            return "break"
        if isinstance(first, ast.Return):
            return "return"
    return "fallback"


def _justification(line: str) -> tuple[bool, str]:
    """Is this `except` line marked with a suppression, and what is the reason?"""
    match = NOQA_RE.search(line)
    if not match:
        return False, ""
    codes = {code.strip().upper() for code in match.group(1).split(",")}
    if not codes & JUSTIFY_CODES:
        return False, ""
    reason = line[match.end():].lstrip(" -–—:")
    return True, reason.strip()


def scan(root: Path) -> list[Handler]:
    """Every broad exception handler under `app/`, classified."""
    out: list[Handler] = []
    base = root / SCAN_DIR
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        lines = source.split("\n")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            print(f"  ! could not parse {path}: {exc}", file=sys.stderr)
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            caught = _caught(node)
            if caught is None:
                continue
            logs, raises = _signals(node.body)
            justified, reason = _justification(lines[node.lineno - 1])
            out.append(Handler(
                file=path.relative_to(root),
                line=node.lineno,
                caught=caught,
                logs=logs,
                raises=raises,
                justified=justified,
                reason=reason,
                shape=_shape(node.body),
            ))
    return out


def main() -> int:
    """Report, or gate on, the silent handlers under `app/`."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--gate", action="store_true",
                        help="exit 1 if any broad handler discards its exception")
    parser.add_argument("--list", action="store_true",
                        help="print every offender rather than the first 40")
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()

    handlers = scan(args.root)
    silent = [h for h in handlers if h.silent]
    justified = [h for h in handlers if h.justified]
    speaking = [h for h in handlers if h.logs or h.raises]

    print(f"broad handlers scanned .......... {len(handlers)}")
    print(f"  log or raise .................. {len(speaking):4d}  (the exception is visible)")
    print(f"  justified (# noqa: BLE001) .... {len(justified):4d}  (deliberately ignored, with a reason)")
    print(f"  silent ........................ {len(silent):4d}  <- discards the exception")

    if silent:
        shapes = Counter(h.shape for h in silent)
        print(f"\n  shapes: {', '.join(f'{k}={v}' for k, v in shapes.most_common())}")
        print("\nDiscarding the exception:")
        shown = sorted(silent, key=lambda h: (str(h.file), h.line))
        for handler in shown if args.list else shown[:40]:
            location = f"{handler.file}:{handler.line}"
            print(f"  {location:60s} {handler.shape}")
        if not args.list and len(shown) > 40:
            print(f"  ... and {len(shown) - 40} more (--list for all)")

    if args.gate and silent:
        print(
            f"\nGate G-QUAL-1 FAILED: {len(silent)} handler(s) catch a broad "
            f"exception and do nothing with it.\n"
            f"Each must log it, raise, or carry `# noqa: BLE001 -- <reason>` "
            f"on the `except` line saying why the failure is ignorable.",
            file=sys.stderr,
        )
        return 1

    if args.gate:
        print("\nGate G-QUAL-1 passed — no exception is discarded silently.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
