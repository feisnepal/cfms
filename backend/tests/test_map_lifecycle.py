"""
Tests for the map lifecycle state machine:

- Transition validation (validate_transition)
- State machine decorator (require_map_state)
- Calculation model extensions
- Audit log model
"""
import pytest
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import HTTPException

from app.api.deps import validate_transition, log_state_transition
from app.models.calculation import MapLifecycleStatus


class TestValidateTransition:
    def test_draft_to_submitted(self):
        validate_transition("draft", "submitted")  # no error

    def test_draft_to_locked_raises(self):
        with pytest.raises(HTTPException) as exc:
            validate_transition("draft", "locked")
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "INVALID_MAP_STATE"

    def test_submitted_to_calculating(self):
        validate_transition("submitted", "calculating")

    def test_submitted_may_return_to_draft(self):
        """Changed 2026-08-27 (H-SUBMIT A2). It used to raise.

        Submitting now FREEZES the map, so the owner needs a way back while
        analysis has not started -- otherwise a typo spotted thirty seconds
        after submitting costs a support request, which teaches people not to
        submit at all.

        Nothing documented a reason for the old rule; the test transcribed the
        table. And the table was already inconsistent with it: `completed ->
        draft`, `locked -> draft` and `failed -> submitted` were all allowed, so
        a COMPLETED map could be reopened while one merely waiting to start
        could not.

        The narrow window is enforced by `withdraw_submission`, not here: that
        endpoint checks the state is exactly `submitted` and answers 409
        otherwise, so this entry does not let anything unwind mid-analysis.
        """
        validate_transition("submitted", "draft")  # no error

    def test_submitted_can_still_go_forward(self):
        """The widening must not have cost the forward transitions."""
        validate_transition("submitted", "calculating")
        validate_transition("submitted", "failed")

    def test_calculating_to_completed(self):
        validate_transition("calculating", "completed")

    def test_calculating_to_retrying(self):
        validate_transition("calculating", "retrying")

    def test_calculating_to_failed(self):
        validate_transition("calculating", "failed")

    def test_calculating_to_locked_raises(self):
        with pytest.raises(HTTPException):
            validate_transition("calculating", "locked")

    def test_retrying_to_calculating(self):
        validate_transition("retrying", "calculating")

    def test_retrying_to_failed(self):
        validate_transition("retrying", "failed")

    def test_failed_to_submitted(self):
        validate_transition("failed", "submitted")

    def test_failed_to_draft_raises(self):
        with pytest.raises(HTTPException):
            validate_transition("failed", "draft")

    def test_completed_to_locked(self):
        validate_transition("completed", "locked")

    def test_completed_to_draft(self):
        validate_transition("completed", "draft")

    def test_locked_to_draft(self):
        validate_transition("locked", "draft")

    def test_locked_to_submitted_raises(self):
        with pytest.raises(HTTPException):
            validate_transition("locked", "submitted")

    def test_unknown_from_state_raises(self):
        with pytest.raises(HTTPException):
            validate_transition("unknown", "draft")


class TestMapLifecycleStatusEnum:
    def test_all_values_present(self):
        values = [e.value for e in MapLifecycleStatus]
        assert set(values) == {
            "draft", "submitted", "calculating", "retrying",
            "failed", "completed", "locked",
        }

    def test_allowed_transitions_covered(self):
        """Every enum value should have at least one allowed transition (except terminal)."""
        from app.api.deps import ALLOWED_TRANSITIONS
        for state in MapLifecycleStatus:
            assert state.value in ALLOWED_TRANSITIONS, f"{state.value} missing from ALLOWED_TRANSITIONS"


class TestAuditLog:
    def test_log_state_transition(self, db):
        from app.models.calculation import Calculation, CalculationStatus
        from app.models.calculation_audit_log import CalculationAuditLog
        from app.models.user import User

        user = User(id=uuid4(), email="audit@test.com", full_name="Audit Tester", hashed_password="x")
        db.add(user)
        db.flush()
        calc = Calculation(id=uuid4(), user_id=user.id, status=CalculationStatus.PENDING)
        db.add(calc)
        db.flush()

        log_state_transition(db, calc.id, "draft", "submitted", triggered_by=user.id)
        db.commit()

        entry = db.query(CalculationAuditLog).filter(
            CalculationAuditLog.calculation_id == calc.id
        ).first()
        assert entry is not None
        assert entry.from_state == "draft"
        assert entry.to_state == "submitted"
        assert str(entry.triggered_by) == str(user.id)


class TestCalculationModelExtension:
    def test_map_lifecycle_status_column_configured(self):
        """Verify the column has a default of 'draft' and is not nullable."""
        from app.models.calculation import Calculation
        col = Calculation.__table__.c.map_lifecycle_status
        assert col.default is not None
        assert str(col.default.arg) == 'draft'
        assert col.nullable is False
