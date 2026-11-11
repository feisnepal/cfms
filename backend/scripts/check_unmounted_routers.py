#!/usr/bin/env python
"""Find routers the application never mounts (H3.4 follow-up · S3-49 family).

`main.py` mounts routers from one list, `SUB_ROUTERS`. A module under `app/api/`
that defines a `router` and is not in that list is invisible: its endpoints do
not exist, and the only symptom is a 404 at the one moment somebody needs them.

Five modules were in that state when this was written, carrying **fourteen
endpoints the frontend actively called** — the whole AI report feature, DFO
approve and reject, submit-for-calculation, super-admin-unlock. All fourteen
are served as of 2026-08-25: `reports.py` was mounted, and the six routes that
existed only in the unimportable `calculations.py` were lifted into
`calculation_lifecycle.py` — after which that module was provably redundant and
was deleted. Three modules remain listed below, none reachable from the UI.

**How this compares, and why it is not a grep.** Two traps make the naive check
wrong in opposite directions:

* `app.routes` holds 14 entries out of 372. The versioned router is mounted as
  a handful of `Mount`/`_IncludedRouter` objects, so a flat scan concludes
  everything is fine. `tests/test_route_authentication.py` documents the same
  trap. The walk here recurses.
* Path strings do not survive mounting — prefixes are prepended and `{param}`
  names vary. So this compares **endpoint function objects**, which are
  identical whether or not a prefix was added.

The gate is a ratchet, not a wall. The known modules are listed below with what
is at stake in each; anything else fails the build. Clearing an entry from
`KNOWN_UNMOUNTED` is how a fix gets locked in — `reports` and `calculations`
were both cleared that way.

Usage:
    python scripts/check_unmounted_routers.py            # report
    python scripts/check_unmounted_routers.py --gate     # exit 1 on a NEW one
    python scripts/check_unmounted_routers.py --routes   # list every dead route
"""
from __future__ import annotations

import argparse
import importlib
import sys
import warnings
from pathlib import Path

# Modules known to be unmounted, each with the consequence. A module NOT in this
# mapping that turns up unmounted fails the gate. Delete an entry when the
# module is either mounted or removed — that is what makes the fix permanent.
KNOWN_UNMOUNTED: dict[str, str] = {
    "geometry": (
        "cannot import (app.api.forests_helpers does not exist). Its 9 routes are "
        "duplicated by mounted routers — the frontend calls the "
        "/api/forests/... equivalents, which work. No user-visible breakage."
    ),
    "new_map_endpoints": (
        "cannot import (NameError: `router` is never defined) — this module has "
        "never worked. Its 5 map routes have zero frontend call sites."
    ),
    "audits": (
        "imports cleanly, simply absent from SUB_ROUTERS. One route, zero "
        "frontend call sites."
    ),
}

SKIP = {"__init__", "deps"}


def audit(root: Path) -> tuple[dict[str, list], dict[str, str]]:
    """Return (unmounted module -> its dead routes, module -> import error)."""
    warnings.filterwarnings("ignore")
    sys.path.insert(0, str(root))

    from app.main import app  # noqa: PLC0415 — import after sys.path is set

    def walk(node, seen):
        """Every route reachable from an app or router.

        `original_router` is the one that matters and the one that is easy to
        miss: FastAPI wraps an included router in `_IncludedRouter`, and without
        following it most of the API is invisible. A first cut of this script
        omitted it and confidently reported `auth` and `forests` as unmounted.
        `tests/test_route_authentication.py` documents the same trap.
        """
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        for route in getattr(node, "routes", []):
            yield route
            yield from walk(route, seen)
            yield from walk(getattr(route, "original_router", None), seen)
            yield from walk(getattr(route, "app", None), seen)

    live = {
        endpoint
        for route in walk(app.router, set())
        if (endpoint := getattr(route, "endpoint", None)) is not None
    }

    unmounted: dict[str, list] = {}
    broken: dict[str, str] = {}
    for path in sorted((root / "app" / "api").glob("*.py")):
        if path.stem in SKIP:
            continue
        try:
            module = importlib.import_module(f"app.api.{path.stem}")
        except Exception as exc:
            broken[path.stem] = f"{type(exc).__name__}: {exc}"
            continue
        router = getattr(module, "router", None)
        if router is None:
            continue
        dead = [
            r for r in router.routes
            if getattr(r, "endpoint", None) is not None and r.endpoint not in live
        ]
        if dead:
            unmounted[path.stem] = dead
    return unmounted, broken


def main() -> int:
    """Report, or gate on, routers the application does not mount."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--gate", action="store_true",
                        help="exit 1 on an unmounted router not already known")
    parser.add_argument("--routes", action="store_true",
                        help="list the dead routes, not just the modules")
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()

    unmounted, broken = audit(args.root)
    affected = sorted(set(unmounted) | set(broken))

    print(f"modules under app/api/ that the app does not serve: {len(affected)}\n")
    for stem in affected:
        known = stem in KNOWN_UNMOUNTED
        mark = "known" if known else "NEW"
        if stem in broken:
            print(f"  [{mark}] app/api/{stem}.py — unimportable")
            print(f"          {broken[stem]}")
        else:
            print(f"  [{mark}] app/api/{stem}.py — "
                  f"{len(unmounted[stem])} route(s) defined, none served")
            if args.routes:
                for route in unmounted[stem]:
                    verbs = ",".join(sorted(route.methods or []))
                    print(f"          {verbs:14s} {route.path}")
        if known:
            print(f"          reason: {KNOWN_UNMOUNTED[stem]}")
        print()

    new = [s for s in affected if s not in KNOWN_UNMOUNTED]
    fixed = [s for s in KNOWN_UNMOUNTED if s not in affected]

    if fixed:
        print(f"These are no longer unmounted: {', '.join(fixed)}")
        print("Remove them from KNOWN_UNMOUNTED so the fix cannot regress.\n")

    if args.gate and new:
        print(
            f"FAILED: {len(new)} router(s) the app does not mount and that are "
            f"not recorded as known: {', '.join(new)}.\n"
            f"Add it to `main.py`'s SUB_ROUTERS, delete the module, or record it "
            f"in KNOWN_UNMOUNTED with what breaks because of it.",
            file=sys.stderr,
        )
        return 1

    if args.gate:
        print("Gate passed — no unmounted router beyond the known ones.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
