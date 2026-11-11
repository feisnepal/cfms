"""Operational Plan model (operational_plans).

Stores the document state for each Operational Plan: the section tree
(JSONB), metadata, and status. Each OP is linked to exactly one
Calculation. The sections JSONB contains the full document tree that
can be modified and exported to DOCX.

See also:
    app.models.op_template.OPTemplate — template model for seeding new OPs
    app.services.operational_plan.op_docx_builder — DOCX export engine
"""

from sqlalchemy import Column, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy import func
from datetime import datetime
import uuid
from ..core.database import Base

class OperationalPlan(Base):
    """Operational Plan instance linked to a Calculation with full document tree."""
    __tablename__ = "operational_plans"
    __table_args__ = (
        Index("idx_operational_plans_calculation_id", "calculation_id"),
        Index("idx_operational_plans_status", "status"))
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False, unique=True)
    forest_name = Column(String(255), nullable=True)
    sections = Column(JSONB, nullable=True, default=dict)
    plan_metadata = Column(JSONB, nullable=True, default=dict)
    status = Column(String(50), nullable=False, server_default="draft")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    submitted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    calculation = relationship("Calculation", back_populates="operational_plan")

    def __repr__(self):
        return f"<OperationalPlan(id={self.id}, calculation_id={self.calculation_id}, status={self.status})>"
