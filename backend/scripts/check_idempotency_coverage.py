#!/usr/bin/env python
"""Gate G-SYNC-1: every mobile-facing write is replay-safe (H2.17 · S2-64).

A field device uploads over a link that drops, then retries -- because a
well-built offline client **must** retry. Without a durable record of what has
already been accepted, the retry writes a second copy of the same trees, plots
or households, and those rows feed the volume, biomass and carbon figures in a
statutory document. A duplicate tree looks exactly like a real tree, so nothing
surfaces it.

`services/idempotency.py` fixed the mechanism. It did not fix the reach: it
landed on **2 of 194 mutating routes**, the same two the Redis version had. The
guard now travels with the router (`route_class=IdempotentRoute`), and this is
what stops the reach from quietly shrinking again.

**Why it checks the live route table and not the source.** `route_class` is set
once per router and is inherited by every route added to it, including the one
added next month -- so grepping for a decorator finds nothing to count. FastAPI
also preserves the class through `include_router`, and the API is mounted twice
(`/api/v1` and the legacy `/api`), so only the assembled app knows the truth.
Two traps make a naive walk wrong, both documented in
`check_unmounted_routers.py`: `app.routes` holds 14 entries out of 372, and the
included routers hang off `original_router`. This walk recurses through both.

**What fails the build**

* a route in a MOBILE_WRITE module that is not an `IdempotentRoute` -- someone
  built a second router in that module and did not pass `route_class`;
* a module with mutating routes that appears in neither list -- a new API
  module forces the "is this a field write?" question to be answered once,
  rather than defaulted to no by silence.

Clearing a module out of `EXEMPT` and into `MOBILE_WRITE_MODULES` is how
coverage gets locked in permanently.

Usage:
    python scripts/check_idempotency_coverage.py            # report
    python scripts/check_idempotency_coverage.py --gate     # exit 1 on a gap
    python scripts/check_idempotency_coverage.py --routes   # list every route
"""
from __future__ import annotations

import argparse
import sys
import warnings
from collections import defaultdict
from pathlib import Path

# The field data collection surface, from `Offline_mobile_tool_preparation_report.md`
# section 2 -- the seven modules an offline client captures at source. The
# mobile client itself is not in this repository and has never been audited
# (task 8.0), so this list is derived from what the backend stores, not from
# what the client calls. When 8.0 lands, reconcile the two.
MOBILE_WRITE_MODULES: dict[str, str] = {
    "field_inventory": "trees by stand type per sample plot -- DBH, height, species, count",
    "inventory": "tree inventory ingest; the same rows under a different entrance",
    "fieldbook": "boundary verification points, captured standing at the boundary",
    "sampling": "sampling designs and per-point marks, recorded at the plot",
    "biodiversity": "species observations with photo and GPS",
    "ntfp": "NTFP sample-plot design now; the plot records (counts, fresh and dry weights) are captured at the plot",
    "forum": "questions, answers and votes typed on a flaky connection are retried; a replay returns the first result instead of a second post",
    "household_info": "door-to-door household survey -- the village side",
    "forest_committee": "committee rosters, filled offline and synced later",
    "yearly_activities": "activity drawn features, which can be field-captured",
    "yearly_plan": "the yearly-plan facade: drawn activity features and plan-line edits, which can be field-captured",
    "workspace": "digitize flush and finalize -- the original two call sites",
}

