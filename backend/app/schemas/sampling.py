"""
Pydantic schemas for Sampling Design API

Supports two sampling methods:
1. Guideline-2061: Nepal DoF standard (sample counts from lookup tables)
2. Manual: Custom sampling with full control (existing method)
"""
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, Literal, Dict, Any
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from enum import Enum


class SamplingMethod(str, Enum):
    """Sampling methodology selection"""
    GUIDELINE_2061 = "guideline_2061"
    MANUAL = "manual"


class GuidelineIntensity(str, Enum):
    """Forest Inventory Guideline-2061 sampling intensities"""
    HALF_PERCENT = "0.5"      # Standard production forest
    ONE_PERCENT = "1.0"        # Detailed inventory
    TWO_PERCENT = "2.0"        # SFM कार्यविधि §16 Production stratum
    POINT_ONE_PERCENT = "0.1"  # Protected zones only


class BlockOverride(BaseModel):
    """Per-block sampling parameter overrides.

    DEPRECATED (2026-08-14): the per-block design/override feature was removed
    from the sampling page. This schema and ``block_overrides`` remain only for
    backward compatibility with previously created designs — the UI no longer
    sends them and new designs should omit them.
    """
    sampling_type: Optional[Literal["systematic", "random", "stratified"]] = Field(
        None,
        description="Override sampling type for this block"
    )
    sampling_intensity_percent: Optional[Decimal] = Field(
        None,
        ge=0,
        le=10.0,
        description="Override sampling intensity for this block. 0 = do not sample this unit (user exclusion)"
    )
    min_samples_per_block: Optional[int] = Field(
        None,
        ge=2,
        le=20,
        description="Override minimum samples for this block"
    )
    sample_count: Optional[int] = Field(
        None,
        ge=0,
        description="An explicit number of plots for this polygon (replaces the intensity arithmetic; 0 = do not sample)"
    )
    boundary_buffer_meters: Optional[float] = Field(
        None,
        ge=0.0,
        le=200.0,
        description="Override boundary buffer for this block"
    )
    min_distance_meters: Optional[int] = Field(
        None,
        ge=5,
        le=500,
        description="Override minimum distance between points for this block"
    )

    model_config = ConfigDict(extra='forbid')


