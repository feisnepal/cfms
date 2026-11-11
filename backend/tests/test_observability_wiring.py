"""Two observability features that were built and reported nothing (H3.3, H3.10).

Both are the shape this phase keeps finding: the mechanism exists, the endpoint
serves it, and the number is meaningless. Neither could be caught by asserting
that the metric or the config is *present* -- which is what a casual check
would have done.
"""
from __future__ import annotations

import logging

from app.core import concurrency
from app.core.logging_config import configure_logging


class TestTheThreadpoolGauge:
    """H3.3. `cfms_threadpool_total` reported -1.0 on every scrape.

    `anyio.to_thread.current_default_thread_limiter()` resolves against the
    running async context and raises `AsyncLibraryNotFoundError` anywhere else.
    A Prometheus scrape arrives on a worker thread, so the gauge's own
    `except` branch returned the "could not read" sentinel every single time.

    The limiter OBJECT has no such restriction once you hold it, which is why
    the fix is to capture it at startup rather than resolve it per scrape.
    """

    def test_stats_are_the_sentinel_before_startup(self):
        """Honest about not knowing yet, rather than reporting a plausible 0."""
        saved = concurrency._LIMITER
        concurrency._LIMITER = None
        try:
            assert concurrency.current_limiter_stats() == (-1.0, -1.0)
        finally:
            concurrency._LIMITER = saved

    def test_a_captured_limiter_is_readable_from_a_sync_context(self):
        """The property the old code did not have.

        This test itself runs synchronously -- the same context a scrape does.
        """
        import anyio
        import anyio.to_thread

        holder = {}

        async def capture():
            holder["limiter"] = anyio.to_thread.current_default_thread_limiter()

        anyio.run(capture)

        saved = concurrency._LIMITER
        concurrency._LIMITER = holder["limiter"]
        try:
            total, borrowed = concurrency.current_limiter_stats()
        finally:
            concurrency._LIMITER = saved

        assert total > 0, "a captured limiter must report a real size"
        assert borrowed >= 0

    def test_resolving_the_limiter_here_would_still_fail(self):
        """Pins WHY the fix has to capture rather than resolve.

        If a future change reverts to calling `current_default_thread_limiter()`
        at scrape time, this documents what happens: it raises, and the gauge
        goes back to -1 with nothing looking broken.
        """
        import anyio.to_thread
        import pytest

        with pytest.raises(Exception):
            anyio.to_thread.current_default_thread_limiter()


class TestTheDebugLogLevel:
    """H3.10. `DEBUG=True` did not raise log verbosity -- the one setting whose
    entire purpose is to do that.

    The level was hardcoded to INFO in the surviving config; the DEBUG-aware
    branch lived only in `observability.configure_logging()`, which could never
    run because this one is called at import and its `if root.handlers: return`
    guard returned immediately, every time.
    """

    def _level_with_debug(self, monkeypatch, debug: bool) -> int:
        from app.core import logging_config

        monkeypatch.setattr(logging_config.settings, "DEBUG", debug, raising=False)
        configure_logging()
        return logging.getLogger().level

    def test_debug_true_gives_debug_level(self, monkeypatch):
        assert self._level_with_debug(monkeypatch, True) == logging.DEBUG

    def test_debug_false_gives_info_level(self, monkeypatch):
        assert self._level_with_debug(monkeypatch, False) == logging.INFO

    def test_the_two_differ(self, monkeypatch):
        """The assertion that actually catches the original defect.

        Both branches returning INFO would satisfy a test that only checked
        `DEBUG=False -> INFO`, and that is exactly what was true before H3.10.
        """
        high = self._level_with_debug(monkeypatch, True)
        low = self._level_with_debug(monkeypatch, False)
        assert high < low, "DEBUG=True must be more verbose than DEBUG=False"
