from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Any


class CalculationProgressResponse(BaseModel):
    id: UUID
    calculation_id: UUID
    current_step: str
    step_label: str | None
    step_index: int
    total_steps: int
    percent: float
    message: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CostEstimateResponse(BaseModel):
    cpu_seconds: float
    peak_memory_mb: float
    cpu_cost: float
    memory_cost: float
    total_cost: float
    currency: str
    rates_applied: dict[str, Any] | None = None
    computed_at: str | None = None


class ProgressWithCostResponse(BaseModel):
    progress: CalculationProgressResponse | None
    cost_estimate: CostEstimateResponse | None
    map_lifecycle_status: str