class SamplingDesignBase(BaseModel):
    """Base schema for sampling design"""
    sampling_type: Literal["systematic", "random", "stratified"] = Field(
        ...,
        description="Sampling methodology"
    )
    sampling_intensity_percent: Optional[Decimal] = Field(
        default=Decimal("0.5"),
        ge=0.1,
        le=10.0,
        description="Sampling intensity as percentage of block area (default 0.5%)"
    )
    intensity_per_hectare: Optional[Decimal] = Field(
        None,
        ge=0.01,
        le=10.0,
        description="[DEPRECATED] Sampling intensity (points per hectare) - use sampling_intensity_percent instead"
    )
    grid_spacing_meters: Optional[int] = Field(
        None,
        ge=10,
        le=1000,
        description="[DEPRECATED] Grid spacing for systematic sampling - calculated from intensity"
    )
    min_samples_per_block: Optional[int] = Field(
        default=5,
        ge=2,
        le=10,
        description="Minimum samples per block (for blocks >= 1 ha). Default: 5"
    )
    min_samples_small_blocks: Optional[int] = Field(
        default=2,
        ge=1,
        le=5,
        description="Minimum samples for blocks < 1 hectare. Default: 2"
    )
    enforce_min_samples_production: Optional[bool] = Field(
        default=True,
        description=(
            "Enforce कार्यविधि §16's minimum 5 plots per sampling unit, for "
            "units classified as Production stratum. When True (default), "
            "the guideline floor is layered on top of "
            "min_samples_per_block/min_samples_small_blocks. When False, "
            "those two fields alone govern the minimum for Production units "
            "-- no guideline floor is applied to them."
        )
    )
    enforce_min_samples_conservation: Optional[bool] = Field(
        default=True,
        description=(
            "Same as enforce_min_samples_production, but for units "
            "classified as Conservation stratum."
        )
    )
    enforce_min_samples_protection: Optional[bool] = Field(
        default=True,
        description=(
            "Same as enforce_min_samples_production, but for units "
            "classified as Protection stratum (this also governs the "
            "0.1% protected-zone sub-sample inside any block, regardless "
            "of that block's own stratum)."
        )
    )
    min_distance_meters: Optional[int] = Field(
        None,
        ge=5,
        le=500,
        description="Minimum distance between points"
    )
    num_strata: Optional[int] = Field(
        None,
        ge=4,
        le=100,
        description="Number of strata for stratified sampling"
    )
    plot_shape: Optional[Literal["circular", "square", "rectangular"]] = Field(
        default="circular",
        description="Sample plot shape (default: circular)"
    )
    plot_radius_meters: Optional[Decimal] = Field(
        default=Decimal("12.6156"),
        ge=1.0,
        le=50.0,
        description="Plot radius for circular plots (default: 12.62m for 500m² plot)"
    )
    plot_length_meters: Optional[Decimal] = Field(
        None,
        ge=1.0,
        le=100.0,
        description="Plot length for rectangular plots"
    )
    plot_width_meters: Optional[Decimal] = Field(
        None,
        ge=1.0,
        le=100.0,
        description="Plot width for rectangular plots"
    )
    boundary_buffer_meters: Optional[float] = Field(
        default=50.0,
        ge=0.0,
        le=200.0,
        description="Minimum distance from boundary to avoid edge effects (default: 50m)"
    )

    # Accessible forest filtering parameters (NEW - Phase 2)
    filter_tree_cover: Optional[bool] = Field(
        default=True,
        description="Filter to ESA WorldCover tree pixels (value=10) - Recommended (default: True)"
    )
    filter_slope: Optional[bool] = Field(
        default=False,
        description="Filter by slope accessibility - Optional (default: False)"
    )
    max_slope_degrees: Optional[float] = Field(
        default=45.0,
        ge=0.0,
        le=90.0,
        description="Maximum slope threshold in degrees (default: 45.0)"
    )

    notes: Optional[str] = Field(None, max_length=1000, description="Design notes")
    block_overrides: Optional[Dict[str, BlockOverride]] = Field(
        None,
        description="DEPRECATED: per-block parameter overrides (removed feature; kept for backward compat). Key is block name, value is override parameters"
    )


