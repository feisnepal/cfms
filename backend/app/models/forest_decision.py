"""A plan decision that a person made for one forest (landslide method, a block's orientation, household placement).

Only the answers are stored. What can be asked, the wording and the allowed choices live in code
(``services/decision_registry.py``), so adding a question never needs a migration. A block's
orientation answer is an audit record only: whether it is still open is read from the block's own columns.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from ..core.database import Base


class ForestDecision(Base):
    __tablename__ = "forest_decisions"
    __table_args__ = (
        # NULLS NOT DISTINCT so a forest-wide decision (scope NULL) is also unique per key.
        Index("uq_forest_decisions_calc_key_scope", "calculation_id", "key", "scope", unique=True,
              postgresql_nulls_not_distinct=True),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(64), nullable=False)
    scope = Column(String(64), nullable=True)  # a block id for per-block decisions, else NULL
    choice = Column(String(64), nullable=False)
    note = Column(Text, nullable=True)
    decided_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
