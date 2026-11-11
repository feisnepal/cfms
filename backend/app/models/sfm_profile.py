"""``sfm_profiles`` — org-wide Sustainable-Forest-Management parameter presets.

The middle layer of the 3-tier SFM parameter model: code default ▸ **this** ▸
per-forest override (``calculation.result_data['sfm_params']``). A super-admin
keeps a handful of physiography presets; a forest with no per-forest override
auto-picks the profile whose ``physiography_hint`` matches its dominant
``admin.physiography`` zone. ``params`` is a *sparse* ``SfmParamsPatch``
(same shape as the per-forest override). Migration 083.

Exact shape of ``soil_erosion_profiles`` (077) / ``hazard_vuln_profiles`` (078).
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class SfmProfile(Base):
    __tablename__ = "sfm_profiles"

    key = Column(String(40), primary_key=True)
    label_ne = Column(String(120), nullable=False)
    label_en = Column(String(120), nullable=False)
    # matched verbatim against admin.physiography."physiography Zone"
    physiography_hint = Column(String(60), nullable=True)
    params = Column(JSONB, nullable=False, server_default="{}")
    is_active = Column(Boolean, nullable=False, server_default="true")
    sort_order = Column(Integer, nullable=False, server_default="0")
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
