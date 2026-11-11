"""
User model - maps to existing users table in cf_db
"""
from sqlalchemy import Column, String, DateTime, Boolean, Integer, Enum as SQLEnum, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from typing import Optional
from datetime import datetime, timezone
import enum
import uuid

from ..core.database import Base


class UserRole(str, enum.Enum):
    """User role enumeration"""
    GUEST = "guest"
    USER = "user"
    ORG_ADMIN = "org_admin"
    SUPER_ADMIN = "super_admin"
    # OP multi-template: authors OP document templates; cannot review/publish.
    # DB enum label is the member NAME ("TEMPLATE_DESIGNER") — SQLAlchemy Enum
    # stores names, matching migration 065.
    TEMPLATE_DESIGNER = "template_designer"


class UserStatus(str, enum.Enum):
    """User status enumeration"""
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class User(Base):
    """
    User model - maps to public.users table
    Authentication and user management
    """
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Null for an account made through Facebook / phone that has not given one yet.
    email = Column(String(255), unique=True, nullable=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=True)
    designation = Column(String(20), nullable=True)  # UserDesignation value
    sub_division = Column(String(255), nullable=True)
    instagram_handle = Column(String(64), nullable=True)  # stored, never verified
    phone_verified_at = Column(DateTime(timezone=True), nullable=True)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    # Set by a super admin. ACTIVE with approved_at null is the limited tier.
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(UUID(as_uuid=True), nullable=True)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.USER)
    status = Column(SQLEnum(UserStatus), nullable=False, default=UserStatus.ACTIVE)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)

    # H2.5 / S1-05: revocation switch for stateless access tokens. Every access
    # token carries the generation it was minted under; logout and password
    # change increment this, and tokens from an older generation stop working.
    # Free to check — get_current_user already loads this row on every request.
    #
    # A counter, not a timestamp: JWT `iat` has one-second resolution, so a
    # token issued moments before logout shares its second and would survive a
    # time-based cutoff.
    token_generation = Column(Integer, nullable=False, default=0, server_default="0")

    # Map & Workspace Unification (U01/U08) — user-level unified-shell opt-out (highest precedence)
    unified_shell_opt_out = Column(Boolean, nullable=False, default=False, server_default='false')

    # Relationships
    organization = relationship("Organization", back_populates="users")
    forest_managers = relationship("ForestManager", back_populates="user")
    calculations = relationship("Calculation", back_populates="user", foreign_keys="Calculation.user_id")
    inventory_calculations = relationship("InventoryCalculation", back_populates="user")
    field_inventory_calculations = relationship("FieldInventoryCalculation", back_populates="user")

    # Who the person says they are (UserType value). Null = an account from before types existed.
    user_type = Column(String(16), nullable=True)
    # What that type asked for (student: institution, supervisor ...; see services/user_types.py).
    type_details = Column(JSONB, nullable=True)
    access_expires_at = Column(DateTime(timezone=True), nullable=True)
    org_member_role = Column(String(8), nullable=True)  # 'owner' | 'member'
    org_vouched_at = Column(DateTime(timezone=True), nullable=True)
    org_vouched_by = Column(UUID(as_uuid=True), nullable=True)

    @property
    def is_approved(self) -> bool:
        return self.approved_at is not None

    @property
    def profile_complete(self) -> bool:
        from ..services.user_types import TypeDetailsError, clean  # local: the service imports this module

        if self.user_type not in {t.value for t in UserType}:
            return False
        try:
            clean(UserType(self.user_type), self.designation, self.sub_division, self.type_details)
        except TypeDetailsError:
            return False
        return True

    @property
    def access_level(self) -> str:
        """'read_only' for a student / researcher: they may look at what they are linked to, not change it."""
        from ..services.user_types import default_access

        if self.role == UserRole.SUPER_ADMIN:
            return "full"
        return default_access(self.user_type)

    @property
    def access_expired(self) -> bool:
        return self.access_expires_at is not None and self.access_expires_at <= datetime.now(timezone.utc)

    @property
    def organization_name(self) -> Optional[str]:
        return self.organization.name if self.organization is not None else None

    @property
    def organization_verified(self) -> bool:
        return self.organization is not None and self.organization.verified_at is not None

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role.value})>"


class UserType(str, enum.Enum):
    """The four kinds of person the system serves. Self-declared; a super admin checks it on approval."""
    OFFICIAL = "official"
    STUDENT = "student"
    RESEARCHER = "researcher"
    ORGANIZATION = "organization"


class UserDesignation(str, enum.Enum):
    """Who the person says they are in the sub-division. Self-declared; a super admin checks it on approval."""
    FOREST_GUARD = "forest_guard"
    FORESTER = "forester"
    RANGER = "ranger"
    OFFICE = "office"


class UserIdentity(Base):
    """A sign-in identity from outside (Facebook). One subject belongs to one user."""
    __tablename__ = "user_identities"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(20), nullable=False)
    subject = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class AuthChallenge(Base):
    """A short-lived secret (phone OTP or emailed link token). Only its hash is stored."""
    __tablename__ = "auth_challenges"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purpose = Column(String(24), nullable=False)
    channel = Column(String(8), nullable=False)
    target = Column(String(255), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    secret_hash = Column(String(64), nullable=False)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    # tz-aware: the cooldown compares this with now(); a naive utcnow is read as local time and skews it.
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
