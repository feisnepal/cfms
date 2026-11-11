"""
JWT lifecycle tests — register, login, access, refresh, expire.

Verifies the full authentication flow works end-to-end and that
invalid/expired tokens are properly rejected.
"""
import sys
import os
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import jwt as pyjwt

from app.core.config import settings


class TestAuthFlow:
    def test_register_login_access_refresh_cycle(self, client):
        """Full lifecycle: register → login → access /me → refresh → /me with new token."""
        email = f"lifecycle_{int(time.time())}@example.com"
        password = "CyclePass1!"

        # Register
        resp = client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "full_name": "Lifecycle Tester"},
        )
        assert resp.status_code == 201, resp.text

        # Login
        resp = client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "access_token" in body
        token = body["access_token"]

        # Access protected route
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["email"] == email

        # Refresh — H2.5 / S1-05: the refresh token goes in the body. Presenting
        # the access token here used to work and was the whole vulnerability,
        # so it is now rejected; see test_token_lifecycle.py.
        assert "refresh_token" in body, body
        resp = client.post(
            "/api/auth/refresh",
            json={"refresh_token": body["refresh_token"]},
        )
        assert resp.status_code == 200, resp.text
        refreshed = resp.json()
        assert "access_token" in refreshed
        new_token = refreshed["access_token"]
        # NOTE: Token identity is NOT asserted — when both calls
        # land in the same Unix second, exp timestamps match and
        # PyJWT produces the same deterministic signature.

        # Access with new token
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        assert resp.status_code == 200

        # Bad token rejected
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalidtokendata"},
        )
        assert resp.status_code in (401, 403)

    def test_expired_token_rejected(self, client):
        """A JWT with past exp timestamp returns 401."""
        payload = {
            "sub": "00000000-0000-0000-0000-000000000000",
            "email": "expired@test.com",
            "type": "access",
            "exp": datetime.utcnow() - timedelta(hours=1),
        }
        expired_token = pyjwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code in (401, 403), resp.text

    def test_unauthenticated_access_rejected(self, client):
        """Accessing /me without any token returns 401."""
        resp = client.get("/api/auth/me")
        assert resp.status_code in (401, 403)
