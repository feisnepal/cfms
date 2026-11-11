"""
Forest management schemas for request/response validation
"""
from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, List, Literal
from datetime import datetime
from uuid import UUID

from ..models.calculation import CalculationStatus


class CommunityForestResponse(BaseModel):
    """Schema for community forest data response"""
    id: int
    name: Optional[str]
    code: Optional[str]
    regime: Optional[str]
    area_hectares: float
    geometry: Optional[Dict[str, Any]]  # GeoJSON

    class Config:
        from_attributes = True


class ForestManagerCreate(BaseModel):
    """Schema for creating forest manager assignment"""
    user_id: UUID
    community_forest_id: int
    role: str = Field(..., pattern="^(manager|chairman|secretary|member)$")


class ForestManagerResponse(BaseModel):
    """Schema for forest manager data response"""
    id: UUID
    user_id: UUID
    community_forest_id: int
    role: str
    assigned_date: datetime
    is_active: bool

    class Config:
        from_attributes = True


class CalculationCreate(BaseModel):
    """Schema for creating a new calculation"""
    forest_name: Optional[str] = None
    block_name: Optional[str] = None


class CalculationResponse(BaseModel):
    """Schema for calculation data response"""
    id: UUID
    user_id: UUID
    uploaded_filename: Optional[str] = None  # Nullable for drafts
    forest_name: Optional[str]
    block_name: Optional[str]
    status: CalculationStatus
    processing_time_seconds: Optional[int]
    error_message: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime] = None  # Added for drafts
    completed_at: Optional[datetime]
    is_draft: Optional[bool] = False  # Added for drafts
    geometry: Optional[Dict[str, Any]]  # GeoJSON
    result_data: Optional[Dict[str, Any]]
    # Name-first creation: lets the client tell a boundary-less draft
    # (draft_data.islands_count == 0) from a legacy island-bearing draft.
    draft_data: Optional[Dict[str, Any]] = None
    # U08/U09 — unified shell feature flag
    unified_shell_enabled: Optional[bool] = None
    # Map lifecycle + structure lock (H-SUBMIT). Without these on the read path
    # the workspace only learns a map is locked if the client submitted it in
    # the same session — so an already-locked forest showed an editable UI and
    # every restructure failed with a 423 instead of a disabled control.
    map_lifecycle_status: Optional[str] = None
    structure_locked: Optional[bool] = None
    structure_locked_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AnalysisResultResponse(BaseModel):
    """Schema for analysis results"""
    calculation_id: UUID
    status: CalculationStatus
    processing_time_seconds: Optional[int]

    # Area calculations
    area_hectares: Optional[float]
    area_sqm: Optional[float]

    # Elevation metrics
    elevation_min: Optional[float]
    elevation_max: Optional[float]
    elevation_mean: Optional[float]

    # Slope analysis
    slope_dominant_class: Optional[str]
    slope_percentages: Optional[Dict[str, float]]

    # Aspect analysis
    aspect_dominant: Optional[str]
    aspect_percentages: Optional[Dict[str, float]]

    # Canopy height
    canopy_dominant_class: Optional[str]
    canopy_percentages: Optional[Dict[str, float]]

    # Forest health
    forest_health_dominant: Optional[str]
    forest_health_percentages: Optional[Dict[str, float]]

    # Biomass and carbon
    agb_mean: Optional[float]
    agb_total: Optional[float]
    carbon_stock: Optional[float]

    # Climate
    temperature_mean: Optional[float]
    precipitation_mean: Optional[float]

    # Land cover
    landcover_dominant: Optional[str]
    landcover_percentages: Optional[Dict[str, float]]

    # Forest change
    forest_loss_hectares: Optional[float]
    forest_gain_hectares: Optional[float]
    forest_loss_by_year: Optional[Dict[str, float]]

    # Administrative location
    province: Optional[str]
    municipality: Optional[str]
    ward: Optional[str]

    # Proximity analysis
    nearest_settlement: Optional[Dict[str, Any]]
    nearest_road: Optional[Dict[str, Any]]
    nearest_river: Optional[Dict[str, Any]]
    buildings_within_1km: Optional[int]

    # Full JSONB data
    full_results: Optional[Dict[str, Any]]


