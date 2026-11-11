"""Digitize audit log — forestry compliance trail (Gap 6.1 / Task 1.4.4).

Records "who mapped what boundary when" for on-screen digitizing:
one row per flush (add_feature), plus finalize and discard actions.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID

from ..core.database import Base


class DigitizeAuditLog(Base):
    __tablename__ = "digitize_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    calculation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("calculations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    layer_id = Column(Integer, nullable=False, index=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # create_draft | add_feature | finalize | discard
    action = Column(String(30), nullable=False)
    feature_count_delta = Column(Integer, default=0)
    geometry_hash = Column(String(64), nullable=True)  # sha256 of feature geometry (concatenated)
    details = Column(String(500), nullable=True)  # e.g. validation error summary
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_digitize_audit_layer", "layer_id", "created_at"),
        Index("idx_digitize_audit_calc", "calculation_id", "created_at"),
    )

    calculation = relationship("Calculation", foreign_keys=[calculation_id])
    user = relationship("User", foreign_keys=[user_id])
