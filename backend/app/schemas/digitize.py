"""Pydantic schemas for the on-screen digitizing API (GD Phase 1.2)."""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class DraftStatus(str, Enum):
    ACTIVE = "active"
    SYNCING = "syncing"
    VALIDATION_FAILED = "validation_failed"
    FINALIZED = "finalized"
    DISCARDED = "discarded"


class DigitizeLayerCreate(BaseModel):
    purpose: str = Field(..., description="One of the 8 import purposes")
    name: str = Field(..., min_length=1, max_length=255)


class DigitizeLayerResponse(BaseModel):
    id: int
    name: str
    purpose: str
    draft_status: Optional[DraftStatus] = None
    feature_count: int
    geometry_types: List[str] = []
    is_draft: bool


class FeaturePayload(BaseModel):
    """A single feature in a bulk upsert/delete request.

    `clientTempId` correlates the response mapping with the frontend buffer;
    the server assigns the final `featureId` (Gap 1.4). For `delete`
    operations, `clientTempId` is the featureId to delete and `feature` is
    optional (ignored).
    """
    clientTempId: str = Field(..., description="Client-generated correlation id")
    feature: Optional[Dict[str, Any]] = Field(
        None, description="GeoJSON Feature (required for upsert)"
    )
    operation: Literal["upsert", "delete"] = "upsert"


class FeatureBulkRequest(BaseModel):
    features: List[FeaturePayload] = Field(..., min_length=1, max_length=50)
    idempotency_key: Optional[str] = Field(None, description="UUID for retry dedup")
    mode: Literal["draft", "append"] = Field(
        "draft",
        description=(
            "draft: features flush into an active draft layer (draft_status active/syncing). "
            "append: features are appended to an existing non-draft layer (finalized or legacy "
            "import); subject to the map lifecycle lock."
        ),
    )


class FeatureBulkResponse(BaseModel):
    mapping: Dict[str, str] = Field(..., description="clientTempId → server featureId")
    feature_count: int


class FinalizeRequest(BaseModel):
    idempotency_key: Optional[str] = Field(None, description="UUID for retry dedup")


class FinalizeAcceptedResponse(BaseModel):
    task_id: str
    status: Literal["queued", "processing"]
    poll_interval_s: int = 2


class FinalizeStatusResponse(BaseModel):
    status: Literal["queued", "processing", "succeeded", "validation_failed", "failed"]
    last_validation_error: Optional[Dict[str, Any]] = None
    feature_count: Optional[int] = None
    geometry_types: Optional[List[str]] = None
    draft_status: Optional[DraftStatus] = None
