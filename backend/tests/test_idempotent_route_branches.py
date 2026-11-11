"""Edge branches of the IdempotentRoute wrapper (H4.2).

`test_idempotent_route.py` covers the ordinary flow: replay, 201 status,
scope, key-reuse, failures and concurrency. These cover the remaining edges:
the `_storable`/`_replay` helpers (non-JSON / streaming / empty / bare
stored bodies) and the wrapper's pass-through branches (malformed JSON on the
wire, and a reservation that vanished between the insert and the read).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.core.idempotent_route import (
    IdempotentRoute,
    _replay,
    _storable,
)
from app.services.idempotency import Outcome


class TestStorable:
    def test_a_failed_response_is_not_stored(self):
        assert _storable(JSONResponse({"x": 1}, status_code=500), "r") is None

    def test_a_streaming_response_is_not_stored(self):
        resp = JSONResponse({"ok": True})
        del resp.body
        assert _storable(resp, "r") is None

    def test_an_empty_response_is_stored_with_a_null_body(self):
        from fastapi.responses import PlainTextResponse

        stored = _storable(PlainTextResponse(""), "r")
        assert stored["status"] == 200
        assert stored["body"] is None

    def test_a_json_response_is_stored_decoded(self):
        stored = _storable(JSONResponse({"created": 1}), "r")
        assert stored["body"] == {"created": 1}


class TestReplay:
    def test_a_bare_stored_value_is_replayed_as_a_200_body(self):
        resp = _replay({"created": 1})
        assert resp.status_code == 200
        assert resp.body == b'{"created":1}'

    def test_an_enveloped_stored_value_preserves_its_status(self):
        import json

        resp = _replay({"__idempotent__": 1, "status": 201, "body": {"created": 1}})
        assert resp.status_code == 201
        assert json.loads(resp.body) == {"created": 1}


class TestPassThrough:
    def _make_client(self):
        calls = {"n": 0}
        router = APIRouter(route_class=IdempotentRoute)

        @router.post("/widgets")
        def create_widget():
            calls["n"] += 1
            return {"created": calls["n"]}

        app = FastAPI()
        app.include_router(router)
        return TestClient(app), calls

    def test_malformed_json_passes_through_unguarded(self):
        client, calls = self._make_client()
        key = f"k-{uuid.uuid4().hex}"
        resp = client.post(
            "/widgets",
            content="not-json",
            headers={"Idempotency-Key": key, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200 or resp.status_code in (400, 422)
        assert calls["n"] == 1

    def test_a_vacated_reservation_runs_the_write(self, monkeypatch):
        import app.services.idempotency as svc

        client, calls = self._make_client()
        key = f"k-{uuid.uuid4().hex}"

        def fake_begin(*a, **k):
            return Outcome(replay=None, owned=False)

        monkeypatch.setattr(svc, "begin", fake_begin)
        resp = client.post(
            "/widgets", json={"x": 1}, headers={"Idempotency-Key": key})
        assert resp.status_code == 200
        assert calls["n"] == 1
