"""Branch coverage: concurrency gauge guards + slo threadpool stat (H4.2)."""
from __future__ import annotations

import pytest

from app.core import concurrency
from app.core import slo_metrics


class TestLimiterStatsGuard:
    def test_a_limiter_that_raises_returns_the_sentinel(self):
        """A gauge must never break a scrape, whatever the limiter does."""

        class _Broken:
            @property
            def total_tokens(self):
                raise RuntimeError("not available")

            @property
            def borrowed_tokens(self):
                raise RuntimeError("not available")

        saved = concurrency._LIMITER
        concurrency._LIMITER = _Broken()
        try:
            assert concurrency.current_limiter_stats() == (-1.0, -1.0)
        finally:
            concurrency._LIMITER = saved


class TestSloThreadpoolStat:
    def test_it_forwards_the_limiter_stats(self):
        saved = concurrency._LIMITER
        try:
            concurrency._LIMITER = None
            assert slo_metrics._threadpool_stat() == (-1.0, -1.0)
        finally:
            concurrency._LIMITER = saved
