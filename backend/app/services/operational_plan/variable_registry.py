"""Central registry of all Operational Plan template variables.

Each variable is registered with metadata: category (A-F), label (Nepali +
English), type (string/number/boolean/dict/list), data source module, and
display precision. The registry is used by the variable resolver and
auto-populate system to map {{variable}} patterns to data.

Entry points:
    VARIABLE_REGISTRY — dict of all registered VariableDef objects
    _reg() — register a single variable (called at module import time)

See also:
    .variable_resolver — resolves registered variables from collected data
# business: central registry of all 487 OP template variables
# NOTE: variable keys must match data_collector output keys exactly
# why: docstring-embedded metadata drives auto-populate and formatting
"""

from typing import Dict, Any, Optional, List, Callable, Literal
from pydantic import BaseModel, Field


class VariableDef(BaseModel):
    """Definition of a single OP template variable with metadata."""

    key: str
    category: Literal["A", "B", "C", "D", "E", "F"]
    label_ne: str = ""
    label_en: str = ""
    var_type: Literal["string", "number", "boolean", "dict", "list"] = "string"
    source: str = ""
    auto_populate: bool = True
    resolver: str = ""
    compute_fn: Optional[str] = None
    description: str = ""
    precision: int = 2
    # THEMATIC_MAP_VARIABLES_PLAN §3.9 / P0 — grouping + prose for the map/variable
    # reference page. `section` groups a variable within its family (map families
    # use S1..S20, legacy map:* use base/location/field/zoning); `viz` is the
    # render technique for map variables; the *_ne/_en descriptions are authored
    # in P3's content pass. Empty is the safe default for the ~490 existing vars.
    section: str = ""
    viz: str = ""
    description_ne: str = ""
    description_en: str = ""
    # HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P1 — set on a legacy key that has a
    # newer canonical twin (e.g. `lsi_prone_area_ha`.alias_of ==
    # `hazard_landslide_prone_area_ha`). The key still resolves; listing surfaces
    # hide it so the picker shows one descriptive name per value.
    alias_of: str = ""


VARIABLE_REGISTRY: Dict[str, VariableDef] = {}


# why: auto-detect decimal precision from key name to avoid manual config
def _infer_precision(key: str, label_en: str) -> int:
    """Auto-detect decimal precision from variable key and English label."""
    text = f" {key} {label_en} ".replace("_", " ").lower()
    key_lower = key.lower()

    # Wood density (before generic "density" match)
    if "wood density" in text:
        return 4
    # Carbon/biomass/CO2 -> 3 decimal places
    if any(w in text for w in ("agb", "bgb", "biomass", "carbon", "co2")):
        return 3
    # Percentages/density -> 1 decimal place
    if any(w in text for w in ("percent", " pct ", "density")):
        return 1
    # Climate
    if any(w in text for w in ("temperature", "precipitation")):
        return 1
    # Elevation/altitude -> whole numbers
    if any(w in text for w in ("elevation", "altitude", "utm")):
        return 0
    # Whole-number measures
    if any(w in text for w in ("cft", "chatta", "bhari", "year", "budget", "rupees")):
        return 0
    # Counts (specific compound suffixes only)
    if any(
        w in text.split()
        for w in (
            "plots",
            "trees",
            "households",
            "members",
            "species",
            "blocks",
            "points",
            "settlements",
            "activities",
            "revision",
            "population",
            "male",
            "female",
            "occupation",
        )
    ):
        return 0
    # Suffix-based count detection (on raw key before space replacement)
    if any(key_lower.endswith(s) for s in ("_count", "_total", "_number")):
        return 0
    return 2


# NOTE: variable keys must match data_collector output keys exactly
def _reg(
    key: str,
    category: str,
    label_ne: str = "",
    label_en: str = "",
    var_type: str = "string",
    source: str = "",
    auto_populate: bool = True,
    resolver: str = "",
    compute_fn: str = "",
    description: str = "",
    precision: int = 2,
    section: str = "",
    viz: str = "",
    description_ne: str = "",
    description_en: str = "",
    alias_of: str = "",
) -> None:
    if var_type == "number" and precision == 2:
        precision = _infer_precision(key, label_en)
    VARIABLE_REGISTRY[key] = VariableDef(
        key=key,
        category=category,
        label_ne=label_ne or key,
        label_en=label_en or key,
        var_type=var_type,
        source=source,
        auto_populate=auto_populate,
        resolver=resolver or f"resolve_{category.lower()}",
        compute_fn=compute_fn or None,
        description=description,
        precision=precision,
        section=section,
        viz=viz,
        description_ne=description_ne,
        description_en=description_en,
        alias_of=alias_of,
    )


# ═══════════════════════════════════════════════════════
# Category A: System Variables (109)
# business: Category A — system variables from calculation, raster, boundary
# ═══════════════════════════════════════════════════════

# A1: Basic Calculation Info (22)
_reg("forest_name", "A", "वनको नाम", "Forest Name", source="calculation")
_reg("block_name", "A", "ब्लकको नाम", "Block Name", source="calculation")
_reg(
    "calculation_status", "A", "गणना स्थिति", "Calculation Status", source="calculation"
)
_reg(
    "created_at",
    "A",
    "सृजना मिति",
    "Created At",
    var_type="string",
    source="calculation",
)
_reg(
    "completed_at",
    "A",
    "सम्पन्न मिति",
    "Completed At",
    var_type="string",
    source="calculation",
)
_reg(
    "total_area_sqm",
    "A",
    "कुल क्षेत्रफल (वर्गमि)",
    "Total Area (sqm)",
    var_type="number",
    source="calculation",
)
_reg(
    "total_area_hectares",
    "A",
    "कुल क्षेत्रफल (हेक्टर)",
    "Total Area (ha)",
    var_type="number",
    source="calculation",
)
_reg(
    "effective_area_hectares",
    "A",
    "प्रभावकारी क्षेत्रफल",
    "Effective Area (ha)",
    var_type="number",
    source="calculation",
)
_reg(
    "excluded_area_hectares",
    "A",
    "बहिष्कृत क्षेत्रफल",
    "Excluded Area (ha)",
    var_type="number",
    source="calculation",
)
_reg("province", "A", "प्रदेश", "Province", source="calculation")
_reg("district", "A", "जिल्ला", "District", source="calculation")
_reg("municipality", "A", "नगरपालिका/गाउँपालिका", "Municipality", source="calculation")
_reg(
    "municipality_type",
    "A",
    "स्थानीय तहको प्रकार",
    "Municipality Type",
    source="calculation",
)
_reg("ward", "A", "वडा नं.", "Ward No", source="calculation")
_reg("watershed", "A", "जलाधार", "Watershed", source="calculation")
_reg(
    "major_river_basin", "A", "प्रमुख नदी बेसिन", "Major River Basin", source="calculation"
)
_reg(
    "total_blocks",
    "A",
    "कुल ब्लक सङ्ख्या",
    "Total Blocks",
    var_type="number",
    source="calculation",
    precision=0,
)
_reg(
    "unit_label_np",
    "A",
    "ब्लक/कम्पार्टमेन्ट (मोड अनुसार)",
    "Block/Compartment (mode-aware, Nepali)",
    var_type="string",
    source="dimension",
)
_reg(
    "unit_label_en",
    "A",
    "Block/Compartment (mode-aware, English)",
    "Block/Compartment (mode-aware, English)",
    var_type="string",
    source="dimension",
)
_reg(
    "unit_label_plural_np",
    "A",
    "ब्लकहरू/कम्पार्टमेन्टहरू (मोड अनुसार)",
    "Blocks/Compartments (mode-aware, Nepali)",
    var_type="string",
    source="dimension",
)
_reg(
    "unit_label_plural_en",
    "A",
    "Blocks/Compartments (mode-aware, English)",
    "Blocks/Compartments (mode-aware, English)",
    var_type="string",
    source="dimension",
)
_reg(
    "utm_zone",
    "A",
    "UTM जोन",
    "UTM Zone",
    var_type="number",
    source="calculation",
    precision=0,
)

# A2: Raster - Physiography (12)
_reg(
    "elevation_min_m",
    "A",
    "न्यूनतम उचाई (मि)",
    "Min Elevation (m)",
    var_type="number",
    source="raster",
    precision=0,
)
_reg(
    "elevation_max_m",
    "A",
    "अधिकतम उचाई (मि)",
    "Max Elevation (m)",
    var_type="number",
    source="raster",
    precision=0,
)
_reg(
    "elevation_mean_m",
    "A",
    "औसत उचाई (मि)",
    "Mean Elevation (m)",
    var_type="number",
    source="raster",
    precision=0,
)
_reg("slope_dominant_class", "A", "मुख्य भिरालो वर्ग", "Dominant Slope", source="raster")
_reg(
    "slope_percentages",
    "A",
    "भिरालो प्रतिशत",
    "Slope Percentages",
    var_type="dict",
    source="raster",
)
_reg("aspect_dominant", "A", "मुख्य दिशा", "Dominant Aspect", source="raster")
_reg(
    "aspect_percentages",
    "A",
    "दिशा प्रतिशत",
    "Aspect Percentages",
    var_type="dict",
    source="raster",
)
_reg("soil_dominant_type", "A", "मुख्य माटो प्रकार", "Dominant Soil Type", source="raster")
_reg(
    "soil_percentages",
    "A",
    "माटो प्रतिशत",
    "Soil Percentages",
    var_type="dict",
    source="raster",
)
_reg(
    "geology_percentages",
    "A",
    "भूगर्भ प्रतिशत",
    "Geology Percentages",
    var_type="dict",
    source="raster",
)
_reg(
    "physiography_percentages",
    "A",
    "भू-आकृति प्रतिशत",
    "Physiography Percentages",
    var_type="dict",
    source="raster",
)
_reg(
    "ecoregion_percentages",
    "A",
    "इकोरिजन प्रतिशत",
    "Ecoregion Percentages",
    var_type="dict",
    source="raster",
)

# A3: Raster - Climate (6)
_reg(
    "temperature_mean_c",
    "A",
    "औसत तापक्रम (से)",
    "Mean Temperature (C)",
    var_type="number",
    source="raster",
    precision=1,
)
_reg(
    "temperature_min_c",
    "A",
    "न्यूनतम तापक्रम (से)",
    "Min Temperature (C)",
    var_type="number",
    source="raster",
    precision=1,
)
_reg(
    "temperature_max_c",
    "A",
    "अधिकतम तापक्रम (से)",
    "Max Temperature (C)",
    var_type="number",
    source="raster",
    precision=1,
)
_reg(
    "precipitation_mean_mm",
    "A",
    "औसत वर्षा (मिमि)",
    "Mean Precipitation (mm)",
    var_type="number",
    source="raster",
    precision=1,
)
_reg(
    "precipitation_min_mm",
    "A",
    "न्यूनतम वर्षा (मिमि)",
    "Min Precipitation (mm)",
    var_type="number",
    source="raster",
    precision=1,
)
_reg(
    "precipitation_max_mm",
    "A",
    "अधिकतम वर्षा (मिमि)",
    "Max Precipitation (mm)",
    var_type="number",
    source="raster",
    precision=1,
)

# A4: Raster - Forest Cover (12)
_reg(
    "forest_type_dominant", "A", "मुख्य वन प्रकार", "Dominant Forest Type", source="raster"
)
_reg(
    "forest_type_percentages",
    "A",
    "वन प्रकार प्रतिशत",
    "Forest Type Percentages",
    var_type="dict",
    source="raster",
)
_reg("landcover_dominant", "A", "मुख्य भू-आवरण", "Dominant Landcover", source="raster")
_reg(
    "landcover_percentages",
    "A",
    "भू-आवरण प्रतिशत",
    "Landcover Percentages",
    var_type="dict",
    source="raster",
)
_reg(
    "landcover_1984_dominant",
    "A",
    "सन् १९८४ को मुख्य भू-उपयोग",
    "Dominant Land Use (1984)",
    source="raster",
)
_reg(
    "landcover_1984_percentages",
    "A",
    "सन् १९८४ को भू-उपयोग प्रतिशत",
    "Land Use Percentages (1984)",
    var_type="dict",
    source="raster",
)
_reg(
    "landcover_1984_area_ha",
    "A",
    "सन् १९८४ को भू-उपयोग क्षेत्रफल (हे.)",
    "Land Use Area 1984 (ha)",
    var_type="dict",
    source="raster",
)
_reg(
    "forest_health_dominant",
    "A",
    "मुख्य वन स्वास्थ्य",
    "Dominant Forest Health",
    source="raster",
)
_reg(
    "forest_health_percentages",
    "A",
    "वन स्वास्थ्य प्रतिशत",
    "Forest Health Percentages",
    var_type="dict",
    source="raster",
)
_reg(
    "canopy_dominant_class",
    "A",
    "मुख्य वन मुकुट वर्ग",
    "Dominant Canopy Class",
    source="raster",
)
_reg(
    "canopy_percentages",
    "A",
    "वन मुकुट प्रतिशत",
    "Canopy Percentages",
    var_type="dict",
    source="raster",
)
_reg(
    "canopy_mean_m",
    "A",
    "औसत वन मुकुट (मि)",
    "Mean Canopy (m)",
    var_type="number",
    source="raster",
    precision=1,
)
_reg(
    "forest_loss_hectares",
    "A",
    "वन क्षति (हे)",
    "Forest Loss (ha)",
    var_type="number",
    source="raster",
)
_reg(
    "forest_gain_hectares",
    "A",
    "वन लाभ (हे)",
    "Forest Gain (ha)",
    var_type="number",
    source="raster",
)
_reg(
    "forest_loss_by_year",
    "A",
    "वार्षिक वन क्षति",
    "Forest Loss by Year",
    var_type="dict",
    source="raster",
)
_reg(
    "nasa_forest_2020_percentages",
    "A",
    "वन गुणस्तर प्रतिशत (नासा)",
    "Forest Quality Percentages (NASA)",
    var_type="dict",
    source="raster",
)
_reg(
    "nasa_forest_2020_dominant",
    "A",
    "मुख्य वन गुणस्तर (नासा)",
    "Dominant Forest Quality (NASA)",
    source="raster",
)
_reg(
    "chart:nasa_forest_2020_pie",
    "A",
    "वन गुणस्तर पाई चार्ट (नासा)",
    "Forest Quality Pie Chart (NASA)",
    var_type="dict",
    source="raster",
)

# A5: Raster - Biomass/Carbon (3)
_reg(
    "agb_mean",
    "A",
    "औसत AGB",
    "Mean AGB",
    var_type="number",
    source="raster",
    precision=3,
)
_reg("agb_total", "A", "कुल AGB", "Total AGB", var_type="number", source="raster")
_reg(
    "carbon_stock",
    "A",
    "कार्बन मौज्दात",
    "Carbon Stock",
    var_type="number",
    source="raster",
    precision=3,
)

# A6: Boundary (5)
_reg("boundary_type", "A", "सिमाना प्रकार", "Boundary Type", source="boundary")
_reg(
    "boundary_features_north",
    "A",
    "उत्तर सिमाना",
    "North Boundary",
    var_type="list",
    source="boundary",
)
_reg(
    "boundary_features_east",
    "A",
    "पूर्व सिमाना",
    "East Boundary",
    var_type="list",
    source="boundary",
)
_reg(
    "boundary_features_south",
    "A",
    "दक्षिण सिमाना",
    "South Boundary",
    var_type="list",
    source="boundary",
)
_reg(
    "boundary_features_west",
    "A",
    "पश्चिम सिमाना",
    "West Boundary",
    var_type="list",
    source="boundary",
)
_reg("extent_n", "A", "उत्तर अक्षांश", "North Latitude", precision=7, source="boundary")
_reg("extent_s", "A", "दक्षिण अक्षांश", "South Latitude", precision=7, source="boundary")
_reg("extent_e", "A", "पूर्व देशान्तर", "East Longitude", precision=7, source="boundary")
_reg("extent_w", "A", "पश्चिम देशान्तर", "West Longitude", precision=7, source="boundary")

# A7: Blocks & Sub-Areas (7)
_reg(
    "blocks_count",
    "A",
    "ब्लक सङ्ख्या",
    "Blocks Count",
    var_type="number",
    source="block",
    precision=0,
)
_reg(
    "sub_areas_by_category",
    "A",
    "उप-क्षेत्र प्रकार",
    "Sub-areas by Category",
    var_type="dict",
    source="block",
)
_reg(
    "sub_areas_total",
    "A",
    "कुल उप-क्षेत्र",
    "Total Sub-areas",
    var_type="number",
    source="block",
    precision=0,
)

_reg(
    "sub_areas_detail",
    "A",
    "उप-क्षेत्र विवरण",
    "Sub-Areas Detail",
    var_type="list",
    source="block",
)
_reg(
    "block_area_detail_merged",
    "A",
    "ब्लक अनुसार क्षेत्रफलको विस्तृत विवरण तथा सामुदायिक वन क्षेत्रफल",
    "Block-wise Detailed Area & Community Forest Area Description (Merged)",
    var_type="list",
    source="block",
)

# A8: Species (4)
_reg(
    "total_species",
    "A",
    "कुल प्रजाति सङ्ख्या",
    "Total Species",
    var_type="number",
    source="species",
    precision=0,
)
_reg(
    "species_list", "A", "प्रजाति सूची", "Species List", var_type="list", source="species"
)
_reg(
    "species_by_role",
    "A",
    "भूमिका अनुसार प्रजाति",
    "Species by Role",
    var_type="dict",
    source="species",
)
_reg(
    "confirmed_species",
    "A",
    "पुष्टि गरिएका प्रजाति",
    "Confirmed Species",
    var_type="list",
    source="species",
)

# A9: Tree Inventory (13)
_reg(
    "inventory_available",
    "A",
    "रूख गणना उपलब्ध",
    "Inventory Available",
    var_type="boolean",
    source="inventory",
)
_reg(
    "inventory_total_trees",
    "A",
    "कुल रूख सङ्ख्या",
    "Total Trees",
    var_type="number",
    source="inventory",
    precision=0,
)
_reg(
    "inventory_mother_trees",
    "A",
    "माँउ रूख सङ्ख्या",
    "Mother Trees",
    var_type="number",
    source="inventory",
    precision=0,
)
_reg(
    "inventory_felling_trees",
    "A",
    "कटानी रूख सङ्ख्या",
    "Felling Trees",
    var_type="number",
    source="inventory",
    precision=0,
)
_reg(
    "inventory_seedling_count",
    "A",
    "बिरुवा सङ्ख्या",
    "Seedling Count",
    var_type="number",
    source="inventory",
    precision=0,
)
_reg(
    "inventory_volume_m3",
    "A",
    "कुल आयतन (m³)",
    "Total Volume (m3)",
    var_type="number",
    source="inventory",
)
_reg(
    "inventory_net_volume_m3",
    "A",
    "शुद्ध आयतन (m³)",
    "Net Volume (m3)",
    var_type="number",
    source="inventory",
)
_reg(
    "inventory_net_volume_cft",
    "A",
    "शुद्ध आयतन (cft)",
    "Net Volume (cft)",
    var_type="number",
    source="inventory",
    precision=0,
)
_reg(
    "inventory_firewood_m3",
    "A",
    "दाउरा आयतन (m³)",
    "Firewood Volume (m3)",
    var_type="number",
    source="inventory",
)
_reg(
    "inventory_firewood_chatta",
    "A",
    "दाउरा (चट्टा)",
    "Firewood (chatta)",
    var_type="number",
    source="inventory",
    precision=0,
)
_reg(
    "inventory_species_summary",
    "A",
    "प्रजाति सारांश",
    "Species Summary",
    var_type="dict",
    source="inventory",
)
_reg(
    "inventory_dbh_summary",
    "A",
    "DBH सारांश",
    "DBH Summary",
    var_type="dict",
    source="inventory",
)
_reg(
    "inventory_block_summary",
    "A",
    "ब्लक सारांश",
    "Block Summary",
    var_type="dict",
    source="inventory",
)

