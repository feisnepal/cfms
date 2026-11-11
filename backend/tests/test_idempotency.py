"""Exactly-once semantics for retried writes (H2.17 / S2-17).

The predecessor kept keys in Redis and was unsound in five ways. Each of those
is pinned here as a test, because the failure mode of a duplicate-prevention
guard is that everything looks fine -- a duplicated tree looks exactly like a
real tree, and it reaches the volume and biomass figures in a statutory
document without anything raising.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.models.idempotency import STALE_IN_FLIGHT_MINUTES, IdempotencyRecord
from app.services.idempotency import (
    begin,
    fingerprint_of,
    mark_completed,
    mark_failed,
    purge_expired,
)


@pytest.fixture()
def key() -> str:
    return f"key-{uuid.uuid4().hex}"


@pytest.fixture()
def resource() -> str:
    return f"trees:{uuid.uuid4().hex[:8]}"


BODY = {"trees": [{"species": "Shorea robusta", "dbh": 32.5}], "plot": 7}


class TestTheFirstAttempt:
    def test_it_owns_the_reservation(self, db, key, resource):
        outcome = begin(db, key, resource, BODY)
        assert outcome.owned is True
        assert outcome.replay is None

    def test_a_record_exists_afterwards(self, db, key, resource):
        begin(db, key, resource, BODY)
        record = db.query(IdempotencyRecord).filter_by(key=key, resource=resource).one()
        assert record.state == "in_flight"
        assert record.response is None


class TestTheRetry:
    def test_a_completed_request_replays_instead_of_running_again(self, db, key, resource):
        """The whole point: the second upload must not write a second copy."""
        first = begin(db, key, resource, BODY)
        assert first.owned is True
        mark_completed(db, key, resource, {"created": 1, "ids": ["abc"]})

        second = begin(db, key, resource, BODY)
        assert second.owned is False
        assert second.replay == {"created": 1, "ids": ["abc"]}

    def test_a_second_attempt_while_the_first_runs_is_refused(self, db, key, resource):
        """The race the predecessor lost.

        It checked and then acted, so two concurrent retries both passed the
        check and both executed. Here the second caller cannot get ownership
        while the first still holds it -- the UNIQUE constraint decides, in one
        statement, not the application.
        """
        first = begin(db, key, resource, BODY)
        assert first.owned is True

        with pytest.raises(HTTPException) as exc:
            begin(db, key, resource, BODY)
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "IDEMPOTENCY_IN_PROGRESS"

    def test_only_one_of_many_simultaneous_attempts_wins(self, db, key, resource):
        """Ten retries, one owner. Anything else is a duplicate write."""
        owned, refused = 0, 0
        for _ in range(10):
            try:
                if begin(db, key, resource, BODY).owned:
                    owned += 1
            except HTTPException as exc:
                assert exc.status_code == 409
                refused += 1
        assert owned == 1, f"{owned} callers believed they owned the write"
        assert refused == 9


class TestKeyReuse:
    def test_the_same_key_with_a_different_body_is_rejected(self, db, key, resource):
        """Replaying the first response would discard this payload silently --
        for field data, an upload that vanishes without a trace."""
        begin(db, key, resource, BODY)
        mark_completed(db, key, resource, {"created": 1})

        with pytest.raises(HTTPException) as exc:
            begin(db, key, resource, {"trees": [], "plot": 99})
        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"

    def test_the_same_key_on_a_different_resource_is_a_different_operation(self, db, key):
        a = begin(db, key, "trees:alpha", BODY)
        b = begin(db, key, "trees:beta", BODY)
        assert a.owned is True and b.owned is True


class TestRecovery:
    def test_a_failed_attempt_may_be_retried(self, db, key, resource):
        begin(db, key, resource, BODY)
        mark_failed(db, key, resource, RuntimeError("database went away"))

        retry = begin(db, key, resource, BODY)
        assert retry.owned is True, "a failed write must be retryable"

    def test_a_stale_in_flight_record_is_taken_over(self, db, key, resource):
        """Without this a crashed worker leaves a tombstone that refuses every
        later attempt at the same upload -- a transient failure made permanent,
        which for field data means the records never arrive at all."""
        begin(db, key, resource, BODY)
        record = db.query(IdempotencyRecord).filter_by(key=key, resource=resource).one()
        record.created_at = datetime.now(timezone.utc) - timedelta(
            minutes=STALE_IN_FLIGHT_MINUTES + 5
        )
        db.commit()

        retry = begin(db, key, resource, BODY)
        assert retry.owned is True

    def test_a_fresh_in_flight_record_is_NOT_taken_over(self, db, key, resource):
        """The other half: a genuinely running job must never be stolen."""
        begin(db, key, resource, BODY)
        with pytest.raises(HTTPException) as exc:
            begin(db, key, resource, BODY)
        assert exc.value.status_code == 409


class TestWithoutAKey:
    def test_it_proceeds_unprotected_by_default(self, db, resource):
        """Legacy callers keep working; the log records that they are exposed."""
        outcome = begin(db, None, resource, BODY)
        assert outcome.owned is False and outcome.replay is None

    def test_it_refuses_when_the_endpoint_requires_one(self, db, resource):
        with pytest.raises(HTTPException) as exc:
            begin(db, None, resource, BODY, required=True)
        assert exc.value.status_code == 400
        assert exc.value.detail["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    def test_an_over_long_key_is_rejected_clearly(self, db, resource):
        with pytest.raises(HTTPException) as exc:
            begin(db, "x" * 300, resource, BODY)
        assert exc.value.status_code == 400
        assert exc.value.detail["code"] == "IDEMPOTENCY_KEY_TOO_LONG"


class TestTheFingerprint:
    def test_key_order_does_not_change_it(self):
        """Two encoders may order a dict differently; that is the same request."""
        assert fingerprint_of({"a": 1, "b": 2}) == fingerprint_of({"b": 2, "a": 1})

    def test_different_data_changes_it(self):
        assert fingerprint_of({"dbh": 32.5}) != fingerprint_of({"dbh": 32.6})

    def test_it_survives_uuids_and_datetimes(self):
        """Ordinary field data. A fingerprint that raised on these would take
        the whole write down with it."""
        value = fingerprint_of({"id": uuid.uuid4(), "at": datetime.now(timezone.utc)})
        assert len(value) == 64


class TestHousekeeping:
    def test_expired_records_are_purged(self, db, key, resource):
        begin(db, key, resource, BODY)
        record = db.query(IdempotencyRecord).filter_by(key=key, resource=resource).one()
        record.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()

        assert purge_expired(db) >= 1
        assert db.query(IdempotencyRecord).filter_by(key=key, resource=resource).first() is None

    def test_live_records_are_not_purged(self, db, key, resource):
        begin(db, key, resource, BODY)
        purge_expired(db)
        assert db.query(IdempotencyRecord).filter_by(key=key, resource=resource).first() is not None
