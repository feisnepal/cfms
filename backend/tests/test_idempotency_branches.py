"""Supplementary hits for the idempotency service's defensive branches (H4.2).

`test_idempotency.py` covers the main flow. These cover the remaining lines:
the fingerprint/response serialisation guards and the bookkeeping no-key
returns and error fallbacks that no current test reached.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.idempotency import IdempotencyRecord
from app.services.idempotency import (
    fingerprint_of,
    mark_completed,
    mark_failed,
)


@pytest.fixture()
def key():
    return f"key-{uuid.uuid4().hex}"


@pytest.fixture()
def resource():
    return f"trees:{uuid.uuid4().hex[:8]}"


BODY = {"trees": [{"species": "Shorea robusta", "dbh": 32.5}]}


def _cyclic():
    box: list = []
    box.append(box)
    return box


class TestFingerprintGuard:
    def test_a_cyclic_body_is_refused_not_fingerprinted(self):
        with pytest.raises(ValueError):
            fingerprint_of({"trees": _cyclic()})


class TestBeginConflictPaths:
    def test_key_reused_with_a_different_body_refuses(self, db, key, resource):
        from fastapi import HTTPException

        from app.services.idempotency import begin

        begin(db, key, resource, {"trees": [{"species": "Shorea robusta", "dbh": 32.5}]})

        with pytest.raises(HTTPException) as exc:
            begin(db, key, resource, {"trees": [{"species": "Dalbergia sissoo", "dbh": 40.0}]})

        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"

    def test_a_lost_insert_is_treated_as_a_new_attempt(self, db, key, resource, monkeypatch):
        """H4.2: reservation says it conflicted, but the visible DB holds no row
        (cleaned up between the two statements) -> treat the write as new."""
        import app.services.idempotency as idm

        class _NoRows:
            def first(self):
                return None

        class _Reservation:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, *args, **kwargs):
                return _NoRows()

            def commit(self):
                pass

        monkeypatch.setattr(idm, "SessionLocal", lambda: _Reservation())

        from app.services.idempotency import begin

        outcome = begin(db, key, resource, BODY)
        assert outcome.owned is False
        assert outcome.replay is None


class TestMarkCompletedBranches:
    def test_no_key_returns_early(self, db, resource):
        assert mark_completed(db, None, resource, {"ok": 1}) is None

    def test_an_unserialisable_response_records_without_a_body(self, db, key, resource):
        from app.services.idempotency import begin

        begin(db, key, resource, BODY)
        mark_completed(db, key, resource, _cyclic())

        record = db.query(IdempotencyRecord).filter_by(key=key, resource=resource).one()
        assert record.state == "completed"
        assert record.response is None


class TestMarkFailedBranches:
    def test_no_key_returns_early(self, db, resource):
        assert mark_failed(db, None, resource, RuntimeError("nope")) is None

    def test_a_poisoned_transaction_is_swallowed(self, db, key, resource, monkeypatch):
        from app.services.idempotency import begin

        begin(db, key, resource, BODY)
        monkeypatch.setattr(
            db,
            "commit",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("lost connection")),
        )
        # The swallow must not raise: a stale in-flight record is recoverable,
        # the real error is not.
        mark_failed(db, key, resource, RuntimeError("real error"))


class TestTheModel:
    def test_repr_is_readable(self):
        r = IdempotencyRecord(key="k", resource="r", state="in_flight")
        assert "k" in repr(r)

    def test_a_non_in_flight_record_is_not_stale(self):
        r = IdempotencyRecord(key="k", resource="r", state="completed")
        assert r.is_stale_in_flight is False

    def test_a_missing_timestamp_is_not_stale(self):
        r = IdempotencyRecord(key="k", resource="r", state="in_flight")
        r.created_at = None
        assert r.is_stale_in_flight is False

    def test_a_naive_timestamp_is_treated_as_utc(self):
        from datetime import datetime

        r = IdempotencyRecord(key="k", resource="r", state="in_flight")
        r.created_at = datetime.utcnow()
        assert r.is_stale_in_flight is False
