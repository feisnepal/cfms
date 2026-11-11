"""H3.3 — the threadpool is sized to the database pool (S1-17 step 2).

H3.1 moved 290 handlers off the event loop into Starlette's threadpool, which
removed the hard concurrency ceiling and moved the bottleneck one layer down.
anyio's default is 40 threads; the database pool ceiling is
`DB_POOL_SIZE + DB_MAX_OVERFLOW`. Where those disagree, the excess handlers do
not fail fast — they block in `pool.connect()` for `DB_POOL_TIMEOUT` and then
raise, turning a queue into a wave of 30-second timeouts.

These tests pin the arithmetic and the one thing that makes the whole idea work:
the queue forms in the threadpool, never in the connection pool.
"""
import logging

import anyio
import pytest

from app.core import concurrency
from app.core.config import settings


@pytest.fixture
def pool(monkeypatch):
    """Set the pool dimensions without touching the real settings object."""
    def _set(size: int, overflow: int, explicit: int = 0, workers: int = 1):
        monkeypatch.setattr(settings, "DB_POOL_SIZE", size)
        monkeypatch.setattr(settings, "DB_MAX_OVERFLOW", overflow)
        monkeypatch.setattr(settings, "THREADPOOL_SIZE", explicit)
        monkeypatch.setattr(settings, "WEB_CONCURRENCY", workers)
    return _set


class TestSizing:
    def test_defaults_to_the_pool_ceiling(self, pool):
        pool(20, 30)
        assert concurrency.resolve_threadpool_size() == 50

    def test_dev_configuration(self, pool):
        """The .env on the development machine is 5 + 10, not the 20 + 30 default."""
        pool(5, 10)
        assert concurrency.resolve_threadpool_size() == 15

    def test_an_explicit_setting_wins(self, pool):
        pool(20, 30, explicit=8)
        assert concurrency.resolve_threadpool_size() == 8

    def test_zero_means_auto_not_zero_threads(self, pool):
        """A literal 0 would deadlock every request; 0 has to mean "derive"."""
        pool(5, 10, explicit=0)
        assert concurrency.resolve_threadpool_size() == 15


class TestApplied:
    def test_the_limiter_actually_changes(self, pool):
        pool(5, 10)

        async def run():
            import anyio.to_thread

            before = anyio.to_thread.current_default_thread_limiter().total_tokens
            applied = concurrency.configure_threadpool()
            after = anyio.to_thread.current_default_thread_limiter().total_tokens
            return before, applied, after

        before, applied, after = anyio.run(run)
        assert applied == 15
        assert after == 15
        # anyio's default is 40; the point of the task is that it no longer is.
        assert after != before or before == 15

    def test_the_threadpool_never_exceeds_the_connection_pool(self, pool):
        """The property the whole task exists for.

        More threads than connections does not buy concurrency — it moves the
        queue from the threadpool, where waiting is free, into `pool.connect()`,
        where waiting costs DB_POOL_TIMEOUT and ends in a 500.
        """
        for size, overflow in [(1, 0), (5, 10), (20, 30), (50, 50)]:
            pool(size, overflow)
            assert concurrency.resolve_threadpool_size() <= size + overflow


class TestOversubscriptionWarning:
    """`workers × pool` against the server's own connection limit.

    Asserted on the returned message rather than on log output: the arithmetic
    is the thing worth pinning, and a pure function pins it without depending on
    how logging happens to be configured under test.
    """

    def test_flags_workers_times_pool_over_the_server_limit(self, pool):
        pool(20, 30, workers=4)  # 4 x 50 = 200 against a default max_connections of 100
        msg = concurrency.oversubscription_warning()
        assert msg is not None
        assert "200" in msg and "too many clients" in msg

    def test_silent_for_a_single_worker(self, pool):
        pool(20, 30, workers=1)
        assert concurrency.oversubscription_warning() is None

    def test_silent_when_the_product_fits(self, pool):
        pool(5, 10, workers=4)  # 4 x 15 = 60, under 100
        assert concurrency.oversubscription_warning() is None

    def test_the_boundary_is_not_off_by_one(self, pool):
        pool(25, 0, workers=4)  # exactly 100 — at the limit, not over it
        assert concurrency.oversubscription_warning() is None
        pool(26, 0, workers=4)  # 104
        assert concurrency.oversubscription_warning() is not None
