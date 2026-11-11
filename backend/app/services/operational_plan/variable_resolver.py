"""Template variable resolver for Operational Plan documents.

Resolves {{variable}} placeholder patterns in OP document content by
looking up each variable in the registry, collecting data from all system
modules, formatting values, and producing the final display string.
Supports simple string/number substitution, nested dict traversal, and
table rendering from list-type variables.
# business: resolves 487 registered variables from collected data across 20+ modules
# constraint: variable pattern {{key}} — key must match registry or resolution returns None
# constraint: table-type variables rendered as formatted HTML/plain tables with fallback
# why: decouples template content from data sources — adding new variables needs no template changes

Key functions:
    resolve_variables() — main entry point for template resolution
    _resolve_table() — renders list-type variables as HTML/plain tables

See also:
    .variable_registry — variable definitions with metadata
    .data_collector — raw data collection from all modules
"""

import re
from datetime import datetime, timezone
from typing import Dict, Any, Iterable, Optional, List, Union
from uuid import UUID

from sqlalchemy.orm import Session
from nepali_datetime import date as nepali_date

from app.core.constants import IPCC_CO2R
from app.models.operational_plan import OperationalPlan
from app.models.calculation import Calculation
from .variable_registry import VARIABLE_ALIASES, VARIABLE_REGISTRY, VariableDef
from .data_collector import collect_all_op_data
from app.utils.number_format import format_devanagari

import logging

logger = logging.getLogger(__name__)


VARIABLE_PATTERN = re.compile(r"\{\{(\w+(?::\w+)*)\}\}")
_SENTINEL = object()


