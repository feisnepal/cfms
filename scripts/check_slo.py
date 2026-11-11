#!/usr/bin/env python
"""Post-deploy SLO gate — the second half of R-4 (H5.7).

R-4 reads: *error rate and p95 within SLO for 15 minutes post-deploy, else
auto-rollback.* The smoke suite (R-3) answers "is it serving?" in one moment.
This answers the different question of whether it has *kept* serving, which is
the failure smoke cannot see: a deploy that works for the first request and
degrades under real traffic.

Fifteen minutes is a deliberate compromise. Short enough that few users meet a
bad deploy; long enough that one unlucky request does not roll back a good one.

**A gate that cannot evaluate must not report success.** If Prometheus is
unreachable — which it will be until the monitoring profile runs — this exits 2
and says so, rather than exiting 0 and letting a silent no-op stand in for a
passing check. The caller decides whether an unevaluated gate blocks the deploy;
it must not decide for itself by returning green.

Usage:
    python scripts/check_slo.py --prometheus http://localhost:9090
    python scripts/check_slo.py --prometheus ... --window 15m --allow-missing
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

# runbooks/SLO.md §1. Availability target 99.5% → an error budget of 0.5%.
ERROR_BUDGET = 0.005
# The page-severity burn rate from the alerting table. Rolling back on anything
# gentler would revert deploys that are merely unlucky.
PAGE_BURN_RATE = 14.4
READ_P95_OBJECTIVE_S = 1.5
WRITE_P95_OBJECTIVE_S = 3.0

EXIT_OK, EXIT_VIOLATED, EXIT_CANNOT_EVALUATE = 0, 1, 2


def query(prom: str, expr: str, timeout: int = 15) -> float | None:
    """Instant query. `None` means "no data", which is not the same as zero."""
    url = f"{prom.rstrip('/')}/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    with urllib.request.urlopen(url, timeout=timeout) as r:
        payload = json.loads(r.read())
    if payload.get("status") != "success":
        raise RuntimeError(payload.get("error", "query failed"))
    result = payload["data"]["result"]
    if not result:
        return None
    return float(result[0]["value"][1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prometheus", required=True)
    ap.add_argument("--window", default="15m", help="lookback, e.g. 15m")
    ap.add_argument("--allow-missing", action="store_true",
                    help="treat an unreachable Prometheus as a pass (records a warning)")
    args = ap.parse_args()
    w = args.window

    excl = 'handler!~"/health|/ready|/metrics"'
    checks = [
        (
            "error rate",
            f'(sum(rate(http_requests_total{{{excl},status=~"5.."}}[{w}])) '
            f'/ sum(rate(http_requests_total{{{excl}}}[{w}]))) or vector(0)',
            PAGE_BURN_RATE * ERROR_BUDGET,
            lambda v, t: v <= t,
            "{v:.3%} of requests failing (budget burn threshold {t:.3%})",
        ),
        (
            "read p95",
            f'histogram_quantile(0.95, sum by (le) (rate('
            f'http_request_duration_seconds_bucket{{method="GET",{excl}}}[{w}])))',
            READ_P95_OBJECTIVE_S,
            lambda v, t: v <= t,
            "{v:.2f}s (objective {t:.2f}s)",
        ),
        (
            "write p95",
            f'histogram_quantile(0.95, sum by (le) (rate('
            f'http_request_duration_seconds_bucket{{method=~"POST|PUT|PATCH|DELETE"}}[{w}])))',
            WRITE_P95_OBJECTIVE_S,
            lambda v, t: v <= t,
            "{v:.2f}s (objective {t:.2f}s)",
        ),
    ]

    print(f"SLO gate — {w} window against {args.prometheus}")
    violations = []
    for name, expr, threshold, ok_if, fmt in checks:
        try:
            value = query(args.prometheus, expr)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            msg = f"Prometheus unreachable: {e}"
            if args.allow_missing:
                print(f"  [SKIP] {name:12s} {msg}")
                print("\n  ::warning::SLO gate could not evaluate; --allow-missing let the deploy stand")
                return EXIT_OK
            print(f"\n  [ERROR] {msg}")
            print("  The gate could not evaluate. It is NOT reporting success — see runbooks/SLO.md §5.")
            return EXIT_CANNOT_EVALUATE
        except RuntimeError as e:
            print(f"  [SKIP] {name:12s} query rejected: {e}")
            continue

        if value is None:
            # No data is genuinely ambiguous: no traffic, or no scrape. Neither
            # is a violation, and neither is evidence of health.
            print(f"  [----] {name:12s} no data in the last {w}")
            continue

        good = ok_if(value, threshold)
        print(f"  [{'PASS' if good else 'FAIL'}] {name:12s} " + fmt.format(v=value, t=threshold))
        if not good:
            violations.append(name)

    if violations:
        print(f"\n  SLO VIOLATED: {', '.join(violations)} — this deploy should be rolled back")
        return EXIT_VIOLATED
    print("\n  Within SLO.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
