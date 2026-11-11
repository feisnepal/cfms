"""
Tests for saga compensation service.
"""
from unittest.mock import Mock, patch, MagicMock
from uuid import uuid4

from app.services.saga_compensation_service import compensate_failed_calculation


class TestSagaCompensation:
    def test_compensate_clears_progress(self):
        db = MagicMock()
        cid = uuid4()

        # Mock progress delete
        delete_mock = MagicMock()
        delete_mock.delete.return_value = 1
        db.query.return_value.filter.return_value = delete_mock

        # Mock calculation query
        calc = MagicMock()
        calc.map_lifecycle_status = "calculating"
        calc.error_message = None
        db.query.return_value.filter.return_value.first.return_value = calc

        result = compensate_failed_calculation(db, cid)

        assert result["progress_cleared"] == 1
        assert calc.status.value == "failed"
        assert calc.map_lifecycle_status == "failed"
        db.flush.assert_called_once()