class SamplingDesignCreate(SamplingDesignBase):
    """
    Schema for creating sampling design with either Guideline-2061 or Manual method.

    Guideline-2061 Method:
    - Sample counts determined by lookup tables based on block size
    - Supports 0.5%, 1%, or 0.1% intensity
    - Systematic sampling only
    - Plot size in sqm (100-500 for production, 25-100 for protected)

    Manual Method:
    - Existing flexible sampling system
    - Supports systematic, random, stratified
    - Intensity as percentage with min samples rules
    - Plot dimensions in meters
    """
    # Override sampling_type to be optional - it's required for Manual method but not for Guideline-2061
    sampling_type: Optional[Literal["systematic", "random", "stratified"]] = Field(
        default="systematic",
        description="Sampling methodology (optional for Guideline-2061, required for Manual)"
    )
    
    # Method selection
    sampling_method: SamplingMethod = Field(
        default=SamplingMethod.GUIDELINE_2061,
        description="Sampling methodology: guideline_2061 (recommended) or manual (advanced)"
    )

    # Phase F (rule F): create-from-preview. When set, the design is persisted
    # from these EXACT previewed plot locations (deterministic) instead of
    # re-generating — what you previewed is what gets created, for all types.
    preview: Optional["SamplingPreviewInfo"] = Field(
        None,
        description="Pre-create preview output echoed back for deterministic creation (F.3)"
    )

    # Guideline-2061 specific parameters
    productive_intensity: Optional[GuidelineIntensity] = Field(
        default=GuidelineIntensity.HALF_PERCENT,
        description="Sampling intensity for productive forest (0.5% or 1%) - Guideline-2061 only"
    )
    sample_protected_zone: Optional[bool] = Field(
        default=False,
        description="Include protected zone sampling at 0.1% intensity - Guideline-2061 only"
    )
    plot_size_sqm: Optional[int] = Field(
        default=500,
        description="Plot size in square meters - Guideline-2061 only. "
                   "Options: 500, 400, 300, 200, 100 (production); 25, 100 (protected)"
    )
    per_block_intensity: Optional[Dict[str, float]] = Field(
        default=None,
        description="Guideline-2061 only. Optional block_name -> intensity_pct map "
                   "(e.g. from SFM's Production/Conservation/Protection classification) "
                   "overriding productive_intensity for the named blocks; unnamed "
                   "blocks still use productive_intensity. A one-shot generation "
                   "input, not persisted state - unrelated to the removed "
                   "block_overrides column."
    )

    per_block_plots: Optional[Dict[str, int]] = Field(
        default=None,
        description="Optional polygon name -> number of plots. Replaces the intensity arithmetic for the named polygons "
                    "(any number is allowed, fewer than 5 included, as long as it amounts to at least the stratum's minimum "
                    "intensity and at most 5 %). 0 = do not sample the polygon."
    )

    @field_validator('plot_size_sqm')
    @classmethod
    def validate_plot_size_sqm(cls, v, info):
        """Validate plot size for Guideline-2061 method

        When sampling protected zones, the user-specified plot size is for PRODUCTIVE zones.
        Protected zones will automatically use 100 sqm plots (standard for protected areas).
        """
        if info.data.get('sampling_method') == SamplingMethod.GUIDELINE_2061 and v is not None:
            valid_production_sizes = [100, 200, 300, 400, 500]

            # Plot size is for productive forests (or both if 100 sqm)
            if v not in valid_production_sizes:
                raise ValueError(
                    f"प्लट आकार {valid_production_sizes} वर्ग मिटरमध्ये एक हुनुपर्छ। प्राप्त: {v}"
                )
        return v

    @field_validator('plot_radius_meters')
    @classmethod
    def validate_plot_radius(cls, v, info):
        """Validate plot radius for circular plots (Manual method)"""
        if info.data.get('sampling_method') == SamplingMethod.MANUAL:
            if info.data.get('plot_shape') == 'circular' and v is None:
                # Default to 12.6156m (500m² plot)
                return Decimal("12.6156")
        return v

    @field_validator('plot_length_meters', 'plot_width_meters')
    @classmethod
    def validate_rectangular_dimensions(cls, v, info):
        """Validate dimensions for rectangular plots (Manual method)"""
        if info.data.get('sampling_method') == SamplingMethod.MANUAL:
            if info.data.get('plot_shape') in ['square', 'rectangular']:
                if v is None:
                    raise ValueError(
                        f"{info.data.get('plot_shape')} प्लटको लागि plot_length_meters र plot_width_meters आवश्यक छन्"
                    )
        return v

    @field_validator('sampling_type')
    @classmethod
    def validate_sampling_type(cls, v, info):
        """Ensure systematic sampling for Guideline-2061"""
        if info.data.get('sampling_method') == SamplingMethod.GUIDELINE_2061:
            if v and v != 'systematic':
                raise ValueError(
                    "Guideline-2061 विधिमा केवल systematic sampling मात्र समर्थित छ। "
                    "Random/stratified को लागि manual विधि प्रयोग गर्नुहोस्।"
                )
            return 'systematic'  # Force systematic for guideline
        return v

    model_config = ConfigDict(extra='forbid')


