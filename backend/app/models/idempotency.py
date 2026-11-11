"""Durable record of idempotent writes (H2.17 / S2-17).

A field device uploads over a connection that drops. It retries. Without a
record of what has already been accepted, the retry writes a second copy of the
same trees, plots or households -- and those rows feed the volume, biomass and
carbon figures in a statutory document. Nobody notices, because a duplicate
tree looks exactly like a real tree.

Why the database and not Redis
------------------------------
The previous implementation kept keys in Redis with an in-memory fallback, and
had two properties that made it unsound for this:

* it checked and then acted, so two concurrent retries could both pass the
  check and both execute, which is the duplicate it existed to prevent; and
* it failed OPEN -- a Redis error was reported as "not seen before", so the
  guard switched itself off exactly when the system was under stress.

A UNIQUE constraint makes the reservation atomic in a single statement: the
database, not the application, decides who got there first, and it decides once
even across gunicorn workers. The record is also durable, so a Redis restart no
longer forgets what has been accepted. Redis remains useful as a read cache in
front of this, never as the source of truth.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..core.database import Base

# How long a completed record is honoured. A field device out of signal for a
# weekend must still have its retry recognised on Monday, so this is generous.
RETENTION_HOURS = 72

# How long an in-flight record may sit before another attempt may take it over.
# Longer than the arq hard timeout (22 min) so a genuinely running job is never
# stolen, short enough that a crashed worker does not block a resend all day.
STALE_IN_FLIGHT_MINUTES = 30


class IdempotencyRecord(Base):
    """One (key, resource) reservation and, once finished, its response."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        # The whole mechanism rests on this. Reservation is
        # `INSERT ... ON CONFLICT DO NOTHING`: exactly one caller inserts a row,
        # every other caller gets zero rows and must consult the existing one.
        UniqueConstraint("key", "resource", name="uq_idempotency_key_resource"),
        Index("ix_idempotency_expires_at", "expires_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Client-supplied. Not a UUID column: clients send opaque strings and a
    # malformed one should be rejected by validation with a clear message, not
    # by a database cast error five frames down.
    key = Column(String(255), nullable=False)

    # What the key is scoped to, e.g. "bulk:<layer_id>". The same key against a
    # different resource is a different operation.
    resource = Column(String(255), nullable=False)

    # SHA-256 of the canonical request body. A client that reuses a key with
    # DIFFERENT data has a bug, and returning the first response would hide it
    # while silently discarding the second payload -- so that is an error, not
    # a cache hit.
    fingerprint = Column(String(64), nullable=False)

    # "in_flight" | "completed" | "failed"
    state = Column(String(16), nullable=False, default="in_flight")

    # The response to replay. NULL while in flight.
    response = Column(JSONB, nullable=True)

    # Set on failure so a retry can be told why, rather than silently reissued.
    error = Column(Text, nullable=True)

    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<IdempotencyRecord(key={self.key!r}, resource={self.resource!r}, "
            f"state={self.state!r})>"
        )

    @property
    def is_stale_in_flight(self) -> bool:
        """An in-flight record whose owner appears to have died.

        Without this a crashed worker leaves a tombstone that refuses every
        later attempt at the same upload -- turning a transient failure into a
        permanent one, which for field data means the records never arrive.
        """
        if self.state != "in_flight":
            return False
        created = self.created_at
        if created is None:
            return False
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_minutes = (datetime.now(timezone.utc) - created).total_seconds() / 60
        return age_minutes > STALE_IN_FLIGHT_MINUTES
