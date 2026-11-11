"""ThematicMapSpec — the declarative description of one thematic map variable.

THEMATIC_MAP_VARIABLES_PLAN §3.2. A spec says *what* to draw (layer, measure,
technique, palette, classification) and *what it needs* (``requires``); the
renderer (``thematic_overlay``) turns it into a PNG.

Two code-owned registries:
    BUILTIN_THEMEMAP_SPECS  — family "thememap" (analysis maps), P1 ships ~26
    BUILTIN_OPSMAP_SPECS    — family "opsmap" (plan maps), populated from P5c

``resolve_spec("thememap:unit__growing_stock")`` → the merged spec (builtin ▸
template-node override ▸ calc override — overrides land in P6).
``spec_hash(spec)`` → a short stable digest for the render cache key, salted
with ``THEMEMAP_RENDER_VERSION`` so a palette/frame change invalidates caches.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Bump when the renderer's output could change for an unchanged spec
# (palette values, frame, shaping backend). Part of the cache key.
THEMEMAP_RENDER_VERSION = 1


class ThematicMapSpec(BaseModel):
    """One thematic map variable. See §3.2 / Appendix C."""

    key: str  # e.g. "unit__growing_stock" (no family prefix)
    family: Literal["thememap", "opsmap"] = "thememap"
    section: str = ""  # S1..S20 (map families) — reference-page grouping
    layer: Literal[
        "unit",
        "subcompartment",
        "subarea",
        "samplingunit",
        "plot",
        "tree",
        "ntfp_plot",
        "feature",
        "grid",
        "zone",
        "settlement",
        "household",
        "flow",
        "vector",
        "forest",
    ] = "unit"
    measure: str = ""  # attribute / derived name
    source: Literal[
        "field_inventory",
        "tree_mapping",
        "inventory",
        "sub_area",
        "sampling",
        "raster_zonal",
        "soil_grid",
        "hazard_grid",
        "user_group",
        "change",
        "plan",
        "geometry",
        "sustainable_fm",
    ] = "field_inventory"
    viz: str = "choropleth"  # a §3.5.8 technique key
    value_kind: Literal["categorical", "numeric", "composition", "directional"] = (
        "numeric"
    )

    # colour + classification
    palette: str = "greens"  # a semantic_palettes key
    class_method: Literal["equal", "quantile", "fixed", "natural"] = "quantile"
    class_count: int = 5
    fixed_breaks: Optional[list[float]] = None

    # normalisation / derived
    normalize: Literal["none", "per_ha", "per_area", "index_100", "z_score"] = "none"
    reference_value: Optional[float] = None  # diverging midpoint

    # multi-variable
    components: Optional[list[str]] = None
    bivariate_measure: Optional[str] = None
    alpha_measure: Optional[str] = None
    glyph_axes: Optional[list[str]] = None

    # point / surface
    dot_value: Optional[float] = None
    interpolate: Optional[Literal["idw", "tin", "kriging"]] = None

    # opsmap time axis
    year: Optional[int] = None
    feature_kind: Optional[str] = None
    # layer == "tree" (stem-mapping points): which mapped trees to draw - all | felling | mother | protected
    tree_filter: Optional[Literal["all", "felling", "mother", "protected"]] = None

    # data prerequisites — drive the §3.9.1 "Copyable?" column
    requires: list[str] = Field(default_factory=list)
    missing_data_behavior: Literal["placeholder", "omit", "omit_section"] = (
        "placeholder"
    )
    enable_hint_ne: str = ""
    enable_hint_en: str = ""

    # rendering
    basemap: Literal["canvas_light", "hillshade", "topo", "osm", "imagery", "none"] = (
        "canvas_light"
    )
    scale_by: Literal["flannery", "linear"] = "flannery"
    layout: Literal["single", "grid"] = "single"
    show_value_labels: bool = False
    # print each unit's name and its SFM forest type ("Type-7") on the map, as small halo text
    show_unit_labels: bool = False
    # colours the user changed in the workspace's Analysis maps group, applied over the palette for THIS forest only:
    # category value -> '#rrggbb' (categorical maps; '_other' = the unmatched colour) or class index -> '#rrggbb'
    # (graduated maps). Part of the spec, so it is part of `spec_hash` and the cached PNG can never be stale.
    colour_overrides: Optional[dict[str, str]] = None
    # what the label says under the unit name: type ("Type-7 · 19-31 deg") | orientation | stock ("210 m3/ha")
    unit_label_kind: Literal["type", "orientation", "stock"] = "type"
    # the look, for maps drawn over imagery: None keeps the standard look
    basemap_alpha: Optional[float] = None
    fill_alpha: Optional[float] = None
    edge_color: Optional[str] = None
    edge_width: Optional[float] = None
    boundary_color: Optional[str] = None
    show_hydrology: bool = False
    combine_with: Optional[str] = None
    legend_title_ne: str = ""
    legend_title_en: str = ""

    # prose (authored in P3's content pass)
    label_ne: str = ""
    label_en: str = ""
    description_ne: str = ""
    description_en: str = ""

    @property
    def token(self) -> str:
        """The full ``{{...}}`` token, e.g. ``thememap:unit__growing_stock``."""
        return f"{self.family}:{self.key}"


def spec_hash(spec: ThematicMapSpec) -> str:
    """Short stable digest of a spec + render version, for the PNG cache key."""
    payload = spec.model_dump(
        exclude={"label_ne", "label_en", "description_ne", "description_en"}
    )
    payload["_v"] = THEMEMAP_RENDER_VERSION
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha1(blob.encode()).hexdigest()[
        :12
    ]  # noqa: S324 -- cache key, not security


# ── builtin registries ───────────────────────────────────────────────────
BUILTIN_THEMEMAP_SPECS: dict[str, ThematicMapSpec] = {}
BUILTIN_OPSMAP_SPECS: dict[str, ThematicMapSpec] = {}


def _t(key: str, **kw) -> None:
    spec = ThematicMapSpec(key=key, family="thememap", **kw)
    BUILTIN_THEMEMAP_SPECS[key] = spec


_FI = ["field_inventory"]

# ── S1 zoning_structure ──────────────────────────────────────────────────
_t(
    "unit__working_circle",
    section="S1",
    measure="working_circle",
    source="field_inventory",
    viz="choropleth",
    value_kind="categorical",
    palette="working_circle",
    requires=_FI,
    label_ne="कार्य वृत्त नक्सा",
    label_en="Working-circle Map",
)
_t(
    "unit__area",
    section="S1",
    measure="area_ha",
    source="geometry",
    viz="graduated",
    palette="growing_stock",
    requires=[],
    label_ne="एकाइ क्षेत्रफल नक्सा",
    label_en="Unit Area Map",
)
_t(
    "unit__area_share",
    section="S1",
    measure="area_share_pct",
    source="geometry",
    viz="choropleth",
    palette="greys",
    requires=[],
    label_ne="क्षेत्रफल हिस्सा नक्सा",
    label_en="Area Share Map",
)

# ── S2 forest_condition ─────────────────────────────────────────────────
_t(
    "unit__forest_condition",
    section="S2",
    measure="forest_condition",
    source="field_inventory",
    viz="choropleth",
    value_kind="categorical",
    palette="condition",
    requires=_FI,
    label_ne="वन अवस्था नक्सा",
    label_en="Forest Condition Map",
)
_t(
    "unit__condition_reason",
    section="S2",
    measure="condition_pair",
    source="field_inventory",
    viz="choropleth",
    value_kind="categorical",
    palette="condition_pair",
    requires=_FI,
    label_ne="वन र पुनरुत्पादन अवस्था (कारण सहित)",
    label_en="Forest and Regeneration Condition (with reasons)",
)
_t(
    "unit__pole_tree_share",
    section="S4",
    measure="tree_share_pct",
    source="field_inventory",
    viz="choropleth",
    palette="growing_stock",
    class_method="equal",
    requires=_FI,
    label_ne="खाँवा र रुखको हिस्सा (रुखको % मौज्दात)",
    label_en="Pole and Tree Map (tree share of the stock)",
)
_t(
    "unit__species_dominant",
    section="S5",
    measure="dominant_species",
    source="field_inventory",
    viz="choropleth",
    value_kind="categorical",
    palette="species_dynamic",  # one colour per species of THIS forest (the classes are the forest's own, not a fixed list)
    requires=_FI,
    label_ne="प्रमुख प्रजाति नक्सा",
    label_en="Dominant Species Map",
)
_t(
    "unit__species_composition__pie",
    section="S5",
    measure="species:share",
    source="field_inventory",
    viz="pie",
    value_kind="composition",
    palette="species_dynamic",
    requires=_FI,
    label_ne="एकाइ अनुसार प्रजाति संरचना (पाई)",
    label_en="Species composition per unit (pie)",
)
_t(
    "unit__regeneration_condition",
    section="S2",
    measure="regeneration_condition",
    source="field_inventory",
    viz="choropleth",
    value_kind="categorical",
    palette="condition",
    requires=_FI,
    label_ne="पुनरुत्पादन अवस्था नक्सा",
    label_en="Regeneration Condition Map",
)
_t(
    "unit__condition_x_stocking",
    section="S2",
    measure="forest_condition",
    source="field_inventory",
    viz="bivariate",
    palette="bivariate_gp",
    bivariate_measure="total_growing_stock_m3_per_ha",
    requires=_FI,
    label_ne="अवस्था × मौज्दात नक्सा",
    label_en="Condition × Stocking Map",
)

# ── S3 growing_stock ────────────────────────────────────────────────────
_t(
    "unit__growing_stock",
    section="S3",
    measure="total_growing_stock_m3_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="growing_stock",
    class_method="natural",
    requires=_FI,
    label_ne="वन मौज्दात नक्सा (प्रति हे.)",
    label_en="Growing Stock Map (per ha)",
)
_t(
    "unit__growing_stock__graduated",
    section="S3",
    measure="total_growing_stock_m3_per_ha",
    source="field_inventory",
    viz="graduated",
    palette="growing_stock",
    normalize="per_area",
    requires=_FI,
    label_ne="कुल वन मौज्दात नक्सा",
    label_en="Total Growing Stock Map",
)
_t(
    "unit__growing_stock__label",
    section="S3",
    measure="total_growing_stock_m3_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="growing_stock",
    class_method="natural",
    show_value_labels=True,
    requires=_FI,
    label_ne="वन मौज्दात नक्सा (मान सहित)",
    label_en="Growing Stock Map (labelled)",
)
_t(
    "unit__growing_stock__dasymetric",
    section="S3",
    measure="total_growing_stock_m3_per_ha",
    source="field_inventory",
    viz="dasymetric",
    palette="growing_stock",
    class_method="natural",
    requires=_FI,
    label_ne="वन मौज्दात नक्सा (सञ्चालनयोग्य क्षेत्र)",
    label_en="Growing Stock Map (operable area)",
)
_t(
    "unit__satellite_stock",
    section="S3",
    measure="satellite_volume_m3_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="growing_stock",
    requires=_FI,
    label_ne="उपग्रह मौज्दात नक्सा",
    label_en="Satellite Growing Stock Map",
)
_t(
    "unit__field_vs_satellite",
    section="S3",
    measure="_field_minus_satellite",
    source="field_inventory",
    viz="choropleth_div",
    palette="deviation",
    reference_value=0.0,
    requires=_FI,
    label_ne="क्षेत्र बनाम उपग्रह नक्सा",
    label_en="Field vs Satellite Map",
)
_t(
    "unit__basal_area",
    section="S3",
    measure="basal_area_m2_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="basal_area",
    requires=_FI,
    label_ne="आधार क्षेत्र नक्सा",
    label_en="Basal Area Map",
)
_t(
    "unit__stock_reliability",
    section="S3",
    measure="total_growing_stock_m3_per_ha",
    source="field_inventory",
    viz="alpha",
    palette="growing_stock",
    alpha_measure="total_sample_plots",
    requires=_FI,
    label_ne="मौज्दात विश्वसनीयता नक्सा",
    label_en="Stock Reliability Map",
)

# ── S4 stand_structure (choropleth only; glyphs land in P5b) ────────────
_t(
    "unit__stems_total",
    section="S4",
    measure="_stems_total",
    source="field_inventory",
    viz="choropleth",
    palette="stems",
    requires=_FI,
    label_ne="कुल रूख/खाँवा नक्सा",
    label_en="Total Stems Map",
)
_t(
    "unit__tree_per_ha",
    section="S4",
    measure="tree_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="stems",
    requires=_FI,
    label_ne="प्रति हे. रूख नक्सा",
    label_en="Trees per ha Map",
)
_t(
    "unit__pole_per_ha",
    section="S4",
    measure="pole_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="stems",
    requires=_FI,
    label_ne="प्रति हे. खाँवा नक्सा",
    label_en="Poles per ha Map",
)
_t(
    "unit__regeneration_stems",
    section="S4",
    measure="regeneration_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="stems",
    requires=_FI,
    label_ne="प्रति हे. पुनरुत्पादन नक्सा",
    label_en="Regeneration per ha Map",
)

# ── S6 yield_regulation ────────────────────────────────────────────────
_t(
    "unit__mai",
    section="S6",
    measure="mai_total_m3_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="increment",
    requires=_FI,
    label_ne="वार्षिक वृद्धि नक्सा (m³/हे./वर्ष)",
    label_en="MAI Map (m³/ha/yr)",
)
_t(
    "unit__mai_percent",
    section="S6",
    measure="mai_percent",
    source="field_inventory",
    viz="choropleth",
    palette="increment",
    requires=_FI,
    label_ne="MAI प्रतिशत नक्सा",
    label_en="MAI Percent Map",
)
_t(
    "unit__aah",
    section="S6",
    measure="aah_total_m3_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="increment",
    requires=_FI,
    label_ne="वार्षिक स्वीकार्य कटान नक्सा",
    label_en="AAH Map (m³/ha/yr)",
)
_t(
    "unit__aah__graduated",
    section="S6",
    measure="aah_total_m3_per_ha",
    source="field_inventory",
    viz="graduated",
    palette="increment",
    normalize="per_area",
    requires=_FI,
    label_ne="कुल AAH नक्सा",
    label_en="Total AAH Map",
)
_t(
    "unit__aah__label",
    section="S6",
    measure="aah_total_m3_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="increment",
    show_value_labels=True,
    requires=_FI,
    label_ne="AAH नक्सा (मान सहित)",
    label_en="AAH Map (labelled)",
)

# ── S7 carbon_biomass ─────────────────────────────────────────────────
_t(
    "unit__carbon",
    section="S7",
    measure="carbon_stock_tc_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="carbon",
    class_method="natural",
    requires=_FI,
    label_ne="कार्बन मौज्दात नक्सा",
    label_en="Carbon Stock Map",
)
_t(
    "unit__co2",
    section="S7",
    measure="co2_equivalent_tco2_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="carbon",
    requires=_FI,
    label_ne="CO₂ समतुल्य नक्सा",
    label_en="CO₂ Equivalent Map",
)
_t(
    "unit__biomass",
    section="S7",
    measure="total_biomass_t_per_ha",
    source="field_inventory",
    viz="choropleth",
    palette="carbon",
    requires=_FI,
    label_ne="जैविक पदार्थ नक्सा",
    label_en="Biomass Map",
)
_t(
    "unit__carbon__graduated",
    section="S7",
    measure="carbon_stock_tc_per_ha",
    source="field_inventory",
    viz="graduated",
    palette="carbon",
    normalize="per_area",
    requires=_FI,
    label_ne="कुल कार्बन नक्सा",
    label_en="Total Carbon Map",
)

# ═══════════════════════════════════════════════════════════════════════════
# P5b — centroid glyphs + small multiples
# ═══════════════════════════════════════════════════════════════════════════
_t(
    "unit__dbh_class_count__stackbar",
    section="S4",
    measure="dbh:count",
    source="field_inventory",
    viz="stackbar",
    value_kind="composition",
    palette="dbh_classes",
    requires=_FI,
    label_ne="ब्यास वर्ग रूख संख्या (एकाइ अनुसार)",
    label_en="DBH-class stems (per unit)",
)
_t(
    "unit__dbh_class_count__pie",
    section="S4",
    measure="dbh:count",
    source="field_inventory",
    viz="pie",
    value_kind="composition",
    palette="dbh_classes",
    requires=_FI,
    label_ne="ब्यास वर्ग रूख हिस्सा (पाई)",
    label_en="DBH-class share (pie)",
)
_t(
    "unit__dbh_class_count__sparkline",
    section="S4",
    measure="dbh:count",
    source="field_inventory",
    viz="sparkline",
    value_kind="composition",
    palette="dbh_classes",
    requires=_FI,
    label_ne="ब्यास वर्ग वक्र (रिभर्स-J जाँच)",
    label_en="DBH-class curve (reverse-J check)",
)
_t(
    "unit__dbh_gs_mai_aah__stackbar",
    section="S4",
    measure="dbh10:stock",
    source="field_inventory",
    viz="stackbar",
    value_kind="composition",
    palette="dbh_classes_10plus",
    requires=_FI,
    label_ne="ब्यास वर्ग (१० सेमी माथि) — वृद्धि भण्डार, MAI, AAH",
    label_en="Growing stock, MAI and AAH by DBH class (10 cm and above)",
)
_t(
    "unit__dbh_class_stock__stackbar",
    section="S4",
    measure="dbh:timber",
    source="field_inventory",
    viz="stackbar",
    value_kind="composition",
    palette="dbh_classes",
    requires=_FI,
    label_ne="ब्यास वर्ग काठ मौज्दात (एकाइ अनुसार)",
    label_en="DBH-class timber (per unit)",
)
_t(
    "unit__dbh_composition__waffle",
    section="S4",
    measure="dbh:count",
    source="field_inventory",
    viz="waffle",
    value_kind="composition",
    palette="dbh_classes",
    requires=_FI,
    label_ne="ब्यास वर्ग वफल",
    label_en="DBH-class waffle",
)
_t(
    "unit__regen_pole_tree__ternary",
    section="S4",
    components=["regeneration_per_ha", "pole_per_ha", "tree_per_ha"],
    source="field_inventory",
    viz="ternary",
    value_kind="composition",
    palette="dbh_classes_3",
    requires=_FI,
    label_ne="पुनरुत्पादन : खाँवा : रूख (त्रिकोण)",
    label_en="Regen : Pole : Tree (ternary)",
)
_t(
    "unit__timber_firewood__stackbar",
    section="S3",
    components=["_timber_total", "_firewood_total"],
    source="field_inventory",
    viz="stackbar",
    value_kind="composition",
    palette="dbh_classes_3",
    requires=_FI,
    label_ne="काठ बनाम दाउरा (एकाइ अनुसार)",
    label_en="Timber vs firewood (per unit)",
)
_t(
    "unit__agb_bgb__stackbar",
    section="S7",
    components=["agb_t_per_ha", "bgb_t_per_ha"],
    source="field_inventory",
    viz="stackbar",
    value_kind="composition",
    palette="carbon",
    requires=_FI,
    label_ne="माथिल्लो बनाम तल्लो जैविक पदार्थ",
    label_en="Above- vs below-ground biomass",
)
_t(
    "unit__health_fingerprint",
    section="S2",
    measure="_radar",
    source="field_inventory",
    viz="radar",
    value_kind="composition",
    palette="condition",
    requires=_FI,
    label_ne="एकाइ स्वास्थ्य फिंगरप्रिन्ट (रडार)",
    label_en="Unit health fingerprint (radar)",
)
_t(
    "unit__condition_with_dbh",
    section="S2",
    measure="forest_condition",
    source="field_inventory",
    viz="choropleth",
    value_kind="categorical",
    palette="condition",
    combine_with="thememap:unit__dbh_class_count__pie",
    requires=_FI,
    label_ne="अवस्था + ब्यास वर्ग पाई",
    label_en="Condition + DBH-class pie",
)
_t(
    "forest__dbh_by_unit",
    section="S12",
    measure="dbh:count",
    source="field_inventory",
    viz="smallmultiples",
    value_kind="composition",
    palette="dbh_classes",
    layout="grid",
    requires=_FI,
    label_ne="ब्यास वर्ग — एकाइ अनुसार सानो नक्साहरू",
    label_en="DBH-class — per-unit small multiples",
)

# ═══════════════════════════════════════════════════════════════════════════
# opsmap — operational-plan / prescription maps (family B, §3.4B) — P5c subset
# (per-block join only; drawn features + the year axis land in P7).
# ═══════════════════════════════════════════════════════════════════════════
_PA = ["proposed_activities"]


def _o(key: str, **kw) -> None:
    BUILTIN_OPSMAP_SPECS[key] = ThematicMapSpec(
        key=key, family="opsmap", source="plan", **kw
    )


# S13 — operations schedule
_o(
    "unit__felling_year",
    section="S13",
    measure="felling_year",
    viz="choropleth",
    value_kind="numeric",
    palette="increment",
    class_method="equal",
    requires=_PA,
    label_ne="कटान वर्ष नक्सा",
    label_en="Felling-year Map",
)
_o(
    "unit__felling_series",
    section="S13",
    measure="felling_series",
    viz="choropleth",
    value_kind="categorical",
    palette="species_qual",
    requires=_PA,
    label_ne="कटान श्रृंखला नक्सा",
    label_en="Felling-series Map",
)
_o(
    "unit__prescribed_harvest",
    section="S13",
    measure="prescribed_harvest",
    viz="graduated",
    palette="growing_stock",
    scale_by="flannery",
    requires=_PA,
    label_ne="नियत कटान परिमाण नक्सा",
    label_en="Prescribed Harvest Map",
)
_o(
    "unit__harvest_vs_aah",
    section="S13",
    measure="harvest_vs_aah",
    viz="choropleth_div",
    palette="deviation",
    reference_value=100.0,
    requires=_PA,
    label_ne="नियत कटान बनाम AAH नक्सा",
    label_en="Prescribed Cut vs AAH Map",
)
# S14 — management zonation (renders from geometry + working_circle even with no plan)
_o(
    "forest__working_circles",
    section="S14",
    measure="working_circle",
    viz="choropleth",
    value_kind="categorical",
    palette="working_circle",
    requires=[],
    label_ne="कार्य वृत्त विभाजन नक्सा",
    label_en="Working-circles Map",
)
# S20 — budget & effort
_o(
    "unit__budget_total",
    section="S20",
    measure="budget_total",
    viz="graduated",
    palette="oranges",
    scale_by="flannery",
    requires=_PA,
    label_ne="कुल बजेट नक्सा (एकाइ अनुसार)",
    label_en="Total Budget Map (per unit)",
)
_o(
    "unit__activity_count",
    section="S20",
    measure="activity_count",
    viz="choropleth",
    palette="increment",
    requires=_PA,
    label_ne="क्रियाकलाप संख्या नक्सा",
    label_en="Activity-count Map",
)

# ═══════════════════════════════════════════════════════════════════════════
# P7 — opsmap drawn-feature + 10-year time family
# ═══════════════════════════════════════════════════════════════════════════
_AF = ["activity_drawn_features"]

# S13 — operations schedule: year panels + composite + derived per-block
_o(
    "forest__annual_coupe_panel",
    section="S13",
    layout="grid",
    requires=_PA,
    label_ne="वार्षिक कटान खण्ड नक्सा",
    label_en="Annual Coupe Panel (per plan year)",
)
_o(
    "forest__ten_year_phasing",
    section="S13",
    layout="grid",
    requires=_PA,
    label_ne="दस वर्षे चरणबद्धता नक्सा",
    label_en="Ten-year Phasing Panel",
)
_o(
    "forest__year_one_operations",
    section="S13",
    layer="feature",
    viz="features",
    year=1,
    combine_with="coupe",
    requires=_AF,
    label_ne="वर्ष १ सञ्चालन नक्सा",
    label_en="Year-1 Operations Map",
)
_o(
    "unit__silviculture_year",
    section="S13",
    measure="felling_year",
    viz="choropleth",
    palette="increment",
    class_method="equal",
    requires=_PA,
    label_ne="मुख्य वन-पालन कार्य वर्ष नक्सा",
    label_en="Silviculture-year Map",
)
_o(
    "unit__operation_count",
    section="S13",
    measure="activity_count",
    viz="choropleth",
    palette="increment",
    requires=_PA,
    label_ne="सञ्चालन संख्या नक्सा",
    label_en="Operation-count Map",
)

# S15 — interventions & planting
_o(
    "feature__plantation_areas",
    section="S15",
    layer="feature",
    viz="features",
    feature_kind="plantation",
    requires=_AF,
    label_ne="रोपण क्षेत्र नक्सा",
    label_en="Plantation Areas Map",
)
_o(
    "feature__anr_areas",
    section="S15",
    layer="feature",
    viz="features",
    feature_kind="anr_area",
    requires=_AF,
    label_ne="प्राकृतिक पुनरुत्पादन क्षेत्र नक्सा",
    label_en="ANR Areas Map",
)
_o(
    "feature__nursery_sites",
    section="S15",
    layer="feature",
    viz="features",
    feature_kind="nursery",
    requires=_AF,
    label_ne="नर्सरी स्थल नक्सा",
    label_en="Nursery Sites Map",
)
_o(
    "feature__seed_stands",
    section="S15",
    layer="feature",
    viz="features",
    feature_kind="seed_stand",
    requires=_AF,
    label_ne="बीउ रूख नक्सा",
    label_en="Seed Stands Map",
)

# S16 — infrastructure
_o(
    "feature__roads_trails",
    section="S16",
    layer="feature",
    viz="features",
    requires=_AF,
    label_ne="प्रस्तावित बाटो तथा गोरेटो नक्सा",
    label_en="Proposed Roads & Trails Map",
)
_o(
    "feature__depots",
    section="S16",
    layer="feature",
    viz="features",
    feature_kind="depot",
    requires=_AF,
    label_ne="काठ डिपो नक्सा",
    label_en="Timber Depots Map",
)
_o(
    "feature__structures_all",
    section="S16",
    layer="feature",
    viz="featurecat",
    requires=_AF,
    label_ne="सम्पूर्ण पूर्वाधार नक्सा",
    label_en="All Infrastructure Map (by type)",
)

# S17 — protection & conservation
_o(
    "feature__fire_lines",
    section="S17",
    layer="feature",
    viz="features",
    feature_kind="fire_line",
    requires=["fire_line_features"],
    label_ne="आगो नियन्त्रण रेखा नक्सा",
    label_en="Fire Lines Map",
)
_o(
    "feature__river_banks",
    section="S17",
    layer="feature",
    viz="features",
    feature_kind="river_bank",
    requires=["river_bank_features"],
    label_ne="खोला किनार (संरक्षण क्षेत्र) नक्सा",
    label_en="River Banks Map",
)
_o(
    "feature__patrol_routes",
    section="S17",
    layer="feature",
    viz="features",
    feature_kind="patrol_route",
    requires=_AF,
    label_ne="गस्ती मार्ग नक्सा",
    label_en="Patrol Routes Map",
)
_o(
    "feature__biodiversity_blocks",
    section="S17",
    layer="feature",
    viz="features",
    feature_kind="biodiversity_block",
    requires=_AF,
    label_ne="जैविक विविधता क्षेत्र नक्सा",
    label_en="Biodiversity Blocks Map",
)
_o(
    "unit__protection_priority",
    section="S17",
    measure="harvest_vs_aah",
    viz="choropleth_div",
    palette="deviation",
    reference_value=100.0,
    requires=_PA,
    label_ne="संरक्षण प्राथमिकता नक्सा",
    label_en="Protection-priority Map",
)

# S18 — livelihoods & community
_o(
    "feature__ntfp_zones",
    section="S18",
    layer="feature",
    viz="features",
    feature_kind="ntfp_zone",
    requires=_AF,
    label_ne="गैरकाष्ठ वन पैदावार क्षेत्र नक्सा",
    label_en="NTFP Zones Map",
)
_o(
    "feature__propoor_plots",
    section="S18",
    layer="feature",
    viz="features",
    feature_kind="propoor_plot",
    requires=_AF,
    label_ne="विपन्न वर्ग भूखण्ड नक्सा",
    label_en="Pro-poor Plots Map",
)
_o(
    "feature__ecotourism",
    section="S18",
    layer="feature",
    viz="features",
    feature_kind="ecotourism_site",
    requires=_AF,
    label_ne="पर्यापर्यटन स्थल नक्सा",
    label_en="Ecotourism Sites Map",
)

# S19 — monitoring & governance
_o(
    "feature__permanent_plots",
    section="S19",
    layer="feature",
    viz="features",
    feature_kind="permanent_sample_plot",
    requires=_AF,
    label_ne="स्थायी नमूना प्लट नक्सा",
    label_en="Permanent Sample Plots Map",
)
_o(
    "feature__monitoring_points",
    section="S19",
    layer="feature",
    viz="features",
    feature_kind="monitoring_point",
    requires=_AF,
    label_ne="अनुगमन बिन्दु नक्सा",
    label_en="Monitoring Points Map",
)
_o(
    "forest__activities_missing_map",
    section="S19",
    viz="qaflag",
    value_kind="categorical",
    palette="deviation",
    requires=_PA,
    label_ne="नक्सा नभएका क्रियाकलाप (QA) नक्सा",
    label_en="Activities Missing a Map (QA)",
)

# S20 — budget, effort, phasing
_o(
    "unit__budget_by_year",
    section="S20",
    layout="grid",
    requires=_PA,
    label_ne="वार्षिक बजेट खण्ड नक्सा",
    label_en="Budget-by-year Panel",
)
_o(
    "unit__persondays",
    section="S20",
    measure="prescribed_harvest",
    viz="graduated",
    palette="oranges",
    scale_by="flannery",
    requires=_PA,
    label_ne="श्रम दिन नक्सा",
    label_en="Person-days Map",
)
_o(
    "unit__actual_vs_planned",
    section="S20",
    measure="harvest_vs_aah",
    viz="choropleth_div",
    palette="deviation",
    reference_value=100.0,
    requires=_PA,
    label_ne="वास्तविक बनाम योजना प्रगति नक्सा",
    label_en="Actual vs Planned Map",
)

# ═══════════════════════════════════════════════════════════════════════════
# P6 — point / density / surface techniques (thememap)
# ═══════════════════════════════════════════════════════════════════════════
_t(
    "plot__location",
    section="S8",
    layer="plot",
    measure="block_name",
    source="field_inventory",
    viz="dotcat",
    value_kind="categorical",
    palette="species_qual",
    requires=_FI,
    label_ne="नमूना प्लट स्थान नक्सा",
    label_en="Sample-plot Location Map",
)
_t(
    "plot__zone",
    section="S8",
    layer="plot",
    measure="zone_type",
    source="field_inventory",
    viz="dotcat",
    value_kind="categorical",
    palette="working_circle",
    requires=_FI,
    label_ne="नमूना प्लट क्षेत्र (उत्पादन/संरक्षित)",
    label_en="Sample-plot Zone Map",
)
_t(
    "grid__plot_density",
    section="S8",
    layer="grid",
    source="field_inventory",
    viz="hexbin",
    palette="density",
    requires=_FI,
    label_ne="नमूना प्लट घनत्व (हेक्सबिन)",
    label_en="Sample-plot Density (hexbin)",
)
_t(
    "forest__plot_kde",
    section="S8",
    layer="forest",
    source="field_inventory",
    viz="heatmap",
    palette="density",
    requires=_FI,
    label_ne="नमूना प्लट घनत्व सतह (KDE)",
    label_en="Sample-plot Density Surface (KDE)",
)
_t(
    "forest__growing_stock_surface",
    section="S3",
    layer="forest",
    source="field_inventory",
    viz="isopleth",
    interpolate="idw",
    palette="growing_stock",
    requires=_FI,
    label_ne="वन मौज्दात सतह (IDW)",
    label_en="Growing-stock Surface (IDW)",
)
_t(
    "forest__carbon_surface",
    section="S7",
    layer="forest",
    source="field_inventory",
    viz="isopleth",
    interpolate="idw",
    palette="carbon",
    requires=_FI,
    label_ne="कार्बन सतह (IDW)",
    label_en="Carbon Surface (IDW)",
)
_t(
    "unit__stems_dotdensity",
    section="S4",
    measure="_stems_total",
    source="field_inventory",
    viz="dotdensity",
    palette="stems",
    requires=_FI,
    label_ne="रूख घनत्व (थोप्ला)",
    label_en="Stem Density (dot density)",
)

# Stem-mapping points (Rambhadevi-style annex maps 1(च), 1(छ), 1(ज)): every mapped tree of the stem-mapped
# unit, only the felling (FT) trees, only the mother (MT) trees. One dot per tree from inventory_trees.
for _key, _filter, _ne, _en in [
    ("unit__stems_all", "all", "रुख नक्शाङ्कन — सबै रुखहरू", "Stem Map - all mapped trees"),
    ("unit__stems_felling", "felling", "रुख नक्शाङ्कन — कटान (FT) रुखहरू", "Stem Map - felling trees"),
    ("unit__stems_mother", "mother", "रुख नक्शाङ्कन — माउ (MT) रुखहरू", "Stem Map - mother trees"),
]:
    _t(
        _key,
        section="S4",
        layer="tree",
        measure="remark_group",
        source="tree_mapping",
        viz="dotcat",
        value_kind="categorical",
        palette="species_qual",
        tree_filter=_filter,
        requires=["tree_mapping"],
        label_ne=_ne,
        label_en=_en,
    )

# NTFP sample plots (owner 2026-10-22): the plots the NTFP survey laid out, coloured by how far their findings are. A user with an NTFP inventory
# prints this beside the NTFP plan; the workspace's "NTFP sample plots" layer is its placeholder.
_t(
    "unit__ntfp_plots",
    section="S4",
    layer="ntfp_plot",
    measure="status_group",
    source="sampling",
    viz="dotcat",
    value_kind="categorical",
    palette="species_qual",
    requires=["ntfp_design"],
    label_ne="गैरकाष्ठ वन पैदावार नमूना प्लट नक्सा",
    label_en="NTFP Sample Plot Map",
    enable_hint_ne="गैरकाष्ठ वन पैदावार पेजमा नमूना प्लट बनाउनुहोस्।",
    enable_hint_en="Lay out the sample plots on the NTFP inventory page.",
)

# Drainage / river network — real line geometry from river.river84 (S9).
_t(
    "forest__drainage_vectors",
    section="S9",
    layer="vector",
    source="geometry",
    viz="hydrolines",
    requires=["hydro"],
    label_ne="जल निकास (नदी/खोला) नक्सा",
    label_en="Drainage / River-network Map",
)
_t(
    "unit__forest_cover_change",
    section="S10",
    measure="cover_change",
    source="change",
    viz="change",
    palette="gain_loss",
    requires=["two_inventory_cycles"],
    label_ne="वन आवरण परिवर्तन नक्सा",
    label_en="Forest-cover Change Map",
)
_t(
    "flow__settlement_to_unit",
    section="S11",
    layer="flow",
    source="user_group",
    viz="flow",
    requires=["demand_model"],
    label_ne="बस्तीबाट आपूर्ति एकाइसम्म प्रवाह नक्सा",
    label_en="Settlement-to-unit Flow Map",
)

# ═══════════════════════════════════════════════════════════════════════════
# P6z — S9 physiography: per-unit zonal statistics over the rasters.* tables
# (source="raster_zonal" → thematic_overlay routes to raster_zonal.per_unit_zonal)
# ═══════════════════════════════════════════════════════════════════════════
_RZ = ["raster_zonal"]
# mirrors soil_erosion_config.DEFAULT_PARAMS.severity_breaks (SSOT there);
# only the fixture / reference-page render uses this — a real forest classifies
# with the resolved per-forest params.
_SOIL_LOSS_DEFAULT_BREAKS = [5.0, 10.0, 20.0, 40.0, 80.0]
_t(
    "zone__elevation_mean",
    section="S9",
    layer="zone",
    measure="elevation_mean",
    source="raster_zonal",
    viz="choropleth",
    palette="greys",
    class_method="equal",
    basemap="imagery",
    requires=_RZ,
    label_ne="औसत उचाइ नक्सा",
    label_en="Mean Elevation Map",
)
_t(
    "zone__elevation_range",
    section="S9",
    layer="zone",
    measure="elevation_range",
    source="raster_zonal",
    viz="choropleth",
    palette="greys",
    basemap="imagery",
    requires=_RZ,
    label_ne="उचाइ फैलावट नक्सा",
    label_en="Elevation Range Map",
)
_t(
    "zone__slope_mean",
    section="S9",
    layer="zone",
    measure="slope_mean",
    source="raster_zonal",
    viz="choropleth",
    palette="oranges",
    class_method="equal",
    basemap="imagery",
    requires=_RZ,
    label_ne="औसत भिरालोपन नक्सा",
    label_en="Mean Slope Map",
)
_t(
    "zone__slope_dominant",
    section="S9",
    layer="zone",
    measure="slope_dominant",
    source="raster_zonal",
    viz="choropleth",
    value_kind="categorical",
    palette="slope_class",
    basemap="imagery",
    requires=_RZ,
    label_ne="प्रमुख भिरालो वर्ग नक्सा",
    label_en="Dominant Slope Class Map",
)
_t(
    "zone__slope_class__stackbar",
    section="S9",
    layer="zone",
    measure="slope_classes",
    source="raster_zonal",
    viz="stackbar",
    value_kind="composition",
    components=["gentle", "moderate", "steep", "very_steep"],
    palette="slope_class",
    basemap="hillshade",
    requires=_RZ,
    label_ne="भिरालो वर्ग हिस्सा नक्सा",
    label_en="Slope-class Share Map",
)
_t(
    "zone__aspect_dominant",
    section="S9",
    layer="zone",
    measure="aspect_dominant",
    source="raster_zonal",
    viz="choropleth",
    value_kind="categorical",
    palette="aspect",
    basemap="imagery",
    requires=_RZ,
    label_ne="प्रमुख मोहडा नक्सा",
    label_en="Dominant Aspect Map",
)
_t(
    "zone__aspect__rose",
    section="S9",
    layer="zone",
    measure="aspect_bins",
    source="raster_zonal",
    viz="rose",
    value_kind="composition",
    palette="aspect",
    basemap="hillshade",
    requires=_RZ,
    label_ne="मोहडा वितरण नक्सा (रोज)",
    label_en="Aspect Distribution Map (rose)",
)
_t(
    "zone__canopy_mean",
    section="S9",
    layer="zone",
    measure="canopy_mean",
    source="raster_zonal",
    viz="choropleth",
    palette="growing_stock",
    class_method="equal",
    requires=_RZ,
    label_ne="औसत रूख उचाइ नक्सा",
    label_en="Mean Canopy Height Map",
)
_t(
    "zone__biomass_raster_mean",
    section="S9",
    layer="zone",
    measure="biomass_mean",
    source="raster_zonal",
    viz="choropleth",
    palette="carbon",
    class_method="equal",
    requires=_RZ,
    label_ne="रास्टर जैविक भार नक्सा (AGB)",
    label_en="Raster AGB Mean Map",
)
_t(
    "zone__landcover_dominant",
    section="S9",
    layer="zone",
    measure="landcover_dominant",
    source="raster_zonal",
    viz="choropleth",
    value_kind="categorical",
    palette="species_qual",
    requires=_RZ,
    label_ne="प्रमुख भू-आवरण नक्सा",
    label_en="Dominant Land-cover Map",
)
_t(
    "zone__landcover__pie",
    section="S9",
    layer="zone",
    measure="landcover_classes",
    source="raster_zonal",
    viz="pie",
    value_kind="composition",
    palette="species_qual",
    requires=_RZ,
    label_ne="भू-आवरण हिस्सा नक्सा",
    label_en="Land-cover Share Map",
)
_t(
    "zone__forest_type_dominant",
    section="S9",
    layer="zone",
    measure="forest_type_dominant",
    source="raster_zonal",
    viz="choropleth",
    value_kind="categorical",
    palette="forest_type",
    requires=_RZ,
    label_ne="प्रमुख वन प्रकार नक्सा",
    label_en="Dominant Forest-type Map",
)
_t(
    "vector__slope_aspect",
    section="S9",
    layer="vector",
    measure="aspect_vector",
    source="raster_zonal",
    viz="vector",
    palette="aspect",
    basemap="hillshade",
    requires=_RZ,
    label_ne="मोहडा दिशा तीर नक्सा",
    label_en="Aspect-direction Vector Map",
)
_t(
    "zone__accessibility",
    section="S9",
    layer="zone",
    measure="accessibility",
    source="raster_zonal",
    viz="choropleth",
    palette="access",
    class_method="quantile",
    requires=["roads"],
    label_ne="पहुँच (सडक/गोरेटो दूरी) नक्सा",
    label_en="Accessibility Map",
)
_t(
    "zone__forest_health",
    section="S9",
    layer="zone",
    measure="forest_health_dominant",
    source="raster_zonal",
    viz="choropleth",
    value_kind="categorical",
    palette="forest_health_class",
    basemap="imagery",
    requires=_RZ,
    label_ne="वन स्वास्थ्य (उपग्रह) नक्सा",
    label_en="Forest Health (satellite) Map",
)
_t(
    "zone__forest_health__pie",
    section="S9",
    layer="zone",
    measure="forest_health_classes",
    source="raster_zonal",
    viz="pie",
    value_kind="composition",
    palette="forest_health_class",
    requires=_RZ,
    label_ne="वन स्वास्थ्य हिस्सा नक्सा",
    label_en="Forest Health Share Map",
)
_t(
    "zone__nasa_quality_dominant",
    section="S9",
    layer="zone",
    measure="nasa_quality_dominant",
    source="raster_zonal",
    viz="choropleth",
    value_kind="categorical",
    palette="nasa_quality",
    basemap="imagery",
    requires=_RZ,
    label_ne="प्राथमिक/दोस्रो वन गुण नक्सा",
    label_en="Primary / Secondary Forest Map",
)
_t(
    "zone__nasa_quality__pie",
    section="S9",
    layer="zone",
    measure="nasa_quality_classes",
    source="raster_zonal",
    viz="pie",
    value_kind="composition",
    palette="nasa_quality",
    requires=_RZ,
    label_ne="वन गुण हिस्सा नक्सा",
    label_en="Forest Quality Share Map",
)

# ── RUSLE soil-loss (S9) — a computed continuous raster, not a per-unit fill.
# source="soil_grid" → thematic_overlay._render_soil_grid; viz="raster_surface".
# fixed_breaks here is only the fixture / reference-page default — a real
# forest's map classifies with the *resolved* params.severity_breaks
# (RUSLE_SOIL_LOSS_IMPLEMENTATION_PLAN.md §0.1 / §2 P2).
_t(
    "soil__annual_loss",
    section="S9",
    layer="grid",
    measure="soil_loss",
    source="soil_grid",
    viz="raster_surface",
    value_kind="numeric",
    palette="reds",  # dedicated "soil_loss" ramp deferred (needs the FE mirror)
    class_method="fixed",
    fixed_breaks=_SOIL_LOSS_DEFAULT_BREAKS,
    basemap="hillshade",
    requires=["raster_zonal", "soil_data"],
    label_ne="वार्षिक माटो क्षय (RUSLE)",
    label_en="Annual Soil Loss (RUSLE)",
    legend_title_ne="टन/हे./वर्ष",
    legend_title_en="t ha⁻¹ yr⁻¹",
)

# P5 — same surface clipped to the user-group extent (catchment soil loss).
_t(
    "soil__annual_loss__user_group",
    section="S9",
    layer="grid",
    measure="soil_loss",
    source="soil_grid",
    viz="raster_surface",
    value_kind="numeric",
    palette="reds",
    class_method="fixed",
    fixed_breaks=_SOIL_LOSS_DEFAULT_BREAKS,
    basemap="hillshade",
    requires=["raster_zonal", "soil_data", "user_group_extent"],
    label_ne="वार्षिक माटो क्षय — उपभोक्ता क्षेत्र (RUSLE)",
    label_en="Annual Soil Loss — User-Group Area (RUSLE)",
    legend_title_ne="टन/हे./वर्ष",
    legend_title_en="t ha⁻¹ yr⁻¹",
)

# P5 — the four RUSLE factor bands as their own surfaces (methodology annex),
# quantile-classed. thematic_overlay._SOIL_BANDS keys off the "__factor_*" suffix.
for _fk, (_fne, _fen) in {
    "soil__factor_r": ("वर्षा क्षयकारिता (R)", "Rainfall erosivity (R)"),
    "soil__factor_k": ("माटो क्षयशीलता (K)", "Soil erodibility (K)"),
    "soil__factor_ls": ("ढलान लम्बाइ-भिरालोपन (LS)", "Slope length & steepness (LS)"),
    "soil__factor_c": ("भू-आवरण व्यवस्थापन (C)", "Cover management (C)"),
}.items():
    _t(
        _fk,
        section="S9",
        layer="grid",
        measure="soil_loss",
        source="soil_grid",
        viz="raster_surface",
        value_kind="numeric",
        class_method="natural",
        basemap="hillshade",
        requires=["raster_zonal", "soil_data"],
        label_ne=f"RUSLE कारक — {_fne}",
        label_en=f"RUSLE Factor — {_fen}",
    )


# ── Landslide hazard + household vulnerability (S9) — computed surfaces.
# source="hazard_grid" → thematic_overlay._render_hazard_grid. LSI / FS classify
# with the *resolved* params; fixed_breaks here is only the fixture default.
# (HOUSEHOLD_VULNERABILITY_ANALYSIS_PLAN.md §2 P4.)
_LSI_DEFAULT_BREAKS = [1.8, 2.6, 3.4, 4.2]  # 5-class weighted-mean scale
_FS_DEFAULT_BREAKS = [1.0, 1.5]  # unstable / marginal / stable

_t(
    "hazard__landslide_susceptibility",
    section="S9",
    layer="grid",
    measure="lsi",
    source="hazard_grid",
    viz="raster_surface",
    value_kind="numeric",
    palette="spectral_r",  # blue (very low) → red (very high)
    class_method="fixed",
    fixed_breaks=_LSI_DEFAULT_BREAKS,
    basemap="hillshade",
    requires=["raster_zonal", "geology"],
    label_ne="पहिरो संवेदनशीलता सूचकाङ्क (LSI)",
    label_en="Landslide Susceptibility Index (LSI)",
    legend_title_ne="संवेदनशीलता वर्ग",
    legend_title_en="Susceptibility class",
)
_t(
    "hazard__landslide_susceptibility__user_group",
    section="S9",
    layer="grid",
    measure="lsi",
    source="hazard_grid",
    viz="raster_surface",
    value_kind="numeric",
    palette="spectral_r",
    class_method="fixed",
    fixed_breaks=_LSI_DEFAULT_BREAKS,
    basemap="hillshade",
    requires=["raster_zonal", "geology", "user_group_extent"],
    label_ne="पहिरो संवेदनशीलता — उपभोक्ता क्षेत्र (LSI)",
    label_en="Landslide Susceptibility — User-Group Area (LSI)",
)
_t(
    "hazard__landslide_prone_area",
    section="S9",
    layer="grid",
    measure="prone",
    source="hazard_grid",
    viz="raster_surface",
    value_kind="categorical",
    palette="reds",
    class_method="fixed",
    fixed_breaks=[0.5],
    basemap="hillshade",
    requires=["raster_zonal", "geology"],
    label_ne="सापेक्ष रूपमा उच्च संवेदनशील क्षेत्र (उच्च+ LSI वर्ग)",
    label_en="Relatively High-Susceptibility Area (High+ LSI class)",
)
_t(
    "hazard__factor_of_safety",
    section="S9",
    layer="grid",
    measure="fs",
    source="hazard_grid",
    viz="raster_surface",
    value_kind="numeric",
    palette="spectral",  # red (unstable) → blue (stable)
    class_method="fixed",
    fixed_breaks=_FS_DEFAULT_BREAKS,
    basemap="hillshade",
    requires=["raster_zonal", "soil_data"],
    label_ne="ढलान स्थायित्व (Factor of Safety) — मनसुन परिदृश्य",
    label_en="Slope Stability (Factor of Safety) — monsoon scenario",
    legend_title_ne="स्थायित्व वर्ग",
    legend_title_en="Stability class",
)
_t(
    "hazard__factor_of_safety__user_group",
    section="S9",
    layer="grid",
    measure="fs",
    source="hazard_grid",
    viz="raster_surface",
    value_kind="numeric",
    palette="spectral",
    class_method="fixed",
    fixed_breaks=_FS_DEFAULT_BREAKS,
    basemap="hillshade",
    requires=["raster_zonal", "soil_data", "user_group_extent"],
    label_ne="ढलान स्थायित्व — उपभोक्ता क्षेत्र",
    label_en="Slope Stability — User-Group Area",
)

# the ten LSI factor rating bands (methodology annex), quantile-classed.
for _hk, (_hne, _hen) in {
    "hazard__lsi_factor_slope": ("भिरालोपन", "Slope angle"),
    "hazard__lsi_factor_lithology": ("शिलावर्ग", "Lithology"),
    "hazard__lsi_factor_curvature_twi": (
        "वक्रता / आर्द्रता (TWI)",
        "Curvature / wetness (TWI)",
    ),
    "hazard__lsi_factor_dist_drainage": ("जलनिकास दूरी", "Distance to drainage"),
    "hazard__lsi_factor_dist_road": ("सडक दूरी", "Distance to road"),
    "hazard__lsi_factor_landcover": ("भू-आवरण", "Land cover"),
    "hazard__lsi_factor_landcover_change": (
        "भू-आवरण परिवर्तन (१९८४–)",
        "Land-cover change (1984–)",
    ),
    "hazard__lsi_factor_aspect": ("मोहडा", "Aspect"),
    "hazard__lsi_factor_rainfall": ("वर्षा", "Rainfall"),
    "hazard__lsi_factor_soil_texture": ("माटोको बनावट", "Soil texture"),
}.items():
    _t(
        _hk,
        section="S9",
        layer="grid",
        measure="lsi_factor",
        source="hazard_grid",
        viz="raster_surface",
        value_kind="numeric",
        class_method="natural",
        basemap="hillshade",
        requires=["raster_zonal", "geology"],
        label_ne=f"LSI कारक — {_hne}",
        label_en=f"LSI Factor — {_hen}",
    )

# household vulnerability — a dot map graduated by score over the LSI backdrop.
_t(
    "hh__vulnerability",
    section="S9",
    layer="household",
    measure="score",
    source="hazard_grid",
    viz="dot_gradient",
    value_kind="numeric",
    palette="reds",
    class_method="quantile",
    basemap="canvas_light",
    requires=["household_data"],
    label_ne="घरधुरी जोखिम (अंक अनुसार)",
    label_en="Household Vulnerability (by score)",
    legend_title_ne="जोखिम अंक",
    legend_title_en="Vulnerability score",
)
_t(
    "hh__vulnerability__user_group",
    section="S9",
    layer="household",
    measure="score",
    source="hazard_grid",
    viz="dot_gradient",
    value_kind="numeric",
    palette="reds",
    class_method="quantile",
    basemap="canvas_light",
    requires=["household_data", "user_group_extent"],
    label_ne="घरधुरी जोखिम — उपभोक्ता क्षेत्र",
    label_en="Household Vulnerability — User-Group Area",
)
_t(
    "hh__priority_settlements",
    section="S9",
    layer="settlement",
    measure="mean_score",
    source="hazard_grid",
    viz="dot_gradient",
    value_kind="numeric",
    palette="reds",
    class_method="quantile",
    basemap="canvas_light",
    requires=["household_data", "user_group_extent"],
    label_ne="प्राथमिकता बस्ती (औसत जोखिम अंक)",
    label_en="Priority Settlements (mean vulnerability score)",
)


# ══════════════════════════════════════════════════════════════════════════
# SFM P5 — दिगो वन व्यवस्थापन classification (source="sustainable_fm";
# thematic_overlay reads result_data['sfm']['blocks'], joins on block_name)
# ══════════════════════════════════════════════════════════════════════════
_t(
    "sfm__forest_type",
    section="S3",
    layer="unit",
    measure="effective_type_no",
    source="sustainable_fm",
    viz="choropleth",
    value_kind="categorical",
    palette="sfm_forest_type",
    basemap="imagery",
    basemap_alpha=1.0,       # the satellite photo at full strength
    fill_alpha=0.42,         # the unit colour is a tint over it, not a cover
    edge_color="#ffffff",
    edge_width=0.9,
    boundary_color="#ffffff",
    show_unit_labels=True,
    unit_label_kind="type",
    requires=["sfm_data"],
    label_ne="दिगो वन व्यवस्थापन वन प्रकार (अनुसूची-१)",
    label_en="Sustainable FM Forest Type (Schedule-1)",
    legend_title_ne="वन प्रकार (सि.नं.)",
    legend_title_en="Forest type (no.)",
)
_t(
    "sfm__orientation",
    section="S3",
    layer="unit",
    measure="orientation",
    source="sustainable_fm",
    viz="choropleth",
    value_kind="categorical",
    palette="sfm_orientation",
    basemap="imagery",
    basemap_alpha=1.0,       # the satellite photo at full strength
    fill_alpha=0.42,         # the unit colour is a tint over it, not a cover
    edge_color="#ffffff",
    edge_width=0.9,
    boundary_color="#ffffff",
    show_unit_labels=True,
    unit_label_kind="orientation",
    requires=["sfm_data"],
    label_ne="कार्य वृत्त अभिमुखीकरण (उत्पादन / संरक्षण / प्रतिरक्षा)",
    label_en="Working-circle Orientation (Production / Conservation / Protection)",
    legend_title_ne="अभिमुखीकरण",
    legend_title_en="Orientation",
)
_t(
    "sfm__gs_vs_threshold",
    section="S3",
    layer="unit",
    measure="gs_ge40_m3_per_ha",
    source="sustainable_fm",
    viz="choropleth",
    value_kind="numeric",
    palette="spectral",
    class_method="fixed",
    fixed_breaks=[150.0, 200.0],
    normalize="none",
    basemap="imagery",
    basemap_alpha=1.0,       # the satellite photo at full strength
    fill_alpha=0.42,         # the unit colour is a tint over it, not a cover
    edge_color="#ffffff",
    edge_width=0.9,
    boundary_color="#ffffff",
    show_unit_labels=True,
    unit_label_kind="stock",
    requires=["sfm_data"],
    label_ne="≥४० से.मि. मौज्दात (घन.मी./हे.) — कटान प्रतिशत सीमा सापेक्ष",
    label_en="Growing stock ≥40 cm DBH (m³/ha) vs the harvest-% step edges",
    legend_title_ne="मौज्दात वर्ग (१५० / २००)",
    legend_title_en="Stock class (150 / 200)",
)


# ── section names (S1..S20) — reference-page grouping (§3.4) ─────────────
SECTION_NAMES: dict[str, dict[str, str]] = {
    # thememap
    "S1": {"ne": "कार्य विभाजन तथा संरचना", "en": "Zoning & structure"},
    "S2": {"ne": "वनको अवस्था", "en": "Forest condition"},
    "S3": {"ne": "वन मौज्दात", "en": "Growing stock"},
    "S4": {"ne": "रूख संख्या तथा व्यास वर्ग", "en": "Stand structure"},
    "S5": {"ne": "प्रजाति", "en": "Species"},
    "S6": {"ne": "वार्षिक वृद्धि तथा कटान", "en": "Yield regulation"},
    "S7": {"ne": "कार्बन तथा जैविक पदार्थ", "en": "Carbon & biomass"},
    "S8": {"ne": "नमूना तथा विश्वसनीयता", "en": "Sampling & reliability"},
    "S9": {"ne": "भू-बनोट", "en": "Physiography"},
    "S10": {"ne": "परिवर्तन तथा अवरोध", "en": "Disturbance & change"},
    "S11": {"ne": "वन पैदावार तथा माग-आपूर्ति", "en": "Resources & demand"},
    "S12": {"ne": "समग्र नक्सा", "en": "Whole-forest overviews"},
    # opsmap
    "S13": {"ne": "कटान तथा सञ्चालन तालिका", "en": "Operations schedule"},
    "S14": {"ne": "व्यवस्थापन क्षेत्र विभाजन", "en": "Management zonation"},
    "S15": {"ne": "हस्तक्षेप तथा रोपण", "en": "Interventions & planting"},
    "S16": {"ne": "पूर्वाधार", "en": "Infrastructure"},
    "S17": {"ne": "संरक्षण", "en": "Protection & conservation"},
    "S18": {"ne": "जीविकोपार्जन तथा समुदाय", "en": "Livelihoods & community"},
    "S19": {"ne": "अनुगमन तथा सुशासन", "en": "Monitoring & governance"},
    "S20": {"ne": "बजेट, श्रम तथा चरणबद्धता", "en": "Budget, effort & phasing"},
}

# ── one-line descriptions per builtin spec (P3 content pass) ────────────
_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "unit__ntfp_plots": (
        "गैरकाष्ठ वन पैदावार सर्वेक्षणका नमूना प्लट र तिनको अवस्था नक्सामा देखाउँछ।",
        "Where the NTFP survey sample plots lie in the forest, coloured by their status.",
    ),
    "unit__working_circle": (
        "प्रत्येक एकाइ उत्पादन वा संरक्षित कार्य वृत्तमा पर्छ भन्ने देखाउँछ।",
        "Which working circle each unit belongs to — production or protection.",
    ),
    "unit__area": (
        "एकाइको क्षेत्रफल अनुसार केन्द्रमा समानुपातिक वृत्त।",
        "Proportional circle at each unit's centre, sized by its area.",
    ),
    "unit__area_share": (
        "प्रत्येक एकाइले कुल वन क्षेत्रफलको कति प्रतिशत ओगट्छ।",
        "Each unit's share of the total forest area, as a choropleth.",
    ),
    "unit__forest_condition": (
        "एकाइ अनुसार वनको अवस्था — राम्रो / मध्यम / कमजोर।",
        "Forest condition per unit — Good / Moderate / Weak.",
    ),
    "unit__species_dominant": (
        "प्रत्येक एकाइको काठ आयतन (पोल र रुख) मा सबैभन्दा बढी हिस्सा भएको प्रजाति — नमूना प्लटको मापनबाट।",
        "The species with the largest share of each unit's timber volume (poles and trees), from its own sample-plot "
        "measurements; one colour per species of this forest.",
    ),
    "unit__species_composition__pie": (
        "प्रत्येक एकाइको प्रमुख ५ प्रजातिको काठ आयतन हिस्सा (बाँकी 'अन्य प्रजाति')।",
        "Each unit's top five species by share of timber volume (the rest as 'other species'), from its own sample-plot "
        "measurements.",
    ),
    "unit__regeneration_condition": (
        "एकाइ अनुसार पुनरुत्पादनको अवस्था।",
        "Regeneration condition per unit — Good / Moderate / Weak.",
    ),
    "unit__dbh_gs_mai_aah__stackbar": (
        "१० सेमी माथिका रुखको वृद्धि भण्डार, MAI र AAH ब्यास वर्ग अनुसार — तीन स्तम्भ।",
        "Growing stock, MAI and AAH of trees from 10 cm up, by DBH class: three bars per unit (MAI and AAH shared in proportion to stock).",
    ),
    "unit__pole_tree_share": (
        "प्रति-हेक्टर मौज्दातमा ३० सेमी माथिका रुखको हिस्सा; खाँवा (१०–३०) र रुख (३०+) को संख्या, मौज्दात, MAI, AAH सहित।",
        "Share of the per-ha stock held by trees of 30 cm and over; hover gives poles (10–30) and trees (30+): stems, stock, MAI, AAH.",
    ),
    "unit__condition_reason": (
        "वनको अवस्था (रङ) र पुनरुत्पादनको अवस्था (गाढापन) एकसाथ, कारण सहित।",
        "Forest condition (hue) and regeneration condition (shade) together, with the numbers behind them.",
    ),
    "unit__condition_x_stocking": (
        "वनको अवस्था र प्रति-हेक्टर मौज्दात एकसाथ — ३×३ द्वि-चर रङ।",
        "Forest condition and per-ha growing stock together, in one 3×3 bivariate scheme.",
    ),
    "unit__growing_stock": (
        "एकाइ अनुसार प्रति-हेक्टर वन मौज्दात (घन मिटर)।",
        "Growing stock per hectare (m³) by unit.",
    ),
    "unit__growing_stock__graduated": (
        "एकाइको कुल वन मौज्दात — क्षेत्रफलले गुणन गरिएको समानुपातिक वृत्त।",
        "Absolute growing stock per unit (per-ha × area), as a proportional symbol.",
    ),
    "unit__growing_stock__label": (
        "वन मौज्दात नक्सा, प्रत्येक एकाइमा मान लेखिएको।",
        "Growing stock choropleth with the value printed on each unit.",
    ),
    "unit__growing_stock__dasymetric": (
        "प्रति-हेक्टर वन मौज्दात, सञ्चालनयोग्य क्षेत्रमा मात्र (बहिष्कृत उप-क्षेत्र काटिएको)।",
        "Per-ha growing stock shown only on the operable area (excluded sub-areas clipped out).",
    ),
    "unit__satellite_stock": (
        "उपग्रह (AGB) आधारित प्रति-हेक्टर मौज्दात अनुमान।",
        "Satellite (AGB-raster) derived growing stock per hectare.",
    ),
    "unit__field_vs_satellite": (
        "क्षेत्र सर्वेक्षण र उपग्रह अनुमानबीचको फरक — शून्यमा तटस्थ।",
        "Field-inventory minus satellite estimate — diverging around zero.",
    ),
    "unit__basal_area": (
        "एकाइ अनुसार प्रति-हेक्टर आधार क्षेत्र (m²)।",
        "Basal area per hectare (m²) by unit.",
    ),
    "unit__stock_reliability": (
        "मौज्दातको रङ, तर नमूना प्लट संख्या अनुसार अपारदर्शिता — पातलो = कम भरपर्दो।",
        "Growing-stock colour, faded by sample-plot count — lighter = less certain.",
    ),
    "unit__stems_total": (
        "एकाइ अनुसार प्रति-हेक्टर कुल रूख + खाँवा संख्या।",
        "Total stems per hectare (trees + poles) by unit.",
    ),
    "unit__tree_per_ha": (
        "एकाइ अनुसार प्रति-हेक्टर रूख संख्या।",
        "Trees per hectare by unit.",
    ),
    "unit__pole_per_ha": (
        "एकाइ अनुसार प्रति-हेक्टर खाँवा संख्या।",
        "Poles per hectare by unit.",
    ),
    "unit__regeneration_stems": (
        "एकाइ अनुसार प्रति-हेक्टर पुनरुत्पादन (बिरुवा) संख्या।",
        "Regeneration stems per hectare by unit.",
    ),
    "unit__mai": (
        "एकाइ अनुसार वार्षिक औसत वृद्धि (m³/हे./वर्ष)।",
        "Mean annual increment per unit (m³/ha/yr).",
    ),
    "unit__mai_percent": (
        "एकाइ अनुसार वार्षिक वृद्धि प्रतिशत।",
        "MAI as a percentage, by unit.",
    ),
    "unit__aah": (
        "एकाइ अनुसार वार्षिक स्वीकार्य कटान (m³/हे./वर्ष)।",
        "Annual allowable harvest per unit (m³/ha/yr).",
    ),
    "unit__aah__graduated": (
        "एकाइको कुल वार्षिक स्वीकार्य कटान — समानुपातिक वृत्त।",
        "Absolute AAH per unit, as a proportional symbol.",
    ),
    "unit__aah__label": (
        "AAH नक्सा, प्रत्येक एकाइमा मान लेखिएको।",
        "AAH choropleth with the value printed on each unit.",
    ),
    "unit__carbon": (
        "एकाइ अनुसार प्रति-हेक्टर कार्बन मौज्दात (tC)।",
        "Carbon stock per hectare (tC) by unit.",
    ),
    "unit__co2": (
        "एकाइ अनुसार प्रति-हेक्टर CO₂ समतुल्य।",
        "CO₂-equivalent per hectare by unit.",
    ),
    "unit__biomass": (
        "एकाइ अनुसार प्रति-हेक्टर कुल जैविक पदार्थ (टन)।",
        "Total biomass per hectare (t) by unit.",
    ),
    "unit__carbon__graduated": (
        "एकाइको कुल कार्बन मौज्दात — समानुपातिक वृत्त।",
        "Absolute carbon stock per unit, as a proportional symbol.",
    ),
    "unit__dbh_class_count__stackbar": (
        "प्रत्येक एकाइको केन्द्रमा ८ ब्यास वर्गको प्रति-हेक्टर रूख संख्या — थाक बार।",
        "A stacked bar at each unit's centre — stems/ha across the 8 DBH classes.",
    ),
    "unit__dbh_class_count__pie": (
        "प्रत्येक एकाइको केन्द्रमा ब्यास वर्ग अनुसार रूख हिस्साको पाई चार्ट।",
        "A pie at each unit's centre — the DBH-class share of stems.",
    ),
    "unit__dbh_class_count__sparkline": (
        "प्रत्येक एकाइको ब्यास वर्ग वितरणको सानो वक्र — रिभर्स-J आकार जाँच्न।",
        "A tiny curve of each unit's DBH-class distribution — the reverse-J adequacy check.",
    ),
    "unit__dbh_class_stock__stackbar": (
        "प्रत्येक एकाइको केन्द्रमा ब्यास वर्ग अनुसार काठ मौज्दात (घ.मी./हे.) — थाक बार।",
        "A stacked bar of timber volume (m³/ha) by DBH class, per unit.",
    ),
    "unit__dbh_composition__waffle": (
        "प्रत्येक एकाइको ब्यास वर्ग संरचना — गनिने कोठाहरूको वफल।",
        "Each unit's DBH-class mix as a counted-cell waffle.",
    ),
    "unit__regen_pole_tree__ternary": (
        "पुनरुत्पादन : खाँवा : रूखको अनुपात एक त्रिकोणीय बिन्दुमा।",
        "The regeneration : pole : tree ratio as one point in a triangle.",
    ),
    "unit__timber_firewood__stackbar": (
        "प्रत्येक एकाइको केन्द्रमा काठ बनाम दाउरा आयतन — थाक बार।",
        "Timber vs firewood volume per unit, as a centroid stacked bar.",
    ),
    "unit__agb_bgb__stackbar": (
        "प्रत्येक एकाइको माथिल्लो बनाम तल्लो जैविक पदार्थ — थाक बार।",
        "Above- vs below-ground biomass per unit, as a centroid stacked bar.",
    ),
    "unit__health_fingerprint": (
        "अवस्था, पुनरुत्पादन, MAI, आधार क्षेत्र र कार्बनलाई ५-अक्ष रडारमा — कुन एकाइ मिल्दाजुल्दा छन्।",
        "Condition, regeneration, MAI, basal area and carbon on a 5-axis radar — which units look alike.",
    ),
    "unit__condition_with_dbh": (
        "वनको अवस्था (रङ भरिएको) माथि ब्यास वर्ग पाई चित्र।",
        "Forest-condition fill with a DBH-class pie glyph on top.",
    ),
    "forest__dbh_by_unit": (
        "प्रत्येक एकाइको ब्यास वर्ग बार — एउटै पानामा सानो नक्साहरूको ग्रिड।",
        "One DBH-class bar per unit, laid out as a grid of small maps.",
    ),
    # opsmap (P5c)
    "unit__felling_year": (
        "कुन ब्लक योजनाको कुन वर्ष कटान हुन्छ — कटान क्रम नक्सा।",
        "Which plan year each block is felled — the coupe/felling order.",
    ),
    "unit__felling_series": (
        "समान अवधिमा कटान हुने ब्लकहरूको समूह (कटान श्रृंखला)।",
        "Blocks grouped into felling series — those cut in the same period.",
    ),
    "unit__prescribed_harvest": (
        "प्रत्येक ब्लकमा कार्ययोजनाले तोकेको कुल कटान परिमाण — समानुपातिक वृत्त।",
        "Total harvest volume the plan prescribes per block, as a proportional symbol.",
    ),
    "unit__harvest_vs_aah": (
        "नियत कटान ÷ ब्लकको AAH सीमा (%) — १००% भन्दा माथि = अधिक कटान।",
        "Prescribed cut ÷ the block's AAH ceiling (%); above 100% = over-cut.",
    ),
    "forest__working_circles": (
        "उत्पादन बनाम संरक्षित कार्य वृत्त।",
        "Production vs protection working circles.",
    ),
    "unit__budget_total": (
        "योजना अवधिभरको प्रत्येक ब्लकको कुल प्रस्तावित बजेट — समानुपातिक वृत्त।",
        "Each block's total proposed budget over the plan, as a proportional symbol.",
    ),
    "unit__activity_count": (
        "प्रत्येक ब्लकलाई छुने प्रस्तावित क्रियाकलापको संख्या।",
        "How many proposed activities touch each block.",
    ),
    # P7 — opsmap drawn features + 10-year axis
    "forest__annual_coupe_panel": (
        "योजनाको हरेक वर्षका लागि एउटा सानो नक्सा — त्यस वर्ष कटान हुने ब्लक "
        "र त्यस वर्ष तोकिएका कोरिएका सुविधाहरू। ५×२ खण्ड।",
        "One mini-map per plan year — the blocks felled that year plus any "
        "drawn features scheduled for it, laid out as a 5×2 panel.",
    ),
    "forest__ten_year_phasing": (
        "पूरै दस वर्षे कार्यतालिका एकै नजरमा — प्रति-वर्ष खण्डमा कोरिएका " "क्रियाकलाप र कटान।",
        "The whole ten-year schedule at a glance — coupe and drawn activities "
        "in a per-year panel grid.",
    ),
    "forest__year_one_operations": (
        "योजना वर्ष १ मा तोकिएका सबै कुरा एउटै आधारमा — कटान क्षेत्रको भराइ "
        "माथि कोरिएका बिन्दु/रेखा/बहुभुज, प्रकार अनुसार चिन्ह।",
        "Everything scheduled for plan year 1 on one base — coupe fill under "
        "the drawn points / lines / polygons, symbolised by feature kind.",
    ),
    "unit__silviculture_year": (
        "प्रत्येक ब्लकको मुख्य वन-पालन कार्य कुन वर्ष हुन्छ भन्ने — वर्ष अनुसार रङ।",
        "The plan year of each block's main silvicultural operation — coloured "
        "sequentially by year.",
    ),
    "unit__operation_count": (
        "योजना अवधिभर प्रत्येक ब्लकमा तोकिएका सञ्चालनको कुल संख्या।",
        "How many prescribed operations touch each block over the plan period.",
    ),
    "feature__plantation_areas": (
        "क्रियाकलापका लागि कोरिएका रोपण / समृद्धीकरण बहुभुजहरू।",
        "The planting / enrichment polygons drawn for the plan's activities.",
    ),
    "feature__anr_areas": (
        "सहायतायुक्त प्राकृतिक पुनरुत्पादनका लागि कोरिएका क्षेत्रहरू।",
        "Areas drawn for assisted natural regeneration.",
    ),
    "feature__nursery_sites": (
        "योजनामा तोकिएका नर्सरी स्थलहरू (बिन्दु चिन्ह)।",
        "Nursery locations prescribed in the plan, as point markers.",
    ),
    "feature__seed_stands": (
        "बीउ रूख / मातृ-वृक्ष आरक्ष स्थलहरू।",
        "Seed stands / mother-tree reserves drawn for the plan.",
    ),
    "feature__roads_trails": (
        "प्रस्तावित बाटो र गोरेटो — वर्ग अनुसार रेखाको मोटाइ।",
        "Proposed roads and trails, line weight by class.",
    ),
    "feature__depots": (
        "काठ डिपो / संकलन केन्द्रहरू (बिन्दु चिन्ह)।",
        "Timber depots / collection points, as point markers.",
    ),
    "feature__structures_all": (
        "सम्पूर्ण निर्मित पूर्वाधार एउटै नक्सामा — प्रकार अनुसार वर्गीकृत बिन्दु।",
        "All built infrastructure on one map — a categorical dot map by type.",
    ),
    "feature__fire_lines": (
        "आगो नियन्त्रण रेखा / फायरब्रेक सञ्जाल।",
        "The fire-break / fire-line network drawn for the plan.",
    ),
    "feature__river_banks": (
        "खोला किनार — दुवै तर्फ २० मिटर संरक्षण क्षेत्र।",
        "River banks - the 20 m protection strip on each side of a river.",
    ),
    "feature__patrol_routes": (
        "गस्ती / रेन्जर मार्गहरू।",
        "Patrol / ranger routes drawn for the plan.",
    ),
    "feature__biodiversity_blocks": (
        "जैविक विविधता संरक्षण क्षेत्रहरू।",
        "Biodiversity conservation areas drawn for the plan.",
    ),
    "unit__protection_priority": (
        "नियत कटान ÷ AAH सीमाबाट व्युत्पन्न ब्लक-तहको संरक्षण प्राथमिकता।",
        "Block-level protection priority derived from prescribed cut ÷ the AAH "
        "ceiling.",
    ),
    "feature__ntfp_zones": (
        "गैरकाष्ठ वन पैदावार / घाँस / दाउरा / खोटो क्षेत्रहरू।",
        "NTFP / grass / fodder / resin zones drawn for the plan.",
    ),
    "feature__propoor_plots": (
        "विपन्न वर्गलाई छुट्याइएका भूखण्डहरू।",
        "Pro-poor allocation plots drawn for the plan.",
    ),
    "feature__ecotourism": (
        "पर्यापर्यटन स्थल तथा पदमार्गहरू।",
        "Ecotourism sites and trails drawn for the plan.",
    ),
    "feature__permanent_plots": (
        "योजना अवधिभरका स्थायी नमूना प्लटहरू (बिन्दु चिन्ह)।",
        "Permanent sample plots for the plan period, as point markers.",
    ),
    "feature__monitoring_points": (
        "अनुगमन / फोटो बिन्दुहरू।",
        "Monitoring / photo points drawn for the plan.",
    ),
    "forest__activities_missing_map": (
        "गुणस्तर जाँच — नक्सा चाहिने (requires_map) तर कुनै सुविधा नकोरिएका "
        "क्रियाकलाप भएका ब्लकहरू रातो।",
        "QA — blocks red where an activity is marked as needing a map "
        "(requires_map) but has no drawn feature.",
    ),
    "unit__budget_by_year": (
        "प्रत्येक योजना वर्षको लागि ब्लक-तहको बजेट — प्रति-वर्ष सानो नक्सा।",
        "Block-level budget for each plan year, as a per-year mini-map panel.",
    ),
    "unit__persondays": (
        "प्रत्येक ब्लकमा तोकिएको श्रम / व्यक्ति-दिन — समानुपातिक वृत्त।",
        "Labour / person-days prescribed per block, as a proportional symbol.",
    ),
    "unit__actual_vs_planned": (
        "वास्तविक बनाम योजना गरिएको प्रगति (ActivityYearDetail.actual_*) — "
        "विचलनकारी रङ, १००% = योजना अनुसार।",
        "Actual vs planned progress (from ActivityYearDetail.actual_*) — "
        "diverging colours, 100% = on plan.",
    ),
    # P6 — point / density / surface
    "plot__location": (
        "क्षेत्र सर्वेक्षणका नमूना प्लटहरू आ-आफ्नो ब्लकको रङमा बिन्दुका रूपमा — "
        "नमूना कहाँ लिइयो भन्ने देखाउँछ।",
        "Field-inventory sample plots as dots, coloured by their block — shows "
        "where the sample was actually taken.",
    ),
    "plot__zone": (
        "प्रत्येक नमूना प्लट उत्पादन कि संरक्षित क्षेत्रमा पर्‍यो — दुई रङका बिन्दु।",
        "Each sample plot coloured by whether it fell in the production or the "
        "protected zone.",
    ),
    "grid__plot_density": (
        "नमूना प्लटको स्थानिक घनत्व — षट्कोण कक्षमा प्रति-कक्ष प्लट गणना; "
        "कम नमूना भएका भाग देखाउँछ।",
        "Spatial density of sample plots — plot count per hexagonal cell; "
        "highlights under-sampled parts of the forest.",
    ),
    "forest__plot_kde": (
        "नमूना प्रयासको न्वारेण घनत्व सतह (KDE) — मौज्दातले तौलिएको।",
        "A smoothed kernel-density surface of sampling effort (KDE), weighted by "
        "the growing stock recorded at each plot.",
    ),
    "forest__growing_stock_surface": (
        "प्लट-तहको वन मौज्दातलाई दूरी-प्रतिलोम भार (IDW) ले अन्तर्वेशन गरी बनाइएको "
        "निरन्तर सतह — ब्लक सिमाना नमानिकन मौज्दात कहाँ बढी/घटी छ देखाउँछ।",
        "A continuous surface interpolated from plot-level growing stock by "
        "inverse-distance weighting (IDW) — shows where stock is high or low "
        "independent of block boundaries.",
    ),
    "forest__carbon_surface": (
        "प्लट-तहको कार्बन मौज्दातबाट IDW अन्तर्वेशनले बनेको निरन्तर सतह।",
        "A continuous IDW-interpolated surface built from plot-level carbon " "stock.",
    ),
    "unit__stems_dotdensity": (
        "थोप्ला-घनत्व नक्सा — प्रत्येक थोप्लो निश्चित संख्याका रूखबराबर; "
        "थोप्ला ब्लकभित्र अनियमित छरिन्छन्, चोरोप्लेथभन्दा सङ्ख्या राम्ररी झल्काउँछ।",
        "Dot-density map — one dot equals a fixed number of stems, scattered at "
        "random inside each block; reads magnitude better than a choropleth.",
    ),
    "unit__stems_all": (
        "रुख नक्शाङ्कन गरिएको क्षेत्रका सबै रुखहरू — प्रत्येक थोप्लो एक रुख।",
        "Every mapped tree of the stem-mapped area - one dot per tree.",
    ),
    "unit__stems_felling": (
        "पुनरुत्पादन कटानमा कटान (FT) गरिने रुखहरू — प्रत्येक थोप्लो एक रुख।",
        "The felling (FT) trees of the regeneration-felling area - one dot per tree.",
    ),
    "unit__stems_mother": (
        "पुनरुत्पादन कटान क्षेत्रमा कायम राखिने माउ (MT) रुखहरू — प्रत्येक थोप्लो एक रुख।",
        "The mother (MT) trees kept in the regeneration-felling area - one dot per tree.",
    ),
    "forest__drainage_vectors": (
        "वनभित्र र वरिपरि पर्ने नदी/खोला रेखाहरू (river84 तथ्याङ्क) — नीलो रेखामा "
        "देखाइन्छ। सिमानाबाहिर अलिकति लम्ब्याइएको।",
        "River and stream lines in and around the forest (river84 layer), drawn "
        "in blue and extended a little past the boundary for context.",
    ),
    "unit__forest_cover_change": (
        "दुई सर्वेक्षण चक्रबीच वन आवरणको वृद्धि/ह्रास — विचलनकारी रङ। "
        "अघिल्लो सर्वेक्षण नभएसम्म उपलब्ध छैन।",
        "Gain / loss of forest cover between two inventory cycles — diverging "
        "colours. Not available until a prior inventory exists to compare "
        "against.",
    ),
    "flow__settlement_to_unit": (
        "कुन बस्तीले कुन आपूर्ति एकाइबाट काठ/दाउरा पाउँछ भन्ने प्रवाह रेखा। "
        "बस्ती माग-वितरण मोडेल नबनेसम्म उपलब्ध छैन।",
        "Flow lines from each settlement to the unit that supplies its timber / "
        "firewood. Not available until a settlement demand-allocation model is "
        "built.",
    ),
    # P6z — S9 physiography (per-unit zonal statistics over the rasters.* tables)
    "zone__elevation_mean": (
        "प्रत्येक एकाइभित्रको औसत उचाइ (DEM रास्टरबाट क्षेत्रगत औसत)।",
        "Mean elevation within each unit — a zonal average over the DEM raster.",
    ),
    "zone__elevation_range": (
        "प्रत्येक एकाइभित्रको उच्चतम र न्यूनतम उचाइको फरक — भू-बनोटको उतारचढाव।",
        "Max minus min elevation within each unit — how broken the terrain is.",
    ),
    "zone__slope_mean": (
        "प्रत्येक एकाइको औसत भिरालोपन (भिरालो-वर्ग रास्टरका वर्गहरूको भारित औसत, डिग्रीमा)।",
        "Mean slope per unit — a pixel-weighted average of the slope-class raster "
        "in degrees.",
    ),
    "zone__slope_dominant": (
        "प्रत्येक एकाइमा सबैभन्दा बढी क्षेत्रफल ओगट्ने भिरालो वर्ग (मन्द → अति भिरालो)।",
        "The slope class covering the most area in each unit (gentle → very steep).",
    ),
    "zone__slope_class__stackbar": (
        "प्रत्येक एकाइको केन्द्रमा चार भिरालो वर्गको क्षेत्रफल हिस्सा — थाक बार।",
        "A stacked bar at each unit's centre — the area share of the four slope "
        "classes.",
    ),
    "zone__aspect_dominant": (
        "प्रत्येक एकाइमा प्रमुख मोहडा (आठ दिशामध्ये सबैभन्दा बढी क्षेत्रफल भएको)।",
        "The dominant hillslope aspect per unit — the compass octant with the "
        "most area.",
    ),
    "zone__aspect__rose": (
        "प्रत्येक एकाइको मोहडा वितरण — आठ दिशाको हिस्सा देखाउने आठ-पंखे रोज चित्र।",
        "Each unit's aspect distribution as an eight-petal wind rose — the share "
        "of area facing each compass octant.",
    ),
    "zone__canopy_mean": (
        "प्रत्येक एकाइको औसत रूख/छत्र उचाइ (क्यानोपी उचाइ रास्टरबाट क्षेत्रगत औसत)।",
        "Mean canopy height per unit — a zonal average over the canopy-height "
        "raster.",
    ),
    "zone__biomass_raster_mean": (
        "प्रत्येक एकाइको औसत माथिल्लो-जमिन जैविक भार (AGB रास्टरबाट, क्षेत्र सर्वेक्षणबाट होइन)।",
        "Mean above-ground biomass per unit from the AGB raster — an independent "
        "check on the field inventory.",
    ),
    "zone__landcover_dominant": (
        "प्रत्येक एकाइमा प्रमुख भू-आवरण वर्ग (ESA WorldCover रास्टरबाट)।",
        "The dominant land-cover class per unit, from the ESA WorldCover raster.",
    ),
    "zone__landcover__pie": (
        "प्रत्येक एकाइको केन्द्रमा भू-आवरण वर्गको क्षेत्रफल हिस्साको पाई चित्र।",
        "A pie at each unit's centre — the area share of land-cover classes.",
    ),
    "zone__forest_type_dominant": (
        "प्रत्येक एकाइमा प्रमुख वन प्रकार (वन-प्रकार रास्टरबाट; नाम core."
        "forest_types साझा शब्दावलीबाट)।",
        "The dominant forest type per unit, from the forest-type raster. Labels "
        "come from core.forest_types, the same vocabulary the tile map uses.",
    ),
    "vector__slope_aspect": (
        "प्रत्येक एकाइको केन्द्रबाट प्रमुख मोहडा (तल्लो-ढलान) दिशातर्फ देखाउने तीर।",
        "An arrow from each unit's centre pointing in the dominant-aspect "
        "(downslope) direction.",
    ),
    "zone__accessibility": (
        "प्रत्येक एकाइको सबैभन्दा टाढाको भित्री बिन्दु सडक/गोरेटोबाट कति टाढा छ "
        "(मिटरमा) — infrastructure.road तह प्रयोग गरी। ठूलो मान = कम पहुँच।",
        "How far the remotest interior point of each unit is from a road or "
        "trail (metres), using the infrastructure.road layer. Higher = less "
        "accessible.",
    ),
    "zone__forest_health": (
        "प्रत्येक एकाइमा उपग्रह-आधारित वन स्वास्थ्यको **प्रमुख वर्ग** "
        "(nepal_forest_health रास्टर, १ = तनावग्रस्त … ५ = उत्कृष्ट)।",
        "Dominant satellite-based forest-health class per unit (nepal_forest_health "
        "raster, 1 = stressed … 5 = excellent).",
    ),
    "zone__forest_health__pie": (
        "प्रत्येक एकाइमा वन स्वास्थ्य वर्गहरूको हिस्सा (१–५ वर्ग प्रतिशत)।",
        "Share of each forest-health class (1-5) within every unit.",
    ),
    "zone__nasa_quality_dominant": (
        "प्रत्येक एकाइमा NASA द्वारा वर्गीकृत वन गुणको प्रमुख वर्ग "
        "(nasa_forest_2020 रास्टर, १ = प्राथमिक … ३ = पुरानो दोस्रो पुस्ता)।",
        "Dominant NASA forest-quality class per unit (nasa_forest_2020 raster, "
        "1 = primary … 3 = old secondary).",
    ),
    "zone__nasa_quality__pie": (
        "प्रत्येक एकाइमा NASA वन गुण वर्गहरूको हिस्सा (१–३ वर्ग प्रतिशत)।",
        "Share of each NASA forest-quality class (1-3) within every unit.",
    ),
    "soil__annual_loss": (
        "RUSLE समीकरण (A = R·K·LS·C·P) बाट गणना गरिएको वार्षिक माटो क्षय, "
        "गम्भीरता वर्गमा विभाजित सतह नक्सा (DEM, माटो, वर्षा र भू-आवरणबाट)।",
        "Annual soil loss from the RUSLE equation (A = R·K·LS·C·P), shown as a "
        "surface classed into severity bands — from the DEM, soil, rainfall and "
        "land-cover layers.",
    ),
    "soil__annual_loss__user_group": (
        "उही RUSLE माटो क्षय सतह, तर वन सिमानाभित्र नभई उपभोक्ता समूहको "
        "बस्ती क्षेत्रभित्र काटिएको — वन बाहिरको भूमिको क्षय पनि देखिन्छ।",
        "The same RUSLE soil-loss surface, clipped to the user-group settlement "
        "catchment instead of the forest boundary — includes erosion on land "
        "outside the forest.",
    ),
    "soil__factor_r": (
        "RUSLE को वर्षा-क्षयकारिता कारक (R) एक्लै — संशोधित फोर्नियर सूचकाङ्कबाट।",
        "The RUSLE rainfall-erosivity factor (R) on its own — from the Modified "
        "Fournier Index.",
    ),
    "soil__factor_k": (
        "RUSLE को माटो-क्षयशीलता कारक (K) एक्लै — बालुवा/सिल्ट/माटो र प्राङ्गारिक "
        "कार्बनबाट (EPIC समीकरण)।",
        "The RUSLE soil-erodibility factor (K) on its own — from sand/silt/clay "
        "and organic carbon (EPIC equation).",
    ),
    "soil__factor_ls": (
        "RUSLE को ढलान लम्बाइ-भिरालोपन कारक (LS) एक्लै — DEM बाट।",
        "The RUSLE slope length & steepness factor (LS) on its own — from the " "DEM.",
    ),
    "soil__factor_c": (
        "RUSLE को भू-आवरण-व्यवस्थापन कारक (C) एक्लै — ESA भू-आवरण र छत्र उचाइबाट।",
        "The RUSLE cover-management factor (C) on its own — from ESA land cover "
        "and canopy height.",
    ),
    # ── landslide hazard + household vulnerability (P4) ──────────────────
    "hazard__landslide_susceptibility": (
        "भिरालोपन, शिलावर्ग, वक्रता/आर्द्रता, जलनिकास र सडक दूरी, भू-आवरण आदि "
        "भारित गरी बनेको पहिरो संवेदनशीलता सूचकाङ्क — ५ वर्गमा। पहिरो सूची "
        "नभएकाले यो सापेक्ष हो, सम्भाव्यता होइन।",
        "A weighted overlay of slope, lithology, curvature/wetness, distance to "
        "drainage and road, land cover and rainfall — reclassed to 5 classes. "
        "Relative susceptibility, not a probability (no landslide inventory).",
    ),
    "hazard__landslide_susceptibility__user_group": (
        "उही पहिरो संवेदनशीलता सूचकाङ्क, उपभोक्ता समूह क्षेत्रमा काटिएको।",
        "The same Landslide Susceptibility Index, clipped to the user-group "
        "settlement catchment.",
    ),
    "hazard__landslide_prone_area": (
        "LSI उच्च वा अति उच्च वर्गमा परेका कक्षहरू एकीकृत गरी बनेको बहुभुज। वर्गहरू यही "
        "वनभित्रको सापेक्ष क्रम हुन् (पूर्ण जोखिम होइन) — क्षेत्रीय प्राथमिकीकरणका लागि मात्र।",
        "The cells in the High / Very-High LSI classes dissolved into one polygon. The classes are "
        "RELATIVE to this forest (not absolute hazard) — for spatial prioritisation only.",
    ),
    "hazard__factor_of_safety": (
        "अनन्त-ढलान मोडेलबाट गणना गरिएको स्थायित्व गुणांक (FS) — मनसुनी संतृप्त "
        "परिदृश्य, अनुमानित रेगोलिथ गहिराइ सहित। FS<१ अस्थिर, १–१.५ सीमान्त।",
        "The infinite-slope Factor of Safety under a saturated-monsoon scenario "
        "with an assumed regolith depth. FS < 1 unstable, 1–1.5 marginal.",
    ),
    "hazard__factor_of_safety__user_group": (
        "उही स्थायित्व गुणांक नक्सा, उपभोक्ता समूह क्षेत्रमा काटिएको।",
        "The same Factor-of-Safety surface, clipped to the user-group area.",
    ),
    "hazard__lsi_factor_slope": (
        "LSI को भिरालोपन कारक एक्लै — DEM बाट डिग्रीमा, १–५ मा पुनर्वर्गीकृत।",
        "The LSI slope-angle factor on its own — from the DEM, reclassed 1–5.",
    ),
    "hazard__lsi_factor_lithology": (
        "LSI को शिलावर्ग कारक — geology.geology बाट; कमजोर शिवालिक = उच्च।",
        "The LSI lithology factor — from geology.geology; weak Siwalik = high.",
    ),
    "hazard__lsi_factor_curvature_twi": (
        "LSI को वक्रता/आर्द्रता कारक — DEM बाट TWI र योजना-वक्रता; भिजेको "
        "अभिसारी कक्षमा उच्च।",
        "The LSI curvature/wetness factor — TWI and plan curvature from the "
        "DEM; high in wet convergent cells.",
    ),
    "hazard__lsi_factor_dist_drainage": (
        "LSI को जलनिकास-दूरी कारक — river.river84 सम्मको दूरी; नजिक = उच्च " "(खोला कटान)।",
        "The LSI distance-to-drainage factor — distance to river.river84; "
        "closer = higher (toe undercutting).",
    ),
    "hazard__lsi_factor_dist_road": (
        "LSI को सडक-दूरी कारक — infrastructure.road सम्मको दूरी; नजिक = उच्च "
        "(काटिएको भिर)।",
        "The LSI distance-to-road factor — distance to infrastructure.road; "
        "closer = higher (cut-slope failures).",
    ),
    "hazard__lsi_factor_landcover": (
        "LSI को भू-आवरण कारक — ESA WorldCover वर्ग; वन न्यून, नाङ्गो जमिन उच्च।",
        "The LSI land-cover factor — ESA WorldCover class; forest low, bare "
        "ground high.",
    ),
    "hazard__lsi_factor_landcover_change": (
        "LSI को भू-आवरण-परिवर्तन कारक — १९८४ मा वन र अहिले वन नभएका कक्षमा उच्च।",
        "The LSI land-cover-change factor — high where 1984 was forest and the "
        "cell is no longer forest.",
    ),
    "hazard__lsi_factor_aspect": (
        "LSI को मोहडा कारक — DEM बाट; मनसुन-सामु फर्केका भिरमा अलि उच्च।",
        "The LSI aspect factor — from the DEM; slightly higher on "
        "monsoon-facing slopes.",
    ),
    "hazard__lsi_factor_rainfall": (
        "LSI को वर्षा कारक — rasters.annual_precipitation; बढी वर्षा = उच्च " "प्रेरक भार।",
        "The LSI rainfall factor — from rasters.annual_precipitation; more "
        "rain = higher trigger weight.",
    ),
    "hazard__lsi_factor_soil_texture": (
        "LSI को माटो-बनावट कारक — soil.soilgrids बाट; गेग्रान-युक्त माटो अलि "
        "बढी संवेदनशील।",
        "The LSI soil-texture factor — from soil.soilgrids; silt-rich soils "
        "are slightly more susceptible.",
    ),
    "hh__vulnerability": (
        "प्रत्येक घरधुरी उसको समग्र जोखिम अंक अनुसार रङ्गिएको बिन्दु, पहिरो "
        "संवेदनशीलता पृष्ठभूमिमा — नाम/जात/निर्देशांक बिना।",
        "Each household as a dot coloured by its composite vulnerability score "
        "over the LSI backdrop — no name, caste or coordinates shown.",
    ),
    "hh__vulnerability__user_group": (
        "उही घरधुरी जोखिम बिन्दु नक्सा, उपभोक्ता समूह क्षेत्रमा।",
        "The same household-vulnerability dot map, within the user-group area.",
    ),
    "hh__priority_settlements": (
        "बस्ती/टोल केन्द्रबिन्दु, औसत घरधुरी जोखिम अंक अनुसार रङ्गिएको — "
        "कुन टोललाई पहिले सम्बोधन गर्ने भन्ने देखाउँछ।",
        "Settlement / tole centroids coloured by mean household vulnerability "
        "score — which toles the plan should address first.",
    ),
    "sfm__forest_type": (
        "प्रत्येक खण्ड/कम्पार्टमेन्ट दिगो वन व्यवस्थापन कार्यविधि, २०७९ अनुसूची-१ का "
        "१४ वन प्रकारमध्ये कुनमा वर्गीकृत भयो — प्रभावकारी प्रकार (अधिरोहण भए सोही)।",
        "Which of the 14 अनुसूची-१ forest types each block / compartment is "
        "classified into — the effective type (an accepted override wins).",
    ),
    "sfm__orientation": (
        "प्रत्येक एकाइको कार्य वृत्त अभिमुखीकरण — उत्पादन, संरक्षण वा प्रतिरक्षा; "
        "प्रतिरक्षा एकाइमा नियमित कटान हुँदैन।",
        "Each unit's working-circle orientation — Production, Conservation or "
        "Protection; a Protection unit carries no regular felling.",
    ),
    "sfm__gs_vs_threshold": (
        "≥४० से.मि. व्यासका रुखको प्रति हेक्टर मौज्दात, कटान प्रतिशत निर्धारण "
        "गर्ने १५० र २०० घन.मी./हे. सीमा सापेक्ष रङ्गिएको।",
        "Per-hectare growing stock of trees ≥40 cm DBH, shaded against the "
        "150 and 200 m³/ha step edges that set the harvest percentage.",
    ),
}

for _k, (_dne, _den) in _DESCRIPTIONS.items():
    _s = BUILTIN_THEMEMAP_SPECS.get(_k) or BUILTIN_OPSMAP_SPECS.get(_k)
    if _s is not None:
        _s.description_ne = _dne
        _s.description_en = _den


# ── legacy map:* metadata (§3.10) ──────────────────────────────────────
# key -> (section, requires, description_en, basemap)
LEGACY_MAP_META: dict[str, tuple[str, list[str], str, str]] = {
    "map:boundary": (
        "S1",
        [],
        "Forest boundary + block outlines on a street basemap.",
        "osm",
    ),
    "map:forest_type": (
        "S5",
        [],
        "Dominant forest-type raster clipped to the boundary.",
        "osm",
    ),
    "map:forest_health": ("S2", [], "Forest-health raster (stress → healthy).", "osm"),
    "map:slope": (
        "S9",
        [],
        "Slope-class raster over a topographic basemap.",
        "hillshade",
    ),
    "map:biomass": ("S7", [], "Above-ground biomass raster.", "osm"),
    "map:landcover": ("S11", [], "Land-cover class raster.", "osm"),
    "map:landcover_1984": (
        "S11",
        [],
        "1984 land-use polygons (landcover.landcover_1984) clipped to the "
        "boundary, filled by class.",
        "osm",
    ),
    # drawn by the thematic map "zone__nasa_quality_dominant" (op_docx_builder.MAP_ALIAS): the dominant NASA 2020 forest-quality class per unit
    "map:nasa_forest_2020": ("S5", [], "NASA 2020 forest quality (primary / young / old secondary forest) per unit.", "osm"),
    "map:soil_texture": ("S9", [], "Dominant soil-texture raster.", "osm"),
    "map:dem": ("S9", [], "Elevation (DEM) over a topographic basemap.", "hillshade"),
    "map:aspect": (
        "S9",
        [],
        "Aspect-class raster over a topographic basemap.",
        "hillshade",
    ),
    "map:canopy": ("S7", [], "Canopy-cover / height raster.", "osm"),
    "map:sampling_plot": (
        "S8",
        ["sampling"],
        "Sample-plot points on a street basemap.",
        "osm",
    ),
    "map:sampling_plot_topo": (
        "S8",
        ["sampling"],
        "Sample-plot points on a topographic basemap.",
        "topo",
    ),
    "map:sampling_plot_satellite": (
        "S8",
        ["sampling"],
        "Sample-plot points on satellite imagery.",
        "imagery",
    ),
    "map:fieldbook": ("S8", ["fieldbook"], "GPS fieldbook path + points.", "topo"),
    "map:usergroup": (
        "S11",
        ["user_group_extent"],
        "User-group settlement catchment + POIs.",
        "topo",
    ),
    "map:subarea": (
        "S1",
        ["sub_areas"],
        "Management sub-areas coloured by category.",
        "topo",
    ),
    "map:compartment": (
        "S1",
        ["compartments"],
        "Compartment polygons, numbered.",
        "osm",
    ),
    "map:sub_compartment": (
        "S1",
        ["compartments"],
        "Sub-compartment polygons, numbered.",
        "osm",
    ),
    "map:boundary_map": ("S1", [], "Alias of map:boundary.", "osm"),
}


# Fields a template node / per-calc override may set on top of the builtin
# spec (P6). Identity, prose and prerequisites stay owned by the builtin.
OVERRIDABLE_FIELDS = frozenset(
    {
        "palette",
        "class_method",
        "class_count",
        "fixed_breaks",
        "normalize",
        "reference_value",
        "basemap",
        "scale_by",
        "layout",
        "show_value_labels",
        "show_unit_labels",
        "unit_label_kind",
        "basemap_alpha",
        "fill_alpha",
        "edge_color",
        "edge_width",
        "boundary_color",
        "show_hydrology",
        "combine_with",
        "interpolate",
        "year",
        "legend_title_ne",
        "legend_title_en",
    }
)


# ── resolution ───────────────────────────────────────────────────────────
def resolve_spec(
    token_or_key: str, *, override: Optional[dict] = None
) -> Optional[ThematicMapSpec]:
    """Look up a spec by ``family:key`` token or a bare ``key``.

    ``override`` is an optional dict from a template node (``TreeNode.thememap_spec``)
    or a per-calc tweak; only :data:`OVERRIDABLE_FIELDS` are honoured — identity,
    prose and ``requires`` always come from the builtin. The merged spec keeps a
    distinct :func:`spec_hash` so its render cache does not collide with the
    builtin's.
    """
    key = token_or_key
    if ":" in token_or_key:
        fam, key = token_or_key.split(":", 1)
        reg = BUILTIN_OPSMAP_SPECS if fam == "opsmap" else BUILTIN_THEMEMAP_SPECS
        spec = reg.get(key)
    else:
        spec = BUILTIN_THEMEMAP_SPECS.get(key) or BUILTIN_OPSMAP_SPECS.get(key)
    if spec is None or not override:
        return spec
    patch = {
        k: v for k, v in override.items() if k in OVERRIDABLE_FIELDS and v is not None
    }
    if not patch:
        return spec
    try:
        # re-validate so a bad override value can't produce a spec that crashes
        # the renderer (model_copy would skip validation).
        return ThematicMapSpec.model_validate({**spec.model_dump(), **patch})
    except Exception:  # noqa: BLE001 -- a bad override must not break the export
        return spec


def all_specs() -> list[ThematicMapSpec]:
    return [*BUILTIN_THEMEMAP_SPECS.values(), *BUILTIN_OPSMAP_SPECS.values()]
