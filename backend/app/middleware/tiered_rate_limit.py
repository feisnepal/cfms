"""Tighter limits for the requests that cost the most.

The global default in `SlowAPIMiddleware` treats every route alike, and most
routes deserve that: a GET that reads one row is cheap enough that hundreds a
minute are unremarkable. File ingest, document generation and analysis runs are
not. One upload can pull a 50 MB archive through a shapefile parser; one report
can render a document with every table in it. A default sized for reads is no
protection there.

The obvious implementation is a decorator on each expensive route, and it is
the wrong one — there are twenty-two upload routes across nine modules and
export routes in seventeen. That list is a maintenance burden that is wrong the
first time somebody adds the twenty-third. So the tier is derived from what the
request *is* rather than from a list of what it hits: a multipart body is an
upload whatever route receives it, and a path under `/export` or `/download` is
an export. A new endpoint of either kind is limited the day it is written.

Keys come from `identity_key`, so these limits are per-user for authenticated
traffic and per-resolved-address only for anonymous traffic — the whole point
of H2.8.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Optional

from limits import RateLimitItemPerSecond
from limits.strategies import SlidingWindowCounterRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.rate_limit import KEY_PREFIX, identity_key, shared_storage

logger = logging.getLogger(__name__)

# Never limited: liveness and readiness are polled by the orchestrator far more
# often than any user route, and limiting them turns a busy minute into a
# restart loop. `/metrics` is scraped on a fixed interval and is already behind
# a token (H2.10).
EXEMPT_PATHS = frozenset({
    "/", "/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json",
})

_EXPORT_MARKERS = ("/export", "/download", "/generate")
_ANALYSIS_MARKERS = ("/calculate", "/analysis", "/analyze", "/recalculate")


def _parse(limit: str) -> RateLimitItemPerSecond:
    """`"20/minute"` -> a per-second item. Only the units we actually use."""
    amount, _, unit = limit.partition("/")
    seconds = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}.get(
        unit.strip().rstrip("s"), 60
    )
    return RateLimitItemPerSecond(int(amount.strip()), seconds)


def classify(request: Request) -> Optional[str]:
    """Which tier this request belongs to, or None for the global default."""
    path = request.url.path
    if path in EXEMPT_PATHS:
        return None

    if request.method in ("GET", "HEAD", "OPTIONS"):
        # A GET cannot carry an upload, but it is the usual verb for an export.
        if any(marker in path for marker in _EXPORT_MARKERS):
            return "export"
        return None

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        return "upload"
    if any(marker in path for marker in _EXPORT_MARKERS):
        return "export"
    if any(marker in path for marker in _ANALYSIS_MARKERS):
        return "analysis"
    return None


class TieredRateLimitMiddleware(BaseHTTPMiddleware):
    """Applies the upload / export / analysis limits on top of the default."""

    def __init__(self, app):
        super().__init__(app)
        self._strategy = None
        self._items: dict[str, RateLimitItemPerSecond] = {}

    def _limiter(self) -> SlidingWindowCounterRateLimiter:
        # Lazy: importing the app must not open a Redis connection.
        if self._strategy is None:
            self._strategy = SlidingWindowCounterRateLimiter(shared_storage())
        return self._strategy

    def _item(self, tier: str) -> RateLimitItemPerSecond:
        if tier not in self._items:
            configured = {
                "upload": settings.RATE_LIMIT_UPLOAD,
                "export": settings.RATE_LIMIT_EXPORT,
                "analysis": settings.RATE_LIMIT_ANALYSIS,
            }[tier]
            self._items[tier] = _parse(configured)
        return self._items[tier]

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        tier = classify(request)
        if tier is None:
            return await call_next(request)

        key = f"{KEY_PREFIX}:tier:{tier}:{identity_key(request)}"
        item = self._item(tier)

        try:
            allowed = self._limiter().hit(item, key)
        except Exception as exc:  # pragma: no cover - storage outage
            # Fail open rather than 500 every upload because Redis blinked.
            logger.warning("Tiered rate limiter unavailable, allowing: %s", exc)
            return await call_next(request)

        if allowed:
            return await call_next(request)

        retry_after = item.get_expiry()
        try:
            stats = self._limiter().get_window_stats(item, key)
            retry_after = max(1, math.ceil(stats.reset_time - time.time()))
        except Exception:  # pragma: no cover - stats are advisory
            logger.debug(
                "rate-limit window stats unavailable - the 429 goes out without "
                "a Retry-After header", exc_info=True,
            )

        logger.warning("Tier %s rate limit hit for %s", tier, key)
        return JSONResponse(
            status_code=429,
            content={
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": (
                    f"Too many {tier} requests. Retry after {retry_after} seconds."
                ),
                "details": {"retry_after_seconds": retry_after, "tier": tier},
            },
            headers={"Retry-After": str(retry_after)},
        )
