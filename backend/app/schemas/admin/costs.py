"""Schemas for super-admin cost aggregation endpoints."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ForestCostRow(BaseModel):
    forest_name: str
    calculation_count: int
    total_cpu_seconds: float
    total_peak_memory_mb: float  # CUMULATIVE sum of each calc's peak (not simultaneous)
    total_cpu_cost: float
    total_memory_cost: float
    total_cost: float
    currency: Optional[str] = None
    last_run_at: Optional[datetime] = None


class ForestCostsResponse(BaseModel):
    rows: list[ForestCostRow]
    grand_total: float
    currency: Optional[str] = None
