"""One row per change of a user's role: who changed it, from what, to what, when.

A role decides who may author templates, approve accounts and read household data, so a change must never be anonymous.
Append-only by use (nothing updates or deletes these rows except the user's own deletion).
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from ..core.database import Base


class UserRoleChange(Base):
    __tablename__ = "user_role_changes"
    __table_args__ = (Index("idx_user_role_changes_user", "user_id", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    old_role = Column(String(40), nullable=False)
    new_role = Column(String(40), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
