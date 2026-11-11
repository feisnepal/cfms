"""NTFP method profile: how to inventory one species (see ``app.core.ntfp_methods`` for the source and the seed)."""
from geoalchemy2 import Geometry
from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, UUID, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from ..core.database import Base


class NtfpMethodProfile(Base):
    __tablename__ = "ntfp_method_profile"
    __table_args__ = (
        CheckConstraint("sampling_method IN ('destructive','semi_destructive','non_destructive')", name="ck_ntfp_method_sampling"),
        CheckConstraint("growth_class IN ('tree','shrub','climber','herb','fungus','lichen')", name="ck_ntfp_method_growth"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    # the normalised Latin name as ntfp_schedule7 reads it (genus only for a "spp." entry), or "np:<nepali name>"
    species_key = Column(String(120), nullable=False, unique=True)
    scientific_name = Column(String(255), nullable=True)
    card_status = Column(String(20), nullable=True)  # documented | provisional | expert_confirmed (null: no card)
    aliases = Column(JSONB, nullable=False, server_default="[]")  # other Latin names read as this species (the guideline's spelling)
    # the Latin name Schedule-7 prints for it (a synonym at times), to give ntfp_schedule7.designated_entries; null when it is not listed
    regulation_name = Column(String(255), nullable=True)
    nepali_name = Column(String(255), nullable=False)
    priority_serial = Column(Integer, nullable=True)  # Annex 1: the 30 priority NTFPs
    altitude_min_m = Column(Integer, nullable=True)
    altitude_max_m = Column(Integer, nullable=True)
    parts_used_ne = Column(String(255), nullable=True)
    uses_ne = Column(String(255), nullable=True)
    has_method_card = Column(Boolean, nullable=False, server_default="false")  # Annex 2
    life_form_ne = Column(String(120), nullable=True)
    growth_class = Column(String(12), nullable=True)
    part_ne = Column(String(255), nullable=True)
    part_groups = Column(JSONB, nullable=False, server_default="[]")  # Schedule-7 group codes of the part harvested
    sampling_method = Column(String(20), nullable=True)
    plot_min_sqm = Column(Numeric(8, 2), nullable=True)
    plot_max_sqm = Column(Numeric(8, 2), nullable=True)
    maturity_ne = Column(String(255), nullable=True)
    n_individuals_min = Column(Integer, nullable=True)
    n_individuals_max = Column(Integer, nullable=True)
    harvest_fraction_pct = Column(Numeric(5, 2), nullable=True)
    conversion_factor = Column(Numeric(6, 4), nullable=True)  # dry weight / fresh weight
    procedure_en = Column(Text, nullable=True)
    source = Column(String(120), nullable=False, server_default="NTFP Resource Survey Guideline 2069")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class NtfpSamplingDesign(Base):
    """The NTFP sample-plot design of one forest (one per forest; creating a new one replaces it). See ``app.services.ntfp_design``."""
    __tablename__ = "ntfp_sampling_designs"
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False, unique=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    plot_shape = Column(String(12), nullable=False, server_default="square")
    seed = Column(Integer, nullable=False)  # the random start: the same seed and inputs give the same plots
    min_plots = Column(Integer, nullable=False)
    species = Column(JSONB, nullable=False, server_default="[]")  # the specs used, with plots and intensity achieved per species
    layout = Column(JSONB, nullable=False, server_default="{}")   # the composite plot: frame and sub-plots
    strata = Column(JSONB, nullable=False, server_default="[]")   # per stratum: area, plots wanted / laid, spacing, warnings
    transects = Column(JSONB, nullable=False, server_default="{}")  # GeoJSON FeatureCollection (WGS84)
    warnings = Column(JSONB, nullable=False, server_default="[]")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    plots = relationship("NtfpSamplePlot", back_populates="design", cascade="all, delete-orphan", passive_deletes=True)


class NtfpSamplePlot(Base):
    __tablename__ = "ntfp_sample_plots"
    __table_args__ = (UniqueConstraint("design_id", "plot_number", name="uq_ntfp_plot_number"),)
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    design_id = Column(UUID(as_uuid=True), ForeignKey("ntfp_sampling_designs.id", ondelete="CASCADE"), nullable=False, index=True)
    plot_number = Column(Integer, nullable=False)
    stratum = Column(String(255), nullable=False)
    transect = Column(Integer, nullable=False)
    location = Column(Geometry("POINT", srid=4326), nullable=False)
    species_keys = Column(JSONB, nullable=False, server_default="[]")  # the species measured in this plot
    # the last "I am here" check: where the person stood, the phone's accuracy, the distance to the plot, and the verdict (at / far / uncertain)
    here_latitude = Column(Float, nullable=True)
    here_longitude = Column(Float, nullable=True)
    here_accuracy_m = Column(Float, nullable=True)
    here_distance_m = Column(Float, nullable=True)
    here_verdict = Column(String(10), nullable=True)
    here_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    design = relationship("NtfpSamplingDesign", back_populates="plots")
    observations = relationship("NtfpObservation", back_populates="plot", cascade="all, delete-orphan", passive_deletes=True)


class NtfpPlotPhoto(Base):
    """A photo taken at a sample plot; the file is under uploads/ntfp_photos/<forest id>/<stored_name>."""
    __tablename__ = "ntfp_plot_photos"
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    plot_id = Column(UUID(as_uuid=True), ForeignKey("ntfp_sample_plots.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    stored_name = Column(String(80), nullable=False)
    content_type = Column(String(40), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    caption = Column(String(300), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NtfpSource(Base):
    """A document a method-card value comes from (read) or a lead not yet read (read_status 'lead'). ``tier`` orders authority: lower is preferred."""
    __tablename__ = "ntfp_source"
    key = Column(String(40), primary_key=True)
    title = Column(Text, nullable=False)
    publisher = Column(String(255), nullable=True)
    year = Column(String(40), nullable=True)
    url = Column(String(500), nullable=True)
    tier = Column(Integer, nullable=False, server_default="5")
    read_status = Column(String(10), nullable=False, server_default="read")
    licence = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)


class NtfpMethodValue(Base):
    """One sourced fact about a species (or a growth form ``form:<class>`` or a part ``part:<group>``): the value, its source, the table or page, a status."""
    __tablename__ = "ntfp_method_value"
    __table_args__ = (
        CheckConstraint("status IN ('documented','derived','provisional','expert_confirmed')", name="ck_ntfp_value_status"),
        CheckConstraint("calendar IS NULL OR calendar IN ('AD','BS')", name="ck_ntfp_value_calendar"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    species_key = Column(String(120), nullable=False, index=True)
    field = Column(String(30), nullable=False)
    part_group = Column(String(2), nullable=True)
    value_num = Column(Numeric(14, 4), nullable=True)
    value_num2 = Column(Numeric(14, 4), nullable=True)
    value_text = Column(Text, nullable=True)
    unit = Column(String(12), nullable=True)
    calendar = Column(String(2), nullable=True)  # AD or BS, for a season's month numbers
    source_key = Column(String(40), ForeignKey("ntfp_source.key"), nullable=False)
    locator = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False)
    chosen = Column(Boolean, nullable=False, server_default="false")
    note = Column(Text, nullable=True)
    reviewed_by = Column(String(120), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NtfpHarvestPlan(Base):
    """The owner's annual harvest of one species' part (the guideline gives no rule, so it is typed). Read by the cost-benefit sync and the yearly plan."""
    __tablename__ = "ntfp_harvest_plan"
    __table_args__ = (
        UniqueConstraint("calculation_id", "species_key", "part_group", name="uq_ntfp_harvest_plan"),
        CheckConstraint("annual_quantity >= 0", name="ck_ntfp_harvest_quantity"),
        CheckConstraint("unit IN ('kg','piece')", name="ck_ntfp_harvest_unit"),
        CheckConstraint("weight_basis IN ('fresh','dry')", name="ck_ntfp_harvest_basis"),
        CheckConstraint("price_override IS NULL OR price_override >= 0", name="ck_ntfp_harvest_price"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False, index=True)
    species_key = Column(String(120), nullable=False)
    part_group = Column(String(2), nullable=False)
    annual_quantity = Column(Numeric(14, 2), nullable=False)
    unit = Column(String(10), nullable=False, server_default="kg")
    weight_basis = Column(String(5), nullable=False, server_default="dry")  # which weight the quantity is: fresh or dry (Schedule-7's rate is the same either way)
    price_override = Column(Numeric(12, 2), nullable=True)  # the owner's own price per unit; else Schedule-7 or its labelled estimate
    notes = Column(Text, nullable=True)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class NtfpObservation(Base):
    """What was found of one species in one sample plot. A row exists only where the survey has been done: ``count_total`` 0 means "looked, not
    there" (frequency needs those zeros), no row means "not surveyed yet"."""
    __tablename__ = "ntfp_plot_observations"
    __table_args__ = (
        UniqueConstraint("plot_id", "species_key", name="uq_ntfp_observation"),
        CheckConstraint("count_total >= 0 AND (count_mature IS NULL OR count_mature >= 0) AND (count_small IS NULL OR count_small >= 0) "
                        "AND (clumps IS NULL OR clumps >= 0) AND (tillers IS NULL OR tillers >= 0)", name="ck_ntfp_observation_counts"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    plot_id = Column(UUID(as_uuid=True), ForeignKey("ntfp_sample_plots.id", ondelete="CASCADE"), nullable=False, index=True)
    species_key = Column(String(120), nullable=False)
    visit_date = Column(Date, nullable=True)
    count_total = Column(Integer, nullable=False)
    count_mature = Column(Integer, nullable=True)
    count_small = Column(Integer, nullable=True)
    clumps = Column(Integer, nullable=True)
    tillers = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    source = Column(String(10), nullable=False, server_default="upload")  # upload | manual: a forest's records are all one or all the other
    entered_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    plot = relationship("NtfpSamplePlot", back_populates="observations")
    weights = relationship("NtfpWeightSample", back_populates="observation", cascade="all, delete-orphan", passive_deletes=True)


class NtfpWeightSample(Base):
    """One sampled individual (or part) of an observation, weighed fresh and, once dry, dry. Grams."""
    __tablename__ = "ntfp_weight_samples"
    __table_args__ = (
        UniqueConstraint("observation_id", "sample_no", name="uq_ntfp_weight_sample"),
        CheckConstraint("fresh_weight_g > 0 AND (dry_weight_g IS NULL OR (dry_weight_g >= 0 AND dry_weight_g <= fresh_weight_g))", name="ck_ntfp_weight"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    observation_id = Column(UUID(as_uuid=True), ForeignKey("ntfp_plot_observations.id", ondelete="CASCADE"), nullable=False, index=True)
    sample_no = Column(Integer, nullable=False)
    part_group = Column(String(2), nullable=True)  # Schedule-7 group code of the part weighed
    fresh_weight_g = Column(Numeric(12, 2), nullable=False)
    dry_weight_g = Column(Numeric(12, 2), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    observation = relationship("NtfpObservation", back_populates="weights")
