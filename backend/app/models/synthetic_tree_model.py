"""
Synthetic Tree Model - tracks generated tree distribution models
"""
from sqlalchemy import Column, String, DateTime, Integer, Float, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
import uuid

from ..core.database import Base


class SyntheticTreeModel(Base):
    """
    Synthetic Tree Model - stores metadata for generated tree distributions

    Tracks GPKG files containing synthetic individual tree points generated
    from canopy height raster data and species proportions.
    """
    __tablename__ = "synthetic_tree_models"
    __table_args__ = (
        Index('idx_synthetic_models_calculation', 'calculation_id'),
        Index('idx_synthetic_models_user', 'user_id'),
        Index('idx_synthetic_models_status', 'status'))

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Model configuration
    model_version = Column(String(20), nullable=False)  # e.g., "v1.0_prototype"
    algorithm_config = Column(JSONB, nullable=False)  # Parameters used for generation

    # Generation statistics
    total_trees = Column(Integer, nullable=True)
    area_hectares = Column(Float, nullable=True)
    trees_per_hectare = Column(Float, nullable=True)
    min_dbh_cm = Column(Float, nullable=True)
    max_dbh_cm = Column(Float, nullable=True)
    min_height_m = Column(Float, nullable=True)
    max_height_m = Column(Float, nullable=True)

    # File information (GPKG - primary export)
    gpkg_filename = Column(String(255), nullable=True)
    file_size_mb = Column(Float, nullable=True)
    file_path = Column(Text, nullable=True)

    # Excel export (regulation format)
    excel_filename = Column(String(255), nullable=True)
    excel_size_mb = Column(Float, nullable=True)
    excel_path = Column(Text, nullable=True)

    # Status tracking
    status = Column(String(20), nullable=False, default="processing")  # processing, completed, failed
    error_message = Column(Text, nullable=True)
    progress_percent = Column(Integer, nullable=True, default=0)
    current_step = Column(String(100), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    processing_time_seconds = Column(Integer, nullable=True)

    # Relationships
    calculation = relationship("Calculation", back_populates="synthetic_tree_models")
    user = relationship("User")

    def __repr__(self):
        return f"<SyntheticTreeModel(id={self.id}, calculation_id={self.calculation_id}, status={self.status}, total_trees={self.total_trees})>"

    @property
    def is_processing(self):
        """Check if model is currently being generated"""
        return self.status == "processing"

    @property
    def is_completed(self):
        """Check if model generation completed successfully"""
        return self.status == "completed"

    @property
    def is_failed(self):
        """Check if model generation failed"""
        return self.status == "failed"
