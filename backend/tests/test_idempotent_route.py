"""The guard as the routes actually get it (H2.17 · S2-64).

`test_idempotency.py` covers the mechanism. This covers the reach: the service
was sound and still protected only 2 of 194 mutating routes, because it had to
be remembered at each call site. `IdempotentRoute` moves it onto the router, so
these tests drive it the way a field device does -- through HTTP, twice.

The endpoints here are synthetic on purpose. A real one would need a
calculation, a forest and a plot, and the thing under test is the wrapper, not
the domain. `TestCoverage` at the bottom is what ties this to the real API.
"""
from __future__ import annotations

import uuid
from collections import Counter

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from app.core.idempotent_route import IdempotentRoute, _resource_of  # noqa: PLF0001
from app.models.idempotency import IdempotencyRecord
from app.services.idempotency import begin


@pytest.fixture()
def calls() -> Counter:
    return Counter()


@pytest.fixture()
def app(calls: Counter) -> FastAPI:
    """A minimal app whose router carries the guard, and nothing else."""
    router = APIRouter(route_class=IdempotentRoute)

    @router.post("/widgets")
    def create_widget(body: dict):
        calls["create"] += 1
        return {"created": calls["create"], "name": body.get("name")}

    @router.post("/widgets-201", status_code=201)
    def create_widget_201(body: dict):
        calls["201"] += 1
        return {"created": calls["201"]}

    @router.post("/widgets-boom")
    def boom(body: dict):
        calls["boom"] += 1
        raise HTTPException(status_code=400, detail="no")

    @router.post("/widgets-text")
    def text(body: dict) -> PlainTextResponse:
        calls["text"] += 1
        return PlainTextResponse("not json")

    @router.get("/widgets")
    def list_widgets():
        calls["list"] += 1
        return {"listed": calls["list"]}

    application = FastAPI()
    application.include_router(router)
    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def key() -> str:
    return f"route-{uuid.uuid4().hex}"


BODY = {"name": "plot-7"}


class TestTheRetry:
    """The whole point: the second attempt must not write again."""

    def test_replays_the_first_response(self, client, key, calls):
        first = client.post("/widgets", json=BODY, headers={"Idempotency-Key": key})
        second = client.post("/widgets", json=BODY, headers={"Idempotency-Key": key})

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json() == first.json()
        # The number that matters. Two requests, one write.
        assert calls["create"] == 1

    def test_the_replay_says_it_is_one(self, client, key):
        client.post("/widgets", json=BODY, headers={"Idempotency-Key": key})
        second = client.post("/widgets", json=BODY, headers={"Idempotency-Key": key})

        # Without this header a device cannot tell "my retry worked" from "my
        # retry was recognised", and that distinction decides whether it
        # reconciles or resends.
        assert second.headers.get("Idempotent-Replay") == "true"

    def test_the_status_code_survives(self, client, key, calls):
        first = client.post("/widgets-201", json=BODY, headers={"Idempotency-Key": key})
        second = client.post("/widgets-201", json=BODY, headers={"Idempotency-Key": key})

        assert first.status_code == 201
        # A replayed 201 arriving as 200 is a different answer to the same
        # question, and a client that branches on it takes the wrong branch.
        assert second.status_code == 201
        assert calls["201"] == 1

    def test_the_key_may_come_from_the_body(self, client, key, calls):
        # `workspace.py`'s clients send it this way. Breaking that contract
        # would silently unprotect the two endpoints that already had a guard.
        body = dict(BODY, idempotency_key=key)
        client.post("/widgets", json=body)
        client.post("/widgets", json=body)
        assert calls["create"] == 1


class TestScope:
    def test_a_key_is_scoped_to_its_path(self, client, key, calls):
        client.post("/widgets", json=BODY, headers={"Idempotency-Key": key})
        client.post("/widgets-201", json=BODY, headers={"Idempotency-Key": key})

        # Same key, different operation. Reusing one key across a whole sync
        # batch must not make the second upload disappear.
        assert calls["create"] == 1
        assert calls["201"] == 1

    def test_reads_are_untouched(self, client, key, calls):
        client.get("/widgets", headers={"Idempotency-Key": key})
        client.get("/widgets", headers={"Idempotency-Key": key})
        assert calls["list"] == 2

    def test_the_version_prefix_is_not_part_of_the_scope(self):
        """A retry against `/api` after reaching `/api/v1` is the same write.

        Both mounts serve the same handler, so treating them as two resources
        would let a client that failed over between them write twice.
        """
        class _Req:
            method = "POST"

            class url:  # noqa: N801 -- stands in for a Starlette URL
                path = "/api/v1/field-inventory/plots"

        class _Legacy(_Req):
            class url:  # noqa: N801
                path = "/api/field-inventory/plots"

        assert _resource_of(_Req()) == _resource_of(_Legacy())


