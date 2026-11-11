"""
Inventory schemas for request/response validation
"""
from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, List
from datetime import datetime
from uuid import UUID


class TreeSpeciesCoefficientResponse(BaseModel):
    """Schema for tree species coefficient response"""
    id: int
    scientific_name: str
    local_name: Optional[str]
    max_dbh_cm: Optional[float]
    max_height_m: Optional[float]
    is_active: bool

    # New fields (added 2026-03-03)
    wood_density_gm_cm3: Optional[float] = Field(None, description="Wood density in g/cm³")
    wood_density_source: Optional[str] = Field(None, description="Source reference for wood density data")
    genus: Optional[str] = Field(None, description="Genus name")

    class Config:
        from_attributes = True


class InventoryUploadRequest(BaseModel):
    """Schema for inventory file upload metadata"""
    calculation_id: Optional[UUID] = Field(None, description="Optional link to boundary calculation")
    grid_spacing_meters: float = Field(20.0, ge=5.0, le=100.0, description="Grid spacing for mother tree selection")
    projection_epsg: Optional[int] = Field(None, description="Optional EPSG code if CRS cannot be auto-detected")


class ValidationReportResponse(BaseModel):
    """Schema for validation report"""
    summary: Dict[str, Any]
    data_detection: Dict[str, Any]
    errors: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    info: List[Dict[str, Any]]
    corrections: List[Dict[str, Any]]


class InventoryCalculationCreate(BaseModel):
    """Schema for creating inventory calculation"""
    uploaded_filename: str
    calculation_id: Optional[UUID] = None
    grid_spacing_meters: float = 20.0
    projection_epsg: int = 32644


class InventoryCalculationResponse(BaseModel):
    """Schema for inventory calculation response"""
    id: UUID
    user_id: UUID
    uploaded_filename: str
    calculation_id: Optional[UUID]
    grid_spacing_meters: float
    projection_epsg: int
    status: str
    processing_time_seconds: Optional[int]
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    # Summary statistics
    total_trees: Optional[int]
    mother_trees_count: Optional[int]
    felling_trees_count: Optional[int]
    seedling_count: Optional[int]
    total_volume_m3: Optional[float]
    total_net_volume_m3: Optional[float]
    total_net_volume_cft: Optional[float]
    total_firewood_m3: Optional[float]
    total_firewood_chatta: Optional[float]

    # H8.3: rows skipped during processing -- present and non-empty only when
    # the upload was a partial success. None means every row parsed.
    row_errors: Optional[list] = None

    class Config:
        from_attributes = True


class InventoryTreeResponse(BaseModel):
    """Schema for individual tree response"""
    id: UUID
    species: str
    local_name: Optional[str]
    dia_cm: float
    height_m: Optional[float]
    tree_class: Optional[str]

    # Volumes
    stem_volume: Optional[float]
    branch_volume: Optional[float]
    tree_volume: Optional[float]
    gross_volume: Optional[float]
    net_volume: Optional[float]
    net_volume_cft: Optional[float]
    firewood_m3: Optional[float]
    firewood_chatta: Optional[float]

    # Mother tree info
    remark: Optional[str]
    grid_cell_id: Optional[int]

    # Coordinates (returned as lon, lat)
    longitude: Optional[float]
    latitude: Optional[float]

    # Block and Sub-area
    block_id: Optional[UUID] = None
    block_name: Optional[str] = None
    sub_area_id: Optional[UUID] = None
    sub_area_name: Optional[str] = None

    class Config:
        from_attributes = True


class InventoryTreesListResponse(BaseModel):
    """Schema for paginated trees list"""
    trees: List[InventoryTreeResponse]
    total_count: int
    page: int
    page_size: int
    has_more: bool


class InventoryUpdateTreeRequest(BaseModel):
    """Schema for updating tree remark"""
    remark: str = Field(..., pattern="^(Mother Tree|Felling Tree|Seedling)$")


class InventorySummaryResponse(BaseModel):
    """Schema for inventory summary statistics"""
    inventory_id: UUID
    total_trees: int
    mother_trees_count: int
    felling_trees_count: int
    seedling_count: int

    # Volume summary
    total_volume_m3: float
    total_net_volume_m3: float
    total_net_volume_cft: float
    total_firewood_m3: float
    total_firewood_chatta: float

    # Species distribution
    species_distribution: Dict[str, int]

    # DBH classes
    dbh_classes: Dict[str, int]

    # Processing info
    status: str
    created_at: datetime
    completed_at: Optional[datetime]
    processing_time_seconds: Optional[int]


class MyInventoriesResponse(BaseModel):
    """Schema for user's inventory list"""
    inventories: List[InventoryCalculationResponse]
    total_count: int


class ExportFormat(str):
    """Export format enum"""
    CSV = "csv"
    SHAPEFILE = "shapefile"
    GEOJSON = "geojson"


# Boundary Correction Schemas

class TreeCorrectionDetail(BaseModel):
    """Schema for individual tree correction"""
    row_number: int
    species: str
    original_x: float
    original_y: float
    corrected_x: float
    corrected_y: float
    distance_moved_meters: float


class CorrectionSummary(BaseModel):
    """Schema for correction summary statistics"""
    total_corrections: int
    max_distance: float
    min_distance: float
    avg_distance: float


class BoundaryCheckResult(BaseModel):
    """Schema for boundary validation result"""
    total_points: int
    out_of_boundary_count: int
    out_of_boundary_percentage: float
    within_tolerance: bool
    needs_correction: bool
    error_message: Optional[str] = None


class CorrectionPreviewResponse(BaseModel):
    """Schema for correction preview response"""
    inventory_id: UUID
    boundary_check: BoundaryCheckResult
    corrections: List[TreeCorrectionDetail]
    summary: CorrectionSummary
    warnings: List[str] = []


class AcceptCorrectionsRequest(BaseModel):
    """Schema for accepting corrections"""
    inventory_id: UUID
    apply_corrections: bool = True


class TreeCorrectionLogResponse(BaseModel):
    """Schema for tree correction log"""
    id: int
    tree_row_number: int
    species: Optional[str]
    original_x: float
    original_y: float
    corrected_x: float
    corrected_y: float
    distance_moved_meters: float
    correction_reason: str
    corrected_at: datetime

    class Config:
        from_attributes = True