_KEY_ALIAS: Dict[tuple, str] = {
    # calculation -> basic_info
    ("basic_info", "calculation_status"): "status",

    # raster -> raster_analysis (nested under sub-objects)
    ("raster_analysis", "elevation_min_m"): "elevation.min_m",
    ("raster_analysis", "elevation_max_m"): "elevation.max_m",
    ("raster_analysis", "elevation_mean_m"): "elevation.mean_m",
    ("raster_analysis", "slope_dominant_class"): "slope.dominant_class",
    ("raster_analysis", "slope_percentages"): "slope.percentages",
    ("raster_analysis", "aspect_dominant"): "aspect.dominant",
    ("raster_analysis", "aspect_percentages"): "aspect.percentages",
    ("raster_analysis", "canopy_dominant_class"): "canopy.dominant_class",
    ("raster_analysis", "canopy_percentages"): "canopy.percentages",
    ("raster_analysis", "canopy_mean_m"): "canopy.mean_m",
    ("raster_analysis", "biomass_agb_mean"): "biomass.agb_mean",
    ("raster_analysis", "biomass_agb_total"): "biomass.agb_total",
    ("raster_analysis", "biomass_carbon_stock"): "biomass.carbon_stock",
    ("raster_analysis", "forest_health_dominant"): "forest_health.dominant",
    ("raster_analysis", "forest_health_percentages"): "forest_health.percentages",
    ("raster_analysis", "forest_type_dominant"): "forest_type.dominant",
    ("raster_analysis", "forest_type_percentages"): "forest_type.percentages",
    ("raster_analysis", "landcover_dominant"): "landcover.dominant",
    ("raster_analysis", "landcover_percentages"): "landcover.percentages",
    # 1984 land use: the analysis stores it under landcover_historical, so the flat names never found it (the OP printed nothing)
    ("raster_analysis", "landcover_1984_dominant"): "landcover_historical.landcover_1984_dominant",
    ("raster_analysis", "landcover_1984_percentages"): "landcover_historical.landcover_1984_percentages",
    ("raster_analysis", "landcover_1984_area_ha"): "landcover_historical.landcover_1984_area_ha",
    ("raster_analysis", "forest_loss_hectares"): "forest_loss_gain.loss_hectares",
    ("raster_analysis", "forest_gain_hectares"): "forest_loss_gain.gain_hectares",
    ("raster_analysis", "forest_loss_by_year"): "forest_loss_gain.loss_by_year",
    ("raster_analysis", "temperature_mean_c"): "temperature.mean_c",
    ("raster_analysis", "temperature_min_c"): "temperature.min_c",
    ("raster_analysis", "temperature_max_c"): "temperature.max_c",
    ("raster_analysis", "precipitation_mean_mm"): "precipitation.mean_mm",
    ("raster_analysis", "precipitation_min_mm"): "precipitation.min_mm",
    ("raster_analysis", "precipitation_max_mm"): "precipitation.max_mm",
    ("raster_analysis", "soil_dominant_type"): "soil.dominant_type",
    ("raster_analysis", "soil_percentages"): "soil.percentages",
    ("raster_analysis", "geology_percentages"): "geology.percentages",
    ("raster_analysis", "physiography_percentages"): "physiography.percentages",
    ("raster_analysis", "ecoregion_percentages"): "ecoregion.percentages",
    # Category B raster hybrid aliases
    ("raster_analysis", "altitude_min_m"): "elevation.min_m",
    ("raster_analysis", "altitude_max_m"): "elevation.max_m",
    ("raster_analysis", "altitude_mean_m"): "elevation.mean_m",
    ("raster_analysis", "dominant_slope"): "slope.dominant_class",
    ("raster_analysis", "dominant_aspect"): "aspect.dominant",
    ("raster_analysis", "dominant_soil"): "soil.dominant_type",
    ("raster_analysis", "crown_density_pct"): "canopy.mean_m",

    # boundary
    ("boundary", "boundary_features_east"): "features.east",
    ("boundary", "boundary_features_west"): "features.west",
    ("boundary", "boundary_features_north"): "features.north",
    ("boundary", "boundary_features_south"): "features.south",
    ("boundary", "boundary_forest_extent_data"): "whole_forest_extent",
    ("boundary", "extent_n"): "whole_forest_extent.N",
    ("boundary", "extent_s"): "whole_forest_extent.S",
    ("boundary", "extent_e"): "whole_forest_extent.E",
    ("boundary", "extent_w"): "whole_forest_extent.W",

    # block
    ("blocks", "blocks_count"): "total_blocks",
    ("blocks", "blocks_with_data"): "blocks",

    # species
    ("species", "species_role_counts"): "species_by_role",

    # inventory (registry uses inventory_ prefix, data does not)
    ("inventory", "inventory_total_trees"): "total_trees",
    ("inventory", "inventory_mother_trees_count"): "mother_trees_count",
    ("inventory", "inventory_felling_trees_count"): "felling_trees_count",
    ("inventory", "inventory_seedling_count"): "seedling_count",
    ("inventory", "inventory_total_volume_m3"): "total_volume_m3",
    ("inventory", "inventory_total_net_volume_m3"): "total_net_volume_m3",
    ("inventory", "inventory_total_net_volume_cft"): "total_net_volume_cft",
    ("inventory", "inventory_total_firewood_m3"): "total_firewood_m3",
    ("inventory", "inventory_total_firewood_chatta"): "total_firewood_chatta",
    ("inventory", "inventory_species_composition"): "species_summary",
    ("inventory", "inventory_dbh_distribution"): "dbh_summary",
    ("inventory", "inventory_block_summary"): "block_summary",

    # field_inventory (Category B aliases)
    ("field_inventory", "growing_stock_m3_per_ha"): "fi_growing_stock_m3_per_ha",
    ("field_inventory", "biomass_t_per_ha"): "fi_total_biomass_t_per_ha",
    ("field_inventory", "carbon_stock_tc_per_ha"): "fi_carbon_stock_tc_per_ha",

    # sampling (nested in designs[0])
    ("sampling", "sampling_type"): "designs.0.sampling_type",
    ("sampling", "sampling_total_points"): "designs.0.total_points",
    ("sampling", "sampling_total_blocks"): "designs.0.total_blocks",
    ("sampling", "sampling_plot_shape"): "designs.0.plot_shape",
    ("sampling", "sampling_plot_radius_m"): "designs.0.plot_radius_meters",
    ("sampling", "sampling_intensity_per_ha"): "designs.0.intensity_per_hectare",
    ("sampling", "sampling_requested_intensity"): "designs.0.requested_intensity_percent",
    ("sampling", "sampling_actual_intensity"): "designs.0.sampling_percentage",
    ("sampling", "sampling_block_summary"): "designs.0.blocks_info",
    ("sampling", "sampling_point_locations"): "sampling_point_locations",
    ("sampling", "sampling_forest_area_ha"): "designs.0.forest_area_hectares",
    ("sampling", "sampling_plot_area_sqm"): "designs.0.plot_area_sqm",
    ("sampling", "sampling_total_sampled_area_ha"): "designs.0.total_sampled_area_hectares",
    ("sampling", "fi_sampling_designs"): "designs",

    # fieldbook
    ("fieldbook", "fieldbook_total_points"): "total_points",
    ("fieldbook", "fieldbook_vertex_count"): "vertex_count",
    ("fieldbook", "fieldbook_interpolated_count"): "interpolated_count",
    ("fieldbook", "fieldbook_perimeter_m"): "perimeter_m",
    ("fieldbook", "fieldbook_avg_elevation_m"): "avg_elevation_m",
    ("fieldbook", "fieldbook_min_elevation_m"): "min_elevation_m",
    ("fieldbook", "fieldbook_max_elevation_m"): "max_elevation_m",
    ("fieldbook", "fieldbook_points"): "points",
    ("fieldbook", "fieldbook_block_summary"): "block_summary",
    # household (strip hh_ prefix)
    ("households", "hh_total_households"): "total_households",
    ("households", "hh_total_population"): "total_population",
    ("households", "hh_total_male"): "total_male",
    ("households", "hh_total_female"): "total_female",
    ("households", "hh_prosperity_distribution"): "prosperity_distribution",
    ("households", "hh_caste_distribution"): "caste_distribution",
    ("households", "hh_timber_demand_cft"): "timber_demand_cft",
    ("households", "hh_firewood_demand_bhari"): "firewood_demand_bhari",
    ("households", "hh_forest_based_occupation"): "forest_based_occupation",

    # committee (special mapping)
    ("committees", "uc_members"): "user_committee.members",
    ("committees", "uc_total_members"): "user_committee.total_members",
    ("committees", "ac_members"): "advisory_committee.members",
    ("committees", "ac_total_members"): "advisory_committee.total_members",
    ("committees", "fc_members"): "financial_committee.members",
    ("committees", "fc_total_members"): "financial_committee.total_members",
    ("committees", "uc_gender_distribution"): "user_committee.gender_distribution",
    ("committees", "uc_position_distribution"): "user_committee.position_distribution",
    ("committees", "uc_caste_distribution"): "user_committee.caste_distribution",

    # biodiversity (strip bio_ prefix)
    ("biodiversity", "bio_available"): "available",
    ("biodiversity", "bio_total_species"): "total_species",
    ("biodiversity", "bio_vegetation_count"): "vegetation_count",
    ("biodiversity", "bio_animal_count"): "animal_count",
    ("biodiversity", "bio_protected_count"): "protected_count",
    ("biodiversity", "bio_invasive_count"): "invasive_count",
    ("biodiversity", "bio_iucn_cr"): "iucn_breakdown.CR",
    ("biodiversity", "bio_iucn_en"): "iucn_breakdown.EN",
    ("biodiversity", "bio_iucn_vu"): "iucn_breakdown.VU",
    ("biodiversity", "bio_sub_category_breakdown"): "sub_category_breakdown",
    ("biodiversity", "bio_vegetation"): "vegetation",
    ("biodiversity", "bio_animals"): "animals",

    # activities (strip activities_ prefix)
    ("activities", "activities_available"): "available",
    ("activities", "activities_total"): "total_activities",
    ("activities", "activities_total_budget"): "total_budget",
    ("activities", "activities_list"): "activities",

    # user_group (strip ug_ prefix)
    ("user_group", "ug_available"): "available",
    ("user_group", "ug_total_settlements"): "total_settlements",
    ("user_group", "ug_buildings"): "buildings",
    # Settlement / Building
    ("user_group", "ug_total_buildings"): "total_buildings",
    ("user_group", "ug_total_building_area_m2"): "total_building_area_m2",
    ("user_group", "ug_avg_building_size_m2"): "avg_building_size_m2",
    ("user_group", "ug_small_buildings"): "small_buildings",
    ("user_group", "ug_medium_buildings"): "medium_buildings",
    ("user_group", "ug_large_buildings"): "large_buildings",
    ("user_group", "ug_small_pct"): "small_pct",
    ("user_group", "ug_medium_pct"): "medium_pct",
    ("user_group", "ug_large_pct"): "large_pct",
    # Land Cover / Area
    ("user_group", "ug_user_group_area_ha"): "user_group_area_ha",
    ("user_group", "ug_forest_overlap_area_ha"): "forest_overlap_area_ha",
    ("user_group", "ug_net_analysis_area_ha"): "net_analysis_area_ha",
    # Biomass / Volume
    ("user_group", "ug_total_biomass_mg"): "total_biomass_mg",
    ("user_group", "ug_total_volume_m3"): "total_volume_m3",
    ("user_group", "ug_avg_biomass_mg_per_ha"): "avg_biomass_mg_per_ha",
    ("user_group", "ug_avg_volume_m3_per_ha"): "avg_volume_m3_per_ha",
    # Land Cover Classes (list)
    ("user_group", "ug_land_cover_classes"): "land_cover_classes",

    # section_generators
    ("section_generators", "fieldbook_narration"): "section:fieldbook_narration",
    # yearly_plan (strip ya_ prefix)
    ("yearly_plan", "ya_available"): "available",
    ("yearly_plan", "ya_year_summary"): "year_summary",
    ("yearly_plan", "ya_plan_matrix"): "plan_matrix",
    ("yearly_plan", "ya_program_budget"): "program_budget",
    ("yearly_plan", "ya_total_budget_by_year"): "total_budget_by_year",
    ("yearly_plan", "ya_total_ten_year_budget"): "total_ten_year_budget",
    ("yearly_plan", "ya_program_pie_data"): "program_pie_data",
    ("yearly_plan", "ya_budget_year_trend"): "budget_year_trend",
    ("yearly_plan", "ya_activity_plan_detail"): "activity_plan_detail",

    # tree_mapping_analysis
    ("tree_mapping_analysis", "sm_forest_structure_status"): "sm_forest_structure_status",
    ("tree_mapping_analysis", "sm_mother_tree_coverage"): "sm_mother_tree_coverage",

    # fi_unit_* aliases → fi_block_* data
    ("field_inventory", "fi_total_plots"): "total_sample_plots",
    ("field_inventory", "fi_total_blocks"): "total_blocks",
    ("raster_analysis", "landcover_1984_dominant"): "landcover_historical.landcover_1984_dominant",
    ("raster_analysis", "landcover_1984_percentages"): "landcover_historical.landcover_1984_percentages",
    ("raster_analysis", "landcover_1984_area_ha"): "landcover_historical.landcover_1984_area_ha",
    ("field_inventory", "fi_unit_regeneration_status"): "fi_block_regeneration_status",
    ("field_inventory", "fi_unit_dbh_class_growing_stock"): "fi_block_dbh_class_growing_stock",
    ("field_inventory", "fi_unit_dbh_class_growing_stock_np"): "fi_block_dbh_class_growing_stock_np",
    ("field_inventory", "fi_unit_summaries"): "fi_block_summaries",
    ("field_inventory", "fi_unit_tree_count_per_ha"): "fi_block_tree_count_per_ha",
    ("field_inventory", "fi_unit_pole_tree_volume"): "fi_block_pole_tree_volume",
    ("field_inventory", "fi_unit_growing_stock"): "fi_block_growing_stock",
    ("field_inventory", "fi_unit_basal_area"): "fi_block_basal_area",
    ("field_inventory", "fi_unit_satellite_volume"): "fi_block_satellite_volume",
    ("field_inventory", "fi_unit_condition_growth"): "fi_block_condition_growth",
    ("field_inventory", "fi_unit_biomass_carbon"): "fi_block_biomass_carbon",

    # ti_unit_* aliases → ti_block_* data
    ("field_inventory", "ti_unit_summaries"): "ti_block_summaries",
    ("field_inventory", "ti_unit_tree_count_total"): "ti_block_tree_count_total",
    ("field_inventory", "ti_unit_pole_tree_volume"): "ti_block_pole_tree_volume",
    ("field_inventory", "ti_unit_growing_stock"): "ti_block_growing_stock",
    ("field_inventory", "ti_unit_basal_area"): "ti_block_basal_area",
    ("field_inventory", "ti_unit_satellite_volume"): "ti_block_satellite_volume",
    ("field_inventory", "ti_unit_condition_growth"): "ti_block_condition_growth",
    ("field_inventory", "ti_unit_biomass_carbon"): "ti_block_biomass_carbon",
    ("field_inventory", "ti_unit_regeneration_status"): "ti_block_regeneration_status",
}


# plan-form fields that the forest's own metadata (Forest Metadata tab) can supply when the plan form is empty
_FOREST_PLAN_DETAILS = frozenset({
    "sub_division_chief", "forest_management_section_chief", "division_forest_officer",
    "technical_assistance_org", "cf_handover_date", "cf_first_renewal_date", "cf_history_note",
})