# Mutating routes that are NOT part of the field-capture surface. Each entry
# states why, because "not mobile" is a claim about a client nobody in this
# repository can see, and an unexplained exemption is how the reach shrinks.
EXEMPT: dict[str, str] = {
    "chat": (
        "assistant access: a member asks, a super admin approves / revokes / sets a cap. Web screens used online; every write sets a "
        "status or a number, so repeating a request changes nothing. The exception is POST messages: a repeat is a second question and is "
        "charged, but it is capped per user per day and limited to 10 a minute, and the panel is web only (D14). No field device writes "
        "through this module."
    ),
    "tiles": (
        "its only write is the workspace's 'Update attribute' command (POST attribute-components/run): an owner-only desktop "
        "action that recomputes derived values from stored data. Running it twice yields the same values, and no field "
        "device writes through this module."
    ),
    "auth": (
        "login, refresh, logout. Replaying a recorded auth response would hand "
        "back a token that has since been rotated or revoked -- idempotency "
        "here is actively wrong, not merely unnecessary."
    ),
    "auth_verification": (
        "sign-in by phone code / Facebook, one-time codes and links, password reset. A replayed response would hand back a spent "
        "token or a consumed code's result -- idempotency here is actively wrong, like login."
    ),
    "admin_users": (
        "the super-admin user panel (assign a role). A web screen used online by one or two people; setting the same role twice is a "
        "no-op by construction, so a replayed request changes nothing and logs nothing."
    ),
    "forests": "CFOP creation and metadata -- office work, on a desktop, online",
    "forest_summary": (
        "the plan decisions on the forest summary panel (landslide method, block orientation, household placement). A web "
        "screen used online by the owner or the DFO. Each write is an upsert keyed by (forest, question, scope), so a replayed "
        "request overwrites one row with the same answer instead of accumulating."
    ),
    "forest_metadata": (
        "the facts a person writes down about a forest -- name, group, CF "
        "codes, fiscal years -- for the report cover page. Registered once, in "
        "the office, like `forests` above; not captured repeatedly per plot. And "
        "the absence of IdempotentRoute is not a hole here: the write is an "
        "upsert against a UNIQUE calculation_id, so a replayed request "
        "overwrites one row with the same values instead of accumulating."
    ),
    "blocks": "forest structure editing in the map workspace (office)",
    "compartments": "forest structure editing in the map workspace (office)",
    "editing": "the unified editing toolset -- office map work on a large screen",
    "fire_lines": (
        "the fire-line tick-list and draw tool in the map workspace -- office map work. Ticking is a set (the same list twice is "
        "the same state), regenerate is idempotent by construction, and a drawn line carries a client_id so a replay returns the "
        "first result instead of a second strip."
    ),
    "boundary": "overlap preview, confirm and dispute; a DFO desk workflow",
    "calculation_lifecycle": "submit, approve, reject, unlock -- DFO desk workflow",
    "operational_plans": "operational plan authoring; office document work",
    "op_table_catalog": "OP document table definitions; office document work",
    "reports": "AI report generation; long-running, office-initiated",
    "all_tree_exports": "export generation. Responses are files, which cannot be replayed",
    "species": "reference data administration",
    "dbh_classes": "reference data administration",
    "tree_models": "tree distribution model administration",
    "translations": "i18n CSV overlay administration",
    "user_group": "user group map administration (office)",
    "uploads": "POST /uploads/classify and /uploads/csv-columns only READ the file they are sent and write nothing, so a retry is harmless",
    "workspace_layout": "per-user dock panel sizes -- a UI preference, not field data",
    "soil_erosion_params": (
        "RUSLE parameter tuning for one forest -- office analysis config, "
        "not field data; the write is a small idempotent JSONB patch"
    ),
    "soil_erosion_profiles": (
        "org-wide RUSLE parameter presets -- super-admin reference data, "
        "not field capture"
    ),
    "hazard_vuln_params": (
        "landslide-hazard / household-vuln parameter tuning for one forest -- "
        "office analysis config, not field data; a small idempotent JSONB patch"
    ),
    "hazard_vuln_profiles": (
        "org-wide landslide-hazard / household-vuln presets -- super-admin "
        "reference data, not field capture"
    ),
    "structure": (
        "structural-change impact preview (FS-4a.15) -- POST only because "
        "the payload (feature_ids + an optional proposed geometry) doesn't "
        "fit in a query string; the endpoint never writes anything, it is "
        "a read-only dry-run"
    ),
    "hazard_erosion": (
        "the Hazard & Erosion context aggregator -- a read summary + a "
        "cache-bust recompute; office analysis, not field data"
    ),
    "cost_benefit": (
        "operational-plan financial analysis -- scenario / cost / benefit "
        "editing on a desktop, office document work, not field capture"
    ),
    "cba_rate_profiles": (
        "org-wide default depot/market rates -- super-admin reference data, "
        "not field capture"
    ),
    "sustainable_fm": (
        "SFM classification read + per-forest SfmParams tuning and per-block "
        "type overrides -- office analysis config, not field capture; the "
        "writes are small idempotent JSONB patches on result_data"
    ),
    "sfm_prescriptions": (
        "the Sustainable-FM Schedule-1 as editable data -- super-admin "
        "reference data (the 14 forest-type rows), not field capture"
    ),
    "sfm_profiles": (
        "org-wide SFM parameter presets -- super-admin reference data, "
        "not field capture"
    ),
}

# Geometry writes are the honest grey area: `blocks`, `compartments`, `editing`
# and `boundary` all write shapes, and the offline report calls drawn features
# "partially" field-capturable. They are exempt because today only a desktop
# map client reaches them. Revisit each when 8.0 says what the mobile client
# actually posts to.