# business: 23 field inventory variables — core of OP Section 6
# A10: Field Inventory (23)
_reg(
    "fi_available",
    "A",
    "क्षेत्र सर्वेक्षण उपलब्ध",
    "Field Inventory Available",
    var_type="boolean",
    source="field_inventory",
)
_reg(
    "fi_total_plots",
    "A",
    "कुल नमूना प्लट",
    "Total Sample Plots",
    var_type="number",
    source="field_inventory",
    precision=0,
)
_reg(
    "fi_total_blocks",
    "A",
    "सर्वेक्षण ब्लक",
    "Survey Blocks",
    var_type="number",
    source="field_inventory",
    precision=0,
)
_reg(
    "fi_regeneration_area_sqm",
    "A",
    "पुनरुत्पादन क्षेत्र (m²)",
    "Regeneration Area (sqm)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "fi_sapling_area_sqm",
    "A",
    "बिरुवा क्षेत्र (m²)",
    "Sapling Area (sqm)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "fi_pole_area_sqm",
    "A",
    "पोल क्षेत्र (m²)",
    "Pole Area (sqm)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "fi_tree_area_sqm",
    "A",
    "रूख क्षेत्र (m²)",
    "Tree Area (sqm)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "fi_regeneration_per_ha",
    "A",
    "प्रतिहेक्टर पुनरुत्पादन",
    "Regeneration per ha",
    var_type="number",
    source="field_inventory",
)
_reg(
    "fi_sapling_per_ha",
    "A",
    "प्रतिहेक्टर बिरुवा",
    "Sapling per ha",
    var_type="number",
    source="field_inventory",
)
_reg(
    "fi_pole_per_ha",
    "A",
    "प्रतिहेक्टर पोल",
    "Pole per ha",
    var_type="number",
    source="field_inventory",
)
_reg(
    "fi_tree_per_ha",
    "A",
    "प्रतिहेक्टर रूख",
    "Tree per ha",
    var_type="number",
    source="field_inventory",
)
_reg(
    "fi_growing_stock_m3_per_ha",
    "A",
    "प्रतिहेक्टर वन मौज्दात (m³)",
    "Growing Stock per ha",
    var_type="number",
    source="field_inventory",
)
_reg(
    "fi_has_protected_stratum",
    "A",
    "संरक्षित क्षेत्र नमूना छ?",
    "Has Protection-stratum Sampling",
    var_type="boolean",
    source="field_inventory",
)
_reg(
    "fi_protected_sample_plots",
    "A",
    "संरक्षित क्षेत्रका नमूना प्लट संख्या",
    "Protection-stratum Sample Plots",
    var_type="number",
    source="field_inventory",
)
_reg(
    "fi_protected_growing_stock_m3_per_ha",
    "A",
    "संरक्षित क्षेत्रको प्रतिहेक्टर वन मौज्दात (m³) — कटानमा समावेश छैन",
    "Protection-stratum Growing Stock per ha (excluded from AAH)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "fi_protected_stratum_note",
    "A",
    "संरक्षित क्षेत्र नमूना टिप्पणी",
    "Protection-stratum Note",
    source="field_inventory",
)
_reg(
    "fi_protected_stratum_table",
    "A",
    "संरक्षित क्षेत्र वन मौज्दात तालिका (ब्लक अनुसार)",
    "Protection-stratum Growing Stock Table (per block)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_protection_units",
    "A",
    "संरक्षित कार्य वृत्तका एकाइहरू",
    "Protection Working-Circle Units",
    var_type="list",
    source="field_inventory",
)

# ── S9: RUSLE soil-loss (P3). source="soil_erosion" → data_collector.get_soil_erosion_data
_SE = dict(category="A", source="soil_erosion", section="S9")
_reg("soil_loss_mean_t_ha", label_ne="औसत वार्षिक माटो क्षय (टन/हे./वर्ष)",
     label_en="Mean annual soil loss (t ha-1 yr-1)", var_type="number", **_SE)
_reg("soil_loss_total_t_yr", label_ne="कुल वार्षिक माटो क्षय (टन/वर्ष)",
     label_en="Total annual soil loss (t yr-1)", var_type="number", **_SE)
_reg("soil_loss_area_ha", label_ne="विश्लेषण क्षेत्रफल (हे.)",
     label_en="Analysed area (ha)", var_type="number", **_SE)
_reg("soil_loss_tolerable", label_ne="सह्य माटो क्षय सीमा (टन/हे./वर्ष)",
     label_en="Tolerable soil-loss limit (t ha-1 yr-1)", var_type="number", **_SE)
_reg("soil_loss_pct_above_tolerable", label_ne="सह्य सीमाभन्दा माथिको क्षेत्रफल (%)",
     label_en="Area above the tolerable limit (%)", var_type="number", **_SE)
_reg("soil_loss_by_unit", label_ne="{{unit_label_np}} अनुसार वार्षिक माटो क्षय",
     label_en="Annual soil loss by unit", var_type="list", **_SE)
_reg("soil_loss_hotspot_units_str", label_ne="उच्च क्षय एकाइहरू",
     label_en="High-erosion units", var_type="string", **_SE)
_reg("soil_loss_dominant_factor", label_ne="प्रमुख स्थानिक कारक (R/K/LS/C)",
     label_en="Dominant spatial factor (R/K/LS/C)", var_type="string", **_SE)
_reg("soil_loss_r_method", label_ne="R कारक विधि",
     label_en="R-factor method", var_type="string", **_SE)
_reg("soil_loss_assumptions", label_ne="विधि सम्बन्धी मान्यताहरू",
     label_en="Methodological assumptions", var_type="list", **_SE)
_reg("soil_loss_ug_mean_t_ha", label_ne="उपभोक्ता क्षेत्रको औसत माटो क्षय (टन/हे./वर्ष)",
     label_en="User-group area mean soil loss (t ha-1 yr-1)", var_type="number", **_SE)
_reg("soil_loss_ug_total_t_yr", label_ne="उपभोक्ता क्षेत्रको कुल माटो क्षय (टन/वर्ष)",
     label_en="User-group area total soil loss (t yr-1)", var_type="number", **_SE)
_reg("soil_loss_ug_minus_cf_mean_t_ha",
     label_ne="वन बाहिरको बस्ती भूमिको औसत माटो क्षय (टन/हे./वर्ष)",
     label_en="Settlement land outside the forest - mean soil loss (t ha-1 yr-1)",
     var_type="number", **_SE)
_reg("soil_loss_ug_minus_cf_total_t_yr",
     label_ne="वन बाहिरको बस्ती भूमिको कुल माटो क्षय (टन/वर्ष)",
     label_en="Settlement land outside the forest - total soil loss (t yr-1)",
     var_type="number", **_SE)
_reg("soil_loss_aoi_comparison",
     label_ne="माटो क्षय — वन र उपभोक्ता क्षेत्रको तुलना",
     label_en="Soil loss — forest vs user-group area comparison",
     var_type="list", **_SE)
_reg("soil_loss_delivered_t_yr", label_ne="नदीसम्म पुग्ने अनुमानित तलछट (टन/वर्ष)",
     label_en="Estimated sediment delivered to streams (t yr-1)", var_type="number", **_SE)
_reg("soil_loss_delivered_ug_t_yr",
     label_ne="उपभोक्ता क्षेत्रबाट नदीसम्म पुग्ने अनुमानित तलछट (टन/वर्ष)",
     label_en="Sediment delivered to streams from the user-group area (t yr-1)",
     var_type="number", **_SE)
_reg("soil_loss_basin_sdr", label_ne="तलछट वितरण अनुपात (SDR)",
     label_en="Basin sediment delivery ratio (SDR)", var_type="number", **_SE)
_reg("soil_loss_methodology_narration", label_ne="माटो क्षय — विधि विवरण",
     label_en="Soil loss — methodology narrative", var_type="string", **_SE)
_reg("soil_loss_methodology_narration_en", label_ne="माटो क्षय — विधि विवरण (अङ्ग्रेजी)",
     label_en="Soil loss — methodology narrative (English)", var_type="string", **_SE)
_reg("soil_loss_findings_narration", label_ne="माटो क्षय — निष्कर्ष विवरण",
     label_en="Soil loss — findings narrative", var_type="string", **_SE)
_reg("soil_loss_findings_narration_en", label_ne="माटो क्षय — निष्कर्ष विवरण (अङ्ग्रेजी)",
     label_en="Soil loss — findings narrative (English)", var_type="string", **_SE)
_reg("soil_loss_prescription_narration", label_ne="माटो क्षय — व्यवस्थापन दिशानिर्देश",
     label_en="Soil loss — prescription narrative", var_type="string", **_SE)
_reg("soil_loss_prescription_narration_en",
     label_ne="माटो क्षय — व्यवस्थापन दिशानिर्देश (अङ्ग्रेजी)",
     label_en="Soil loss — prescription narrative (English)", var_type="string", **_SE)

# ── S9: landslide hazard + household vulnerability (P5).
# source="hazard_vuln" → data_collector.get_hazard_vuln_data
_HV = dict(category="A", source="hazard_vuln", section="S9")
_reg("lsi_prone_area_ha", label_ne="सापेक्ष रूपमा उच्च संवेदनशील क्षेत्रफल (हे.)",
     label_en="Relatively high-susceptibility area (ha)", var_type="number", **_HV)
_reg("lsi_prone_area_pct", label_ne="सापेक्ष रूपमा उच्च संवेदनशील क्षेत्रफल (%)",
     label_en="Relatively high-susceptibility area (%)", var_type="number", **_HV)
_reg("lsi_area_by_class", label_ne="पहिरो संवेदनशीलता वर्ग अनुसार क्षेत्रफल",
     label_en="Area by landslide-susceptibility class", var_type="list", **_HV)
_reg("lsi_by_unit", label_ne="{{unit_label_np}} अनुसार पहिरो संवेदनशीलता",
     label_en="Landslide susceptibility by unit", var_type="list", **_HV)
_reg("lsi_high_units_str", label_ne="उच्च पहिरो संवेदनशीलता एकाइहरू",
     label_en="High-susceptibility units", var_type="string", **_HV)
_reg("lsi_class_method", label_ne="LSI वर्गीकरण विधि",
     label_en="LSI classification method", var_type="string", **_HV)
_reg("lsi_consistency_ratio", label_ne="AHP संगति अनुपात (CR)",
     label_en="AHP consistency ratio (CR)", var_type="number", **_HV)
_reg("fs_enabled", label_ne="स्थायित्व गुणांक नक्सा समावेश",
     label_en="Factor-of-Safety map included", var_type="string", **_HV)
_reg("fs_unstable_area_ha", label_ne="अस्थिर क्षेत्रफल — मनसुन परिदृश्य (हे.)",
     label_en="Unstable area — monsoon scenario (ha)", var_type="number", **_HV)
_reg("fs_unstable_pct", label_ne="अस्थिर क्षेत्रफल (%)",
     label_en="Unstable area (%)", var_type="number", **_HV)
_reg("fs_marginal_pct", label_ne="सीमान्त स्थायित्व क्षेत्रफल (%)",
     label_en="Marginally-stable area (%)", var_type="number", **_HV)
_reg("fs_scenario_note", label_ne="FS परिदृश्य टिप्पणी",
     label_en="FS scenario note", var_type="string", **_HV)
_reg("fs_scenario_note_en", label_ne="FS परिदृश्य टिप्पणी (अङ्ग्रेजी)",
     label_en="FS scenario note (English)", var_type="string", **_HV)
_reg("fs_by_unit", label_ne="{{unit_label_np}} अनुसार ढलान स्थायित्व",
     label_en="Slope stability by unit", var_type="list", **_HV)
_reg("hazard_aoi_comparison", label_ne="क्षेत्रगत पहिरो जोखिम तुलना (सा.व. / उपभोक्ता क्षेत्र)",
     label_en="Landslide-hazard comparison by area (CF / user-group)", var_type="list", **_HV)
_reg("hh_count", label_ne="विश्लेषित घरधुरी संख्या",
     label_en="Households analysed", var_type="number", **_HV)
_reg("hh_priority_count", label_ne="प्राथमिकता घरधुरी संख्या",
     label_en="Priority households", var_type="number", **_HV)
_reg("hh_mean_score", label_ne="औसत घरधुरी जोखिम अंक",
     label_en="Mean household vulnerability score", var_type="number", **_HV)
_reg("hh_hazard_layer_informative", label_ne="भौतिक प्रकोप तह विभेदकारी",
     label_en="Physical-hazard layer discriminative", var_type="string", **_HV)
_reg("hh_priority_table", label_ne="प्राथमिकता घरधुरी सूची (घर नं. / टोल / अंक / कारक)",
     label_en="Priority households (house no. / tole / score / driver)", var_type="list", **_HV)
_reg("hh_settlement_rollup_table", label_ne="टोल अनुसार घरधुरी जोखिम सारांश",
     label_en="Household vulnerability roll-up by settlement", var_type="list", **_HV)
_reg("hh_driver_counts", label_ne="प्रमुख जोखिम कारक अनुसार घरधुरी",
     label_en="Households by dominant vulnerability driver", var_type="list", **_HV)
_reg("hazard_assumptions", label_ne="जोखिम विश्लेषण — मान्यताहरू",
     label_en="Hazard analysis — assumptions", var_type="list", **_HV)
_reg("hazard_methodology_narration", label_ne="जोखिम — विधि विवरण",
     label_en="Hazard — methodology narrative", var_type="string", **_HV)
_reg("hazard_methodology_narration_en", label_ne="जोखिम — विधि विवरण (अङ्ग्रेजी)",
     label_en="Hazard — methodology narrative (English)", var_type="string", **_HV)
_reg("hazard_findings_narration", label_ne="जोखिम — निष्कर्ष विवरण",
     label_en="Hazard — findings narrative", var_type="string", **_HV)
_reg("hazard_findings_narration_en", label_ne="जोखिम — निष्कर्ष विवरण (अङ्ग्रेजी)",
     label_en="Hazard — findings narrative (English)", var_type="string", **_HV)
_reg("hazard_prescription_narration", label_ne="जोखिम — व्यवस्थापन दिशानिर्देश",
     label_en="Hazard — prescription narrative", var_type="string", **_HV)
_reg("hazard_prescription_narration_en", label_ne="जोखिम — व्यवस्थापन दिशानिर्देश (अङ्ग्रेजी)",
     label_en="Hazard — prescription narrative (English)", var_type="string", **_HV)

# ── S9 canonical naming — HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P1 ────────────
# One descriptive `hazard_*` key per Hazard & Erosion display value. The legacy
# keys above (soil_loss_* / lsi_* / fs_* / hh_*) stay registered and resolvable;
# VARIABLE_ALIASES maps canonical → legacy and the resolver + docx builder fall
# through it, so templates already authored against the old keys keep working.
# The cross-cutting `hazard_*_narration` / `hazard_assumptions` keys are already
# on-scheme and stay canonical (no alias).
VARIABLE_ALIASES: Dict[str, str] = {
    # erosion (RUSLE) — source="soil_erosion"
    "hazard_erosion_mean_t_ha": "soil_loss_mean_t_ha",
    "hazard_erosion_total_t_yr": "soil_loss_total_t_yr",
    "hazard_erosion_area_ha": "soil_loss_area_ha",
    "hazard_erosion_tolerable_limit": "soil_loss_tolerable",
    "hazard_erosion_pct_above_tolerable": "soil_loss_pct_above_tolerable",
    "hazard_erosion_by_unit_table": "soil_loss_by_unit",
    "hazard_erosion_hotspot_units": "soil_loss_hotspot_units_str",
    "hazard_erosion_dominant_factor": "soil_loss_dominant_factor",
    "hazard_erosion_r_method": "soil_loss_r_method",
    "hazard_erosion_assumptions": "soil_loss_assumptions",
    "hazard_erosion_ug_mean_t_ha": "soil_loss_ug_mean_t_ha",
    "hazard_erosion_ug_total_t_yr": "soil_loss_ug_total_t_yr",
    "hazard_erosion_ug_minus_cf_mean_t_ha": "soil_loss_ug_minus_cf_mean_t_ha",
    "hazard_erosion_ug_minus_cf_total_t_yr": "soil_loss_ug_minus_cf_total_t_yr",
    "hazard_erosion_aoi_comparison_table": "soil_loss_aoi_comparison",
    "hazard_erosion_delivered_t_yr": "soil_loss_delivered_t_yr",
    "hazard_erosion_delivered_ug_t_yr": "soil_loss_delivered_ug_t_yr",
    "hazard_erosion_basin_sdr": "soil_loss_basin_sdr",
    "hazard_erosion_methodology_narration": "soil_loss_methodology_narration",
    "hazard_erosion_methodology_narration_en": "soil_loss_methodology_narration_en",
    "hazard_erosion_findings_narration": "soil_loss_findings_narration",
    "hazard_erosion_findings_narration_en": "soil_loss_findings_narration_en",
    "hazard_erosion_prescription_narration": "soil_loss_prescription_narration",
    "hazard_erosion_prescription_narration_en": "soil_loss_prescription_narration_en",
    # erosion — P2: values the endpoints render but that had no _reg entry
    "hazard_erosion_customised": "soil_loss_customised",
    "hazard_erosion_sdr_enabled": "soil_loss_sdr_enabled",
    "hazard_erosion_sdr_mean": "soil_loss_sdr_mean",
    "hazard_erosion_severity_breaks": "soil_loss_severity_breaks",
    "hazard_erosion_ug_area_ha": "soil_loss_ug_area_ha",
    "hazard_erosion_ug_minus_cf_area_ha": "soil_loss_ug_minus_cf_area_ha",
    # landslide (LSI) — source="hazard_vuln"
    "hazard_landslide_prone_area_ha": "lsi_prone_area_ha",
    "hazard_landslide_prone_area_pct": "lsi_prone_area_pct",
    "hazard_landslide_area_by_class_table": "lsi_area_by_class",
    "hazard_landslide_by_unit_table": "lsi_by_unit",
    "hazard_landslide_high_units": "lsi_high_units_str",
    "hazard_landslide_class_method": "lsi_class_method",
    "hazard_landslide_ahp_cr": "lsi_consistency_ratio",
    "hazard_landslide_aoi_comparison_table": "hazard_aoi_comparison",
    "hazard_landslide_customised": "lsi_customised",  # P2
    # slope stability (Factor of Safety) — source="hazard_vuln"
    "hazard_slope_fs_enabled": "fs_enabled",
    "hazard_slope_unstable_area_ha": "fs_unstable_area_ha",
    "hazard_slope_unstable_pct": "fs_unstable_pct",
    "hazard_slope_marginal_pct": "fs_marginal_pct",
    "hazard_slope_marginal_area_ha": "fs_marginal_area_ha",  # P2
    "hazard_slope_depth_mean_m": "fs_depth_mean_m",  # P2
    "hazard_slope_scenario_note": "fs_scenario_note",
    "hazard_slope_scenario_note_en": "fs_scenario_note_en",
    "hazard_slope_by_unit_table": "fs_by_unit",
    # household vulnerability — source="hazard_vuln"
    "hazard_household_count": "hh_count",
    "hazard_household_priority_count": "hh_priority_count",
    "hazard_household_mean_score": "hh_mean_score",
    "hazard_household_max_score": "hh_max_score",  # P2
    "hazard_household_coord_source": "hh_coord_source",  # P2
    "hazard_household_layer_informative": "hh_hazard_layer_informative",
    "hazard_household_priority_table": "hh_priority_table",
    "hazard_household_settlement_rollup_table": "hh_settlement_rollup_table",
    "hazard_household_driver_counts_table": "hh_driver_counts",
}

# reverse map — a legacy key → its canonical twin (for "also known as" in the picker)
LEGACY_TO_CANONICAL: Dict[str, str] = {v: k for k, v in VARIABLE_ALIASES.items()}

_reg("hazard_erosion_mean_t_ha", label_ne="औसत वार्षिक माटो क्षय (टन/हे./वर्ष)",
     label_en="Mean annual soil loss (t/ha/yr)", var_type="number", **_SE)
