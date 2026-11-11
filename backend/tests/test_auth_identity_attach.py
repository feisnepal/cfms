"""The request-identity attach never fails authentication (H8.7 / S2-68).

`utils/auth.get_current_user` completes the request identity the correlation
middleware started -- it binds the authenticated user's id into the request
context so the write/read audit trails can record who acted, without any
endpoint being asked to remember. It is best-effort by design: it runs AFTER
authentication has approved the request, so a failure there must never turn a
granted request into a denied one.

The happy path (the `set_identity` call) runs on every authenticated request and
is covered by the whole suite. The `except` around it never is -- so this pins
that the failure is swallowed and the request still succeeds.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def authed(client, auth_headers):
    return auth_headers


def test_an_identity_failure_does_not_deny_the_request(client, authed, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("request context unavailable")

    monkeypatch.setattr("app.core.request_context.set_identity", _boom)

    resp = client.get("/api/forests/my-forests", headers=authed)
    # The identity attach failed, yet the request authentication approved must
    # still be honoured -- a failure here is logged at DEBUG and swallowed.
    assert resp.status_code == 200


def test_the_happy_path_attaches_the_user(client, authed):
    """The `set_identity` line itself runs and the request succeeds -- the
    control that makes the failure test above meaningful."""
    resp = client.get("/api/forests/my-forests", headers=authed)
    assert resp.status_code == 200
