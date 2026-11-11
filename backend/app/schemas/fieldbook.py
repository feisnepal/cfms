"""
Pydantic schemas for Fieldbook API
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID


class FieldbookPointBase(BaseModel):
    """Base schema for fieldbook point"""
    point_number: int = Field(..., description="Sequential point number")
    point_type: str = Field(..., description="Type: 'vertex' or 'interpolated'")
    longitude: Decimal = Field(..., description="WGS84 longitude")
    latitude: Decimal = Field(..., description="WGS84 latitude")
    easting_utm: Optional[Decimal] = Field(None, description="UTM Easting")
    northing_utm: Optional[Decimal] = Field(None, description="UTM Northing")
    utm_zone: Optional[int] = Field(None, description="UTM Zone (44 or 45 for Nepal)")
    azimuth_to_next: Optional[Decimal] = Field(None, description="Bearing to next point (degrees)")
    distance_to_next: Optional[Decimal] = Field(None, description="Distance to next point (meters)")
    elevation: Optional[Decimal] = Field(None, description="Elevation from DEM (meters)")
    remarks: Optional[str] = Field(None, description="Field remarks")
    is_verified: bool = Field(False, description="GPS verified in field")
    block_number: Optional[int] = Field(None, description="Block number (for multi-block forests)")
    block_name: Optional[str] = Field(None, description="Block name (e.g., 'Block 1', 'Ward 5')")
    sub_area_name: Optional[str] = Field(None, description="Sub-area name, if this point is on a sub-area boundary")
    sub_area_category: Optional[str] = Field(None, description="Sub-area category (e.g. 'religious', 'plantation', 'private_land')")
    is_excluded: Optional[bool] = Field(None, description="True if on an excluded (private land) sub-area boundary")
    point_label: Optional[str] = Field(None, description="Label shown to people: 'O1'.. for outer points, 'I1'.. for internal")
    boundary_class: Optional[str] = Field(None, description="'outer' (on the forest boundary) or 'internal'")
    junction_degree: Optional[int] = Field(None, description="Number of units that meet at this point")
    is_junction: Optional[bool] = Field(None, description="Outer: boundary + 2 or more units; internal: 3 or more units")
    adjacent_units: Optional[List[str]] = Field(None, description="Names of the units this point separates")
    next_point_label: Optional[str] = Field(None, description="Label of the point azimuth/distance lead to")
    line_id: Optional[str] = Field(None, description="The line that first reached this point: O-n outer ring, I-n internal edge, L-n loop")
    lines: Optional[dict] = Field(None, description="Every line this point is on and its order in each, e.g. {'I-2': 5, 'O-1': 12}")


class FieldbookPointCreate(FieldbookPointBase):
    """Schema for creating fieldbook point"""
    pass


class FieldbookPointUpdate(BaseModel):
    """Schema for updating fieldbook point"""
    remarks: Optional[str] = None
    is_verified: Optional[bool] = None

    model_config = ConfigDict(extra='forbid')


class FieldbookPoint(FieldbookPointBase):
    """Schema for fieldbook point response"""
    id: UUID
    calculation_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FieldbookGenerateRequest(BaseModel):
    """Request schema for generating fieldbook"""
    interpolation_distance_meters: int = Field(
        default=50,
        ge=0,
        le=200,
        description="Distance for interpolating points between vertices (meters). 0 = vertices only."
    )
    extract_elevation: bool = Field(
        default=True,
        description="Extract elevation from DEM for each point"
    )
    calculate_reference: bool = Field(
        default=False,
        description="Calculate reference (nearest landmark) for each point. WARNING: This is VERY slow (10-20 seconds per point). Only enable if needed."
    )

    model_config = ConfigDict(extra='forbid')


class FieldbookGenerateResponse(BaseModel):
    """Response schema for fieldbook generation"""
    calculation_id: UUID
    total_vertices: int = Field(..., description="Number of original vertices")
    interpolated_points: int = Field(..., description="Number of interpolated points")
    total_points: int = Field(..., description="Total points in fieldbook")
    total_perimeter_meters: Decimal = Field(..., description="Total boundary perimeter")
    avg_elevation_meters: Optional[Decimal] = Field(None, description="Average elevation")
    min_elevation_meters: Optional[Decimal] = Field(None, description="Minimum elevation")
    max_elevation_meters: Optional[Decimal] = Field(None, description="Maximum elevation")
    unit_type: Optional[str] = Field(None, description="Which in-built layer was used: 'block' or 'compartment'")
    unit_count: Optional[int] = Field(None, description="Number of blocks/compartments the fieldbook was generated from")
    outer_points: Optional[int] = Field(None, description="Points on the forest's outer boundary (O1..)")
    internal_points: Optional[int] = Field(None, description="Points on internal boundaries (I1..)")
    junction_points: Optional[int] = Field(None, description="Points where 3 or more regions meet")


class FieldbookListResponse(BaseModel):
    """Response schema for listing fieldbook points"""
    points: list[FieldbookPoint]
    total_count: int


class FieldbookExportFormat(str):
    """Export format options"""
    CSV = "csv"
    EXCEL = "excel"
    GPX = "gpx"
    GEOJSON = "geojson"
