"""
Cache layer tests — adapted to existing cache infrastructure.

Tests the actual cache components that exist in the codebase:
  - signal_cache_invalidated() response header attachment
  - Map file cache (_map_cache_get/set/clear)
  - Chart file cache (_chart_cache_get/set/clear)
  - ResilientRedis circuit-breaker pattern

Note: FileCache class and @cache decorator referenced in the original
test plan were never implemented — those tests are excluded.
"""
import sys
import os
import tempfile
import io
import time
from unittest.mock import patch, MagicMock, PropertyMock
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import Response


# ───────────────────────────────────────────────────────────
# signal_cache_invalidated
# ───────────────────────────────────────────────────────────
class TestSignalCacheInvalidated:
    def test_sets_headers(self):
        from app.services.cache_invalidation import signal_cache_invalidated

        resp = Response()
        signal_cache_invalidated(resp, "calc-123", ["maps", "charts"])
        assert resp.headers["X-Cache-Invalidated"] == "maps,charts"
        assert resp.headers["X-Cache-Calc-Id"] == "calc-123"

    def test_all_categories(self):
        from app.services.cache_invalidation import signal_cache_invalidated

        resp = Response()
        signal_cache_invalidated(resp, "42", ["all"])
        assert resp.headers["X-Cache-Invalidated"] == "all"

    def test_empty_categories(self):
        from app.services.cache_invalidation import signal_cache_invalidated

        resp = Response()
        signal_cache_invalidated(resp, "x", [])
        assert resp.headers["X-Cache-Invalidated"] == ""


# ───────────────────────────────────────────────────────────
# Map file cache (plan_map_service)
# ───────────────────────────────────────────────────────────
class TestMapFileCache:
    def _make_calc_id(self):
        return uuid4()

    def test_set_and_get_roundtrip(self):
        from app.services.management_plan_docx.plan_map_service import (
            _map_cache_set, _map_cache_get, clear_map_cache,
        )

        cid = self._make_calc_id()
        buf = io.BytesIO(b"fake_png_data_12345" * 500)  # >5KB to pass size check
        _map_cache_set(cid, "boundary", buf)

        retrieved = _map_cache_get(cid, "boundary")
        assert retrieved is not None
        assert retrieved.read() == b"fake_png_data_12345" * 500

        clear_map_cache(cid)

    def test_get_missing_returns_none(self):
        from app.services.management_plan_docx.plan_map_service import (
            _map_cache_get,
        )

        assert _map_cache_get(uuid4(), "nonexistent") is None

    def test_clear_single_layer(self):
        from app.services.management_plan_docx.plan_map_service import (
            _map_cache_set, _map_cache_get, clear_map_cache,
        )

        cid = self._make_calc_id()
        buf = io.BytesIO(b"datadatadata!!!!!" * 500)

        _map_cache_set(cid, "boundary", buf)
        _map_cache_set(cid, "usergroup", buf)
        assert _map_cache_get(cid, "boundary") is not None

        clear_map_cache(cid, layer_name="boundary")
        assert _map_cache_get(cid, "boundary") is None
        assert _map_cache_get(cid, "usergroup") is not None

        clear_map_cache(cid)

    def test_skips_small_files(self):
        from app.services.management_plan_docx.plan_map_service import (
            _map_cache_set, _map_cache_get,
        )

        cid = self._make_calc_id()
        tiny = io.BytesIO(b"tiny")  # <5KB
        _map_cache_set(cid, "boundary", tiny)
        assert _map_cache_get(cid, "boundary") is None

    def test_clear_all(self):
        from app.services.management_plan_docx.plan_map_service import (
            _map_cache_set, _map_cache_get, clear_map_cache,
        )

        cid = self._make_calc_id()
        buf = io.BytesIO(b"datadatadata!!!!!" * 500)
        _map_cache_set(cid, "a", buf)
        _map_cache_set(cid, "b", buf)
        clear_map_cache(cid)
        assert _map_cache_get(cid, "a") is None
        assert _map_cache_get(cid, "b") is None