_reg("hazard_erosion_total_t_yr", label_ne="कुल वार्षिक माटो क्षय (टन/वर्ष)",
     label_en="Total annual soil loss (t/yr)", var_type="number", **_SE)
_reg("hazard_erosion_area_ha", label_ne="विश्लेषण क्षेत्रफल (हे.)",
     label_en="Analysed area (ha)", var_type="number", **_SE)
_reg("hazard_erosion_tolerable_limit", label_ne="सह्य माटो क्षय सीमा (टन/हे./वर्ष)",
     label_en="Tolerable soil-loss limit (t/ha/yr)", var_type="number", **_SE)
_reg("hazard_erosion_pct_above_tolerable", label_ne="सह्य सीमाभन्दा माथिको क्षेत्रफल (%)",
     label_en="Area above the tolerable limit (%)", var_type="number", **_SE)
_reg("hazard_erosion_by_unit_table", label_ne="{{unit_label_np}} अनुसार वार्षिक माटो क्षय",
     label_en="Annual soil loss by unit (table)", var_type="list", **_SE)
_reg("hazard_erosion_hotspot_units", label_ne="उच्च क्षय एकाइहरू",
     label_en="High-erosion units", var_type="string", **_SE)
_reg("hazard_erosion_dominant_factor", label_ne="प्रमुख स्थानिक कारक (R/K/LS/C)",
     label_en="Dominant RUSLE factor (R/K/LS/C)", var_type="string", **_SE)
_reg("hazard_erosion_r_method", label_ne="R कारक विधि",
     label_en="R-factor method", var_type="string", **_SE)
_reg("hazard_erosion_assumptions", label_ne="माटो क्षय — विधि सम्बन्धी मान्यताहरू",
     label_en="Soil loss — methodological assumptions", var_type="list", **_SE)
_reg("hazard_erosion_ug_mean_t_ha", label_ne="उपभोक्ता क्षेत्रको औसत माटो क्षय (टन/हे./वर्ष)",
     label_en="User-group area — mean soil loss (t/ha/yr)", var_type="number", **_SE)
_reg("hazard_erosion_ug_total_t_yr", label_ne="उपभोक्ता क्षेत्रको कुल माटो क्षय (टन/वर्ष)",
     label_en="User-group area — total soil loss (t/yr)", var_type="number", **_SE)
_reg("hazard_erosion_ug_minus_cf_mean_t_ha",
     label_ne="वन बाहिरको बस्ती भूमिको औसत माटो क्षय (टन/हे./वर्ष)",
     label_en="Settlement land outside the forest — mean soil loss (t/ha/yr)",
     var_type="number", **_SE)
_reg("hazard_erosion_ug_minus_cf_total_t_yr",
     label_ne="वन बाहिरको बस्ती भूमिको कुल माटो क्षय (टन/वर्ष)",
     label_en="Settlement land outside the forest — total soil loss (t/yr)",
     var_type="number", **_SE)
_reg("hazard_erosion_aoi_comparison_table",
     label_ne="माटो क्षय — वन र उपभोक्ता क्षेत्रको तुलना",
     label_en="Soil loss — CF vs user-group comparison (table)", var_type="list", **_SE)
_reg("hazard_erosion_delivered_t_yr", label_ne="नदीसम्म पुग्ने अनुमानित तलछट (टन/वर्ष)",
     label_en="Estimated sediment delivered to streams (t/yr)", var_type="number", **_SE)
_reg("hazard_erosion_delivered_ug_t_yr",
     label_ne="उपभोक्ता क्षेत्रबाट नदीसम्म पुग्ने अनुमानित तलछट (टन/वर्ष)",
     label_en="Sediment delivered to streams from the user-group area (t/yr)",
     var_type="number", **_SE)
_reg("hazard_erosion_basin_sdr", label_ne="तलछट वितरण अनुपात (SDR)",
     label_en="Basin sediment delivery ratio (SDR)", var_type="number", **_SE)
_reg("hazard_erosion_methodology_narration", label_ne="माटो क्षय — विधि विवरण",
     label_en="Soil loss — methodology narrative", var_type="string", **_SE)
_reg("hazard_erosion_methodology_narration_en", label_ne="माटो क्षय — विधि विवरण (अङ्ग्रेजी)",
     label_en="Soil loss — methodology narrative (English)", var_type="string", **_SE)
_reg("hazard_erosion_findings_narration", label_ne="माटो क्षय — निष्कर्ष विवरण",
     label_en="Soil loss — findings narrative", var_type="string", **_SE)
_reg("hazard_erosion_findings_narration_en", label_ne="माटो क्षय — निष्कर्ष विवरण (अङ्ग्रेजी)",
     label_en="Soil loss — findings narrative (English)", var_type="string", **_SE)
_reg("hazard_erosion_prescription_narration", label_ne="माटो क्षय — व्यवस्थापन दिशानिर्देश",
     label_en="Soil loss — prescription narrative", var_type="string", **_SE)
_reg("hazard_erosion_prescription_narration_en",
     label_ne="माटो क्षय — व्यवस्थापन दिशानिर्देश (अङ्ग्रेजी)",
     label_en="Soil loss — prescription narrative (English)", var_type="string", **_SE)

_reg("hazard_landslide_prone_area_ha", label_ne="सापेक्ष रूपमा उच्च संवेदनशील क्षेत्रफल (हे.)",
     label_en="Relatively high-susceptibility area (ha)", var_type="number", **_HV)
_reg("hazard_landslide_prone_area_pct", label_ne="सापेक्ष रूपमा उच्च संवेदनशील क्षेत्रफल (%)",
     label_en="Relatively high-susceptibility area (%)", var_type="number", **_HV)
_reg("hazard_landslide_area_by_class_table", label_ne="पहिरो संवेदनशीलता वर्ग अनुसार क्षेत्रफल",
     label_en="Area by landslide-susceptibility class (table)", var_type="list", **_HV)
_reg("hazard_landslide_by_unit_table", label_ne="{{unit_label_np}} अनुसार पहिरो संवेदनशीलता",
     label_en="Landslide susceptibility by unit (table)", var_type="list", **_HV)
_reg("hazard_landslide_high_units", label_ne="उच्च पहिरो संवेदनशीलता एकाइहरू",
     label_en="High-susceptibility units", var_type="string", **_HV)
_reg("hazard_landslide_class_method", label_ne="LSI वर्गीकरण विधि",
     label_en="LSI classification method", var_type="string", **_HV)
_reg("hazard_landslide_ahp_cr", label_ne="AHP संगति अनुपात (CR)",
     label_en="LSI — AHP consistency ratio (CR)", var_type="number", **_HV)
_reg("hazard_landslide_aoi_comparison_table",
     label_ne="क्षेत्रगत पहिरो जोखिम तुलना (सा.व. / उपभोक्ता क्षेत्र)",
     label_en="Landslide-hazard comparison by area, CF / user-group (table)",
     var_type="list", **_HV)

_reg("hazard_slope_fs_enabled", label_ne="स्थायित्व गुणांक नक्सा समावेश",
     label_en="Factor-of-Safety map included", var_type="string", **_HV)
_reg("hazard_slope_unstable_area_ha", label_ne="अस्थिर क्षेत्रफल — मनसुन परिदृश्य (हे.)",
     label_en="Unstable area — monsoon scenario (ha)", var_type="number", **_HV)
_reg("hazard_slope_unstable_pct", label_ne="अस्थिर क्षेत्रफल (%)",
     label_en="Unstable area (%)", var_type="number", **_HV)
_reg("hazard_slope_marginal_pct", label_ne="सीमान्त स्थायित्व क्षेत्रफल (%)",
     label_en="Marginally-stable area (%)", var_type="number", **_HV)
_reg("hazard_slope_scenario_note", label_ne="FS परिदृश्य टिप्पणी",
     label_en="Slope-stability scenario note", var_type="string", **_HV)
_reg("hazard_slope_scenario_note_en", label_ne="FS परिदृश्य टिप्पणी (अङ्ग्रेजी)",
     label_en="Slope-stability scenario note (English)", var_type="string", **_HV)
_reg("hazard_slope_by_unit_table", label_ne="{{unit_label_np}} अनुसार ढलान स्थायित्व",
     label_en="Slope stability by unit (table)", var_type="list", **_HV)

_reg("hazard_household_count", label_ne="विश्लेषित घरधुरी संख्या",
     label_en="Households analysed", var_type="number", **_HV)
_reg("hazard_household_priority_count", label_ne="प्राथमिकता घरधुरी संख्या",
     label_en="Priority households", var_type="number", **_HV)
_reg("hazard_household_mean_score", label_ne="औसत घरधुरी जोखिम अंक",
     label_en="Mean household vulnerability score", var_type="number", **_HV)
_reg("hazard_household_layer_informative", label_ne="भौतिक प्रकोप तह विभेदकारी",
     label_en="Physical-hazard layer discriminative", var_type="string", **_HV)
_reg("hazard_household_priority_table",
     label_ne="प्राथमिकता घरधुरी सूची (घर नं. / टोल / अंक / कारक)",
     label_en="Priority households — house no. / tole / score / driver (table)",
     var_type="list", **_HV)
_reg("hazard_household_settlement_rollup_table", label_ne="टोल अनुसार घरधुरी जोखिम सारांश",
     label_en="Household vulnerability roll-up by settlement (table)", var_type="list", **_HV)
_reg("hazard_household_driver_counts_table", label_ne="प्रमुख जोखिम कारक अनुसार घरधुरी",
     label_en="Households by dominant vulnerability driver (table)", var_type="list", **_HV)

# P2 — values the Hazard & Erosion endpoints render that had no registry entry
# at all (so a designer could not drop them into a template). Resolution goes
# through the P1 alias fall-through to the collector key named in VARIABLE_ALIASES.
_reg("hazard_erosion_customised", label_ne="माटो क्षय — प्यारामिटर समायोजित",
     label_en="Soil loss — parameters customised for this forest", var_type="string", **_SE)
_reg("hazard_erosion_sdr_enabled", label_ne="तलछट वितरण अनुपात गणना सक्रिय",
     label_en="Sediment-delivery-ratio computation enabled", var_type="string", **_SE)
_reg("hazard_erosion_sdr_mean", label_ne="औसत तलछट वितरण अनुपात",
     label_en="Mean sediment delivery ratio", var_type="number", **_SE)
_reg("hazard_erosion_severity_breaks", label_ne="माटो क्षय गम्भीरता वर्ग सीमा",
     label_en="Soil-loss severity class breaks", var_type="list", **_SE)
_reg("hazard_erosion_ug_area_ha", label_ne="उपभोक्ता क्षेत्रको विश्लेषण क्षेत्रफल (हे.)",
     label_en="User-group analysed area (ha)", var_type="number", **_SE)
_reg("hazard_erosion_ug_minus_cf_area_ha",
     label_ne="वन बाहिरको बस्ती भूमिको क्षेत्रफल (हे.)",
     label_en="Settlement land outside the forest — area (ha)", var_type="number", **_SE)
_reg("hazard_landslide_customised", label_ne="पहिरो जोखिम — प्यारामिटर समायोजित",
     label_en="Landslide hazard — parameters customised for this forest",
     var_type="string", **_HV)
_reg("hazard_slope_marginal_area_ha", label_ne="सीमान्त स्थायित्व क्षेत्रफल (हे.)",
     label_en="Marginally-stable area (ha)", var_type="number", **_HV)
_reg("hazard_slope_depth_mean_m", label_ne="औसत रेगोलिथ गहिराइ (मि.)",
     label_en="Mean regolith depth (m)", var_type="number", **_HV)
_reg("hazard_household_max_score", label_ne="अधिकतम घरधुरी जोखिम अंक",
     label_en="Maximum household vulnerability score", var_type="number", **_HV)
_reg("hazard_household_coord_source", label_ne="घरधुरी निर्देशांक स्रोत",
     label_en="Household coordinate source (survey / building footprint)",
     var_type="string", **_HV)

# P2 — one drop-in variable with the whole Hazard & Erosion write-up (the six
# methodology/findings/prescription paragraphs under headings). Assembled in
# data_collector; plain key in raw["soil_erosion"].
_reg("hazard_erosion_full_narration",
     label_ne="माटो क्षय, पहिरो र घरधुरी जोखिम — पूर्ण विवरण",
     label_en="Soil loss, landslide & household hazard — full narrative",
     var_type="string", **_SE)

# P2 — charts (Chart.js dicts via variable_resolver._resolve_chart). The
# Hazard & Erosion page has no charts today; these are the core 4.
_reg("chart:hazard_landslide_area_by_class", "A",
     "पहिरो संवेदनशीलता वर्ग अनुसार क्षेत्रफल (बार चार्ट)",
     "Area by landslide-susceptibility class (bar chart)",
     var_type="dict", source="hazard_vuln", section="S9")
_reg("chart:hazard_slope_class_split", "A",
     "ढलान स्थायित्व वर्ग विभाजन (बार चार्ट)",
     "Slope-stability class split — unstable / marginal / stable (bar chart)",
     var_type="dict", source="hazard_vuln", section="S9")
_reg("chart:hazard_household_driver_split", "A",
     "प्रमुख जोखिम कारक अनुसार घरधुरी (बार चार्ट)",
     "Households by dominant vulnerability driver (bar chart)",
     var_type="dict", source="hazard_vuln", section="S9")
_reg("chart:hazard_erosion_aoi_comparison", "A",
     "माटो क्षय — क्षेत्रगत तुलना (बार चार्ट)",
     "Soil loss — CF vs user-group comparison (bar chart)",
     var_type="dict", source="soil_erosion", section="S9")

# stamp each legacy twin as a deprecated alias so listing surfaces show only the
# canonical key (resolution still finds it by dict lookup).
for _canon, _legacy in VARIABLE_ALIASES.items():
    _legacy_def = VARIABLE_REGISTRY.get(_legacy)
    if _legacy_def is not None and not _legacy_def.alias_of:
        _legacy_def.alias_of = _canon

# ── Financial Analysis: Cost-Benefit Analysis (P7). source="cost_benefit" →
#    data_collector.get_cost_benefit_data. NPV/IRR/B-C from the *base* scenario.
_CBA = dict(category="A", source="cost_benefit", section="S14")
_reg("cba_discount_rate", label_ne="आर्थिक विश्लेषण — छुट दर (%)",
     label_en="CBA — discount rate (%)", var_type="number", precision=1, **_CBA)
_reg("cba_time_horizon_years", label_ne="आर्थिक विश्लेषण — विश्लेषण अवधि (वर्ष)",
     label_en="CBA — analysis horizon (years)", var_type="number", precision=0, **_CBA)
_reg("cba_base_npv", label_ne="आर्थिक विश्लेषण — खुद वर्तमान मूल्य (NPV)",
     label_en="CBA — NPV of base scenario", var_type="number", precision=0, **_CBA)
_reg("cba_base_irr", label_ne="आर्थिक विश्लेषण — आन्तरिक प्रतिफल दर (IRR %)",
     label_en="CBA — IRR of base scenario (%)", var_type="number", precision=1, **_CBA)
_reg("cba_base_bc_ratio", label_ne="आर्थिक विश्लेषण — लाभ-लागत अनुपात (B/C)",
     label_en="CBA — benefit-cost ratio of base scenario", var_type="number", **_CBA)
_reg("cba_base_payback", label_ne="आर्थिक विश्लेषण — भुक्तानी अवधि (वर्ष)",
     label_en="CBA — payback period of base scenario (years)", var_type="number",
     precision=1, **_CBA)
_reg("cba_verdict", label_ne="आर्थिक विश्लेषण — निष्कर्ष",
     label_en="CBA — viability verdict", var_type="string", **_CBA)
_reg("cba_summary_table", label_ne="आर्थिक विश्लेषण — सूचकांक सारांश",
     label_en="CBA — indicator summary", var_type="list", **_CBA)
_reg("cba_cash_flow_table", label_ne="आर्थिक विश्लेषण — वार्षिक नगद प्रवाह",
     label_en="CBA — year-wise cash flow", var_type="list", **_CBA)
_reg("cba_cost_breakdown", label_ne="आर्थिक विश्लेषण — लागत विवरण (शीर्षकगत)",
     label_en="CBA — cost breakdown by category", var_type="list", **_CBA)
_reg("cba_benefit_breakdown", label_ne="आर्थिक विश्लेषण — लाभ विवरण (स्रोतगत)",
     label_en="CBA — benefit breakdown by source", var_type="list", **_CBA)

# ── § ३.१०: Sustainable Forest Management (दिगो वन व्यवस्थापन) — P6.
#    source="sustainable_fm" → data_collector.get_sustainable_fm_data (read-only;
#    the SFM tab builds result_data['sfm']). Rendered BESIDE the MAI→AAH section.
_SFM = dict(category="A", source="sustainable_fm", section="S3")
_reg("sfm_dominant_type_ne", label_ne="दिगो वन व्यवस्थापन — प्रमुख वन प्रकार",
     label_en="SFM — dominant forest type", var_type="string", **_SFM)
_reg("sfm_dominant_type_en", label_ne="दिगो वन व्यवस्थापन — प्रमुख वन प्रकार (अङ्ग्रेजी)",
     label_en="SFM — dominant forest type (English)", var_type="string", **_SFM)
_reg("sfm_total_annual_harvest_m3",
     label_ne="उत्पादन नियमन अनुसारको वार्षिक कटान परिमाण (घन.मी.)",
     label_en="SFM — allowable annual harvest, production regulation (m³)",
     var_type="number", precision=1, **_SFM)
_reg("sfm_production_area_ha", label_ne="दिगो वन व्यवस्थापन — उत्पादनशील क्षेत्रफल (हे.)",
     label_en="SFM — production area (ha)", var_type="number", precision=2, **_SFM)
_reg("sfm_protection_area_ha", label_ne="दिगो वन व्यवस्थापन — संरक्षण क्षेत्रफल (हे.)",
     label_en="SFM — protection area (ha)", var_type="number", precision=2, **_SFM)
_reg("sfm_plan_regime_note", label_ne="दिगो वन व्यवस्थापन — कार्ययोजना प्रकृति टिप्पणी",
     label_en="SFM — plan regime note", var_type="string", **_SFM)
_reg("sfm_sampling_intensity_note", label_ne="दिगो वन व्यवस्थापन — नमुना तीव्रता टिप्पणी",
     label_en="SFM — sampling intensity note", var_type="string", **_SFM)
_reg("sfm_felling_series_note", label_ne="दिगो वन व्यवस्थापन — कटान श्रृंखला टिप्पणी",
     label_en="SFM — felling series note", var_type="string", **_SFM)
_reg("sfm_methodology", label_ne="दिगो वन व्यवस्थापन — विधि",
     label_en="SFM — methodology", var_type="string", **_SFM)
_reg("sfm_findings", label_ne="दिगो वन व्यवस्थापन — नतिजा",
     label_en="SFM — findings", var_type="string", **_SFM)
_reg("sfm_prescription", label_ne="दिगो वन व्यवस्थापन — सिफारिस",
     label_en="SFM — prescription", var_type="string", **_SFM)
_reg("sfm_block_prescription_table",
     label_ne="दिगो वन व्यवस्थापन — {{unit_label_np}} अनुसार प्रिस्क्रिप्सन",
     label_en="SFM — per-unit prescription table", var_type="list", **_SFM)
_reg("sfm_type_area_table", label_ne="दिगो वन व्यवस्थापन — वन प्रकार अनुसार क्षेत्रफल",
     label_en="SFM — area by forest type", var_type="list", **_SFM)
_reg("sfm_yield_table", label_ne="दिगो वन व्यवस्थापन — कटान श्रृंखला अनुसार उत्पादन नियमन",
     label_en="SFM — yield regulation by felling series", var_type="list", **_SFM)
_reg("sfm_working_circle_table", label_ne="दिगो वन व्यवस्थापन — कार्य वृत्त अभिमुखीकरण",
     label_en="SFM — working-circle orientation", var_type="list", **_SFM)
