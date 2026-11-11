"""
Compartment split history model
"""
from sqlalchemy import Index, Column, String, DateTime, Integer, ForeignKey, Float, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from ..core.database import Base


class CompartmentSplitHistory(Base):
    """
    Track history of compartment splitting operations

    This model stores audit logs of when and how forest blocks were
    subdivided into compartments, including the algorithm used and parameters.
    """
    __tablename__ = "compartment_split_history"
    __table_args__ = (
        Index('idx_split_history_calc', 'calculation_id'),
        Index('idx_split_history_created_at', 'created_at'),
        Index('idx_split_history_created_by', 'created_by'),
        Index('idx_split_history_parent', 'parent_block_id'),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_block_id = Column(UUID(as_uuid=True), ForeignKey("forest_blocks.id", ondelete="CASCADE"), nullable=False)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False)

    # Split configuration
    split_method = Column(String(50), nullable=False)  # 'parallel', 'grid', 'custom'
    split_direction = Column(Float, nullable=True)  # angle in degrees (0-360)
    split_parameters = Column(JSONB, nullable=True)  # method-specific parameters
    number_of_compartments = Column(Integer, nullable=False)

    # User and audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Metadata
    naming_pattern = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    # Relationships
    parent_block = relationship("ForestBlock", foreign_keys=[parent_block_id])
    # calculation = relationship("Calculation")
    # created_by_user = relationship("User")

    def __repr__(self):
        return f"<CompartmentSplitHistory(id={self.id}, method={self.split_method}, compartments={self.number_of_compartments})>"
