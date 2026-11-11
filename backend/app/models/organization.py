"""
Organization model - maps to existing organizations table
"""
from sqlalchemy import Index, Column, String, DateTime, Enum as SQLEnum, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
import uuid

from ..core.database import Base


class SubscriptionType(str, enum.Enum):
    """Organization subscription types"""
    BASIC = "basic"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


class Organization(Base):
    """
    Organization model - maps to public.organizations table
    Represents community forest user groups or organizations
    """
    __tablename__ = "organizations"
    __table_args__ = (
        Index('ix_organizations_name', 'name', unique=True),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    contact_email = Column(String(255), nullable=False)
    contact_phone = Column(String(20), nullable=True)
    subscription_type = Column(SQLEnum(SubscriptionType), nullable=False, default=SubscriptionType.BASIC)
    max_users = Column(Integer, nullable=False, default=5)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    # Made at sign-up by a user of type "organization". A super admin sets verified_at once it is real;
    # only then can its owner vouch for members.
    kind = Column(String(16), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)

    # Relationships
    users = relationship("User", back_populates="organization")

    def __repr__(self):
        return f"<Organization(id={self.id}, name={self.name})>"