class ForestListQuery(BaseModel):
    """Schema for querying forest list"""
    search: Optional[str] = None
    regime: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class MyForestsResponse(BaseModel):
    """Schema for user's assigned forests"""
    forests: List[Dict[str, Any]]
    total_count: int
    total_area_hectares: float


class ReanalysisRequest(BaseModel):
    """Schema for re-running analysis with different options"""
    # Analysis options (all optional, if not provided will use stored defaults)
    run_raster_analysis: Optional[bool] = None
    run_elevation: Optional[bool] = None
    run_slope: Optional[bool] = None
    run_aspect: Optional[bool] = None
    run_canopy: Optional[bool] = None
    run_biomass: Optional[bool] = None
    run_forest_health: Optional[bool] = None
    run_forest_type: Optional[bool] = None
    run_landcover: Optional[bool] = None
    run_forest_loss: Optional[bool] = None
    run_forest_gain: Optional[bool] = None
    run_fire_loss: Optional[bool] = None
    run_temperature: Optional[bool] = None
    run_precipitation: Optional[bool] = None
    run_soil: Optional[bool] = None
    run_proximity: Optional[bool] = None


class GenerateMapsRequest(BaseModel):
    """Schema for requesting map generation"""
    # Map types to generate (all optional, at least one should be True)
    generate_boundary_map: bool = False
    generate_topographic_map: bool = False
    generate_slope_map: bool = False
    generate_aspect_map: bool = False
    generate_forest_type_map: bool = False
    generate_canopy_height_map: bool = False
    generate_landcover_change_map: bool = False
    generate_soil_map: bool = False
    generate_forest_health_map: bool = False


class AddSpeciesRequest(BaseModel):
    """Schema for adding a species to a calculation"""
    species_id: int = Field(..., description="ID of species from tree_species_coefficients table")
    role: str = Field("Associate", description="Role of the species (Dominant, Co-dominant, Associate, Occasional, Rare)")
    availability_rank: int = Field(3, ge=1, le=4, description="Availability rank (1=Dominant, 2=Co-dominant, 3=Associate, 4=Occasional/Rare)")


class GeometryUpdateRequest(BaseModel):
    """Schema for updating calculation boundary geometry"""
    geometry: Dict[str, Any] = Field(..., description="GeoJSON geometry for the new boundary")
    reanalyze: bool = Field(True, description="Whether to re-run analysis after geometry update")


