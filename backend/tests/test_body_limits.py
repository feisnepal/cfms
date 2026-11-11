"""H2.15 — geometry and body-size limits on every entrance (S2-56).

The defect these tests exist for was not a missing defence, it was an unapplied
one. `validate_vertex_count` had been written well enough to carry a comment
explaining a Shapely 2.x subtlety, and then wired into two call sites out of a
dozen entrances. `MAX_UPLOAD_SIZE_MB` had a value and no enforcement at all.

So the assertions here are deliberately about *coverage*, not about the
counting logic: an unguarded route is the bug, and
`test_every_geometry_route_is_covered` is the gate (G-SEC-5) that keeps the
next one from arriving unnoticed.
"""
import json

import pytest
from fastapi import Body, FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.constants import (
    REQUEST_MAX_TOTAL_VERTICES,
    WORKSPACE_IMPORT_MAX_VERTICES,
)
from app.middleware.body_limits import (
    RequestBodyLimitMiddleware,
    is_json_body,
    limit_bytes_for,
)
from app.services.geometry_sanitizer import count_positions


# ---------------------------------------------------------------------------
# A minimal app carrying only the middleware, so a failure here is the
# middleware's and not some route's validation reaching the same verdict first.
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_client():
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware)

    @app.post("/echo")
    async def echo(payload: dict = Body(...)):
        return {"received": True, "keys": sorted(payload.keys())}

    @app.post("/raw")
    async def raw(request_body: bytes = Body(...)):
        return {"size": len(request_body)}

    return TestClient(app)


def _ring(n: int):
    """A closed ring of `n` distinct positions near the demo forest."""
    coords = [[84.0 + i * 0.00001, 28.0] for i in range(n)]
    coords.append(coords[0])
    return coords


def _polygon(n: int):
    return {"type": "Polygon", "coordinates": [_ring(n)]}


# ---------------------------------------------------------------------------
# The counter
# ---------------------------------------------------------------------------


class TestCountPositions:
    def test_counts_a_polygon(self):
        total, largest = count_positions(_polygon(10), budget=10_000)
        assert total == 11  # 10 distinct + the closing position
        assert largest == 11

    def test_counts_every_geojson_type(self):
        body = {
            "point": {"type": "Point", "coordinates": [84.0, 28.0]},
            "line": {"type": "LineString", "coordinates": [[84.0, 28.0], [84.1, 28.1]]},
            "multi": {
                "type": "MultiPolygon",
                "coordinates": [[_ring(3)], [_ring(4)]],
            },
        }
        total, largest = count_positions(body, budget=10_000)
        assert total == 1 + 2 + 4 + 5
        assert largest == 9  # the MultiPolygon, counted as one geometry

    def test_finds_geometry_at_any_depth_and_field_name(self):
        """The walk must not depend on the field being called `geometry`."""
        body = {"a": {"b": [{"whatever": _polygon(5)}]}}
        total, _ = count_positions(body, budget=10_000)
        assert total == 6

    def test_counts_geometry_serialized_as_a_string(self):
        """`yearly_activities.geometry` is typed `str`, not `dict`."""
        body = {"geometry": json.dumps(_polygon(7))}
        total, largest = count_positions(body, budget=10_000)
        assert total == 8
        assert largest == 8

    def test_ignores_a_type_that_lies(self):
        """A hostile body will not describe itself honestly."""
        body = {"type": "Point", "coordinates": [_ring(50)]}
        total, _ = count_positions(body, budget=10_000)
        assert total == 51

    def test_booleans_are_not_coordinates(self):
        total, _ = count_positions({"coordinates": [[True, False]]}, budget=100)
        assert total == 0

    def test_stops_at_the_budget(self):
        """Counting a hostile body must not itself be the denial of service."""
        total, _ = count_positions(_polygon(50_000), budget=1_000)
        assert total == 1_000

    def test_a_body_without_geometry_counts_nothing(self):
        total, largest = count_positions(
            {"email": "a@b.com", "password": "x", "n": [1, 2, 3]}, budget=100
        )
        assert (total, largest) == (0, 0)


# ---------------------------------------------------------------------------
# Vertex enforcement through the middleware
# ---------------------------------------------------------------------------


