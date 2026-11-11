"""The legend of a Sustainable Forest Management map, from what THIS forest actually has (owner request 2026-10-12).

The SFM tab used to print the whole palette under its map (all 14 forest types, every orientation, fixed stock classes) whether or not the
forest has them. This builds the legend the way the print map colours its units - the same spec, the same colour functions, the user's own
colour changes laid over - and keeps only the classes that occur, with how many units and how many hectares each covers.

Read-only: it reads the stored SFM result and the unit geometries and never builds or changes anything.
"""
from __future__ import annotations

import logging
from typing import Any, Dict
from uuid import UUID

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SFM_MAP_KEYS = ("sfm__forest_type", "sfm__orientation", "sfm__gs_vs_threshold")


def _leaf_units(db: Session, calculation_id: UUID) -> list[dict]:
    """The units the map actually paints - the print map's own loader, so the legend counts exactly the units the PNG colours."""
    from app.services.operational_plan import thematic_overlay as to

    return to._units_with_geometry(db, calculation_id)


def build_legend(db: Session, calculation_id: UUID, spec_key: str, variant: str = "baseline") -> Dict[str, Any]:
    """``{state, key, total_ha, classes: [{key, color, label_ne, label_en, count, area_ha, share_pct}]}``."""
    from app.services.operational_plan import thematic_overlay as to
    from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS
    from app.services.operational_plan.unit_maps import build_unit_map

    if spec_key not in SFM_MAP_KEYS:
        raise KeyError(spec_key)
    values = to._load_sfm_unit_values(db, calculation_id, variant=variant)
    if not values:
        return {"state": "not_computed", "key": spec_key}
    spec = to._with_user_colours(db, calculation_id, BUILTIN_THEMEMAP_SPECS[spec_key])
    built = build_unit_map(_leaf_units(db, calculation_id), values, spec)
    if built.get("state") != "ready":
        return {"state": built.get("state", "no_data"), "key": spec_key}
    total = sum(float(c.get("area_ha") or 0.0) for c in built["legend"])
    classes = [
        {
            "key": str(c["key"]),
            "color": c["color"],
            "label_ne": c.get("label_ne") or c.get("label") or "",
            "label_en": c.get("label_en") or c.get("label") or "",
            "count": int(c.get("count") or 0),
            "area_ha": round(float(c.get("area_ha") or 0.0), 2),
            "share_pct": round(100.0 * float(c.get("area_ha") or 0.0) / total, 1) if total > 0 else 0.0,
        }
        for c in built["legend"]
    ]
    return {"state": "ready", "key": spec_key, "variant": variant, "custom_colours": bool(built.get("custom_colours")),
            "total_ha": round(total, 2), "classes": classes}