class SubAreaCategory(str):
    """Valid sub-area categories"""
    PROTECTED = "protected"
    PLANTATION = "plantation"
    PRO_POOR = "pro-poor"
    RELIGIOUS = "religious"
    BIODIVERSITY = "biodiversity"
    TOURIST = "tourist"
    OFFICE = "office"
    PRIVATE_LAND = "private_land"
    AGROFORESTRY = "agroforestry"
    TREE_STRATA = "tree_strata"
    WATER_HOLE = "water_hole"
    WILDLIFE_CORRIDOR = "wildlife_corridor"
    ENCRACHED = "encroached"

    @classmethod
    def valid_categories(cls) -> List[str]:
        return [
            cls.PROTECTED, cls.PLANTATION, cls.PRO_POOR, cls.RELIGIOUS,
            cls.BIODIVERSITY, cls.TOURIST, cls.OFFICE, cls.PRIVATE_LAND,
            cls.AGROFORESTRY, cls.TREE_STRATA, cls.WATER_HOLE, cls.WILDLIFE_CORRIDOR,
            cls.ENCRACHED,
        ]

    @classmethod
    def catalog(cls) -> List[Dict[str, Any]]:
        """Canonical category catalogue (single source of truth for the API).

        Each entry: key, label (EN), label_np, color, is_excluded.
        is_excluded is derived from category — only private_land is excluded.
        """
        return [
            {"key": cls.PROTECTED,        "label": "Protected Area",        "label_np": "संरक्षित क्षेत्र",         "color": "#ef4444", "is_excluded": False},
            {"key": cls.PLANTATION,       "label": "Plantation",            "label_np": "बृक्षारोपण क्षेत्र",        "color": "#10b981", "is_excluded": False},
            {"key": cls.PRO_POOR,         "label": "Pro-Poor Allocated",    "label_np": "गरिव तथा विपन्नको लागी छुट्याइएको क्षेत्र", "color": "#f59e0b", "is_excluded": False},
            {"key": cls.RELIGIOUS,        "label": "Religious Area",        "label_np": "धार्मीक क्षेत्र",            "color": "#8b5cf6", "is_excluded": False},
            {"key": cls.BIODIVERSITY,     "label": "Biodiversity",          "label_np": "जैविक विविधता क्षेत्र",      "color": "#06b6d4", "is_excluded": False},
            {"key": cls.TOURIST,          "label": "Tourist Area",          "label_np": "पर्यटन क्षेत्र",              "color": "#ec4899", "is_excluded": False},
            {"key": cls.OFFICE,           "label": "Office Complex",        "label_np": "कार्यालय परिसर",             "color": "#6b7280", "is_excluded": False},
            {"key": cls.PRIVATE_LAND,     "label": "Private Land (Excluded)", "label_np": "निजि जग्गा (बहिस्कृत)",   "color": "#dc2626", "is_excluded": True},
            {"key": cls.AGROFORESTRY,     "label": "Agroforestry",          "label_np": "कृषिवन क्षेत्र",             "color": "#84cc17", "is_excluded": False},
            {"key": cls.TREE_STRATA,      "label": "Large Tree Area",       "label_np": "धेरै ठुला रूख भएको क्षेत्र",   "color": "#15803d", "is_excluded": False},
            {"key": cls.WATER_HOLE,       "label": "Water Hole",            "label_np": "पानी मूहान",                 "color": "#0ea5e9", "is_excluded": False},
            {"key": cls.WILDLIFE_CORRIDOR, "label": "Wildlife Corridor",    "label_np": "जैविक मार्ग",               "color": "#a855f7", "is_excluded": False},
            {"key": cls.ENCRACHED,        "label": "Encroached",            "label_np": "अतीक्रमीत क्षेत्र",          "color": "#78350f", "is_excluded": False},
        ]


class SubAreaCategoryItem(BaseModel):
    """Single entry of the sub-area category catalogue."""
    key: str
    label: str
    label_np: str
    color: str
    is_excluded: bool


class BlockBreakdownItem(BaseModel):
    """Schema for block breakdown item"""
    blockId: Optional[str] = Field(None, description="Block ID")
    blockName: str = Field(..., description="Block name")
    area: float = Field(..., description="Area in hectares in this block")
    percentage: float = Field(..., description="Percentage of sub-area in this block")

    class Config:
        # Allow field names to be used directly (camelCase from frontend)
        populate_by_name = True


class SubAreaCreateRequest(BaseModel):
    """Schema for creating a sub-area"""
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., description="Sub-area category")
    geometry: Dict[str, Any] = Field(..., description="GeoJSON geometry")
    block_id: Optional[str] = Field(None, description="Primary block ID (for single-block sub-areas)")
    block_name: Optional[str] = Field(None, description="Primary block name (for single-block sub-areas)")
    block_breakdown: Optional[List[BlockBreakdownItem]] = Field(None, description="Block-wise breakdown for cross-block sub-areas")
    is_excluded: bool = Field(False, description="Whether this area is excluded from forest (e.g., private land)")
    area_hectares: Optional[float] = Field(None, description="Area in hectares (optional - will be calculated if not provided)")

    def validate_category(self):
        if self.category not in SubAreaCategory.valid_categories():
            raise ValueError(f"INVALID_CATEGORY: अमान्य श्रेणी। मान्य श्रेणीहरू: {', '.join(SubAreaCategory.valid_categories())}")


