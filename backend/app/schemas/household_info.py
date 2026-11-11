"""
Pydantic schemas for Household Information
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal
from uuid import UUID


def normalize_classification(value):
    """The caste group is spelled "जनजाती" (owner, 2026-10-05); fold the old spelling "जनजाति" into it."""
    if isinstance(value, str):
        return value.strip().replace("जनजाति", "जनजाती") or None
    return value


# Base schema with common fields
class HouseholdInfoBase(BaseModel):
    """Base household information fields"""
    house_no: int = Field(..., description="House number", ge=1)
    surname: str = Field(..., min_length=1, max_length=100, description="Surname (थर)")
    household_head_male: Optional[str] = Field(None, max_length=200, description="Male household head name")
    household_head_female: Optional[str] = Field(None, max_length=200, description="Female household head name")
    address_tole: Optional[str] = Field(None, max_length=200, description="Address tole")
    latitude: Optional[Decimal] = Field(None, ge=-90, le=90, description="Latitude")
    longitude: Optional[Decimal] = Field(None, ge=-180, le=180, description="Longitude")

    # Population
    female_count: int = Field(0, ge=0, description="Number of females")
    male_count: int = Field(0, ge=0, description="Number of males")

    # Land & Occupation
    land_area: Optional[Decimal] = Field(None, ge=0, description="Land area")
    land_unit: Optional[str] = Field(None, description="Land unit (ropani/kaththa)")
    forest_based_occupation: bool = Field(False, description="Forest-based occupation")
    other_occupation: bool = Field(False, description="Other occupation")

    # Livestock
    cow_ox_count: int = Field(0, ge=0, description="Number of cows/oxen")
    buffalo_count: int = Field(0, ge=0, description="Number of buffaloes")
    goat_sheep_count: int = Field(0, ge=0, description="Number of goats/sheep")

    # Forest Product Demands
    timber_demand_cft: Decimal = Field(5, ge=0, description="Timber demand in cubic feet")
    pole_demand: int = Field(5, ge=0, description="Pole demand")
    firewood_demand_bhari: Optional[Decimal] = Field(None, ge=0, description="Firewood demand in bhari")
    grass_demand_bhari: Optional[Decimal] = Field(None, ge=0, description="Grass demand in bhari")
    bedding_demand_bhari: Optional[Decimal] = Field(None, ge=0, description="Bedding material demand in bhari")

    # Flags
    firewood_auto_calculated: bool = Field(True, description="Firewood auto-calculated flag")
    grass_auto_calculated: bool = Field(True, description="Grass auto-calculated flag")
    bedding_auto_calculated: bool = Field(True, description="Bedding auto-calculated flag")

    # Classification
    caste_classification_ne: Optional[str] = Field(None, max_length=100, description="Caste classification (Nepali)")

    @validator("caste_classification_ne", pre=True, allow_reuse=True)
    def _fold_janajati(cls, v):
        return normalize_classification(v)

    caste_classification_en: Optional[str] = Field(None, max_length=100, description="Caste classification (English)")
    caste_classification_manual: bool = Field(False, description="Manual classification override flag")

    # Other Info
    other_group_membership: Optional[bool] = Field(None, description="Other group membership")
    prosperity_level: str = Field('मध्यम', description="Prosperity level")
    prosperity_auto_suggested: bool = Field(True, description="Prosperity auto-suggested flag")
    remarks: Optional[str] = Field(None, description="Remarks")

    @validator('land_unit')
    def validate_land_unit(cls, v):
        if v and v not in ['ropani', 'kaththa']:
            raise ValueError("भूमि इकाइ 'रोपनी' वा 'कठ्ठा' हुनुपर्छ")
        return v

    @validator('prosperity_level')
    def validate_prosperity_level(cls, v):
        valid_levels = ['सम्पन्न', 'मध्यम', 'विपन्न', 'अति विपन्न']
        if v not in valid_levels:
            raise ValueError(f"समृद्धि स्तर 'सम्पन्न', 'मध्यम', 'विपन्न', वा 'अति विपन्न' हुनुपर्छ")
        return v


# Schema for creating household info
class HouseholdInfoCreate(HouseholdInfoBase):
    """Schema for creating household information"""
    pass


# Schema for updating household info
class HouseholdInfoUpdate(BaseModel):
    """Schema for updating household information (all fields optional)"""
    # H8.2 / S2-63. The version the client last read. Optional today because
    # the web frontend sends none; when absent the write proceeds unguarded and
    # is logged. `OPTIMISTIC_LOCK_REQUIRE_VERSION` makes it mandatory.
    version: Optional[int] = Field(
        None, ge=0,
        description="Record version you last read. Send it back to detect a "
                    "concurrent edit; a mismatch answers 409 with both versions.",
    )
    house_no: Optional[int] = Field(None, ge=1)
    surname: Optional[str] = Field(None, min_length=1, max_length=100)
    household_head_male: Optional[str] = Field(None, max_length=200)
    household_head_female: Optional[str] = Field(None, max_length=200)
    address_tole: Optional[str] = Field(None, max_length=200)
    latitude: Optional[Decimal] = Field(None, ge=-90, le=90)
    longitude: Optional[Decimal] = Field(None, ge=-180, le=180)
    female_count: Optional[int] = Field(None, ge=0)
    male_count: Optional[int] = Field(None, ge=0)
    land_area: Optional[Decimal] = Field(None, ge=0)
    land_unit: Optional[str] = None
    forest_based_occupation: Optional[bool] = None
    other_occupation: Optional[bool] = None
    cow_ox_count: Optional[int] = Field(None, ge=0)
    buffalo_count: Optional[int] = Field(None, ge=0)
    goat_sheep_count: Optional[int] = Field(None, ge=0)
    timber_demand_cft: Optional[Decimal] = Field(None, ge=0)
    pole_demand: Optional[int] = Field(None, ge=0)
    firewood_demand_bhari: Optional[Decimal] = Field(None, ge=0)
    grass_demand_bhari: Optional[Decimal] = Field(None, ge=0)
    bedding_demand_bhari: Optional[Decimal] = Field(None, ge=0)
    firewood_auto_calculated: Optional[bool] = None
    grass_auto_calculated: Optional[bool] = None
    bedding_auto_calculated: Optional[bool] = None
    caste_classification_ne: Optional[str] = Field(None, max_length=100)

    @validator("caste_classification_ne", pre=True, allow_reuse=True)
    def _fold_janajati(cls, v):
        return normalize_classification(v)

    caste_classification_en: Optional[str] = Field(None, max_length=100)
    caste_classification_manual: Optional[bool] = None
    other_group_membership: Optional[bool] = None
    prosperity_level: Optional[str] = None
    prosperity_auto_suggested: Optional[bool] = None
    remarks: Optional[str] = None


# Schema for response (includes computed fields and metadata)
class HouseholdInfoResponse(HouseholdInfoBase):
    """Schema for household information response"""
    id: UUID
    calculation_id: UUID
    # Returned so the client has a version to send back on its next write.
    # Without this the precondition is unusable: nobody can supply a version
    # they were never given.
    version: int = 0
    total_population: int = Field(..., description="Total population (computed)")
    created_at: datetime
    updated_at: datetime
    created_by: UUID

    class Config:
        from_attributes = True


# Schema for bulk upload validation result
class HouseholdUploadValidation(BaseModel):
    """Validation result for a single household row"""
    row_number: int
    is_valid: bool
    errors: List[str] = []
    warnings: List[str] = []
    data: Optional[dict] = None


class HouseholdUploadResponse(BaseModel):
    """Response for household upload"""
    success: bool
    total_rows: int
    valid_rows: int
    invalid_rows: int
    records_imported: int
    records_updated: int = 0  # Number of existing records updated
    records_removed: int = 0  # households removed by "replace the whole list" (owner decision D5)
    validations: List[HouseholdUploadValidation]
    # Problems grouped by cause, in both languages, each with how to fix it (services/upload/findings.py)
    findings: List[Dict[str, Any]] = []


# Schema for household summary statistics
class HouseholdSummary(BaseModel):
    """Summary statistics for household data"""
    total_households: int
    total_population: int
    total_male: int
    total_female: int
    total_cow_ox: int
    total_buffalo: int
    total_goat_sheep: int
    total_timber_demand_cft: Decimal
    total_pole_demand: int
    total_firewood_demand_bhari: Decimal
    total_grass_demand_bhari: Decimal
    total_bedding_demand_bhari: Decimal
    avg_land_area: Optional[Decimal] = None
    caste_distribution: dict  # {classification: count}
    prosperity_distribution: dict  # {level: count}
    forest_dependent_households: int
    source: Optional[str] = None  # 'households' | 'summary'


# Schema for caste lookup
class CasteClassificationResponse(BaseModel):
    """Response for caste classification lookup"""
    classification_ne: str
    classification_en: Optional[str] = None
    caste_ne: str
    caste_en: Optional[str] = None
    surname_ne: str
    surname_en: Optional[str] = None

    class Config:
        from_attributes = True


# Schema for surname suggestions
class SurnameSuggestion(BaseModel):
    """Surname suggestion for autocomplete"""
    surname_ne: str
    surname_en: Optional[str] = None
    classification_ne: str
    caste_ne: str


# Schema for template download options
class TemplateDownloadOptions(BaseModel):
    """Options for downloading household template"""
    land_unit: str = Field('ropani', description="Land unit (ropani/kaththa)")
    include_coordinates: bool = Field(False, description="Include coordinate columns")

    @validator('land_unit')
    def validate_land_unit(cls, v):
        if v not in ['ropani', 'kaththa']:
            raise ValueError("भूमि इकाइ 'रोपनी' वा 'कठ्ठा' हुनुपर्छ")
        return v


class HouseholdSummaryInput(BaseModel):
    """Totals typed by the user when there is no household-wise data."""
    total_households: int = Field(..., ge=1)
    male_count: int = Field(0, ge=0)
    female_count: int = Field(0, ge=0)
    forest_occupation_households: int = Field(0, ge=0)
    other_occupation_households: int = Field(0, ge=0)
    cow_ox_count: int = Field(0, ge=0)
    buffalo_count: int = Field(0, ge=0)
    goat_sheep_count: int = Field(0, ge=0)
    avg_land_area: Optional[Decimal] = Field(None, ge=0)
    land_unit: Optional[str] = None
    # Auto-calculated by default; the five typed totals are used only when this is false.
    demands_auto_calculated: bool = True
    timber_demand_cft: Optional[Decimal] = Field(None, ge=0)
    pole_demand: Optional[int] = Field(None, ge=0)
    firewood_demand_bhari: Optional[Decimal] = Field(None, ge=0)
    grass_demand_bhari: Optional[Decimal] = Field(None, ge=0)
    bedding_demand_bhari: Optional[Decimal] = Field(None, ge=0)
    caste_distribution: dict = Field(default_factory=dict)       # {classification: households}
    prosperity_distribution: dict = Field(default_factory=dict)  # {level: households}

    @validator("caste_distribution", pre=True)
    def _fold_caste_keys(cls, v):
        if not isinstance(v, dict):
            return v
        out: dict = {}
        for k, n in v.items():
            k = normalize_classification(k) or k
            out[k] = (out[k] + n) if k in out and isinstance(n, int) and isinstance(out[k], int) else n
        return out

    @validator("caste_distribution", "prosperity_distribution")
    def _counts_non_negative(cls, v):
        for k, n in v.items():
            if not isinstance(n, int) or isinstance(n, bool) or n < 0:
                raise ValueError(f"'{k}' must be a whole number of households, 0 or more")
        return v


class HouseholdSummaryOut(HouseholdSummaryInput):
    total_households: int
    warnings: List[str] = []
