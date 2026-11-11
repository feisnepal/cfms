#!/usr/bin/env python
"""Response-model coverage ratchet — fail on NEW un-typed routes (H4.8).

The audit's S3-47 measured 138 ``response_model=`` declarations across 405
routes (34%): most handlers return whatever they built, so the OpenAPI
contract (and the frontend types generated from /openapi.json) documents a
fraction of the API, and a handler that changes shape is free to do so
silently.

This gate makes that number a ratchet, like the ruff/black/eslint/tsc
baselines: the current count of routes lacking a response model is recorded,
and CI fails if it *increases*. It never blocks a fix; ``--update`` re-records
the (smaller) count. Response models are added route by route on the backlog,
and each one shrinks the baseline until it hits zero.

**What counts:** every HTTP route under the canonical ``/api/v1`` namespace
whose ``APIRoute.response_model is None``. The legacy ``/api`` shim is
excluded so the same logical route is not counted twice (S3-48). File-style
routes with no declared model are included — WinRT — because OpenAPI lists
them and the frontend generator consumes that list. ``response_model=None``
passed explicitly is the same as omitted: it means "no response model".

Deliberately mirrors `frontend/scripts/check-tsc-baseline.mjs` and
`check_ruff_baseline.py` — same baseline shape, same ``--update`` flag, same
"expected to SHRINK" contract.

Usage:
    python scripts/check_response_model_baseline.py            # gate
    python scripts/check_response_model_baseline.py --update   # re-record (refuses growth)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "response-model-baseline.json"
API_V1_PREFIX = "/api/v1"

sys.path.insert(0, str(ROOT))


def url_of_untyped_routes(app, prefix: str = API_V1_PREFIX) -> dict[str, str]:
    """Routes lacking a response model, keyed `METHOD path` -> description.

    Walks the app the same way `tests/conftest.py` does, because a flat scan
    of `app.routes` misses the nested-routers FastAPI keeps as
    `_IncludedRouter` wrappers — exactly how a route gate ends up passing
    against the defect it exists to catch. The wrapper carries the mount
    prefix in `include_context.prefix` while the leaf `APIRoute` holds the
    unprefixed path, so both halves are needed to reconstruct a route URL.
    """
    from fastapi.routing import APIRoute  # noqa: PLC0415

    missing: dict[str, str] = {}

    def walk(node, mount: str = "") -> None:
        for route in getattr(node, "routes", []):
            included = getattr(route, "include_context", None)
            if included is not None:
                # _IncludedRouter: the mount prefix lives here; the real router
                # (with unprefixed leaf paths) sits behind it.
                sub = included.prefix or ""
                walk(included.included_router, f"{mount}{sub}")
                continue
            own = f"{mount}{getattr(route, 'path', '')}"
            if isinstance(route, APIRoute) and own.startswith(prefix) and route.response_model is None:
                desc = getattr(route, "summary", None) or getattr(route, "description", None) or ""
                if desc and "\n" in desc:
                    desc = desc.splitlines()[0]
                first = next(iter(route.methods or set()), "")
                key = f"{first.upper():<6} {own}"
                missing.setdefault(key, desc.strip()[:120])
            walk(route, mount)
            walk(getattr(route, "original_router", None), mount)
            walk(getattr(route, "app", None), mount)

    walk(app)
    return dict(sorted(missing.items()))


def collect() -> dict[str, str]:
    """Untyped route inventory for the live app (H4.8 gate input)."""
    from app.main import app  # noqa: PLC0415 -- import must follow sys.path

    return url_of_untyped_routes(app)


def load() -> dict:
    if not BASELINE.exists():
        return {"total": 0, "routes": {}}
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def save(routes: dict[str, dict]) -> None:
    BASELINE.write_text(json.dumps({
        "_comment": (
            "API routes LACKING a response_model, keyed 'METHOD path'. "
            "Expected to SHRINK as models are added (H4.8, S3-47). "
            "Regenerate with: python scripts/check_response_model_baseline.py --update"
        ),
        "total": len(routes),
        "routes": routes,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--update", action="store_true",
                        help="re-record the baseline; refuses to record growth")
    args = parser.parse_args()

    found = collect()
    baseline = load()
    known: dict[str, dict] = baseline.get("routes", {})

    new = {k: v for k, v in found.items() if k not in known}
    fixed = {k: v for k, v in known.items() if k not in found}

    total_now, total_was = len(found), baseline.get("total", 0)
    print(f"routes without response_model: {total_now}   baseline: {total_was}")

    if args.update:
        if not BASELINE.exists():
            save(found)
            print(f"baseline created with {total_now} route(s) to type")
            return 0
        if new:
            print("\nRefusing to record growth — the baseline may only shrink:",
                  file=sys.stderr)
            for key in new:
                print(f"  {key}", file=sys.stderr)
            print("\nAdd a response_model to these routes, or record them "
                  "deliberately by editing response-model-baseline.json by hand.",
                  file=sys.stderr)
            return 1
        save(found)
        print(f"baseline updated: {total_was} -> {total_now}")
        return 0

    if new:
        print(f"\nFAILED: {len(new)} route(s) added without a response model:",
              file=sys.stderr)
        for key in new:
            print(f"  {key}", file=sys.stderr)
        print("\nAdd a response_model to each, or run --update if deliberate.",
              file=sys.stderr)
        return 1

    if fixed:
        print(f"\n{len(fixed)} route(s) gained a response model since the baseline. "
              f"Run --update to lock that in so they cannot come back.")

    print("passed — no new un-typed routes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())