class SubAreaUpdateRequest(BaseModel):
    """Schema for updating a sub-area"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[str] = Field(None, description="Sub-area category")
    geometry: Optional[Dict[str, Any]] = Field(None, description="GeoJSON geometry")
    block_id: Optional[str] = Field(None, description="Associated block ID")
    block_name: Optional[str] = Field(None, description="Associated block name")
    is_excluded: Optional[bool] = Field(None, description="Whether this area is excluded from forest")
    area_hectares: Optional[float] = Field(None, description="Area in hectares (optional - will be calculated if not provided)")
    style: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Per-feature style override — {fill, fillOpacity, stroke, weight}, any subset. "
            "An explicit null clears it back to the category colour "
            "(WORKSPACE_LAYER_STYLING_PLAN.md P3)."
        ),
    )


class BlockRenameRequest(BaseModel):
    """Phase C (auto-block): rename a forest block's display/serial/natural names.

    ``name`` is the display name (mirrors ``block_name`` when the latter is the
    auto-generated serial). ``block_name`` may be given to override the serial
    independently (e.g. a manual ``Block-12``); ``natural_name`` is the
    best-effort river/ridge name. All fields optional — only provided ones are
    applied; at least one is required.

    ``compartment_code``/``dominant_slope_band``/``dominant_aspect``/
    ``dominant_canopy_class`` (attribute-table editability, user report
    2026-09-12 — a merge auto-picks these from the larger source feature, and
    the user must still be able to correct the pick by hand) follow the same
    "present in the request → apply, including clearing to null; absent →
    leave untouched" rule as ``natural_name``/``style`` below.

    ``management_orientation`` is the user-editable counterpart to the
    "Suggested Orientation" SFM's own classifier computes (user report,
    2026-09-12) — auto-suggested at slope Auto-Block commit time, always
    overridable. Stores the same capitalized strings
    ``sustainable_fm.orientation.propose`` returns.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    block_name: Optional[str] = Field(None, min_length=1, max_length=255)
    natural_name: Optional[str] = Field(None, max_length=255)
    compartment_code: Optional[str] = Field(None, max_length=50)
    dominant_slope_band: Optional[int] = Field(
        None, ge=1, le=4, description="कार्यविधि §15.2 slope band: 1=<19° 2=19-31° 3=31-45° 4=>45°"
    )
    dominant_aspect: Optional[int] = Field(
        None, ge=1, le=8, description="1=N 2=NE 3=E 4=SE 5=S 6=SW 7=W 8=NW"
    )
    dominant_canopy_class: Optional[int] = Field(
        None, ge=1, le=4, description="1=non-forest 2=regeneration 3=pole 4=tree"
    )
    # The four Raster-Sources classifications (migration 105). Same "present in
    # the request -> apply, including clearing to null" rule as the 084/085
    # dominant_* fields. `elevation_*` is deliberately absent: it is read-only,
    # derived from the geometry (response-only, plan rule 8 / §5.1 item 5).
    dominant_health_class: Optional[int] = Field(
        None, ge=1, le=5, description="NDVI forest health: 1=Stressed 2=Poor 3=Fair 4=Good 5=Excellent"
    )
    dominant_nasa_quality: Optional[int] = Field(
        None, ge=1, le=3, description="NASA 2020 forest quality: 1=Primary 2=Young secondary 3=Old secondary"
    )
    dominant_landcover: Optional[int] = Field(
        None, ge=10, le=100, description="ESA WorldCover land-cover code (10-100); 0=NoData is never a dominant value"
    )
    dominant_elevation_zone: Optional[int] = Field(
        None, ge=1, le=3, description="DEM elevation zone 1=low 2=mid 3=high (mean ± 1 SD of this forest)"
    )
    management_orientation: Optional[Literal["Production", "Conservation", "Protection"]] = Field(
        None, description="SFM-aligned management orientation for a slope-carved block"
    )
    style: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Per-feature style override — {fill, fillOpacity, stroke, weight}, any subset. "
            "An explicit null clears it (WORKSPACE_LAYER_STYLING_PLAN.md P3)."
        ),
    )


