"""
Field Inventory schemas - Pydantic models for API
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from decimal import Decimal


# ============================================================================
# REQUEST SCHEMAS
# ============================================================================

class FieldInventoryUploadRequest(BaseModel):
    """Request schema for field inventory upload"""
    calculation_id: Optional[UUID] = None
    regeneration_area_sqm: Optional[Decimal] = Field(default=10.0, ge=1.0, le=100.0)
    sapling_area_sqm: Optional[Decimal] = Field(default=25.0, ge=1.0, le=100.0)
    pole_area_sqm: Optional[Decimal] = Field(default=50.0, ge=10.0, le=500.0)
    tree_area_sqm: Optional[Decimal] = Field(default=500.0, ge=100.0, le=2000.0)


class FieldInventorySampleSizeUpdate(BaseModel):
    """Request schema for updating sample plot sizes"""
    regeneration_area_sqm: Decimal = Field(ge=1.0, le=100.0)
    sapling_area_sqm: Decimal = Field(ge=1.0, le=100.0)
    pole_area_sqm: Decimal = Field(ge=10.0, le=500.0)
    tree_area_sqm: Decimal = Field(ge=100.0, le=2000.0)


# ============================================================================
# RESPONSE SCHEMAS
# ============================================================================

class FieldInventoryCalculationResponse(BaseModel):
    """Response schema for field inventory calculation"""
    id: UUID
    calculation_id: Optional[UUID]
    user_id: UUID
    uploaded_filename: str

    # Sample plot sizes
    regeneration_area_sqm: Decimal
    sapling_area_sqm: Decimal
    pole_area_sqm: Decimal
    tree_area_sqm: Decimal

    # Status
    status: str
    processing_time_seconds: Optional[int]
    error_message: Optional[str]

    # Summary
    total_sample_plots: Optional[int]
    total_blocks: Optional[int]

    # Timestamps
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class FieldInventorySamplePlotResponse(BaseModel):
    """Response schema for sample plot — includes dimension metadata."""
    id: UUID
    block_name: str
    sample_plot_number: int
    longitude: float
    latitude: float
    compartment_code: Optional[str] = Field(None, description="Compartment code (null in block mode)")
    compartment_id: Optional[UUID] = Field(None, description="Compartment forest_block ID (null in block mode)")
    division_level: Optional[int] = Field(None, description="1=compartment, 2=sub_compartment (null in block mode)")
    created_at: datetime

    class Config:
        from_attributes = True


class FieldInventoryMeasurementResponse(BaseModel):
    """Response schema for measurement"""
    id: UUID
    stand_type: str
    sn: Optional[int]
    species_scientific: str
    species_local: Optional[str]
    dbh_cm: Optional[Decimal]
    height_m: Optional[Decimal]
    height_estimated: bool
    tree_class: Optional[str]
    count: int

    # Volumes (for pole and tree)
    stem_volume: Optional[Decimal]
    branch_volume: Optional[Decimal]
    tree_volume: Optional[Decimal]
    gross_volume: Optional[Decimal]
    net_volume: Optional[Decimal]
    net_volume_cft: Optional[Decimal]
    firewood_m3: Optional[Decimal]
    firewood_chatta: Optional[Decimal]

    dbh_class: Optional[str]
    basal_area_m2: Optional[Decimal] = None

    created_at: datetime

    class Config:
        from_attributes = True


class FieldInventoryBlockSummaryResponse(BaseModel):
    """Response schema for block summary"""
    id: UUID
    block_name: str
    total_sample_plots: int

    # Per-hectare counts
    regeneration_per_ha: Optional[int]
    sapling_per_ha: Optional[int]
    pole_per_ha: Optional[int]
    tree_per_ha: Optional[int]

    # Per-hectare volumes
    pole_timber_m3_per_ha: Optional[Decimal]
    pole_firewood_m3_per_ha: Optional[Decimal]
    tree_timber_m3_per_ha: Optional[Decimal]
    tree_firewood_m3_per_ha: Optional[Decimal]

    # Growing stock
    total_growing_stock_m3_per_ha: Optional[Decimal]

    # Satellite-derived volume (from AGB raster)
    satellite_volume_m3_per_ha: Optional[Decimal] = Field(None, description="Satellite-derived volume from AGB 2022 Nepal raster (m³/ha)")

    # Forest condition
    regeneration_condition: Optional[str]
    forest_condition: Optional[str]

    # MAI
    mai_percent: Optional[Decimal]
    dominant_growth_rate: Optional[str]

    # Basal area
    basal_area_m2_per_ha: Optional[Decimal] = Field(None, description="Basal area (m²/ha)")

    # DBH class breakdown (8-class system)
    dbh_class_breakdown: Optional[Dict[str, Any]] = Field(None, description="DBH class breakdown with per-hectare counts")

    # Carbon and biomass metrics (IPCC/REDD+)
    weighted_wood_density: Optional[Decimal] = Field(None, description="Volume-weighted wood density (t/m³)")
    agb_t_per_ha: Optional[Decimal] = Field(None, description="Above-ground biomass (tonnes/ha)")
    bgb_t_per_ha: Optional[Decimal] = Field(None, description="Below-ground biomass (tonnes/ha)")
    total_biomass_t_per_ha: Optional[Decimal] = Field(None, description="Total biomass (tonnes/ha)")
    carbon_stock_tc_per_ha: Optional[Decimal] = Field(None, description="Carbon stock (tonnes C/ha)")
    co2_equivalent_tco2_per_ha: Optional[Decimal] = Field(None, description="CO2 equivalent (tonnes CO2/ha)")

    created_at: datetime

    class Config:
        from_attributes = True


class FieldInventoryDetailedBlockResponse(BaseModel):
    """Detailed block response with measurements"""
    block_summary: FieldInventoryBlockSummaryResponse
    sample_plots: List[FieldInventorySamplePlotResponse]
    measurement_count: int


class FieldInventoryValidationReport(BaseModel):
    """Validation report for field inventory upload"""
    success: bool
    summary: Dict[str, Any]

    # Data detection
    data_detection: Dict[str, Any]

    # Validation results
    errors: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    info: List[Dict[str, Any]] = []

    # Boundary check (if calculation_id provided)
    boundary_check: Optional[Dict[str, Any]] = None

    # Column mapping
    column_mapping: Optional[Dict[str, Any]] = None

    # Next step
    field_inventory_id: Optional[UUID] = None
    next_step: Optional[str] = None


class FieldInventorySummaryResponse(BaseModel):
    """Summary response for entire field inventory"""
    field_inventory_id: UUID
    status: str
    total_sample_plots: int
    total_blocks: int
    blocks: List[FieldInventoryBlockSummaryResponse]

    # Overall statistics - Trees per hectare
    total_regeneration_per_ha: Optional[int] = None
    total_sapling_per_ha: Optional[int] = None
    total_pole_per_ha: Optional[int] = None
    total_tree_per_ha: Optional[int] = None

    # Overall statistics - Volumes
    total_pole_timber_m3_per_ha: Optional[Decimal] = None
    total_pole_firewood_m3_per_ha: Optional[Decimal] = None
    total_tree_timber_m3_per_ha: Optional[Decimal] = None
    total_tree_firewood_m3_per_ha: Optional[Decimal] = None
    total_growing_stock_m3_per_ha: Optional[Decimal] = None

    # Overall forest condition
    overall_forest_condition: Optional[str] = None
    overall_regeneration_condition: Optional[str] = None
    overall_growth_rate: Optional[str] = None
    average_mai_percent: Optional[Decimal] = None

    # Average basal area
    average_basal_area_m2_per_ha: Optional[Decimal] = None

    # Carbon & biomass averages
    average_wood_density: Optional[Decimal] = None
    average_agb_t_per_ha: Optional[Decimal] = None
    average_bgb_t_per_ha: Optional[Decimal] = None
    average_total_biomass_t_per_ha: Optional[Decimal] = None
    average_carbon_stock_tc_per_ha: Optional[Decimal] = None
    average_co2_equivalent_tco2_per_ha: Optional[Decimal] = None

    # Processing info
    processing_time_seconds: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]


class FieldInventoryExportResponse(BaseModel):
    """Response schema for export"""
    success: bool
    filename: str
    format: str
    size_bytes: int
    download_url: str


# ============================================================================
# VALIDATION SCHEMAS
# ============================================================================

class ColumnMappingPreviewResponse(BaseModel):
    """Response for column mapping preview"""
    success: bool
    filename: str
    total_rows: int
    csv_columns: List[str]
    sample_data: List[Dict[str, Any]]

    # Mapping results
    mapping: Dict[str, str]
    confidence: Dict[str, float]
    unmapped_columns: List[str]
    suggestions: Dict[str, List[str]]

    # Validation
    missing_required: List[str]
    duplicates: List[str]
    needs_user_input: bool

    # Required columns
    required_columns: List[str]
    optional_columns: List[str]


class StandTypeMeasurement(BaseModel):
    """Measurement data by stand type"""
    stand_type: str
    species_column: str
    dbh_column: Optional[str]
    height_column: Optional[str]
    class_column: Optional[str]
    count_column: Optional[str]
    sn_column: Optional[str]


class ValidationIssue(BaseModel):
    """Individual validation issue"""
    row_number: int
    column_name: Optional[str]
    severity: str  # 'error', 'warning', 'info'
    issue_type: str
    original_value: Optional[str]
    corrected_value: Optional[str]
    message: str
    confidence: Optional[float] = None