# ───────────────────────────────────────────────────────────
# Chart file cache (op_docx_builder)
# ───────────────────────────────────────────────────────────
class TestChartFileCache:
    def _make_calc_id(self):
        return uuid4()

    def test_set_and_get_roundtrip(self):
        from app.services.operational_plan.op_docx_builder import (
            _chart_cache_set, _chart_cache_get, clear_chart_cache,
        )

        cid = self._make_calc_id()
        data = b"<svg>chart_data</svg>"
        buf = io.BytesIO(data)

        _chart_cache_set(cid, "species_pie", buf)
        retrieved = _chart_cache_get(cid, "species_pie")
        assert retrieved is not None
        assert retrieved.read() == data

        clear_chart_cache(cid)

    def test_get_missing_returns_none(self):
        from app.services.operational_plan.op_docx_builder import (
            _chart_cache_get,
        )

        assert _chart_cache_get(uuid4(), "missing") is None

    def test_clear_chart_single(self):
        from app.services.operational_plan.op_docx_builder import (
            _chart_cache_set, _chart_cache_get, clear_chart_cache,
        )

        cid = self._make_calc_id()
        buf = io.BytesIO(b"<svg>a</svg>")
        _chart_cache_set(cid, "pie_a", buf)
        _chart_cache_set(cid, "pie_b", buf)
        assert _chart_cache_get(cid, "pie_a") is not None

        clear_chart_cache(cid, chart_key="pie_a")
        assert _chart_cache_get(cid, "pie_a") is None
        assert _chart_cache_get(cid, "pie_b") is not None

        clear_chart_cache(cid)


# ───────────────────────────────────────────────────────────
# ResilientRedis circuit-breaker
# ───────────────────────────────────────────────────────────
class TestResilientRedis:
    def test_get_set_roundtrip_via_memory_fallback(self):
        """Without a Redis server, ResilientRedis falls back to memory."""
        from app.core.resilient_redis import ResilientRedis

        r = ResilientRedis(host="127.0.0.1", port=16379, socket_connect_timeout=1, socket_timeout=1)
        r._memory["mykey"] = "myvalue"
        assert r.get("mykey") == "myvalue"

    def test_set_and_get_from_memory(self):
        from app.core.resilient_redis import ResilientRedis

        r = ResilientRedis(host="127.0.0.1", port=16379, socket_connect_timeout=1, socket_timeout=1)
        r.set("k1", "v1")
        assert r.get("k1") == "v1"

    def test_delete_from_memory(self):
        from app.core.resilient_redis import ResilientRedis

        r = ResilientRedis(host="127.0.0.1", port=16379, socket_connect_timeout=1, socket_timeout=1)
        r.set("k1", "v1")
        r.set("k2", "v2")
        assert r.delete("k1") == 1
        assert r.get("k1") is None
        assert r.get("k2") == "v2"

    def test_circuit_opens_after_failures(self):
        from app.core.resilient_redis import ResilientRedis, CircuitState

        r = ResilientRedis(
            host="127.0.0.1", port=16379,
            socket_connect_timeout=1, socket_timeout=1,
            failure_threshold=2,
        )
        # Force a real Redis call that fails -> opens circuit
        r.get("fail")
        assert r._state == CircuitState.CLOSED
        r.get("fail")
        assert r._state == CircuitState.OPEN

    def test_circuit_closes_on_recovery(self):
        from app.core.resilient_redis import ResilientRedis, CircuitState

        mock_redis = MagicMock()
        mock_redis.get.return_value = "val"

        r = ResilientRedis(
            host="127.0.0.1", port=16379,
            socket_connect_timeout=1, socket_timeout=1,
            failure_threshold=1,
            success_threshold=1,
        )
        r._r = mock_redis
        r._state = CircuitState.HALF_OPEN
        result = r.get("key")
        assert result == "val"
        assert r._state == CircuitState.CLOSED

    def test_state_property_transitions_open_to_half_open(self):
        from app.core.resilient_redis import ResilientRedis, CircuitState

        r = ResilientRedis(
            host="127.0.0.1", port=16379,
            failure_threshold=1, recovery_timeout=0,
        )

        r._state = CircuitState.OPEN
        r._last_failure_time = time.time() - 60
        assert r.state == CircuitState.HALF_OPEN
