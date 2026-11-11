"""``sfm_forest_type_prescriptions`` — the दिगो वन व्यवस्थापन कार्यविधि, २०७९
अनुसूची-१ as data (14 rows).

The single source of truth for the guideline: for a forest type (सि.नं. 1–14),
which species groups / zone / slope band / plantation-vs-natural trigger it, its
management orientation, and — per regeneration branch (क / ख) — the silvicultural
system, felling / rotation cycle, regeneration method, mother-tree retention and
the **yield rule** (a step function on ≥ 40 cm growing stock per hectare, or a
stem-count target, or salvage-only).

Super-admin editable via ``PUT /admin/sfm-prescriptions/{type_no}`` (P7) so the
guideline stays data, never Python. Seeded by
``scripts/seed_sfm_prescriptions.py`` (called from migration 082, re-runnable
standalone).

``branches`` JSONB shape — see ``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §3.4::

    {
      "<branch>": {                         # "adequate" | "inadequate" | "default"
        "method": "selection_felling_cycle" | "shelterwood_periodic_block"
                  | "stem_count" | "area_coupe",
        "system_ne": "…", "system_en": "…",
        "felling_cycle_years": 10, "regeneration_period_years": null,
        "rotation_years": 80,               # int OR [min, max] — informational
        "regen_method_ne": "…", "regen_method_en": "…",
        "mother_trees_per_ha": [15, 25],    # shelterwood; null otherwise
        "yield_rules": {
          "basis": "growing_stock_pct_ge40" | "stem_count" | "area_volume" | "none",
          "steps": [ {"gs_per_ha_min": 200, "gs_per_ha_max": null, "pct": 2.0}, … ],
          "target_stems_per_ha": [100, 150],
          "note_ne": "…", "note_en": "…"
        },
        "note_ne": "…", "note_en": "…"      # the अनुसूची-१ row note
      }
    }
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app.core.database import Base


class SfmForestTypePrescription(Base):
    __tablename__ = "sfm_forest_type_prescriptions"

    type_no = Column(Integer, primary_key=True, autoincrement=False)  # सि.नं. 1–14
    name_ne = Column(String(200), nullable=False)
    name_en = Column(String(200), nullable=False)

    # Classifier triggers. `zone_triggers` == [] means "any zone".
    species_groups = Column(ARRAY(String(32)), nullable=False, server_default="{}")
    zone_triggers = Column(ARRAY(String(32)), nullable=False, server_default="{}")
    slope_band = Column(SmallInteger, nullable=True)  # 1..4, types 1–3 only
    origin = Column(String(20), nullable=True)  # 'natural' | 'plantation' | NULL

    orientation = Column(
        String(20), nullable=False
    )  # Production / Conservation / Protection / …

    branches = Column(JSONB, nullable=False)  # see the module docstring

    notes_ne = Column(Text, nullable=True)
    notes_en = Column(Text, nullable=True)

    is_active = Column(Boolean, nullable=False, server_default="true")
    sort_order = Column(Integer, nullable=False, server_default="0")

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<SfmForestTypePrescription type_no={self.type_no} {self.name_en!r}>"
