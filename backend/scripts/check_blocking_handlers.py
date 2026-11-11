#!/usr/bin/env python
"""Find route handlers that block the event loop — gate G-PERF-1 (H3.1 / H3.2 · S1-17).

FastAPI runs a `def` handler in a threadpool and an `async def` handler
**directly on the event loop**. The session factory here is synchronous
SQLAlchemy over psycopg2, so every `db.query(...)` inside an `async def` handler
blocks the whole process — not that request, the *server*. With a single uvicorn
worker that is a hard concurrency ceiling: one slow tile render or one large
shapefile import stalls every other user, health checks included.

The fix is one word per handler, `async def` → `def`, and it is safe **only when
the handler never awaits**. This script decides that with the AST rather than a
regex, because the distinction it turns on — does this function body contain a
real `await` — is exactly what a regex cannot see.

Three kinds of await keep a handler async, and all three are detected:

* `await` expressions
* `async with` (an async context manager cannot be entered from a `def`)
* `async for`

Awaits inside a *nested* function do not count: a handler containing an inner
`async def` helper is itself convertible, since the inner one keeps its own
coroutine nature.

Usage:
    python scripts/check_blocking_handlers.py            # report
    python scripts/check_blocking_handlers.py --gate     # exit 1 on any offender
    python scripts/check_blocking_handlers.py --fix      # rewrite the safe ones
"""
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

API_DIRS = ["app/api", "app"]
ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete", "head", "options"}
# The dependency that makes a handler blocking. `Session` is the annotation;
# `get_db` is the provider — either is enough to identify one.
SYNC_SESSION_MARKERS = {"Session", "get_db"}


@dataclass
class Handler:
    file: Path
    line: int
    name: str
    is_async: bool
    uses_session: bool
    awaits: list[str]
    is_generator: bool = False

    @property
    def blocking(self) -> bool:
        """async, touches a sync Session, never awaits, and is not a generator.

        Generators are excluded deliberately. Converting an `async def` that
        yields turns an async generator into a sync one, and Starlette streams
        the two differently — that is a behaviour change on a streaming
        endpoint, not the one-word no-op this conversion is everywhere else.
        """
        return (
            self.is_async and self.uses_session
            and not self.awaits and not self.is_generator
        )

    @property
    def legitimately_async(self) -> bool:
        return self.is_async and self.uses_session and bool(self.awaits)


def _is_route(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    for dec in node.decorator_list:
        call = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(call, ast.Attribute) and call.attr in ROUTE_DECORATORS:
            return True
    return False


def _uses_sync_session(node) -> bool:
    """Does any parameter annotate `Session` or default to `Depends(get_db)`?"""
    args = node.args
    for arg in [*args.args, *args.kwonlyargs, *args.posonlyargs]:
        if arg.annotation is not None:
            for sub in ast.walk(arg.annotation):
                if isinstance(sub, ast.Name) and sub.id in SYNC_SESSION_MARKERS:
                    return True
                if isinstance(sub, ast.Attribute) and sub.attr in SYNC_SESSION_MARKERS:
                    return True
    for default in [*args.defaults, *args.kw_defaults]:
        if default is None:
            continue
        for sub in ast.walk(default):
            if isinstance(sub, ast.Name) and sub.id in SYNC_SESSION_MARKERS:
                return True
            if isinstance(sub, ast.Attribute) and sub.attr in SYNC_SESSION_MARKERS:
                return True
    return False


def _awaits_in_own_body(node) -> list[str]:
    """Awaits belonging to THIS function, not to a nested one.

    A handler that defines an inner `async def` helper is still convertible —
    the helper keeps its own coroutine nature and is awaited from wherever it is
    called, not from the enclosing `def`.
    """
    found: list[str] = []

    def walk(n, top: bool) -> None:
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)):
                continue  # a nested scope owns its own awaits
            if isinstance(child, ast.Await):
                found.append(f"await@{child.lineno}")
            elif isinstance(child, ast.AsyncWith):
                found.append(f"async-with@{child.lineno}")
            elif isinstance(child, ast.AsyncFor):
                found.append(f"async-for@{child.lineno}")
            walk(child, False)

    walk(node, True)
    return found


def _is_generator(node) -> bool:
    """Does this function yield in its own body (not a nested one)?"""
    for child in ast.walk(node):
        if isinstance(child, (ast.Yield, ast.YieldFrom)):
            return True
    return False


def scan(root: Path) -> list[Handler]:
    out: list[Handler] = []
    seen: set[Path] = set()
    for rel in API_DIRS:
        base = root / rel
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts or path in seen:
                continue
            seen.add(path)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError as exc:
                print(f"  ! could not parse {path}: {exc}", file=sys.stderr)
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    continue
                if not _is_route(node):
                    continue
                out.append(Handler(
                    file=path.relative_to(root),
                    line=node.lineno,
                    name=node.name,
                    is_async=isinstance(node, ast.AsyncFunctionDef),
                    uses_session=_uses_sync_session(node),
                    awaits=_awaits_in_own_body(node),
                    is_generator=_is_generator(node),
                ))
    return out


def fix(handlers: list[Handler], root: Path) -> int:
    """Rewrite `async def` → `def` for the safe ones, one line each."""
    by_file: dict[Path, list[Handler]] = {}
    for h in handlers:
        by_file.setdefault(h.file, []).append(h)

    changed = 0
    for rel, hs in by_file.items():
        path = root / rel
        lines = path.read_text(encoding="utf-8").split("\n")
        for h in sorted(hs, key=lambda x: -x.line):
            idx = h.line - 1
            line = lines[idx]
            if not line.lstrip().startswith("async def "):
                print(f"  ! {rel}:{h.line} is not an `async def` line, skipping")
                continue
            lines[idx] = line.replace("async def ", "def ", 1)
            changed += 1
        path.write_text("\n".join(lines), encoding="utf-8")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gate", action="store_true", help="exit 1 if any blocking handler remains")
    ap.add_argument("--fix", action="store_true", help="rewrite the safe ones in place")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args()

    handlers = scan(args.root)
    blocking = [h for h in handlers if h.blocking]
    legit = [h for h in handlers if h.legitimately_async]
    sync_ok = [h for h in handlers if not h.is_async and h.uses_session]
    streaming = [h for h in handlers
                 if h.is_async and h.uses_session and not h.awaits and h.is_generator]

    print(f"routes scanned .................. {len(handlers)}")
    print(f"  async + sync Session + awaits . {len(legit):4d}  (correctly async — leave alone)")
    print(f"  def + sync Session ............ {len(sync_ok):4d}  (already in the threadpool)")
    print(f"  streaming generators .......... {len(streaming):4d}  (excluded — see Handler.blocking)")
    print(f"  async + sync Session, NO await  {len(blocking):4d}  <- blocks the event loop")

    if args.fix and blocking:
        n = fix(blocking, args.root)
        print(f"\nconverted {n} handler(s) to `def`")
        return 0

    if blocking:
        print("\nBlocking the event loop:")
        for h in sorted(blocking, key=lambda x: (str(x.file), x.line))[:200]:
            print(f"  {str(h.file)+':'+str(h.line):48s} {h.name}")
        if args.gate:
            print(
                f"\nG-PERF-1 FAILED: {len(blocking)} handler(s) are `async def` while depending on a\n"
                "synchronous Session and never awaiting. FastAPI runs these on the event loop, so\n"
                "each one blocks the whole process. Change `async def` to `def` — FastAPI will run\n"
                "them in its threadpool. See S1-17.",
            )
            return 1
    else:
        print("\nNo handler blocks the event loop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
