"""
Tests for calculation cost estimation service.
"""
import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from app.services.calculation_cost_service import (
    CalculationCostTracker,
    get_cost_estimate,
    CPU_COST_PER_HOUR,
    MEMORY_COST_PER_GB_HOUR,
    CURRENCY,
    default_rates,
)


def test_default_rates():
    rates = default_rates()
    assert rates["cpu_cost_per_hour"] == 0.10
    assert rates["memory_cost_per_gb_hour"] == 0.05
    assert rates["currency"] == "USD"


def test_tracker_finalize_computes_correct_cost():
    db = Mock()
    calc = Mock()
    calc.cost_estimate = None
    db.query.return_value.filter.return_value.first.return_value = calc

    tracker = CalculationCostTracker(db, "00000000-0000-0000-0000-000000000001")
    tracker.finalize(cpu_seconds=3600, peak_memory_mb=1024)

    est = tracker.estimates
    assert est is not None
    assert est["cpu_seconds"] == 3600.0
    assert est["peak_memory_mb"] == 1024.0
    # 1 CPU-hour @ $0.10 = $0.10
    assert est["cpu_cost"] == 0.10
    # 1 GB-hour @ $0.05 = $0.05
    assert est["memory_cost"] == 0.05
    assert est["total_cost"] == 0.15
    assert est["currency"] == "USD"
    assert "computed_at" in est

    # Verify persisted
    calc.cost_estimate = est
    db.flush.assert_called_once()


def test_get_cost_estimate():
    calc = Mock()
    calc.cost_estimate = {"cpu_seconds": 180.0, "peak_memory_mb": 512.0, "total_cost": 0.005, "currency": "USD"}
    result = get_cost_estimate(calc)
    assert result is not None
    assert result["cpu_seconds"] == 180.0


def test_get_cost_estimate_none():
    calc = Mock()
    calc.cost_estimate = None
    assert get_cost_estimate(calc) is None


def test_tracker_context_manager():
    db = Mock()
    calc = Mock()
    calc.cost_estimate = None
    db.query.return_value.filter.return_value.first.return_value = calc

    tracker = CalculationCostTracker(db, "00000000-0000-0000-0000-000000000001")
    tracker._start = 0.0
    with patch('time.perf_counter', return_value=1800.0):
        tracker.__exit__(None, None, None)

    est = tracker.estimates
    assert est is not None
    assert est["peak_memory_mb"] == 0  # no memory recorded
    assert est["cpu_seconds"] == 1800.0


def test_record_memory_peak():
    tracker = CalculationCostTracker(Mock(), "00000000-0000-0000-0000-000000000001")
    tracker.record_memory(512.0)
    tracker.record_memory(1024.0)
    tracker.record_memory(768.0)
    assert tracker._peak_memory_mb == 1024.0
