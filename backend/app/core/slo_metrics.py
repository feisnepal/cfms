"""Metrics the SLOs and the incident runbooks need (H5.7 · R-4).

`prometheus_fastapi_instrumentator` already gives request rate, status codes and
`http_request_duration_seconds` — enough for the availability and latency SLOs.
What it cannot give is anything about the two subsystems the incident runbook
had to tell responders they could not see:

- **The database pool.** `get_db_pool_status()` has existed all along, exposed
  only on `/api/db-info`, which is DEBUG-only — so it returns 404 in production,
  which is the only place it matters. INC-2 was left telling responders to read
  `pg_stat_activity` instead, which shows the server's view but not the
  application's: a pool exhausted by leaked sessions and one exhausted by load
  look identical from the database side.
- **The calculation queue.** The worker is `max_concurrency=1`, so a backlog is
  the normal shape of load and only becomes an incident when it stops draining.
  Depth alone does not say that — depth *plus time* does, which is why the age
  of the oldest queued job is here too.

These are **gauges sampled at scrape time**, not counters incremented in
handlers, so they cost nothing on the request path — which matters on a service
whose known problem (S1-17) is blocking work on the event loop.

Every collector fails soft. A metrics endpoint that 500s during an incident,
because it could not reach Redis, removes the visibility you were reaching for
at the worst possible moment.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Registered lazily so importing this module never touches the registry twice
# under --reload, which would raise a duplicate-timeseries error.
_registered = False


def register_slo_metrics() -> None:
    """Attach the gauges to the default Prometheus registry. Idempotent."""
    global _registered
    if _registered:
        return

    try:
        from prometheus_client import Gauge
    except ImportError:  # pragma: no cover - metrics disabled builds
        logger.warning("prometheus_client unavailable; SLO gauges not registered")
        return

    # --- database pool -----------------------------------------------------
    # Saturation is (checked_out) / (pool_size + max_overflow). Exported as
    # three numbers rather than one ratio so an alert can distinguish "busy"
    # from "leaking": a healthy pool returns connections, a leaking one holds
    # them with the request count flat.
    pool_checked_out = Gauge(
        "cfms_db_pool_checked_out",
        "Connections currently checked out of the SQLAlchemy pool",
    )
    pool_size = Gauge("cfms_db_pool_size", "Configured pool size")
    pool_overflow = Gauge("cfms_db_pool_overflow", "Overflow connections in use")

    @pool_checked_out.set_function
    def _checked_out() -> float:
        return _pool_value("checked_out")

    @pool_size.set_function
    def _size() -> float:
        return _pool_value("pool_size")

    @pool_overflow.set_function
    def _overflow() -> float:
        # SQLAlchemy's `overflow()` counts UP FROM `-pool_size`, so an idle pool
        # reports a negative number. Exported raw it would put -5 on a dashboard
        # labelled "overflow connections in use", which is not what anybody
        # reading that panel would conclude. Clamped — but -1 still passes
        # through, because that is the "could not read" sentinel.
        raw = _pool_value("overflow")
        return raw if raw < 0 and raw == -1.0 else max(0.0, raw)

    # --- threadpool (H3.3) -------------------------------------------------
    # After H3.1 moved 290 handlers into the threadpool, this became the place
    # requests queue. Saturation here is the leading indicator that used to be
    # invisible because the event loop serialised everything.
    pool_threads_total = Gauge(
        "cfms_threadpool_total",
        "Threads Starlette may use for `def` handlers (sized to the DB pool)",
    )
    pool_threads_used = Gauge(
        "cfms_threadpool_in_use",
        "Threads currently borrowed. Equal to total means requests are queueing.",
    )

    @pool_threads_total.set_function
    def _threads_total() -> float:
        return _threadpool_stat()[0]

    @pool_threads_used.set_function
    def _threads_used() -> float:
        return _threadpool_stat()[1]

    # --- calculation queue -------------------------------------------------
    queue_depth = Gauge(
        "cfms_calculation_queue_depth",
        "Jobs waiting in the arq calculation queue",
    )
    queue_oldest = Gauge(
        "cfms_calculation_queue_oldest_seconds",
        "Age of the oldest queued calculation. Depth alone cannot tell a busy "
        "queue from a stalled one; this can.",
    )

    @queue_depth.set_function
    def _depth() -> float:
        return _queue_stat()[0]

    @queue_oldest.set_function
    def _oldest() -> float:
        return _queue_stat()[1]

    _registered = True
    logger.info("SLO gauges registered: db pool, threadpool, calculation queue")


def _pool_value(key: str) -> float:
    try:
        from app.core.database import get_db_pool_status

        return float(get_db_pool_status().get(key, 0) or 0)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("pool gauge unavailable: %s", exc)
        return -1.0  # -1 distinguishes "could not read" from a true zero


def _threadpool_stat() -> tuple[float, float]:
    """(total, borrowed). `(-1, -1)` before the threadpool is configured.

    Reads the limiter captured at startup rather than resolving it here.
    `current_default_thread_limiter()` raises `AsyncLibraryNotFoundError`
    outside the running async context, and a Prometheus scrape arrives on a
    worker thread -- so calling it here returned the -1 sentinel on **every
    scrape since this gauge was written**. The gauge was live, the endpoint
    served it, and the value was always "could not read".
    """
    from .concurrency import current_limiter_stats  # noqa: PLC0415 -- avoids an import cycle

    return current_limiter_stats()


def _queue_stat() -> tuple[float, float]:
    """(depth, age of oldest in seconds). `(-1, -1)` when Redis is unreachable.

    Returning -1 rather than 0 matters: a zero-depth queue and an unreachable
    Redis are opposite situations, and an alert that cannot tell them apart
    stays silent during exactly the outage it exists for.
    """
    try:
        import time

        import redis

        from app.core.config import settings

        if not settings.REDIS_URL:
            return (0.0, 0.0)
        client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2)
        # arq keeps queued jobs in a sorted set scored by their run-at time.
        key = "arq:calculation"
        depth = float(client.zcard(key) or 0)
        oldest = 0.0
        if depth:
            head = client.zrange(key, 0, 0, withscores=True)
            if head:
                # arq scores are milliseconds since the epoch.
                oldest = max(0.0, time.time() - (head[0][1] / 1000.0))
        return (depth, oldest)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("queue gauge unavailable: %s", exc)
        return (-1.0, -1.0)
