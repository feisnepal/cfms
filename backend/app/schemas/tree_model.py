"""
Pydantic schemas for synthetic tree distribution models
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID


class TreeModelConfigBase(BaseModel):
    """Base configuration for tree model generation"""
    min_dbh_cm: float = Field(default=10.0, ge=5.0, le=50.0, description="Minimum DBH in centimeters")
    min_height_m: float = Field(default=5.0, ge=2.0, le=20.0, description="Minimum height in meters")
    max_trees_per_ha: int = Field(default=1000, ge=50, le=5000, description="Maximum trees per hectare cap")
    spatial_distribution: str = Field(default="random", description="Spatial distribution pattern: random, clustered, regular")
    plot_buffer_meters: float = Field(default=25.0, ge=5.0, le=100.0, description="Buffer distance around sample plots in meters")
    algorithm_version: str = Field(default="v1.0", description="Algorithm version to use")

    @field_validator('spatial_distribution')
    @classmethod
    def validate_distribution(cls, v):
        allowed = ['random', 'clustered', 'regular']
        if v not in allowed:
            raise ValueError(f"INVALID_DISTRIBUTION: spatial_distribution {allowed} मध्ये एक हुनुपर्छ")
        return v


class GenerateTreeModelRequest(BaseModel):
    """Request to generate synthetic tree distribution"""
    config: Optional[TreeModelConfigBase] = Field(default=None, description="Optional configuration, uses defaults if not provided")


class TreeModelStatistics(BaseModel):
    """Statistics about generated tree model"""
    total_trees: int
    area_hectares: float
    trees_per_hectare: float
    min_dbh_cm: Optional[float] = None
    max_dbh_cm: Optional[float] = None
    mean_dbh_cm: Optional[float] = None
    min_height_m: Optional[float] = None
    max_height_m: Optional[float] = None
    mean_height_m: Optional[float] = None
    species_count: Optional[int] = None
    dominant_species: Optional[list[str]] = None


class TreeModelResponse(BaseModel):
    """Response for tree model generation"""
    id: UUID
    calculation_id: UUID
    user_id: UUID
    model_version: str
    algorithm_config: Dict[str, Any]

    # Statistics
    total_trees: Optional[int] = None
    area_hectares: Optional[float] = None
    trees_per_hectare: Optional[float] = None
    min_dbh_cm: Optional[float] = None
    max_dbh_cm: Optional[float] = None
    min_height_m: Optional[float] = None
    max_height_m: Optional[float] = None

    # File info
    gpkg_filename: Optional[str] = None
    file_size_mb: Optional[float] = None
    excel_filename: Optional[str] = None
    excel_size_mb: Optional[float] = None

    # Status
    status: str
    progress_percent: Optional[int] = 0
    current_step: Optional[str] = None
    error_message: Optional[str] = None

    # Timestamps
    created_at: datetime
    completed_at: Optional[datetime] = None
    processing_time_seconds: Optional[int] = None

    class Config:
        from_attributes = True


class TreeModelListResponse(BaseModel):
    """List of tree models"""
    models: list[TreeModelResponse]
    total_count: int


class TreeModelProgressUpdate(BaseModel):
    """Progress update for tree model generation"""
    model_id: UUID
    status: str
    progress_percent: int
    current_step: str
    estimated_time_remaining_seconds: Optional[int] = None