class SamplingDesignUpdate(BaseModel):
    """Schema for updating sampling design"""
    notes: Optional[str] = Field(None, max_length=1000)
    # H8.2 / S2-63. Declared explicitly because this model forbids extras --
    # without it a client that sends its version gets a 422 rather than the
    # protection it asked for.
    version: Optional[int] = Field(
        None, ge=0,
        description="Record version you last read; a mismatch answers 409.",
    )

    model_config = ConfigDict(extra='forbid')


class SamplingDesign(SamplingDesignBase):
    """Schema for sampling design response"""
    id: UUID
    calculation_id: UUID
    # Handed back so the client has a version to send on its next write.
    version: int = 0
    total_points: int
    created_at: datetime
    updated_at: datetime
    default_parameters: Optional[Dict[str, Any]] = Field(
        None,
        description="Default sampling parameters applied to all blocks"
    )
    block_overrides: Optional[Dict[str, Any]] = Field(
        None,
        description="DEPRECATED: per-block parameter overrides (removed feature; kept for backward compat)"
    )
    result_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Computed summary data (blocks_info, totals, percentages) from generation"
    )

    model_config = ConfigDict(from_attributes=True)


class SamplingPointGeoJSON(BaseModel):
    """GeoJSON feature for a sampling point"""
    type: Literal["Feature"] = "Feature"
    geometry: dict = Field(..., description="GeoJSON Point geometry")
    properties: dict = Field(..., description="Point properties (plot number, etc.)")


class SamplingPointsGeoJSON(BaseModel):
    """GeoJSON FeatureCollection for sampling points"""
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[SamplingPointGeoJSON]


class BlockSamplingInfo(BaseModel):
    """Information about sampling in one block"""
    block_number: int
    block_name: str
    block_area_hectares: Decimal
    samples_generated: int
    minimum_enforced: bool = Field(
        ...,
        description="Whether minimum sample rule was applied"
    )
    mmu_exempt: bool = Field(
        default=False,
        description=(
            "P8 8.1: this unit is below the absolute MMU and was exempted from the "
            "flat per-unit minimum, so 0 plots were placed. It is not a failure - a "
            "sub-MMU unit is not a management unit and cannot hold the plots."
        ),
    )
    user_excluded: bool = Field(
        default=False,
        description=(
            "The user set this unit's intensity to 0%, meaning 'do not sample "
            "this unit'. 0 plots were placed on purpose; not a failure and not "
            "subject to the stratum floor."
        ),
    )
    mmu_exempt_reason: Optional[str] = Field(
        default=None, description="Why the floor was not applied, in numbers"
    )
    actual_intensity_percent: Decimal = Field(
        ...,
        description="Actual sampling intensity achieved for this block"
    )
    grid_spacing_meters: Optional[Decimal] = Field(
        None,
        description="Grid spacing used for systematic sampling (meters)"
    )

    # Guideline-2061 specific fields
    samples_from_guideline: Optional[int] = Field(
        None,
        description="Sample count from Guideline-2061 table (if using guideline method)"
    )
    is_protected: Optional[str | bool] = Field(
        None,
        description="Protection status: 'Yes'/'No'/'Mixed' (string) or True/False (bool, legacy)"
    )
    guideline_fallback_used: Optional[bool] = Field(
        None,
        description="Whether manual calculation was used because block exceeded table range"
    )

    # Accessible forest area breakdown
    accessible_forest_area_ha: Optional[Decimal] = Field(
        None,
        description="Accessible forest area in hectares (tree cover + slope OK)"
    )
    inaccessible_steep_forest_ha: Optional[Decimal] = Field(
        None,
        description="Tree cover but too steep for sampling"
    )
    non_forest_area_ha: Optional[Decimal] = Field(
        None,
        description="Non-tree cover area (grassland, cropland, water, etc.)"
    )
    accessible_forest_percentage: Optional[Decimal] = Field(
        None,
        description="Percentage of block that is accessible forest"
    )
    sampling_method: Optional[str] = Field(
        None,
        description="Sampling method used: 'systematic' or 'random' (random used as fallback when systematic fails)"
    )
    stratum: Optional[str] = Field(
        None,
        description="SFM stratum for this unit: 'production', 'conservation' or 'protection' (कार्यविधि §16)"
    )
    floor_intensity_pct: Optional[Decimal] = Field(
        None,
        description="Minimum allowed sampling intensity (%) for the unit's stratum (कार्यविधि §16)"
    )
    plot_size_sqm: Optional[int] = Field(
        None,
        description="Plot size (m²) enforced for the unit's stratum (500 production/conservation, 100 protection)"
    )
    protected_area_ha: Optional[Decimal] = Field(
        None,
        description="Protected area in hectares within this block"
    )
    protected_samples_count: Optional[int] = Field(
        None,
        description="Number of samples generated in protected area"
    )
    protected_sampling_method: Optional[str] = Field(
        None,
        description="Sampling method used for protected area: 'systematic' or 'random'"
    )
    protected_grid_spacing_meters: Optional[Decimal] = Field(
        None,
        description="Grid spacing used for protected area systematic sampling (meters)"
    )
    protected_intensity_percent: Optional[Decimal] = Field(
        None,
        description="Actual sampling intensity achieved for protected area"
    )
    productive_area_ha: Optional[Decimal] = Field(
        None,
        description="Productive (non-protected) forest area in hectares"
    )
    productive_samples_count: Optional[int] = Field(
        None,
        description="Number of samples generated in productive area"
    )
    productive_sampling_method: Optional[str] = Field(
        None,
        description="Sampling method used for productive area: 'systematic' or 'random'"
    )

    model_config = ConfigDict(from_attributes=True)