_reg("sfm_sampling_plan_table", label_ne="दिगो वन व्यवस्थापन — नमुना योजना (सुझाव)",
     label_en="SFM — advisory sampling plan", var_type="list", **_SFM)

_reg(
    "fi_basal_area_m2_per_ha",
    "A",
    "प्रतिहेक्टर आधार क्षेत्र",
    "Basal Area per ha",
    var_type="number",
    source="field_inventory",
)
_reg(
    "fi_regeneration_condition",
    "A",
    "पुनरुत्पादन अवस्था",
    "Regeneration Condition",
    source="field_inventory",
)
_reg(
    "fi_forest_condition", "A", "वन अवस्था", "Forest Condition", source="field_inventory"
)
_reg(
    "fi_mai_percent",
    "A",
    "MAI प्रतिशत",
    "MAI Percent",
    var_type="number",
    source="field_inventory",
    precision=1,
)
_reg(
    "fi_agb_t_per_ha",
    "A",
    "प्रतिहेक्टर AGB (टन)",
    "AGB t/ha",
    var_type="number",
    source="field_inventory",
    precision=3,
)
_reg(
    "fi_bgb_t_per_ha",
    "A",
    "प्रतिहेक्टर BGB (टन)",
    "BGB t/ha",
    var_type="number",
    source="field_inventory",
    precision=3,
)
_reg(
    "fi_total_biomass_t_per_ha",
    "A",
    "प्रतिहेक्टर कुल जैविक पदार्थ",
    "Total Biomass t/ha",
    var_type="number",
    source="field_inventory",
    precision=3,
)
_reg(
    "fi_carbon_stock_tc_per_ha",
    "A",
    "प्रतिहेक्टर कार्बन मौज्दात",
    "Carbon Stock tC/ha",
    var_type="number",
    source="field_inventory",
    precision=3,
)
_reg(
    "fi_co2_equivalent_tco2_per_ha",
    "A",
    "प्रतिहेक्टर CO₂ समतुल्य",
    "CO₂ Equivalent tCO₂/ha",
    var_type="number",
    source="field_inventory",
    precision=3,
)
_reg(
    "fi_weighted_wood_density",
    "A",
    "भारित काठ घनत्व",
    "Weighted Wood Density",
    var_type="number",
    source="field_inventory",
    precision=4,
)
_reg(
    "fi_species_block_growing_stock",
    "A",
    "ब्लक अनुसार प्रजाति वन मौज्दात (पोल+रूख)",
    "Block-wise Species Growing Stock (Pole+Tree)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_regeneration_status",
    "A",
    "वन खन्ड अनुसार पुनरोत्पादनको स्थिति",
    "Forest Block-wise Regeneration Status",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_dbh_class_growing_stock",
    "A",
    "ब्लक अनुसार DBH वर्ग वन मौज्दात",
    "Block-wise DBH Class Growing Stock",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_dbh_class_growing_stock_np",
    "A",
    "ब्लक अनुसार DBH वर्ग वन मौज्दात (नेपाली)",
    "Block-wise DBH Class Growing Stock (Nepali)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_dbh_class_ag_np",
    "A",
    "ब्यास क्लास अनुसार प्रति हेक्टर मौज्दात (एड्भान्स ग्रोथ र परिपक्व रूख)",
    "DBH Class Growing Stock — Advance Growth & Mature Tree (Nepali)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_dbh_class_advance_np",
    "A",
    "एड्भान्स ग्रोथ (१०-४० से.मी.) अनुसार प्रति हेक्टर मौज्दात",
    "Advance Growth (10-40 cm) Growing Stock per ha (Nepali)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_dbh_class_mature_np",
    "A",
    "परिपक्व रूख (>४० से.मी.) अनुसार प्रति हेक्टर मौज्दात",
    "Mature Tree (>40 cm) Growing Stock per ha (Nepali)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_summaries",
    "A",
    "ब्लक अनुसार पूर्ण नतिजा",
    "Block-wise Full Results",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_tree_count_per_ha",
    "A",
    "वन ब्लक अनुसार प्रति हेक्टर विरूवा, लाथ्रा, पोल तथा रूखको संख्या",
    "Block-wise Trees per Hectare (Regen/Sapling/Pole/Tree)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_pole_tree_volume",
    "A",
    "ब्लक अनुसार प्रति हेक्टर पोल (खाँवा) तथा रूखको काठ दाउराको परिणाम घ.मी.",
    "Block-wise Pole & Tree Timber/Firewood Volume m³/ha",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_growing_stock",
    "A",
    "वन ब्लक अनुसार काठ, दाउरा तथा जम्मा वृद्धि मौज्दात (Growing Stock) प्रति हेक्टर",
    "Block-wise Growing Stock (Timber/Firewood/Total) m³/ha",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_basal_area",
    "A",
    "ब्लक अनुसार प्रति हेक्टर वेसल एरीया",
    "Block-wise Basal Area m²/ha",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_satellite_volume",
    "A",
    "NASA/ORNL/biomass_carbon_density/v1 को अधारमा प्रति हेक्टर ग्रोइङ्स्टक अनुमान (घ.मी. प्रति हेक्टर)",
    "Block-wise Satellite-derived Growing Stock m³/ha",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_condition_growth",
    "A",
    "ब्लक अनुसार पुनरोत्पादन तथा वनको अवस्था र वार्षिक वृद्धि निर्धारण",
    "Block-wise Regeneration/Forest Condition & MAI%",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_block_biomass_carbon",
    "A",
    "(IPCC/REDD+) अनुसारको वनश्रोत सर्भेक्षणको अधारमा बायोमास तथा कार्वनको अनुमान",
    "Block-wise Biomass & Carbon (IPCC/REDD+)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_mai_table",
    "A",
    "वार्षिक वृद्धि तालिका (m³/ha/yr)",
    "Annual Increment (MAI) Table",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_aah_table",
    "A",
    "वार्षिक स्वीकार्य कटान तालिका (m³/ha/yr)",
    "Annual Allowable Cut (AAH) Table",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_species_composition",
    "A",
    "प्रजाति संरचना (प्रतिशत)",
    "Species Composition (%)",
    var_type="dict",
    source="field_inventory",
)
_reg(
    "fi_dominant_species",
    "A",
    "मुख्य प्रजाति",
    "Dominant Species",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_co_dominant_species",
    "A",
    "सह-मुख्य प्रजाति",
    "Co-dominant Species",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_associated_species",
    "A",
    "आनुषंगिक प्रजाति",
    "Associated Species",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_fast_growing_species",
    "A",
    "द्रुत बृद्धि हुने प्रजाति",
    "Fast Growing Species",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_moderate_growing_species",
    "A",
    "मध्यम बृद्धि हुने प्रजाति",
    "Moderate Growing Species",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_slow_growing_species",
    "A",
    "सुस्त बृद्धि हुने प्रजाति",
    "Slow Growing Species",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_species_volume_by_block",
    "A",
    "ब्लक अनुसार प्रजाति आयतन",
    "Block-wise Species Volume",
    var_type="list",
    source="field_inventory",
)

# ---- Mode-agnostic aliases for fi_block_* variables ----
# These resolve to the same data as the fi_block_* equivalents.
# Use in OP templates that need to work for both blocks AND compartments.
_reg(
    "fi_unit_regeneration_status",
    "A",
    "एकाइ अनुसार पुनरोत्पादन स्थिति",
    "Unit-wise Regeneration Status",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_unit_dbh_class_growing_stock",
    "A",
    "एकाइ अनुसार DBH वर्ग वन मौज्दात",
    "Unit-wise DBH Class Growing Stock",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_unit_dbh_class_growing_stock_np",
    "A",
    "एकाइ अनुसार DBH वर्ग वन मौज्दात (नेपाली)",
    "Unit-wise DBH Class Growing Stock (Nepali)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_unit_summaries",
    "A",
    "एकाइ अनुसार पूर्ण नतिजा",
    "Unit-wise Full Results",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_unit_tree_count_per_ha",
    "A",
    "एकाइ अनुसार प्रति हेक्टर रूख संख्या",
    "Unit-wise Tree Count per ha",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_unit_pole_tree_volume",
    "A",
    "एकाइ अनुसार पोल+रूख आयतन",
    "Unit-wise Pole & Tree Volume",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_unit_growing_stock",
    "A",
    "एकाइ अनुसार प्रति हेक्टर वृद्धि मौज्दात",
    "Unit-wise Growing Stock per ha",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_unit_basal_area",
    "A",
    "एकाइ अनुसार आधार क्षेत्र",
    "Unit-wise Basal Area",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_unit_satellite_volume",
    "A",
    "एकाइ अनुसार उपग्रह-आधारित आयतन",
    "Unit-wise Satellite Volume",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_unit_condition_growth",
    "A",
    "एकाइ अनुसार अवस्था तथा वार्षिक वृद्धि",
    "Unit-wise Condition & MAI%",
    var_type="list",
    source="field_inventory",
)
_reg(
    "fi_unit_biomass_carbon",
    "A",
    "एकाइ अनुसार बायोमास तथा कार्बन",
    "Unit-wise Biomass & Carbon",
    var_type="list",
    source="field_inventory",
)
# A10b: Total Inventory — कुल मौज्दात (Absolute quantities from per-hectare data)
# Scalar forest-wide totals
_reg(
    "ti_available",
    "A",
    "कुल मौज्दात उपलब्ध",
    "Total Inventory Available",
    var_type="boolean",
    source="field_inventory",
)
_reg(
    "ti_effective_area_ha",
    "A",
    "प्रभावकारी क्षेत्रफल (हे)",
    "Effective Area (ha)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "ti_total_blocks",
    "A",
    "कुल ब्लक सङ्ख्या",
    "Total Blocks",
    var_type="number",
    source="field_inventory",
    precision=0,
)
_reg(
    "ti_total_plots",
    "A",
    "कुल नमूना प्लट",
    "Total Sample Plots",
    var_type="number",
    source="field_inventory",
    precision=0,
)
_reg(
    "ti_total_regeneration",
    "A",
    "कुल पुनरुत्पादन (सङ्ख्या)",
    "Total Regeneration (count)",
    var_type="number",
    source="field_inventory",
    precision=0,
)
_reg(
    "ti_total_sapling",
    "A",
    "कुल लाथ्रा (सङ्ख्या)",
    "Total Sapling (count)",
    var_type="number",
    source="field_inventory",
    precision=0,
)
_reg(
    "ti_total_pole",
    "A",
    "कुल पोल/खाँवा (सङ्ख्या)",
    "Total Pole (count)",
    var_type="number",
    source="field_inventory",
    precision=0,
)
_reg(
    "ti_total_tree",
    "A",
    "कुल रूख (सङ्ख्या)",
    "Total Tree (count)",
    var_type="number",
    source="field_inventory",
    precision=0,
)
_reg(
    "ti_total_growing_stock_m3",
    "A",
    "कुल वन मौज्दात (m³)",
    "Total Growing Stock (m³)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "ti_production_area_ha",
    "A",
    "उत्पादन कार्य वृत्तको क्षेत्रफल (हे)",
    "Production Working-Circle Area (ha)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "ti_protection_working_circle_area_ha",
    "A",
    "संरक्षित कार्य वृत्तको क्षेत्रफल (हे)",
    "Protection Working-Circle Area (ha)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "ti_protected_area_ha",
    "A",
    "संरक्षित क्षेत्रफल (हे)",
    "Protection-stratum Area (ha)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "ti_protected_growing_stock_m3",
    "A",
    "संरक्षित क्षेत्रको कुल वन मौज्दात (m³) — कटानमा समावेश छैन",
    "Protection-stratum Total Growing Stock (m³, excluded from AAH)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "ti_total_basal_area_m2",
    "A",
    "कुल आधार क्षेत्र (m²)",
    "Total Basal Area (m²)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "ti_total_mai_m3_per_year",
    "A",
    "कुल वार्षिक वृद्धि (m³/वर्ष)",
    "Total MAI (m³/yr)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "ti_total_aah_m3_per_year",
    "A",
    "कुल वार्षिक स्वीकार्य कटानी (m³/वर्ष)",
    "Total AAH (m³/yr)",
    var_type="number",
    source="field_inventory",
)
_reg(
    "ti_total_agb_tonnes",
    "A",
    "कुल जमिन माथिको बायोमास (टन)",
    "Total AGB (tonnes)",
    var_type="number",
    source="field_inventory",
    precision=3,
)
_reg(
    "ti_total_bgb_tonnes",
    "A",
    "कुल जमिन मुनिको बायोमास (टन)",
    "Total BGB (tonnes)",
    var_type="number",
    source="field_inventory",
    precision=3,
)
_reg(
    "ti_total_biomass_tonnes",
    "A",
    "कुल जैविक पदार्थ (टन)",
    "Total Biomass (tonnes)",
    var_type="number",
    source="field_inventory",
    precision=3,
)
_reg(
    "ti_total_carbon_tc",
    "A",
    "कुल कार्बन मौज्दात (tC)",
    "Total Carbon Stock (tC)",
    var_type="number",
    source="field_inventory",
    precision=3,
)
_reg(
    "ti_total_co2_tco2",
    "A",
    "कुल CO₂ समतुल्य (tCO₂)",
    "Total CO₂ Equivalent (tCO₂)",
    var_type="number",
    source="field_inventory",
    precision=3,
)
_reg(
    "ti_weighted_wood_density",
    "A",
    "भारित काठ घनत्व",
    "Weighted Wood Density",
    var_type="number",
    source="field_inventory",
    precision=4,
)

# Block-wise list variables (absolute / कुल मौज्दात)
_reg(
    "ti_block_summaries",
    "A",
    "ब्लक अनुसार कुल मौज्दात (पूर्ण नतिजा)",
    "Block-wise Total Inventory (Full Results)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_block_tree_count_total",
    "A",
    "ब्लक अनुसार कुल रूख सङ्ख्या",
    "Block-wise Total Tree Count",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_block_pole_tree_volume",
    "A",
    "ब्लक अनुसार कुल पोल तथा रूख आयतन",
    "Block-wise Total Pole & Tree Volume",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_block_growing_stock",
    "A",
    "ब्लक अनुसार कुल वृद्धि मौज्दात",
    "Block-wise Total Growing Stock",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_block_basal_area",
    "A",
    "ब्लक अनुसार कुल आधार क्षेत्र",
    "Block-wise Total Basal Area",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_block_satellite_volume",
    "A",
    "ब्लक अनुसार कुल उपग्रह-आधारित आयतन",
    "Block-wise Total Satellite Volume",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_block_condition_growth",
    "A",
    "ब्लक अनुसार अवस्था तथा वार्षिक वृद्धि",
    "Block-wise Condition & MAI%",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_block_biomass_carbon",
    "A",
    "ब्लक अनुसार कुल बायोमास तथा कार्बन",
    "Block-wise Total Biomass & Carbon",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_block_regeneration_status",
    "A",
    "ब्लक अनुसार पुनरोत्पादन अवस्था",
    "Block-wise Regeneration Status",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_mai_table",
    "A",
    "वार्षिक वृद्धि तालिका (कुल)",
    "MAI Table (Absolute)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_aah_table",
    "A",
    "वार्षिक स्वीकार्य कटानी तालिका (कुल)",
    "AAH Table (Absolute)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_species_block_growing_stock",
    "A",
    "ब्लक अनुसार प्रजाति कुल मौज्दात",
    "Block-wise Species Total Growing Stock",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_species_volume_by_block",
    "A",
    "ब्लक अनुसार प्रजाति कुल आयतन",
    "Block-wise Species Total Volume",
    var_type="list",
    source="field_inventory",
)

# ---- Mode-agnostic aliases for ti_block_* variables ----
_reg(
    "ti_unit_summaries",
    "A",
    "एकाइ अनुसार कुल मौज्दात (पूर्ण नतिजा)",
    "Unit-wise Total Inventory (Full Results)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_unit_tree_count_total",
    "A",
    "एकाइ अनुसार कुल रूख संख्या",
    "Unit-wise Total Tree Count",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_unit_pole_tree_volume",
    "A",
    "एकाइ अनुसार कुल पोल तथा रूख आयतन",
    "Unit-wise Total Pole & Tree Volume",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_unit_growing_stock",
    "A",
    "एकाइ अनुसार कुल वृद्धि मौज्दात",
    "Unit-wise Total Growing Stock",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_unit_basal_area",
    "A",
    "एकाइ अनुसार कुल आधार क्षेत्र",
    "Unit-wise Total Basal Area",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_unit_satellite_volume",
    "A",
    "एकाइ अनुसार कुल उपग्रह-आधारित आयतन",
    "Unit-wise Total Satellite Volume",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_unit_condition_growth",
    "A",
    "एकाइ अनुसार अवस्था तथा वार्षिक वृद्धि",
    "Unit-wise Condition & MAI%",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_unit_biomass_carbon",
    "A",
    "एकाइ अनुसार कुल बायोमास तथा कार्बन",
    "Unit-wise Total Biomass & Carbon",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_unit_regeneration_status",
    "A",
    "एकाइ अनुसार पुनरोत्पादन अवस्था",
    "Unit-wise Regeneration Status",
    var_type="list",
    source="field_inventory",
)

# Species composition (absolute values)
_reg(
    "ti_species_composition_absolute",
    "A",
    "प्रजाति संरचना (कुल मौज्दात)",
    "Species Composition (Absolute)",
    var_type="dict",
    source="field_inventory",
)
_reg(
    "ti_dominant_species_absolute",
    "A",
    "मुख्य प्रजाति (कुल)",
    "Dominant Species (Absolute)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_co_dominant_species_absolute",
    "A",
    "सह-मुख्य प्रजाति (कुल)",
    "Co-dominant Species (Absolute)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_associated_species_absolute",
    "A",
    "आनुषंगिक प्रजाति (कुल)",
    "Associated Species (Absolute)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_fast_growing_species_total",
    "A",
    "द्रुत वृद्धि प्रजाति कुल आयतन",
    "Fast Growing Species Total",
    var_type="number",
    source="field_inventory",
)
_reg(
    "ti_moderate_growing_species_total",
    "A",
    "मध्यम वृद्धि प्रजाति कुल आयतन",
    "Moderate Growing Species Total",
    var_type="number",
    source="field_inventory",
)
_reg(
    "ti_slow_growing_species_total",
    "A",
    "सुस्त वृद्धि प्रजाति कुल आयतन",
    "Slow Growing Species Total",
    var_type="number",
    source="field_inventory",
)

# Chart variables for Total Inventory
_reg(
    "ti_chart_block_stock_pie",
    "A",
    "ब्लक अनुसार ग्रोइङ स्टक पाई चार्ट",
    "Block-wise Growing Stock Pie Chart",
    var_type="dict",
    source="field_inventory",
)
_reg(
    "ti_chart_block_comparison_bar",
    "A",
    "ब्लक तुलना बार चार्ट",
    "Block Comparison Bar Chart",
    var_type="dict",
    source="field_inventory",
)
_reg(
    "ti_chart_dbh_class_bar",
    "A",
    "DBH वर्ग आयतन बार चार्ट",
    "DBH Class Volume Bar Chart",
    var_type="dict",
    source="field_inventory",
)

