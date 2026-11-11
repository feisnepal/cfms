from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Index, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID

from ..core.database import Base

# Draft lifecycle states for digitize layers (Gap 1.1)
DRAFT_STATUS_ACTIVE = "active"
DRAFT_STATUS_SYNCING = "syncing"
DRAFT_STATUS_VALIDATION_FAILED = "validation_failed"
DRAFT_STATUS_FINALIZED = "finalized"
DRAFT_STATUS_DISCARDED = "discarded"

DRAFT_STATUS_ALL = {
    DRAFT_STATUS_ACTIVE,
    DRAFT_STATUS_SYNCING,
    DRAFT_STATUS_VALIDATION_FAILED,
    DRAFT_STATUS_FINALIZED,
    DRAFT_STATUS_DISCARDED,
}


class WorkspaceLayer(Base):
    __tablename__ = "workspace_layers"

    id = Column(Integer, primary_key=True, index=True)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    # NULL = unassigned layer (the "Skip / Assign Purpose Later" import). A chosen
    # purpose is one of block/compartment/sub_compartment/sub_area/user_group/custom/reference.
    purpose = Column(String(50), nullable=True)
    source_format = Column(String(10), nullable=False)  # .geojson/.kml/.kmz/.gpx/.csv/.xlsx/.shp
    feature_count = Column(Integer, default=0)
    file_size_bytes = Column(Integer, nullable=True)
    geometry_types = Column(JSON, nullable=True)  # ["Polygon", "LineString", ...]
    layer_data = Column(JSON, nullable=True)  # GeoJSON FeatureCollection
    layer_metadata = Column(JSON, nullable=True)
    layer_hash = Column(String(64), nullable=True)  # SHA-256 for dedup
    is_draft = Column(Boolean, default=True)
    draft_status = Column(String(20), nullable=True)  # None=legacy import, else active/syncing/validation_failed/finalized/discarded
    last_validation_error = Column(JSON, nullable=True)  # {rule, message, feature_id} when validation_failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # soft delete
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        Index('idx_workspace_layers_calc_draft_status', 'calculation_id', 'draft_status'),
        Index("idx_workspace_layers_calc_id", "calculation_id"),
        Index("idx_workspace_layers_calc_draft", "calculation_id", "is_draft"),
        Index("idx_workspace_layers_calc_purpose", "calculation_id", "purpose"),
        Index("idx_workspace_layers_calc_hash", "calculation_id", "layer_hash"),
        {"extend_existing": True},
    )
