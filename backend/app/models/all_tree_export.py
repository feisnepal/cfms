"""
All Tree Export - tracks full-extent tree exports from canopy height raster
"""
from sqlalchemy import Column, String, DateTime, Integer, Float, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from ..core.database import Base


class AllTreeExport(Base):
    """
    All Tree Export - stores metadata for full-extent tree exports

    Tracks GPKG/Excel/CSV files containing ALL individual tree points
    generated from the canopy height raster across the entire forest boundary.
    """
    __tablename__ = "all_tree_exports"
    __table_args__ = (
        Index('idx_all_tree_exports_calculation', 'calculation_id'),
        Index('idx_all_tree_exports_user', 'user_id'),
        Index('idx_all_tree_exports_status', 'status'))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Model type: 'full_extent' = all trees in boundary, 'sample_subset' = filtered by plot buffers
    model_type = Column(String(20), nullable=False, default="full_extent")

    # Model configuration
    model_version = Column(String(20), nullable=False)
    algorithm_config = Column(JSONB, nullable=False)

    # Generation statistics
    total_trees = Column(Integer, nullable=True)
    area_hectares = Column(Float, nullable=True)
    trees_per_hectare = Column(Float, nullable=True)
    min_dbh_cm = Column(Float, nullable=True)
    max_dbh_cm = Column(Float, nullable=True)
    min_height_m = Column(Float, nullable=True)
    max_height_m = Column(Float, nullable=True)

    # GPKG file
    gpkg_filename = Column(String(255), nullable=True)
    gpkg_size_mb = Column(Float, nullable=True)
    gpkg_path = Column(Text, nullable=True)

    # Excel file (flat format: 1 row = 1 tree)
    excel_filename = Column(String(255), nullable=True)
    excel_size_mb = Column(Float, nullable=True)
    excel_path = Column(Text, nullable=True)

    # CSV file (flat format)
    csv_filename = Column(String(255), nullable=True)
    csv_size_mb = Column(Float, nullable=True)
    csv_path = Column(Text, nullable=True)

    # Status tracking
    status = Column(String(20), nullable=False, default="processing")
    error_message = Column(Text, nullable=True)
    progress_percent = Column(Integer, nullable=True, default=0)
    current_step = Column(String(100), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    processing_time_seconds = Column(Integer, nullable=True)

    # Relationships
    calculation = relationship("Calculation", back_populates="all_tree_exports")
    user = relationship("User")

    def __repr__(self):
        return f"<AllTreeExport(id={self.id}, calculation_id={self.calculation_id}, type={self.model_type}, status={self.status}, total_trees={self.total_trees})>"

    @property
    def expires_at(self):
        """When this export is deleted (one hour after it finishes); None while running."""
        from ..services.export_cleanup import all_tree_export_expiry
        return all_tree_export_expiry(self)

    @property
    def is_processing(self):
        return self.status == "processing"

    @property
    def is_completed(self):
        return self.status == "completed"

    @property
    def is_failed(self):
        return self.status == "failed"
