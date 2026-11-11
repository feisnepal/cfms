"""Request / response schemas of the calculation-scoped yearly plan facade
(YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.1)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from .yearly_activities import CalculationDrawnFeatureResponse


def _check_years(values: Optional[List[int]]) -> Optional[List[int]]:
    if values is None:
        return values
    clean = sorted({int(v) for v in values})
    if any(y < 1 or y > 10 for y in clean):
        raise ValueError("years must be between 1 and 10")
    return clean


class ActivityFeatureCreate(BaseModel):
    """Draw a place for an activity. The plan line is found or created in the same transaction."""

    potential_activity_id: int
    feature_type: str = Field(..., pattern="^(point|line|polygon)$")
    geometry: str  # GeoJSON string, like the legacy route
    name: Optional[str] = None
    years: List[int] = Field(default_factory=lambda: [1])
    kind: Optional[str] = None
    # the user's numbers (the wizard); absent for a raw draw, which creates the line unreviewed
    quantity: Optional[Decimal] = Field(None, gt=0)
    budget: Optional[Decimal] = Field(None, ge=0)
    # "plan this year too": give the chosen years the line's default values when they are unplanned
    plan_years: bool = False

    _years = field_validator("years")(_check_years)


class ActivityFeatureUpdate(BaseModel):
    name: Optional[str] = None
    years: Optional[List[int]] = None
    kind: Optional[str] = None
    potential_activity_id: Optional[int] = None  # move to another activity (D5)
    plan_years: bool = False

    _years = field_validator("years")(_check_years)


class YearItem(BaseModel):
    year: int = Field(..., ge=1, le=10)
    quantity: Optional[Decimal] = Field(None, ge=0)
    budget: Optional[Decimal] = Field(None, ge=0)


class PlanLineUpdate(BaseModel):
    """One all-or-nothing edit of a plan line's numbers (the Plan table and the legacy Save)."""

    default_quantity: Optional[Decimal] = Field(None, gt=0)
    default_yearly_budget: Optional[Decimal] = Field(None, ge=0)
    years: List[YearItem] = Field(default_factory=list)
    notes: Optional[str] = None
    status: Optional[str] = None
    expected_version: Optional[int] = None
    # Undo: put the line back to "not reviewed" (it was, before the edit being undone). The numbers themselves are
    # restored by sending them; this only clears the flag that no other edit can clear.
    unreview: bool = False


class PlanLineCreate(BaseModel):
    """Add an activity to the plan without drawing a place (the wizard: an activity that needs no map,
    "applies to the whole forest", or a place to be decided later). The user's numbers are given, so the
    line is created reviewed."""

    potential_activity_id: int
    years: List[int] = Field(default_factory=lambda: [1])
    quantity: Optional[Decimal] = Field(None, gt=0)
    budget: Optional[Decimal] = Field(None, ge=0)
    # "different each year": explicit numbers for individual years (others keep quantity / budget)
    year_values: List[YearItem] = Field(default_factory=list)
    whole_forest: bool = False

    _years = field_validator("years")(_check_years)


class PlanLineCreated(BaseModel):
    plan_line: Dict[str, Any]
    created_plan_line: bool
    unit: Optional[str] = None


class PlanLineConfirm(BaseModel):
    expected_version: Optional[int] = None


class ActivityFeatureOut(CalculationDrawnFeatureResponse):
    """A feature with its derived location and the measured quantity for its activity's unit."""

    block_names: List[str] = Field(default_factory=list)
    sub_area_names: List[str] = Field(default_factory=list)


class ActivityFeatureCreated(BaseModel):
    feature: ActivityFeatureOut
    plan_line: Dict[str, Any]
    created_plan_line: bool
    created_year_rows: List[int]
    planned_years_added: List[int]
    measured_quantity: Optional[Decimal] = None
    unit: Optional[str] = None


class PlanLineResult(BaseModel):
    plan_line: Dict[str, Any]
    filled_years: List[int] = Field(default_factory=list)
