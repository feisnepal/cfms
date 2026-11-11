"""
Pydantic schemas for yearly activities
"""
import logging
from pydantic import BaseModel, Field, validator, model_validator
from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID
from decimal import Decimal
import json

from app.services.yearly_plan_rules import total_budget

logger = logging.getLogger(__name__)


# ===== POTENTIAL ACTIVITIES (Master List) =====

class PotentialActivityBase(BaseModel):
    """Base schema for potential activity fields."""
    project_name: Optional[str] = None
    program: Optional[str] = None
    activity: Optional[str] = None
    description: Optional[str] = None
    unit: Optional[str] = None
    quantity: Optional[str] = None  # Original varchar field
    yearly_budget: Optional[str] = None  # Original varchar field
    is_default: Optional[str] = None  # Original varchar field
    display_order: int = 0
    is_active: bool = True


class PotentialActivityResponse(BaseModel):
    """Response schema for potential activity master list."""
    id: int
    sn: Optional[str] = None
    project_name: Optional[str] = None
    program: Optional[str] = None  # Maps to progarms (with typo)
    activity: Optional[str] = None  # Maps to activities
    description: Optional[str] = None
    unit: Optional[str] = None
    quantity: Optional[str] = None
    yearly_budget: Optional[str] = None
    is_default: Optional[str] = None
    display_order: int = 0
    is_active: bool = True
    requires_map: bool = False  # NEW: Map-able activities
    # Finding an activity (YEARLY_ACTIVITIES_WORKSPACE_PLAN §4.11): default map symbol, English name and
    # extra search words. All nullable; the picker works on the Nepali name alone.
    map_kind: Optional[str] = None
    map_geom: Optional[str] = None  # point | line | polygon when the activity overrides its kind's shape
    name_en: Optional[str] = None
    search_terms: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj):
        """Custom from_orm to handle field name mapping"""
        data = {
            "id": obj.id,
            "sn": obj.sn,
            "project_name": obj.project_name,
            "program": obj.progarms,  # Map progarms to program
            "activity": obj.activities,  # Map activities to activity
            "description": obj.description,
            "unit": obj.unit,
            "quantity": obj.quantity,
            "yearly_budget": obj.yearly_budget,
            "is_default": obj.is_default,
            "display_order": obj.display_order,
            "is_active": obj.is_active,
            "requires_map": getattr(obj, 'requires_map', False),
            "map_kind": getattr(obj, 'map_kind', None),
            "map_geom": getattr(obj, 'map_geom', None),
            "name_en": getattr(obj, 'name_en', None),
            "search_terms": getattr(obj, 'search_terms', None),
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
        }
        return cls(**data)


# ===== PROPOSED ACTIVITIES (Per Forest) =====

class ProposedActivityBase(BaseModel):
    """Base schema for proposed activity with spatial assignment."""
    potential_activity_id: int
    block_id: Optional[UUID] = None
    sub_area_id: Optional[UUID] = None  # NEW: Spatial integration
    default_quantity: Decimal = Field(..., gt=0)
    # D17: a wholly voluntary activity may have a default budget of 0
    default_yearly_budget: Decimal = Field(..., ge=0)
    notes: Optional[str] = None
    status: str = 'proposed'

    @validator('sub_area_id')
    def validate_sub_area_requires_block(cls, v, values):
        """Sub-area can only be set if block is also set"""
        if v is not None and values.get('block_id') is None:
            raise ValueError('उप-क्षेत्रको लागि ब्लक आईडी आवश्यक छ')
        return v


class ProposedActivityCreate(ProposedActivityBase):
    """Request schema for creating a proposed activity."""
    pass


class ProposedActivityUpdate(BaseModel):
    """Request schema for updating a proposed activity."""
    block_id: Optional[UUID] = None
    sub_area_id: Optional[UUID] = None  # NEW
    default_quantity: Optional[Decimal] = Field(None, gt=0)
    default_yearly_budget: Optional[Decimal] = Field(None, ge=0)
    notes: Optional[str] = None
    status: Optional[str] = None
    # "Applies to the whole forest" for a mappable activity (plan §4.4b); the operational-plan and
    # plan-map collectors already read this flag
    assign_to_all_blocks: Optional[bool] = None
    # optimistic lock (plan §5.5): accepted and logged when absent, refused with 409 when stale
    expected_version: Optional[int] = None


