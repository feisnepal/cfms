"""
Sampling design models for forest inventory
"""
from sqlalchemy import text, Boolean, Index, Column, String, Integer, Numeric, Text, ForeignKey, DateTime, BigInteger
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from geoalchemy2 import Geometry
import uuid

from ..core.database import Base


class SamplingDesign(Base):
    """
    Sampling design for forest inventory.
    Stores methodology and generated sampling points for a calculation.
    """
    __tablename__ = "sampling_designs"
    __table_args__ = (
        Index('idx_sampling_block_overrides', 'block_overrides', postgresql_using='gin'),
        Index('idx_sampling_designs_calc_id', 'calculation_id'),
        Index('idx_sampling_designs_calculation', 'calculation_id'),
        Index('idx_sampling_designs_points', 'points_geometry', postgresql_using='gist'),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # H8.2 / S2-63: optimistic-lock counter. Bumped ONLY by
    # services/optimistic_lock.py, in the same statement that checks it -- a
    # separate read-then-write is the lost update it exists to prevent.
    version = Column(BigInteger, nullable=False, default=0, server_default=text("0"),
                     comment=("H8.2/S2-63 optimistic-lock counter. Bumped only by "
                             "services/optimistic_lock.py, in the same statement that "
                             "checks it."))

    calculation_id = Column(UUID(as_uuid=True), ForeignKey('calculations.id', ondelete='CASCADE'), nullable=False)

    # Sampling methodology
    sampling_type = Column(String(50), nullable=False)  # 'systematic', 'random', 'stratified'
    intensity_per_hectare = Column(Numeric(10, 4), nullable=True)  # Points per hectare
    grid_spacing_meters = Column(Integer, nullable=True)  # For systematic sampling
    min_distance_meters = Column(Integer, nullable=True)  # Minimum distance between points

    # Plot configuration
    plot_shape = Column(String(50), nullable=True)  # 'circular', 'square', 'rectangular'
    plot_radius_meters = Column(Numeric(10, 2), nullable=True)  # For circular plots
    plot_length_meters = Column(Numeric(10, 2), nullable=True)  # For rectangular plots
    plot_width_meters = Column(Numeric(10, 2), nullable=True)   # For rectangular plots

    # Spatial data
    exclusion_geometry = Column(Geometry('MULTIPOLYGON', srid=4326), nullable=True)  # Areas to exclude
    points_geometry = Column(Geometry('MULTIPOINT', srid=4326), nullable=True)       # Generated points

    # Summary
    total_points = Column(Integer, default=0, nullable=False)
    notes = Column(Text, nullable=True)

    # Block assignment for each point (for multi-block forests)
    # Format: [{"point_index": 0, "block_number": 1, "block_name": "Ward 5"}, ...]
    points_block_assignment = Column(JSONB, nullable=True)

    # Computed summary data from generation (total_blocks, blocks_info, sampling_percentage, etc.)
    # Stored to avoid recalculation on page reload
    result_data = Column(JSONB, nullable=True)

    # Cached computed points with elevation, UTM, boundary distance, etc.
    # Stored after first calculation to avoid expensive recomputation
    points_data = Column(JSONB, nullable=True)

    # Per-block sampling parameters (Option 2: Single design with overrides)
    # Default parameters applied to all blocks unless overridden
    # Format: {"sampling_type": "systematic", "intensity_percent": 0.5, "min_samples": 5, ...}
    default_parameters = Column(JSONB, nullable=True)

    # Block-specific parameter overrides
    # Format: {"Block 1": {"intensity_percent": 1.0, "min_samples": 10}, "Block 3": {...}}
    block_overrides = Column(JSONB, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    filter_tree_cover = Column(Boolean, nullable=False, server_default=text('true'), comment='Filter to ESA WorldCover tree pixels (value=10)')
    filter_slope = Column(Boolean, nullable=False, server_default=text('false'), comment='Filter by slope accessibility')
    max_slope_degrees = Column(Numeric(4, 1), nullable=True, comment='Maximum slope threshold in degrees')
    accessible_area_hectares = Column(Numeric(10, 4), nullable=True, comment='Accessible forest area (tree cover + slope OK)')
    inaccessible_steep_hectares = Column(Numeric(10, 4), nullable=True, comment='Tree cover but too steep for sampling')
    non_forest_area_hectares = Column(Numeric(10, 4), nullable=True, comment='Non-tree cover area (grassland, cropland, water, etc.)')

    # Relationships
    calculation = relationship("Calculation", back_populates="sampling_designs")

    def __repr__(self):
        return f"<SamplingDesign(id={self.id}, type={self.sampling_type}, points={self.total_points})>"
