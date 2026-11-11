from sqlalchemy import (
    Index,
    Column,
    String,
    DateTime,
    Integer,
    ForeignKey,
    Text,
    Boolean,
    Numeric,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from datetime import datetime
import uuid

from ..core.database import Base


class ForestBoundaryAudit(Base):
    __tablename__ = "forest_boundary_audits"
    __table_args__ = (Index("ix_public_forest_boundary_audits_forest_id", "forest_id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    forest_id = Column(
        UUID(as_uuid=True), ForeignKey("calculations.id"), nullable=False, index=True
    )
    submitted_geometry = Column(Geometry(srid=4326), nullable=True)
    submitted_area_ha = Column(Numeric(10, 4), nullable=True)
    submitted_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    submitted_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    resolved_geometry = Column(Geometry(srid=4326), nullable=True)
    resolved_area_ha = Column(Numeric(10, 4), nullable=True)
    overlap_removed_ha = Column(Numeric(10, 4), nullable=True)
    overlap_with_forest_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=True)
    resolution_method = Column(String(30), nullable=True)
    user_confirmed = Column(Boolean, default=False)
    user_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    dispute_id = Column(
        Integer,
        ForeignKey("boundary_disputes.id", deferrable=True, initially="DEFERRED"),
        nullable=True,
    )
    dfo_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    dfo_reason_np = Column(Text, nullable=True)
    gap_included_ha = Column(Numeric(10, 4), nullable=True)
    gap_forest_ids = Column(JSONB, nullable=True)
    dispute_reason_type = Column(String(16), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    forest = relationship("Calculation", foreign_keys=[forest_id])
    submitter = relationship("User", foreign_keys=[submitted_by_user_id])
    dfo_user = relationship("User", foreign_keys=[dfo_user_id])
