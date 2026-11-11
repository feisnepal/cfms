"""
Pydantic schemas for compartment management
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from uuid import UUID
from datetime import datetime
from ..services.forest_units.model import DEPTH_TOP_COMPARTMENT


# NEW: Request Schemas for hierarchy support

class RenameBlockRequest(BaseModel):
    """Request to rename any block/compartment/sub-compartment"""
    new_name: str = Field(..., min_length=1, max_length=255)

    class Config:
        json_schema_extra = {
            "example": {
                "new_name": "North-East Patch"
            }
        }


class SubDivideRequest(BaseModel):
    """Request to create sub-compartments"""
    method: Literal["parallel", "grid", "custom"]
    parameters: Dict[str, Any]
    naming_pattern: str = Field(default="{parent_name}-S{index}")
    reassign_trees: bool = Field(default=True)
    notes: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "method": "parallel",
                "parameters": {
                    "direction_angle": 90,
                    "num_compartments": 3
                },
                "naming_pattern": "{parent_name}-S{index}"
            }
        }


# NEW: Response Schemas for hierarchical tree

class CompartmentTreeNode(BaseModel):
    """Tree node for hierarchical display"""
    id: UUID
    name: str
    area_hectares: float
    area_sqm: float
    division_level: int = DEPTH_TOP_COMPARTMENT  # top-level default (blocks and compartments both start at 1, migration 094)
    color: Optional[str] = None
    is_locked: bool = False
    child_count: int = 0
    is_compartment: bool = False
    compartment_code: Optional[str] = None
    children: List['CompartmentTreeNode'] = []

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "B1-C1",
                "area_hectares": 65.42,
                "area_sqm": 654200.0,
                "division_level": 1,
                "color": "#33FF57",
                "is_locked": False,
                "child_count": 3,
                "children": []
            }
        }


class CompartmentTreeResponse(BaseModel):
    """Full tree response"""
    blocks: List[CompartmentTreeNode]
    total_area_hectares: float
    total_compartments: int
    total_sub_compartments: int = 0
    # 'block' | 'compartment' | 'undecided' - the branch of the structure rule this forest uses (forest_units).
    stream: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "blocks": [],
                "total_area_hectares": 1000.5,
                "total_compartments": 12,
                "total_sub_compartments": 36
            }
        }


# Request Schemas

class SplitPreviewRequest(BaseModel):
    """Request to preview compartment split"""
    block_id: UUID
    method: Literal["parallel", "grid", "custom"]
    parameters: Dict[str, Any]

    class Config:
        json_schema_extra = {
            "example": {
                "block_id": "123e4567-e89b-12d3-a456-426614174000",
                "method": "parallel",
                "parameters": {
                    "direction_angle": 90,
                    "num_compartments": 5,
                    "min_area_sqm": 1000,
                    "max_deviation_percent": 10
                }
            }
        }


class ExecuteSplitRequest(BaseModel):
    """Request to execute compartment split"""
    block_id: UUID
    method: Literal["parallel", "grid", "custom"]
    parameters: Dict[str, Any]
    naming_pattern: str = Field(default="{block_name}-C{index}")
    reassign_trees: bool = Field(default=True, description="Auto-assign existing trees by GPS location")
    notes: Optional[str] = None


# Response Schemas

class CompartmentPreview(BaseModel):
    """Preview of a single compartment"""
    index: int
    name: str
    geometry: Dict[str, Any]  # GeoJSON
    area_sqm: float
    area_hectares: float
    area_deviation_percent: float
    tree_count: int
    perimeter_m: Optional[float] = None


class SplitValidation(BaseModel):
    """Validation results for split operation"""
    is_valid: bool
    warnings: List[str] = []
    errors: List[str] = []
    total_area_match: bool


class SplitPreviewResponse(BaseModel):
    """Response for split preview"""
    compartments: List[CompartmentPreview]
    validation: SplitValidation
    total_area_sqm: float
    parent_block_name: str


class ExecuteSplitResponse(BaseModel):
    """Response for executed split"""
    split_history_id: UUID
    compartments_created: List[UUID]
    trees_reassigned: int
    success: bool
    message: str


# Info Schemas

class SplitDirection(BaseModel):
    """Preset splitting direction"""
    name: str
    angle: Optional[float]
    description: Optional[str] = None


class AvailableBlock(BaseModel):
    """Forest block available for splitting"""
    id: UUID
    name: str
    area_sqm: float
    area_hectares: float
    geometry: Dict[str, Any]
    has_compartments: bool
    tree_count: int
    compartment_count: int = 0
    total_trees_in_calculation: int = 0


# Tree Reassignment Schemas

class TreeReassignmentPreview(BaseModel):
    """Preview of tree reassignment"""
    tree_id: UUID
    species: str
    location: Dict[str, float]  # {"lat": ..., "lon": ...}
    suggested_compartment_id: Optional[UUID]
    suggested_compartment_name: Optional[str]


class TreeReassignmentRequest(BaseModel):
    """Request to reassign trees"""
    block_id: UUID
    auto_assign: bool = True
    manual_assignments: Optional[Dict[UUID, UUID]] = None  # tree_id -> compartment_id


class TreeReassignmentResponse(BaseModel):
    """Response for tree reassignment"""
    success: bool
    trees_assigned: int
    trees_unassigned: int
    assignments_by_compartment: Dict[str, Dict[str, Any]]  # compartment_id -> {name, count}
