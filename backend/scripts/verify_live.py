#!/usr/bin/env python
"""Verify the hardening behaviours against a RUNNING backend.

Why this is not part of `scripts/smoke_test.py`
-----------------------------------------------
That script states its contract in its own docstring: "Every check is
read-only. Nothing here writes to the deployed system, so it is safe to run
against production." Every check here WRITES -- creating a household twice,
replaying an upload, sending a stale version. Adding them there would quietly
destroy a guarantee somebody is relying on when they point it at production.
Different question, different tool.

**This script is not safe to run against production.** It creates scratch
records and deletes them again, and a failure part-way through can leave one
behind. Point it at a development instance.

Why it exists
-------------
21 hardening rows sit built-but-unverified, and the queue only grows. Six were
terminal one-liners (now `bash scripts/ci.sh lint gates`). These four were
"open the app and try it", which is an afternoon that has to be repeated after
every change, and therefore is not repeated.

The pytest suite already covers all four against the TEST database. This asks
the different question that manual testing was really for: does it work on the
live instance, with migrations actually applied to `cf_db`, the real
configuration, and the real server -- the class of failure a test harness
mocks away.

Usage:
    python scripts/verify_live.py --api http://localhost:8001
    python scripts/verify_live.py --api http://localhost:8001 \
        --email demo@forest.com --password Demo1234
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field

GREEN, RED, YELLOW, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


@dataclass
class Outcome:
    name: str
    task: str
    ok: bool
    detail: str = ""


@dataclass
class Verifier:
    api: str
    email: str
    password: str
    timeout: int = 20
    token: str = ""
    results: list = field(default_factory=list)
    _scratch: list = field(default_factory=list)

    # -- plumbing ----------------------------------------------------------
    def _call(self, method, path, body=None, headers=None, token=True):
        url = f"{self.api.rstrip('/')}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token and self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode() or "{}"
                return r.status, dict(r.headers), json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode() or "{}"
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = {"raw": raw[:400]}
            return e.code, dict(e.headers), parsed

    def record(self, name, task, ok, detail=""):
        self.results.append(Outcome(name, task, ok, detail))
        mark = f"{GREEN}PASS{OFF}" if ok else f"{RED}FAIL{OFF}"
        print(f"  {mark}  [{task}] {name}")
        if detail and not ok:
            print(f"        {detail}")

    # -- setup -------------------------------------------------------------
    def login(self) -> bool:
        status, _h, body = self._call(
            "POST", "/api/v1/auth/login",
            {"email": self.email, "password": self.password}, token=False,
        )
        self.token = (body or {}).get("access_token", "")
        if status != 200 or not self.token:
            print(f"{RED}cannot log in as {self.email} ({status}){OFF}")
            return False
        return True

    def a_calculation(self):
        """A calculation to hang scratch households off. Reuses an existing one
        rather than creating a forest: this verifies behaviour, and creating a
        CFOP has side effects that outlive the run."""
        status, _h, body = self._call("GET", "/api/v1/forests/calculations")
        if status != 200:
            return None
        items = body if isinstance(body, list) else body.get("items") or body.get("data") or []
        return items[0].get("id") if items else None

    # -- checks ------------------------------------------------------------
    def check_correlation_id(self):
        """H3.9. Before it, the ID reached a response header and nothing else --
        `logging_config.py` read an attribute nothing ever set."""
        sent = f"verify-{uuid.uuid4()}"
        status, headers, _b = self._call(
            "GET", "/api/v1/auth/me", headers={"X-Correlation-ID": sent},
        )
        got = headers.get("X-Correlation-ID") or headers.get("x-correlation-id")
        self.record(
            "the correlation ID a client sends comes back", "3.9",
            status == 200 and got == sent,
            f"status={status} sent={sent} got={got}",
        )

    def check_threadpool_gauge(self):
        """H3.3. The threadpool is where requests queue now that H3.1 moved 290
        handlers into it, so its size is the leading saturation indicator.

        This asserts a real number, not merely that the gauge exists. It
        reported `-1.0` -- the "could not read" sentinel -- on every scrape
        since it was written, because `current_default_thread_limiter()` raises
        outside the async context and a Prometheus scrape arrives on a worker
        thread. A check for "the metric is present" would have passed
        throughout.
        """
        try:
            req = urllib.request.Request(f"{self.api.rstrip('/')}/metrics")
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = r.read().decode()
        except Exception as exc:  # noqa: BLE001 -- reported as a failed check
            self.record("the threadpool gauge reports a real size", "3.3", False,
                        f"could not read /metrics: {exc}")
            return

        total = None
        for line in body.splitlines():
            if line.startswith("cfms_threadpool_total"):
                try:
                    total = float(line.split()[-1])
                except ValueError:
                    pass
                break
        ok = total is not None and total > 0
        self.record("the threadpool gauge reports a real size, not the -1 sentinel",
                    "3.3", ok, f"cfms_threadpool_total={total}")

    def check_duplicate_household(self, calc_id):
        """H8.6. `house_no` was already the key the upload path upserts on; it
        was simply never declared, so nothing stopped a second write."""
        house_no = 90000 + uuid.uuid4().int % 9000
        payload = {"house_no": house_no, "surname": "VerifyScratch",
                   "female_count": 1, "male_count": 1}
        s1, _h1, b1 = self._call("POST", f"/api/v1/household/calculations/{calc_id}/households", payload)
        if s1 != 200:
            self.record("a duplicate house number is refused", "8.6", False,
                        f"could not create the first household: {s1} {str(b1)[:200]}")
            return None
        self._scratch.append(b1.get("id"))

        s2, _h2, b2 = self._call("POST", f"/api/v1/household/calculations/{calc_id}/households", payload)
        detail = (b2 or {}).get("detail") or {}
        message = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        # 409 alone is not enough: the point of the task was a message that
        # says which record already exists, not a generic "Bad request".
        ok = s2 == 409 and "house number" in message.lower()
        self.record("a duplicate house number is refused, and says so", "8.6", ok,
                    f"status={s2} message={message[:160]!r}")
        return b1

    def check_optimistic_lock(self, household):
        """H8.2. Two enumerators editing one household used to produce a silent
        last-write-wins overwrite, with no version to find it by afterwards."""
        if not household:
            self.record("a stale version is refused with both versions", "8.2", False,
                        "no scratch household to test against")
            return
        hid = household["id"]
        s1, _h, b1 = self._call("PUT", f"/api/v1/household/households/{hid}",
                                {"surname": "First", "version": household.get("version", 0)})
        if s1 != 200:
            self.record("a stale version is refused with both versions", "8.2", False,
                        f"the first versioned write failed: {s1} {str(b1)[:200]}")
            return
        s2, _h2, b2 = self._call("PUT", f"/api/v1/household/households/{hid}",
                                 {"surname": "Second", "version": household.get("version", 0)})
        detail = (b2 or {}).get("detail") or {}
        ok = (s2 == 409 and isinstance(detail, dict)
              and detail.get("code") == "VERSION_CONFLICT"
              and "your_version" in detail and "current_version" in detail)
        self.record("a stale version is refused, carrying BOTH versions", "8.2", ok,
                    f"status={s2} detail={str(detail)[:200]}")

    def check_idempotent_replay(self, calc_id):
        """H2.17. A field device on a dropping link must retry; without a
        durable record the retry writes the records a second time."""
        key = f"verify-{uuid.uuid4()}"
        house_no = 91000 + uuid.uuid4().int % 9000
        payload = {"house_no": house_no, "surname": "VerifyReplay",
                   "female_count": 1, "male_count": 1}
        path = f"/api/v1/household/calculations/{calc_id}/households"
        s1, h1, b1 = self._call("POST", path, payload, headers={"Idempotency-Key": key})
        if s1 != 200:
            self.record("a replayed write returns the first response", "2.17", False,
                        f"the first write failed: {s1} {str(b1)[:200]}")
            return
        self._scratch.append(b1.get("id"))
        s2, h2, b2 = self._call("POST", path, payload, headers={"Idempotency-Key": key})
        replay = (h2.get("Idempotent-Replay") or h2.get("idempotent-replay") or "").lower()
        same_row = b1.get("id") == b2.get("id")
        ok = s2 == 200 and replay == "true" and same_row
        self.record("a replayed write returns the first response, not a second row",
                    "2.17", ok,
                    f"status={s2} Idempotent-Replay={replay!r} same_id={same_row}")

    # -- cleanup -----------------------------------------------------------
    def cleanup(self):
        removed = 0
        for hid in [h for h in self._scratch if h]:
            status, _h, _b = self._call("DELETE", f"/api/v1/household/households/{hid}")
            if status in (200, 204, 404):
                removed += 1
        if self._scratch:
            print(f"{DIM}  cleaned up {removed}/{len(self._scratch)} scratch household(s){OFF}")
            if removed != len(self._scratch):
                print(f"{YELLOW}  some scratch records could not be removed — "
                      f"look for surname 'VerifyScratch' / 'VerifyReplay'{OFF}")

    def report(self) -> bool:
        failed = [r for r in self.results if not r.ok]
        print(f"\n  {len(self.results)} check(s), {len(failed)} failed")
        return not failed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", default="http://localhost:8001")
    ap.add_argument("--email", default="demo@forest.com")
    ap.add_argument("--password", default="Demo1234")
    ap.add_argument("--timeout", type=int, default=20)
    args = ap.parse_args()

    print(f"{DIM}Verifying hardening behaviour against {args.api}.{OFF}")
    print(f"{DIM}This WRITES scratch records — do not point it at production.{OFF}\n")

    v = Verifier(api=args.api, email=args.email, password=args.password, timeout=args.timeout)
    try:
        v._call("GET", "/health", token=False)
    except Exception:
        print(f"{YELLOW}nothing is answering on {args.api} — start the backend first.{OFF}")
        return 2   # distinct from a failure: not run is not the same as not passed

    if not v.login():
        return 2

    v.check_correlation_id()
    v.check_threadpool_gauge()

    calc_id = v.a_calculation()
    if not calc_id:
        print(f"{YELLOW}  no calculation available — the write checks need one.{OFF}")
        return 2

    try:
        household = v.check_duplicate_household(calc_id)
        v.check_optimistic_lock(household)
        v.check_idempotent_replay(calc_id)
    finally:
        v.cleanup()

    return 0 if v.report() else 1


if __name__ == "__main__":
    raise SystemExit(main())
