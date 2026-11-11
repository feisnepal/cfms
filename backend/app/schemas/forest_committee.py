"""
Forest Committee Schemas
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal


# ============ Forest User Committee (Main Committee) ============

class ForestUserCommitteeBase(BaseModel):
    """Base schema for main forest user committee"""
    serial_no: int = Field(..., ge=1, le=15, description="सि.नं. (1-15)")
    gender: str = Field(..., description="लिङ्ग (महिला/पुरूष)")
    position: str = Field(..., description="पद")
    caste_category: str = Field(..., description="जातिय वर्ग")
    name: str = Field(..., min_length=1, max_length=200, description="नाम")
    address: Optional[str] = Field(None, description="ठेगाना (optional)")
    mobile: Optional[str] = Field(None, description="मोवाइल नंवर (optional, 10 digits)")

    @validator('address', pre=True)
    def validate_address(cls, v):
        # Convert empty string to None
        if v == '' or (isinstance(v, str) and v.strip() == ''):
            return None
        return v

    @validator('gender')
    def validate_gender(cls, v):
        valid_genders = ['महिला', 'पुरूष']
        if v not in valid_genders:
            raise ValueError("लिङ्ग 'महिला' वा 'पुरूष' हुनुपर्छ")
        return v

    @validator('position')
    def validate_position(cls, v):
        valid_positions = ['अध्यक्ष', 'उपाध्यक्ष', 'कोषाध्यक्ष', 'सह कोषाध्यक्ष', 'सचिव', 'सह सचिव', 'सदस्य']
        if v not in valid_positions:
            raise ValueError("पद 'अध्यक्ष', 'उपाध्यक्ष', 'कोषाध्यक्ष', 'सह कोषाध्यक्ष', 'सचिव', 'सह सचिव', वा 'सदस्य' हुनुपर्छ")
        return v

    @validator('caste_category')
    def validate_caste_category(cls, v):
        valid_categories = ['जनजाती', 'आदिवासी', 'दलित', 'सिमान्तकृत', 'अन्य']
        if v not in valid_categories:
            raise ValueError("जात वर्गीकरण 'जनजाती', 'आदिवासी', 'दलित', 'सिमान्तकृत', वा 'अन्य' हुनुपर्छ")
        return v

    @validator('mobile')
    def validate_mobile(cls, v):
        if v is not None and v != '':
            # Remove any spaces or dashes
            cleaned = v.replace(' ', '').replace('-', '')
            if len(cleaned) != 10:
                raise ValueError("मोवाइल नम्बर ठीक १० अंकको हुनुपर्छ")
            if not cleaned.isdigit():
                raise ValueError("मोवाइल नम्बरमा केवल अंकहरू मात्र हुनुपर्छ")
            return cleaned
        return None


class ForestUserCommitteeCreate(ForestUserCommitteeBase):
    """Schema for creating main committee member"""
    pass


class ForestUserCommitteeUpdate(BaseModel):
    """Schema for updating main committee member (all fields optional)"""
    serial_no: Optional[int] = Field(None, ge=1, le=15)
    gender: Optional[str] = None
    position: Optional[str] = None
    caste_category: Optional[str] = None
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    address: Optional[str] = Field(None, min_length=1)
    mobile: Optional[str] = None


class ForestUserCommitteeResponse(ForestUserCommitteeBase):
    """Schema for main committee member response"""
    id: UUID
    calculation_id: UUID
    created_at: datetime
    updated_at: datetime
    created_by: UUID

    class Config:
        from_attributes = True


# ============ Advisory Committee ============

class AdvisoryCommitteeBase(BaseModel):
    """Base schema for advisory committee"""
    serial_no: int = Field(..., ge=1, le=10, description="सि.नं. (1-10)")
    name: str = Field(..., min_length=1, max_length=200, description="नाम")
    address: Optional[str] = Field(None, description="ठेगाना (optional)")
    mobile: Optional[str] = Field(None, description="मोवाइल नंवर (optional, 10 digits)")

    @validator('address', pre=True)
    def validate_address(cls, v):
        # Convert empty string to None
        if v == '' or (isinstance(v, str) and v.strip() == ''):
            return None
        return v

    @validator('mobile')
    def validate_mobile(cls, v):
        if v is not None and v != '':
            cleaned = v.replace(' ', '').replace('-', '')
            if len(cleaned) != 10:
                raise ValueError("मोवाइल नम्बर ठीक १० अंकको हुनुपर्छ")
            if not cleaned.isdigit():
                raise ValueError("मोवाइल नम्बरमा केवल अंकहरू मात्र हुनुपर्छ")
            return cleaned
        return None


class AdvisoryCommitteeCreate(AdvisoryCommitteeBase):
    """Schema for creating advisory committee member"""
    pass


class AdvisoryCommitteeUpdate(BaseModel):
    """Schema for updating advisory committee member (all fields optional)"""
    serial_no: Optional[int] = Field(None, ge=1, le=10)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    address: Optional[str] = Field(None, min_length=1)
    mobile: Optional[str] = None


class AdvisoryCommitteeResponse(AdvisoryCommitteeBase):
    """Schema for advisory committee member response"""
    id: UUID
    calculation_id: UUID
    created_at: datetime
    updated_at: datetime
    created_by: UUID

    class Config:
        from_attributes = True


# ============ Financial Committee ============

class FinancialCommitteeBase(BaseModel):
    """Base schema for financial committee"""
    serial_no: int = Field(..., ge=1, le=10, description="सि.नं. (1-10)")
    name: str = Field(..., min_length=1, max_length=200, description="नाम")
    address: Optional[str] = Field(None, description="ठेगाना (optional)")
    mobile: Optional[str] = Field(None, description="मोवाइल नंवर (optional, 10 digits)")

    @validator('address', pre=True)
    def validate_address(cls, v):
        # Convert empty string to None
        if v == '' or (isinstance(v, str) and v.strip() == ''):
            return None
        return v

    @validator('mobile')
    def validate_mobile(cls, v):
        if v is not None and v != '':
            cleaned = v.replace(' ', '').replace('-', '')
            if len(cleaned) != 10:
                raise ValueError("मोवाइल नम्बर ठीक १० अंकको हुनुपर्छ")
            if not cleaned.isdigit():
                raise ValueError("मोवाइल नम्बरमा केवल अंकहरू मात्र हुनुपर्छ")
            return cleaned
        return None


class FinancialCommitteeCreate(FinancialCommitteeBase):
    """Schema for creating financial committee member"""
    pass


class FinancialCommitteeUpdate(BaseModel):
    """Schema for updating financial committee member (all fields optional)"""
    serial_no: Optional[int] = Field(None, ge=1, le=10)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    address: Optional[str] = Field(None, min_length=1)
    mobile: Optional[str] = None


class FinancialCommitteeResponse(FinancialCommitteeBase):
    """Schema for financial committee member response"""
    id: UUID
    calculation_id: UUID
    created_at: datetime
    updated_at: datetime
    created_by: UUID

    class Config:
        from_attributes = True


# ============ Bulk Operations & Validation ============

class CommitteeValidationIssue(BaseModel):
    """Single validation issue"""
    row_number: int
    field: str
    issue_type: str  # "error" or "warning"
    message: str


class CommitteeValidationResult(BaseModel):
    """Validation result for a single row"""
    row_number: int
    is_valid: bool
    errors: List[str] = []
    warnings: List[str] = []
    data: Optional[dict] = None


class CommitteeUploadResponse(BaseModel):
    """Response for committee data upload"""
    success: bool
    main_committee_imported: int = 0
    advisory_committee_imported: int = 0
    financial_committee_imported: int = 0
    total_rows_processed: int
    validations: List[CommitteeValidationResult] = []
    warnings: List[str] = []


class CommitteeSummary(BaseModel):
    """Summary statistics for committee composition"""
    # Main Committee
    main_committee_size: int
    main_committee_women: int
    main_committee_men: int
    women_percentage: float

    # Position assignments
    positions_filled: dict  # {position: name}
    positions_unfilled: List[str]

    # Gender validation warnings
    meets_50_percent_rule: bool
    key_position_warnings: List[str] = []

    # Advisory & Financial
    advisory_committee_size: int
    financial_committee_size: int

    # Validation issues
    validation_warnings: List[str] = []
    validation_errors: List[str] = []


class AllCommitteesResponse(BaseModel):
    """Response containing all three committees"""
    main_committee: List[ForestUserCommitteeResponse]
    advisory_committee: List[AdvisoryCommitteeResponse]
    financial_committee: List[FinancialCommitteeResponse]
    summary: Optional[CommitteeSummary] = None


# ============ Bulk Create/Update ============

class BulkCommitteeCreate(BaseModel):
    """Schema for creating multiple committee members at once"""
    main_committee: List[ForestUserCommitteeCreate] = []
    advisory_committee: List[AdvisoryCommitteeCreate] = []
    financial_committee: List[FinancialCommitteeCreate] = []

    @validator('main_committee')
    def validate_main_committee_size(cls, v):
        if len(v) > 15:
            raise ValueError("मुख्य समितिमा १५ भन्दा बढी सदस्य हुन सक्दैन")
        return v

    @validator('advisory_committee')
    def validate_advisory_size(cls, v):
        if len(v) > 10:
            raise ValueError("सल्लाहकार समितिमा १० भन्दा बढी सदस्य हुन सक्दैन")
        return v

    @validator('financial_committee')
    def validate_financial_size(cls, v):
        if len(v) > 10:
            raise ValueError("आर्थिक समितिमा १० भन्दा बढी सदस्य हुन सक्दैन")
        return v