class SubAreaResponse(BaseModel):
    """Schema for sub-area response"""
    id: str
    name: str
    category: str
    geometry: Dict[str, Any]
    area_hectares: float
    block_id: Optional[str] = None
    block_name: Optional[str] = None
    block_breakdown: Optional[List[BlockBreakdownItem]] = None
    is_excluded: bool = False
    style: Optional[Dict[str, Any]] = None


class SubAreaListResponse(BaseModel):
    """Schema for sub-area list response"""
    sub_areas: List[SubAreaResponse]
    total_count: int
    total_area_hectares: float


class BoundaryPieceUpdateRequest(BaseModel):
    """BOUNDARY_PIECES_PLAN.md P3 — rename a boundary piece. Deliberately just
    `name` (D3: minimal first cut) — geometry/delete are not editable through
    this endpoint (D7: piece-level reshape/delete is a later phase; a piece's
    geometry only ever changes as a side effect of a boundary write, kept in
    sync by `boundary_pieces_service.sync_boundary_pieces`)."""
    name: str = Field(..., min_length=1, max_length=255)


class BoundaryPieceResponse(BaseModel):
    """Schema for a single forest-boundary-piece response."""
    id: str
    name: str
    geometry: Dict[str, Any]
    area_hectares: float


class BoundaryPieceListResponse(BaseModel):
    """Schema for the boundary-pieces list response."""
    pieces: List[BoundaryPieceResponse]
    total_count: int
    total_area_hectares: float


class BlockPolygonResponse(BaseModel):
    """Schema for individual polygon extracted from boundary geometry"""
    index: int
    geometry: Dict[str, Any]
    area_hectares: float
    current_name: Optional[str] = None


class BlockPolygonListResponse(BaseModel):
    """Schema for list of polygons from a calculation"""
    polygons: List[BlockPolygonResponse]
    total_count: int


class BlockCreateRequest(BaseModel):
    """Schema for creating a forest block from polygon mapping"""
    polygon_index: int
    name: str


class BlockCreateListRequest(BaseModel):
    """Schema for creating multiple forest blocks"""
    blocks: List[BlockCreateRequest]
    # REMOVED: run_analysis parameter - analysis is now triggered separately from Analysis page


class BlockCreateFromGeometryRequest(BaseModel):
    """Schema for creating forest blocks from arbitrary GeoJSON geometries"""
    blocks: List[Dict[str, Any]]  # Each: {geometry: GeoJSON, name: str, index?: int}


class BlockResponse(BaseModel):
    """Schema for forest block response"""
    id: str
    name: str
    block_name: Optional[str] = None
    natural_name: Optional[str] = None
    compartment_code: Optional[str] = None
    geometry: Dict[str, Any]
    area_hectares: float
    index: int
    created_at: datetime
    working_circle: str = "production"
    style: Optional[Dict[str, Any]] = None
    # Field-inventory forest condition ('Good' | 'Moderate' | 'Weak'), when a
    # field inventory has been processed. Surfaced for the "Colour by condition"
    # thematic preset (WORKSPACE_LAYER_STYLING_PLAN.md P4.5).
    forest_condition: Optional[str] = None
    # Slope band (1-4) that dominated this block's geometry when it was
    # carved via the slope-class Auto-Block source (migration 084). NULL for
    # every other origin.
    dominant_slope_band: Optional[int] = None
    # Same shape, for the `aspect` (1-8) and `canopy` (1-4) Auto-Block
    # sources (migration 085). NULL for every other origin.
    dominant_aspect: Optional[int] = None
    dominant_canopy_class: Optional[int] = None
    # The four Raster-Sources classifications (migration 105).
    dominant_health_class: Optional[int] = None
    dominant_nasa_quality: Optional[int] = None
    dominant_landcover: Optional[int] = None
    dominant_elevation_zone: Optional[int] = None
    # Read-only real altitude (migration 105). Values are floats, not Decimal,
    # because these cross a JSON boundary (Numeric(7,1) columns).
    elevation_min_m: Optional[float] = None
    elevation_mean_m: Optional[float] = None
    elevation_max_m: Optional[float] = None
    # Management orientation (migration 086) -- the user-editable, persisted
    # value (auto-suggested at slope Auto-Block commit time from SFM's own
    # classifier). NULL for every other origin.
    management_orientation: Optional[str] = None
    # Persisted at slope Auto-Block commit (migration 087) from SFM's own classifier and
    # never recomputed on read: it is the value the user saw when the block was created.
    # NULL for every other origin.
    suggested_orientation: Optional[str] = None
    # Persisted alongside suggested_orientation, read-only explanation of *why* (the सि.नं. reference; slope-trigger cases name the
    # threshold, D7, 2026-09-15). Blank under the same condition.
    orientation_justification_ne: Optional[str] = None
    orientation_justification_en: Optional[str] = None

    class Config:
        from_attributes = True