class SamplingGenerateResponse(BaseModel):
    """Response schema for sampling design generation"""
    sampling_design_id: UUID
    calculation_id: UUID
    sampling_type: str
    total_points: int
    total_blocks: int = Field(..., description="Number of forest blocks")
    forest_area_hectares: Decimal
    requested_intensity_percent: Decimal = Field(
        ...,
        description="Requested sampling intensity percentage"
    )
    actual_intensity_per_hectare: Decimal = Field(
        ...,
        description="Actual sampling intensity achieved (points per hectare)"
    )
    plot_area_sqm: Optional[Decimal] = Field(None, description="Individual plot area")
    total_sampled_area_hectares: Optional[Decimal] = Field(
        None,
        description="Total area covered by all plots"
    )
    sampling_percentage: Optional[Decimal] = Field(
        None,
        description="Percentage of forest area sampled"
    )
    blocks_info: list[BlockSamplingInfo] = Field(
        default_factory=list,
        description="Per-block sampling details"
    )


class SamplingPreviewInfo(BaseModel):
    """Captured output of ``POST /sampling/preview`` echoed back to create (F.3).

    When ``SamplingDesignCreate.preview`` is set, the design is persisted from
    these exact plot locations (deterministic — what you preview is what gets
    created, for systematic AND random) rather than re-generating points.
    """
    preview_token: UUID = Field(
        ...,
        description="Token returned by the preview endpoint this design is created from"
    )
    total_points: int = Field(..., description="Total number of sample plots")
    total_blocks: int = Field(..., description="Number of forest units (blocks/compartments)")
    forest_area_hectares: Decimal = Field(..., description="Total forest area sampled (ha)")
    requested_intensity_percent: Decimal = Field(..., description="Requested sampling intensity %")
    actual_intensity_per_hectare: Decimal = Field(..., description="Actual intensity (points per hectare)")
    plot_area_sqm: Optional[Decimal] = Field(None, description="Individual plot area (m²)")
    total_sampled_area_hectares: Optional[Decimal] = Field(None, description="Total area covered by all plots")
    sampling_percentage: Optional[Decimal] = Field(None, description="Actual sampling % of the previewed layout")
    blocks_info: list[BlockSamplingInfo] = Field(
        default_factory=list,
        description="Per-unit sampling details (same shape as create response)"
    )
    sampling_points_geojson: SamplingPointsGeoJSON = Field(
        ...,
        description="Previewed plot locations as a GeoJSON FeatureCollection"
    )
    area_basis: str = Field(
        default="tree_cover",
        description="Sampling area basis used for the preview ('tree_cover' | 'full_area')"
    )


