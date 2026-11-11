"""H2.10 / S3-11 — three endpoints that told strangers about the system.

`GET /test-species` was unauthenticated and enumerated the routing table, paths
and methods included. It existed to debug a router-registration problem and was
never removed.

`/docs`, `/redoc` and `/openapi.json` were served unconditionally: the complete
route inventory, every parameter name and every response shape for a system
holding household records — plus a "Try it out" console pointed at production.

`/metrics` was public whenever ENABLE_METRICS was on, which is the default.
Prometheus output names every route, its call volume and its latency, mapping
the application and leaking which parts are in use.

Note on DEBUG: these tests run in whatever mode the test environment is in, so
the docs assertions check that the wiring is conditional rather than checking
one side of the condition — asserting `docs_url is None` would pass or fail on
the environment rather than on the code.
"""
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import settings
from app.core.observability import _require_metrics_token

MAIN_PY = Path(__file__).resolve().parents[1] / "app" / "main.py"


def _creds(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class TestTestSpeciesIsGone:
    def test_the_route_does_not_answer(self, client):
        assert client.get("/test-species").status_code == 404

    def test_the_route_is_not_registered(self):
        """Walks nested routers — a flat `app.routes` scan misses most of them."""
        from app.main import app

        from conftest import all_route_paths

        assert not any("test-species" in p for p in all_route_paths(app))

    def test_no_other_route_enumerates_the_routing_table(self):
        """The defect was route disclosure, not the URL it lived at."""
        src = MAIN_PY.read_text(encoding="utf-8")
        assert "app.routes:" not in src.replace("for route in app.routes:", "")


class TestDocsAreDevelopmentOnly:
    @pytest.mark.parametrize("attr", ["docs_url", "redoc_url", "openapi_url"])
    def test_each_docs_surface_is_conditional_on_debug(self, attr):
        src = MAIN_PY.read_text(encoding="utf-8")
        assert f"{attr}=" in src, f"{attr} is not set explicitly — it defaults to on"
        line = next(l for l in src.splitlines() if l.strip().startswith(f"{attr}="))
        assert "settings.DEBUG" in line and "None" in line, \
            f"{attr} is served unconditionally: {line.strip()}"

    def test_they_follow_the_current_mode(self):
        from app.main import app

        if settings.DEBUG:
            assert app.docs_url == "/docs"
        else:
            assert app.docs_url is None
            assert app.openapi_url is None


class TestMetricsRequireAToken:
    def test_without_a_configured_token_the_endpoint_denies(self, monkeypatch):
        """Absent config must fail closed. Defaulting to open is how it got here."""
        monkeypatch.setattr(settings, "METRICS_TOKEN", "")
        with pytest.raises(HTTPException) as exc:
            _require_metrics_token(_creds("anything"))
        assert exc.value.status_code == 404

    def test_a_wrong_token_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-scraper-token")
        with pytest.raises(HTTPException) as exc:
            _require_metrics_token(_creds("wrong"))
        assert exc.value.status_code == 401

    def test_no_credentials_at_all_are_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-scraper-token")
        with pytest.raises(HTTPException) as exc:
            _require_metrics_token(None)
        assert exc.value.status_code == 401

    def test_the_configured_token_is_accepted(self, monkeypatch):
        monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-scraper-token")
        assert _require_metrics_token(_creds("s3cret-scraper-token")) is None

    def test_comparison_is_constant_time(self):
        """A token compared with == leaks itself one byte at a time."""
        import inspect

        src = inspect.getsource(_require_metrics_token)
        assert "compare_digest" in src