class ProposedActivityResponse(ProposedActivityBase):
    """Response schema for proposed activity with spatial details."""
    id: UUID
    calculation_id: UUID
    created_at: datetime
    updated_at: datetime

    # Spatial assignment options (NEW)
    assign_to_all_blocks: bool = False
    use_custom_yearly_values: bool = False
    # optimistic-lock counter and the "numbers were typed / confirmed" marker (migration 091)
    version: int = 1
    reviewed_at: Optional[datetime] = None

    # Include potential activity details
    potential_activity: Optional[PotentialActivityResponse] = None

    # Spatial details
    block_name: Optional[str] = None
    sub_area_name: Optional[str] = None
    sub_area_category: Optional[str] = None
    location_description: Optional[str] = None

    class Config:
        from_attributes = True


# ===== YEAR DETAILS (Year-Specific Overrides) =====

class YearDetailBase(BaseModel):
    """Base schema for year-specific activity details."""
    year_number: int = Field(..., ge=1, le=10)
    quantity: Optional[Decimal] = Field(None, ge=0)
    yearly_budget: Optional[Decimal] = Field(None, ge=0)
    target_completion_month: Optional[str] = None
    actual_quantity: Optional[Decimal] = None
    actual_budget: Optional[Decimal] = None
    status: str = 'planned'
    notes: Optional[str] = None


class YearDetailCreate(YearDetailBase):
    """Request schema for creating year detail."""
    # the plan line's version, when the client holds one (optimistic lock, plan §5.5)
    expected_version: Optional[int] = None


class YearDetailUpdate(BaseModel):
    """Request schema for updating year detail."""
    quantity: Optional[Decimal] = Field(None, ge=0)
    yearly_budget: Optional[Decimal] = Field(None, ge=0)
    target_completion_month: Optional[str] = None
    actual_quantity: Optional[Decimal] = None
    actual_budget: Optional[Decimal] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    expected_version: Optional[int] = None


class YearDetailResponse(YearDetailBase):
    """Response schema for year detail."""
    id: UUID
    proposed_activity_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ===== COMPOSITE SCHEMAS =====

class ProposedActivityWithYears(ProposedActivityResponse):
    """Proposed activity with all 10 years of data"""
    year_details: List[YearDetailResponse] = []

    # Computed fields
    total_budget_10_years: Decimal = Field(default=0)

    @validator('total_budget_10_years', always=True)
    def calculate_total_budget(cls, v, values):
        """Calculate total budget across 10 years"""
        default_budget = values.get('default_yearly_budget', 0)
        year_details = values.get('year_details', [])
        # a stored 0 is a real value, not "use the default" (yearly_plan_rules)
        return total_budget(default_budget, year_details)


class ActivitySummary(BaseModel):
    """Summary statistics for yearly activities"""
    total_activities: int
    total_budget_10_years: Decimal
    by_project: dict  # {project_name: count}
    by_program: dict  # {program: count}
    by_block: dict    # {block_name: count}
    by_year: dict     # {year_number: budget}
    by_status: dict   # {status: count}


# ===== NEW: SPATIAL SCHEMAS =====

class ActivityLocationSummary(BaseModel):
    """Summary of activities by spatial location"""
    by_block: dict  # {block_name: count}
    by_sub_area_category: dict  # {category: count}
    by_sub_area: dict  # {sub_area_name: count}
    whole_forest_count: int  # Activities not assigned to specific locations


# ===== BULK OPERATIONS =====

class BulkProposedActivityCreate(BaseModel):
    """Create multiple proposed activities at once"""
    activities: List[ProposedActivityCreate]


class DefaultActivitiesRequest(BaseModel):
    """Request to auto-select default activities"""
    override_existing: bool = False  # If true, replace existing activities


# ===== SPATIAL ASSIGNMENT SCHEMAS =====

class SpatialAssignmentBase(BaseModel):
    """Base schema for spatial assignment of activities."""
    block_id: Optional[UUID] = None
    sub_area_id: Optional[UUID] = None
    assignment_type: str = Field(default="all_blocks", pattern="^(all_blocks|block|sub_area)$")


class SpatialAssignmentCreate(SpatialAssignmentBase):
    """Request schema for creating spatial assignment."""
    pass


class SpatialAssignmentResponse(SpatialAssignmentBase):
    """Response schema for spatial assignment."""
    id: UUID
    proposed_activity_id: UUID
    created_at: datetime

    block_name: Optional[str] = None
    sub_area_name: Optional[str] = None

    class Config:
        from_attributes = True


# ===== DRAWN FEATURE SCHEMAS =====

class DrawnFeatureBase(BaseModel):
    """Base schema for drawn map features."""
    feature_type: str = Field(..., pattern="^(point|line|polygon)$")
    geometry: str  # GeoJSON string
    properties: dict = {}


