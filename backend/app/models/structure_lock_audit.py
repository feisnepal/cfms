from sqlalchemy import Index, Column, String, DateTime, Integer, ForeignKey, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime

from ..core.database import Base


class StructureLockAudit(Base):
    """
    Audit trail for structure_locked state transitions (S14).

    Records every lock/unlock event including who triggered it and why
    (Nepali reason required for DFO actions).
    """
    __tablename__ = "structure_lock_audits"
    __table_args__ = (
        Index('idx_sla_created_at', 'created_at'),
        Index('ix_public_structure_lock_audits_calculation_id', 'calculation_id'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id"), nullable=False, index=True)
    transition = Column(String(30), nullable=False)
    from_state = Column(Boolean, nullable=False)
    to_state = Column(Boolean, nullable=False)
    triggered_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reason_np = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    calculation = relationship("Calculation", foreign_keys=[calculation_id])
    triggered_by = relationship("User", foreign_keys=[triggered_by_user_id])
