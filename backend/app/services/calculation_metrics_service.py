"""Prometheus metrics for calculation lifecycle.

Requires prometheus_client (bundled via prometheus_fastapi_instrumentator).
Safe no-op when prometheus is not installed.
"""
import logging
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)

# Lazy import to avoid crash when prometheus not installed
_counter = None
_gauge = None
_histogram = None
# H4.1: `_histogram_cost` was assigned inside `_lazy_init` but never declared
# module-level or `global`, so the assignment created a local that was thrown
# away and `observe_cost` raised NameError on a name that never existed.
# Cost metrics have therefore never been recorded.
_histogram_cost = None


def _lazy_init():
    global _counter, _gauge, _histogram, _histogram_cost
    if _counter is not None or not settings.ENABLE_METRICS:
        return
    try:
        from prometheus_client import Counter, Gauge, Histogram

        _counter = Counter(
            "calculation_total",
            "Total calculations by status",
            ["status", "dimension_mode"],
        )
        _gauge = Gauge(
            "calculation_queue_depth",
            "Current number of queued calculations",
        )
        _gauge_running = Gauge(
            "calculation_running",
            "Whether a calculation is currently running (1/0)",
        )
        _histogram = Histogram(
            "calculation_duration_seconds",
            "Calculation duration in seconds",
            buckets=[10, 30, 60, 120, 300, 600, 1200, 1800, 3600],
        )
        _histogram_cost = Histogram(
            "calculation_cost_total",
            "Calculation total cost in currency units",
            buckets=[0.001, 0.01, 0.05, 0.10, 0.50, 1.0, 5.0, 10.0],
        )
        logger.info("[metrics] Calculation metrics registered")
    except ImportError:
        logger.debug("[metrics] prometheus_client not available — metrics disabled")
    except Exception as e:
        logger.warning("[metrics] Failed to init calculation metrics: %s", e)


def increment_calculation(status: str, dimension_mode: str = "block"):
    _lazy_init()
    if _counter:
        _counter.labels(status=status, dimension_mode=dimension_mode).inc()


def set_queue_depth(depth: int):
    _lazy_init()
    if _gauge:
        _gauge.set(depth)


def set_running(running: bool):
    _lazy_init()
    if _gauge:
        from prometheus_client import Gauge
        _gauge_running = [g for g in Gauge._metrics.values() if g._name == "calculation_running"]
        if _gauge_running:
            _gauge_running[0].set(1 if running else 0)


def observe_duration(seconds: float):
    _lazy_init()
    if _histogram:
        _histogram.observe(seconds)


def observe_cost(cost: float):
    _lazy_init()
    if _histogram_cost:
        _histogram_cost.observe(cost)