# plan-form fields the SFM classification already answers (silviculture_derived.py)
_SILVICULTURE_DERIVED = (
    "silviculture_system", "rotation_years", "regeneration_period_years", "mother_tree_spacing_m",
)

_UG_FOLLOWS_FOREST = {
    "ug_province": "province", "ug_district": "forest_district", "ug_municipality": "forest_municipality",
    "ug_ward": "forest_ward", "ug_division": "division", "ug_sub_division": "sub_division",
    "ug_municipality_type": "forest_municipality_type",
}


# 1984 land-use classes are stored in English; the plan is in Nepali
def _class_label(var_name: str, key: str) -> str:
    if var_name.startswith("landcover_1984"):
        from app.core.landcover_1984 import LC1984_LABELS

        return (LC1984_LABELS.get(key) or {}).get("ne") or key
    return str(key)


def format_breakdown(values: dict, var_name: str = "") -> Optional[str]:
    """A ``{class: number}`` variable as one line of text, largest first: ``वन ९६.०९%, खेतीयोग्य ३.८१%``.

    The percentage and area variables are dicts; a dict used inside a sentence used to come out empty. Returns ``None`` for a
    dict that is not a plain class-to-number breakdown (the caller then leaves it for the table builders)."""
    if not values or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values.values()):
        return None
    unit = "%" if "percent" in var_name else (" हे." if var_name.endswith("_ha") else "")
    parts = [
        f"{_class_label(var_name, k)} {format_devanagari(v, 2)}{unit}"
        for k, v in sorted(values.items(), key=lambda kv: kv[1], reverse=True)
        if v
    ]
    return ", ".join(parts) if parts else None