class TestVertexLimits:
    def test_ordinary_geometry_passes(self, app_client):
        resp = app_client.post("/echo", json={"geometry": _polygon(100)})
        assert resp.status_code == 200
        assert resp.json()["received"] is True

    def test_oversized_polygon_is_rejected(self, app_client):
        resp = app_client.post(
            "/echo", json={"geometry": _polygon(WORKSPACE_IMPORT_MAX_VERTICES + 1)}
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "IMPORT_MAX_VERTICES_EXCEEDED"
        assert resp.json()["details"]["max"] == WORKSPACE_IMPORT_MAX_VERTICES

    def test_the_route_never_runs(self, app_client):
        """Rejection happens before the handler, which is the whole point."""
        resp = app_client.post(
            "/echo", json={"geometry": _polygon(WORKSPACE_IMPORT_MAX_VERTICES + 1)}
        )
        assert "received" not in resp.json()

    def test_many_small_geometries_are_capped_in_aggregate(self, app_client):
        """Under the per-geometry cap individually, far over it together."""
        per_feature = 500
        count = (REQUEST_MAX_TOTAL_VERTICES // per_feature) + 5
        body = {"features": [_polygon(per_feature - 1) for _ in range(count)]}
        resp = app_client.post("/echo", json=body)
        assert resp.status_code == 400
        assert resp.json()["details"]["max"] == REQUEST_MAX_TOTAL_VERTICES

    def test_a_legitimate_bulk_payload_is_not_caught(self, app_client):
        """50 features at the digitize ceiling is what the app itself sends."""
        body = {"features": [{"geometry": _polygon(200)} for _ in range(50)]}
        resp = app_client.post("/echo", json=body)
        assert resp.status_code == 200

    def test_string_encoded_geometry_is_rejected_too(self, app_client):
        resp = app_client.post(
            "/echo",
            json={"geometry": json.dumps(_polygon(WORKSPACE_IMPORT_MAX_VERTICES + 1))},
        )
        assert resp.status_code == 400

    def test_geo_json_content_type_is_still_counted(self, app_client):
        """Relabelling the body must not step around the guard."""
        payload = json.dumps({"geometry": _polygon(WORKSPACE_IMPORT_MAX_VERTICES + 1)})
        resp = app_client.post(
            "/echo",
            content=payload,
            headers={"content-type": "application/geo+json"},
        )
        assert resp.status_code == 400

    def test_a_unicode_escaped_key_does_not_evade_the_scan(self, app_client):
        r"""A key spelled in escapes still decodes to `coordinates`.

        The cheap path scans the raw bytes for `coordinates`, so a body that
        spells the key in escapes would slip past it. Anything large enough to
        matter is parsed regardless — this is the test that holds that rule in
        place.
        """
        ring = json.dumps(_ring(WORKSPACE_IMPORT_MAX_VERTICES + 1))
        payload = (
            '{"geometry": {"type": "Polygon", '
            '"coordi' + '\\u006e' + 'ates": [' + ring + "]}}"
        )
        assert b"coordinates" not in payload.encode()
        resp = app_client.post(
            "/echo", content=payload, headers={"content-type": "application/json"}
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "IMPORT_MAX_VERTICES_EXCEEDED"

    def test_malformed_json_is_left_to_the_handler(self, app_client):
        """Unparseable JSON never reaches geometry code; 422 is the route's."""
        resp = app_client.post(
            "/echo",
            content=b'{"coordinates": [[[',
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Size enforcement
# ---------------------------------------------------------------------------


class TestBodySize:
    def test_json_over_the_cap_is_refused(self, app_client):
        oversized = b'{"x":"' + b"a" * (settings.MAX_JSON_BODY_SIZE_MB * 1024 * 1024) + b'"}'
        resp = app_client.post(
            "/echo", content=oversized, headers={"content-type": "application/json"}
        )
        assert resp.status_code == 413
        assert resp.json()["error_code"] == "REQUEST_BODY_TOO_LARGE"

    def test_a_lying_content_length_buys_nothing(self, app_client):
        """The declared length is a hint; the bytes that arrive are the truth."""
        oversized = b"x" * (settings.MAX_JSON_BODY_SIZE_MB * 1024 * 1024 + 1024)

        def chunks():
            yield oversized

        resp = app_client.post(
            "/raw",
            content=chunks(),  # chunked: no content-length at all
            headers={"content-type": "application/octet-stream"},
        )
        assert resp.status_code == 413

    def test_multipart_gets_the_upload_cap_not_the_json_cap(self):
        assert limit_bytes_for("multipart/form-data; boundary=x") == (
            settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        )
        assert limit_bytes_for("application/json") == (
            settings.MAX_JSON_BODY_SIZE_MB * 1024 * 1024
        )

    def test_max_upload_size_mb_is_now_actually_enforced(self, app_client):
        """S2-56's other half: the setting existed and did nothing."""
        limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        resp = app_client.post(
            "/raw",
            content=b"x" * 16,
            headers={
                "content-type": "multipart/form-data; boundary=x",
                "content-length": str(limit + 1),
            },
        )
        assert resp.status_code == 413

    def test_a_normal_request_is_untouched(self, app_client):
        resp = app_client.post("/echo", json={"name": "Demo forest"})
        assert resp.status_code == 200

    def test_reads_skip_the_middleware_entirely(self, app_client):
        """A GET carries no body; it must not pay for any of this."""
        resp = app_client.get("/echo")
        assert resp.status_code == 405  # reached routing, not intercepted


class TestJsonDetection:
    @pytest.mark.parametrize(
        "content_type",
        ["application/json", "application/json; charset=utf-8", "application/geo+json"],
    )
    def test_json_flavours(self, content_type):
        assert is_json_body(content_type) is True

    @pytest.mark.parametrize(
        "content_type",
        ["multipart/form-data", "application/octet-stream", "text/csv", ""],
    )
    def test_non_json(self, content_type):
        assert is_json_body(content_type) is False


# ---------------------------------------------------------------------------
# Gate G-SEC-5
# ---------------------------------------------------------------------------


def _geometry_bearing_routes(app):
    """Routes whose OpenAPI request body mentions geometry.

    This under-reports on purpose — most of these bodies are typed
    `Dict[str, Any]` and declare nothing, which is exactly why the enforcement
    is a middleware rather than a per-route dependency. What it can prove is
    that no route which *does* declare geometry sits outside the guard.
    """
    schema = app.openapi()
    found = []
    for path, operations in schema.get("paths", {}).items():
        for method, operation in operations.items():
            if method.upper() not in {"POST", "PUT", "PATCH"}:
                continue
            body = json.dumps(operation.get("requestBody", {}))
            refs = json.dumps(
                [
                    schema["components"]["schemas"].get(name, {})
                    for name in schema.get("components", {}).get("schemas", {})
                    if f'"#/components/schemas/{name}"' in body
                ]
            )
            if "coordinates" in (body + refs).lower() or "geometry" in (body + refs).lower():
                found.append((method.upper(), path))
    return found


class TestGateGSec5:
    """Every geometry-bearing route is behind the ingress guard."""

    def test_the_middleware_is_installed(self):
        from app.main import app

        assert any(
            m.cls is RequestBodyLimitMiddleware for m in app.user_middleware
        ), "RequestBodyLimitMiddleware is not registered on the app"

    def test_every_geometry_route_is_covered(self):
        """The gate. A geometry route the guard cannot see fails here.

        Coverage means two things: the route takes a body-carrying method, and
        its path is not on any exemption list. There is no exemption list — the
        middleware exempts nothing — so this asserts the property that keeps it
        that way.
        """
        from app.main import app
        from app.middleware.body_limits import _BODYLESS_METHODS

        routes = _geometry_bearing_routes(app)
        assert routes, "found no geometry-bearing routes — the scan is broken"

        uncovered = [
            (method, path)
            for method, path in routes
            if method in _BODYLESS_METHODS
        ]
        assert not uncovered, (
            "geometry-bearing routes the body guard cannot reach: "
            f"{uncovered}"
        )

    def test_a_real_geometry_route_rejects_an_oversized_polygon(self, client):
        """End to end on the real app, not the synthetic one.

        Unauthenticated on purpose: the guard sits ahead of routing, so the
        request never reaches the auth dependency. A caller does not need an
        account to be turned away, which is the difference between this and a
        per-route dependency.
        """
        resp = client.put(
            "/api/forests/calculations/1/boundary",
            json={
                "geometry": _polygon(WORKSPACE_IMPORT_MAX_VERTICES + 1),
                "area_hectares": 10.0,
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "IMPORT_MAX_VERTICES_EXCEEDED"

    def test_the_gate_would_catch_a_regression(self):
        """Anti-false-pass: exempting a method must break the assertion."""
        from app.main import app

        routes = _geometry_bearing_routes(app)
        pretend_exempt = {"POST", "PUT", "PATCH"}
        uncovered = [r for r in routes if r[0] in pretend_exempt]
        assert uncovered, (
            "the gate cannot fail, so it is not a gate — the scan found no "
            "route it would have caught"
        )
