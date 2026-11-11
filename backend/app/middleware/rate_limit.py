"""Per-user rate limiting for workspace operations.

The per-user keying here was always right — it is the design the slowapi
limiter was rebuilt around in H2.8. Two things were not:

**The buckets were unbounded.** `_buckets` was a `defaultdict` whose only
eviction was a `reset()` no application code ever called. One entry per user id
ever seen, held for the life of the process; an attacker could mint ids and
grow it without limit. Counters now live in the shared `limits` storage, whose
keys carry an expiry — Redis reclaims them by TTL, and the in-memory backend
sweeps expired keys on the next write. The set is bounded by *active*
identities rather than by every identity in history.

The strategy is a sliding-window **counter**, not a moving window. That choice
is about memory, not smoothing: a moving window stores one entry per hit, so a
busy key grows without bound within its own window — measured at 300 entries
for 300 requests, which is worse than the token bucket it replaced. The counter
form keeps two integers per key whatever the traffic.

**The buckets were in one process.** A limit of 5 imports/minute became 5 per
worker, forgiven on every restart. The same storage that backs the slowapi
limiter backs these, so with Redis configured one limit means one limit.

The public surface — `check(user_id)` / `reset(user_id)` — is unchanged, and so
are the four call sites in `api/workspace.py`.
"""
from __future__ import annotations

import logging
import math
from typing import Callable
from functools import wraps
from uuid import UUID

from limits import RateLimitItemPerSecond
from limits.strategies import SlidingWindowCounterRateLimiter

from app.core.exceptions import RateLimitExceeded
from app.core.rate_limit import KEY_PREFIX, shared_storage

logger = logging.getLogger(__name__)




class WorkspaceRateLimiter:
    """Per-user rate limiter for workspace operations.

    Usage:
        limiter = WorkspaceRateLimiter(max_requests=5, window_seconds=60, name="import")
        limiter.check(user_id)

    `name` namespaces the counters. Without it two limiters with the same shape
    would share one window across unrelated operations — which is exactly what
    a shared backend makes possible, and a per-process dict never did.
    """

    def __init__(self, max_requests: int = 5, window_seconds: int = 60, name: str = "workspace"):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._name = name
        # Expressed per-second so any window length is representable; the
        # moving window then behaves like the token bucket this replaced —
        # capacity refills continuously rather than all at once on the minute.
        self._item = RateLimitItemPerSecond(max_requests, window_seconds)
        self._strategy = None

    def _limiter(self) -> SlidingWindowCounterRateLimiter:
        if self._strategy is None:
            self._strategy = SlidingWindowCounterRateLimiter(shared_storage())
        return self._strategy

    def _key(self, user_id: UUID | str) -> str:
        return f"{KEY_PREFIX}:ws:{self._name}:{user_id}"

    def check(self, user_id: UUID | str) -> None:
        """Raise RateLimitExceeded if this user has exceeded the limit."""
        key = self._key(user_id)
        if self._limiter().hit(self._item, key):
            return

        # Tell the caller when capacity actually returns rather than repeating
        # the window length: under a moving window the wait is usually shorter,
        # and a client that sleeps the full window wastes the difference.
        retry_after = self._window_seconds
        try:
            import time

            stats = self._limiter().get_window_stats(self._item, key)
            retry_after = max(1, math.ceil(stats.reset_time - time.time()))
        except Exception:  # pragma: no cover - stats are advisory only
            logger.debug(
                "rate-limit window stats unavailable - the 429 goes out without "
                "a Retry-After header", exc_info=True,
            )

        logger.warning("Rate limit hit for user %s on %s", user_id, self._name)
        raise RateLimitExceeded(retry_after_seconds=retry_after)

    def reset(self, user_id: UUID | str) -> None:
        """Clear this user's window. Used by tests and by admin recovery.

        Through the strategy, not the storage: `limits` namespaces the stored
        key by the limit's shape, so `storage.clear(our_key)` silently clears
        nothing at all.
        """
        try:
            self._limiter().clear(self._item, self._key(user_id))
        except Exception:  # pragma: no cover - best effort
            logger.debug("Could not clear rate-limit key for %s", user_id)


# Shared instances: 5 imports/minute
import_limiter = WorkspaceRateLimiter(max_requests=5, window_seconds=60, name="import")

# Digitize API: create/finalize 10/min, bulk 100/min — Gap 2.3.
# Deliberately NOT the import_limiter (5/min would block a 50-tree draw).
digitize_limiter = WorkspaceRateLimiter(max_requests=10, window_seconds=60, name="digitize")
digitize_bulk_limiter = WorkspaceRateLimiter(
    max_requests=100, window_seconds=60, name="digitize_bulk"
)


def rate_limit(requests_per_minute: int = 5, name: str = "decorated"):
    """Decorator-based rate limiting for endpoints.

    Usage:
        @router.post("/import")
        @rate_limit(5, name="layer_import")
        async def import_layer(...):
    """
    limiter = WorkspaceRateLimiter(
        max_requests=requests_per_minute, window_seconds=60, name=name
    )

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get("current_user")
            if user and hasattr(user, "id"):
                limiter.check(user.id)
            return await func(*args, **kwargs)
        return wrapper
    return decorator
