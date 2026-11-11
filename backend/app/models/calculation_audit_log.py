"""Calculation audit log — immutable state transition records for map lifecycle."""
import sqlalchemy as sa
from sqlalchemy import Index, Column, String, DateTime, Integer, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid

from ..core.database import Base


class CalculationAuditLog(Base):
    __tablename__ = "calculation_audit_log"
    __table_args__ = (
        Index('ix_public_calculation_audit_log_calculation_id', 'calculation_id'),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id"), nullable=False, index=True)
    from_state = Column(String(20), nullable=False)
    to_state = Column(String(20), nullable=False)
    triggered_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reason = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    correlation_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
