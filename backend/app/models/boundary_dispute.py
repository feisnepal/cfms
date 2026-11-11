import enum
from sqlalchemy import (
    Index,
    Column,
    String,
    DateTime,
    Integer,
    ForeignKey,
    Text,
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from datetime import datetime

from ..core.database import Base


class DisputeStatus(str, enum.Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class BoundaryDispute(Base):
    __tablename__ = "boundary_disputes"
    __table_args__ = (
        Index("ix_public_boundary_disputes_forest_id_1", "forest_id_1"),
        Index("ix_public_boundary_disputes_forest_id_2", "forest_id_2"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    filed_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    forest_id_1 = Column(
        UUID(as_uuid=True), ForeignKey("calculations.id"), nullable=False, index=True
    )
    forest_id_2 = Column(
        UUID(as_uuid=True), ForeignKey("calculations.id"), nullable=False, index=True
    )
    dispute_reason_np = Column(Text, nullable=False)
    forest_1_boundary = Column(Geometry(srid=4326), nullable=True)
    forest_2_proposed = Column(Geometry(srid=4326), nullable=True)
    forest_2_clipped = Column(Geometry(srid=4326), nullable=True)
    overlap_area = Column(Geometry(srid=4326), nullable=True)
    gap_geometry = Column(Geometry(srid=4326), nullable=True)
    dispute_reason_type = Column(String(16), nullable=True)
    status = Column(SQLEnum(DisputeStatus), nullable=False, default=DisputeStatus.OPEN)
    assigned_to_dfo_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolved_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolution_type = Column(String(20), nullable=True)
    resolution_notes_np = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    filer = relationship("User", foreign_keys=[filed_by_user_id])
    forest_1 = relationship("Calculation", foreign_keys=[forest_id_1])
    forest_2 = relationship("Calculation", foreign_keys=[forest_id_2])
    dfo = relationship("User", foreign_keys=[assigned_to_dfo_id])
    resolver = relationship("User", foreign_keys=[resolved_by_user_id])
