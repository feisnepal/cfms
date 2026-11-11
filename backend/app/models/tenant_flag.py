"""TenantFlag model — DB-backed feature-flag precedence store.

Precedence (U08): user.opt_out > calc.enabled > tenant.default.
A NULL tenant_id row is the GLOBAL default (permap U01/U08 contract).

PG forbids NULLs in composite PRIMARY KEY columns, so tenant_flags uses a
surrogate id PK. Uniqueness is enforced separately:
  - uq_tenant_flags_tenant_key (tenant_id, key): one row per tenant-scoped key
  - uq_tenant_flags_global on (key) WHERE tenant_id IS NULL: one global default
"""
from sqlalchemy import text, Index, Column, String, Boolean, BigInteger
from sqlalchemy.dialects.postgresql import UUID

from ..core.database import Base


class TenantFlag(Base):
    __tablename__ = "tenant_flags"
    __table_args__ = (
        Index('uq_tenant_flags_global', 'key', unique=True, postgresql_where=text('(tenant_id IS NULL)')),
        Index('uq_tenant_flags_tenant_key', 'tenant_id', 'key', unique=True),
    )
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    key = Column(String(100), nullable=False)
    value = Column(Boolean, nullable=False, default=False, server_default="false")

    def __repr__(self):
        return f"<TenantFlag(tenant_id={self.tenant_id}, key={self.key}, value={self.value})>"