# A10c: Total Inventory — new table variables for OP document
_reg(
    "ti_block_area_table",
    "A",
    "ब्लक क्षेत्रफल — प्रभावकारी वन आवरण",
    "Block Area — Effective Forest Cover",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_species_dbh_class_table",
    "A",
    "प्रजाति अनुसार DBH क्लास मौज्दात",
    "Species-wise DBH Class Growing Stock",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_forest_dbh_class_table",
    "A",
    "पुरै वन क्षेत्र — प्रजाति अनुसार DBH क्लास मौज्दात",
    "Entire Forest — Species-wise DBH Class",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_dbh_class_totals_table",
    "A",
    "DBH क्लास अनुसार कुल मौज्दात",
    "DBH Class Total Growing Stock",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_dbh_class_perha_table",
    "A",
    "DBH क्लास अनुसार कुल मौज्दात (प्रति हे.)",
    "DBH Class Total Growing Stock (per ha)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_dbh_mai_table",
    "A",
    "DBH क्लास अनुसार MAI",
    "DBH Class-wise MAI",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_dbh_aah_table",
    "A",
    "DBH क्लास अनुसार AAH",
    "DBH Class-wise AAH",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_species_composition_table",
    "A",
    "प्रजाति संरचना (स्थानीय नाम)",
    "Species Composition (Local Name)",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_block_productivity_table",
    "A",
    "ब्लक अनुसार उत्पादनसिल संचिती",
    "Block-wise Productive Growing Stock",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_economic_valuation_table",
    "A",
    "आर्थिक मूल्याङ्कन",
    "Economic Valuation",
    var_type="list",
    source="field_inventory",
)
_reg(
    "ti_sustainability_table",
    "A",
    "दिगोपन सूचकांक",
    "Sustainability Index",
    var_type="list",
    source="field_inventory",
)