class SamplingPreviewResponse(BaseModel):
    """Response of ``POST /calculations/{id}/sampling/preview`` (rule F).

    Superset of the create summary — includes the plot GeoJSON plus the
    boundary/block layers so the shared ``SamplingMapView`` renders the preview
    with identical symbols/labels to a persisted design. No DB rows are written.
    """
    preview_token: UUID = Field(..., description="Token identifying this preview")
    total_points: int = Field(..., description="Total number of sample plots")
    total_units: int = Field(..., description="Number of forest units (blocks/compartments)")
    requested_intensity_percent: Decimal = Field(..., description="Requested sampling intensity %")
    sampling_percentage: Optional[Decimal] = Field(None, description="Actual sampling % of the previewed layout")
    area_basis: str = Field(default="tree_cover", description="Sampling area basis ('tree_cover' | 'full_area')")
    blocks_info: list[BlockSamplingInfo] = Field(
        default_factory=list,
        description="Per-unit sampling details (same shape as create response)"
    )
    sampling_points_geojson: SamplingPointsGeoJSON = Field(
        ...,
        description="Previewed plot locations for the shared map"
    )
    boundary_layer: dict = Field(..., description="GeoJSON Feature of the forest boundary")
    forest_blocks_layer: Optional[dict] = Field(
        None,
        description="GeoJSON FeatureCollection of blocks/compartments/sub-compartments"
    )
    filter_settings: dict = Field(
        default_factory=dict,
        description="Active filter settings (filter_tree_cover / filter_slope / max_slope_degrees)"
    )
    calculation_id: UUID = Field(..., description="Calculation the preview was computed for")
    sampling_type: str = Field(default="systematic", description="Sampling type ('systematic' | 'random' | 'stratified')")

    # Create-response fields echoed so the frontend can send the captured preview
    # back to /sampling/create for deterministic creation (rule F.3).
    total_blocks: int = Field(..., description="Number of forest units (alias of total_units)")
    forest_area_hectares: Decimal = Field(..., description="Total forest area sampled (ha)")
    actual_intensity_per_hectare: Decimal = Field(..., description="Actual intensity (points per hectare)")
    plot_area_sqm: Optional[Decimal] = Field(None, description="Individual plot area (m²)")
    total_sampled_area_hectares: Optional[Decimal] = Field(None, description="Total area covered by all plots")


class SamplingExportFormat(str):
    """Export format options"""
    CSV = "csv"
    GPX = "gpx"
    GEOJSON = "geojson"
    KML = "kml"


class ProtectedZoneInfo(BaseModel):
    """
    Information about protected zones in a calculation.
    Used to determine if protected zone sampling option should be shown.
    """
    has_protected: bool = Field(
        ...,
        description="Whether calculation has any protected zones"
    )
    protected_area_hectares: float = Field(
        ...,
        description="Total protected area in hectares"
    )
    protected_zone_names: list[str] = Field(
        default_factory=list,
        description="Names of protected zones"
    )
    protected_zone_count: int = Field(
        ...,
        description="Number of protected zones"
    )
    productive_area_hectares: float = Field(
        ...,
        description="Non-protected (productive) area in hectares"
    )
    total_area_hectares: float = Field(
        ...,
        description="Total forest area in hectares"
    )

    model_config = ConfigDict(from_attributes=True)


# Resolve the forward reference on SamplingDesignCreate.preview (defined above
# SamplingPreviewInfo) so Pydantic validates it on first use.
SamplingDesignCreate.model_rebuild()

