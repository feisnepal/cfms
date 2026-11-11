"""Submission record: a statutory document leaves the building.

See also:
    alembic/versions/097_document_submissions -- DDL and the append-only RULES
    app.services.document_integrity           -- issuance (bytes, hash, code)
    app.core.forest_delete_rules              -- why this table outlives its forest

An operational plan is exported to .docx, printed, and submitted to the District
Forest Office. `document_issuances` records that the document was *produced*;
this table records that it was *handed over*. Those are different facts with
different lifetimes, which is why they are different tables -- and why the
issuance table's UPDATE rule could not have carried the second one.

Per WORKSPACE_FLOW_NAV_PLAN D17, a row here is the fact and
`OperationalPlan.status` is a read-only projection of the latest one. Nothing
writes `status` independently.

No foreign keys on `calculation_id` / `plan_id`, and no ORM relationships: the
record that a statutory document was submitted to an office must outlive deletion
of the forest it describes, so the ids are evidence rather than referential
integrity. The consequence is that this table deliberately never cascades.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from ..core.database import Base

# How a submission reached the receiving office. `hand_delivery` is the default
# because the statutory route is a printed hard copy carried in by hand.
SUBMISSION_CHANNELS: tuple[str, ...] = (
    "hand_delivery",
    "email",
    "post",
    "portal",
)


class DocumentSubmission(Base):
    """One act of submitting an issued document to a receiving office."""

    __tablename__ = "document_submissions"
    __table_args__ = (
        Index("ix_document_submissions_plan_id_submitted_at", "plan_id", "submitted_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                server_default=func.gen_random_uuid())

    # Which issuance this is about. Not an FK -- see the module docstring.
    issuance_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    calculation_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    plan_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # The receiving office and when it happened. `submitted_to` is free text
    # because no office table exists in this system and one string column does not
    # justify inventing one.
    submitted_to = Column(String(255), nullable=False)
    submitted_at = Column(DateTime(timezone=True), nullable=False,
                          server_default=func.now())
    channel = Column(String(32), nullable=False, server_default="hand_delivery")

    # The DFO's own file reference for the printed copy -- the field the forest
    # office is asked for months later, and the reason this table exists.
    reference_no = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)

    submitted_by = Column(UUID(as_uuid=True), nullable=True)
    ip_address = Column(String(64), nullable=True)
    client_type = Column(String(32), nullable=True)
    correlation_id = Column(String(64), nullable=True)

    # No ORM relationship to the issuance, deliberately. `document_issuances` has
    # no ORM model at all -- `services/document_integrity.py` writes it with raw
    # SQL -- so a relationship here would fail mapper configuration at startup and
    # take the whole app with it. `issuance_id` is evidence, not a join.

    def __repr__(self):
        return (f"<DocumentSubmission(id={self.id}, plan_id={self.plan_id}, "
                f"submitted_to={self.submitted_to!r}, ref={self.reference_no!r})>")
