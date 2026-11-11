"""Server-side record of issued refresh tokens (H2.5 / S1-05).

Refresh tokens are stateless JWTs like everything else here, but a session that
cannot be revoked is not a session — so each one is also recorded, consumed on
use, and grouped into a family per login. See migration 050 for why.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.database import Base


class RefreshToken(Base):
    """One issued refresh token."""

    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jti = Column(String(64), nullable=False, unique=True, index=True)
    family = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    issued_at = Column(DateTime(timezone=True),
                       default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(String(64), nullable=True)
    user_agent = Column(String(256), nullable=True)

    user = relationship("User")

    @property
    def is_live(self) -> bool:
        """Usable right now: not consumed, not revoked, not expired."""
        if self.consumed_at is not None or self.revoked_at is not None:
            return False
        expires = self.expires_at
        if expires is None:
            return False
        now = datetime.now(expires.tzinfo or timezone.utc)
        return expires > now

    def __repr__(self):
        return f"<RefreshToken(jti={self.jti}, user_id={self.user_id})>"
