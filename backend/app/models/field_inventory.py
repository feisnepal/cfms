"""
Field Inventory models - For fieldbook measurements with 4 stand types
"""
from sqlalchemy import (Column, String, DateTime, Integer, ForeignKey, Text, Numeric,
                        Boolean, Index, UniqueConstraint, event, func, select)
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from datetime import datetime
import uuid

from ..core.database import Base


class FieldInventoryCalculation(Base):
    """
    Field inventory calculation model
    Stores main field inventory processing records
    """
    __tablename__ = "field_inventory_calculations"
    __table_args__ = (
        Index('idx_field_inventory_calc_user', 'user_id'),
        Index('idx_field_inventory_calc_calculation', 'calculation_id'),
        Index('idx_field_inventory_calc_status', 'status'))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="SET NULL"), nullable=True, unique=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # File metadata
    uploaded_filename = Column(String(255), nullable=False)
    column_mapping = Column(JSONB, nullable=True)

    # Configurable sample plot sizes (in square meters)
    regeneration_area_sqm = Column(Numeric(10, 2), default=10.0, nullable=False)
    sapling_area_sqm = Column(Numeric(10, 2), default=25.0, nullable=False)
    pole_area_sqm = Column(Numeric(10, 2), default=100.0, nullable=False)
    tree_area_sqm = Column(Numeric(10, 2), default=500.0, nullable=False)

    # Processing status
    status = Column(String(50), default='processing', nullable=False)
    processing_time_seconds = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Summary statistics
    total_sample_plots = Column(Integer, nullable=True)
    total_blocks = Column(Integer, nullable=True)

    # Relationships
    user = relationship("User", back_populates="field_inventory_calculations")
    calculation = relationship("Calculation", foreign_keys=[calculation_id])
    sample_plots = relationship("FieldInventorySamplePlot", back_populates="field_inventory_calculation", cascade="all, delete-orphan")
    block_summaries = relationship("FieldInventoryBlockSummary", back_populates="field_inventory_calculation", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<FieldInventoryCalculation(id={self.id}, status='{self.status}', plots={self.total_sample_plots})>"


class FieldInventorySamplePlot(Base):
    """
    Sample plot model
    Stores sample plot locations for field inventory
    """
    __tablename__ = "field_inventory_sample_plots"
    __table_args__ = (
        Index('idx_field_inventory_plots_calc', 'field_inventory_calculation_id'),
        Index('idx_field_inventory_plots_block', 'block_name'),
        Index('idx_field_inventory_plots_location', 'location', postgresql_using='gist'),
        Index('idx_field_inventory_plots_unit_id', 'unit_id'))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_inventory_calculation_id = Column(UUID(as_uuid=True), ForeignKey("field_inventory_calculations.id", ondelete="CASCADE"), nullable=False)

    # Plot identification
    block_name = Column(String(255), nullable=False)
    sample_plot_number = Column(Integer, nullable=False)
    location = Column(Geography('POINT', srid=4326), nullable=False)

    # Sampling stratum: 'productive' (operable forest, regular intensity) or
    # 'protected' (protection sub-area, growing-stock-only ~0.1% sample).
    # Assigned by point-in-polygon during field-inventory processing.
    # NULL = not stratified (no protected sub-areas, or pre-migration-072 plot);
    # consumers must treat NULL as 'productive'. See migration 072.
    zone_type = Column(String(20), nullable=True)

    # Forest Structure rule (D10, migration 095): the live unit link -- the
    # leaf forest_blocks row (whichever stream this forest uses) whose
    # geometry contained the plot's point as of the last assignment. The
    # live DB additionally carries unmapped `compartment_id`/`compartment_code`
    # columns from an older, dead scheme -- do not write to them; `block_name`
    # stays as the display fallback.
    unit_id = Column(UUID(as_uuid=True), ForeignKey("forest_blocks.id", ondelete="SET NULL"), nullable=True)

    # Resource yield per 100 sqm per year (from uploaded CSV/Excel)
    firewood_kg_per_100sqm_per_year = Column(Numeric(10, 2), nullable=True)
    grass_kg_per_100sqm_per_year = Column(Numeric(10, 2), nullable=True)
    bedding_material_kg_per_100sqm_per_year = Column(Numeric(10, 2), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    field_inventory_calculation = relationship("FieldInventoryCalculation", back_populates="sample_plots")
    measurements = relationship("FieldInventoryMeasurement", back_populates="sample_plot", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<FieldInventorySamplePlot(id={self.id}, block='{self.block_name}', plot={self.sample_plot_number})>"


class FieldInventoryMeasurement(Base):
    """
    Individual measurement model
    Stores tree measurements by stand type (Regeneration, Sapling, Pole, Tree)
    """
    __tablename__ = "field_inventory_measurements"
    __table_args__ = (
        # H8.6 / S2-67. Every tree measurement was anonymous within its plot:
        # 25,948 rows, `sn` NULL in all of them, UUID primary key only. A UUID
        # generated per insert makes every replayed row a NEW row by
        # definition, so sync duplication could be neither prevented nor
        # detected -- two identical-looking rows are equally consistent with
        # two real trees and with one tree counted twice.
        #
        # The key includes `stand_type` because the upload layout carries four
        # independent serials (`regen_sn`, `sapling_sn`, `pole_sn`, `tree_sn`),
        # each numbered from 1. Tree #1 and Pole #1 in one plot is ordinary
        # data -- 1,092 of 1,105 plots hold more than one stand type -- so the
        # (sample_plot_id, sn) form the report specifies would reject it.
        UniqueConstraint('sample_plot_id', 'stand_type', 'sn',
                         name='uq_measurement_plot_stand_sn'),
        Index('idx_field_inventory_meas_plot', 'sample_plot_id'),
        Index('idx_field_inventory_meas_stand_type', 'stand_type'),
        Index('idx_field_inventory_meas_species', 'species_scientific'))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sample_plot_id = Column(UUID(as_uuid=True), ForeignKey("field_inventory_sample_plots.id", ondelete="CASCADE"), nullable=False)

    # Measurement data
    stand_type = Column(String(20), nullable=False)  # 'Regeneration', 'Sapling', 'Pole', 'Tree'
    # NOT NULL is what makes the constraint above real: PostgreSQL treats NULLs
    # as distinct, so a nullable `sn` would give a UNIQUE constraint that every
    # one of the 25,948 legacy rows satisfies and that enforces nothing.
    # Assigned by `_assign_measurement_serials` below when a caller omits it.
    sn = Column(Integer, nullable=False)
    species_scientific = Column(String(255), nullable=False)
    species_local = Column(String(255), nullable=True)
    dbh_cm = Column(Numeric(10, 2), nullable=True)
    height_m = Column(Numeric(10, 2), nullable=True)
    height_estimated = Column(Boolean, default=False, nullable=False)
    tree_class = Column(String(10), nullable=True)
    count = Column(Integer, default=1, nullable=False)

    # Calculated volumes (only for Pole and Tree)
    stem_volume = Column(Numeric(15, 6), nullable=True)
    branch_volume = Column(Numeric(15, 6), nullable=True)
    tree_volume = Column(Numeric(15, 6), nullable=True)
    gross_volume = Column(Numeric(15, 6), nullable=True)
    net_volume = Column(Numeric(15, 6), nullable=True)
    net_volume_cft = Column(Numeric(15, 6), nullable=True)
    firewood_m3 = Column(Numeric(15, 6), nullable=True)
    firewood_chatta = Column(Numeric(15, 6), nullable=True)

    # DBH classification
    dbh_class = Column(String(50), nullable=True)

    # Basal area (computed from DBH)
    basal_area_m2 = Column(Numeric(15, 6), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    sample_plot = relationship("FieldInventorySamplePlot", back_populates="measurements")

    def __repr__(self):
        return f"<FieldInventoryMeasurement(id={self.id}, stand_type='{self.stand_type}', species='{self.species_scientific}')>"


class FieldInventoryBlockSummary(Base):
    """
    Block summary model
    Stores per-hectare extrapolation and forest condition assessment
    """
    __tablename__ = "field_inventory_block_summary"
    __table_args__ = (
        Index('idx_field_inventory_summary_calc', 'field_inventory_calculation_id'),
        Index('idx_field_inventory_summary_block', 'block_name'))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_inventory_calculation_id = Column(UUID(as_uuid=True), ForeignKey("field_inventory_calculations.id", ondelete="CASCADE"), nullable=False)
    block_name = Column(String(255), nullable=False)

    # Sample plot statistics
    total_sample_plots = Column(Integer, nullable=False)

    # Per-hectare counts (extrapolated)
    regeneration_per_ha = Column(Integer, nullable=True)
    sapling_per_ha = Column(Integer, nullable=True)
    pole_per_ha = Column(Integer, nullable=True)
    tree_per_ha = Column(Integer, nullable=True)

    # Per-hectare volumes (extrapolated) - timber only
    pole_timber_m3_per_ha = Column(Numeric(15, 6), nullable=True)
    pole_firewood_m3_per_ha = Column(Numeric(15, 6), nullable=True)
    tree_timber_m3_per_ha = Column(Numeric(15, 6), nullable=True)
    tree_firewood_m3_per_ha = Column(Numeric(15, 6), nullable=True)

    # Total growing stock (timber only) — PRODUCTIVE stratum only; this is what
    # forest condition, MAI and the Annual Allowable Harvest are computed from.
    total_growing_stock_m3_per_ha = Column(Numeric(15, 6), nullable=True)

    # Protection stratum (protected sub-area plots, sampled growing-stock-only).
    # Reported separately, never added to AAH. NULL when the block has no
    # protection-stratum plots. See migration 073.
    protected_growing_stock_m3_per_ha = Column(Numeric(15, 6), nullable=True)
    protected_sample_plots = Column(Integer, nullable=True)

    # Satellite-derived volume (from AGB raster - added 2026-03-23)
    satellite_volume_m3_per_ha = Column(Numeric(15, 6), nullable=True)  # Volume from AGB 2022 Nepal raster

    # Basal area (computed from pole/tree DBH)
    basal_area_m2_per_ha = Column(Numeric(15, 6), nullable=True)

    # DBH class breakdown (8-class system)
    dbh_class_breakdown = Column(JSONB, nullable=True)

    # Forest condition assessment
    regeneration_condition = Column(String(20), nullable=True)  # 'Good', 'Moderate', 'Weak'
    forest_condition = Column(String(20), nullable=True)  # 'Good', 'Moderate', 'Weak'

    # Mean Annual Increment (%)
    mai_percent = Column(Numeric(5, 2), nullable=True)
    dominant_growth_rate = Column(String(20), nullable=True)  # 'Fast', 'Moderate', 'Slow'

    # Per-hectare resource yields (from kg/100sqm → kg/ha, for demand-supply)
    firewood_kg_per_ha_per_year = Column(Numeric(15, 6), nullable=True)
    grass_kg_per_ha_per_year = Column(Numeric(15, 6), nullable=True)
    bedding_material_kg_per_ha_per_year = Column(Numeric(15, 6), nullable=True)

    # Carbon and biomass metrics (IPCC/REDD+ - added 2026-03-03)
    agb_t_per_ha = Column(Numeric(15, 6), nullable=True)  # Above-ground biomass (tonnes/ha)
    bgb_t_per_ha = Column(Numeric(15, 6), nullable=True)  # Below-ground biomass (tonnes/ha)
    total_biomass_t_per_ha = Column(Numeric(15, 6), nullable=True)  # Total biomass (tonnes/ha)
    carbon_stock_tc_per_ha = Column(Numeric(15, 6), nullable=True)  # Carbon stock (tonnes C/ha)
    co2_equivalent_tco2_per_ha = Column(Numeric(15, 6), nullable=True)  # CO2 equivalent (tonnes CO2/ha)
    weighted_wood_density = Column(Numeric(5, 3), nullable=True)  # Volume-weighted wood density (t/m³)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    field_inventory_calculation = relationship("FieldInventoryCalculation", back_populates="block_summaries")

    def __repr__(self):
        return f"<FieldInventoryBlockSummary(id={self.id}, block='{self.block_name}', condition='{self.forest_condition}')>"


# ---------------------------------------------------------------------------
# H8.6 / S2-67 — `sn` is assigned here, not at each insert site.
# ---------------------------------------------------------------------------
# The column existed and was correct from the beginning. It was populated in
# **0 of 25,948 rows**, because filling it depended on the uploader mapping an
# SN column and no upload ever has -- 0 of 20 stored `column_mapping`s carry a
# `*_sn` key. A field the writer must remember is a field that ends up empty,
# which is the same failure `IdempotentRoute` (H2.17) and
# `RequestBodyLimitMiddleware` (H2.15) were built to remove.
#
# A session-level hook covers both ingest paths in `field_inventory_service.py`
# and any third one added later, so `sn` cannot silently return to NULL. And
# because the column is NOT NULL in the database, a path this hook somehow
# missed fails loudly at flush rather than quietly writing an anonymous tree.
def _assign_measurement_serials(session: Session, flush_context, instances) -> None:
    """Give every new measurement the next free serial in its plot and stand type.

    A serial supplied by the caller -- a physical tree tag from the field -- is
    kept. Only rows with none get one, so traceability is never overwritten by
    a positional number.
    """
    pending = [
        obj for obj in session.new
        if isinstance(obj, FieldInventoryMeasurement) and obj.sn is None
    ]
    if not pending:
        return

    # Group by the two columns the constraint is on. The counter has to be
    # per-group: numbering across a whole upload would collide on the very
    # first plot that has both a Pole and a Tree, which is 1,092 of 1,105.
    groups: dict[tuple, list] = {}
    for obj in pending:
        plot_id = obj.sample_plot_id
        if plot_id is None and obj.sample_plot is not None:
            # Assigned by relationship rather than by id; the FK is not
            # populated until the flush itself.
            plot_id = obj.sample_plot.id
        if plot_id is None:
            # Nothing to scope a serial to. Leaving it None lets NOT NULL
            # raise, which names the row -- better than inventing a number
            # that belongs to no plot.
            continue
        groups.setdefault((plot_id, obj.stand_type), []).append(obj)

    for (plot_id, stand_type), objects in groups.items():
        # Start above whatever is already stored, so an incremental upload
        # continues the sequence instead of restarting it at 1 and colliding.
        highest = session.execute(
            select(func.max(FieldInventoryMeasurement.sn)).where(
                FieldInventoryMeasurement.sample_plot_id == plot_id,
                FieldInventoryMeasurement.stand_type == stand_type,
            )
        ).scalar()
        # Serials the caller supplied in this same batch are already spoken
        # for, and are not visible to the query above.
        supplied = {
            obj.sn for obj in session.new
            if isinstance(obj, FieldInventoryMeasurement)
            and obj.sn is not None
            and obj.stand_type == stand_type
            and (obj.sample_plot_id == plot_id
                 or (obj.sample_plot is not None and obj.sample_plot.id == plot_id))
        }
        nxt = (highest or 0) + 1
        for obj in objects:
            while nxt in supplied:
                nxt += 1
            obj.sn = nxt
            nxt += 1


event.listen(Session, "before_flush", _assign_measurement_serials)