class BlockListResponse(BaseModel):
    """Schema for block list response"""
    blocks: List[BlockResponse]
    total_count: int
    total_area_hectares: float
    # 'block' | 'compartment' | 'undecided' - the branch of the structure rule this forest uses (forest_units).
    # Additive; only the calculation's block list fills it.
    stream: Optional[str] = None


class BlockAreaDetailItem(BaseModel):
    """Schema for per-block area detail (Table 5)"""
    block_name: str
    total_area_ha: float
    tree_cover_area_ha: float
    other_landcover_area_ha: float
    protected_area_ha: float
    private_land_area_ha: float
    effective_area_ha: float
    official_area_ha: float = 0.0


class BlockAreaDetailResponse(BaseModel):
    """Schema for block area detail response (Table 5)"""
    calculation_id: str
    forest_name: str
    total_blocks: int
    block_details: List[BlockAreaDetailItem]
    totals: BlockAreaDetailItem


class DraftSaveRequest(BaseModel):
    """Schema for saving work-in-progress polygon creation (islands) as draft"""
    forest_name: str = Field(..., min_length=1, max_length=255, description="Name of the forest")
    islands: List[Dict[str, Any]] = Field(default_factory=list, description="Array of island objects with geometry and area")
    mode: str = Field(..., pattern="^(auto|manual)$", description="Creation mode (auto or manual)")
    draft_id: Optional[UUID] = Field(None, description="Existing draft ID to update, if resuming")
    # U11: wizard step index for autosave resume
    draft_step_index: Optional[int] = Field(None, ge=0, le=10, description="Current wizard step index (0-based)")

    class Config:
        json_schema_extra = {
            "example": {
                "forest_name": "Community Forest ABC",
                "islands": [
                    {
                        "id": "island-1234567890",
                        "geometry": {"type": "Polygon", "coordinates": [[[85.0, 27.0], [85.1, 27.0], [85.1, 27.1], [85.0, 27.1], [85.0, 27.0]]]},
                        "area": 12.5
                    }
                ],
                "mode": "manual",
                "draft_id": None
            }
        }


class DraftResponse(BaseModel):
    """Schema for draft data response"""
    id: UUID
    forest_name: str
    islands_count: int
    total_area: float
    mode: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DraftDetailResponse(BaseModel):
    """Schema for detailed draft response including full data"""
    id: UUID
    forest_name: str
    draft_data: Dict[str, Any]  # Contains islands array, mode, and draft_step_index
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConvertDraftRequest(BaseModel):
    """Schema for converting draft to calculation"""
    outer_boundary: Dict[str, Any] = Field(..., description="GeoJSON geometry object")
    
    class Config:
        extra = "allow"  # Allow additional fields


class CreateNameOnlyDraftRequest(BaseModel):
    """Schema for creating a draft by name only (no boundary yet).

    The boundary is added afterwards in the workspace via the unified
    "Add Boundary" action (import file or draw on map).
    """
    forest_name: str = Field(..., min_length=1, max_length=255, description="Name of the forest")


class MergeForestBoundaryRequest(BaseModel):
    """Schema for merging one or more geometry pieces into the forest boundary.

    Block / Compartment / Forest-boundary pieces (as GeoJSON geometries) are
    unioned together to form the single authoritative forest boundary.
    """
    geometries: List[Dict[str, Any]] = Field(
        ...,
        min_length=1,
        description="GeoJSON geometry objects to merge into the forest boundary",
    )
