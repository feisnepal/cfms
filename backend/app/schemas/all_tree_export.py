"""
Pydantic schemas for All Tree Export
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID


class AllTreeExportConfigBase(BaseModel):
    """Configuration for all-tree export generation"""
    min_dbh_cm: float = Field(default=10.0, ge=5.0, le=50.0, description="Minimum DBH in centimeters")
    max_dbh_cm: Optional[float] = Field(default=None, ge=10.0, le=200.0, description="Maximum DBH in centimeters (optional)")
    min_height_m: float = Field(default=5.0, ge=2.0, le=20.0, description="Minimum height in meters")
    max_trees_per_ha: int = Field(default=1000, ge=50, le=5000, description="Maximum trees per hectare cap")
    algorithm_version: str = Field(default="v1.0", description="Algorithm version to use")

    species_role_target_ratio: Optional[Dict[str, float]] = Field(
        default=None,
        description=(
            "Optional target ratio for species roles. "
            "Example: {'dominant': 0.50, 'co-dominant': 0.30, 'associate': 0.15, 'occasional': 0.04, 'rare': 0.01}. "
            "When null, uses database rank-based weighting."
        )
    )

    @field_validator('species_role_target_ratio')
    @classmethod
    def validate_ratio(cls, v):
        if v is None:
            return v
        valid_roles = {'dominant', 'co-dominant', 'associate', 'occasional', 'rare'}
        provided_roles = set(v.keys())
        if not provided_roles.issubset(valid_roles):
            raise ValueError(f"INVALID_ROLES: अमान्य भूमिकाहरू: {provided_roles - valid_roles}. मान्य: {valid_roles}")
        total = sum(v.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"RATIO_SUM_INVALID: अनुपातको योग १.० हुनुपर्छ, प्राप्त: {total}")
        return v


class GenerateAllTreesRequest(BaseModel):
    """Request to generate all-tree export"""
    config: Optional[AllTreeExportConfigBase] = Field(default=None, description="Optional configuration, uses defaults if not provided")
    unit_ids: Optional[List[UUID]] = Field(
        default=None,
        description=(
            "forest_blocks ids (block / sub-block / compartment / sub-compartment) to limit the "
            "export to. Omitted or empty = the whole forest boundary."
        ),
    )


class AllTreeExportStatistics(BaseModel):
    """Statistics about generated all-tree export"""
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
    block_wise_stats: Optional[Dict[str, Any]] = None
    dbh_class_distribution: Optional[Dict[str, int]] = None
    species_role_distribution: Optional[Dict[str, int]] = None


class AllTreeExportResponse(BaseModel):
    """Response for all-tree export"""
    id: UUID
    calculation_id: UUID
    user_id: UUID
    model_type: str
    model_version: str
    algorithm_config: Dict[str, Any]

    total_trees: Optional[int] = None
    area_hectares: Optional[float] = None
    trees_per_hectare: Optional[float] = None
    min_dbh_cm: Optional[float] = None
    max_dbh_cm: Optional[float] = None
    min_height_m: Optional[float] = None
    max_height_m: Optional[float] = None

    gpkg_filename: Optional[str] = None
    gpkg_size_mb: Optional[float] = None
    excel_filename: Optional[str] = None
    excel_size_mb: Optional[float] = None
    csv_filename: Optional[str] = None
    csv_size_mb: Optional[float] = None

    status: str
    progress_percent: Optional[int] = 0
    current_step: Optional[str] = None
    error_message: Optional[str] = None

    created_at: datetime
    completed_at: Optional[datetime] = None
    processing_time_seconds: Optional[int] = None
    # Exports are deleted one hour after they finish; None while still running
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AllTreeExportListResponse(BaseModel):
    """List of all-tree exports"""
    exports: List[AllTreeExportResponse]
    total_count: int
