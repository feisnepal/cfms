"""
Calculation model - maps to existing calculations table
Stores uploaded boundaries and analysis results
"""
import logging
import sqlalchemy as sa
from sqlalchemy import text, Column, String, DateTime, Enum as SQLEnum, Integer, ForeignKey, Text, Index, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, validates
from geoalchemy2 import Geometry
from datetime import datetime
import enum
import uuid

from ..core.database import Base

logger = logging.getLogger(__name__)


class CalculationStatus(str, enum.Enum):
    """Calculation processing status"""
    PENDING = "pending"  # Waiting for block naming (multi-polygon upload)
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MapLifecycleStatus(str, enum.Enum):
    """Map lifecycle state machine — Draft → Submitted → Calculating → Completed → Locked"""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CALCULATING = "calculating"
    RETRYING = "retrying"
    FAILED = "failed"
    COMPLETED = "completed"
    LOCKED = "locked"


class Calculation(Base):
    """
    Calculation model - maps to public.calculations table
    Stores user-uploaded forest boundaries and analysis results
    """
    __tablename__ = "calculations"
    __table_args__ = (
        Index('idx_calculations_has_submitted_op', 'has_submitted_op', postgresql_where=text('(has_submitted_op = true)')),
        Index('idx_calculations_boundary_status', 'boundary_status', postgresql_where=text("((boundary_status)::text = ANY ((ARRAY['draft'::character varying, 'disputed'::character varying])::text[]))")),
        Index('idx_calculations_created_at', 'created_at'),
        Index('idx_calculations_status', 'status'),
        Index('idx_calculations_structure_locked', 'structure_locked', postgresql_where=text('(structure_locked = true)')),
        Index('idx_calculations_user_id', 'user_id'),
        Index('ix_calculations_is_draft', 'is_draft', 'user_id'),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    application_id = Column(UUID(as_uuid=True), nullable=True)  # Optional reference to application

    # File and geometry data
    uploaded_filename = Column(String(255), nullable=True)  # Nullable for drafts
    boundary_geom = Column(Geometry(srid=4326), nullable=True)  # Nullable for drafts

    # Forest-specific metadata
    forest_name = Column(String(255), nullable=True)
    block_name = Column(String(255), nullable=True)

    # Analysis results stored as JSONB
    result_data = Column(JSONB, nullable=True)

    # Draft support for work-in-progress polygon creation
    is_draft = Column(Boolean, nullable=False, default=False)
    draft_data = Column(JSONB, nullable=True)  # Stores islands and other draft data

    # User's selected analysis and map options (for re-analysis and tracking)
    analysis_options = Column(JSONB, nullable=True)  # e.g., {"run_elevation": true, "run_slope": false, ...}
    map_options = Column(JSONB, nullable=True)  # e.g., {"boundary": true, "slope": true, ...}

    # Processing metadata
    status = Column(SQLEnum(CalculationStatus), nullable=False, default=CalculationStatus.PROCESSING)
    processing_time_seconds = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)

    # Structure lock — blocks/sub-area mutations disabled when True
    structure_locked = Column(Boolean, nullable=False, default=False, server_default=sa.text("false"), comment="When True, block and sub-area geometry mutations are locked. Set automatically on OP submission. SUPER_ADMIN can override.")
    blocks_cleared_by_user = Column(Boolean, nullable=False, default=False, server_default=sa.text("false"), comment="Set when the user deliberately deletes the last block, leaving zero. Suppresses persist_boundary's single-block auto-create on subsequent boundary saves until the user explicitly regenerates a block (create-single-block).")
    structure_locked_at = Column(DateTime(timezone=True), nullable=True, comment="Timestamp of last lock/unlock transition")
    structure_locked_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, comment="User who last changed lock state")

    # Boundary overlap system status (S11)
    boundary_status = Column(String(20), nullable=False, default='draft', index=True)
    boundary_status_changed_at = Column(DateTime(timezone=True), nullable=True)
    boundary_status_changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Map lifecycle state machine (P3) — supersedes structure_locked for workflow
    map_lifecycle_status = Column(String(20), nullable=False, default='draft', index=True)
    map_lifecycle_retries = Column(Integer, nullable=False, default=0)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    submitted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    locked_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    locked_reason = Column(Text, nullable=True)
    dfo_decision_at = Column(DateTime(timezone=True), nullable=True)
    dfo_decision_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    dfo_decision_notes = Column(Text, nullable=True)

    # Calculation cost estimation (P3.2)
    cost_estimate = Column(JSONB, nullable=True, comment="Resource cost breakdown: {cpu_seconds, peak_memory_mb, cpu_cost, memory_cost, total_cost, currency}")

    # Map & Workspace Unification (U*) — unified shell / feature flags / optimistic lock
    unified_shell_enabled = Column(Boolean, nullable=False, default=False, server_default=sa.text("false"), comment="U08: enables the unified shell for this calc (overridable by user.opt_out / tenant default)")
    geometry_version = Column(sa.BigInteger, nullable=False, default=0, server_default=sa.text("0"), comment="U02/A.5: optimistic-lock clock for geometry writes (dedicated column, compare-and-set, atomic)")
    export_status = Column(sa.String(20), nullable=False, default='idle', server_default=sa.text("'idle'"), comment="U12: idle|queued|running|complete|failed — ONLY 'running' blocks geometry writes")
    export_started_at = Column(DateTime(timezone=True), nullable=True, comment="U12: lease begin")
    export_heartbeat_at = Column(DateTime(timezone=True), nullable=True, comment="U12: lease heartbeat — stale when now - heartbeat > lease_ttl")
    draft_recycle_state = Column(sa.String(20), nullable=True, comment="U11: NULL|staged_delete|recycled — soft-archive before hard purge")
    recycled_at = Column(DateTime(timezone=True), nullable=True, comment="U11: time soft-archived; hard-delete 24h after this")

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    column_mapping = Column(JSONB, nullable=True, comment='Stores the actual column mapping used for this calculation (JSON format)')
    has_submitted_op = Column(Boolean, nullable=False, server_default=text('false'))

    # Relationships
    user = relationship("User", back_populates="calculations", foreign_keys=[user_id])
    fieldbook_points = relationship("Fieldbook", back_populates="calculation", cascade="all, delete-orphan")
    sampling_designs = relationship("SamplingDesign", back_populates="calculation", cascade="all, delete-orphan")
    biodiversity_records = relationship("CalculationBiodiversity", back_populates="calculation", cascade="all, delete-orphan")
    synthetic_tree_models = relationship("SyntheticTreeModel", back_populates="calculation", cascade="all, delete-orphan")
    all_tree_exports = relationship("AllTreeExport", back_populates="calculation", cascade="all, delete-orphan")
    household_data = relationship("HouseholdInformation", back_populates="calculation", cascade="all, delete-orphan")
    forest_committee_members = relationship("ForestUserCommittee", back_populates="calculation", cascade="all, delete-orphan")
    advisory_committee_members = relationship("AdvisoryCommittee", back_populates="calculation", cascade="all, delete-orphan")
    financial_committee_members = relationship("FinancialCommittee", back_populates="calculation", cascade="all, delete-orphan")
    proposed_activities = relationship("ProposedYearlyActivity", back_populates="calculation", cascade="all, delete-orphan")
    operational_plan = relationship("OperationalPlan", back_populates="calculation", uselist=False, cascade="all, delete-orphan")

    @validates("result_data")
    def _clean_sub_area_geometries(self, key, value):
        """Sub-areas live only in this JSONB blob — unlike blocks/
        compartments/sub-compartments (all `ForestBlock`, one shared
        `@validates('geometry')` guard) there is no dedicated, validated
        table for them to route through, so a degenerate-noise fragment from
        a geometry operation (clip, union, buffer — a re-clip after a
        boundary edit, a sub-area merge, ...) had no single choke point to
        get caught at (user report, 2026-09-13: "ensure it applies to ...
        sub-areas ... in all layers"). This is that choke point: every write
        to `result_data` passes through here, so every one of the ~15 call
        sites that create/edit a sub-area's geometry is covered without
        needing to be individually patched.

        Purely defensive — this must NEVER raise or block an unrelated
        `result_data` write for a reason that has nothing to do with
        sub-areas: unlike the ForestBlock guard (where geometry is the sole
        purpose of the write), `result_data` carries many unrelated features'
        state, so a genuinely multi-part sub-area (an existing structural
        situation, not noise) is logged and left untouched here, never
        raised on.
        """
        if not isinstance(value, dict):
            return value
        subs = value.get("sub_areas")
        if not isinstance(subs, list) or not subs:
            return value

        from shapely.geometry import mapping, shape
        from ..utils.single_part_geometry import MultiPartFeatureError, ensure_single_polygon

        changed = False
        cleaned: list = []
        for sub_area in subs:
            geom_dict = sub_area.get("geometry") if isinstance(sub_area, dict) else None
            if geom_dict is None:
                cleaned.append(sub_area)
                continue
            try:
                geom = shape(geom_dict)
                fixed = ensure_single_polygon(geom)
            except MultiPartFeatureError:
                # A genuinely multi-part sub-area is a pre-existing
                # structural situation, not numerical noise -- not this
                # guard's job to restructure into multiple entries.
                cleaned.append(sub_area)
                continue
            except Exception:  # noqa: BLE001 -- best-effort; never block an unrelated result_data write
                logger.warning(
                    "sub-area geometry cleanup failed for sub_area id=%s - "
                    "left unchanged", sub_area.get("id") if isinstance(sub_area, dict) else None,
                    exc_info=True,
                )
                cleaned.append(sub_area)
                continue
            if fixed is geom:
                cleaned.append(sub_area)
                continue
            changed = True
            new_sa = dict(sub_area)
            new_sa["geometry"] = mapping(fixed)
            cleaned.append(new_sa)

        if not changed:
            return value
        new_value = dict(value)
        new_value["sub_areas"] = cleaned
        return new_value

    def __repr__(self):
        return f"<Calculation(id={self.id}, user_id={self.user_id}, status={self.status.value})>"


# GiST spatial index on the boundary geometry (module-level, string-based
# reference so it is registered once and create_all does not double-emit it).
Index(
    "idx_calculations_boundary_geom",
    "boundary_geom",
    postgresql_using="gist",
)

