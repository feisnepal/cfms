"""
Observability wiring: structured logging, Sentry (gated), and Prometheus
metrics. Everything here is a no-op when the relevant config is unset, so the
app runs unchanged in dev/local.
"""
import logging
import secrets
import sys
from typing import TYPE_CHECKING, Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI


# H3.10 / S2-31: `configure_logging()` used to live here and was called from
# `lifespan`. It could never run — `main.py` configures logging at IMPORT
# time, so the root logger always had a handler by then and this function's
# `if root.handlers: return` guard returned immediately, every time. Its one
# distinctive behaviour, a DEBUG-aware level, has been folded into the
# surviving `core/logging_config.configure_logging()`, which had hardcoded
# INFO. Deleted rather than left in place: two mechanisms where one silently
# wins is the pattern this audit found most often.


def init_sentry() -> None:
    """Initialize Sentry if SENTRY_DSN is set; otherwise no-op."""
    if not settings.SENTRY_DSN:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment="staging" if settings.DEBUG else "production",
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        release=settings.APP_VERSION,
    )


def _require_metrics_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
) -> None:
    """H2.10 / S3-11: gate /metrics on a scraper token.

    The endpoint was public. Prometheus output names every route, its call
    volume and its latency distribution — a map of the application and of who
    is using which part of it. Compared with a bearer header, which is what
    every scraper can already send.
    """
    expected = settings.METRICS_TOKEN
    if not expected:
        raise HTTPException(status_code=404, detail="Not found")
    presented = credentials.credentials if credentials else ""
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid metrics token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def instrument_metrics(app: "FastAPI") -> None:
    """Expose Prometheus metrics at /metrics when ENABLE_METRICS is on.

    Reachable only with METRICS_TOKEN, or in DEBUG where the whole stack is
    already open by design.
    """
    if not settings.ENABLE_METRICS:
        return
    from prometheus_fastapi_instrumentator import Instrumentator

    # FastAPI >=0.139 wraps `include_router` results in `_IncludedRouter`,
    # which has no `.path`; the instrumentator's per-request route-name walk
    # assumes every entry in `app.routes` is a plain Route and crashes on the
    # first request (AttributeError in `routing.get_route_name`). Skip the
    # wrappers so /metrics (and every request) keeps working on modern FastAPI.
    try:
        import prometheus_fastapi_instrumentator.routing as routing_mod
        from fastapi.routing import _IncludedRouter

        _orig_get_route_name = routing_mod._get_route_name

        def _get_route_name_skip_wrappers(scope, routes):
            return _orig_get_route_name(
                scope, [r for r in routes if not isinstance(r, _IncludedRouter)]
            )

        routing_mod._get_route_name = _get_route_name_skip_wrappers
    except Exception:
        logger = logging.getLogger(__name__)
        logger.warning(
            "instrumentator route-name walk not patched; "
            "modern-FastAPI compat unavailable"
        )

    guard = [] if settings.DEBUG else [Depends(_require_metrics_token)]
    Instrumentator().instrument(app).expose(
        app, endpoint="/metrics", include_in_schema=False, dependencies=guard
    )

    # H5.7: the instrumentator covers requests. These cover the two subsystems
    # the incident runbook had to say were invisible — the database pool and the
    # calculation queue. Sampled at scrape time, so nothing is added to the
    # request path.
    from app.core.slo_metrics import register_slo_metrics

    register_slo_metrics()
