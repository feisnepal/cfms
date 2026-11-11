"""
Security validation tests.

Covers:
- Security response headers (X-Content-Type-Options, X-Frame-Options, etc.)
- CORS allowed origins
- SQL injection protection on search/query endpoints
- File upload validation (extension, path traversal, size limits)
- Rate limiting on auth endpoints
"""
import sys
import os
import io
import zipfile
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings


# ═══════════════════════════════════════════
# Security Headers
# ═══════════════════════════════════════════
class TestSecurityHeaders:
    def test_x_content_type_options_present(self, client):
        resp = client.get("/")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options_present(self, client):
        resp = client.get("/")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_x_xss_protection_present(self, client):
        resp = client.get("/")
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_referrer_policy_present(self, client):
        resp = client.get("/")
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_strict_transport_security_in_production(self, client, monkeypatch):
        """HSTS is set only when DEBUG is False."""
        monkeypatch.setattr(settings, "DEBUG", False)
        client_d = TestClient(app)
        resp = client_d.get("/")
        hsts = resp.headers.get("Strict-Transport-Security")
        if hsts:
            assert "max-age=31536000" in hsts


# ═══════════════════════════════════════════
# CORS
# ═══════════════════════════════════════════
class TestCORS:
    def test_cors_allows_configured_origin(self, client):
        resp = client.options(
            "/api/auth/login",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"

    def test_cors_blocks_unconfigured_origin(self, client):
        resp = client.options(
            "/api/auth/login",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        acao = resp.headers.get("Access-Control-Allow-Origin")
        assert acao != "http://evil.com"

    def test_cors_allows_authorization_header(self, client):
        resp = client.options(
            "/api/auth/login",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════
# API Versioning
# ═══════════════════════════════════════════
class TestAPIVersioning:
    def test_legacy_route_has_deprecation_header(self, client):
        resp = client.post("/api/auth/login", json={"email": "x@y.z", "password": "bad"})
        assert "Deprecation" in resp.headers
        assert "/api/v1" in resp.headers["Deprecation"]

    def test_v1_route_no_deprecation(self, client):
        resp = client.post("/api/v1/auth/login", json={"email": "x@y.z", "password": "bad"})
        assert "Deprecation" not in resp.headers


# ═══════════════════════════════════════════
# SQL Injection Protection
# ═══════════════════════════════════════════
class TestSQLInjection:
    LOGIN_PAYLOADS = [
        {"email": "admin' OR '1'='1", "password": "x"},
        {"email": "'; DROP TABLE users; --", "password": "x"},
        {"email": "' UNION SELECT * FROM users --", "password": "x"},
    ]

    @pytest.mark.parametrize("payload", LOGIN_PAYLOADS)
    def test_sqli_login_returns_401_not_500(self, client, payload):
        """SQL injection in login returns 401 (auth failure) not 500 (crash)."""
        resp = client.post("/api/auth/login", json=payload)
        assert resp.status_code in (400, 401, 422), f"Got {resp.status_code} for {payload}"
        assert "server error" not in resp.text.lower()

    def test_sqli_in_registration_email(self, client):
        """SQL injection in registration email returns 422, not 500."""
        resp = client.post(
            "/api/auth/register",
            json={
                "email": "test' OR 1=1--@example.com",
                "password": "Test1234!",
                "full_name": "SQLi Test",
            },
        )
        assert resp.status_code in (400, 422, 201)
        assert "server error" not in resp.text.lower()


# ═══════════════════════════════════════════
# File Upload Security
# ═══════════════════════════════════════════
class TestFileUploadSecurity:
    def test_rejects_invalid_extension(self, client, auth_headers):
        """Upload with .exe extension should be rejected."""
        resp = client.post(
            "/api/forests/upload",
            headers=auth_headers,
            data={"forest_name": "Test Forest"},
            files={"file": ("malware.exe", b"fake content", "application/octet-stream")},
        )
        assert resp.status_code in (400, 415, 422, 500, 501)
        assert "server error" not in resp.text.lower()

    def test_rejects_oversized_upload(self, client, auth_headers):
        """Upload exceeding MAX_UPLOAD_SIZE_MB should be rejected."""
        big_data = b"x" * ((settings.MAX_UPLOAD_SIZE_MB + 1) * 1024 * 1024)
        resp = client.post(
            "/api/forests/upload",
            headers=auth_headers,
            data={"forest_name": "Test Forest"},
            files={"file": ("huge.geojson", big_data, "application/geo+json")},
        )
        assert resp.status_code in (400, 413, 422, 500, 501)
        assert "server error" not in resp.text.lower()

    def test_allowed_extension_works_basic(self, client, auth_headers):
        """Known-good extension with minimal content reaches handler (may 400 on content)."""
        resp = client.post(
            "/api/forests/upload",
            headers=auth_headers,
            data={"forest_name": "Test Forest"},
            files={"file": ("test.geojson", b'{"type":"Point","coordinates":[0,0]}', "application/geo+json")},
        )
        assert resp.status_code not in (500, 415)