class DrawnFeatureCreate(DrawnFeatureBase):
    """Request schema for creating a drawn feature."""

    @model_validator(mode='after')
    def validate_spatial_data(self) -> 'DrawnFeatureCreate':
        """Validate geometry before creating a new feature"""
        try:
            geo_dict = json.loads(self.geometry)
        except json.JSONDecodeError:
            raise ValueError("ज्यामिति मान्य JSON स्ट्रिंग हुनुपर्छ।")

        if "type" not in geo_dict or "coordinates" not in geo_dict:
            raise ValueError("अमान्य GeoJSON ढाँचा: 'type' र 'coordinates' फिल्डहरू आवश्यक छन्।")

        coords = geo_dict["coordinates"]
        geom_type = geo_dict["type"].lower()

        # Cross-check geometry type with feature_type
        expected_type = "linestring" if self.feature_type == "line" else self.feature_type
        if geom_type != expected_type:
            raise ValueError(f"ज्यामिति प्रकार '{geom_type}' फिचर प्रकार '{self.feature_type}' संग मेल खादैन।")

        # Validate coordinate structures
        if geom_type == "point":
            if not isinstance(coords, list) or len(coords) != 2:
                raise ValueError("बिन्दु निर्देशांक दुई संख्याको सूची [देशान्तर, अक्षान्तर] हुनुपर्छ।")
            if not all(isinstance(c, (int, float)) for c in coords):
                raise ValueError("बिन्दु निर्देशांक संख्यात्मक मान हुनुपर्छ।")

        elif geom_type == "linestring":
            if not isinstance(coords, list) or len(coords) < 2:
                raise ValueError("LineString मा मान्य रेखा बन्न कम्तिमा दुई बिन्दुहरू आवश्यक छन्।")
            for i, point in enumerate(coords):
                if not isinstance(point, list) or len(point) != 2:
                    raise ValueError(f"LineString बिन्दु {i} [देशान्तर, अक्षान्तर] ढाँचामा हुनुपर्छ।")

        elif geom_type == "polygon":
            if not isinstance(coords, list) or not isinstance(coords[0], list):
                raise ValueError("Polygon निर्देशांक रिङहरूको सूची हुनुपर्छ।")
            if len(coords[0]) < 4:
                raise ValueError("Polygon मा बन्द रेखा बन्न कम्तिमा ४ बिन्दुहरू (सहित बन्द बिन्दु) आवश्यक छन्।")

            # Ensure the polygon is closed (first and last points match)
            ring = coords[0]
            if ring[0] != ring[-1]:
                raise ValueError("Polygon रिङ बन्द हुनुपर्छ (पहिलो र अन्तिम निर्देशांक जोडा मिल्नुपर्छ)।")

        # Validate with Shapely
        self._validate_with_shapely(geo_dict, geom_type)

        return self

    def _validate_with_shapely(self, geo_dict: dict, geom_type: str):
        """Use Shapely to validate geometry validity"""
        try:
            from shapely.geometry import shape
            logger.debug(f"[_validate_with_shapely CREATE] geo_dict: {geo_dict}")
            geom = shape(geo_dict)
            if not geom.is_valid:
                if geom_type == "polygon":
                    raise ValueError("POLYGON_INVALID: अमान्य बहुभुज ज्यामिति (आत्म-प्रतिच्छेदन वा अमान्य अभिविन्यास हुन सक्छ)।")
                else:
                    raise ValueError(f"GEOMETRY_INVALID: अमान्य {geom_type} ज्यामिति।")
        except ImportError:
            # Shapely not available, skip this validation
            pass
        except Exception as e:
            if "Invalid" not in str(e):
                logger.debug(f"[_validate_with_shapely CREATE] ERROR: {e}")
                raise ValueError(f"GEOMETRY_VALIDATION_FAILED: ज्यामिति प्रमाणीकरण असफल: {str(e)}")
            raise


