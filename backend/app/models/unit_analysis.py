"""What "Run analysis" computed for ONE unit polygon (block, compartment, sub-block or sub-compartment).

``values`` holds the flattened ``an_*`` values the attribute table shows (see ``services/unit_analysis_service.py``). A unit
that failed keeps ``error`` and counts as not analysed. Deleting the unit or the forest deletes the row.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..core.database import Base


class UnitAnalysis(Base):
    __tablename__ = "unit_analysis"
    __table_args__ = (Index("uq_unit_analysis_block_id", "block_id", unique=True),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False, index=True)
    block_id = Column(UUID(as_uuid=True), ForeignKey("forest_blocks.id", ondelete="CASCADE"), nullable=False)
    values = Column(JSONB, nullable=False, default=dict)
    raw = Column(JSONB, nullable=False, default=dict)  # the analyser's full result; the OP placeholders read this
    error = Column(Text, nullable=True)
    computed_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
