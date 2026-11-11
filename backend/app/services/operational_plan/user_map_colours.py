"""The colours a user changed for a map in the workspace's Analysis maps group, as the print maps and the map tiles read them.

One place for three things, so the document, the Sustainable FM / Hazard tabs and the workspace tiles can never disagree:

* which Analysis-maps id belongs to which map variable (``SPEC_TO_ANALYSIS``),
* how a saved colour set is read (``saved_renderer`` / ``indexed_overrides``),
* how it is laid over a map's default colours (``apply``).

Saved shape (``result_data.layer_renderers['analysis:<id>']``):

* the three SFM maps keep their renderer (categorized / graduated, see ``thematic_overlay._with_user_colours``);
* the hazard maps save ``{"mode": "indexed", "colors": {"<class index>": "#rrggbb", ...}}`` — ONLY the classes the user
  changed, so a map the user never touched keeps its default look and its old cache key.

Strictly per forest. The system palette is never edited; "Default colours" just deletes the saved entry. Reading never raises:
a malformed entry is ignored (a document must still build, a tile must still draw).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

_LSI_FACTORS = (
    "slope", "lithology", "curvature_twi", "dist_drainage", "dist_road",
    "landcover", "landcover_change", "aspect", "rainfall", "soil_texture",
)

# print-map spec key -> Analysis-maps id (frontend lib/analysisMaps.ts)
SPEC_TO_ANALYSIS: dict[str, str] = {
    "sfm__forest_type": "sfm_type",
    "sfm__orientation": "sfm_orientation",
    "sfm__gs_vs_threshold": "sfm_stock",
    "soil__annual_loss": "hazard_soil",
    "soil__annual_loss__user_group": "hazard_soil",
    "hazard__landslide_susceptibility": "hazard_lsi",
    "hazard__landslide_susceptibility__user_group": "hazard_lsi",
    "hazard__landslide_prone_area": "hazard_prone",
    "hazard__factor_of_safety": "hazard_fs",
    "hazard__factor_of_safety__user_group": "hazard_fs",
    **{f"soil__factor_{k}": f"hazard_f_soil_{k}" for k in ("r", "k", "ls", "c")},
    **{f"hazard__lsi_factor_{n}": f"hazard_f_lsi_{n}" for n in _LSI_FACTORS},
    # the workspace chart (field-inventory glyph): class-indexed like the hazard maps
    "unit__dbh_class_stock__stackbar": "chart_timber",
    "unit__dbh_class_count__stackbar": "chart_dbh_stems",
    "unit__dbh_gs_mai_aah__stackbar": "chart_dbh_gs_mai_aah",
    "unit__dbh_class_count__pie": "chart_dbh_pie",
    "unit__dbh_composition__waffle": "chart_dbh_waffle",
    "unit__regen_pole_tree__ternary": "chart_regen_pole_tree",
    "unit__timber_firewood__stackbar": "chart_timber_firewood",
    "unit__agb_bgb__stackbar": "chart_biomass",
    "unit__species_composition__pie": "chart_species",
}


def _register_unit_maps() -> None:
    """The single-number field-inventory maps ("Colour by"): keyed by class index, or by category value for the categorical ones."""
    from app.services.operational_plan import unit_maps

    for map_id, (spec_key, _suffix) in unit_maps.FI_MAPS.items():
        SPEC_TO_ANALYSIS[spec_key] = map_id


_register_unit_maps()


def saved_renderer(db: Any, calculation_id: UUID, analysis_id: str) -> Optional[dict]:
    """The saved colour entry for one Analysis map of one forest, or ``None``. Never raises."""
    try:
        from app.models.calculation import Calculation

        calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        saved = ((calc.result_data or {}).get("layer_renderers") or {}).get(f"analysis:{analysis_id}") if calc else None
        return saved if isinstance(saved, dict) else None
    except Exception:  # noqa: BLE001 -- a colour preference must never stop a document or a tile
        logger.warning("could not read the saved colours for %s", analysis_id, exc_info=True)
        return None


def indexed_overrides(saved: Optional[dict]) -> dict[str, str]:
    """``{"<class index>": "#rrggbb"}`` from an ``indexed`` entry; anything malformed is dropped."""
    if not saved or saved.get("mode") != "indexed" or not isinstance(saved.get("colors"), dict):
        return {}
    out: dict[str, str] = {}
    for k, v in saved["colors"].items():
        if isinstance(v, str) and HEX.match(v) and re.fullmatch(r"[A-Za-z0-9_]{1,40}", str(k)):
            out[str(int(k)) if str(k).isdigit() else str(k)] = v  # a class index, or a category value (Good, production …)
    return out


def apply(colours: list[str], overrides: Optional[dict[str, str]]) -> list[str]:
    """``colours`` with each overridden class index replaced; the very same list when there is nothing to apply."""
    if not overrides:
        return colours
    return [overrides.get(str(i)) or c for i, c in enumerate(colours)]


def hazard_overrides(db: Any, calculation_id: UUID, key: str) -> dict[str, str]:
    """Overrides for a hazard TILE key (``soil``, ``lsi``, ``fs``, ``prone``, ``f_soil_r`` …)."""
    return indexed_overrides(saved_renderer(db, calculation_id, f"hazard_{key}"))


def signature(overrides: Optional[dict[str, str]]) -> str:
    """Short stable digest, for cache keys and ETags ('' when there is none)."""
    if not overrides:
        return ""
    return hashlib.sha1(json.dumps(overrides, sort_keys=True).encode()).hexdigest()[:8]  # noqa: S324 -- cache key
