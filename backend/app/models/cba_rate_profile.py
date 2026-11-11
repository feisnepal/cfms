"""``cba_rate_profiles`` — org-wide default depot / market rates for the CBA.

The middle layer of the rate model: code ``FALLBACK_RATES`` ▸ **this** ▸
per-scenario ``default_rates``. v1 keeps a single row (``key = 'global'``, see
``CBA_MODULE_PLAN.md`` D4); the shape matches ``hazard_vuln_profiles`` so it can
grow physiography-keyed rows later. Migration 080.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class CbaRateProfile(Base):
    __tablename__ = "cba_rate_profiles"

    key = Column(String(40), primary_key=True)
    label = Column(String(120), nullable=False)
    rates = Column(JSONB, nullable=False, server_default="{}")
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