def audit(root: Path):
    """Return module -> {"guarded": [...], "plain": [...]} for mutating routes."""
    warnings.filterwarnings("ignore")
    sys.path.insert(0, str(root))

    from app.core.idempotent_route import (  # noqa: PLC0415 -- after sys.path
        MUTATING_METHODS,
        IdempotentRoute,
    )
    from app.main import app  # noqa: PLC0415

    def walk(node, seen):
        """Every route reachable from the app, through both mounts.

        `original_router` is the one easy to miss: FastAPI wraps an included
        router in `_IncludedRouter`, and without following it most of the API
        is invisible.
        """
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        for route in getattr(node, "routes", []):
            yield route
            yield from walk(route, seen)
            yield from walk(getattr(route, "original_router", None), seen)
            yield from walk(getattr(route, "app", None), seen)

    found: dict[str, dict[str, list]] = defaultdict(lambda: {"guarded": [], "plain": []})
    # The same endpoint is served under /api/v1 and /api. Counting it twice
    # would double every number and say nothing extra.
    seen_endpoints: set = set()
    for route in walk(app.router, set()):
        endpoint = getattr(route, "endpoint", None)
        methods = getattr(route, "methods", None) or set()
        if endpoint is None or not (methods & MUTATING_METHODS):
            continue
        identity = (endpoint, frozenset(methods))
        if identity in seen_endpoints:
            continue
        seen_endpoints.add(identity)
        module = endpoint.__module__.rsplit(".", 1)[-1]
        bucket = "guarded" if isinstance(route, IdempotentRoute) else "plain"
        verbs = ",".join(sorted(methods & MUTATING_METHODS))
        found[module][bucket].append(f"{verbs:18s} {getattr(route, 'path', '?')}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--gate", action="store_true",
                        help="exit 1 on an unguarded mobile write or an unclassified module")
    parser.add_argument("--routes", action="store_true",
                        help="list every mutating route, not just the counts")
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()

    found = audit(args.root)
    guarded_total = sum(len(v["guarded"]) for v in found.values())
    plain_total = sum(len(v["plain"]) for v in found.values())

    print(f"mutating routes: {guarded_total + plain_total} "
          f"({guarded_total} idempotent, {plain_total} not)\n")

    gaps: list[str] = []
    unclassified: list[str] = []
    promotable: list[str] = []

    print("mobile-facing writes (must be idempotent)")
    for module in sorted(MOBILE_WRITE_MODULES):
        counts = found.get(module)
        if counts is None:
            # Not an error: the module may define no mutating route at all.
            print(f"  --   app/api/{module}.py — no mutating routes served")
            continue
        plain = counts["plain"]
        mark = "GAP " if plain else "ok  "
        print(f"  {mark} app/api/{module}.py — "
              f"{len(counts['guarded'])} guarded, {len(plain)} unguarded")
        print(f"         {MOBILE_WRITE_MODULES[module]}")
        if plain:
            gaps.append(module)
            for line in plain:
                print(f"         UNGUARDED  {line}")
        elif args.routes:
            for line in counts["guarded"]:
                print(f"         {line}")

    print("\nexempt (not part of the field-capture surface)")
    for module in sorted(found):
        if module in MOBILE_WRITE_MODULES:
            continue
        counts = found[module]
        if module not in EXEMPT:
            unclassified.append(module)
            print(f"  NEW  app/api/{module}.py — "
                  f"{len(counts['plain']) + len(counts['guarded'])} mutating route(s), "
                  f"not classified")
            continue
        if not counts["plain"] and counts["guarded"]:
            promotable.append(module)
        print(f"  ok   app/api/{module}.py — "
              f"{len(counts['plain']) + len(counts['guarded'])} mutating route(s)")
        print(f"         reason: {EXEMPT[module]}")
        if args.routes:
            for line in counts["plain"] + counts["guarded"]:
                print(f"         {line}")

    if promotable:
        print(f"\nThese exempt modules are now fully guarded: {', '.join(promotable)}")
        print("Move them into MOBILE_WRITE_MODULES so the coverage cannot regress.")

    if not args.gate:
        return 0

    if gaps:
        print("\nGATE FAILED (G-SYNC-1): a mobile-facing write is not replay-safe.")
        print(f"  modules: {', '.join(gaps)}")
        print("  Build that module's router with "
              "`APIRouter(route_class=IdempotentRoute)`. A retry that reaches an")
        print("  unguarded route writes the field data a second time, and nothing "
              "downstream can tell the copies apart.")
        return 1

    if unclassified:
        print("\nGATE FAILED (G-SYNC-1): a module with mutating routes is unclassified.")
        print(f"  modules: {', '.join(unclassified)}")
        print("  Add it to MOBILE_WRITE_MODULES (and give its router "
              "`route_class=IdempotentRoute`) if a field device writes to it,")
        print("  or to EXEMPT with the reason it does not. Silence defaults it "
              "to unprotected, which is the failure this gate exists to stop.")
        return 1

    print("\nGATE PASSED: every mobile-facing write is replay-safe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
