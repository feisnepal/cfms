"""Pydantic schemas for the boundary overlap system (S11)."""

from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field


class BoundaryStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    APPROVED = "approved"
    DISPUTED = "disputed"


class OverlapMethod(str, Enum):
    UPLOAD = "upload"
    DIGITIZE = "digitize"
    POINTS = "points"


class BoundaryStatusUpdate(BaseModel):
    status: BoundaryStatus
    reason: Optional[str] = None


class BoundaryStatusResponse(BaseModel):
    id: UUID
    boundary_status: BoundaryStatus
    boundary_status_changed_at: Optional[datetime]
    boundary_status_changed_by: Optional[UUID]
    boundary_geom_updated_at: Optional[datetime]


class PreviewRequest(BaseModel):
    geometry: Dict[str, Any] = Field(..., description="GeoJSON geometry")
    method: OverlapMethod
    forest_id: Optional[UUID] = None


class OverlappingForest(BaseModel):
    id: UUID
    name: Optional[str]
    name_np: Optional[str] = None
    overlap_ha: Decimal
    forest_area_ha: Decimal
    gap_ha: Decimal = Decimal("0")
    gap_shape: str = "none"
    gap_size: str = "none"
    gap_width_m: Decimal = Decimal("0")
    gap_action: str = "report"  # "snap" | "absorb" | "offer" | "report"
    adjacent: bool = True
    geometry: Optional[Dict[str, Any]] = None


class GapForest(BaseModel):
    """A relationship where the proposed boundary leaves an unclaimed GAP to an
    adjoining forest (a shared-edge puzzle that flags, never auto-absorbs)."""

    id: UUID
    name: Optional[str]
    name_np: Optional[str] = None
    overlap_ha: Decimal = Decimal("0")
    gap_ha: Decimal
    gap_shape: str  # "none" | "ribbon" | "island" | "mixed"
    gap_size: str  # "none" | "small" | "medium" | "large"
    gap_width_m: Decimal = Decimal("0")  # medial (narrow) width of the strip
    gap_action: str = "offer"  # "snap" | "absorb" | "offer" | "report"
    gap_geometry: Optional[Dict[str, Any]] = None
    adjacent: bool = True
    geometry: Optional[Dict[str, Any]] = None


class PreviewResponse(BaseModel):
    status: str
    orig_area_ha: Decimal
    resolved_area_ha: Decimal
    removed_ha: Decimal
    removed_pct: Decimal
    requires_confirmation: bool
    reason: Optional[str] = None
    overlapping_forests: List[OverlappingForest] = []
    gaps: List[GapForest] = []
    gap_total_ha: Decimal = Decimal("0")
    resolved_geometry: Optional[Dict[str, Any]] = None
    original_geometry: Optional[Dict[str, Any]] = None
    warnings: List[str] = []


class ConfirmRequest(BaseModel):
    resolved_geometry: Dict[str, Any]
    original_geometry: Dict[str, Any]
    forest_name: str
    forest_name_np: Optional[str] = None
    mode: str = "compartment"
    forest_group_id: Optional[int] = None
    method: OverlapMethod = OverlapMethod.DIGITIZE
    #: When set (PF-3 edit/reshape path), persist onto the existing calculation
    #: instead of creating a new one — keeps an on-map boundary edit/vertex move
    #: on the SAME calculation id rather than duplicating the forest.
    calculation_id: Optional[UUID] = None
    forest_id: Optional[UUID] = None


class ConfirmResponse(BaseModel):
    id: UUID
    boundary_status: BoundaryStatus
    boundary_geom_updated_at: Optional[datetime]
    audit_id: int


class PointsPreviewRequest(BaseModel):
    points: List[Dict[str, float]] = Field(..., description="List of {lat, lng} points")


class GapRow(BaseModel):
    forest_id: UUID
    gap_ha: Decimal = Decimal("0")


class IncludeGapRequest(BaseModel):
    """Persist the full resolved proposed boundary (the user chose to include one
    or more gaps into this CF). ``geometry`` is the FULL proposed polygon already
    extended by the chosen gap(s); ``gaps`` records which neighbour gaps were
    included for the audit trail."""

    geometry: Dict[str, Any] = Field(
        ..., description="Full resolved proposed boundary GeoJSON"
    )
    original_geometry: Dict[str, Any] = Field(
        ..., description="Original (pre-include) boundary GeoJSON"
    )
    forest_name: str
    forest_name_np: Optional[str] = None
    method: OverlapMethod = OverlapMethod.DIGITIZE
    calculation_id: Optional[UUID] = None
    forest_id: Optional[UUID] = None
    gaps: List[GapRow] = []


class IncludeGapResponse(BaseModel):
    id: UUID
    boundary_status: BoundaryStatus
    boundary_geom_updated_at: Optional[datetime]
    audit_id: int
    gap_included_ha: Decimal


class NearbyRelation(BaseModel):
    id: UUID
    name: str
    boundary_status: str
    geometry: Optional[Dict[str, Any]] = None
    area_ha: Decimal = Decimal("0")
    overlap_ha: Decimal = Decimal("0")
    gap_ha: Decimal = Decimal("0")
    gap_shape: str = "none"
    gap_size: str = "none"
    adjacent: bool = False


class DisputeFileRequest(BaseModel):
    forest_id: UUID
    reason_np: str = Field(..., min_length=10)
    dispute_reason_type: str = "overlap"  # "overlap" | "gap"


class DisputeResponse(BaseModel):
    dispute_id: int
    status: str


class DisputeDetail(BaseModel):
    id: int
    forest_id_1: UUID
    forest_id_2: UUID
    dispute_reason_np: str
    status: str
    forest_1_boundary: Optional[Dict[str, Any]] = None
    forest_2_proposed: Optional[Dict[str, Any]] = None
    forest_2_clipped: Optional[Dict[str, Any]] = None
    overlap_area: Optional[Dict[str, Any]] = None
    gap_geometry: Optional[Dict[str, Any]] = None
    dispute_reason_type: Optional[str] = "overlap"
    created_at: datetime
    updated_at: datetime
    assigned_to_dfo_id: Optional[UUID] = None
    resolution_type: Optional[str] = None
    resolution_notes_np: Optional[str] = None


class DisputeResolveRequest(BaseModel):
    forest_id: UUID
    new_boundary: Dict[str, Any]
    reason_np: str = Field(..., min_length=10)
    resolution_type: str = Field(
        ..., pattern=r"^(edit_forest_1|edit_forest_2|dismiss)$"
    )


class DisputeResolveResponse(BaseModel):
    dispute_id: int
    status: str
    forest_1_status: BoundaryStatus
    forest_2_status: BoundaryStatus


class BoundaryAuditEntry(BaseModel):
    id: int
    forest_id: UUID
    submitted_area_ha: Optional[Decimal]
    resolved_area_ha: Optional[Decimal]
    overlap_removed_ha: Optional[Decimal]
    overlap_with_forest_ids: Optional[List[UUID]]
    resolution_method: Optional[str]
    user_confirmed: bool
    dispute_id: Optional[int]
    dfo_reason_np: Optional[str]
    gap_included_ha: Optional[Decimal] = None
    gap_forest_ids: Optional[List[str]] = None
    dispute_reason_type: Optional[str] = None
    created_at: datetime


class AuditListResponse(BaseModel):
    audits: List[BoundaryAuditEntry]
    total: int
    limit: int
    offset: int


class BoundaryLegendItem(BaseModel):
    status: str
    color: str
    label: str
    label_np: str
