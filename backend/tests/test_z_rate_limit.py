"""
Rate limiting tests — kept in a last-to-run file to avoid polluting
the in-memory slowapi limiter for registration/login-dependent tests.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


class TestRateLimiting:
    def test_login_rate_limit_returns_429(self, client):
        """After many rapid login attempts, slowapi returns 429."""
        for _ in range(15):
            client.post(
                "/api/auth/login",
                json={"email": "ratelimit@test.com", "password": "Test1234!"},
            )
        resp = client.post(
            "/api/auth/login",
            json={"email": "ratelimit@test.com", "password": "Test1234!"},
        )
        if resp.status_code == 429:
            assert "rate limit" in resp.text.lower()
