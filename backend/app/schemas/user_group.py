"""Pydantic schemas for User Group extent and analysis endpoints.

Request/response models for extent upload, manual digitization, auto-
buffer, spatial analysis, and land cover analysis. Covers all input
validation and response serialization for the User Group module.

See also:
    app.api.user_group — API endpoints
    app.services.user_group_analysis — business logic
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class ExtentUploadRequest(BaseModel):
    """Request schema for uploading a user group extent file."""
    source_type: str = "uploaded"


class ManualExtentRequest(BaseModel):
    """Request schema for manually digitized extent geometry."""
    geometry: Dict[str, Any]


class AutoBufferRequest(BaseModel):
    """Request schema for auto-buffer extent generation."""
    buffer_distance: int = 1000


class AnalysisRequest(BaseModel):
    """Request schema for triggering spatial analysis on an extent."""
    extent_id: int


class SettlementStatistics(BaseModel):
    """Settlement analysis statistics within a user group extent."""
    settlement_id: Optional[int] = None
    settlement_name: str
    building_count: int
    total_area_m2: float
    small_buildings: int = 0
    medium_buildings: int = 0
    large_buildings: int = 0
    avg_building_size_m2: float = 0
    direction_from_forest: str
    lat: Optional[float] = None
    lon: Optional[float] = None

    class Config:
        from_attributes = True


class BuildingPoint(BaseModel):
    """Individual building point with location and area."""
    lat: float
    lon: float
    area: Optional[float] = None


class UserGroupResults(BaseModel):
    """Complete user group spatial analysis results."""
    extent_id: int
    extent_geometry: Dict[str, Any]
    forest_boundary: Dict[str, Any]
    settlements: List[SettlementStatistics]
    buildings: List[BuildingPoint]


class ExtentResponse(BaseModel):
    """Response schema for extent creation operations."""
    extent_id: int
    message: str
    # what we noticed and fixed while reading the file (UTM converted, columns swapped): plain, bilingual, with nothing to do
    findings: list = []


class ExtentGeoJSONResponse(BaseModel):
    """Thin read of the current extent for the workspace layer's DataSource.

    `geometry` is a GeoJSON geometry (MultiPolygon); `null` fields when no
    extent exists yet.
    """
    extent_id: Optional[int] = None
    source_type: Optional[str] = None
    buffer_distance_m: Optional[int] = None
    area_hectares: Optional[float] = None
    geometry: Optional[Dict[str, Any]] = None


class AnalysisResponse(BaseModel):
    """Response schema for analysis execution."""
    message: str
    settlements_analyzed: int
    total_buildings: int


class POILayer(BaseModel):
    """Point of Interest layer item."""
    name: str
    lon: float
    lat: float
    type: Optional[str] = None


class POIResponse(BaseModel):
    """Response schema for points of interest search."""
    poi: Optional[List[POILayer]] = []
    education: Optional[List[POILayer]] = []
    health: Optional[List[POILayer]] = []
    rivers: Optional[List[Dict[str, Any]]] = []


# ============================================================================
# Land Cover Analysis Schemas
# ============================================================================

class LandCoverClass(BaseModel):
    """Individual land cover class statistics."""
    class_code: int
    class_name: str
    area_ha: float
    percentage: float
    avg_biomass_mg_per_ha: float
    min_biomass_mg_per_ha: float
    max_biomass_mg_per_ha: float
    total_biomass_mg: float
    avg_volume_m3_per_ha: float
    total_volume_m3: float
    pixel_count: int


class LandCoverAnalysisResponse(BaseModel):
    """Complete land cover analysis results."""
    # Area summary
    user_group_area_ha: float
    forest_overlap_area_ha: float
    net_analysis_area_ha: float

    # Land cover breakdown
    land_cover_classes: List[LandCoverClass]

    # Overall biomass summary
    total_biomass_mg: float
    total_volume_m3: float
    avg_biomass_mg_per_ha: float
    avg_volume_m3_per_ha: float

    # Metadata
    analysis_date: datetime
    has_forest_overlap: bool

    class Config:
        from_attributes = True