class TestKeyReuse:
    def test_the_same_key_with_a_different_body_is_refused(self, client, key, calls):
        client.post("/widgets", json=BODY, headers={"Idempotency-Key": key})
        response = client.post(
            "/widgets", json={"name": "plot-9"}, headers={"Idempotency-Key": key},
        )

        # Replaying the first response here would discard the second payload
        # without a trace -- for field data, an upload that vanishes.
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"
        assert calls["create"] == 1


class TestFailure:
    def test_a_failed_write_is_retried_not_replayed(self, client, key, calls):
        first = client.post("/widgets-boom", json=BODY, headers={"Idempotency-Key": key})
        second = client.post("/widgets-boom", json=BODY, headers={"Idempotency-Key": key})

        assert first.status_code == 400
        # A 400 cached as though it were a result would make a transient
        # failure permanent: the device could never get the records in.
        assert second.status_code == 400
        assert calls["boom"] == 2

    def test_an_unreplayable_response_is_retried(self, client, key, calls):
        client.post("/widgets-text", json=BODY, headers={"Idempotency-Key": key})
        client.post("/widgets-text", json=BODY, headers={"Idempotency-Key": key})

        # There is no stored body to give back, and answering an empty 200
        # would be worse than doing the work again.
        assert calls["text"] == 2


class TestConcurrency:
    def test_an_in_flight_duplicate_is_refused(self, client, db, key, calls):
        """The race the Redis version could not win.

        It checked and then acted, so two retries arriving together both passed
        the check and both wrote. Here the first attempt still holds the
        reservation, and the second is refused rather than run.
        """
        resource = "POST /widgets"
        outcome = begin(db, key, resource, BODY)
        assert outcome.owned

        response = client.post("/widgets", json=BODY, headers={"Idempotency-Key": key})

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "IDEMPOTENCY_IN_PROGRESS"
        assert calls["create"] == 0


class TestWithoutAKey:
    def test_the_write_still_happens(self, client, calls):
        """The web frontend sends no key today, and must keep working.

        `IDEMPOTENCY_REQUIRE_KEY` is what turns this into a refusal, and it
        stays false until the mobile client sends one.
        """
        client.post("/widgets", json=BODY)
        client.post("/widgets", json=BODY)
        assert calls["create"] == 2

    def test_nothing_is_recorded(self, client, db, calls):
        before = db.query(IdempotencyRecord).count()
        client.post("/widgets", json=BODY)
        db.expire_all()
        assert db.query(IdempotencyRecord).count() == before


class TestCoverage:
    """G-SYNC-1 in the suite, not only in CI.

    The gate runs in `lint-backend`. A developer who removes `route_class` from
    a field-module router should not have to wait for a pipeline to find out.
    """

    def test_every_mobile_facing_write_is_guarded(self):
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root / "scripts"))
        import check_idempotency_coverage as gate  # noqa: PLC0415

        found = gate.audit(root)
        gaps = {
            module: found[module]["plain"]
            for module in gate.MOBILE_WRITE_MODULES
            if found.get(module, {}).get("plain")
        }
        assert not gaps, (
            "these mobile-facing writes are not replay-safe; build their router "
            f"with route_class=IdempotentRoute: {gaps}"
        )

    def test_every_mutating_module_is_classified(self):
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root / "scripts"))
        import check_idempotency_coverage as gate  # noqa: PLC0415

        unclassified = sorted(
            module for module in gate.audit(root)
            if module not in gate.MOBILE_WRITE_MODULES and module not in gate.EXEMPT
        )
        assert not unclassified, (
            "a new API module has mutating routes and is in neither list. Decide "
            "once whether a field device writes to it: "
            f"{unclassified}"
        )
