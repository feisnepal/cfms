"""DB-backed translation row (Phase 3 i18n super-admin editor).

One row per i18n dotted key. The frontend ships bundled en/ne.json defaults and
merges only rows where `is_override` is true at boot. `history` is an
append-only JSONB snapshot array written on every edit via
`upsert_translation`.
"""
from sqlalchemy import Column, BigInteger, Text, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from ..core.database import Base


class Translation(Base):
    __tablename__ = "translations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    key = Column(Text, nullable=False, unique=True, index=True)
    en = Column(Text, nullable=True)
    ne = Column(Text, nullable=True)
    context = Column(Text, nullable=True)
    source_file = Column(String(16), nullable=False, default="bundle")
    is_override = Column(Boolean, nullable=False, default=False)
    reviewed = Column(Boolean, nullable=False, default=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    history = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())