class DrawnFeatureUpdate(BaseModel):
    """Request schema for updating a drawn feature."""
    feature_type: Optional[str] = Field(None, pattern="^(point|line|polygon)$")
    geometry: Optional[str] = None
    properties: Optional[dict] = None

    @model_validator(mode='after')
    def validate_spatial_data(self) -> 'DrawnFeatureUpdate':
        """Validate geometry if it's being updated"""
        if not self.geometry:
            return self

        try:
            geo_dict = json.loads(self.geometry)
        except json.JSONDecodeError:
            raise ValueError("ज्यामिति मान्य JSON स्ट्रिंग हुनुपर्छ।")

        if "type" not in geo_dict or "coordinates" not in geo_dict:
            raise ValueError("अमान्य GeoJSON ढाँचा: 'type' र 'coordinates' फिल्डहरू आवश्यक छन्।")

        coords = geo_dict["coordinates"]
        geom_type = geo_dict["type"].lower()

        # Cross-check geometry type with feature_type (if provided)
        if self.feature_type:
            expected_type = "linestring" if self.feature_type == "line" else self.feature_type
            if geom_type != expected_type:
                raise ValueError(f"ज्यामिति प्रकार '{geom_type}' फिचर प्रकार '{self.feature_type}' संग मेल खादैन।")

        # Validate coordinate structures
        if geom_type == "point":
            if not isinstance(coords, list) or len(coords) != 2:
                raise ValueError("बिन्दु निर्देशांक दुई संख्याको सूची [देशान्तर, अक्षान्तर] हुनुपर्छ।")

        elif geom_type == "linestring":
            if not isinstance(coords, list) or len(coords) < 2:
                raise ValueError("LineString मा मान्य रेखा बन्न कम्तिमा दुई बिन्दुहरू आवश्यक छन्।")

        elif geom_type == "polygon":
            if not isinstance(coords, list) or not isinstance(coords[0], list):
                raise ValueError("Polygon निर्देशांक रिङहरूको सूची हुनुपर्छ।")
            if len(coords[0]) < 4:
                raise ValueError("Polygon मा बन्द रेखा बन्न कम्तिमा ४ बिन्दुहरू (सहित बन्द बिन्दु) आवश्यक छन्।")

            ring = coords[0]
            if ring[0] != ring[-1]:
                raise ValueError("Polygon रिङ बन्द हुनुपर्छ (पहिलो र अन्तिम निर्देशांक जोडा मिल्नुपर्छ)।")

        # Validate with Shapely
        self._validate_with_shapely(geo_dict, geom_type)

        return self

    def _validate_with_shapely(self, geo_dict: dict, geom_type: str):
        """Use Shapely to validate geometry validity"""
        try:
            from shapely.geometry import shape
            logger.debug(f"[_validate_with_shapely] geo_dict: {geo_dict}")
            geom = shape(geo_dict)
            if not geom.is_valid:
                if geom_type == "polygon":
                    raise ValueError("POLYGON_INVALID: अमान्य बहुभुज ज्यामिति (आत्म-प्रतिच्छेदन वा अमान्य अभिविन्यास हुन सक्छ)।")
                else:
                    raise ValueError(f"GEOMETRY_INVALID: अमान्य {geom_type} ज्यामिति।")
        except ImportError:
            pass
        except Exception as e:
            if "Invalid" not in str(e):
                logger.debug(f"[_validate_with_shapely] ERROR: {e}")
                raise ValueError(f"GEOMETRY_VALIDATION_FAILED: ज्यामिति प्रमाणीकरण असफल: {str(e)}")
            raise


class DrawnFeatureResponse(DrawnFeatureBase):
    """Response schema for drawn feature."""
    id: UUID
    proposed_activity_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CalculationDrawnFeatureResponse(DrawnFeatureResponse):
    """A drawn feature as the workspace's Activity Features layer needs it: with the activity it
    belongs to, so the map can label it "<activity> · year 1" instead of an anonymous "Feature 1"."""
    activity_name: Optional[str] = None
    program_name: Optional[str] = None
    block_name: Optional[str] = None
    # The symbol this feature draws with: a key of feature_kinds.KINDS, or "" for the generic
    # point / line / polygon. Its own properties.kind wins over the activity's default.
    kind: str = ""
    # The quantity belongs to the activity's PLAN LINE, not to the place: every place of one activity shares it.
    # `plan_quantity` is that line's quantity, `plan_unit` what it is counted in, `shared_count` how many live
    # places of the line there are (so the table can say "shared x3" instead of implying each place has its own).
    plan_quantity: Optional[float] = None
    plan_unit: Optional[str] = None
    shared_count: int = 1


# ===== ENHANCED PROPOSED ACTIVITY SCHEMA =====

class ProposedActivityEnhancedResponse(ProposedActivityResponse):
    """Enhanced proposed activity with spatial assignments and drawn features"""
    assign_to_all_blocks: bool = False
    use_custom_yearly_values: bool = False
    spatial_assignments: List[SpatialAssignmentResponse] = []
    drawn_features: List[DrawnFeatureResponse] = []


# ===== BLOCK WITH SUB-AREAS =====

class BlockWithSubAreasResponse(BaseModel):
    """Block info with its sub-areas"""
    block_id: str
    block_name: str
    sub_areas: List[Any] = []  # [{id, name, category}]