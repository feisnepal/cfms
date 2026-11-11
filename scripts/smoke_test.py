#!/usr/bin/env python
"""Post-deploy smoke suite — gate R-3, and what makes R-4's rollback possible.

You cannot roll back on failure if you cannot detect failure. This is the
detector: a small set of checks that answer "is the thing that just deployed
actually serving?", fast enough to run in a deploy pipeline and specific enough
that a failure names its own cause.

Deliberately narrow. It is not the test suite — that ran in CI against the
commit. It asks a different question: *this build, on this host, right now, with
this database and this configuration.* The failures it exists to catch are the
ones only a real deployment produces — a migration that did not run, a database
the container cannot reach, an auth dependency that got dropped, a frontend
built against the wrong API origin.

Every check is read-only. Nothing here writes to the deployed system, so it is
safe to run against production.

Usage:
    python scripts/smoke_test.py --api http://localhost:8001
    python scripts/smoke_test.py --api https://api.example.np --web https://example.np
    python scripts/smoke_test.py --api ... --expect-revision 051_app_tables_to_public
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    critical: bool = True
    elapsed_ms: int = 0


@dataclass
class Smoke:
    api: str
    web: str | None = None
    timeout: int = 15
    results: list[Result] = field(default_factory=list)

    # -- plumbing ----------------------------------------------------------
    def _get(self, url: str, headers: dict | None = None):
        req = urllib.request.Request(url, headers=headers or {})
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read(), int((time.time() - started) * 1000)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), int((time.time() - started) * 1000)
        except Exception as e:  # connection refused, DNS, TLS, timeout
            return None, str(e).encode(), int((time.time() - started) * 1000)

    def check(self, name: str, critical: bool = True):
        def wrap(fn):
            started = time.time()
            try:
                ok, detail = fn()
            except Exception as e:
                ok, detail = False, f"{type(e).__name__}: {e}"
            self.results.append(
                Result(name, ok, detail, critical, int((time.time() - started) * 1000))
            )
        return wrap

    # -- the checks --------------------------------------------------------
    def run(self, expect_revision: str | None = None) -> bool:
        api = self.api.rstrip("/")

        # The application is answering at all, and can reach its database.
        # `/health` reports the connection, so this distinguishes "container is
        # up" from "container can actually serve" — the difference that decides
        # whether a deploy succeeded.
        @self.check("api /health reports a connected database")
        def _():
            status, body, _ = self._get(f"{api}/health")
            if status != 200:
                return False, f"HTTP {status}"
            data = json.loads(body)
            if data.get("database") != "connected":
                return False, f"database={data.get('database')!r}"
            return True, f"status={data.get('status')} version={data.get('version')}"

        # Authentication is still enforced. A deploy that drops an auth
        # dependency looks perfectly healthy — this is the check that notices.
        # Gate G-SEC-1 asserts this at build time; here it is asserted about the
        # thing actually running.
        @self.check("a protected route refuses an anonymous caller")
        def _():
            status, _, _ = self._get(f"{api}/api/auth/me")
            if status in (401, 403):
                return True, f"HTTP {status} as expected"
            return False, f"HTTP {status} — protected route answered without a token"

        # H2.15 body limits are live. Cheap to verify and it proves the
        # middleware stack assembled, not just the routes.
        @self.check("ingress limits are enforced", critical=False)
        def _():
            req = urllib.request.Request(
                f"{api}/api/auth/login", method="POST",
                headers={"content-type": "application/json", "content-length": "999999999"},
                data=b'{"a":1}',
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return False, f"oversized body accepted (HTTP {r.status})"
            except urllib.error.HTTPError as e:
                return (e.code == 413), f"HTTP {e.code}" + ("" if e.code == 413 else " — expected 413")

        # Docs must not be public outside development (H2.10 / S3-11).
        @self.check("API docs are not exposed", critical=False)
        def _():
            status, _, _ = self._get(f"{api}/docs")
            if status in (404, 401, 403):
                return True, f"HTTP {status}"
            return False, f"HTTP {status} — /docs is reachable; is DEBUG on in this environment?"

        # The migration that was supposed to run, ran. A deploy whose migration
        # step silently no-ops is the failure this catches — the application
        # starts fine and misbehaves later, against a schema it does not expect.
        if expect_revision:
            @self.check(f"database is at revision {expect_revision}")
            def _():
                status, body, _ = self._get(f"{api}/health")
                if status != 200:
                    return False, f"cannot read /health: HTTP {status}"
                data = json.loads(body)
                got = data.get("alembic_revision") or data.get("revision")
                if got is None:
                    return False, ("/health does not report a revision — add one, or drop "
                                   "--expect-revision from the pipeline")
                return (got == expect_revision), f"reported {got!r}"

        # The frontend is served and is the built bundle, not a directory index
        # or an nginx default page.
        if self.web:
            web = self.web.rstrip("/")

            @self.check("web root serves the built application")
            def _():
                status, body, _ = self._get(web + "/")
                if status != 200:
                    return False, f"HTTP {status}"
                text = body.decode("utf-8", "replace").lower()
                if "<div id=\"root\"" not in text and "<div id=root" not in text:
                    return False, "response is not the application shell"
                return True, f"{len(body):,} bytes"

            # The bundle calls same-origin /api/*, so nginx must proxy it. This
            # is the check that catches the S1-26 class of defect: both
            # containers healthy, and the frontend unable to reach the backend.
            @self.check("web proxies /api to the backend")
            def _():
                status, _, _ = self._get(f"{web}/api/v1/")
                if status is None:
                    return False, "no response through the web origin"
                if status >= 500:
                    return False, f"HTTP {status} — proxy target is wrong or down"
                return True, f"HTTP {status}"

        return self.report()

    def report(self) -> bool:
        width = max(len(r.name) for r in self.results)
        failed_critical = 0
        print()
        for r in self.results:
            mark = "PASS" if r.ok else ("FAIL" if r.critical else "WARN")
            if not r.ok and r.critical:
                failed_critical += 1
            print(f"  [{mark}] {r.name:{width}s}  {r.detail}")
        passed = sum(1 for r in self.results if r.ok)
        print(f"\n  {passed}/{len(self.results)} checks passed")
        if failed_critical:
            print(f"  {failed_critical} CRITICAL failure(s) — this deploy should be rolled back")
        return failed_critical == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", required=True, help="base URL of the deployed API")
    ap.add_argument("--web", help="base URL of the deployed frontend, if separate")
    ap.add_argument("--expect-revision", help="alembic revision the deploy should have applied")
    ap.add_argument("--timeout", type=int, default=15)
    ap.add_argument("--retries", type=int, default=6,
                    help="attempts while the deployment comes up, 5s apart")
    args = ap.parse_args()

    # A container takes a moment to become ready; failing on the first refused
    # connection would make every deploy look broken.
    for attempt in range(1, args.retries + 1):
        status, _, _ = Smoke(args.api, timeout=args.timeout)._get(args.api.rstrip("/") + "/health")
        if status is not None:
            break
        print(f"  waiting for {args.api} ... ({attempt}/{args.retries})")
        time.sleep(5)
    else:
        print(f"\n  [FAIL] {args.api} never answered after {args.retries} attempts")
        return 1

    smoke = Smoke(args.api, args.web, args.timeout)
    return 0 if smoke.run(args.expect_revision) else 1


if __name__ == "__main__":
    raise SystemExit(main())
