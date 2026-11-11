"""Size the threadpool to the database pool (H3.3 · S1-17 step 2).

H3.1 moved 290 handlers off the event loop and into Starlette's threadpool.
That removed the hard ceiling — and moved the bottleneck one layer down, which
is worth being explicit about because it is a consequence of the fix rather
than a pre-existing fault:

    anyio's default threadpool ....... 40 threads
    database pool ceiling ............ DB_POOL_SIZE + DB_MAX_OVERFLOW

Whenever those disagree in that direction, up to 25 handlers can be running
concurrently while only 15 can hold a connection. The excess do not fail fast —
they block in `pool.connect()` for `DB_POOL_TIMEOUT` (30s) and *then* raise.
Under load that converts a queue into a wave of 30-second timeouts, which is a
worse failure than simply waiting.

So the threadpool is capped at the pool ceiling. The queue then forms in the
threadpool, where waiting is free and bounded by nothing, instead of in the
connection pool, where waiting costs a 30-second timeout and ends in a 500.

**Per worker, not per deployment.** Each gunicorn/uvicorn worker gets its own
threadpool *and* its own database pool, so total connections are
`workers × (DB_POOL_SIZE + DB_MAX_OVERFLOW)`. That product must stay under
PostgreSQL's `max_connections` (100 by default) — four workers at the shipped
20+30 would ask for 200 and fail at the server rather than in the pool. The
startup check below says so rather than leaving it to be discovered.
"""
from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def resolve_threadpool_size() -> int:
    """How many threads this worker should run. Explicit setting wins."""
    if settings.THREADPOOL_SIZE > 0:
        return settings.THREADPOOL_SIZE
    return settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW


# The limiter object captured while the event loop is running.
#
# `current_default_thread_limiter()` resolves against the running async context
# and raises `AsyncLibraryNotFoundError` anywhere else -- including a Prometheus
# scrape, which happens in a `def` handler on a worker thread. That is why
# `cfms_threadpool_total` reported -1.0 on every scrape since it was written:
# the gauge existed, the endpoint served it, and the number was always the
# "could not read" sentinel.
#
# The object itself has no such restriction. Captured once here, its
# `total_tokens` and `borrowed_tokens` are readable from any thread.
_LIMITER = None


def current_limiter_stats() -> tuple[float, float]:
    """(total, borrowed) from the captured limiter; (-1, -1) before startup."""
    if _LIMITER is None:
        return (-1.0, -1.0)
    try:
        return (float(_LIMITER.total_tokens), float(_LIMITER.borrowed_tokens))
    except Exception as exc:  # noqa: BLE001 -- a gauge must never break a scrape
        logger.debug("threadpool stats unavailable: %s", exc)
        return (-1.0, -1.0)


def configure_threadpool() -> int:
    """Apply the limit to anyio's default limiter. Returns the size applied.

    Must run inside the event loop — `current_default_thread_limiter()` resolves
    against the running async context, so calling it at import time gets a
    different limiter from the one Starlette will use.
    """
    try:
        import anyio.to_thread

        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        size = resolve_threadpool_size()
        limiter.total_tokens = size
        # Keep it, so the metrics gauges can read it from a sync scrape.
        global _LIMITER
        _LIMITER = limiter
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not size the threadpool: %s", exc)
        return -1

    logger.info(
        "Threadpool sized to %d (was %d) to match the database pool "
        "(%d + %d overflow). Handlers queue here rather than on pool.connect(), "
        "where waiting costs a %ds timeout.",
        size, previous, settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW,
        settings.DB_POOL_TIMEOUT,
    )
    warning = oversubscription_warning()
    if warning:
        logger.warning("%s", warning)
    return size


def oversubscription_warning() -> str | None:
    """The problem with `workers × pool`, or None when there is none.

    Returns the message rather than logging it, so the arithmetic can be tested
    without capturing log output — and so a startup check or a health endpoint
    could surface the same finding without a second implementation.

    Silent oversubscription surfaces as `FATAL: sorry, too many clients` under
    load: at the *server*, where the connection pool's own diagnostics cannot
    see it, and typically during the first busy hour after somebody raises the
    worker count.
    """
    workers = settings.WEB_CONCURRENCY
    if workers <= 1:
        return None
    per_worker = settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW
    total = workers * per_worker
    if total <= settings.PG_MAX_CONNECTIONS:
        return None
    return (
        f"{workers} workers x {per_worker} connections = {total}, above the "
        f"assumed max_connections of {settings.PG_MAX_CONNECTIONS}. Postgres "
        f"will refuse connections under load with 'too many clients'. Lower "
        f"DB_POOL_SIZE, lower the worker count, or raise max_connections."
    )