# A10d: Total Inventory — section narrations (auto-generated)
_reg(
    "section:ti_block_area_narration",
    "A",
    "ब्लक क्षेत्रफल विवरण (स्वतः उत्पन्न)",
    "Block Area Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_forest_total_narration",
    "A",
    "सामुदायिक वन कुल योग विवरण (स्वतः उत्पन्न)",
    "Forest Total Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_block_growing_stock_narration",
    "A",
    "ब्लक मौज्दात विवरण (स्वतः उत्पन्न)",
    "Block Growing Stock Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_species_stock_narration",
    "A",
    "प्रजाति मौज्दात विवरण (स्वतः उत्पन्न)",
    "Species Stock Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_species_dbh_narration",
    "A",
    "प्रजाति DBH वर्ग मौज्दात विवरण (स्वतः उत्पन्न)",
    "Species DBH Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_forest_dbh_narration",
    "A",
    "पुरै वन DBH वर्ग विवरण (स्वतः उत्पन्न)",
    "Forest DBH Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_dbh_total_narration",
    "A",
    "DBH वर्ग कुल मौज्दात विवरण (स्वतः उत्पन्न)",
    "DBH Class Total Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_dbh_perha_narration",
    "A",
    "DBH वर्ग प्रति हे. मौज्दात विवरण (स्वतः उत्पन्न)",
    "DBH Class Per Ha Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_dbh_mai_narration",
    "A",
    "DBH वर्ग MAI विवरण (स्वतः उत्पन्न)",
    "DBH Class MAI Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_dbh_aah_narration",
    "A",
    "DBH वर्ग AAH विवरण (स्वतः उत्पन्न)",
    "DBH Class AAH Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_species_composition_narration",
    "A",
    "प्रजाति संरचना विवरण (स्वतः उत्पन्न)",
    "Species Composition Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_productivity_narration",
    "A",
    "उत्पादनसिल संचिती विवरण (स्वतः उत्पन्न)",
    "Productivity Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_economic_narration",
    "A",
    "आर्थिक मूल्याङ्कन विवरण (स्वतः उत्पन्न)",
    "Economic Valuation Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ti_sustainability_narration",
    "A",
    "दिगोपन सूचकांक विवरण (स्वतः उत्पन्न)",
    "Sustainability Index Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)

_reg(
    "section:field_inventory_narration",
    "A",
    "क्षेत्र सर्वेक्षण विवरण (स्वतः उत्पन्न)",
    "Field Inventory Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:sampling_narration",
    "A",
    "स्याम्पलिङ विवरण (स्वतः उत्पन्न)",
    "Sampling Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:fieldbook_narration",
    "A",
    "फिल्डबुक विवरण (स्वतः उत्पन्न)",
    "Fieldbook Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:household_narration",
    "A",
    "घरधुरी विवरण (स्वतः उत्पन्न)",
    "Household Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:committee_narration",
    "A",
    "समिति विवरण (स्वतः उत्पन्न)",
    "Committee Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:user_group_narration",
    "A",
    "उपभोक्ता समूह विवरण (स्वतः उत्पन्न)",
    "User Group Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:demand_supply_narration",
    "A",
    "माग/आपूर्ति विवरण (स्वतः उत्पन्न)",
    "Demand & Supply Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)

# Tree Mapping Analysis Narrations
_reg(
    "section:sm_hierarchy_narration",
    "A",
    "स्थानिक स्तर रूख सारांश विवरण (स्वतः उत्पन्न)",
    "Hierarchy Summary Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:sm_species_narration",
    "A",
    "प्रजाति संरचना विवरण (स्वतः उत्पन्न)",
    "Species Composition Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:sm_dbh_narration",
    "A",
    "DBH वर्ग विवरण (स्वतः उत्पन्न)",
    "DBH Class Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:sm_stand_type_narration",
    "A",
    "स्ट्यान्ड प्रकार विवरण (स्वतः उत्पन्न)",
    "Stand Type Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:sm_carbon_narration",
    "A",
    "कार्बन मौज्दात विवरण (स्वतः उत्पन्न)",
    "Carbon Stock Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:sm_volume_narration",
    "A",
    "आयतन वितरण विवरण (स्वतः उत्पन्न)",
    "Volume Distribution Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:sm_mother_tree_narration",
    "A",
    "माँउ रूख कभरेज विवरण (स्वतः उत्पन्न)",
    "Mother Tree Coverage Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:sm_felling_narration",
    "A",
    "कटानी रूख विश्लेषण विवरण (स्वतः उत्पन्न)",
    "Felling Tree Analysis Narration (Auto-generated)",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)

# A11: Sampling (14)
_reg(
    "sampling_available",
    "A",
    "नमूना योजना उपलब्ध",
    "Sampling Available",
    var_type="boolean",
    source="sampling",
)
_reg("sampling_type", "A", "नमूना प्रकार", "Sampling Type", source="sampling")
_reg(
    "sampling_total_points",
    "A",
    "कुल नमूना बिन्दु",
    "Total Sample Points",
    var_type="number",
    source="sampling",
)
_reg(
    "sampling_total_blocks",
    "A",
    "कुल ब्लक सङ्ख्या",
    "Total Blocks",
    var_type="number",
    source="sampling",
)
_reg("sampling_plot_shape", "A", "प्लट आकार", "Plot Shape", source="sampling")
_reg(
    "sampling_plot_radius_m",
    "A",
    "प्लट अर्धव्यास (मि)",
    "Plot Radius (m)",
    var_type="number",
    source="sampling",
)
_reg(
    "sampling_intensity_per_ha",
    "A",
    "प्रतिहेक्टर तीव्रता",
    "Intensity per ha",
    var_type="number",
    source="sampling",
)
_reg(
    "sampling_requested_intensity",
    "A",
    "अनुरोध गरिएको नमुना इन्टेन्सिटी",
    "Requested Intensity",
    var_type="number",
    source="sampling",
)
_reg(
    "sampling_actual_intensity",
    "A",
    "वास्तविक नमुना इन्टेन्सिटी",
    "Actual Sampling Intensity",
    var_type="number",
    source="sampling",
)
_reg(
    "sampling_block_summary",
    "A",
    "ब्लक अनुसार नमुनाप्लट विवरण तालीका",
    "Per-Block Sampling Summary",
    var_type="list",
    source="sampling",
)
_reg(
    "sampling_point_locations",
    "A",
    "नमुना प्लट स्थान विवरण तालीका",
    "Sample Point Locations",
    var_type="list",
    source="sampling",
)
_reg(
    "sampling_forest_area_ha",
    "A",
    "वन क्षेत्रफल (हे)",
    "Forest Area (ha)",
    var_type="number",
    source="sampling",
)
_reg(
    "sampling_plot_area_sqm",
    "A",
    "प्लट क्षेत्रफल (वर्गमि)",
    "Plot Area (sqm)",
    var_type="number",
    source="sampling",
)
_reg(
    "sampling_total_sampled_area_ha",
    "A",
    "जम्मा नमुना क्षेत्रफल (हे)",
    "Total Sampled Area (ha)",
    var_type="number",
    source="sampling",
)

# A12: Household (13)
_reg(
    "hh_available",
    "A",
    "घरधुरी डाटा उपलब्ध",
    "Household Data Available",
    var_type="boolean",
    source="household",
)
_reg(
    "hh_total_households",
    "A",
    "कुल घरधुरी",
    "Total Households",
    var_type="number",
    source="household",
)
_reg(
    "hh_total_population",
    "A",
    "कुल जनसंख्या",
    "Total Population",
    var_type="number",
    source="household",
)
_reg(
    "hh_total_male",
    "A",
    "पुरुष जनसंख्या",
    "Male Population",
    var_type="number",
    source="household",
)
_reg(
    "hh_total_female",
    "A",
    "महिला जनसंख्या",
    "Female Population",
    var_type="number",
    source="household",
)
_reg(
    "hh_prosperity_distribution",
    "A",
    "समृद्धि वितरण",
    "Prosperity Distribution",
    var_type="dict",
    source="household",
)
_reg(
    "hh_caste_distribution",
    "A",
    "जाति वितरण",
    "Caste Distribution",
    var_type="dict",
    source="household",
)
_reg(
    "hh_timber_demand_cft",
    "A",
    "काठ माग (cft)",
    "Timber Demand (cft)",
    var_type="number",
    source="household",
)
_reg(
    "hh_firewood_demand_bhari",
    "A",
    "दाउरा माग (भारी)",
    "Firewood Demand (bhari)",
    var_type="number",
    source="household",
)
_reg(
    "hh_forest_based_occupation",
    "A",
    "वन पेशा भएका घरधुरी",
    "Forest-based Occupation HH",
    var_type="number",
    source="household",
)
_reg(
    "chart:hh_caste_pie",
    "A",
    "जाति वितरण (पाई चार्ट)",
    "Caste Distribution Pie Chart",
    var_type="dict",
    source="household",
)
_reg(
    "chart:hh_prosperity_bar",
    "A",
    "समृद्धि वितरण (बार चार्ट)",
    "Prosperity Distribution Bar Chart",
    var_type="dict",
    source="household",
)
_reg(
    "chart:hh_demand_supply_bar",
    "A",
    "माग र आपूर्ति तुलना (बार चार्ट)",
    "Demand & Supply Comparison Bar Chart",
    var_type="dict",
    source="household",
)
_reg(
    "chart:demand_supply_bar",
    "A",
    "माग र आपूर्ति ब्रेकडाउन (बार चार्ट)",
    "Demand & Supply Breakdown Bar Chart",
    var_type="dict",
    source="household",
)
_reg(
    "chart:demand_supply_deficit_bar",
    "A",
    "बचत/कमी तुलना (बार चार्ट)",
    "Surplus/Deficit Comparison Bar Chart",
    var_type="dict",
    source="household",
)
_reg(
    "hh_records",
    "A",
    "घरपरिवारको विस्तृत तालिका",
    "Household Records Table",
    var_type="list",
    source="household",
)

# A13: Committees (9)
_reg(
    "uc_members",
    "A",
    "उपभोक्ता समिति सदस्य",
    "User Committee Members",
    var_type="list",
    source="committee",
)
_reg(
    "uc_total_members",
    "A",
    "उपभोक्ता समिति सदस्य सङ्ख्या",
    "UC Total Members",
    var_type="number",
    source="committee",
)
_reg(
    "ac_members",
    "A",
    "सल्लाहकार समिति सदस्य",
    "Advisory Committee Members",
    var_type="list",
    source="committee",
)
_reg(
    "ac_total_members",
    "A",
    "सल्लाहकार समिति सदस्य सङ्ख्या",
    "AC Total Members",
    var_type="number",
    source="committee",
)
_reg(
    "fc_members",
    "A",
    "वित्त समिति सदस्य",
    "Finance Committee Members",
    var_type="list",
    source="committee",
)
_reg(
    "fc_total_members",
    "A",
    "वित्त समिति सदस्य सङ्ख्या",
    "FC Total Members",
    var_type="number",
    source="committee",
)
_reg(
    "uc_gender_distribution",
    "A",
    "लैङ्गिक वितरण",
    "Gender Distribution",
    var_type="dict",
    source="committee",
)
_reg(
    "uc_position_distribution",
    "A",
    "पद वितरण",
    "Position Distribution",
    var_type="dict",
    source="committee",
)
_reg(
    "uc_caste_distribution",
    "A",
    "जातीय वितरण",
    "Caste Distribution",
    var_type="dict",
    source="committee",
)
_reg(
    "cf_chairperson",
    "A",
    "सामुदायिक वन अध्यक्ष",
    "CF Chairperson",
    source="committee",
    resolver="resolve_chairperson",
)

# NOTE: species variables populated by biodiversity module
# A14: Biodiversity (12)
_reg(
    "bio_available",
    "A",
    "जैविक विविधता उपलब्ध",
    "Biodiversity Available",
    var_type="boolean",
    source="biodiversity",
)
_reg(
    "bio_total_species",
    "A",
    "कुल जैविक प्रजाति",
    "Total Biodiversity Species",
    var_type="number",
    source="biodiversity",
)
_reg(
    "bio_vegetation_count",
    "A",
    "वनस्पति प्रजाति सङ्ख्या",
    "Vegetation Count",
    var_type="number",
    source="biodiversity",
)
_reg(
    "bio_animal_count",
    "A",
    "जनावर प्रजाति सङ्ख्या",
    "Animal Count",
    var_type="number",
    source="biodiversity",
)
_reg(
    "bio_protected_count",
    "A",
    "संरक्षित प्रजाति सङ्ख्या",
    "Protected Species Count",
    var_type="number",
    source="biodiversity",
)
_reg(
    "bio_invasive_count",
    "A",
    "मिचाहा प्रजाति सङ्ख्या",
    "Invasive Species Count",
    var_type="number",
    source="biodiversity",
)
_reg(
    "bio_iucn_cr",
    "A",
    "संकटग्रस्त प्रजाति (CR)",
    "Critically Endangered (CR)",
    var_type="number",
    source="biodiversity",
)
_reg(
    "bio_iucn_en",
    "A",
    "लोपोन्मुख प्रजाति (EN)",
    "Endangered (EN)",
    var_type="number",
    source="biodiversity",
)
_reg(
    "bio_iucn_vu",
    "A",
    "असुरक्षित प्रजाति (VU)",
    "Vulnerable (VU)",
    var_type="number",
    source="biodiversity",
)
_reg(
    "bio_sub_category_breakdown",
    "A",
    "उप-प्रकार अनुसार विवरण",
    "Sub-category Breakdown",
    var_type="dict",
    source="biodiversity",
)
_reg(
    "bio_vegetation",
    "A",
    "वनस्पति विवरण",
    "Vegetation Details",
    var_type="list",
    source="biodiversity",
)
_reg(
    "bio_animals",
    "A",
    "जनावर विवरण",
    "Animal Details",
    var_type="list",
    source="biodiversity",
)

# A15: Activities (4)
_reg(
    "activities_available",
    "A",
    "क्रियाकलाप उपलब्ध",
    "Activities Available",
    var_type="boolean",
    source="activities",
)
_reg(
    "activities_total",
    "A",
    "कुल क्रियाकलाप",
    "Total Activities",
    var_type="number",
    source="activities",
)
_reg(
    "activities_total_budget",
    "A",
    "कुल बजेट (रु)",
    "Total Budget (Rs)",
    var_type="number",
    source="activities",
)
_reg(
    "activities_list",
    "A",
    "क्रियाकलाप सूची",
    "Activities List",
    var_type="list",
    source="activities",
)

# A16: Yearly Plan — 10-Year Activity Breakdown (8)
_reg(
    "ya_available",
    "A",
    "वार्षिक योजना उपलब्ध",
    "Yearly Plan Available",
    var_type="boolean",
    source="yearly_activities",
)
_reg(
    "ya_year_summary",
    "A",
    "वर्ष अनुसार क्रियाकलाप सारांश",
    "Year-wise Activity Summary",
    var_type="list",
    source="yearly_activities",
)
_reg(
    "ya_plan_matrix",
    "A",
    "१० वर्षे योजना तालिका (क्रियाकलाप × वर्ष)",
    "10-Year Plan Matrix (Activity × Year)",
    var_type="list",
    source="yearly_activities",
)
_reg(
    "ya_program_budget",
    "A",
    "कार्यक्रम अनुसार बजेट विवरण",
    "Program-wise Budget Breakdown",
    var_type="list",
    source="yearly_activities",
)
_reg(
    "ya_total_budget_by_year",
    "A",
    "वर्ष अनुसार कुल बजेट",
    "Total Budget per Year",
    var_type="dict",
    source="yearly_activities",
)
_reg(
    "ya_total_ten_year_budget",
    "A",
    "१० वर्षे कुल बजेट",
    "Total 10-Year Budget",
    var_type="number",
    source="yearly_activities",
)
_reg(
    "ya_program_pie_data",
    "A",
    "कार्यक्रम अनुसार बजेट पाई डाटा",
    "Program Budget Pie Data",
    var_type="dict",
    source="yearly_activities",
)
_reg(
    "ya_budget_year_trend",
    "A",
    "वर्ष अनुसार बजेट प्रवृत्ति",
    "Budget Year Trend",
    var_type="dict",
    source="yearly_activities",
)
_reg(
    "ya_activity_plan_detail",
    "A",
    "क्रियाकलाप योजना विस्तृत विवरण",
    "Activity Plan Detail (CSV-style)",
    var_type="list",
    source="yearly_activities",
)

# A17: User Group (20)
_reg(
    "ug_available",
    "A",
    "उपभोक्ता समूह डाटा उपलब्ध",
    "User Group Available",
    var_type="boolean",
    source="user_group",
)
_reg(
    "ug_total_settlements",
    "A",
    "कुल बस्ती",
    "Total Settlements",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_buildings",
    "A",
    "बस्ती विवरण",
    "Settlement Details",
    var_type="list",
    source="user_group",
)

# Settlement / Building Breakdown
_reg(
    "ug_total_buildings",
    "A",
    "कुल भवन",
    "Total Buildings",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_total_building_area_m2",
    "A",
    "कुल भवन क्षेत्रफल (m²)",
    "Total Building Area (m²)",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_avg_building_size_m2",
    "A",
    "औसत भवन आकार (m²)",
    "Avg Building Size (m²)",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_small_buildings",
    "A",
    "साना भवन (<50 m²)",
    "Small Buildings (<50 m²)",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_medium_buildings",
    "A",
    "मध्यम भवन (50-150 m²)",
    "Medium Buildings (50-150 m²)",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_large_buildings",
    "A",
    "ठुला भवन (>150 m²)",
    "Large Buildings (>150 m²)",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_small_pct",
    "A",
    "साना भवन प्रतिशत",
    "Small Buildings %",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_medium_pct",
    "A",
    "मध्यम भवन प्रतिशत",
    "Medium Buildings %",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_large_pct",
    "A",
    "ठुला भवन प्रतिशत",
    "Large Buildings %",
    var_type="number",
    source="user_group",
)

# Land Cover / Area Summary
_reg(
    "ug_user_group_area_ha",
    "A",
    "उपभोक्ता समूह क्षेत्रफल (हे)",
    "User Group Area (ha)",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_forest_overlap_area_ha",
    "A",
    "वन ओभरल्याप क्षेत्रफल (हे)",
    "Forest Overlap Area (ha)",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_net_analysis_area_ha",
    "A",
    "शुद्ध विश्लेषण क्षेत्रफल (हे)",
    "Net Analysis Area (ha)",
    var_type="number",
    source="user_group",
)

# Biomass / Volume
_reg(
    "ug_total_biomass_mg",
    "A",
    "कुल जैविक पदार्थ (Mg)",
    "Total Biomass (Mg)",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_total_volume_m3",
    "A",
    "कुल आयतन (m³)",
    "Total Volume (m³)",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_avg_biomass_mg_per_ha",
    "A",
    "औसत जैविक पदार्थ (Mg/ha)",
    "Avg Biomass (Mg/ha)",
    var_type="number",
    source="user_group",
)
_reg(
    "ug_avg_volume_m3_per_ha",
    "A",
    "औसत आयतन (m³/ha)",
    "Avg Volume (m³/ha)",
    var_type="number",
    source="user_group",
)

# Land Cover Classes (list)
_reg(
    "ug_land_cover_classes",
    "A",
    "भू-आवरण वर्ग विवरण",
    "Land Cover Class Details",
    var_type="list",
    source="user_group",
)

# A17: Additional Committee (0 — reuses A13)

# A18: Compartments (6)
_reg(
    "compartment_message",
    "A",
    "कम्पार्टमेन्ट सन्देश",
    "Compartment Message",
    source="compartment",
)
_reg(
    "compartment_summary",
    "A",
    "कम्पार्टमेन्ट सारांश",
    "Compartment Summary",
    var_type="list",
    source="compartment",
)
_reg(
    "compartment_detail",
    "A",
    "कम्पार्टमेन्ट विवरण",
    "Compartment Detail",
    var_type="list",
    source="compartment",
)
_reg(
    "compartment_species_composition",
    "A",
    "कम्पार्टमेन्ट प्रजाति संरचना",
    "Compartment Species Composition",
    var_type="list",
    source="compartment",
)
_reg(
    "compartment_area_breakdown",
    "A",
    "कम्पार्टमेन्ट क्षेत्रफल विवरण",
    "Compartment Area Breakdown",
    var_type="list",
    source="compartment",
)
_reg(
    "compartment_dbh_distribution",
    "A",
    "कम्पार्टमेन्ट DBH वितरण",
    "Compartment DBH Distribution",
    var_type="list",
    source="compartment",
)

# ═══════════════════════════════════════════════════════
# Category B: Hybrid Variables (11)
# constraint: Categories A-F align with OP document sections 1-6
# ═══════════════════════════════════════════════════════


_reg(
    "altitude_min_m",
    "B",
    "न्यूनतम उचाई (मि)",
    "Min Altitude (m)",
    var_type="number",
    source="raster",
    resolver="resolve_hybrid",
)
_reg(
    "altitude_max_m",
    "B",
    "अधिकतम उचाई (मि)",
    "Max Altitude (m)",
    var_type="number",
    source="raster",
    resolver="resolve_hybrid",
)
_reg(
    "altitude_mean_m",
    "B",
    "औसत उचाई (मि)",
    "Mean Altitude (m)",
    var_type="number",
    source="raster",
    resolver="resolve_hybrid",
)
_reg(
    "dominant_slope",
    "B",
    "मुख्य भिरालो",
    "Dominant Slope",
    source="raster",
    resolver="resolve_hybrid",
)
_reg(
    "dominant_aspect",
    "B",
    "मुख्य दिशा",
    "Dominant Aspect",
    source="raster",
    resolver="resolve_hybrid",
)
_reg(
    "dominant_soil",
    "B",
    "मुख्य माटो",
    "Dominant Soil",
    source="raster",
    resolver="resolve_hybrid",
)
_reg(
    "crown_density_pct",
    "B",
    "वन मुकुट घनत्व (%)",
    "Crown Density (%)",
    var_type="number",
    source="raster",
    resolver="resolve_hybrid",
)
_reg(
    "trees_per_hectare",
    "B",
    "प्रतिहेक्टर रूख",
    "Trees per Hectare",
    var_type="number",
    source="inventory",
    resolver="resolve_hybrid",
)
_reg(
    "growing_stock_m3_per_ha",
    "B",
    "प्रतिहेक्टर वन मौज्दात",
    "Growing Stock per ha (m³)",
    var_type="number",
    source="field_inventory",
    resolver="resolve_hybrid",
)
_reg(
    "biomass_t_per_ha",
    "B",
    "प्रतिहेक्टर जैविक पदार्थ",
    "Biomass per ha (t)",
    var_type="number",
    source="field_inventory",
    resolver="resolve_hybrid",
)
_reg(
    "carbon_stock_tc_per_ha",
    "B",
    "प्रतिहेक्टर कार्बन मौज्दात",
    "Carbon Stock per ha (tC)",
    var_type="number",
    source="field_inventory",
    resolver="resolve_hybrid",
)

# ═══════════════════════════════════════════════════════
# Category C: User Input Variables (50)
# business: Category C — 50 user input variables for manual entry
# ═══════════════════════════════════════════════════════


_reg(
    "cf_registration_number",
    "C",
    "सामुदायिक वन दर्ता नं.",
    "CF Registration No",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "op_preparation_year",
    "C",
    "कार्ययोजना तयारी वर्ष",
    "OP Preparation Year",
    var_type="number",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "cf_code",
    "C",
    "सामुदायिक वन कोड",
    "CF Code",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "op_start_fy",
    "C",
    "कार्ययोजना सुरू आर्थिक वर्ष",
    "OP Start FY",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "op_end_fy",
    "C",
    "कार्ययोजना अन्तिम आर्थिक वर्ष",
    "OP End FY",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "physiography_zone",
    "C",
    "भू-आकृति क्षेत्र",
    "Physiography Zone",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "protected_area_status",
    "C",
    "संरक्षित क्षेत्र स्थिति",
    "Protected Area Status",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "technical_assistance_org",
    "C",
    "प्राविधिक सहयोग संस्था",
    "Technical Assistance Org",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "op_general_assembly_date",
    "C",
    "साधारण सभा मिति",
    "General Assembly Date",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "forest_type",
    "C",
    "वनको किसिम",
    "Forest Type",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "forest_abundance",
    "C",
    "वन बाहुल्यता",
    "Forest Abundance",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "forest_avg_age",
    "C",
    "औसत वन उमेर",
    "Forest Avg Age",
    var_type="number",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "main_non_timber_fp",
    "C",
    "मुख्य गैर-काठ वन पैदावार",
    "Main Non-Timber FP",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "avg_crown_density_pct",
    "C",
    "औसत छत्र घनत्व (%)",
    "Avg Crown Density (%)",
    var_type="number",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "ug_settlement",
    "C",
    "उपभोक्ता समूह बस्ती",
    "UG Settlement",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "prepared_by",
    "C",
    "तयार गर्ने",
    "Prepared By",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "reviewed_by",
    "C",
    "समीक्षा गर्ने",
    "Reviewed By",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "plan_year_start",
    "C",
    "योजना सुरु वर्ष",
    "Plan Start Year",
    var_type="number",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "plan_year_end",
    "C",
    "योजना अन्त वर्ष",
    "Plan End Year",
    var_type="number",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "user_group_name",
    "C",
    "उपभोक्ता समूहको नाम",
    "User Group Name",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "user_group_code",
    "C",
    "दर्ता नं.",
    "Registration No",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "cf_handover_date",
    "C",
    "हस्तान्तरण मिति",
    "Handover Date",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "plan_language",
    "C",
    "भाषा",
    "Language",
    auto_populate=False,
    resolver="resolve_user_input",
)

_reg(
    "kabuliyatnama_date",
    "C",
    "कबुलियतिनामा मिति",
    "Kabuliyatnama Date",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "kabuliyatnama_date_year",
    "C",
    "कबुलियतिनामा मिति (वर्ष)",
    "Kabuliyatnama Date Year",
    var_type="number",
    auto_populate=False,
    resolver="resolve_kabuliyatnama_detail",
)
_reg(
    "kabuliyatnama_date_month",
    "C",
    "कबुलियतिनामा मिति (महिना)",
    "Kabuliyatnama Date Month",
    var_type="number",
    auto_populate=False,
    resolver="resolve_kabuliyatnama_detail",
)
_reg(
    "kabuliyatnama_date_day",
    "C",
    "कबुलियतिनामा मिति (गते)",
    "Kabuliyatnama Date Day",
    var_type="number",
    auto_populate=False,
    resolver="resolve_kabuliyatnama_detail",
)
_reg(
    "kabuliyatnama_date_sentence",
    "C",
    "कबुलियतिनामा मिति (वाक्य)",
    "Kabuliyatnama Date Sentence",
    auto_populate=False,
    resolver="resolve_kabuliyatnama_detail",
)

# ── Metadata Form Fields (boundaries, locations, identifiers) ──
_reg(
    "sn_number",
    "C",
    "क्रम संख्या",
    "SN Number",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "province_guideline_year",
    "C",
    "प्रदेश कार्यविधि वर्ष",
    "Province Guideline Year",
    var_type="number",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "division",
    "C",
    "डिभिजन",
    "Division",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "sub_division",
    "C",
    "सब डिभिजन",
    "Sub Division",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "sub_division_chief",
    "C",
    "सब डिभिजन प्रमुख",
    "Sub Division Chief",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "forest_management_section_chief",
    "C",
    "वन व्यवस्थापन शाखा प्रमुख",
    "Forest Management Section Chief",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "division_forest_officer",
    "C",
    "डिभिजन प्रमुख",
    "Division Forest Officer",
    auto_populate=False,
    resolver="resolve_user_input",
)
# Rambhadevi SFM Renew template: signature blocks, history note and silviculture parameters
for _k, _ne, _en, _t in [
    ("cf_first_renewal_date", "पहिलो पटक कार्ययोजना परिमार्जन मिति", "First OP Renewal Date", "string"),
    ("cf_history_note", "वनको ऐतिहासिक पृष्ठभूमि (स्थानीय)", "Local History Note", "string"),
    ("silviculture_system", "वन सम्वर्द्धन प्रणाली", "Silviculture System", "string"),
    ("rotation_years", "बाली चक्र (वर्ष)", "Rotation (years)", "number"),
    ("regeneration_period_years", "पुनरुत्पादन अवधि (वर्ष)", "Regeneration Period (years)", "number"),
    ("mother_tree_spacing_m", "माउ रुखको औषत दुरी (मिटर)", "Mother-tree Average Spacing (m)", "number"),
    ("plan_duration_years", "कार्ययोजना अवधि (वर्ष)", "Plan Duration (years)", "number"),
]:
    _reg(_k, "C", _ne, _en, var_type=_t, auto_populate=False, resolver="resolve_user_input", precision=0 if _t == "number" and _k != "mother_tree_spacing_m" else 1)
_reg(
    "forest_municipality",
    "C",
    "स्थानीय तह",
    "Municipality",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "forest_ward",
    "C",
    "वार्ड",
    "Ward",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "forest_district",
    "C",
    "जिल्ला (वन)",
    "District (Forest)",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg("ug_province", "C", "प्रदेश (उपभोक्ता)", "Province (User Group)", auto_populate=False, resolver="resolve_user_input")
_reg("ug_municipality", "C", "स्थानीय तह (उपभोक्ता)", "Municipality (User Group)", auto_populate=False, resolver="resolve_user_input")
_reg("ug_ward", "C", "वार्ड (उपभोक्ता)", "Ward (User Group)", auto_populate=False, resolver="resolve_user_input")
_reg("ug_division", "C", "डिभिजन वन कार्यालय (उपभोक्ता)", "Division (User Group)", auto_populate=False, resolver="resolve_user_input")
_reg("ug_sub_division", "C", "इलाका वन कार्यालय (उपभोक्ता)", "Sub-division (User Group)", auto_populate=False, resolver="resolve_user_input")
_reg(
    "ug_district",
    "C",
    "जिल्ला (उपभोक्ता)",
    "District (User Group)",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "forest_municipality_type",
    "C",
    "स्थानीय तहको प्रकार (वन)",
    "Municipality Type (Forest)",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "ug_municipality_type",
    "C",
    "स्थानीय तहको प्रकार (उपभोक्ता)",
    "Municipality Type (User Group)",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "cf_sn_number",
    "C",
    "सामुदायिक वन क्रम संख्या",
    "CF SN Number",
    var_type="number",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "constitution_approved_year",
    "C",
    "विधान स्वीकृति मिति",
    "Constitution Approved Date",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "user_group_reg_no",
    "C",
    "समूह दर्ता नं.",
    "User Group Reg No",
    var_type="number",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "cf_name",
    "C",
    "सामुदायिक वनको नाम",
    "CF Name",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "cf_boundary_east",
    "C",
    "पूर्व सिमाना",
    "East Boundary",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "cf_boundary_west",
    "C",
    "पश्चिम सिमाना",
    "West Boundary",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "cf_boundary_north",
    "C",
    "उत्तर सिमाना",
    "North Boundary",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "cf_boundary_south",
    "C",
    "दक्षिण सिमाना",
    "South Boundary",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "ug_boundary_east",
    "C",
    "उपभोक्ता समूह पूर्व सिमाना",
    "UG East Boundary",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "ug_boundary_west",
    "C",
    "उपभोक्ता समूह पश्चिम सिमाना",
    "UG West Boundary",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "ug_boundary_north",
    "C",
    "उपभोक्ता समूह उत्तर सिमाना",
    "UG North Boundary",
    auto_populate=False,
    resolver="resolve_user_input",
)
_reg(
    "ug_boundary_south",
    "C",
    "उपभोक्ता समूह दक्षिण सिमाना",
    "UG South Boundary",
    auto_populate=False,
    resolver="resolve_user_input",
)


# ═══════════════════════════════════════════════════════
# Category D: Computed Variables (10)
# business: Category D — computed variables derived from multiple inputs
# ═══════════════════════════════════════════════════════


_reg(
    "total_plan_area_ha",
    "D",
    "योजना कुल क्षेत्रफल",
    "Total Plan Area (ha)",
    var_type="number",
    resolver="resolve_computed",
    compute_fn="compute_total_plan_area",
)
_reg(
    "forest_area_ha",
    "D",
    "वन क्षेत्रफल",
    "Forest Area (ha)",
    var_type="number",
    resolver="resolve_computed",
    compute_fn="compute_forest_area",
)
_reg(
    "non_forest_area_ha",
    "D",
    "गैर-वन क्षेत्रफल",
    "Non-forest Area (ha)",
    var_type="number",
    resolver="resolve_computed",
    compute_fn="compute_non_forest_area",
)
_reg(
    "forest_pct",
    "D",
    "वन प्रतिशत",
    "Forest Percentage",
    var_type="number",
    resolver="resolve_computed",
    compute_fn="compute_forest_pct",
)
_reg(
    "total_growing_stock_m3",
    "D",
    "कुल वन मौज्दात (m³)",
    "Total Growing Stock (m³)",
    var_type="number",
    resolver="resolve_computed",
    compute_fn="compute_total_growing_stock",
)
_reg(
    "total_carbon_stock_tc",
    "D",
    "कुल कार्बन मौज्दात (tC)",
    "Total Carbon Stock (tC)",
    var_type="number",
    resolver="resolve_computed",
    compute_fn="compute_total_carbon_stock",
)
_reg(
    "total_co2_tco2",
    "D",
    "कुल CO₂ (tCO₂)",
    "Total CO₂ (tCO₂)",
    var_type="number",
    resolver="resolve_computed",
    compute_fn="compute_total_co2",
)
_reg(
    "annual_increment_m3",
    "D",
    "वार्षिक वृद्धि (m³)",
    "Annual Increment (m³)",
    var_type="number",
    resolver="resolve_computed",
    compute_fn="compute_annual_increment",
)
_reg(
    "household_forest_area_per_hh",
    "D",
    "प्रति घरधुरी वन क्षेत्र",
    "Forest Area per HH (ha)",
    var_type="number",
    resolver="resolve_computed",
    compute_fn="compute_forest_per_hh",
)
_reg(
    "plan_years_range",
    "D",
    "योजना अवधि (साल)",
    "Plan Years Range",
    var_type="string",
    resolver="resolve_computed",
    compute_fn="compute_plan_years_range",
)
_reg(
    "cf_area_provided",
    "D",
    "प्रदान गरिएको क्षेत्रफल (हे)",
    "CF Area Provided (ha)",
    var_type="number",
    resolver="resolve_computed",
    compute_fn="compute_cf_area_provided",
)

# ═══════════════════════════════════════════════════════
# Category E: Section Content (5)
# ═══════════════════════════════════════════════════════
_reg(
    "section_6_previous_review",
    "E",
    "विगत समीक्षा (पाठ)",
    "Previous Review Text",
    source="template",
    auto_populate=True,
    resolver="resolve_section_content",
)
_reg(
    "section_8_production",
    "E",
    "उत्पादन (पाठ)",
    "Production Text",
    source="template",
    auto_populate=True,
    resolver="resolve_section_content",
)
_reg(
    "section_16_prohibited",
    "E",
    "निषेधित कार्य (पाठ)",
    "Prohibited Activities Text",
    source="template",
    auto_populate=True,
    resolver="resolve_section_content",
)
_reg(
    "section_17_penalties",
    "E",
    "वन अपराध (पाठ)",
    "Penalties Text",
    source="template",
    auto_populate=True,
    resolver="resolve_section_content",
)
_reg(
    "section_18_misc",
    "E",
    "विविध (पाठ)",
    "Miscellaneous Text",
    source="template",
    auto_populate=True,
    resolver="resolve_section_content",
)

# ═══════════════════════════════════════════════════════
# Section Generator Variables (20) — auto-generated Nepali narratives
# ═══════════════════════════════════════════════════════
_reg(
    "section:forest_summary",
    "A",
    "वन सारांश विवरण",
    "Forest Summary Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:slope_analysis",
    "A",
    "भिरालो विश्लेषण विवरण",
    "Slope Analysis Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:elevation_profile",
    "A",
    "उचाइ विवरण",
    "Elevation Profile Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:aspect_analysis",
    "A",
    "दिशा विश्लेषण विवरण",
    "Aspect Analysis Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:forest_health",
    "A",
    "वन स्वास्थ्य विवरण",
    "Forest Health Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:forest_type",
    "A",
    "वन प्रकार विवरण",
    "Forest Type Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:species_potential",
    "A",
    "सम्भावित प्रजाति विवरण",
    "Potential Species Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:actual_species",
    "A",
    "वास्तविक प्रजाति विवरण",
    "Actual Species Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:biodiversity",
    "A",
    "जैविक विविधता विवरण",
    "Biodiversity Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:canopy_structure",
    "A",
    "वन मुकुट विवरण",
    "Canopy Structure Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:biomass_carbon",
    "A",
    "जैविक पदार्थ तथा कार्बन विवरण",
    "Biomass & Carbon Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:climate_conditions",
    "A",
    "मौसम अवस्था विवरण",
    "Climate Conditions Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:land_cover",
    "A",
    "भू-आवरण विवरण",
    "Land Cover Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:forest_loss",
    "A",
    "वन क्षति विवरण",
    "Forest Loss Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:fire_loss",
    "A",
    "आगलागी क्षति विवरण",
    "Fire Loss Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:land_cover_1984",
    "A",
    "सन् १९८४ को भू-उपयोग विवरण",
    "Land Use 1984 Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ntfp",
    "A",
    "गैरकाष्ठ वन पैदावार विवरण",
    "NTFP Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:ntfp_inventory",
    "A",
    "गैरकाष्ठ वन पैदावार सर्वेक्षण नतिजा विवरण",
    "NTFP Inventory Results Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:forest_quality",
    "A",
    "वन गुणस्तर विवरण (नासा)",
    "Forest Quality Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:soil_analysis",
    "A",
    "माटो विश्लेषण विवरण",
    "Soil Analysis Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:location_context",
    "A",
    "स्थान तथा सन्दर्भ विवरण",
    "Location & Context Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:species_distribution",
    "A",
    "प्रजाति वितरण विवरण",
    "Species Distribution Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)
_reg(
    "section:accessible_forest",
    "A",
    "पहुँचयोग्य वन क्षेत्र विवरण",
    "Accessible Forest Section",
    var_type="string",
    source="section_generator",
    auto_populate=True,
)

# ═══════════════════════════════════════════════════════
# Category F: Template Variables (6)
# NOTE: Category F — template-level variables for document structure control
# ═══════════════════════════════════════════════════════


_reg(
    "document_version",
    "F",
    "दस्तावेज संस्करण",
    "Document Version",
    auto_populate=True,
    resolver="resolve_template",
)
_reg(
    "generated_date",
    "F",
    "उत्पादन मिति",
    "Generated Date",
    auto_populate=True,
    resolver="resolve_template",
)
_reg(
    "generated_by",
    "F",
    "उत्पादन गर्ने",
    "Generated By",
    auto_populate=True,
    resolver="resolve_template",
)
_reg(
    "document_language",
    "F",
    "दस्तावेज भाषा",
    "Document Language",
    auto_populate=True,
    resolver="resolve_template",
)
_reg(
    "export_format",
    "F",
    "निर्यात ढाँचा",
    "Export Format",
    auto_populate=True,
    resolver="resolve_template",
)
_reg(
    "plan_revision_number",
    "F",
    "संशोधन नं.",
    "Revision Number",
    var_type="number",
    auto_populate=True,
    resolver="resolve_template",
)

# ═══════════════════════════════════════════════════════
# Chart Variables (14) — special content_type="chart"
# ═══════════════════════════════════════════════════════
_reg(
    "chart:forest_type_pie",
    "A",
    "वन प्रकार पाई चार्ट",
    "Forest Type Pie Chart",
    var_type="dict",
    source="raster",
)
_reg(
    "chart:landcover_pie",
    "A",
    "भू-आवरण पाई चार्ट",
    "Landcover Pie Chart",
    var_type="dict",
    source="raster",
)
_reg(
    "chart:ug_land_cover_classes_chart",
    "A",
    "उपभोक्ता समूह भू-आवरण पाई चार्ट",
    "UG Land Cover Classes Pie Chart",
    var_type="dict",
    source="user_group",
)
_reg(
    "chart:slope_bar",
    "A",
    "भिरालो बार चार्ट",
    "Slope Bar Chart",
    var_type="dict",
    source="raster",
)
_reg(
    "chart:aspect_rose",
    "A",
    "दिशा रोज चार्ट",
    "Aspect Rose Chart",
    var_type="dict",
    source="raster",
)
_reg(
    "chart:soil_bar",
    "A",
    "माटो बार चार्ट",
    "Soil Bar Chart",
    var_type="dict",
    source="raster",
)
_reg(
    "chart:canopy_bar",
    "A",
    "वन मुकुट बार चार्ट",
    "Canopy Bar Chart",
    var_type="dict",
    source="raster",
)
_reg(
    "chart:forest_health_pie",
    "A",
    "वन स्वास्थ्य पाई चार्ट",
    "Forest Health Pie Chart",
    var_type="dict",
    source="raster",
)
_reg(
    "chart:species_composition_pie",
    "A",
    "प्रजाति संरचना पाई चार्ट",
    "Species Comp. Pie Chart",
    var_type="dict",
    source="inventory",
)
_reg(
    "chart:species_composition_pie_fi",
    "A",
    "प्रजाति संरचना पाई चार्ट (क्षेत्र सर्वेक्षण)",
    "Species Comp. Pie Chart (Field Inventory)",
    var_type="dict",
    source="field_inventory",
)
_reg(
    "chart:block_volume_bar",
    "A",
    "ब्लक आयतन बार चार्ट",
    "Block Volume Bar Chart",
    var_type="dict",
    source="inventory",
)
_reg(
    "chart:block_area_bar",
    "A",
    "ब्लक क्षेत्रफल बार चार्ट",
    "Block Area Bar Chart",
    var_type="dict",
    source="block",
)
_reg(
    "chart:hh_prosperity_pie",
    "A",
    "समृद्धि पाई चार्ट",
    "Prosperity Pie Chart",
    var_type="dict",
    source="household",
)
_reg(
    "chart:hh_caste_bar",
    "A",
    "जाति बार चार्ट",
    "Caste Bar Chart",
    var_type="dict",
    source="household",
)
_reg(
    "chart:budget_bar",
    "A",
    "बजेट बार चार्ट",
    "Budget Bar Chart",
    var_type="dict",
    source="activities",
)
_reg(
    "chart:ya_budget_year_bar",
    "A",
    "वर्ष अनुसार बजेट बार चार्ट",
    "Year-wise Budget Bar Chart",
    var_type="dict",
    source="yearly_activities",
)
_reg(
    "chart:ya_program_pie",
    "A",
    "कार्यक्रम अनुसार बजेट पाई चार्ट",
    "Program-wise Budget Pie Chart",
    var_type="dict",
    source="yearly_activities",
)
_reg(
    "chart:dbh_class_bar",
    "A",
    "ब्यास क्लास अनुसार प्रति हेक्टर मौज्दात (खाँवा र रूख)",
    "DBH Class Growing Stock Bar Chart (Pole & Tree)",
    var_type="dict",
    source="field_inventory",
)
_reg(
    "chart:dbh_class_count_bar",
    "A",
    "ब्यास क्लास अनुसार प्रति हेक्टर रूख संख्या (खाँवा र रूख)",
    "DBH Class Tree Count Bar Chart (Pole & Tree)",
    var_type="dict",
    source="field_inventory",
)

# ── Fixed pictures placed by {{asset:name}} (app/assets/op_images/<name>.png) ──
_reg("asset:cf_logo", "A", "सामुदायिक वन लोगो", "Community forestry logo", var_type="dict", source="assets")
_reg("asset:sample_plot_layout", "A", "नमुना प्लट लेआउट चित्र", "Nested sample-plot layout diagram", var_type="dict", source="assets")

# ── Plan extras (Rambhadevi-style plan; plan_extras.py) - derived, nothing typed ──
for _k, _ne, _en, _t in [
    ("uc_female_members", "उपभोक्ता समितिमा महिला सदस्य संख्या", "User committee - female members", "number"),
    ("uc_male_members", "उपभोक्ता समितिमा पुरुष सदस्य संख्या", "User committee - male members", "number"),
    ("hh_caste_prosperity_table", "जातजाति र सम्पन्नता स्तरीकरण", "Households by caste and prosperity (table)", "list"),
    ("ya_silviculture_schedule_table", "वन सम्वर्द्धनका कृयाकलापहरुको कार्यान्वयन तालिका", "Silviculture operations by year and unit (table)", "list"),
    ("ya_felling_by_year_table", "वार्षिक रूपमा उत्पादन हुने काठ दाउराको परिमाण", "Felling / collection yield by year (table)", "list"),
    ("fire_line_plan_table", "अग्निरेखा निर्माण तथा मर्मत योजना", "Fire-line plan by year (table)", "list"),
    ("fire_line_table", "अग्नी रेखाको विवरण", "Fire lines (table: each boundary, road and drawn line)", "list"),
    ("fire_line_count", "अग्नी रेखाको संख्या", "Fire lines - count", "number"),
    ("fire_line_total_km", "जम्मा अग्नी रेखा (कि.मि.)", "Fire lines - total length (km)", "number"),
    ("fire_line_total_ha", "जम्मा अग्नी रेखाको क्षेत्रफल (हे.)", "Fire lines - total area (ha)", "number"),
    ("fire_line_existing_km", "विद्यमान अग्नी रेखा - बाटो (कि.मि.)", "Existing fire lines - roads (km)", "number"),
    ("fire_line_existing_ha", "विद्यमान अग्नी रेखा - बाटोको क्षेत्रफल (हे.)", "Existing fire lines - roads (ha)", "number"),
    ("fire_line_new_km", "नयाँ निर्माण गर्नुपर्ने अग्नी रेखा (कि.मि.)", "Fire lines still to construct (km)", "number"),
    ("fire_line_new_ha", "नयाँ निर्माण गर्नुपर्ने अग्नी रेखाको क्षेत्रफल (हे.)", "Fire lines still to construct (ha)", "number"),
    ("river_bank_table", "खोला किनारको विवरण", "River banks (table: each bank, its river and units)", "list"),
    ("river_bank_count", "खोला किनारको संख्या", "River banks - count", "number"),
    ("river_bank_total_km", "जम्मा खोलाको लम्बाइ (कि.मि.)", "River banks - river length (km)", "number"),
    ("river_bank_total_ha", "जम्मा खोला किनारको क्षेत्रफल (हे.) - संरक्षण क्षेत्र", "River banks - total area (ha), a protection area", "number"),
    ("fire_line_river_bank_combined_ha", "अग्नी रेखा र खोला किनारको जम्मा क्षेत्रफल (हे.), ओभरल्याप एक पटक", "Fire lines and river banks together (ha), overlap counted once", "number"),
    ("fire_line_river_bank_overlap_ha", "अग्नी रेखा र खोला किनार मिलेको क्षेत्रफल (हे.)", "Area shared by fire lines and river banks (ha)", "number"),
    ("ya_annual_budget_table", "बार्षिक क्रियाकलाप तथा बजेट (हजारमा)", "Annual activities and budget (table, thousands)", "list"),
    ("sfm_regeneration_felling_unit", "पुनरुत्पादन कटान गरिने एकाइ", "Regeneration-felling unit", "string"),
    ("sfm_preparatory_felling_unit", "पुनरुत्पादन तयारी कटान गरिने एकाइ", "Preparatory-felling unit", "string"),
    ("sfm_annual_yield_timber_cft", "वार्षिक काठ उत्पादन (घ.फि.)", "Annual timber yield (cft)", "number"),
    ("sfm_annual_yield_firewood_chatta", "वार्षिक दाउरा उत्पादन (चट्टा)", "Annual firewood yield (chatta)", "number"),
    ("sm_felling_tree_list", "कटान (FT) रुखहरुको विवरण", "Felling trees list (stem mapping)", "list"),
    ("sm_mother_tree_list", "माउ (MT) रुखहरुको विवरण", "Mother trees list (stem mapping)", "list"),
    ("sm_protected_tree_list", "संरक्षित (PT) रुखहरुको विवरण", "Protected trees list (stem mapping)", "list"),
    ("sm_felling_annual_trees", "प्रत्येक बर्ष कटान गर्ने रुख संख्या", "Felling trees per year", "number"),
    ("sm_mother_trees_per_ha", "माउ रुख संख्या प्रति हेक्टर", "Mother trees per ha", "number"),
    ("sm_species_count", "कटान क्षेत्रमा प्रजाति संख्या", "Species count in the felling area", "number"),
    ("sm_stem_mapped_units", "रुख नक्शाङ्कन गरिएको एकाइ", "Stem-mapped unit(s)", "string"),
    ("aspect_dominant_names", "मोहडा (प्रमुख दिशाहरु)", "Dominant aspects (names)", "string"),
    ("slope_range_deg", "भिरालोपनाको दायरा (डिग्री)", "Slope range (degrees, class bands)", "string"),
    ("soil_texture_names", "माटोको किसिम", "Soil texture classes", "string"),
    ("erosion_status_word", "भू-क्षयको अवस्था", "Soil-loss status (severity class)", "string"),
    ("drainage_summary", "खोला/खोल्सीको विवरण", "Streams and rivers (summary)", "string"),
    ("nested_plot_radii_m", "नमुना प्लटका त्रिज्या (मि.)", "Nested sample-plot radii (m)", "string"),
    ("unit_count", "एकाइ (सब-कम्पार्टमेन्ट) संख्या", "Leaf unit count", "number"),
    ("unit_parent_count", "कम्पार्टमेन्ट संख्या", "Compartment (parent unit) count", "number"),
    ("demand_poles_count", "बल्लाबल्लीको वार्षिक माग (संख्या)", "Annual pole demand (count)", "number"),
    ("sm_top_species", "कटान क्षेत्रको प्रमुख प्रजाति", "Top species among the felling trees", "string"),
    ("sm_tree_total", "रुख नक्शाङ्कन गरिएका जम्मा रुख", "Mapped trees - total", "number"),
    ("sm_felling_tree_total", "कटान (FT) रुख संख्या", "Felling trees - total", "number"),
    ("sm_mother_tree_total", "माउ (MT) रुख संख्या", "Mother trees - total", "number"),
    ("sm_protected_tree_total", "संरक्षित (PT) रुख संख्या", "Protected trees - total", "number"),
    ("fi_main_species_names", "मुख्य प्रजातिहरु (नाम)", "Main species (names)", "string"),
    ("fi_other_species_names", "अन्य प्रजातिहरु (नाम)", "Other species (names)", "string"),
    ("ya_thinning_unit_count", "थिनिङ्ग तथा सुधार कटान गरिने एकाइ संख्या", "Units thinned (count)", "number"),
    ("ya_thinning_area_ha", "थिनिङ्ग तथा सुधार कटान क्षेत्रफल (हे.)", "Area thinned (ha)", "number"),
    ("fi_unit_per_ha_summary_table", "आवधिक खण्डमा प्रति हेक्टर वनको अवस्था", "Per-ha forest state by unit (table)", "list"),
    ("fi_forest_state_table", "वनको वर्तमान अवस्था", "Current forest state (table)", "list"),
    ("fieldbook_outer_table", "वन सिमाना सर्वेक्षण कोअर्डिनेट", "Boundary survey coordinates (UTM)", "list"),
    ("fieldbook_internal_table", "सब कम्पार्टमेन्ट विभाजक कोअर्डिनेट", "Unit divider coordinates (UTM)", "list"),
    ("plot_utm_coordinate_table", "स्याम्पल प्लटको कोअर्डिनेट", "Sample-plot coordinates (UTM)", "list"),
    ("hansen2000_dominant", "सन् २००० को वनको अवस्था (Hansen) - प्रमुख", "Forest cover 2000 (Hansen) - dominant class", "string"),
    ("hansen2000_percentages", "सन् २००० को वन आवरण (Hansen) - प्रतिशत", "Forest cover 2000 (Hansen) - percentages", "dict"),
]:
    _reg(_k, "A", _ne, _en, var_type=_t, source="plan_extras", precision=0 if _t == "number" else 2)

# ── Species x stage tables and charts (Rambhadevi-style plan; species_stage_tables.py) ──
for _k, _ne, _en in [
    ("fi_species_regen_per_ha_table", "प्रजाति अनुसार पुनरुत्पादनको अवस्था (प्रति हेक्टर)", "Regeneration per ha by species (forest)"),
    ("fi_species_pole_per_ha_table", "प्रजाति अनुसार पोलको प्रति हेक्टर मौज्दात", "Pole stock per ha by species (forest)"),
    ("fi_species_tree_per_ha_table", "प्रजाति अनुसार रुखको प्रति हेक्टर मौज्दात", "Tree stock per ha by species (forest)"),
    ("fi_unit_species_regen_per_ha_table", "{{unit}} र प्रजाति अनुसार पुनरुत्पादनको अवस्था", "Regeneration per ha by unit and species"),
    ("fi_unit_species_pole_per_ha_table", "{{unit}} र प्रजाति अनुसार पोलको मौज्दात", "Pole stock per ha by unit and species"),
    ("fi_unit_species_tree_per_ha_table", "{{unit}} र प्रजाति अनुसार रुखको मौज्दात", "Tree stock per ha by unit and species"),
]:
    _reg(_k, "A", "खण्ड".join(_ne.split("{{unit}}")), _en, var_type="list", source="field_inventory")
# ── Regulation species groups (species_regulation_tables.py): fi_reg_* = 21 named + Other (Terai/Hill), fi_regc_* =
#    classified species only (codes 1-21). Own tables (below / here), bar charts and a narration each. ──
for _k, _ne, _en in [
    ("fi_regc_species_regen_per_ha_table", "पुनरुत्पादनको अवस्था (प्रति हेक्टर)", "Regeneration per ha"),
    ("fi_regc_species_pole_per_ha_table", "पोलको प्रति हेक्टर मौज्दात", "Pole stock per ha"),
    ("fi_regc_species_tree_per_ha_table", "रुखको प्रति हेक्टर मौज्दात", "Tree stock per ha"),
    ("fi_regc_unit_species_regen_per_ha_table", "खण्ड अनुसार पुनरुत्पादनको अवस्था", "Regeneration per ha by unit"),
    ("fi_regc_unit_species_pole_per_ha_table", "खण्ड अनुसार पोलको मौज्दात", "Pole stock per ha by unit"),
    ("fi_regc_unit_species_tree_per_ha_table", "खण्ड अनुसार रुखको मौज्दात", "Tree stock per ha by unit"),
]:
    _reg(_k, "A", f"वर्गीकृत प्रजाति (२१ तोकिएका): {_ne}", f"Classified species (21 named): {_en}", var_type="list", source="field_inventory")
for _p, _ne_g, _en_g in [("fi_reg", "नियमावली प्रजाति वर्ग", "regulation species group"), ("fi_regc", "वर्गीकृत प्रजाति", "classified species")]:
    for _k, _ne, _en in [
        (f"chart:{_p}_species_pole_count_bar", "पोलको प्रति हेक्टर संख्या", "Pole count per ha"),
        (f"chart:{_p}_species_pole_volume_bar", "पोलको प्रति हेक्टर आयतन", "Pole volume per ha"),
        (f"chart:{_p}_species_tree_count_bar", "रुखको प्रति हेक्टर संख्या", "Tree count per ha"),
        (f"chart:{_p}_species_tree_volume_bar", "रुखको प्रति हेक्टर आयतन", "Tree volume per ha"),
    ]:
        _reg(_k, "A", f"{_ne_g} अनुसार {_ne}", f"{_en} by {_en_g} (bar chart)", var_type="dict", source="field_inventory")
    _reg(f"section:{_p}_species_narration", "A", f"{_ne_g} मौज्दात विवरण (स्वतः उत्पन्न)",
         f"Stock narration by {_en_g} (auto-generated)", var_type="string", source="section_generator", auto_populate=True)

# ── (all-categories tables) 21 designated species + Other (Terai/Hill) ──
for _k, _ne, _en in [
    ("fi_reg_species_regen_per_ha_table", "नियमावली प्रजाति वर्ग अनुसार पुनरुत्पादनको अवस्था (प्रति हेक्टर)", "Regeneration per ha by regulation species group (forest)"),
    ("fi_reg_species_pole_per_ha_table", "नियमावली प्रजाति वर्ग अनुसार पोलको प्रति हेक्टर मौज्दात", "Pole stock per ha by regulation species group (forest)"),
    ("fi_reg_species_tree_per_ha_table", "नियमावली प्रजाति वर्ग अनुसार रुखको प्रति हेक्टर मौज्दात", "Tree stock per ha by regulation species group (forest)"),
    ("fi_reg_unit_species_regen_per_ha_table", "{{unit}} र नियमावली प्रजाति वर्ग अनुसार पुनरुत्पादनको अवस्था", "Regeneration per ha by unit and regulation species group"),
    ("fi_reg_unit_species_pole_per_ha_table", "{{unit}} र नियमावली प्रजाति वर्ग अनुसार पोलको मौज्दात", "Pole stock per ha by unit and regulation species group"),
    ("fi_reg_unit_species_tree_per_ha_table", "{{unit}} र नियमावली प्रजाति वर्ग अनुसार रुखको मौज्दात", "Tree stock per ha by unit and regulation species group"),
]:
    _reg(_k, "A", "खण्ड".join(_ne.split("{{unit}}")), _en, var_type="list", source="field_inventory")
for _k, _ne, _en in [
    ("chart:fi_unit_regen_per_ha_bar", "खण्ड अनुसार बिरुवाको प्रति हेक्टर संख्या", "Seedlings per ha by unit (bar chart)"),
    ("chart:fi_unit_sapling_per_ha_bar", "खण्ड अनुसार लाथ्राको प्रति हेक्टर संख्या", "Saplings per ha by unit (bar chart)"),
    ("chart:fi_species_pole_count_bar", "प्रजाति अनुसार पोलको प्रति हेक्टर संख्या", "Pole count per ha by species (bar chart)"),
    ("chart:fi_species_pole_volume_bar", "प्रजाति अनुसार पोलको प्रति हेक्टर आयतन", "Pole volume per ha by species (bar chart)"),
    ("chart:fi_species_tree_count_bar", "प्रजाति अनुसार रुखको प्रति हेक्टर संख्या", "Tree count per ha by species (bar chart)"),
    ("chart:fi_species_tree_volume_bar", "प्रजाति अनुसार रुखको प्रति हेक्टर आयतन", "Tree volume per ha by species (bar chart)"),
]:
    _reg(_k, "A", _ne, _en, var_type="dict", source="field_inventory")

# ── Tree Mapping (sm_*) chart variables ──
_reg(
    "chart:sm_felling_dbh_pie",
    "A",
    "ब्यास वर्ग अनुसार कटानी रूख (पाई चार्ट)",
    "DBH-wise Felling Trees (Pie Chart)",
    var_type="dict",
    source="tree_mapping_analysis",
)
_reg(
    "chart:sm_felling_species_bar",
    "A",
    "प्रजाति अनुसार कटानी रूख (बार चार्ट)",
    "Species-wise Felling Trees (Bar Chart)",
    var_type="dict",
    source="tree_mapping_analysis",
)
_reg(
    "chart:sm_mother_felling_pie",
    "A",
    "माँउ रूख बनाम कटानी रूख (पाई चार्ट)",
    "Mother vs Felling Trees (Pie Chart)",
    var_type="dict",
    source="tree_mapping_analysis",
)
_reg(
    "chart:sm_mother_felling_species_bar",
    "A",
    "प्रजाति अनुसार माँउ बनाम कटानी (बार चार्ट)",
    "Mother vs Felling by Species (Bar Chart)",
    var_type="dict",
    source="tree_mapping_analysis",
)
_reg(
    "chart:sm_stand_type_bar",
    "A",
    "स्तर अनुसार वन प्रकार (बार चार्ट)",
    "Stand Type by Hierarchy (Bar Chart)",
    var_type="dict",
    source="tree_mapping_analysis",
)
_reg(
    "chart:sm_carbon_bar",
    "A",
    "स्तर अनुसार कार्बन (बार चार्ट)",
    "Carbon by Hierarchy (Bar Chart)",
    var_type="dict",
    source="tree_mapping_analysis",
)
_reg(
    "chart:sm_volume_bar",
    "A",
    "स्तर अनुसार आयतन (बार चार्ट)",
    "Volume by Hierarchy (Bar Chart)",
    var_type="dict",
    source="tree_mapping_analysis",
)
_reg(
    "chart:sm_mother_felling_hierarchy_bar",
    "A",
    "स्तर अनुसार माँउ बनाम कटानी (बार चार्ट)",
    "Mother vs Felling by Hierarchy (Bar Chart)",
    var_type="dict",
    source="tree_mapping_analysis",
)

# ═══════════════════════════════════════════════════════
# Fieldbook Variables
# ═══════════════════════════════════════════════════════
_FIELDBOOK_VARS = [
    ("fieldbook_total_points", "जम्मा फिल्डबुक बिन्दु", "Total Fieldbook Points"),
    ("fieldbook_vertex_count", "मुख्य बिन्दु संख्या", "Vertex Point Count"),
    (
        "fieldbook_interpolated_count",
        "अन्तरसम्मिलित बिन्दु संख्या",
        "Interpolated Point Count",
    ),
    ("fieldbook_perimeter_m", "वन परिधि (मिटर)", "Forest Perimeter (m)"),
    ("fieldbook_avg_elevation_m", "औसत उचाइ (मिटर)", "Average Elevation (m)"),
    ("fieldbook_min_elevation_m", "न्यूनतम उचाइ (मिटर)", "Minimum Elevation (m)"),
    ("fieldbook_max_elevation_m", "अधिकतम उचाइ (मिटर)", "Maximum Elevation (m)"),
    ("fieldbook_points", "फिल्डबुक बिन्दु विवरण तालिका", "Fieldbook Points Table"),
    (
        "fieldbook_block_summary",
        "ब्लक अनुसार फिल्डबुक बिन्दु विवरण",
        "Block-wise Fieldbook Points",
    ),
    ("fieldbook_narration", "फिल्डबुक विवरण (अनुच्छेद)", "Fieldbook Narration"),
]
for _fk, _fne, _fen in _FIELDBOOK_VARS:
    _vtype = (
        "list" if _fk in ("fieldbook_points", "fieldbook_block_summary") else "string"
    )
    _src = "section_generator" if _fk == "fieldbook_narration" else "fieldbook"
    _reg(_fk, "A", _fne, _fen, var_type=_vtype, source=_src)

# ═══════════════════════════════════════════════════════
# Map Variables
# ═══════════════════════════════════════════════════════
_MAP_TYPES = [
    ("map:boundary", "सिमाना नक्सा", "Boundary Map"),
    ("map:boundary_satellite", "उपग्रह तस्वीरमा सिमाना नक्सा", "Boundary on Satellite Imagery"),
    ("map:forest_type", "वन प्रकार नक्सा", "Forest Type Map"),
    ("map:forest_health", "वन स्वास्थ्य नक्सा", "Forest Health Map"),
    ("map:slope", "भिरालो नक्सा", "Slope Map"),
    ("map:biomass", "बायोमास नक्सा", "Biomass Map"),
    ("map:landcover", "भू-आवरण नक्सा", "Land Cover Map"),
    ("map:landcover_1984", "सन् १९८४ को भू-उपयोग नक्सा", "Land Use Map (1984)"),
    ("map:nasa_forest_2020", "वन गुणस्तर नक्सा (नासा २०२०)", "Forest Quality Map (NASA 2020)"),
    ("map:soil_texture", "माटो बनावट नक्सा", "Soil Texture Map"),
    ("map:dem", "उचाइ नक्सा", "Elevation Map"),
    ("map:aspect", "दिशा नक्सा", "Aspect Map"),
    ("map:canopy", "वन छाना नक्सा", "Canopy Cover Map"),
    ("map:sampling_plot", "नमुना प्लट नक्सा", "Sample Plot Map"),
    ("map:sampling_plot_topo", "स्थलाकृतिक नमुना प्लट नक्सा", "Sample Plot Map (Topo)"),
    (
        "map:sampling_plot_satellite",
        "उपग्रह नमुना प्लट नक्सा",
        "Sample Plot Map (Satellite)",
    ),
    ("map:fieldbook", "फिल्डबुक बाटो नक्सा", "Fieldbook Path Map"),
    ("map:usergroup", "उपयोगकर्ता समूह नक्सा", "User Group Map"),
    ("map:subarea", "उप-क्षेत्र नक्सा", "Sub-Area Map"),
    ("map:compartment", "कम्पार्टमेन्ट नक्सा", "Compartment Map"),
    ("map:sub_compartment", "उप-कम्पार्टमेन्ट नक्सा", "Sub-Compartment Map"),
    # map:activity_features dropped 2026-09-03 (P3) — it was registered but
    # missing from op_docx_builder's known_layers, so it always rendered
    # "[Unknown map type]". Drawn activity features come back as opsmap S15-S19.
]
# section + requires for the reference page — see thematic_map_spec.LEGACY_MAP_META
_LEGACY_MAP_SECTION = {
    "map:boundary": "base", "map:boundary_satellite": "base", "map:forest_type": "field", "map:forest_health": "field",
    "map:slope": "base", "map:biomass": "field", "map:landcover": "field",
    "map:landcover_1984": "base",
    "map:nasa_forest_2020": "field",
    "map:soil_texture": "base", "map:dem": "base", "map:aspect": "base",
    "map:canopy": "field", "map:sampling_plot": "field", "map:sampling_plot_topo": "field",
    "map:sampling_plot_satellite": "field", "map:fieldbook": "field",
    "map:usergroup": "field", "map:subarea": "zoning", "map:compartment": "zoning",
    "map:sub_compartment": "zoning",
}
for _mkey, _mne, _men in _MAP_TYPES:
    _reg(_mkey, "A", _mne, _men, var_type="dict", source="maps",
         section=_LEGACY_MAP_SECTION.get(_mkey, "base"), viz="basemap_overlay")
# backward compat alias
_reg(
    "map:boundary_map",
    "A",
    "सिमाना नक्सा",
    "Boundary Map",
    var_type="dict",
    source="maps",
)

# ═══════════════════════════════════════════════════════
# Thematic map variables (THEMATIC_MAP_VARIABLES_PLAN §3.4A / P1)
# Registered from the code-owned BUILTIN_THEMEMAP_SPECS so they appear in the
# variable catalog / picker. The renderer (thematic_overlay) is authoritative
# for behaviour; here we only surface key + label + section + viz.
# ═══════════════════════════════════════════════════════
try:
    from .thematic_map_spec import BUILTIN_THEMEMAP_SPECS as _TM_SPECS

    for _sk, _sp in _TM_SPECS.items():
        _reg(
            f"thememap:{_sk}",
            "A",
            _sp.label_ne or _sk,
            _sp.label_en or _sk,
            var_type="dict",
            source="thematic_map",
            section=_sp.section,
            viz=_sp.viz,
        )
except Exception:  # noqa: BLE001 -- registry must import even if the spec module is mid-refactor
    pass

# ═══════════════════════════════════════════════════════
# Table Variables (32) — inline table rendering
# ═══════════════════════════════════════════════════════
_TABLE_LABELS = [
    ("table_1", "भौगोलिक अवस्था", "Geographic Condition"),
    ("table_2", "वन क्षेत्रफल", "Forest Area"),
    ("table_3", "भू-उपयोग विवरण", "Land Use Details"),
    ("table_4", "माटोको प्रकार", "Soil Type"),
    ("table_5", "ब्लक विवरण", "Block Details"),
    ("table_6", "वन प्रकार", "Forest Type"),
    ("table_7", "रूख गणना", "Tree Count"),
    ("table_8", "आयतन विवरण", "Volume Details"),
    ("table_9", "नियत मात्रा", "Prescribed Quantity"),
    ("table_10", "मुख्य प्रजाति", "Main Species"),
    ("table_11", "घरधुरी विवरण", "Household Details"),
    ("table_12", "जनसंख्या विवरण", "Population Details"),
    ("demand_supply", "माग र आपूर्ति", "Demand and Supply"),
    ("table_14", "समिति विवरण", "Committee Details"),
    ("table_15", "वार्षिक क्रियाकलाप", "Annual Activities"),
    ("table_16", "बजेट विवरण", "Budget Details"),
    ("table_17", "वन पैदावार सङ्कलन", "Forest Product Collection"),
    ("table_18", "वन संवर्द्धन क्रियाकलाप", "Forest Enhancement Activities"),
    ("table_19", "संरक्षण योजना", "Conservation Plan"),
    ("table_20", "जैविक विविधता", "Biodiversity"),
    ("table_21", "आय-आर्जन योजना", "Income Generation Plan"),
    ("table_22", "सीप विकास", "Skill Development"),
    ("table_23", "पर्यापर्यटन", "Eco-tourism"),
    ("table_24", "अनुगमन योजना", "Monitoring Plan"),
    ("table_25", "मूल्याङ्कन मापदण्ड", "Evaluation Criteria"),
    ("table_26", "सामुदायिक विकास", "Community Development"),
    ("table_27", "वैकल्पिक उर्जा", "Alternative Energy"),
    ("table_28", "संस्थागत विकास", "Institutional Development"),
    ("table_29", "सहकार्य सम्झौता", "Collaboration Agreement"),
    ("table_30", "वित्तीय विश्लेषण", "Financial Analysis"),
    ("table_31", "जोखिम व्यवस्थापन", "Risk Management"),
    ("table_32", "अन्य तालिका", "Other Table"),
    ("table_33", "संरक्षण स्थिति विवरण", "IUCN Conservation Status"),
    ("table_34", "संरक्षित प्रजाति सूची", "Protected Species List"),
    ("table_35", "मिचाहा प्रजाति सूची", "Invasive Species List"),
    ("table_36", "वनस्पति प्रजाति सूची", "Vegetation Species List"),
    ("table_37", "जनावर प्रजाति सूची", "Animal Species List"),
    ("table_38", "गैरकाष्ठ वन पैदावार प्रजाति सूची", "NTFP Species List"),
    ("table_39", "गैरकाष्ठ वन पैदावार सर्वेक्षण नतिजा", "NTFP Inventory Results"),
]
for _tid, _ne, _en in _TABLE_LABELS:
    _reg(f"table:{_tid}", "A", _ne, _en, var_type="dict", source="op_table")

TABLE_ID_ALIAS = {
    "biodiversity": "table_20",
    "iucn_status": "table_33",
    "protected_species": "table_34",
    "invasive_species": "table_35",
    "vegetation_species": "table_36",
    "animal_species": "table_37",
    "ntfp": "table_38",
    "ntfp_inventory": "table_39",
}

_reg(
    "table:fieldinventory",
    "A",
    "क्षेत्र सर्वेक्षण मापन तथ्याङ्क",
    "Field Inventory Measurement Data",
    var_type="list",
    source="field_inventory",
)
for _alias, _tid in TABLE_ID_ALIAS.items():
    _entry = VARIABLE_REGISTRY.get(f"table:{_tid}")
    if _entry:
        _reg(
            f"table:{_alias}",
            "A",
            _entry.label_ne,
            _entry.label_en,
            var_type="dict",
            source="op_table",
        )

# ═══════════════════════════════════════════════════════════════════
# Category A: Tree Mapping Analysis (source="tree_mapping_analysis")
# ═══════════════════════════════════════════════════════════════════

# Scalar variables
_reg(
    "sm_available",
    "A",
    "रूख म्यापिङ विश्लेषण उपलब्ध",
    "Tree Mapping Analysis Available",
    var_type="boolean",
    source="tree_mapping_analysis",
)
_reg(
    "sm_total_blocks_analyzed",
    "A",
    "विश्लेषित ब्लक सङ्ख्या",
    "Blocks Analyzed",
    var_type="number",
    source="tree_mapping_analysis",
    precision=0,
)
_reg(
    "sm_total_trees_analyzed",
    "A",
    "विश्लेषित कुल रूख सङ्ख्या",
    "Total Trees Analyzed",
    var_type="number",
    source="tree_mapping_analysis",
    precision=0,
)
_reg(
    "sm_total_carbon_tc",
    "A",
    "कुल कार्बन मौज्दात (tC)",
    "Total Carbon Stock (tC)",
    var_type="number",
    source="tree_mapping_analysis",
    precision=3,
)
_reg(
    "sm_total_co2_tco2",
    "A",
    "कुल CO₂ समतुल्य (tCO₂)",
    "Total CO₂ Equivalent (tCO₂)",
    var_type="number",
    source="tree_mapping_analysis",
    precision=3,
)

# List variables (rendered as inline tables in DOCX)
_reg(
    "sm_hierarchy_summary",
    "A",
    "स्थानिक स्तर अनुसार रूख सारांश",
    "Spatial Hierarchy Tree Summary",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_species_by_hierarchy",
    "A",
    "स्थानिक स्तर अनुसार प्रजाति विश्लेषण",
    "Species Composition by Spatial Level",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_species_diversity",
    "A",
    "ब्लक अनुसार प्रजाति विविधता",
    "Species Diversity by Block",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_dbh_by_hierarchy",
    "A",
    "स्थानिक स्तर अनुसार DBH वर्ग विश्लेषण",
    "DBH Class by Spatial Level",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_dbh_species_by_hierarchy",
    "A",
    "स्थानिक स्तर अनुसार DBH-प्रजाति विश्लेषण",
    "DBH × Species by Spatial Level",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_stand_type_by_hierarchy",
    "A",
    "स्थानिक स्तर अनुसार स्ट्यान्ड प्रकार",
    "Stand Type by Spatial Level",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_carbon_by_hierarchy",
    "A",
    "स्थानिक स्तर अनुसार कार्बन मौज्दात",
    "Carbon Stock by Spatial Level",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_volume_by_hierarchy",
    "A",
    "स्थानिक स्तर अनुसार आयतन विश्लेषण",
    "Volume Analysis by Spatial Level",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_top_species_by_volume",
    "A",
    "आयतन अनुसार शीर्ष प्रजाति",
    "Top Species by Volume",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_mother_tree_by_hierarchy",
    "A",
    "स्थानिक स्तर अनुसार माँउ रूख विश्लेषण",
    "Mother Tree Analysis by Spatial Level",
    var_type="list",
    source="tree_mapping_analysis",
)

# Dict variables
_reg(
    "sm_forest_structure_status",
    "A",
    "वन संरचना अवस्था",
    "Forest Structure Status",
    var_type="dict",
    source="tree_mapping_analysis",
)
_reg(
    "sm_mother_tree_coverage",
    "A",
    "माँउ रूख ग्रिड कभरेज",
    "Mother Tree Grid Coverage",
    var_type="dict",
    source="tree_mapping_analysis",
)
_reg(
    "sm_mother_tree_by_species",
    "A",
    "प्रजाति अनुसार माँउ रूख",
    "Mother Tree by Species",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_felling_tree_by_species",
    "A",
    "प्रजाति अनुसार कटानी रूख",
    "Felling Tree by Species",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_mother_felling_summary",
    "A",
    "माँउ रूख बनाम कटानी रूख सारांश",
    "Mother Tree vs Felling Tree Summary",
    var_type="dict",
    source="tree_mapping_analysis",
)
_reg(
    "sm_hierarchy_remark_breakdown",
    "A",
    "स्तर अनुसार माँउ/कटानी विभाजन",
    "Hierarchy Remark Breakdown",
    var_type="dict",
    source="tree_mapping_analysis",
)
_reg(
    "sm_species_hier_remark",
    "A",
    "स्तर र प्रजाति अनुसार माँउ/कटानी",
    "Species by Hierarchy with Remark",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_dbh_hier_remark",
    "A",
    "स्तर र DBH अनुसार माँउ/कटानी",
    "DBH by Hierarchy with Remark",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_felling_dbh_analysis",
    "A",
    "कटानी रूख DBH विश्लेषण (≥३० सेमी)",
    "Felling Tree DBH Analysis (≥30cm)",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_felling_species_analysis",
    "A",
    "कटानी रूख प्रजाति विश्लेषण (≥३० सेमी)",
    "Felling Tree Species Analysis (≥30cm)",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_felling_totals",
    "A",
    "कटानी रूख कुल योग (≥३० सेमी)",
    "Felling Tree Totals (≥30cm)",
    var_type="dict",
    source="tree_mapping_analysis",
)

# --- Legend variables for chart symbolization ---
_reg(
    "sm_mf_hierarchy_legend",
    "A",
    "माँउ/कटानी स्तर चार्ट लिजेन्ड",
    "Mother/Felling Hierarchy Chart Legend",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_stand_type_legend",
    "A",
    "स्ट्यान्ड प्रकार चार्ट लिजेन्ड",
    "Stand Type Chart Legend",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_carbon_legend",
    "A",
    "कार्बन चार्ट लिजेन्ड",
    "Carbon Chart Legend",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_volume_legend",
    "A",
    "आयतन चार्ट लिजेन्ड",
    "Volume Chart Legend",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_mf_species_legend",
    "A",
    "माँउ/कटानी प्रजाति चार्ट लिजेन्ड",
    "Mother/Felling Species Chart Legend",
    var_type="list",
    source="tree_mapping_analysis",
)
_reg(
    "sm_felling_species_legend",
    "A",
    "कटानी प्रजाति चार्ट लिजेन्ड",
    "Felling Species Chart Legend",
    var_type="list",
    source="tree_mapping_analysis",
)


def get_variable(key: str) -> Optional[VariableDef]:
    """Look up a variable definition by its registry key."""
    return VARIABLE_REGISTRY.get(key)


def get_variables_by_category(category: str) -> List[VariableDef]:
    """Return all variable definitions matching a given category."""
    return [v for v in VARIABLE_REGISTRY.values() if v.category == category]


def get_variables_by_source(source: str) -> List[VariableDef]:
    """Return all variable definitions originating from a given data source."""
    return [v for v in VARIABLE_REGISTRY.values() if v.source == source]


def search_variables(query: str) -> List[VariableDef]:
    """Search variable definitions by key, Nepali label, or English label."""
    q = query.lower()
    return [
        v
        for v in VARIABLE_REGISTRY.values()
        if q in v.key.lower() or q in v.label_ne.lower() or q in v.label_en.lower()
    ]


def get_all_variables() -> List[VariableDef]:
    """Return all registered variable definitions."""
    return list(VARIABLE_REGISTRY.values())
