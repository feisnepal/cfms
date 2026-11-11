"""
ForestManager model - NEW table for user-forest assignments
"""
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from ..core.database import Base


class ForestManager(Base):
    """
    ForestManager model - junction table for user-forest assignments
    Links users to community forests they manage
    """
    __tablename__ = "forest_managers"
    __table_args__ = (
        UniqueConstraint('user_id', 'community_forest_id', name='uq_user_forest'),
        Index('idx_forest_managers_user', 'user_id'),
        Index('idx_forest_managers_forest', 'community_forest_id'))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    community_forest_id = Column(Integer, nullable=False)  # References admin.community_forests(id)
    role = Column(String(50), nullable=False)  # 'manager', 'chairman', 'secretary', 'member'
    assigned_date = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    user = relationship("User", back_populates="forest_managers")

    def __repr__(self):
        return f"<ForestManager(user_id={self.user_id}, forest_id={self.community_forest_id}, role={self.role})>"
