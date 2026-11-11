"""Exactly-once semantics for retried writes (H2.17 / S2-17).

Replaces `idempotency_service.py`, which was racy and failed open. See
`app/models/idempotency.py` and migration 053 for why it could not simply be
extended to the other 84 mobile-facing write endpoints.

The shape at a call site::

    outcome = begin(db, key, "trees:<calc_id>", body, user_id=user.id)
    if outcome.replay is not None:
        return outcome.replay
    try:
        result = ...do the write...
    except Exception as exc:
        mark_failed(db, key, resource, exc)
        raise
    mark_completed(db, key, resource, result)
    return result

`begin()` either hands you ownership or raises the right HTTP error, so a call
site cannot accidentally proceed on a duplicate: the only way past it is to own
the reservation or to have a response to replay.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..models.idempotency import RETENTION_HOURS, IdempotencyRecord

logger = logging.getLogger(__name__)

MAX_KEY_LENGTH = 255


def fingerprint_of(payload: Any) -> str:
    """A stable SHA-256 of the request body.

    `sort_keys` because two encoders may order a dict differently and that must
    not read as a different payload. `default=str` so UUIDs, datetimes and
    Decimals fingerprint rather than raising -- a fingerprint that throws on
    ordinary field data would take the whole write down with it.
    """
    try:
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        )
    except (TypeError, ValueError) as exc:
        # Deliberately not silent: an unfingerprintable body means the
        # protection is not active for that request, and the caller deserves
        # to know rather than to believe it is protected.
        raise ValueError(f"Request body cannot be fingerprinted: {exc}") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class Outcome:
    """What `begin()` decided.

    `replay` set  -> return it unchanged; the work already happened.
    `replay` None -> you own the reservation; do the work, then mark it.
    """

    replay: Optional[dict[str, Any]]
    owned: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def begin(
    db: Session,
    key: Optional[str],
    resource: str,
    payload: Any,
    *,
    user_id: Optional[UUID] = None,
    required: bool = False,
) -> Outcome:
    """Reserve `(key, resource)`, replay a finished one, or refuse.

    Raises 400 when a key is required and absent, 409 while an identical
    request is still running, and 422 when a key is reused with a different
    body.
    """
    if not key:
        if required:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "IDEMPOTENCY_KEY_REQUIRED",
                    "message": "This endpoint requires an Idempotency-Key header.",
                },
            )
        # Legacy callers without a key get the old behaviour: no protection.
        # Not silent -- an unprotected write to a mobile-facing endpoint is
        # exactly what this task exists to find, so it is visible in the log.
        logger.info(
            "idempotency: no key supplied for %s - write is unprotected", resource
        )
        return Outcome(replay=None, owned=False)

    if len(key) > MAX_KEY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "IDEMPOTENCY_KEY_TOO_LONG",
                "message": f"Idempotency-Key must be at most {MAX_KEY_LENGTH} characters.",
            },
        )

    fingerprint = fingerprint_of(payload)
    expires_at = _now() + timedelta(hours=RETENTION_HOURS)

    # Reserve in a SEPARATE session, committed immediately.
    #
    # It has to be visible to a concurrent retry before the work starts, and a
    # row written in the endpoint's own transaction is invisible to everyone
    # else until that transaction commits -- by which time both callers would
    # already have done the work.
    #
    # ON CONFLICT DO NOTHING makes this the atomic step: exactly one caller
    # gets a row back, and every other caller gets nothing and must consult the
    # record that already exists. The database arbitrates, not the application,
    # so this holds across gunicorn workers and across hosts.
    inserted = False
    with SessionLocal() as reservation_db:
        result = reservation_db.execute(
            text(
                """
                INSERT INTO public.idempotency_records
                    (id, key, resource, fingerprint, state, user_id, created_at, expires_at)
                VALUES
                    (gen_random_uuid(), :key, :resource, :fingerprint, 'in_flight',
                     :user_id, now(), :expires_at)
                ON CONFLICT (key, resource) DO NOTHING
                RETURNING id
            """
            ),
            {
                "key": key,
                "resource": resource,
                "fingerprint": fingerprint,
                "user_id": str(user_id) if user_id else None,
                "expires_at": expires_at,
            },
        )
        inserted = result.first() is not None
        reservation_db.commit()

    if inserted:
        return Outcome(replay=None, owned=True)

    # Somebody else holds it. Decide from the existing record.
    existing = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.key == key, IdempotencyRecord.resource == resource)
        .first()
    )
    if existing is None:
        # Lost the insert but cannot see the row: it was cleaned up between the
        # two statements. Treat as a fresh attempt rather than refusing a write
        # that may never have happened.
        logger.warning(
            "idempotency: conflict on %s/%s but no record found - treating as new",
            resource,
            key,
        )
        return Outcome(replay=None, owned=False)

    if existing.fingerprint != fingerprint:
        # The same key with different data. Replaying the first response would
        # discard this payload silently, which for field data means the second
        # upload vanishes without a trace.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": (
                    "This Idempotency-Key was already used for a different "
                    "request body. Use a new key for a new request."
                ),
            },
        )

    if existing.state == "completed":
        return Outcome(replay=existing.response or {}, owned=False)

    if existing.state == "failed":
        # The previous attempt failed, so this is a legitimate retry. Take the
        # record over rather than refusing forever.
        existing.state = "in_flight"
        existing.error = None
        existing.created_at = _now()
        existing.expires_at = expires_at
        db.commit()
        return Outcome(replay=None, owned=True)

    # Still in flight.
    if existing.is_stale_in_flight:
        # The owner appears to have died. Without this, a crashed worker leaves
        # a tombstone that refuses every later attempt at the same upload,
        # turning a transient failure into a permanent one.
        logger.warning(
            "idempotency: taking over a stale in-flight record for %s/%s",
            resource,
            key,
        )
        existing.created_at = _now()
        existing.expires_at = expires_at
        db.commit()
        return Outcome(replay=None, owned=True)

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "IDEMPOTENCY_IN_PROGRESS",
            "message": (
                "An identical request is still being processed. "
                "Retry in a few seconds."
            ),
        },
    )


def mark_completed(
    db: Session, key: Optional[str], resource: str, response: Any
) -> None:
    """Record the response so a later retry replays it instead of re-running."""
    if not key:
        return
    try:
        payload = json.loads(json.dumps(response, default=str))
    except (TypeError, ValueError) as exc:
        # The write succeeded; only the bookkeeping failed. Recording the
        # completion without a body is better than leaving it in_flight, which
        # would let a stale takeover re-run the write and duplicate it.
        logger.error(
            "idempotency: cannot serialise response for %s/%s: %s",
            resource,
            key,
            exc,
            exc_info=True,
        )
        payload = None

    db.query(IdempotencyRecord).filter(
        IdempotencyRecord.key == key,
        IdempotencyRecord.resource == resource,
    ).update(
        {"state": "completed", "response": payload, "completed_at": _now()},
        synchronize_session=False,
    )
    db.commit()


def mark_failed(
    db: Session, key: Optional[str], resource: str, error: BaseException | str
) -> None:
    """Record a failure so the next attempt may retry rather than wait it out."""
    if not key:
        return
    try:
        db.rollback()  # the caller's transaction is probably poisoned
        db.query(IdempotencyRecord).filter(
            IdempotencyRecord.key == key,
            IdempotencyRecord.resource == resource,
        ).update(
            {"state": "failed", "error": str(error)[:2000], "completed_at": _now()},
            synchronize_session=False,
        )
        db.commit()
    except Exception as exc:
        # Never let bookkeeping replace the original error. A stale in-flight
        # record is recoverable; losing the real exception is not.
        logger.error(
            "idempotency: could not record failure for %s/%s: %s",
            resource,
            key,
            exc,
            exc_info=True,
        )


def purge_expired(db: Session) -> int:
    """Delete records past their expiry. Returns how many went."""
    deleted = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.expires_at < _now())
        .delete(synchronize_session=False)
    )
    db.commit()
    if deleted:
        logger.info("idempotency: purged %d expired record(s)", deleted)
    return deleted
