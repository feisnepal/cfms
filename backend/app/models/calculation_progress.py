"""CalculationProgress — tracks per-step progress during async map calculation."""
import sqlalchemy as sa
from sqlalchemy import Index, Column, String, DateTime, Integer, Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime
import uuid

from ..core.database import Base


class CalculationProgress(Base):
    __tablename__ = "calculation_progress"
    __table_args__ = (
        Index('ix_public_calculation_progress_calculation_id', 'calculation_id'),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False, index=True)

    current_step = Column(String(50), nullable=False, default="pending")
    step_label = Column(String(255), nullable=True)
    step_index = Column(Integer, nullable=False, default=0)
    total_steps = Column(Integer, nullable=False, default=1)
    percent = Column(Float, nullable=False, default=0.0)
    message = Column(Text, nullable=True)
    detail = Column(JSONB, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    correlation_id = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
