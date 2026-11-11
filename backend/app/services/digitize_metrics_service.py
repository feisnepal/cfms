"""Prometheus metrics for on-screen digitizing (Task 1.5.1).

Mirrors the calculation_metrics_service pattern — lazy import of
prometheus_client (bundled via prometheus_fastapi_instrumentator) and safe
no-op when ENABLE_METRICS is off or prometheus is not installed.

Metrics:
- digitize_finalize_duration_seconds       Histogram  (bucketized)
- digitize_finalize_result{status}          Counter
- digitize_drafts_abandoned_total           Counter  (per cleanup batch)
- digitize_draft_create_total               Counter  (audit convenience)
"""
import logging
import time

from app.core.config import settings

logger = logging.getLogger(__name__)

_counter = None
_histogram = None
_abandoned = None
_draft_create = None


def _lazy_init():
    global _counter, _histogram, _abandoned, _draft_create
    if _counter is not None or not settings.ENABLE_METRICS:
        return
    try:
        from prometheus_client import Counter, Histogram

        _counter = Counter(
            "digitize_finalize_result",
            "Digitize finalize outcomes by status",
            ["status"],
        )
        _histogram = Histogram(
            "digitize_finalize_duration_seconds",
            "Digitize finalize duration in seconds",
            buckets=[0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300],
        )
        _abandoned = Counter(
            "digitize_drafts_abandoned_total",
            "Abandoned digitize drafts cleaned up by the hourly cron",
        )
        _draft_create = Counter(
            "digitize_draft_create_total",
            "Digitize draft layers created",
            ["purpose"],
        )
        logger.info("[metrics] Digitize metrics registered")
    except ImportError:
        logger.debug("[metrics] prometheus_client not available — metrics disabled")
    except Exception as e:
        logger.warning("[metrics] Failed to init digitize metrics: %s", e)


def increment_finalize_result(status: str):
    _lazy_init()
    if _counter:
        _counter.labels(status=status).inc()


def observe_finalize_duration(seconds: float):
    _lazy_init()
    if _histogram:
        _histogram.observe(seconds)


def increment_abandoned_drafts(count: int = 1):
    _lazy_init()
    if _abandoned:
        _abandoned.inc(count)


def increment_draft_create(purpose: str):
    _lazy_init()
    if _draft_create:
        _draft_create.labels(purpose=purpose).inc()


class finalize_duration_timer:
    """Context manager observing digitize_finalize_duration_seconds."""

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, *exc):
        observe_finalize_duration(time.monotonic() - self._start)
        return False
