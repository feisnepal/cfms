"""
Inventory models - maps to inventory tables
"""
from sqlalchemy import text, Column, String, DateTime, Integer, ForeignKey, Text, Float, Boolean, Index, BigInteger, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from datetime import datetime
import uuid

from ..core.database import Base


class TreeSpeciesCoefficient(Base):
    """
    Tree species coefficients model
    Stores allometric equations for volume calculations
    """
    __tablename__ = "tree_species_coefficients"
    __table_args__ = (
        Index('idx_species_code', 'species_code'),
        Index('idx_species_aliases', 'aliases', postgresql_using='gin'),
        Index('idx_species_genus', 'genus'),
        Index('idx_species_local_name', 'local_name'),
        Index('idx_species_scientific_name', 'scientific_name', unique=True),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    scientific_name = Column(String(255), unique=True, nullable=False)
    local_name = Column(String(100), nullable=True)

    # Volume equation coefficients
    a = Column(Float, nullable=True)
    b = Column(Float, nullable=True)
    c = Column(Float, nullable=True)
    a1 = Column(Float, nullable=True)
    b1 = Column(Float, nullable=True)

    # Additional parameters
    s = Column(Float, nullable=True)
    m = Column(Float, nullable=True)
    bg = Column(Float, nullable=True)

    # Species metadata
    aliases = Column(JSONB, nullable=True)  # Array stored as JSONB
    max_dbh_cm = Column(Float, nullable=True)
    max_height_m = Column(Float, nullable=True)
    typical_hd_ratio_min = Column(Float, nullable=True)
    typical_hd_ratio_max = Column(Float, nullable=True)

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Wood density and taxonomy (added 2026-03-03)
    wood_density_gm_cm3 = Column(Float, nullable=True)
    wood_density_source = Column(Text, nullable=True)
    genus = Column(String(100), nullable=True)

    # Full stem merchantable (added 2026-05-15)
    # If TRUE, entire stem is merchantable (no top deduction, 100% recovery).
    # Per Regulation 2079, Khair (Acacia catechu) qualifies.
    full_stem_merchantable = Column(Boolean, default=False, nullable=False)
    species_code = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<TreeSpeciesCoefficient(id={self.id}, name='{self.scientific_name}')>"


class InventoryCalculation(Base):
    """
    Inventory calculation model
    Stores main inventory processing records
    """
    __tablename__ = "inventory_calculations"
    __table_args__ = (
        Index('idx_inventory_calc_user', 'user_id'),
        Index('idx_inventory_calc_calculation', 'calculation_id'),
        Index('idx_inventory_calc_status', 'status'))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # H8.2 / S2-63: optimistic-lock counter. Bumped ONLY by
    # services/optimistic_lock.py, in the same statement that checks it -- a
    # separate read-then-write is the lost update it exists to prevent.
    version = Column(BigInteger, nullable=False, default=0, server_default=text("0"),
                     comment=("H8.2/S2-63 optimistic-lock counter. Bumped only by "
                             "services/optimistic_lock.py, in the same statement that "
                             "checks it."))

    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="SET NULL"), nullable=True, unique=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    uploaded_filename = Column(String(255), nullable=False)

    # Grid settings for mother tree selection
    grid_spacing_meters = Column(Float, default=20.0, nullable=False)
    projection_epsg = Column(Integer, default=32644, nullable=False)
    grid_origin_x = Column(Float, nullable=True)
    grid_origin_y = Column(Float, nullable=True)
    grid_num_cols = Column(Integer, nullable=True)
    grid_num_rows = Column(Integer, nullable=True)

    # Column mapping (stores user's column mapping for processing)
    column_mapping = Column(JSONB, nullable=True)
    # H8.3 / S3-16: a bad value on one row used to raise out of the insert
    # loop, and the caller responded by deleting the whole InventoryCalculation
    # -- cascading away every tree already stored. Rows that failed to parse
    # are now skipped and recorded here instead, e.g.
    # [{"row_number": 4999, "reason": "Cannot convert column 'dia_cm' to float"}]
    row_errors = Column(JSONB, nullable=True)

    # Processing status
    status = Column(String(50), default='processing', nullable=False)
    processing_time_seconds = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Summary statistics
    total_trees = Column(Integer, nullable=True)
    mother_trees_count = Column(Integer, nullable=True)
    felling_trees_count = Column(Integer, nullable=True)
    seedling_count = Column(Integer, nullable=True)
    total_volume_m3 = Column(Float, nullable=True)
    total_net_volume_m3 = Column(Float, nullable=True)
    total_net_volume_cft = Column(Float, nullable=True)
    total_firewood_m3 = Column(Float, nullable=True)
    total_firewood_chatta = Column(Float, nullable=True)
    needs_compartment_assignment = Column(Boolean, nullable=False, server_default=text('false'))

    # Relationships
    user = relationship("User", back_populates="inventory_calculations")
    calculation = relationship("Calculation", foreign_keys=[calculation_id])
    trees = relationship("InventoryTree", back_populates="inventory_calculation", cascade="all, delete-orphan")
    validation_logs = relationship("InventoryValidationLog", back_populates="inventory_calculation", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<InventoryCalculation(id={self.id}, status='{self.status}', trees={self.total_trees})>"


class InventoryTree(Base):
    """
    Individual tree record model
    Stores tree measurements and calculated volumes
    """
    __tablename__ = "inventory_trees"
    __table_args__ = (
        Index('idx_inventory_trees_compartment', 'compartment_id'),
        Index('idx_inventory_trees_forest_block', 'forest_block_id'),
        Index('idx_inventory_trees_block_id', 'block_id'),
        Index('idx_inventory_trees_calc_id', 'inventory_calculation_id'),
        Index('idx_inventory_trees_class', 'tree_class'),
        Index('idx_inventory_trees_sub_area_id', 'sub_area_id'),
        Index('idx_inventory_trees_calc', 'inventory_calculation_id'),
        Index('idx_inventory_trees_location', 'location', postgresql_using='gist'),
        Index('idx_inventory_trees_remark', 'remark'),
        Index('idx_inventory_trees_species', 'species'),
        Index('idx_inventory_trees_unit_id', 'unit_id'))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inventory_calculation_id = Column(UUID(as_uuid=True), ForeignKey("inventory_calculations.id", ondelete="CASCADE"), nullable=False)

    # Original data
    species = Column(String(255), nullable=False)
    # H6.2 / S3-16: Numeric(10,2), matching `field_inventory_measurements.dbh_cm`.
    # The same measurement under two names and, until now, two types -- and both
    # tables feed the same statutory volume and carbon totals.
    dia_cm = Column(Numeric(10, 2), nullable=False)
    height_m = Column(Numeric(10, 2), nullable=True)
    tree_class = Column(String(10), nullable=True)

    # Spatial location
    location = Column(Geography('POINT', srid=4326), nullable=False)

    # Calculated volumes
    stem_volume = Column(Numeric(15, 6), nullable=True)
    branch_volume = Column(Numeric(15, 6), nullable=True)
    tree_volume = Column(Numeric(15, 6), nullable=True)
    gross_volume = Column(Numeric(15, 6), nullable=True)
    net_volume = Column(Numeric(15, 6), nullable=True)
    net_volume_cft = Column(Numeric(15, 6), nullable=True)
    firewood_m3 = Column(Numeric(15, 6), nullable=True)
    firewood_chatta = Column(Numeric(15, 6), nullable=True)

    # Mother tree designation
    remark = Column(String(50), nullable=True)  # 'Mother Tree' or 'Felling Tree'
    grid_cell_id = Column(Integer, nullable=True)

    # Diameter classification
    stand_type = Column(String(20), nullable=True)  # 'Regeneration', 'Pole', 'Tree'
    dbh_class = Column(String(50), nullable=True)   # 'Sm. Pole (10-20)', 'Lg. Tree (50-60)', etc.

    # Metadata
    local_name = Column(String(100), nullable=True)

    # Block and Sub-area association (derived from GPS location)
    block_id = Column(UUID(as_uuid=True), ForeignKey("forest_blocks.id", ondelete="SET NULL"), nullable=True)
    block_name = Column(String(255), nullable=True)
    sub_area_id = Column(UUID(as_uuid=True), ForeignKey("forest_sub_areas.id", ondelete="SET NULL"), nullable=True)
    sub_area_name = Column(String(255), nullable=True)
    row_number = Column(Integer, nullable=True)

    # Forest Structure rule (D10, migration 095): the live unit link -- the
    # leaf forest_blocks row (block/compartment/sub-block/sub-compartment,
    # whichever stream this forest uses) whose geometry contained the tree's
    # point as of the last assignment. `block_id`/`forest_block_id`/
    # `compartment_id` above are dead legacy columns, dropped in P6 -- do not
    # write to them. `block_name` stays as the display fallback.
    unit_id = Column(UUID(as_uuid=True), ForeignKey("forest_blocks.id", ondelete="SET NULL"), nullable=True)

    # Extra columns from uploaded CSV (JSONB)
    extra_columns = Column(JSONB, nullable=True)

    # Boundary correction tracking
    was_corrected = Column(Boolean, default=False, nullable=False)
    original_x = Column(Float, nullable=True)  # Original longitude before correction
    original_y = Column(Float, nullable=True)  # Original latitude before correction

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    forest_block_id = Column(UUID(as_uuid=True), ForeignKey('forest_blocks.id', ondelete='SET NULL'), nullable=True)
    compartment_id = Column(UUID(as_uuid=True), ForeignKey('forest_blocks.id', ondelete='SET NULL'), nullable=True)

    # Relationships
    inventory_calculation = relationship("InventoryCalculation", back_populates="trees")

    def __repr__(self):
        return f"<InventoryTree(id={self.id}, species='{self.species}', dbh={self.dia_cm})>"


class InventoryValidationLog(Base):
    """
    Validation log model
    Stores validation history and reports
    """
    __tablename__ = "inventory_validation_logs"
    __table_args__ = (
        Index('idx_validation_logs_calc', 'inventory_calculation_id'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inventory_calculation_id = Column(UUID(as_uuid=True), ForeignKey("inventory_calculations.id", ondelete="CASCADE"), nullable=True)

    # Validation metadata
    validated_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    total_rows = Column(Integer, nullable=True)
    valid_rows = Column(Integer, nullable=True)
    error_rows = Column(Integer, nullable=True)
    warning_rows = Column(Integer, nullable=True)
    auto_corrections = Column(Integer, nullable=True)

    # Detection results
    detected_crs = Column(String(20), nullable=True)
    detected_diameter_type = Column(String(20), nullable=True)
    coordinate_x_column = Column(String(50), nullable=True)
    coordinate_y_column = Column(String(50), nullable=True)

    # Full validation report
    validation_report = Column(JSONB, nullable=True)

    # User actions
    user_confirmed = Column(Boolean, default=False, nullable=False)
    user_confirmation_time = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    inventory_calculation = relationship("InventoryCalculation", back_populates="validation_logs")
    issues = relationship("InventoryValidationIssue", back_populates="validation_log", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<InventoryValidationLog(id={self.id}, errors={self.error_rows}, warnings={self.warning_rows})>"


class InventoryValidationIssue(Base):
    """
    Individual validation issue model
    Stores row-level validation problems
    """
    __tablename__ = "inventory_validation_issues"
    __table_args__ = (
        Index('idx_validation_issues_log', 'validation_log_id'),
        Index('idx_validation_issues_severity', 'severity'))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    validation_log_id = Column(UUID(as_uuid=True), ForeignKey("inventory_validation_logs.id", ondelete="CASCADE"), nullable=False)

    # Issue details
    row_number = Column(Integer, nullable=False)
    column_name = Column(String(100), nullable=True)
    severity = Column(String(20), nullable=False)  # 'error', 'warning', 'info'
    issue_type = Column(String(50), nullable=True)

    # Values
    original_value = Column(Text, nullable=True)
    corrected_value = Column(Text, nullable=True)

    # Message
    message = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)

    # User action
    user_accepted = Column(Boolean, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    validation_log = relationship("InventoryValidationLog", back_populates="issues")

    def __repr__(self):
        return f"<InventoryValidationIssue(id={self.id}, row={self.row_number}, severity='{self.severity}')>"


class TreeCorrectionLog(Base):
    """
    Tree correction log model
    Stores record of boundary corrections applied to out-of-boundary trees
    """
    __tablename__ = "tree_correction_logs"
    __table_args__ = (
        Index('idx_tree_corrections_inventory', 'inventory_calculation_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    inventory_calculation_id = Column(UUID(as_uuid=True), ForeignKey("inventory_calculations.id", ondelete="CASCADE"), nullable=False)

    # Tree identification
    tree_row_number = Column(Integer, nullable=False)
    species = Column(String(255), nullable=True)

    # Original coordinates (before correction)
    original_x = Column(Float, nullable=False)
    original_y = Column(Float, nullable=False)

    # Corrected coordinates (snapped to boundary)
    corrected_x = Column(Float, nullable=False)
    corrected_y = Column(Float, nullable=False)

    # Distance moved
    distance_moved_meters = Column(Float, nullable=False)

    # Why corrected
    correction_reason = Column(String(100), nullable=False)  # 'out_of_boundary', 'gps_error'

    # When corrected
    corrected_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    inventory_calculation = relationship("InventoryCalculation")

    def __repr__(self):
        return f"<TreeCorrectionLog(id={self.id}, row={self.tree_row_number}, moved={self.distance_moved_meters:.2f}m)>"
