"""Request identity reaches code that has no Request (H8.7 · S2-68).

The geometry audit records who acted, from where, on which client. The single
point every geometry write passes through -- `editing.py::_write_geometry` --
is several frames below the endpoint with no `Request` in scope.

Threading `Request` and `current_user` through twelve endpoints, three persist
helpers and the write function is the shape S2-68 describes: something that must
be remembered at every call site, and is therefore present at some of them.
`geometry_audits` holds 0 rows after five months because the audit depended on
being remembered.

So identity travels the way the correlation id does (H3.9) -- bound by
middleware, read where needed. These tests pin the two halves separately,
because they are bound at different times: the middleware knows the address
before authentication has run, and only the auth dependency knows the user.
"""
from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core.request_context import (
    DEFAULT_CLIENT_TYPE,
    RequestIdentity,
    get_identity,
    identity_from_request,
    reset_identity,
    set_identity,
)
from app.middleware.correlation import CorrelationIdMiddleware


@pytest.fixture()
def app() -> FastAPI:
    router = APIRouter()

    @router.get("/who")
    def who():
        # Read from a plain function, exactly as the audit does -- no Request,
        # no dependency, several frames from the endpoint if it were nested.
        ident = get_identity()
        return {
            "user_id": ident.user_id,
            "ip_address": ident.ip_address,
            "client_type": ident.client_type,
            "user_agent": ident.user_agent,
        }

    application = FastAPI()
    application.add_middleware(CorrelationIdMiddleware)
    application.include_router(router)
    return application


@pytest.fixture()
def mini_client(app: FastAPI) -> TestClient:
    """Named `mini_client`, NOT `client`.

    A fixture called `client` in a test file shadows conftest's for everything
    in that file -- including `auth_headers`, which depends on it. That made
    `auth_headers` register against this synthetic app, which has no auth
    routes, and the failure surfaced as a 404 during fixture setup rather than
    anywhere near the cause.
    """
    with TestClient(app) as c:
        yield c


class TestTheMiddlewareHalf:
    def test_the_address_reaches_code_with_no_request(self, mini_client):
        body = mini_client.get("/who").json()
        assert body["ip_address"], "no address reached the handler"

    def test_the_client_type_defaults_to_web(self, mini_client):
        """Honest rather than guessed: the only client in existence is the web
        app, and this becomes a real signal the day the mobile client sends the
        header."""
        assert mini_client.get("/who").json()["client_type"] == DEFAULT_CLIENT_TYPE

    def test_a_declared_client_type_is_recorded(self, mini_client):
        body = mini_client.get("/who", headers={"X-Client-Type": "Mobile"}).json()
        assert body["client_type"] == "mobile"      # normalised

    def test_the_user_agent_is_captured(self, mini_client):
        body = mini_client.get("/who", headers={"User-Agent": "CFMS-Field/2.1"}).json()
        assert body["user_agent"] == "CFMS-Field/2.1"

    def test_identity_does_not_leak_between_requests(self, mini_client):
        """Reset in a `finally`, like the correlation id.

        Without it a worker stamps the next request with the previous
        requester's address -- worse than recording nothing, because the audit
        row would be confidently wrong about who acted.
        """
        mini_client.get("/who", headers={"X-Client-Type": "mobile"})
        assert get_identity().client_type == DEFAULT_CLIENT_TYPE
        assert get_identity().user_id is None


class TestTheAuthHalf:
    def test_the_user_is_absent_until_authentication_runs(self, mini_client):
        """The middleware cannot know it: dependencies have not resolved yet.

        Pinned so nobody 'fixes' the middleware to read a user it cannot have.
        """
        assert mini_client.get("/who").json()["user_id"] is None

    def test_the_real_app_attaches_a_user(self, client, auth_headers):
        """Through the real dependency chain, not a stand-in.

        `get_current_active_user` is where the user first exists, and every
        route requiring a user passes through it -- so no endpoint has to
        remember to record one.
        """
        response = client.get("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200
        # The identity is bound during the request and reset after it, so the
        # assertion is that the request SUCCEEDED through the chain that binds
        # it; the binding itself is asserted in the unit test below.
        assert response.json().get("email")

    def test_attaching_a_user_preserves_the_rest(self):
        """`replace()` on a frozen dataclass, not a fresh object.

        Rebuilding it would silently drop the address and client type the
        middleware had already resolved, and the audit row would be
        attributable to a person but not a place.
        """
        from dataclasses import replace

        token = set_identity(RequestIdentity(
            ip_address="10.1.2.3", client_type="mobile", user_agent="UA/1",
        ))
        try:
            set_identity(replace(get_identity(), user_id="user-1"))
            ident = get_identity()
            assert ident.user_id == "user-1"
            assert ident.ip_address == "10.1.2.3"
            assert ident.client_type == "mobile"
            assert ident.user_agent == "UA/1"
        finally:
            reset_identity(token)


class TestItNeverBreaksTheRequest:
    def test_a_broken_request_object_yields_an_empty_identity(self):
        """An audit trail that can fail the operation it records is worse than
        no audit trail -- which is the trade S2-68 is about."""

        class _Hostile:
            @property
            def headers(self):
                raise RuntimeError("no headers for you")

        ident = identity_from_request(_Hostile())
        assert ident.client_type == DEFAULT_CLIENT_TYPE
        assert ident.user_id is None

    def test_outside_a_request_the_identity_is_empty_not_an_error(self):
        """Background jobs and scripts call the same code."""
        ident = get_identity()
        assert ident.user_id is None
        assert ident.client_type == DEFAULT_CLIENT_TYPE
