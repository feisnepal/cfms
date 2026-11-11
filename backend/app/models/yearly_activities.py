from sqlalchemy.dialects.postgresql import ARRAY
"""
Yearly Activities models for community forest planning
"""
from sqlalchemy import text, Column, String, DateTime, Integer, ForeignKey, Boolean, Numeric, Text, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import JSONB as JSONBType
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from datetime import datetime
import uuid

from ..core.database import Base


class PotentialActivity(Base):
    """
    Master list of all possible activities for community forests.
    Admins manage this table.
    """
    __tablename__ = "potential_activities"
    __table_args__ = (
        Index('idx_potential_activities_default', 'is_default'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(UUID(as_uuid=True), nullable=True)

    # Hierarchy (existing columns with typo in original table)
    sn = Column(String, nullable=True)
    project_name = Column(String, nullable=True)
    progarms = Column(String, nullable=True)  # Note: typo in original table
    activities = Column(String, nullable=True)
    # Default map symbol for features drawn for this activity: a key of
    # services/operational_plan/feature_kinds.KINDS (migration 090). NULL = generic symbol.
    map_kind = Column(String(40), nullable=True)
    # The shape this activity is drawn as ('point' | 'line' | 'polygon') when it differs from its kind's own shape
    # (owner, 2026-10-14: the shape belongs to the activity, never to its unit). NULL = the kind's shape. Migration 124.
    map_geom = Column(String(10), nullable=True)
    # English name and search words (migration 091, D29): let people find an activity by typing English or
    # romanised Nepali. Nullable; nothing reads them until they are seeded.
    name_en = Column(Text, nullable=True)
    search_terms = Column(Text, nullable=True)
    unit = Column(String, nullable=True)
    quantity = Column(String, nullable=True)  # Original as varchar
    yearly_budget = Column(String, nullable=True)  # Original as varchar
    is_default = Column(String, nullable=True)  # Original as varchar

    # New columns added by migration
    description = Column(Text, nullable=True)
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    requires_map = Column(Boolean, nullable=False, server_default=text('false'))
    # THEMATIC_MAP_VARIABLES_PLAN §3.4B / P5c (D18): an admin flags the harvest /
    # felling / कटान rows so opsmap:unit__felling_year etc. can find them.
    # NULL = not a felling activity. (migration 076)
    is_felling = Column(Boolean, nullable=True)

    # Relationships
    proposed_activities = relationship("ProposedYearlyActivity", back_populates="potential_activity", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PotentialActivity(id={self.id}, activity='{self.activities}')>"

    @property
    def program(self):
        """Alias for progarms field (with typo)"""
        return self.progarms

    @property
    def activity(self):
        """Alias for activities field"""
        return self.activities


class ProposedYearlyActivity(Base):
    """
    Activities selected by a specific community forest.
    Each forest can select multiple activities from the master list.
    Includes spatial assignment to blocks and sub-areas.
    """
    __tablename__ = "proposed_yearly_activities"
    __table_args__ = (
        Index('idx_proposed_activities_block', 'block_id'),
        Index('idx_proposed_activities_calculation', 'calculation_id'),
        Index('idx_proposed_activities_status', 'status'),
        Index('idx_proposed_activities_sub_area', 'sub_area_id'),
        CheckConstraint(
            '(sub_area_id IS NULL) OR (sub_area_id IS NOT NULL AND block_id IS NOT NULL)',
            name='check_sub_area_has_block'
        ),
        # One plan line per activity per location level (migration 091). One index per level:
        # NULL block / sub-area values are distinct to PostgreSQL.
        Index('uq_proposed_activity_forest', 'calculation_id', 'potential_activity_id', unique=True,
              postgresql_where=text('block_id IS NULL AND sub_area_id IS NULL')),
        Index('uq_proposed_activity_block', 'calculation_id', 'potential_activity_id', 'block_id', unique=True,
              postgresql_where=text('block_id IS NOT NULL AND sub_area_id IS NULL')),
        Index('uq_proposed_activity_sub_area', 'calculation_id', 'potential_activity_id', 'block_id', 'sub_area_id',
              unique=True, postgresql_where=text('sub_area_id IS NOT NULL')),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign keys
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False)
    potential_activity_id = Column(Integer, ForeignKey("potential_activities.id", ondelete="CASCADE"), nullable=False)
    block_id = Column(UUID(as_uuid=True), ForeignKey("forest_blocks.id", ondelete="SET NULL"), nullable=True)
    sub_area_id = Column(UUID(as_uuid=True), nullable=True)  # No FK - sub-areas stored in result_data

    # Default values (apply to all 10 years unless overridden)
    default_quantity = Column(Numeric(10, 2), nullable=False)
    default_yearly_budget = Column(Numeric(12, 2), nullable=False)

    # Metadata
    notes = Column(Text, nullable=True)
    status = Column(String(50), default='proposed', nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    # Optimistic-lock counter (optimistic_lock domain 'yearly_plan'); bumped by check_and_bump, never by hand
    version = Column(Integer, nullable=False, default=1, server_default=text('1'))
    # Set when the user typed or confirmed the numbers; never by the system (migration 091)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    # Spatial assignment options
    assign_to_all_blocks = Column(Boolean, default=False, nullable=False)
    use_custom_yearly_values = Column(Boolean, default=False, nullable=False)
    year_numbers = Column(ARRAY(Integer), nullable=True)

    # Relationships
    calculation = relationship("Calculation", back_populates="proposed_activities")
    potential_activity = relationship("PotentialActivity", back_populates="proposed_activities")
    block = relationship("ForestBlock", foreign_keys=[block_id])
    year_details = relationship("ActivityYearDetail", back_populates="proposed_activity", cascade="all, delete-orphan")
    spatial_assignments = relationship("ActivitySpatialAssignment", back_populates="proposed_activity", cascade="all, delete-orphan")
    drawn_features = relationship("ActivityDrawnFeature", back_populates="proposed_activity", cascade="all, delete-orphan")

    def __repr__(self):
        location = "entire forest"
        if self.block:
            location = f"{self.block.name}"
        return f"<ProposedYearlyActivity(id={self.id}, location={location})>"


class ActivityYearDetail(Base):
    """
    Year-specific overrides for quantity and budget.
    If a row exists, it overrides the default values for that year.
    """
    __tablename__ = "activity_year_details"
    __table_args__ = (
        Index('idx_activity_year_detail_activity', 'proposed_activity_id'),
        Index('idx_activity_year_number', 'year_number'),
        Index('idx_activity_year_proposed', 'proposed_activity_id'),
        Index('idx_activity_year_status', 'status'),
        CheckConstraint('year_number >= 1 AND year_number <= 10', name='check_year_number'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign key
    proposed_activity_id = Column(UUID(as_uuid=True), ForeignKey("proposed_yearly_activities.id", ondelete="CASCADE"), nullable=False)

    # Year tracking
    year_number = Column(Integer, nullable=False)

    # Overridden values (NULL = use default from proposed_yearly_activities)
    quantity = Column(Numeric(10, 2), nullable=True)
    yearly_budget = Column(Numeric(12, 2), nullable=True)

    # Year-specific details
    target_completion_month = Column(String(20), nullable=True)
    actual_quantity = Column(Numeric(10, 2), nullable=True)
    actual_budget = Column(Numeric(12, 2), nullable=True)
    status = Column(String(50), default='planned', nullable=False)

    # Notes
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    block_id = Column(UUID(as_uuid=True), ForeignKey('forest_blocks.id', ondelete='SET NULL'), nullable=True)
    sub_area_id = Column(UUID(as_uuid=True), ForeignKey('forest_sub_areas.id', ondelete='SET NULL'), nullable=True)

    # Relationships
    proposed_activity = relationship("ProposedYearlyActivity", back_populates="year_details")

    def __repr__(self):
        return f"<ActivityYearDetail(id={self.id}, year={self.year_number})>"


class ActivitySpatialAssignment(Base):
    """
    Assign activity to specific blocks or sub-areas.
    Multiple assignments allowed per activity.
    """
    __tablename__ = "activity_spatial_assignments"
    __table_args__ = (
        CheckConstraint(
            "(assignment_type = 'all_blocks') OR "
            "(block_id IS NOT NULL AND sub_area_id IS NULL AND assignment_type = 'block') OR "
            "(block_id IS NOT NULL AND sub_area_id IS NOT NULL AND assignment_type = 'sub_area')",
            name='chk_block_or_subarea'
        ),
        CheckConstraint("assignment_type IN ('all_blocks', 'block', 'sub_area')", name='chk_assignment_type'))
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposed_activity_id = Column(UUID(as_uuid=True), ForeignKey("proposed_yearly_activities.id", ondelete="CASCADE"), nullable=False)
    block_id = Column(UUID(as_uuid=True), ForeignKey("forest_blocks.id", ondelete="CASCADE"), nullable=True)
    sub_area_id = Column(UUID(as_uuid=True), nullable=True)  # No FK - sub-areas stored in result_data
    assignment_type = Column(String(20), nullable=False, server_default="all_blocks")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    
    # Relationships
    proposed_activity = relationship("ProposedYearlyActivity", back_populates="spatial_assignments")
    block = relationship("ForestBlock")

    def __repr__(self):
        return f"<ActivitySpatialAssignment(id={self.id}, type={self.assignment_type})>"


class ActivityDrawnFeature(Base):
    """
    User-drawn point/line/polygon for activities.
    Each activity can have multiple drawn features.
    """
    __tablename__ = "activity_drawn_features"
    __table_args__ = (
        CheckConstraint("feature_type IN ('point', 'line', 'polygon')", name='chk_feature_type'),
        Index("idx_activity_features_geometry_gist", "geometry", postgresql_using="gist"),
        Index("idx_activity_features_proposed_activity", "proposed_activity_id"),
        Index("idx_activity_features_calculation", "calculation_id"))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposed_activity_id = Column(UUID(as_uuid=True), ForeignKey("proposed_yearly_activities.id", ondelete="CASCADE"), nullable=False)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id"), nullable=False, index=True)
    feature_type = Column(String(20), nullable=False)
    geometry = Column(Geometry, nullable=False)
    properties = Column(JSONBType, server_default="{}")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Relationships
    proposed_activity = relationship("ProposedYearlyActivity", back_populates="drawn_features")
    calculation = relationship("Calculation", foreign_keys=[calculation_id])
    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<ActivityDrawnFeature(id={self.id}, type={self.feature_type})>"


class YearlyPlanStatus(Base):
    """Whether the owner has said the yearly activities are finished (step 15 of the workflow).

    One row per forest, created the first time the owner answers. Any change to the plan lines, their year rows or their drawn
    features after "Done" flips ``is_done`` back to false (``services/yearly_plan_status.py``) - the owner has to say it again.
    """
    __tablename__ = "yearly_plan_status"

    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), primary_key=True)
    is_done = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    done_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    done_at = Column(DateTime(timezone=True), nullable=True)
    # why the last "Done" was undone, when the system did it ('plan_changed'); null when the owner switched it off
    reopened_reason = Column(String(40), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