class VariableResolver:
    """Resolves OP template variables from collected data using the registry.

    Central place all OP template content flows through before document
    generation. Caches raw data per-request to avoid repeated DB queries.
    """

    def __init__(
        self,
        db: Session,
        calculation_id: UUID,
        plan: OperationalPlan,
        render_mode: str = "values",
    ):
        self.db = db
        self.calculation_id = calculation_id
        self.plan = plan
        # "values" (default) resolves every {{token}} to its data value.
        # "tokens" leaves {{token}} text untouched — for the designer / author
        # -mode preview toggle, so a template author can trace which variable
        # sits where without the numbers on top
        # (OP_TEMPLATE_MANAGEMENT_PLAN.md §3.2, T2).
        self.render_mode = render_mode
        self._raw_data: Optional[Dict[str, Any]] = None
        self._resolved: Dict[str, Any] = {}

    def get_raw_data(self) -> Dict[str, Any]:
        if self._raw_data is None:
            self._raw_data = collect_all_op_data(self.db, str(self.calculation_id))
        return self._raw_data

    @staticmethod
    def _deep_get(data: Union[Dict, List, Any], path: str) -> Any:
        if not path:
            return None
        current = data
        for key in path.split("."):
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, (list, tuple)):
                try:
                    idx = int(key)
                    current = current[idx] if 0 <= idx < len(current) else None
                except (ValueError, IndexError):
                    return None
            else:
                return None
            if current is None:
                return None
        return current

    def resolve_all(self) -> Dict[str, Any]:
        for key, var_def in VARIABLE_REGISTRY.items():
            try:
                self._resolved[key] = self._resolve_single(var_def)
            except Exception:
                # Every {{variable}} in a statutory document comes through here. None
                # renders as a blank where a measured figure belongs.
                logger.exception(
                    "variable %s could not be resolved - it will be blank in the "
                    "operational plan", key,
                )
                self._resolved[key] = None
        return self._resolved

    def resolve_keys(self, keys: Iterable[str]) -> Dict[str, Any]:
        """Resolve only the named registry keys.

        :meth:`resolve_all` walks every registered key, and `_resolve_single`
        dispatches by prefix, so it invokes the chart and table resolvers for
        every chart in the registry whether or not the document uses them. A
        readiness check only needs the handful of tokens one plan actually
        references, so it asks for those instead.

        The two failure modes stay distinguishable, which is the whole point:

        * a key **absent from the result** is not in the registry (a typo);
        * a key **present with the value ``None``** is registered but has no
          data for this forest.

        :meth:`resolve_node_content` collapses both to ``""``, which is why a
        plan could previously report success while rendering a blank where a
        measured figure belongs.
        """
        out: Dict[str, Any] = {}
        for key in keys:
            var_def = VARIABLE_REGISTRY.get(key)
            if var_def is None:
                continue
            try:
                out[key] = self._resolve_single(var_def)
            except Exception:
                logger.exception(
                    "variable %s could not be resolved - it will be blank in "
                    "the operational plan", key,
                )
                out[key] = None
        return out

    def _no_data(self) -> str:
        """Red-bold 'No data' marker text, in the plan's language."""
        from . import no_data

        lang = None
        try:
            lang = (self.get_raw_data().get("basic_info") or {}).get("language")
        except Exception:  # noqa: BLE001 -- the language only picks the words; Nepali is the default
            logger.exception("no-data language lookup failed")
        return no_data.marked(lang)

    def resolve_node_content(self, content: str) -> str:
        # Author-mode / designer preview: keep every {{token}} verbatim so the
        # variable structure of the document stays visible.
        if self.render_mode == "tokens":
            return content

        def _replacer(match):
            var_name = match.group(1)
            # {{inline_table:N}} is a placement instruction, not data: the builder's
            # split (op_docx_builder._add_text_content) places the table and must see
            # the token intact — resolving it here used to print a red "No data"
            # paragraph where the table belongs (ND-1, RC1).
            if var_name.startswith(("chart:", "map:", "thememap:", "opsmap:", "table:", "asset:", "inline_table:")) or var_name.endswith(":full"):
                return match.group(0)
            var_def = VARIABLE_REGISTRY.get(var_name)
            if var_def is None:
                # an unknown key (a typo) and a key with no data are both shown, never silently dropped (owner, 2026-10-16)
                return self._no_data()
            if var_name not in self._resolved:
                try:
                    self._resolved[var_name] = self._resolve_single(var_def)
                except Exception:  # noqa: BLE001 -- logged; the document shows "No data" instead of failing the export
                    logger.exception("variable %s could not be resolved - the plan will show 'No data' for it", var_name)
                    self._resolved[var_name] = None
            val = self._resolved[var_name]
            if val is None:
                return self._no_data()
            if isinstance(val, dict):
                text = format_breakdown(val, var_name)
                return text if text is not None else match.group(0)
            if isinstance(val, list):
                return match.group(0)
            return format_devanagari(val, var_def.precision)

        return VARIABLE_PATTERN.sub(_replacer, content)

    def _resolve_single(self, var_def: VariableDef) -> Any:
        key = var_def.key
        if key.startswith("chart:"):
            return self._resolve_chart(var_def)
        if key.startswith(("thememap:", "opsmap:")):
            # THEMATIC_MAP_VARIABLES_PLAN §3.7 — the renderer (thematic_overlay)
            # does its own prereq check + placeholder, so this is always
            # "available" as a token; op_docx_builder dispatches on the prefix.
            from .thematic_map_spec import resolve_spec

            spec = resolve_spec(key)
            if spec is None:
                return None
            return {"type": "thememap", "spec_key": key, "available": True}
        if key.startswith("map:"):
            layer_name = key.split(":", 1)[1]
            if layer_name == "usergroup":
                from app.models.user_group import UserGroupExtent
                exists = self.db.query(UserGroupExtent.id).filter(
                    UserGroupExtent.calculation_id == self.calculation_id
                ).first() is not None
                if not exists:
                    return None
            return {"type": "map", "layer": layer_name, "available": True}
        if key.startswith("table:"):
            return self._resolve_table(var_def)
        if key.startswith("asset:"):
            return {"type": "asset", "name": key.split(":", 1)[1], "available": True}
        resolver_map = {
            "resolve_a": self._resolve_category_a,
            "resolve_b": self._resolve_hybrid,
            "resolve_c": self._resolve_user_input,
            "resolve_d": self._resolve_computed,
            "resolve_e": self._resolve_section_content,
            "resolve_f": self._resolve_template,
            "resolve_hybrid": self._resolve_hybrid,
            "resolve_user_input": self._resolve_user_input,
            "resolve_computed": self._resolve_computed,
            "resolve_section_content": self._resolve_section_content,
            "resolve_template": self._resolve_template,
            "resolve_kabuliyatnama_detail": self._resolve_kabuliyatnama_detail,
            "resolve_chairperson": self._resolve_chairperson,
        }
        resolver = resolver_map.get(var_def.resolver, self._resolve_category_a)
        return resolver(var_def)

    def _resolve_category_a(self, var_def: VariableDef) -> Any:
        data = self.get_raw_data()
        source_map = {
            "calculation": "basic_info",
            "raster": "raster_analysis",
            "boundary": "boundary",
            "block": "blocks",
            "species": "species",
            "inventory": "inventory",
            "field_inventory": "field_inventory",
            "fieldbook": "fieldbook",
            "sampling": "sampling",
            "household": "households",
            "committee": "committees",
            "biodiversity": "biodiversity",
            "activities": "activities",
            "yearly_activities": "yearly_plan",
            "user_group": "user_group",
            "section_generator": "section_generators",
            "compartment": "compartment",
            "tree_mapping_analysis": "tree_mapping_analysis",
            "soil_erosion": "soil_erosion",
            "hazard_vuln": "hazard_vuln",
            "cost_benefit": "cost_benefit",
            "sustainable_fm": "sustainable_fm",
            "plan_extras": "plan_extras",
            "dimension": "dimension",
        }
        section = source_map.get(var_def.source, "basic_info")
        section_data = data.get(section, {})

        if var_def.key in section_data:
            return section_data[var_def.key]

        path = _KEY_ALIAS.get((section, var_def.key))
        if path:
            return self._deep_get(section_data, path)

        # HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P1 — a canonical `hazard_*` key
        # reads from its legacy twin's payload slot (the collectors still emit
        # soil_loss_* / lsi_* / fs_* / hh_*).
        legacy = VARIABLE_ALIASES.get(var_def.key)
        if legacy is not None and legacy in section_data:
            return section_data[legacy]

        return None

    def _resolve_hybrid(self, var_def: VariableDef) -> Any:
        overrides = (self.plan.plan_metadata or {}).get("hybrid_overrides", {})
        if var_def.key in overrides:
            return overrides[var_def.key]
        system_val = self._resolve_category_a(var_def)
        if system_val is not None:
            return system_val
        return None

    def _forest_cf_code(self) -> Optional[str]:
        """The forest's community-forest code from the saved Forest Metadata (the national database code, Schedule 11)."""
        from app.services.forest_metadata_service import get_metadata

        try:
            stored = get_metadata(self.db, self.calculation_id)
        except Exception:  # noqa: BLE001 -- the document must still build; the plan's own typed value is the fallback
            logger.exception("variable_resolver: could not read the forest metadata code")
            return None
        return (stored.get("cf_national_code") or "").strip() or None if stored.get("persisted") else None

    def _resolve_user_input(self, var_def: VariableDef) -> Any:
        if var_def.key == "cf_code":
            # One code per forest: the saved Forest Metadata outranks anything typed into the plan's own form.
            saved = self._forest_cf_code()
            if saved:
                return saved
        from app.services.operational_plan.forest_shared_fields import SHARED_FIELDS

        if var_def.key in SHARED_FIELDS:
            # one place (Forest Metadata tab), no per-plan override; a value the plan typed before this rule is only
            # the last resort below, when the forest has none
            forest_value = self._shared_values().get(var_def.key)
            if forest_value:
                return forest_value
        user_inputs = (self.plan.plan_metadata or {}).get("user_inputs", {})
        val = user_inputs.get(var_def.key, _SENTINEL)
        if val is _SENTINEL or val is None:
            if var_def.key == "kabuliyatnama_date":
                return nepali_date.today().strftime("%Y/%m/%d")
            fallback_map = {
                "forest_municipality": "municipality",
                "forest_ward": "ward",
            }
            derived = self._form_field_fallback(var_def.key)
            if derived not in (None, ""):
                return derived
            if var_def.key in fallback_map:
                a_def = VARIABLE_REGISTRY.get(fallback_map[var_def.key])
                if a_def:
                    return self._resolve_category_a(a_def)
            return None
        return val

    # ── form fields the system already knows: used when the plan form has not been filled (a template preview
    #    runs against a forest with no plan at all) ──────────────────────────────────────────────────────────
    _DIGITS_NE = str.maketrans("0123456789", "०१२३४५६७८९")

    def _shared_values(self) -> Dict[str, str]:
        if not hasattr(self, "_shared_cache"):
            from app.services.operational_plan.forest_shared_fields import shared_values

            self._shared_cache = shared_values(self.db, self.calculation_id)
        return self._shared_cache

    def _forest_metadata_row(self):
        if not hasattr(self, "_fm_cache"):
            from app.models.forest_metadata import ForestMetadata

            try:
                self._fm_cache = self.db.query(ForestMetadata).filter(
                    ForestMetadata.calculation_id == self.calculation_id).first()
            except Exception:  # noqa: BLE001 -- a metadata lookup must not stop the document; the field stays blank
                logger.exception("variable_resolver: forest metadata could not be read")
                self._fm_cache = None
        return self._fm_cache

    def _silviculture_derived(self) -> Dict[str, Any]:
        if not hasattr(self, "_silv_cache"):
            from app.services.operational_plan import silviculture_derived

            self._silv_cache = {}
            try:
                calc = self.db.query(Calculation).filter(Calculation.id == self.calculation_id).first()
                sfm = ((calc.result_data or {}).get("sfm") or {}) if calc else {}
                self._silv_cache = silviculture_derived.derive(self.db, self.calculation_id, sfm) if sfm else {}
            except Exception:  # noqa: BLE001 -- the derivation is a fallback; without it the field stays blank
                logger.exception("variable_resolver: silviculture values could not be derived")
        return self._silv_cache

    @staticmethod
    def _fy_text(value) -> Optional[str]:
        """'2083/84', '2083/084' or '२०८३/०८४' -> '२०८३/०८४' (the plan form's fiscal-year format)."""
        import re as _re

        if not value:
            return None
        digits = str(value).translate(str.maketrans("०१२३४५६७८९", "0123456789"))
        m = _re.match(r"\s*(\d{4})\s*[/.-]\s*(\d{2,4})\s*$", digits)
        if not m:
            return None
        second = m.group(2)[-2:]
        return f"{m.group(1)}/0{second}".translate(VariableResolver._DIGITS_NE)

    def _form_field_fallback(self, key: str):
        meta = self._forest_metadata_row()
        data = self.get_raw_data()
        basic = data.get("basic_info", {}) or {}
        if key in _UG_FOLLOWS_FOREST:              # the group's location defaults to the forest's (as the plan form did)
            forest_key = _UG_FOLLOWS_FOREST[key]
            return self._shared_values().get(forest_key) or (basic.get("municipality_type") if key == "ug_municipality_type" else None)
        if key in _SILVICULTURE_DERIVED:           # ND-4: the SFM tab has already decided these; a typed value still wins
            return self._silviculture_derived().get(key)
        if key in _FOREST_PLAN_DETAILS:            # entered once on the Forest Metadata tab
            return (getattr(meta, key, None) or None) if meta else None
        if key == "forest_district":
            return (meta.district if meta else None) or basic.get("district")
        if key == "forest_municipality_type":
            return basic.get("municipality_type")
        if key == "division":
            return meta.division if meta else None
        if key == "sub_division":
            return meta.sub_division if meta else None
        if key in ("op_start_fy", "op_end_fy"):
            return self._fy_text(getattr(meta, "fy_start" if key == "op_start_fy" else "fy_end", None)) if meta else None
        if key == "op_preparation_year":
            fy = self._fy_text(getattr(meta, "fy_start", None)) if meta else None
            return int(fy[:4].translate(str.maketrans("०१२३४५६७८९", "0123456789"))) if fy else None
        if key == "plan_duration_years":
            return 10
        if key == "forest_type":
            return "प्राकृतिक"
        if key == "physiography_zone":
            pct = (data.get("raster_analysis", {}).get("physiography") or {}).get("percentages") or {}
            return max(pct, key=pct.get) if pct else None
        if key == "avg_crown_density_pct":
            ra = data.get("raster_analysis", {}) or {}
            val = ra.get("crown_density_pct") or (ra.get("canopy") or {}).get("crown_density_pct")
            return round(val) if isinstance(val, (int, float)) else None
        if key in ("cf_boundary_east", "cf_boundary_south", "cf_boundary_west", "cf_boundary_north"):
            feats = ((data.get("boundary") or {}).get("features") or {}).get(key.rsplit("_", 1)[1])
            if isinstance(feats, (list, tuple)):
                feats = ", ".join(str(f) for f in feats if f)
            return feats or None
        return None

    MONTH_NAMES_NP = (None, "वैशाख", "जेष्ठ", "असार", "श्रावण", "भदौ", "आश्विन", "कार्तिक", "मंसिर", "पौष", "माघ", "फाल्गुण", "चैत्र")
    DAY_NAMES_NP = ("आइतबार", "सोमबार", "मङ्गलबार", "बुधबार", "बिहिबार", "शुक्रबार", "शनिबार")

    def _resolve_kabuliyatnama_detail(self, var_def: VariableDef) -> Any:
        user_inputs = (self.plan.plan_metadata or {}).get("user_inputs", {})
        raw = user_inputs.get("kabuliyatnama_date", "")
        if not raw or not isinstance(raw, str):
            today_default = nepali_date.today()
            raw = today_default.strftime("%Y/%m/%d")
        parts = raw.split("/")
        if len(parts) != 3:
            return raw
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if var_def.key == "kabuliyatnama_date_year":
            return y
        if var_def.key == "kabuliyatnama_date_month":
            return m
        if var_def.key == "kabuliyatnama_date_day":
            return d
        if var_def.key == "kabuliyatnama_date_sentence":
            try:
                nd = nepali_date(y, m, d)
                month_name = self.MONTH_NAMES_NP[m] if 1 <= m <= 12 else str(m)
                day_name = self.DAY_NAMES_NP[nd.weekday()]
                return f"ईति सम्वत {format_devanagari(y)} साल {month_name} महिना {format_devanagari(d)} गते रोज {day_name} शुभम् ।"
            except (ValueError, OverflowError):
                return raw
        return raw

    def _resolve_chairperson(self, var_def: VariableDef) -> Any:
        data = self.get_raw_data()
        committees = data.get("committees", {})
        uc = committees.get("user_committee", {})
        members = uc.get("members", [])
        for m in members:
            if m.get("position") == "अध्यक्ष":
                return m.get("name")
        return None

    def _resolve_computed(self, var_def: VariableDef) -> Any:
        if not var_def.compute_fn:
            return None
        ctx = self._resolved if self._resolved else self.resolve_all()
        compute_map = {
            "compute_total_plan_area": lambda: ctx.get("total_area_hectares", 0),
            "compute_forest_area": lambda: self._compute_forest_area(ctx),
            "compute_non_forest_area": lambda: max(0, ctx.get("total_plan_area_ha", 0) - ctx.get("forest_area_ha", 0)),
            "compute_forest_pct": lambda: round(ctx.get("forest_area_ha", 0) / max(ctx.get("total_plan_area_ha", 1), 1) * 100, 2),
            "compute_total_growing_stock": lambda: ctx.get("growing_stock_m3_per_ha", 0) * ctx.get("forest_area_ha", 0),
            "compute_total_carbon_stock": lambda: ctx.get("carbon_stock_tc_per_ha", 0) * ctx.get("forest_area_ha", 0),
            "compute_total_co2": lambda: ctx.get("total_carbon_stock_tc", 0) * IPCC_CO2R,
            "compute_annual_increment": lambda: ctx.get("total_growing_stock_m3", 0) * (ctx.get("fi_mai_percent") or 0) / 100,
            "compute_forest_per_hh": lambda: round(ctx.get("forest_area_ha", 0) / max(ctx.get("hh_total_households", 1), 1), 2),
            "compute_plan_years_range": lambda: f"{ctx.get('plan_year_start', '')}-{ctx.get('plan_year_end', '')}",
            "compute_cf_area_provided": lambda: self._compute_cf_area_provided(),
        }
        fn = compute_map.get(var_def.compute_fn)
        return fn() if fn else None

    def _compute_forest_area(self, ctx: Dict) -> float:
        data = self.get_raw_data()
        blocks_data = data.get("blocks", {})
        sub_areas = blocks_data.get("sub_areas", {})
        forest_area = 0
        for cat, info in sub_areas.items():
            if "वन" in str(cat) or "forest" in str(cat).lower():
                forest_area += info.get("total_area_hectares", 0)
        if forest_area == 0:
            forest_area = data.get("basic_info", {}).get("effective_area_hectares", 0)
        return forest_area

    def _compute_cf_area_provided(self) -> float:
        data = self.get_raw_data()
        bi = data.get("basic_info", {})
        effective = bi.get("effective_area_hectares", 0)
        if effective:
            return effective
        blocks_data = data.get("blocks", {})
        blocks = blocks_data.get("blocks", [])
        return sum(b.get("effective_area_hectares", b.get("area_hectares", 0)) for b in blocks)

    def _resolve_section_content(self, var_def: VariableDef) -> Any:
        sections = {
            "section_6_previous_review": "विगतको कार्ययोजनाको समीक्षा गर्दा...",
            "section_8_production": "वन पैदावार उत्पादन निम्नानुसार गरिनेछ...",
            "section_16_prohibited": "सामुदायिक वनमा निम्न कार्यहरू निषेधित गरिएका छन्...",
            "section_17_penalties": "वन अपराध सम्बन्धी सजाय: ...",
            "section_18_misc": "अन्य विविध व्यवस्थाहरू: ...",
        }
        return sections.get(var_def.key, "")

    def _resolve_template(self, var_def: VariableDef) -> Any:
        now = datetime.now(timezone.utc)
        template_values = {
            "document_version": (self.plan.plan_metadata or {}).get("version", "2.0"),
            "generated_date": now.strftime("%Y-%m-%d"),
            "generated_by": "",
            "document_language": (self.plan.plan_metadata or {}).get("language", "NP"),
            "export_format": "DOCX",
            "plan_revision_number": (self.plan.plan_metadata or {}).get("revision", 1),
        }
        return template_values.get(var_def.key, "")

    # ── Chart color palette for village-friendly graphics ──
    # business: forest-green dominant palette chosen for intuitive readability at village level
    # constraint: 16 colors max — bars/pies with >16 categories cycle colors
    _CHART_COLORS = [
        "#2d5a27", "#5a8f4c", "#8bb87c", "#b8d9a5",
        "#3498db", "#2980b9", "#e67e22", "#d35400",
        "#e74c3c", "#c0392b", "#9b59b6", "#8e44ad",
        "#f1c40f", "#f39c12", "#1abc9c", "#16a085",
    ]

    def _resolve_chart(self, var_def: VariableDef) -> Optional[Dict[str, Any]]:
        key = var_def.key  # e.g. "chart:forest_type_pie"
        chart_key = key.replace("chart:", "")
        data = self.get_raw_data()

        def _pct_data(pct_dict: dict) -> dict:
            items = sorted(pct_dict.items(), key=lambda x: x[1], reverse=True)
            labels = [k for k, _ in items]
            values = [v for _, v in items]
            colors = self._CHART_COLORS[:len(labels)]
            return {"type": "pie", "labels": labels, "datasets": [{"data": values, "backgroundColor": colors}]}

        def _bar_data(labels: list, values: list, label: str = "Value") -> dict:
            colors = self._CHART_COLORS[:len(labels)]
            return {"type": "bar", "labels": labels, "datasets": [{"label": label, "data": values, "backgroundColor": colors}]}

        try:
            if chart_key == "forest_type_pie":
                pcts = data.get("raster_analysis", {}).get("forest_type", {}).get("percentages", {})
                return _pct_data(pcts) if pcts else None
            elif chart_key == "landcover_pie":
                pcts = data.get("raster_analysis", {}).get("landcover", {}).get("percentages", {})
                return _pct_data(pcts) if pcts else None
            elif chart_key == "ug_land_cover_classes_chart":
                lc_classes = data.get("user_group", {}).get("land_cover_classes", [])
                if lc_classes:
                    pcts = {c.get("class_name", f"Class {c.get('class_code', '')}"): c.get("percentage", 0) for c in lc_classes}
                    return _pct_data(pcts)
                return None
            elif chart_key == "slope_bar":
                pcts = data.get("raster_analysis", {}).get("slope", {}).get("percentages", {})
                if pcts:
                    return _bar_data(list(pcts.keys()), list(pcts.values()), "Percentage")
                return None
            elif chart_key == "aspect_rose":
                pcts = data.get("raster_analysis", {}).get("aspect", {}).get("percentages", {})
                if pcts:
                    return _pct_data(pcts)
                return None
            elif chart_key == "soil_bar":
                pcts = data.get("raster_analysis", {}).get("soil", {}).get("percentages", {})
                if pcts:
                    return _bar_data(list(pcts.keys()), list(pcts.values()), "Percentage")
                return None
            elif chart_key == "canopy_bar":
                pcts = data.get("raster_analysis", {}).get("canopy", {}).get("percentages", {})
                if pcts:
                    return _bar_data(list(pcts.keys()), list(pcts.values()), "Percentage")
                return None
            elif chart_key == "forest_health_pie":
                pcts = data.get("raster_analysis", {}).get("forest_health", {}).get("percentages", {})
                return _pct_data(pcts) if pcts else None
            elif chart_key == "species_composition_pie":
                species = data.get("inventory", {}).get("species_summary", {})
                if species:
                    items = sorted(species.items(), key=lambda x: x[1], reverse=True)[:10]
                    labels = [k for k, _ in items]
                    values = [v for _, v in items]
                    colors = self._CHART_COLORS[:len(labels)]
                    return {"type": "pie", "labels": labels, "datasets": [{"data": values, "backgroundColor": colors}]}
                return None
            elif chart_key == "species_composition_pie_fi":
                comp = data.get("field_inventory", {}).get("fi_species_composition", {})
                if comp:
                    items = sorted(comp.items(), key=lambda x: x[1], reverse=True)[:10]
                    labels = [k for k, _ in items]
                    values = [v for _, v in items]
                    colors = self._CHART_COLORS[:len(labels)]
                    return {"type": "pie", "labels": labels, "datasets": [{"data": values, "backgroundColor": colors}]}
                return None
            elif chart_key == "block_volume_bar":
                bs = data.get("inventory", {}).get("block_summary", {})
                if bs:
                    labels = list(bs.keys())
                    values = [v.get("total_volume", 0) for v in bs.values()]
                    return _bar_data(labels, values, "Volume (m³)")
                return None
            elif chart_key == "block_area_bar":
                blocks = data.get("blocks", {}).get("blocks", [])
                if blocks:
                    labels = [b.get("name", f"Block {i+1}") for i, b in enumerate(blocks)]
                    values = [b.get("area_hectares", 0) for b in blocks]
                    return _bar_data(labels, values, "Area (ha)")
                return None
            elif chart_key == "hh_prosperity_pie":
                dist = data.get("households", {}).get("prosperity_distribution", {})
                return _pct_data(dist) if dist else None
            elif chart_key == "hh_caste_bar":
                dist = data.get("households", {}).get("caste_distribution", {})
                if dist:
                    return _bar_data(list(dist.keys()), list(dist.values()), "Households")
                return None
            elif chart_key == "hh_caste_pie":
                dist = data.get("households", {}).get("caste_distribution", {})
                return _pct_data(dist) if dist else None
            elif chart_key == "hh_prosperity_bar":
                dist = data.get("households", {}).get("prosperity_distribution", {})
                if dist:
                    return _bar_data(list(dist.keys()), list(dist.values()), "घरधुरी")
                return None
            elif chart_key == "hh_demand_supply_bar":
                ds = data.get("demand_supply", {})
                if ds and ds.get("demand"):
                    products = ["firewood_bhari", "grass_bhari", "bedding_bhari", "timber_cft", "poles_count"]
                    ds_labels = {
                        "firewood_bhari": "दाउरा भारी",
                        "grass_bhari": "घाँस भारी",
                        "bedding_bhari": "सोतर भारी",
                        "timber_cft": "काठ क्यू.फि.",
                        "poles_count": "खाँवा संख्या",
                    }
                    labels = [ds_labels.get(k, k) for k in products]
                    demand_vals = [ds.get("demand", {}).get(k, 0) or 0 for k in products]
                    supply_vals = [ds.get("total_supply", {}).get(k, 0) or 0 for k in products]
                    colors = ["#dc2626", "#059669"]
                    return {
                        "type": "bar",
                        "labels": labels,
                        "datasets": [
                            {"label": "माग", "data": demand_vals, "backgroundColor": colors[0]},
                            {"label": "आपूर्ति", "data": supply_vals, "backgroundColor": colors[1]},
                        ],
                    }
                return None
            elif chart_key == "demand_supply_bar":
                ds = data.get("demand_supply", {})
                if ds and ds.get("demand"):
                    products = ["firewood_bhari", "grass_bhari", "bedding_bhari", "timber_cft", "poles_count"]
                    ds_labels = {
                        "firewood_bhari": "दाउरा भारी",
                        "grass_bhari": "घाँस भारी",
                        "bedding_bhari": "सोतर भारी",
                        "timber_cft": "काठ क्यू.फि.",
                        "poles_count": "खाँवा संख्या",
                    }
                    labels = [ds_labels.get(k, k) for k in products]
                    demand_vals = [ds.get("demand", {}).get(k, 0) or 0 for k in products]
                    cf_reg_vals = []
                    for k in products:
                        v = ds.get("supply_cf_regular", {}).get(k, 0)
                        cf_reg_vals.append(v if isinstance(v, (int, float)) else 0)
                    cf_aah_vals = []
                    for k in products:
                        v = ds.get("supply_cf_aah", {}).get(k, 0)
                        cf_aah_vals.append(v if isinstance(v, (int, float)) else 0)
                    private_vals = [ds.get("supply_private", {}).get(k, 0) or 0 for k in products]
                    total_supply_vals = [ds.get("total_supply", {}).get(k, 0) or 0 for k in products]
                    return {
                        "type": "bar",
                        "labels": labels,
                        "datasets": [
                            {"label": "माग", "data": demand_vals, "backgroundColor": "#dc2626"},
                            {"label": "सा.वन नियमित", "data": cf_reg_vals, "backgroundColor": "#059669"},
                            {"label": "सा.वन AAH", "data": cf_aah_vals, "backgroundColor": "#3498db"},
                            {"label": "निजि क्षेत्र", "data": private_vals, "backgroundColor": "#e67e22"},
                            {"label": "जम्मा आपूर्ति", "data": total_supply_vals, "backgroundColor": "#9b59b6"},
                        ],
                    }
                return None
            elif chart_key == "demand_supply_deficit_bar":
                ds = data.get("demand_supply", {})
                if ds and ds.get("demand"):
                    products = ["firewood_bhari", "grass_bhari", "bedding_bhari", "timber_cft", "poles_count"]
                    ds_labels = {
                        "firewood_bhari": "दाउरा भारी",
                        "grass_bhari": "घाँस भारी",
                        "bedding_bhari": "सोतर भारी",
                        "timber_cft": "काठ क्यू.फि.",
                        "poles_count": "खाँवा संख्या",
                    }
                    labels = [ds_labels.get(k, k) for k in products]
                    deficit_vals = []
                    deficit_labels = []
                    for k in products:
                        diff = (ds.get("total_supply", {}).get(k, 0) or 0) - (ds.get("demand", {}).get(k, 0) or 0)
                        deficit_vals.append(diff)
                        deficit_labels.append("बचत" if diff >= 0 else "कमी")
                    bar_colors = ["#059669" if v >= 0 else "#dc2626" for v in deficit_vals]
                    return {
                        "type": "bar",
                        "labels": labels,
                        "datasets": [{
                            "label": "बचत/कमी",
                            "data": deficit_vals,
                            "backgroundColor": bar_colors,
                        }],
                        "deficit_labels": deficit_labels,
                    }
                return None
            elif chart_key == "budget_bar":
                activities = data.get("activities", {}).get("activities", [])
                if activities:
                    labels = [f"Activity {a.get('activity_id', i+1)}" for i, a in enumerate(activities)]
                    values = []
                    for a in activities:
                        total = sum(yd.get("budget", 0) for yd in a.get("yearly_details", []))
                        values.append(total or a.get("default_quantity", 0))
                    return _bar_data(labels, values, "Budget (Rs)")
                return None
            elif chart_key == "ya_budget_year_bar":
                yp = data.get("yearly_plan", {})
                trend = yp.get("budget_year_trend", {})
                if trend and isinstance(trend, dict):
                    labels = [f"Year {k}" for k in sorted(trend.keys(), key=int)]
                    values = [trend[k] for k in sorted(trend.keys(), key=int)]
                    return _bar_data(labels, values, "Budget (Rs)")
                return None
            elif chart_key == "ya_program_pie":
                yp = data.get("yearly_plan", {})
                pie_data = yp.get("program_pie_data", {})
                if pie_data and isinstance(pie_data, dict):
                    prog_items = {k: v for k, v in pie_data.items() if v > 0}
                    if prog_items:
                        items = sorted(prog_items.items(), key=lambda x: x[1], reverse=True)
                        labels = [k for k, _ in items]
                        values = [v for _, v in items]
                        colors = self._CHART_COLORS[:len(labels)]
                        return {"type": "pie", "labels": labels, "datasets": [{"data": values, "backgroundColor": colors}]}
                return None
            elif chart_key == "dbh_class_bar":
                chart_data = data.get("field_inventory", {}).get("fi_dbh_class_chart_data", [])
                if chart_data:
                    labels = [d["label"] for d in chart_data]
                    values = [d["count_per_ha"] for d in chart_data]
                    return _bar_data(labels, values, "संख्या/हे.")
                return None
            elif chart_key == "dbh_class_count_bar":
                chart_data = data.get("field_inventory", {}).get("fi_dbh_class_chart_data", [])
                if chart_data:
                    labels = [d["label"] for d in chart_data]
                    values = [d["count_per_ha"] for d in chart_data]
                    return _bar_data(labels, values, "संख्या/हे.")
                return None
            elif chart_key.startswith(("fi_reg_", "fi_regc_")):
                from app.services.operational_plan.species_regulation_tables import chart_series as reg_series
                series = reg_series(data.get("field_inventory", {}), chart_key)
                if series:
                    labels, values, _title, ylab = series
                    return _bar_data(labels, values, ylab)
                return None
            elif chart_key.startswith(("fi_unit_", "fi_species_")):
                from app.services.operational_plan.species_stage_tables import chart_series
                series = chart_series(data.get("field_inventory", {}), chart_key)
                if series:
                    labels, values, _title, ylab = series
                    return _bar_data(labels, values, ylab)
                return None
            elif chart_key == "hazard_landslide_area_by_class":
                rows = data.get("hazard_vuln", {}).get("lsi_area_by_class", [])
                rows = [r for r in rows if (r.get("क्षेत्रफल_हे") or 0) > 0]
                if rows:
                    return _bar_data(
                        [r.get("वर्ग", "") for r in rows],
                        [r.get("क्षेत्रफल_हे", 0) for r in rows],
                        "क्षेत्रफल (हे.)",
                    )
                return None
            elif chart_key == "hazard_slope_class_split":
                hv = data.get("hazard_vuln", {})
                if not hv.get("fs_enabled"):
                    return None
                unstable = float(hv.get("fs_unstable_pct") or 0.0)
                marginal = float(hv.get("fs_marginal_pct") or 0.0)
                stable = max(0.0, round(100.0 - unstable - marginal, 1))
                if unstable + marginal + stable <= 0:
                    return None
                return _bar_data(
                    ["अस्थिर", "सीमान्त स्थिर", "स्थिर"],
                    [unstable, marginal, stable],
                    "क्षेत्रफल (%)",
                )
            elif chart_key == "hazard_household_driver_split":
                rows = data.get("hazard_vuln", {}).get("hh_driver_counts", [])
                rows = [r for r in rows if (r.get("घरधुरी") or 0) > 0]
                if rows:
                    return _bar_data(
                        [r.get("कारक", "") for r in rows],
                        [r.get("घरधुरी", 0) for r in rows],
                        "घरधुरी संख्या",
                    )
                return None
            elif chart_key == "hazard_erosion_aoi_comparison":
                rows = data.get("soil_erosion", {}).get("soil_loss_aoi_comparison", [])
                rows = [
                    r for r in rows if r.get("औसत_क्षय_टन_हे_वर्ष") is not None
                ]
                if rows:
                    return _bar_data(
                        [r.get("क्षेत्र", "") for r in rows],
                        [r.get("औसत_क्षय_टन_हे_वर्ष", 0) for r in rows],
                        "औसत माटो क्षय (टन/हे./वर्ष)",
                    )
                return None
            elif chart_key.startswith("sm_"):
                return self._resolve_sm_chart(chart_key, data)
        except Exception:
            logger.exception(
                "chart data for %s could not be built - the chart will be "
                "missing from the plan", chart_key,
            )
            return None
        return None

    def _resolve_sm_chart(self, chart_key: str, data: dict) -> Optional[Dict[str, Any]]:
        sm = data.get("tree_mapping_analysis", {})
        _colors = self._CHART_COLORS

        # Helper functions
        def _pct_data(labels, values, is_pie=True):
            colors = _colors[:len(labels)]
            return {"type": "pie" if is_pie else "bar", "labels": labels, "datasets": [{"data": values, "backgroundColor": colors}]}

        def _grouped_bar(labels, datasets_dict):
            return {
                "type": "bar", "labels": labels,
                "datasets": [
                    {"label": k, "data": v, "backgroundColor": _colors[i % len(_colors)]}
                    for i, (k, v) in enumerate(datasets_dict.items())
                ],
            }

        if chart_key == "sm_felling_dbh_pie":
            fda = sm.get("sm_felling_dbh_analysis", [])
            if fda:
                labels = [r.get("dbh_class", str(i)) for i, r in enumerate(fda)]
                values = [r.get("tree_count", 0) for r in fda]
                return _pct_data(labels, values)
        elif chart_key == "sm_felling_species_bar":
            fsa = sm.get("sm_felling_species_analysis", [])[:10]
            if fsa:
                labels = [format_devanagari(i, 0) for i in range(1, len(fsa) + 1)]
                values = [r.get("tree_count", 0) for r in fsa]
                return _pct_data(labels, values, is_pie=False)
        elif chart_key == "sm_mother_felling_pie":
            mfs = sm.get("sm_mother_felling_summary", {})
            if mfs:
                labels = ["माँउ रूख", "कटानी रूख"]
                values = [mfs.get("total_mother_trees", 0), mfs.get("total_felling_trees", 0)]
                return _pct_data(labels, values)
        elif chart_key == "sm_mother_felling_species_bar":
            mbs = sm.get("sm_mother_tree_by_species", [])[:10]
            fbs = sm.get("sm_felling_tree_by_species", [])[:10]
            if mbs or fbs:
                all_species = list(dict.fromkeys([r.get("species", "") for r in mbs] + [r.get("species", "") for r in fbs]))[:10]
                labels = [format_devanagari(i, 0) for i in range(1, len(all_species) + 1)]
                mother_map = {r.get("species", ""): r.get("tree_count", 0) for r in mbs}
                felling_map = {r.get("species", ""): r.get("tree_count", 0) for r in fbs}
                mother_vals = [mother_map.get(sp, 0) for sp in all_species]
                felling_vals = [felling_map.get(sp, 0) for sp in all_species]
                return _grouped_bar(labels, {"माँउ": mother_vals, "कटानी": felling_vals})
        elif chart_key == "sm_stand_type_bar":
            st = sm.get("sm_stand_type_by_hierarchy", [])
            if st:
                labels = [format_devanagari(i, 0) for i in range(1, len(st) + 1)]
                regen = [r.get("regeneration", 0) for r in st]
                sapling = [r.get("sapling", 0) for r in st]
                pole = [r.get("pole", 0) for r in st]
                tree = [r.get("tree", 0) for r in st]
                return _grouped_bar(labels, {"पुनरुत्पादन": regen, "लाथ्रा": sapling, "पोल": pole, "रूख": tree})
        elif chart_key == "sm_carbon_bar":
            cb = sm.get("sm_carbon_by_hierarchy", [])
            if cb:
                labels = [format_devanagari(i, 0) for i in range(1, len(cb) + 1)]
                carbon_vals = [r.get("carbon_tc", 0) for r in cb]
                co2_vals = [r.get("co2_tco2", 0) for r in cb]
                return _grouped_bar(labels, {"कार्बन (tC)": carbon_vals, "CO₂e (tCO₂)": co2_vals})
        elif chart_key == "sm_volume_bar":
            vb = sm.get("sm_volume_by_hierarchy", [])
            if vb:
                labels = [format_devanagari(i, 0) for i in range(1, len(vb) + 1)]
                stem = [r.get("stem_volume_m3", 0) for r in vb]
                branch = [r.get("branch_volume_m3", 0) for r in vb]
                return _grouped_bar(labels, {"काण्ड": stem, "हाँगा": branch})
        elif chart_key == "sm_mother_felling_hierarchy_bar":
            hs = sm.get("sm_hierarchy_summary", [])
            rbd = sm.get("sm_hierarchy_remark_breakdown", {})
            if hs:
                labels = [format_devanagari(i, 0) for i in range(1, len(hs) + 1)]
                mother_vals = []
                felling_vals = []
                for r in hs:
                    key = f"{r.get('compartment','-')}|{r.get('sub_compartment','-')}"
                    breakdown = rbd.get(key, {})
                    mother_vals.append(breakdown.get("mother_trees", 0))
                    felling_vals.append(breakdown.get("felling_trees", 0))
                return _grouped_bar(labels, {"माँउ": mother_vals, "कटानी": felling_vals})
        return None

    def _resolve_table(self, var_def: VariableDef) -> Optional[Dict[str, Any]]:
        # business: tables rendered inline in OP documents — auto-populated from DB or built as fallback
        # NOTE: fallback path exists for every registered table — see variable_registry TABLE_ID_ALIAS
        table_id = var_def.key.replace("table:", "")
        from app.services.operational_plan.variable_registry import TABLE_ID_ALIAS
        table_id = TABLE_ID_ALIAS.get(table_id, table_id)
        try:
            from app.models.op_table import OPTableData
            from sqlalchemy import select
            tbl = self.db.execute(
                select(OPTableData).where(
                    OPTableData.calculation_id == self.calculation_id,
                    OPTableData.table_id == table_id,
                )
            ).scalar_one_or_none()
            if tbl and tbl.rows:
                return {"table_id": table_id, "rows": tbl.rows, "auto_populated": tbl.auto_populated}
        except Exception:
            logger.exception(
                "stored table %s could not be read - falling back to rebuilding "
                "it, discarding any hand edits", table_id,
            )
        # Fallback: build from raw data_collector data if OPTableData is empty
        try:
            raw = self.get_raw_data()
            if table_id == "demand_supply":
                ds = raw.get("demand_supply", {})
                if ds.get("demand"):
                    ds_labels = {
                        "firewood_bhari": "दाउरा भारी",
                        "grass_bhari": "घाँस भारी",
                        "bedding_bhari": "सोतर भारी",
                        "timber_cft": "काठ क्यू.फि.",
                        "poles_count": "खाँवा संख्या",
                    }
                    products = ["firewood_bhari", "grass_bhari", "bedding_bhari", "timber_cft", "poles_count"]
                    rows = []
                    for k in products:
                        deficit = ds.get("deficit", {}).get(k, 0) or 0
                        if isinstance(deficit, (int, float)):
                            sign = "बचत" if deficit >= 0 else "कमी"
                            deficit_str = f"{sign} {abs(deficit):.2f}"
                        else:
                            deficit_str = str(deficit) if deficit else "-"
                        cf_reg = ds.get("supply_cf_regular", {})
                        cf_aah = ds.get("supply_cf_aah", {})
                        rows.append({
                            "product": ds_labels.get(k, k),
                            "demand": ds.get("demand", {}).get(k, 0) or 0,
                            "cf_regular": cf_reg[k] if k in cf_reg else "-",
                            "cf_aah": cf_aah[k] if k in cf_aah else "-",
                            "private": ds.get("supply_private", {}).get(k, 0) or 0,
                            "total_supply": ds.get("total_supply", {}).get(k, 0) or 0,
                            "deficit": deficit_str,
                        })
                    if rows:
                        return {"table_id": table_id, "rows": rows, "auto_populated": True}

            # Tree mapping analysis tables (sm_* prefix)
            if table_id.startswith("sm_"):
                sm_data = raw.get("tree_mapping_analysis", {})
                rows = sm_data.get(table_id, [])
                if rows:
                    return {"table_id": table_id, "rows": rows, "auto_populated": True}

            if table_id == "table_39":
                inv = raw.get("ntfp_inventory") or {}
                if inv.get("available") and inv.get("table_rows"):
                    return {"table_id": table_id, "rows": inv["table_rows"], "auto_populated": True}
                return None

            if table_id in ("table_20", "table_33", "table_34", "table_35", "table_36", "table_37", "table_38"):
                bio = raw.get("biodiversity", {})
                if not bio.get("available"):
                    return None
                if table_id == "table_20":
                    rows = []
                    idx = 0
                    for rec in bio.get("vegetation", []):
                        idx += 1
                        rows.append({
                            "sn": idx, "name": rec.get("name", ""), "scientific_name": rec.get("scientific_name", ""),
                            "type": "वनस्पति", "sub_category": rec.get("sub_category", ""),
                            "iucn_status": rec.get("iucn_status", ""),
                            "is_protected": "हो" if rec.get("is_protected") else "होइन",
                            "is_invasive": "हो" if rec.get("is_invasive") else "होइन",
                        })
                    for rec in bio.get("animals", []):
                        idx += 1
                        rows.append({
                            "sn": idx, "name": rec.get("name", ""), "scientific_name": rec.get("scientific_name", ""),
                            "type": "जनावर", "sub_category": rec.get("sub_category", ""),
                            "iucn_status": rec.get("iucn_status", ""),
                            "is_protected": "हो" if rec.get("is_protected") else "होइन",
                            "is_invasive": "हो" if rec.get("is_invasive") else "होइन",
                        })
                    if rows:
                        return {"table_id": table_id, "rows": rows, "auto_populated": True}

                if table_id == "table_33":
                    iucn_map = {"CR": "संकटग्रस्त", "EN": "लोपोन्मुख", "VU": "असुरक्षित",
                                "NT": "नजिकै खतरा", "LC": "कम चासो", "DD": "अपर्याप्त"}
                    iucn_order = ["CR", "EN", "VU", "NT", "LC", "DD"]
                    breakdown = bio.get("iucn_breakdown", {})
                    rows = []
                    for code in iucn_order:
                        cnt = breakdown.get(code, 0)
                        if cnt:
                            rows.append({"iucn_code": code, "nepali_label": iucn_map.get(code, code), "count": cnt})
                    if rows:
                        return {"table_id": table_id, "rows": rows, "auto_populated": True}

                if table_id == "table_34":
                    rows = []
                    idx = 0
                    for rec in bio.get("vegetation", []):
                        if rec.get("is_protected"):
                            idx += 1
                            rows.append({"sn": idx, "name": rec.get("name", ""), "scientific_name": rec.get("scientific_name", ""), "sub_category": rec.get("sub_category", ""), "iucn_status": rec.get("iucn_status", "")})
                    for rec in bio.get("animals", []):
                        if rec.get("is_protected"):
                            idx += 1
                            rows.append({"sn": idx, "name": rec.get("name", ""), "scientific_name": rec.get("scientific_name", ""), "sub_category": rec.get("sub_category", ""), "iucn_status": rec.get("iucn_status", "")})
                    if rows:
                        return {"table_id": table_id, "rows": rows, "auto_populated": True}

                if table_id == "table_35":
                    rows = []
                    idx = 0
                    for rec in bio.get("vegetation", []):
                        if rec.get("is_invasive"):
                            idx += 1
                            rows.append({"sn": idx, "name": rec.get("name", ""), "scientific_name": rec.get("scientific_name", ""), "sub_category": rec.get("sub_category", ""), "iucn_status": rec.get("iucn_status", "")})
                    for rec in bio.get("animals", []):
                        if rec.get("is_invasive"):
                            idx += 1
                            rows.append({"sn": idx, "name": rec.get("name", ""), "scientific_name": rec.get("scientific_name", ""), "sub_category": rec.get("sub_category", ""), "iucn_status": rec.get("iucn_status", "")})
                    if rows:
                        return {"table_id": table_id, "rows": rows, "auto_populated": True}

                if table_id == "table_36":
                    rows = []
                    for idx, rec in enumerate(bio.get("vegetation", []), 1):
                        rows.append({
                            "sn": idx, "name": rec.get("name", ""), "scientific_name": rec.get("scientific_name", ""),
                            "sub_category": rec.get("sub_category", ""), "iucn_status": rec.get("iucn_status", ""),
                            "is_protected": "हो" if rec.get("is_protected") else "होइन",
                            "is_invasive": "हो" if rec.get("is_invasive") else "होइन",
                            "primary_use": rec.get("primary_use", ""),
                        })
                    if rows:
                        return {"table_id": table_id, "rows": rows, "auto_populated": True}

                if table_id == "table_38":
                    from app.core.ntfp import ntfp_species

                    rows = [
                        {"sn": idx, "name": r["name"], "scientific_name": r["scientific_name"], "parts": r["parts"],
                         "price_text": r["price_text"], "abundance": r["abundance"]}
                        for idx, r in enumerate(ntfp_species(bio.get("vegetation", [])), 1)
                    ]
                    if rows:
                        return {"table_id": table_id, "rows": rows, "auto_populated": True}

                if table_id == "table_37":
                    rows = []
                    for idx, rec in enumerate(bio.get("animals", []), 1):
                        rows.append({
                            "sn": idx, "name": rec.get("name", ""), "scientific_name": rec.get("scientific_name", ""),
                            "sub_category": rec.get("sub_category", ""), "iucn_status": rec.get("iucn_status", ""),
                            "is_protected": "हो" if rec.get("is_protected") else "होइन",
                            "is_invasive": "हो" if rec.get("is_invasive") else "होइन",
                            "primary_use": rec.get("primary_use", ""),
                        })
                    if rows:
                        return {"table_id": table_id, "rows": rows, "auto_populated": True}

        except Exception:
            logger.exception(
                "table %s could not be built - it will be missing from the plan",
                table_id,
            )
        return None
