"""3.13 / S3-34 — the arq workers and the report path must honour REDIS_URL.

Before this fix `app/worker.py`, `app/api/reports.py` and
`app/services/report/job_store.py` each hardcoded ``redis://localhost:6379/0``,
so in Compose the report worker could not reach Redis and the API-side enqueue
fell back to inline generation on the request thread — silently.
"""
import importlib

import pytest

from app.core import redis_config
from app.core.config import settings


# ── redis_dsn() ───────────────────────────────────────────────────────────────

def test_redis_dsn_uses_configured_url(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "redis://cache.internal:6390/2", raising=False)
    assert redis_config.redis_dsn() == "redis://cache.internal:6390/2"


def test_redis_dsn_falls_back_to_localhost_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "", raising=False)
    assert redis_config.redis_dsn() == redis_config.DEFAULT_REDIS_DSN


def test_redis_dsn_ignores_whitespace_only(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "   ", raising=False)
    assert redis_config.redis_dsn() == redis_config.DEFAULT_REDIS_DSN


# ── redacted() ────────────────────────────────────────────────────────────────

def test_redacted_masks_password():
    out = redis_config.redacted("redis://:s3cr3t@cache.internal:6379/0")
    assert "s3cr3t" not in out
    assert out == "redis://:***@cache.internal:6379/0"


def test_redacted_masks_password_keeps_username():
    out = redis_config.redacted("rediss://user:pw@host:6380/1")
    assert "pw" not in out
    assert out == "rediss://user:***@host:6380/1"


def test_redacted_leaves_authless_dsn_unchanged():
    dsn = "redis://localhost:6379/0"
    assert redis_config.redacted(dsn) == dsn


# ── wiring: the three report-path sites resolve through redis_dsn() ────────────

def test_job_store_redis_url_is_the_shared_dsn():
    from app.services.report import job_store
    assert job_store.REDIS_URL == redis_config.redis_dsn()


@pytest.mark.parametrize(
    "module_name, settings_cls",
    [
        ("app.worker", "WorkerSettings"),
        ("app.calculation_worker", "CalculationWorkerSettings"),
    ],
)
def test_worker_settings_honour_a_non_localhost_url(monkeypatch, module_name, settings_cls):
    monkeypatch.setattr(settings, "REDIS_URL", "redis://redis.svc:6381/4", raising=False)
    mod = importlib.reload(importlib.import_module(module_name))
    try:
        rs = getattr(mod, settings_cls).redis_settings
        assert (rs.host, rs.port, rs.database) == ("redis.svc", 6381, 4)
        assert callable(getattr(mod, settings_cls).on_startup)
    finally:
        monkeypatch.setattr(settings, "REDIS_URL", "", raising=False)
        importlib.reload(mod)


def test_no_hardcoded_localhost_dsn_in_report_enqueue():
    """Regression guard: the API-side enqueue must not carry its own DSN literal."""
    import inspect
    from app.api import reports

    src = inspect.getsource(reports)
    assert 'from_dsn("redis://localhost:6379/0")' not in src
    assert 'from_dsn(redis_dsn())' in src
