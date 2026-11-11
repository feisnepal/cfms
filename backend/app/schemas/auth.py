"""
Authentication schemas for request/response validation
"""
import re
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Any, Optional
from datetime import datetime
from uuid import UUID

from ..models.user import UserRole, UserStatus, UserDesignation, UserType


def _check_password(v: str) -> str:
    """Validate password strength"""
    if len(v) < 8:
        raise ValueError('पासवर्ड कम्तिमा ८ अक्षरको हुनुपर्छ')
    if not any(c.isupper() for c in v):
        raise ValueError('पासवर्डमा कम्तिमा एक ठो ठूलो अक्षर (A-Z) हुनुपर्छ')
    if not any(c.islower() for c in v):
        raise ValueError('पासवर्डमा कम्तिमा एक ठो सानो अक्षर (a-z) हुनुपर्छ')
    if not any(c.isdigit() for c in v):
        raise ValueError('पासवर्डमा कम्तिमा एक ठो अंक (0-9) हुनुपर्छ')
    return v


def _clean_handle(v: Optional[str]) -> Optional[str]:
    v = (v or '').strip().lstrip('@')
    if v and not re.fullmatch(r'[A-Za-z0-9._]{1,30}', v):
        raise ValueError('Instagram handle may only hold letters, digits, dot and underscore')
    return v or None


class UserRegister(BaseModel):
    """Schema for user registration"""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)
    full_name: str = Field(..., min_length=2, max_length=255)
    # Every field below is required: the person says who they are, and proves the phone.
    phone: str = Field(..., max_length=20)
    phone_code: str = Field(..., min_length=4, max_length=8)
    user_type: UserType
    # Official: designation + sub_division. Every other type: `details` (see services/user_types.py).
    designation: Optional[UserDesignation] = None
    sub_division: Optional[str] = Field(None, max_length=255)
    details: Optional[dict[str, Any]] = None
    # At least one social identity: a Facebook token (verified with Facebook) or an Instagram handle (stored as given).
    facebook_access_token: Optional[str] = Field(None, max_length=1024)
    instagram_handle: Optional[str] = Field(None, max_length=64)

    @validator('instagram_handle')
    def clean_handle(cls, v):
        return _clean_handle(v)

    @validator('password')
    def validate_password(cls, v):
        return _check_password(v)


class UserLogin(BaseModel):
    """Schema for user login"""
    email: EmailStr
    password: str


class Token(BaseModel):
    """Schema for JWT token response"""
    access_token: str
    # H2.5 / S1-05: issued alongside the access token and rotated on every use.
    # Optional so the schema still describes responses from before this change.
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshRequest(BaseModel):
    """Body for POST /auth/refresh.

    The refresh token travels in the body rather than the Authorization header
    on purpose: the header is where the *access* token lives, and the old
    endpoint's willingness to accept whatever was in it — expired or not — was
    the vulnerability (S1-05).
    """
    refresh_token: str


class TokenData(BaseModel):
    """Schema for decoded token data"""
    sub: str  # user_id
    email: Optional[str] = None
    exp: Optional[datetime] = None


class UserResponse(BaseModel):
    """Schema for user data response"""
    id: UUID
    email: Optional[str]
    full_name: str
    phone: Optional[str]
    role: UserRole
    status: UserStatus
    organization_id: Optional[UUID]
    created_at: datetime
    last_login: Optional[datetime]
    designation: Optional[str] = None
    sub_division: Optional[str] = None
    instagram_handle: Optional[str] = None
    phone_verified_at: Optional[datetime] = None
    email_verified_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    is_approved: bool = False
    # False until designation + sub-division are filled in (a Facebook account starts without them).
    profile_complete: bool = False
    user_type: Optional[str] = None
    type_details: Optional[dict[str, Any]] = None
    # 'read_only' for a student / researcher; access_expires_at ends it.
    access_level: str = "full"
    access_expires_at: Optional[datetime] = None
    org_member_role: Optional[str] = None
    org_vouched_at: Optional[datetime] = None
    organization_name: Optional[str] = None
    organization_verified: bool = False

    class Config:
        from_attributes = True


class MemberResponse(BaseModel):
    """A member of an organisation, as its owner sees them."""
    id: UUID
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    org_member_role: Optional[str] = None
    org_vouched_at: Optional[datetime] = None
    is_approved: bool = False
    type_details: Optional[dict[str, Any]] = None

    class Config:
        from_attributes = True


class AccessUpdate(BaseModel):
    """Super admin: when access ends (null clears it) and/or the declared type."""
    access_expires_at: Optional[datetime] = None
    user_type: Optional[UserType] = None


class PasswordReset(BaseModel):
    """Schema for password reset request"""
    email: EmailStr


class PhoneCodeRequest(BaseModel):
    phone: str = Field(..., max_length=20)


class PhoneLogin(BaseModel):
    phone: str = Field(..., max_length=20)
    code: str = Field(..., min_length=4, max_length=8)


class FacebookLogin(BaseModel):
    access_token: str = Field(..., max_length=1024)


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=255)
    user_type: Optional[UserType] = None
    designation: Optional[UserDesignation] = None
    sub_division: Optional[str] = Field(None, max_length=255)
    details: Optional[dict[str, Any]] = None
    instagram_handle: Optional[str] = Field(None, max_length=64)

    @validator('instagram_handle')
    def clean_handle(cls, v):
        return _clean_handle(v)


class PhoneVerify(BaseModel):
    phone: str = Field(..., max_length=20)
    code: str = Field(..., min_length=4, max_length=8)


class EmailLinkRequest(BaseModel):
    email: EmailStr


class TokenBody(BaseModel):
    token: str = Field(..., max_length=256)


class ForgotPassword(BaseModel):
    """Email address or phone number of the account."""
    identifier: str = Field(..., max_length=255)


class ResetPassword(BaseModel):
    """Either an emailed `token`, or the SMS `phone` + `code`."""
    new_password: str = Field(..., min_length=8, max_length=72)
    token: Optional[str] = Field(None, max_length=256)
    phone: Optional[str] = Field(None, max_length=20)
    code: Optional[str] = Field(None, max_length=8)

    @validator('new_password')
    def validate_password(cls, v):
        return _check_password(v)


class ResetLink(BaseModel):
    url: str
    expires_in: int


class PasswordChange(BaseModel):
    """Schema for password change"""
    old_password: str
    new_password: str = Field(..., min_length=8, max_length=72)

    @validator('new_password')
    def validate_password(cls, v):
        """Validate password strength"""
        if len(v) < 8:
            raise ValueError('पासवर्ड कम्तिमा ८ अक्षरको हुनुपर्छ')
        if not any(c.isupper() for c in v):
            raise ValueError('पासवर्डमा कम्तिमा एक ठो ठूलो अक्षर (A-Z) हुनुपर्छ')
        if not any(c.islower() for c in v):
            raise ValueError('पासवर्डमा कम्तिमा एक ठो सानो अक्षर (a-z) हुनुपर्छ')
        if not any(c.isdigit() for c in v):
            raise ValueError('पासवर्डमा कम्तिमा एक ठो अंक (0-9) हुनुपर्छ')
        return v
