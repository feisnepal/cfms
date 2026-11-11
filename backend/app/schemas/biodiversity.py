"""
Pydantic schemas for biodiversity species
"""
from pydantic import BaseModel, UUID4, Field
from typing import Optional, List
from datetime import datetime
from decimal import Decimal


# Base schemas
class BiodiversitySpeciesBase(BaseModel):
    """Base schema for biodiversity species"""
    category: str = Field(..., max_length=50, description="Main category: vegetation, animal")
    sub_category: Optional[str] = Field(None, max_length=50, description="Sub-category: tree, mammal, bird, etc.")
    nepali_name: str = Field(..., max_length=255)
    english_name: str = Field(..., max_length=255)
    scientific_name: str = Field(..., max_length=255)
    primary_use: Optional[str] = Field(None, max_length=100)
    secondary_uses: Optional[str] = None
    iucn_status: Optional[str] = Field(None, max_length=10)
    cites_appendix: Optional[str] = Field(None, max_length=20)
    distribution: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    is_invasive: bool = False
    is_protected: bool = False


class BiodiversitySpeciesCreate(BiodiversitySpeciesBase):
    """Schema for creating species (admin only)"""
    pass


class BiodiversitySpeciesResponse(BiodiversitySpeciesBase):
    """Schema for species response"""
    id: UUID4
    created_at: datetime

    class Config:
        from_attributes = True


class BiodiversitySpeciesListResponse(BaseModel):
    """Paginated species list response"""
    items: List[BiodiversitySpeciesResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# Calculation Biodiversity schemas
class CalculationBiodiversityBase(BaseModel):
    """Base schema for calculation biodiversity selection"""
    species_id: UUID4
    presence_status: str = Field("present", max_length=20)
    abundance: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None
    photo_url: Optional[str] = Field(None, max_length=500)
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None


class CalculationBiodiversityCreate(CalculationBiodiversityBase):
    """Schema for creating biodiversity record"""
    pass


class CalculationBiodiversityBulkCreate(BaseModel):
    """Schema for bulk creating biodiversity records"""
    species_ids: List[UUID4] = Field(..., description="List of species IDs to add")
    presence_status: str = Field("present", max_length=20)
    notes: Optional[str] = None


class CalculationBiodiversityUpdate(BaseModel):
    """Schema for updating biodiversity record"""
    presence_status: Optional[str] = Field(None, max_length=20)
    abundance: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None
    photo_url: Optional[str] = Field(None, max_length=500)
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None


class CalculationBiodiversityResponse(CalculationBiodiversityBase):
    """Schema for biodiversity record response"""
    id: UUID4
    calculation_id: UUID4
    recorded_by: Optional[UUID4]
    recorded_at: datetime
    species: BiodiversitySpeciesResponse

    class Config:
        from_attributes = True


class CalculationBiodiversitySummary(BaseModel):
    """Summary of biodiversity for a calculation"""
    calculation_id: UUID4
    total_species: int
    vegetation_count: int
    animal_count: int
    protected_species_count: int
    invasive_species_count: int
    species: List[CalculationBiodiversityResponse]


# Filter schemas
class SpeciesFilterParams(BaseModel):
    """Query parameters for filtering species"""
    category: Optional[str] = None
    sub_category: Optional[str] = None
    search: Optional[str] = None
    iucn_status: Optional[str] = None
    cites_listed: Optional[bool] = None
    is_invasive: Optional[bool] = None
    is_protected: Optional[bool] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)


# Preset schemas
class SpeciesPreset(BaseModel):
    """Predefined species sets for quick selection"""
    name: str
    description: str
    species_ids: List[UUID4]


class SpeciesPresetResponse(BaseModel):
    """Available presets response"""
    presets: List[SpeciesPreset]
