"""``soil_erosion_profiles`` — org-wide RUSLE parameter presets (P7).

The middle layer of the soil-erosion parameter model: code default ▸ **this** ▸
per-forest override (``calculation.result_data['soil_erosion_params']``). A
super-admin keeps a handful of physiography presets; a forest with no per-forest
override auto-picks the profile whose ``physiography_hint`` matches its dominant
``admin.physiography`` zone. ``params`` is a *sparse* :class:`SoilErosionParams`
patch (same shape as the per-forest override). Migration 077.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class SoilErosionProfile(Base):
    __tablename__ = "soil_erosion_profiles"

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
