"""
Tests for calculation queue service.
"""
import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4

from app.services.calculation_queue_service import (
    enqueue_calculation,
    dequeue_calculation,
    complete_calculation,
    get_queue_status,
)


class TestCalculationQueue:
    def setup_method(self):
        # Use in-memory fallback for all tests
        from app.services import calculation_queue_service
        calculation_queue_service._fallback_store.clear()
        calculation_queue_service._fallback_counter = 0
        calculation_queue_service._redis = None

    def test_enqueue_and_dequeue(self):
        cid = uuid4()
        pos = enqueue_calculation(cid)
        assert pos == 1

        dequeued = dequeue_calculation()
        assert dequeued == str(cid)

    def test_multiple_enqueue_sequential_positions(self):
        cid1 = uuid4()
        cid2 = uuid4()
        pos1 = enqueue_calculation(cid1)
        pos2 = enqueue_calculation(cid2)
        assert pos1 == 1
        assert pos2 == 2

    def test_fifo_order(self):
        cid1 = uuid4()
        cid2 = uuid4()
        enqueue_calculation(cid1)
        enqueue_calculation(cid2)
        assert dequeue_calculation() == str(cid1)
        assert dequeue_calculation() == str(cid2)

    def test_dequeue_empty_returns_none(self):
        assert dequeue_calculation() is None

    def test_complete_calculation_removes_from_queue(self):
        cid = uuid4()
        enqueue_calculation(cid)
        dequeued = dequeue_calculation()
        complete_calculation(dequeued, success=True)
        # Should be removed from active tracking
        status = get_queue_status()
        assert status["depth"] == 0
        assert status["running_calculation_id"] is None

    def test_queue_status_with_running_job(self):
        cid = uuid4()
        enqueue_calculation(cid)
        cid2 = uuid4()
        enqueue_calculation(cid2)
        dequeue_calculation()  # cid1 is now running
        status = get_queue_status()
        assert status["depth"] == 1  # cid2 still pending

    def test_queue_status_empty(self):
        status = get_queue_status()
        assert status["depth"] == 0
        assert status["running_calculation_id"] is None

    def test_enqueue_after_dequeue(self):
        cid1 = uuid4()
        cid2 = uuid4()
        enqueue_calculation(cid1)
        enqueue_calculation(cid2)
        dequeue_calculation()  # pops cid1
        cid3 = uuid4()
        pos3 = enqueue_calculation(cid3)
        assert pos3 == 3
        assert dequeue_calculation() == str(cid2)
        assert dequeue_calculation() == str(cid3)
