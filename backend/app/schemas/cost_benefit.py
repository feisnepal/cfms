"""Pydantic schemas for the Cost-Benefit Analysis module (CBA_MODULE_PLAN.md P0).

Mirrors ``app/models/cost_benefit.py``. ``Decimal`` throughout — no ``float`` into
the DB. ``*Update`` schemas are all-optional (``PATCH``-style ``model_dump(
exclude_unset=True)`` on the API side).
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# ── cost items ───────────────────────────────────────────────────────────────


class CBACostItemCreate(BaseModel):
    category: str = Field(..., max_length=200)
    description: str = ""
    year_from: int = Field(1, ge=1)
    year_to: int = Field(1, ge=1)
    amount_per_year: Decimal = Field(Decimal(0), ge=0)
    is_recurring: bool = False
    source_link: Optional[str] = None
    notes: Optional[str] = None
    display_order: int = 0


class CBACostItemUpdate(BaseModel):
    category: Optional[str] = None
    description: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    amount_per_year: Optional[Decimal] = None
    is_recurring: Optional[bool] = None
    source_link: Optional[str] = None
    notes: Optional[str] = None
    display_order: Optional[int] = None


class CBACostItemResponse(CBACostItemCreate):
    id: UUID
    cba_id: UUID
    total_amount: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── benefit items ────────────────────────────────────────────────────────────


class CBABenefitItemCreate(BaseModel):
    source: str = Field(..., max_length=50)
    description: str = ""
    year_from: int = Field(1, ge=1)
    year_to: int = Field(1, ge=1)
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    amount_per_year: Decimal = Field(Decimal(0), ge=0)
    is_recurring: bool = False
    source_link: Optional[str] = None
    notes: Optional[str] = None
    display_order: int = 0


class CBABenefitItemUpdate(BaseModel):
    source: Optional[str] = None
    description: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    amount_per_year: Optional[Decimal] = None
    is_recurring: Optional[bool] = None
    source_link: Optional[str] = None
    notes: Optional[str] = None
    display_order: Optional[int] = None


class CBABenefitItemResponse(CBABenefitItemCreate):
    id: UUID
    cba_id: UUID
    total_amount: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── scenario ─────────────────────────────────────────────────────────────────


class CBAScenarioCreate(BaseModel):
    name: str = "Base Scenario"
    description: Optional[str] = None
    discount_rate: Decimal = Field(Decimal("10.00"), ge=0, le=100)
    time_horizon_years: int = Field(10, ge=1, le=50)
    irr_start_year: int = Field(1, ge=1)
    currency: str = "NPR"
    default_rates: Dict = Field(default_factory=dict)


class CBAScenarioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    discount_rate: Optional[Decimal] = None
    time_horizon_years: Optional[int] = None
    irr_start_year: Optional[int] = None
    currency: Optional[str] = None
    default_rates: Optional[Dict] = None
    status: Optional[str] = None


class CBAResultResponse(BaseModel):
    npv: Optional[Decimal] = None
    irr: Optional[Decimal] = None
    benefit_cost_ratio: Optional[Decimal] = None
    payback_period_years: Optional[Decimal] = None
    total_cost_pv: Optional[Decimal] = None
    total_benefit_pv: Optional[Decimal] = None
    cash_flow_data: Optional[List] = None
    computed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CBAScenarioResponse(BaseModel):
    id: UUID
    calculation_id: UUID
    name: str
    description: Optional[str] = None
    discount_rate: Decimal
    time_horizon_years: int
    irr_start_year: int
    currency: str
    default_rates: Dict
    is_base_scenario: bool
    status: str
    cost_items: List[CBACostItemResponse] = []
    benefit_items: List[CBABenefitItemResponse] = []
    result: Optional[CBAResultResponse] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CBAScenarioListItem(BaseModel):
    id: UUID
    name: str
    is_base_scenario: bool
    status: str
    discount_rate: Decimal
    cost_count: int = 0
    benefit_count: int = 0
    has_result: bool = False
    npv: Optional[Decimal] = None
    irr: Optional[Decimal] = None
    benefit_cost_ratio: Optional[Decimal] = None
    payback_period_years: Optional[Decimal] = None
    created_at: datetime


# ── compare / re-populate / export ───────────────────────────────────────────


class CBACompareRequest(BaseModel):
    cba_ids: List[UUID] = Field(..., min_length=1)


class CBACompareItem(BaseModel):
    cba_id: UUID
    name: str
    npv: Optional[Decimal] = None
    irr: Optional[Decimal] = None
    benefit_cost_ratio: Optional[Decimal] = None
    payback_period_years: Optional[Decimal] = None
    total_cost: Optional[Decimal] = None
    total_benefit: Optional[Decimal] = None
    cost_count: int = 0
    benefit_count: int = 0


class CBARepopulateResponse(BaseModel):
    updated: Dict[str, int]
    inserted: Dict[str, int]
    deleted: Dict[str, int]
    message: str
    # e.g. a manual row named like an activity that is now also added automatically (never deleted)
    warnings: List[str] = []


class CBAExportData(BaseModel):
    base_npv: Optional[Decimal] = None
    base_irr: Optional[Decimal] = None
    base_bc_ratio: Optional[Decimal] = None
    base_payback: Optional[Decimal] = None
    summary_table: List = []
    cash_flow_table: List = []
    cost_breakdown: List = []
    benefit_breakdown: List = []


class CBACloneRequest(BaseModel):
    name: Optional[str] = None
