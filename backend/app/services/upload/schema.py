"""Canonical upload schema — the single source of truth for the unified upload.

Both the **Forest Data Workbook** generator and the **upload validator** read
this module and nothing else. Every *purpose* (what a piece of uploaded data
is), its columns, the signals used to auto-classify a loose file, and its
validation rules (each tagged ``error`` / ``warning``) live here.

    from app.services.upload import schema
    schema.get("forest_boundary")          # one Purpose
    schema.ordered()                        # boundary first, then the rest
    schema.to_dict()                        # JSON for the frontend / generator

UNIFIED_UPLOAD_PLAN.md §4.1 (template) and §5 (validations).

Adding a purpose or a rule is a deliberate edit *here* — the dialog does not
grow free-form mapping.
"""

from __future__ import annotations

# `replace` is aliased: test_no_import_side_effects flags a bare `replace(` call
# at module scope (it means `os.replace` / `Path.replace` to that AST guard).
from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from typing import Literal, Optional

SCHEMA_VERSION = "1.0"

# ── thresholds (SSOT — boundary_validation imports these) ────────────────
MAX_AREA_HA = 1000.0
MAX_BUILTUP_CROPLAND_PCT = 40.0
PA_NON_BUFFER_TOLERANCE_PCT = 5.0
NEPAL_OUTSIDE_TOLERANCE_PCT = 0.5
# a unit polygon may poke this far past the forest boundary before it is an error
UNIT_OUTSIDE_TOLERANCE_M = 2.0
# blocks / compartments should tile at least this much of the forest
UNIT_MIN_COVERAGE_PCT = 90.0
# ESA WorldCover class codes used by R3
ESA_BUILT_UP = 50
ESA_CROPLAND = 40
# tree measurement sanity
TREE_DBH_MAX_CM = 500.0
TREE_HEIGHT_MAX_M = 100.0

# the 14 sub-area management categories (mirror of semantic_palettes._SUBAREA_CATEGORY)
SUB_AREA_CATEGORIES = (
    "protected",
    "plantation",
    "pro-poor",
    "religious",
    "biodiversity",
    "tourist",
    "office",
    "private_land",
    "agroforestry",
    "tree_strata",
    "water_hole",
    "wildlife_corridor",
    "agriculture",
    "settlement",
)

DType = Literal["text", "integer", "number", "boolean", "date"]
Level = Literal["error", "warning"]
Kind = Literal["spatial", "tabular", "spatial_or_tabular"]


@dataclass(frozen=True)
class Column:
    name: str
    dtype: DType
    required: bool = False
    unit: Optional[str] = None
    enum: tuple[str, ...] = ()
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    example: object = None
    aliases: tuple[str, ...] = ()  # fuzzy-match synonyms for a loose sheet
    description_en: str = ""
    description_ne: str = ""

    def as_dict(self) -> dict:
        d = {
            "name": self.name,
            "dtype": self.dtype,
            "required": self.required,
            "unit": self.unit,
            "enum": list(self.enum),
            "minimum": self.minimum,
            "maximum": self.maximum,
            "example": self.example,
            "aliases": list(self.aliases),
            "description_en": self.description_en,
            "description_ne": self.description_ne,
        }
        return {k: v for k, v in d.items() if v not in (None, [], ())}


@dataclass(frozen=True)
class Rule:
    """One validation check. ``kind`` selects the validator's dispatch;
    ``params`` is kind-specific. Every rule is an ``error`` or a ``warning``.
    """

    code: str
    level: Level
    kind: Literal[
        # --- geometry / spatial ---
        "geometry_sane",  # valid, polygonal/expected type, in Nepal bbox, no lat/lon swap
        "nepal_extent",  # within ST_Union(admin.province.shape) (± NEPAL_OUTSIDE_TOLERANCE_PCT)
        "max_area",  # geodesic area <= params.limit_ha
        "min_area",  # geodesic area >= params.limit_ha
        "landcover_max",  # Σ(ESA classes params.classes) <= params.limit_pct of area
        "protected_area_buffer_zone",  # admin.protected_area overlap must be 'Buffer Zone'
        "within_boundary",  # feature inside the forest boundary (± params.tolerance_m)
        "coverage",  # Σ(features) covers >= params.min_pct of the boundary
        "no_overlap",  # features don't overlap each other beyond tolerance
        "geometry_type",  # geometry is one of params.types
        # --- tabular ---
        "required_columns",  # params.columns all present (after fuzzy mapping)
        "column_range",  # params.column within [params.min, params.max]
        "column_enum",  # params.column in params.values
        "non_empty",  # params.column has no blank cells
        "unique",  # params.columns are unique together
        # --- cross-file / reference ---
        "resolves_to",  # params.column (or a spatial join) resolves to a real params.target
        "species_known",  # species resolves in tree_species_coefficients
        "ward_valid",  # ward number valid for the forest's district
        # --- delegation ---
        "handler",  # params.ref = "module:function" that returns its own findings
    ]
    message_en: str
    message_ne: str
    params: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "level": self.level,
            "kind": self.kind,
            "message_en": self.message_en,
            "message_ne": self.message_ne,
            "params": self.params,
        }


@dataclass(frozen=True)
class Purpose:
    id: str
    label_en: str
    label_ne: str
    kind: Kind
    order: int  # boundary is 0 — it must be first / present in a bundle
    layer_name: str  # canonical GeoPackage layer + Excel sheet name
    geometry_types: tuple[str, ...] = ()
    name_aliases: tuple[str, ...] = ()  # classification signal 1 (layer/sheet name)
    fingerprint_required: tuple[str, ...] = ()  # classification signal 2 (column set)
    geometry_hint: str = ""  # classification signal 3 (shape heuristic, human-readable)
    columns: tuple[Column, ...] = ()
    rules: tuple[Rule, ...] = ()
    append_only: bool = False  # a re-upload adds rather than replaces
    required_in_bundle: bool = False  # a bulk bundle is refused without this
    description_en: str = ""
    description_ne: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label_en": self.label_en,
            "label_ne": self.label_ne,
            "kind": self.kind,
            "order": self.order,
            "layer_name": self.layer_name,
            "geometry_types": list(self.geometry_types),
            "name_aliases": list(self.name_aliases),
            "fingerprint_required": list(self.fingerprint_required),
            "geometry_hint": self.geometry_hint,
            "append_only": self.append_only,
            "required_in_bundle": self.required_in_bundle,
            "description_en": self.description_en,
            "description_ne": self.description_ne,
            "columns": [c.as_dict() for c in self.columns],
            "rules": [r.as_dict() for r in self.rules],
        }


# ══════════════════════════════════════════════════════════════════════════
# reusable column fragments
# ══════════════════════════════════════════════════════════════════════════
_LON = Column(
    "longitude",
    "number",
    required=True,
    unit="degrees (WGS84)",
    minimum=79.9,
    maximum=88.4,
    example=85.0421,
    aliases=("lon", "lng", "long", "x", "देशान्तर", "देशान्तर_रेखांश"),
    description_en="Longitude in decimal degrees, WGS84.",
    description_ne="देशान्तर, दशमलव डिग्रीमा (WGS84)।",
)
_LAT = Column(
    "latitude",
    "number",
    required=True,
    unit="degrees (WGS84)",
    minimum=26.3,
    maximum=30.6,
    example=27.4381,
    aliases=("lat", "y", "अक्षांश"),
    description_en="Latitude in decimal degrees, WGS84.",
    description_ne="अक्षांश, दशमलव डिग्रीमा (WGS84)।",
)
_UNIT_NAME = Column(
    "name",
    "text",
    required=True,
    example="Block-1",
    aliases=("block_name", "compartment_code", "code", "label", "नाम", "ब्लक"),
    description_en="A short, unique name for this unit.",
    description_ne="यस एकाइको छोटो, अद्वितीय नाम।",
)
_WORKING_CIRCLE = Column(
    "working_circle",
    "text",
    enum=("production", "protection"),
    example="production",
    aliases=("wc", "circle", "कार्य_वृत्त"),
    description_en="'production' or 'protection'. Defaults to 'production'.",
    description_ne="'production' वा 'protection'। पूर्वनिर्धारित 'production'।",
)


# ══════════════════════════════════════════════════════════════════════════
# the purposes
# ══════════════════════════════════════════════════════════════════════════
PURPOSES: dict[str, Purpose] = {}


def _reg(p: Purpose) -> None:
    PURPOSES[p.id] = p


_reg(
    Purpose(
        id="forest_boundary",
        label_en="Forest boundary",
        label_ne="वन सिमाना",
        kind="spatial",
        order=0,
        required_in_bundle=True,
        layer_name="forest_boundary",
        geometry_types=("POLYGON", "MULTIPOLYGON"),
        name_aliases=(
            "boundary",
            "forest_boundary",
            "forest boundary",
            "सिमाना",
            "वन_सिमाना",
        ),
        geometry_hint="The single polygon that encloses every other layer; the largest by area.",
        description_en="The outer boundary of the community forest. Must be uploaded first.",
        description_ne="सामुदायिक वनको बाहिरी सिमाना। सबैभन्दा पहिले अपलोड गर्नुपर्छ।",
        rules=(
            Rule(
                "forest_boundary.validate",
                "error",
                "handler",
                "The forest boundary is checked for validity, Nepal extent, "
                "the 1000 ha cap, the 40% built-up + cropland cap, and "
                "protected-area / Buffer Zone rules.",
                "वन सिमानाको वैधता, नेपाल सिमा, १००० हेक्टर सीमा, ४०% बस्ती + "
                "कृषि सीमा, र संरक्षित क्षेत्र / मध्यवर्ती क्षेत्र नियम जाँचिन्छ।",
                {
                    "ref": "app.services.boundary_validation:validate_forest_boundary",
                    "rules": {
                        "R0_geometry_sane": {"level": "error"},
                        "R1_nepal_extent": {
                            "level": "error",
                            "tolerance_pct": NEPAL_OUTSIDE_TOLERANCE_PCT,
                            "reference": "admin.province.shape",
                        },
                        "R2_max_area": {"level": "error", "limit_ha": MAX_AREA_HA},
                        "R3_landcover_max": {
                            "level": "error",
                            "limit_pct": MAX_BUILTUP_CROPLAND_PCT,
                            "esa_classes": [ESA_BUILT_UP, ESA_CROPLAND],
                            "reference": "rasters.esa_world_cover",
                        },
                        "R4_protected_area_buffer_zone": {
                            "warn_up_to_pct": PA_NON_BUFFER_TOLERANCE_PCT,
                            "buffer_zone_value": "Buffer Zone",
                            "reference": "admin.protected_area.description",
                        },
                    },
                },
            ),
        ),
    )
)

_reg(
    Purpose(
        id="blocks",
        label_en="Blocks",
        label_ne="ब्लक",
        kind="spatial",
        order=10,
        layer_name="blocks",
        geometry_types=("POLYGON", "MULTIPOLYGON"),
        name_aliases=("blocks", "block", "ब्लक", "खण्ड"),
        geometry_hint="Several adjacent polygons that together tile most of the boundary.",
        description_en="Top-level management divisions of the forest.",
        description_ne="वनका मुख्य व्यवस्थापन विभाजनहरू।",
        columns=(_UNIT_NAME, _WORKING_CIRCLE),
        rules=(
            Rule(
                "blocks.name_required",
                "error",
                "non_empty",
                "Every block needs a name.",
                "प्रत्येक ब्लकलाई नाम चाहिन्छ।",
                {"column": "name"},
            ),
            Rule(
                "blocks.name_unique",
                "error",
                "unique",
                "Block names must be unique.",
                "ब्लकका नाम अद्वितीय हुनुपर्छ।",
                {"columns": ["name"]},
            ),
            Rule(
                "blocks.inside_boundary",
                "error",
                "within_boundary",
                "Blocks must lie inside the forest boundary.",
                "ब्लकहरू वन सिमानाभित्र हुनुपर्छ।",
                {"tolerance_m": UNIT_OUTSIDE_TOLERANCE_M},
            ),
            Rule(
                "blocks.coverage",
                "warning",
                "coverage",
                f"Blocks should cover at least {UNIT_MIN_COVERAGE_PCT:.0f}% of the forest.",
                f"ब्लकहरूले वनको कम्तीमा {UNIT_MIN_COVERAGE_PCT:.0f}% भाग ओगट्नुपर्छ।",
                {"min_pct": UNIT_MIN_COVERAGE_PCT},
            ),
            Rule(
                "blocks.no_overlap",
                "warning",
                "no_overlap",
                "Blocks should not overlap each other.",
                "ब्लकहरू एकअर्कासँग खप्टिनु हुँदैन।",
                {},
            ),
            Rule(
                "blocks.working_circle_enum",
                "error",
                "column_enum",
                "working_circle must be 'production' or 'protection'.",
                "working_circle 'production' वा 'protection' हुनुपर्छ।",
                {"column": "working_circle", "values": ["production", "protection"]},
            ),
        ),
    )
)

_reg(
    Purpose(
        id="compartments",
        label_en="Compartments",
        label_ne="कम्पार्टमेन्ट",
        kind="spatial",
        order=11,
        layer_name="compartments",
        geometry_types=("POLYGON", "MULTIPOLYGON"),
        name_aliases=("compartments", "compartment", "कम्पार्टमेन्ट"),
        geometry_hint="Like blocks — adjacent polygons tiling the forest. Replaces any derived splits.",
        description_en="Compartment divisions (used instead of blocks in compartment mode).",
        description_ne="कम्पार्टमेन्ट विभाजन (कम्पार्टमेन्ट मोडमा ब्लकको सट्टा)।",
        columns=(_UNIT_NAME, _WORKING_CIRCLE),
        rules=(
            Rule(
                "compartments.name_required",
                "error",
                "non_empty",
                "Every compartment needs a name.",
                "प्रत्येक कम्पार्टमेन्टलाई नाम चाहिन्छ।",
                {"column": "name"},
            ),
            Rule(
                "compartments.name_unique",
                "error",
                "unique",
                "Compartment names must be unique.",
                "कम्पार्टमेन्टका नाम अद्वितीय हुनुपर्छ।",
                {"columns": ["name"]},
            ),
            Rule(
                "compartments.inside_boundary",
                "error",
                "within_boundary",
                "Compartments must lie inside the forest boundary.",
                "कम्पार्टमेन्टहरू वन सिमानाभित्र हुनुपर्छ।",
                {"tolerance_m": UNIT_OUTSIDE_TOLERANCE_M},
            ),
            Rule(
                "compartments.no_overlap",
                "warning",
                "no_overlap",
                "Compartments should not overlap each other.",
                "कम्पार्टमेन्टहरू एकअर्कासँग खप्टिनु हुँदैन।",
                {},
            ),
        ),
    )
)

_reg(
    Purpose(
        id="sub_compartments",
        label_en="Sub-compartments",
        label_ne="उप-कम्पार्टमेन्ट",
        kind="spatial",
        order=12,
        layer_name="sub_compartments",
        geometry_types=("POLYGON", "MULTIPOLYGON"),
        name_aliases=("sub_compartments", "subcompartments", "उप_कम्पार्टमेन्ट"),
        geometry_hint="Polygons contained within compartments.",
        description_en="Sub-divisions of compartments.",
        description_ne="कम्पार्टमेन्टका उप-विभाजन।",
        columns=(_UNIT_NAME,),
        rules=(
            Rule(
                "sub_compartments.name_unique",
                "error",
                "unique",
                "Sub-compartment names must be unique.",
                "उप-कम्पार्टमेन्टका नाम अद्वितीय हुनुपर्छ।",
                {"columns": ["name"]},
            ),
            Rule(
                "sub_compartments.inside_compartment",
                "error",
                "within_boundary",
                "Sub-compartments must lie inside a compartment.",
                "उप-कम्पार्टमेन्ट कम्पार्टमेन्टभित्र हुनुपर्छ।",
                {"tolerance_m": UNIT_OUTSIDE_TOLERANCE_M, "target": "compartments"},
            ),
        ),
    )
)

_reg(
    Purpose(
        id="sub_blocks",
        label_en="Sub-blocks",
        label_ne="उप-ब्लक",
        kind="spatial",
        order=13,
        layer_name="sub_blocks",
        geometry_types=("POLYGON", "MULTIPOLYGON"),
        name_aliases=("sub_blocks", "subblocks", "sub-block", "उप_ब्लक"),
        geometry_hint="Polygons contained within blocks.",
        description_en="Sub-divisions of blocks.",
        description_ne="ब्लकका उप-विभाजन।",
        columns=(_UNIT_NAME,),
        rules=(
            Rule(
                "sub_blocks.name_unique",
                "error",
                "unique",
                "Sub-block names must be unique.",
                "उप-ब्लकका नाम अद्वितीय हुनुपर्छ।",
                {"columns": ["name"]},
            ),
            Rule(
                "sub_blocks.inside_block",
                "error",
                "within_boundary",
                "Sub-blocks must lie inside a block.",
                "उप-ब्लकहरू ब्लकभित्र हुनुपर्छ।",
                {"tolerance_m": UNIT_OUTSIDE_TOLERANCE_M, "target": "blocks"},
            ),
        ),
    )
)

_reg(
    Purpose(
        id="sub_areas",
        label_en="Sub-areas",
        label_ne="उप-क्षेत्र",
        kind="spatial",
        order=20,
        append_only=True,
        layer_name="sub_areas",
        geometry_types=("POLYGON", "MULTIPOLYGON"),
        name_aliases=("sub_areas", "subareas", "sub-area", "उप_क्षेत्र"),
        geometry_hint="Smaller polygons inside the forest, each with a management category.",
        description_en="Special-management patches: protected, plantation, private land, etc.",
        description_ne="विशेष व्यवस्थापन क्षेत्र: संरक्षित, बृक्षारोपण, निजी जग्गा, आदि।",
        columns=(
            Column(
                "name",
                "text",
                example="Sacred grove",
                aliases=("label", "नाम"),
                description_en="Optional label for this sub-area.",
                description_ne="यस उप-क्षेत्रको वैकल्पिक नाम।",
            ),
            Column(
                "category",
                "text",
                required=True,
                enum=SUB_AREA_CATEGORIES,
                example="protected",
                aliases=("purpose", "type", "वर्ग", "प्रकार", "sub_area_type"),
                description_en="One of the 14 management categories.",
                description_ne="१४ व्यवस्थापन वर्गमध्ये एक।",
            ),
        ),
        rules=(
            Rule(
                "sub_areas.category_required",
                "error",
                "non_empty",
                "Every sub-area needs a category.",
                "प्रत्येक उप-क्षेत्रलाई वर्ग चाहिन्छ।",
                {"column": "category"},
            ),
            Rule(
                "sub_areas.category_enum",
                "error",
                "column_enum",
                "category must be one of the allowed management categories.",
                "वर्ग अनुमत व्यवस्थापन वर्गमध्ये एक हुनुपर्छ।",
                {"column": "category", "values": list(SUB_AREA_CATEGORIES)},
            ),
            Rule(
                "sub_areas.inside_boundary",
                "error",
                "within_boundary",
                "Sub-areas must lie inside the forest boundary.",
                "उप-क्षेत्रहरू वन सिमानाभित्र हुनुपर्छ।",
                {"tolerance_m": UNIT_OUTSIDE_TOLERANCE_M},
            ),
        ),
    )
)

_reg(
    Purpose(
        id="sample_plots",
        label_en="Sample plots",
        label_ne="नमुना प्लट",
        kind="spatial_or_tabular",
        order=30,
        layer_name="sample_plots",
        geometry_types=("POINT", "MULTIPOINT", "POLYGON"),
        name_aliases=("sample_plots", "plots", "sample plot", "नमुना_प्लट", "प्लट"),
        fingerprint_required=("plot_number",),
        geometry_hint="Points (or small circles) on a regular grid inside the forest.",
        description_en="Field-inventory sample plot locations.",
        description_ne="क्षेत्र सर्वेक्षण नमुना प्लटका स्थानहरू।",
        columns=(
            Column(
                "plot_number",
                "integer",
                required=True,
                example=1,
                aliases=("plot_no", "plot", "sample_plot_number", "प्लट_नं"),
                description_en="Plot number, unique within its block.",
                description_ne="प्लट नम्बर, ब्लकभित्र अद्वितीय।",
            ),
            Column(
                "block",
                "text",
                example="Block-1",
                aliases=("block_name", "unit", "ब्लक"),
                description_en="Block/compartment this plot belongs to (else resolved by location).",
                description_ne="यो प्लट पर्ने ब्लक/कम्पार्टमेन्ट (नभए स्थानबाट पत्ता लगाइन्छ)।",
            ),
            Column(
                "radius_m",
                "number",
                unit="m",
                minimum=1,
                maximum=50,
                example=12.62,
                aliases=("radius", "plot_radius"),
                description_en="Plot radius in metres, if circular.",
                description_ne="वृत्ताकार भए प्लटको त्रिज्या मिटरमा।",
            ),
            _dc_replace(_LON, required=False),
            _dc_replace(_LAT, required=False),
        ),
        rules=(
            Rule(
                "sample_plots.plot_number_required",
                "error",
                "non_empty",
                "Every plot needs a plot number.",
                "प्रत्येक प्लटलाई प्लट नम्बर चाहिन्छ।",
                {"column": "plot_number"},
            ),
            Rule(
                "sample_plots.inside_boundary",
                "error",
                "within_boundary",
                "Sample plots must lie inside the forest boundary.",
                "नमुना प्लटहरू वन सिमानाभित्र हुनुपर्छ।",
                {"tolerance_m": 0},
            ),
            Rule(
                "sample_plots.block_resolves",
                "warning",
                "resolves_to",
                "The 'block' value should match a real block (else it is resolved by location).",
                "'block' मान वास्तविक ब्लकसँग मिल्नुपर्छ (नभए स्थानबाट पत्ता लगाइन्छ)।",
                {"column": "block", "target": "blocks", "fallback": "point_in_polygon"},
            ),
        ),
    )
)

_reg(
    Purpose(
        id="trees",
        label_en="Trees",
        label_ne="रूख",
        kind="spatial_or_tabular",
        order=40,
        layer_name="trees",
        geometry_types=("POINT", "MULTIPOINT"),
        name_aliases=("trees", "tree", "inventory", "tree_inventory", "रूख", "रूख_सूची"),
        fingerprint_required=("species", "dbh_cm", "latitude"),
        geometry_hint="Many points, one per tree, scattered through the forest.",
        description_en="Individual trees measured on the ground, with GPS positions.",
        description_ne="जमिनमा नापिएका छुट्टाछुट्टै रूख, जीपीएस स्थानसहित।",
        columns=(
            Column(
                "species",
                "text",
                required=True,
                example="Shorea robusta",
                aliases=(
                    "species_scientific",
                    "sp",
                    "scientific_name",
                    "प्रजाति",
                    "रूख_प्रजाति",
                ),
                description_en="Scientific species name (matched to the coefficient table).",
                description_ne="वैज्ञानिक प्रजातिको नाम (गुणांक तालिकासँग मिलाइने)।",
            ),
            Column(
                "dbh_cm",
                "number",
                required=True,
                unit="cm",
                minimum=0,
                maximum=TREE_DBH_MAX_CM,
                example=31.4,
                aliases=("dia_cm", "dbh", "diameter", "dia", "व्यास"),
                description_en="Diameter at breast height, centimetres.",
                description_ne="छातीको उचाइमा व्यास, सेन्टिमिटर।",
            ),
            Column(
                "height_m",
                "number",
                unit="m",
                minimum=0,
                maximum=TREE_HEIGHT_MAX_M,
                example=18.6,
                aliases=("ht", "height", "उचाइ"),
                description_en="Total tree height, metres (estimated from DBH if blank).",
                description_ne="रूखको कुल उचाइ, मिटर (खाली भए व्यासबाट अनुमान)।",
            ),
            _LON,
            _LAT,
            Column(
                "plot",
                "text",
                example="Block-1",
                aliases=("plot_no", "sample_plot", "block"),
                description_en="Optional plot/block the tree belongs to.",
                description_ne="रूख पर्ने वैकल्पिक प्लट/ब्लक।",
            ),
            Column(
                "tree_no",
                "integer",
                example=7,
                aliases=("tree_number", "sn", "रूख_नं"),
                description_en="Tree number within its plot.",
                description_ne="प्लटभित्र रूख नम्बर।",
            ),
            Column(
                "class",
                "text",
                enum=("Regeneration", "Sapling", "Pole", "Tree"),
                aliases=("stand_type", "size_class"),
                description_en="Stand type, if recorded.",
                description_ne="रेकर्ड गरिएको भए स्ट्यान्ड प्रकार।",
            ),
        ),
        rules=(
            Rule(
                "trees.required_columns",
                "error",
                "required_columns",
                "Tree data needs species, dbh_cm, longitude and latitude.",
                "रूख तथ्याङ्कलाई species, dbh_cm, longitude र latitude चाहिन्छ।",
                {"columns": ["species", "dbh_cm", "longitude", "latitude"]},
            ),
            Rule(
                "trees.dbh_range",
                "warning",
                "column_range",
                f"DBH should be between 0 and {TREE_DBH_MAX_CM:.0f} cm.",
                f"व्यास ० देखि {TREE_DBH_MAX_CM:.0f} सेन्टिमिटर बीच हुनुपर्छ।",
                {"column": "dbh_cm", "min": 0, "max": TREE_DBH_MAX_CM},
            ),
            Rule(
                "trees.height_range",
                "warning",
                "column_range",
                f"Height should be between 0 and {TREE_HEIGHT_MAX_M:.0f} m.",
                f"उचाइ ० देखि {TREE_HEIGHT_MAX_M:.0f} मिटर बीच हुनुपर्छ।",
                {"column": "height_m", "min": 0, "max": TREE_HEIGHT_MAX_M},
            ),
            Rule(
                "trees.inside_boundary",
                "warning",
                "within_boundary",
                "Some trees fall outside the forest boundary (kept, flagged).",
                "केही रूख वन सिमानाबाहिर छन् (राखिन्छ, चिन्ह लगाइन्छ)।",
                {"tolerance_m": 0},
            ),
            Rule(
                "trees.species_known",
                "warning",
                "species_known",
                "Some species are not in the coefficient table — volume/biomass may be approximate.",
                "केही प्रजाति गुणांक तालिकामा छैनन् — आयतन/बायोमास अनुमानित हुन सक्छ।",
                {},
            ),
            Rule(
                "trees.plot_tree_unique",
                "warning",
                "unique",
                "The same (plot, tree_no) appears more than once.",
                "उही (plot, tree_no) एकपटकभन्दा बढी देखिन्छ।",
                {"columns": ["plot", "tree_no"]},
            ),
        ),
    )
)

_reg(
    Purpose(
        id="field_inventory",
        label_en="Field inventory (per plot)",
        label_ne="क्षेत्र सर्वेक्षण (प्लट अनुसार)",
        kind="tabular",
        order=41,
        layer_name="field_inventory",
        name_aliases=("field_inventory", "field inventory", "fi", "क्षेत्र_सर्वेक्षण"),
        fingerprint_required=("block", "plot_number", "regen_species"),
        description_en=(
            "The per-plot survey sheet with regeneration / sapling / pole / tree "
            "measurements. Its full column list is produced by the field-inventory "
            "column mapping (field_inventory_service); the core keys are below."
        ),
        description_ne=(
            "पुनरुत्पादन / बिरुवा / खम्बा / रूख नाप भएको प्रति-प्लट सर्वेक्षण पाना। "
            "यसको पूर्ण स्तम्भ सूची field_inventory_service ले बनाउँछ; मुख्य कुञ्जीहरू तल छन्।"
        ),
        columns=(
            Column(
                "block", "text", required=True, aliases=("block_name", "unit", "ब्लक")
            ),
            Column(
                "plot_number",
                "integer",
                required=True,
                aliases=("sample_plot_number", "plot"),
            ),
            _dc_replace(_LON, required=False),
            _dc_replace(_LAT, required=False),
            Column(
                "regen_species", "text", aliases=("regeneration_species_scientific",)
            ),
            Column("pole_species", "text", aliases=("pole_species_scientific",)),
            Column("pole_dbh_cm", "number", unit="cm"),
            Column("tree_species", "text", aliases=("tree_species_scientific",)),
            Column("tree_dbh_cm", "number", unit="cm"),
            Column("tree_height_m", "number", unit="m"),
        ),
        rules=(
            Rule(
                "field_inventory.required_columns",
                "error",
                "required_columns",
                "Field inventory needs a block column and a plot number.",
                "क्षेत्र सर्वेक्षणलाई ब्लक स्तम्भ र प्लट नम्बर चाहिन्छ।",
                {"columns": ["block", "plot_number"]},
            ),
            Rule(
                "field_inventory.plot_block_resolves",
                "warning",
                "resolves_to",
                "Each plot is re-keyed to the block its GPS point falls in "
                "(the sheet's block label is a hint only).",
                "प्रत्येक प्लट यसको जीपीएस बिन्दु पर्ने ब्लकमा पुन: कुञ्जीकृत हुन्छ "
                "(पानाको ब्लक लेबल संकेत मात्र हो)।",
                {
                    "column": "block",
                    "target": "blocks",
                    "fallback": "point_in_polygon",
                    "impl": "app.services.field_inventory_service:assign_plot_blocks_by_location",
                },
            ),
        ),
    )
)

_reg(
    Purpose(
        id="forest_metadata",
        label_en="Forest details",
        label_ne="वनको विवरण",
        kind="tabular",
        order=45,
        layer_name="forest_metadata",
        name_aliases=("forest_metadata", "metadata", "forest details", "वनको विवरण"),
        fingerprint_required=("forest_name", "district"),
        description_en="The forest's identifying details (name, group, location, offices, national code, plan years): one row. Template: 07_Forest_Metadata.",
        description_ne="वनको पहिचान विवरण (नाम, समूह, ठेगाना, कार्यालय, राष्ट्रिय कोड, योजना वर्ष): एउटा पङ्क्ति। टेम्प्लेट: 07_Forest_Metadata।",
        columns=tuple(
            Column(name, "text", required=name == "forest_name", description_en=en, description_ne=ne)
            for name, en, ne in (
                ("forest_name", "Name of the community forest.", "सामुदायिक वनको नाम।"),
                ("group_name", "Name of the user group.", "उपभोक्ता समूहको नाम।"),
                ("province", "Province.", "प्रदेश।"),
                ("district", "District.", "जिल्ला।"),
                ("palika", "Municipality / rural municipality.", "पालिका।"),
                ("ward", "Ward number.", "वडा नम्बर।"),
                ("division", "Division forest office.", "डिभिजन वन कार्यालय।"),
                ("sub_division", "Sub-division (ilaka) forest office.", "इलाका वन कार्यालय।"),
                ("cf_national_code", "National database code of the community forest.", "सामुदायिक वनको राष्ट्रिय कोड।"),
                ("fy_start", "Plan start fiscal year, e.g. 2083/84.", "योजना सुरु हुने आर्थिक वर्ष, जस्तै २०८३/८४।"),
                ("fy_end", "Plan end fiscal year, e.g. 2092/93.", "योजना अन्त्य हुने आर्थिक वर्ष, जस्तै २०९२/९३।"),
            )
        ),
    )
)


_reg(
    Purpose(
        id="households",
        label_en="Households",
        label_ne="घरधुरी",
        kind="tabular",
        order=50,
        layer_name="households",
        name_aliases=("households", "household", "hh", "घरधुरी", "घरपरिवार"),
        fingerprint_required=("household_head", "ward"),
        description_en=(
            "User-group household records (contains personal data). The full sheet, "
            "with Nepali headers and the land-unit / coordinate options, is produced "
            "by household_info.download_household_template."
        ),
        description_ne=(
            "उपभोक्ता समूहका घरधुरी अभिलेख (व्यक्तिगत विवरण समावेश)। पूर्ण पाना "
            "household_info.download_household_template ले बनाउँछ।"
        ),
        columns=(
            Column(
                "household_head",
                "text",
                required=True,
                aliases=("head", "name", "घरमूली", "घरमुलीको_नाम"),
                description_en="Name of the household head.",
                description_ne="घरमूलीको नाम।",
            ),
            Column(
                "ward",
                "integer",
                required=True,
                minimum=1,
                maximum=33,
                aliases=("ward_no", "वडा", "वडा_नं"),
                description_en="Ward number.",
                description_ne="वडा नम्बर।",
            ),
            Column("settlement", "text", aliases=("tole", "बस्ती", "टोल")),
            Column(
                "members",
                "integer",
                minimum=1,
                aliases=("family_size", "hh_size", "सदस्य"),
            ),
            Column(
                "caste_ethnicity", "text", aliases=("caste", "ethnicity", "जातजाति")
            ),
        ),
        rules=(
            Rule(
                "households.required_columns",
                "error",
                "required_columns",
                "Household data needs a head name and a ward number.",
                "घरधुरी तथ्याङ्कलाई घरमूलीको नाम र वडा नम्बर चाहिन्छ।",
                {"columns": ["household_head", "ward"]},
            ),
            Rule(
                "households.ward_valid",
                "warning",
                "ward_valid",
                "A ward number is outside the range for this forest's district.",
                "वडा नम्बर यस वनको जिल्लाको दायराभन्दा बाहिर छ।",
                {"column": "ward"},
            ),
            Rule(
                "households.dedupe",
                "warning",
                "unique",
                "The same household (head + ward + settlement) appears more than once.",
                "उही घरधुरी (घरमूली + वडा + बस्ती) एकपटकभन्दा बढी देखिन्छ।",
                {"columns": ["household_head", "ward", "settlement"]},
            ),
        ),
    )
)

_reg(
    Purpose(
        id="user_group_boundary",
        label_en="User-group boundary",
        label_ne="उपभोक्ता समूह सिमाना",
        kind="spatial",
        order=60,
        layer_name="user_group_boundary",
        geometry_types=("POLYGON", "MULTIPOLYGON", "POINT", "MULTIPOINT", "LINESTRING"),
        name_aliases=(
            "user_group_boundary",
            "user group boundary",
            "usergroup",
            "settlement_boundary",
            "उपभोक्ता_समूह_सिमाना",
        ),
        geometry_hint="A polygon (or a hull of settlement points) around the households, usually outside the forest.",
        description_en="The settlement catchment that drives household / settlement / land-cover analysis.",
        description_ne="घरधुरी / बस्ती / भू-आवरण विश्लेषण चलाउने बस्ती क्षेत्र।",
        rules=(
            Rule(
                "user_group_boundary.geometry_sane",
                "error",
                "geometry_sane",
                "The user-group boundary must be a valid polygon, line or point set.",
                "उपभोक्ता समूह सिमाना मान्य बहुभुज, रेखा वा बिन्दु समूह हुनुपर्छ।",
                {},
            ),
        ),
    )
)

_reg(
    Purpose(
        id="roads",
        label_en="Roads & trails",
        label_ne="सडक र पदमार्ग",
        kind="spatial",
        order=70,
        layer_name="roads",
        geometry_types=("LINESTRING", "MULTILINESTRING"),
        name_aliases=("roads", "trails", "roads_trails", "paths", "सडक", "पदमार्ग"),
        geometry_hint="Line features.",
        description_en="Roads, trails and tracks in and around the forest.",
        description_ne="वन र वरपरका सडक, पदमार्ग र गोरेटो।",
        columns=(
            Column("name", "text", aliases=("label", "नाम")),
            Column(
                "type",
                "text",
                enum=("road", "trail", "track", "footpath"),
                aliases=("class", "highway", "प्रकार"),
            ),
        ),
        rules=(
            Rule(
                "roads.geometry_type",
                "error",
                "geometry_type",
                "Roads must be line geometry.",
                "सडक रेखा ज्यामिति हुनुपर्छ।",
                {"types": ["LINESTRING", "MULTILINESTRING"]},
            ),
        ),
    )
)

_reg(
    Purpose(
        id="water",
        label_en="Water features",
        label_ne="जल स्रोत",
        kind="spatial",
        order=71,
        layer_name="water",
        geometry_types=(
            "LINESTRING",
            "MULTILINESTRING",
            "POLYGON",
            "MULTIPOLYGON",
            "POINT",
        ),
        name_aliases=(
            "water",
            "rivers",
            "streams",
            "ponds",
            "hydrology",
            "जल_स्रोत",
            "नदी",
            "खोला",
        ),
        geometry_hint="Lines (rivers/streams), polygons (ponds/lakes) or points (springs).",
        description_en="Rivers, streams, ponds, springs.",
        description_ne="नदी, खोला, पोखरी, मूल।",
        columns=(
            Column("name", "text", aliases=("label", "नाम")),
            Column(
                "type",
                "text",
                enum=("river", "stream", "pond", "lake", "spring", "canal"),
                aliases=("class", "प्रकार"),
            ),
        ),
    )
)

_reg(
    Purpose(
        id="activities",
        label_en="Planned activities",
        label_ne="प्रस्तावित क्रियाकलाप",
        kind="spatial_or_tabular",
        order=80,
        layer_name="activities",
        geometry_types=(
            "POINT",
            "LINESTRING",
            "POLYGON",
            "MULTIPOLYGON",
            "MULTILINESTRING",
        ),
        name_aliases=(
            "activities",
            "activity",
            "operations",
            "क्रियाकलाप",
            "प्रस्तावित_क्रियाकलाप",
        ),
        fingerprint_required=("activity", "year"),
        geometry_hint="Points/lines/polygons drawn for operational-plan activities, each with a plan year.",
        description_en="Operational-plan activities and where they happen, by plan year 1–10.",
        description_ne="कार्ययोजनाका क्रियाकलाप र तिनको स्थान, योजना वर्ष १–१० अनुसार।",
        columns=(
            Column(
                "activity",
                "text",
                required=True,
                aliases=("name", "operation", "क्रियाकलाप"),
                description_en="What the activity is (e.g. thinning, plantation, fire line).",
                description_ne="क्रियाकलाप के हो (जस्तै पातलो पार्ने, बृक्षारोपण, आगो रेखा)।",
            ),
            Column(
                "year",
                "integer",
                required=True,
                minimum=1,
                maximum=10,
                aliases=("plan_year", "yr", "वर्ष"),
                description_en="Plan year, 1–10.",
                description_ne="योजना वर्ष, १–१०।",
            ),
            Column(
                "unit",
                "text",
                aliases=("block", "compartment", "ब्लक"),
                description_en="Block/compartment the activity applies to (else resolved by location).",
                description_ne="क्रियाकलाप लागू हुने ब्लक/कम्पार्टमेन्ट (नभए स्थानबाट पत्ता लगाइन्छ)।",
            ),
            Column(
                "kind",
                "text",
                enum=(
                    "plantation_areas",
                    "anr_areas",
                    "nursery_sites",
                    "seed_stands",
                    "roads_trails",
                    "depots",
                    "structures_all",
                    "fire_lines",
                    "patrol_routes",
                    "biodiversity_blocks",
                    "ntfp_zones",
                    "propoor_plots",
                    "ecotourism",
                    "permanent_plots",
                    "monitoring_points",
                ),
                aliases=("feature_kind", "category"),
                description_en="Drawn-feature kind (for the opsmap feature maps).",
                description_ne="कोरिएको सुविधाको प्रकार (opsmap सुविधा नक्साका लागि)।",
            ),
        ),
        rules=(
            Rule(
                "activities.required_columns",
                "error",
                "required_columns",
                "Activities need an activity name and a plan year.",
                "क्रियाकलापलाई क्रियाकलापको नाम र योजना वर्ष चाहिन्छ।",
                {"columns": ["activity", "year"]},
            ),
            Rule(
                "activities.year_range",
                "error",
                "column_range",
                "Plan year must be 1–10.",
                "योजना वर्ष १–१० हुनुपर्छ।",
                {"column": "year", "min": 1, "max": 10},
            ),
            Rule(
                "activities.unit_resolves",
                "warning",
                "resolves_to",
                "The 'unit' value should match a real block/compartment (else resolved by location).",
                "'unit' मान वास्तविक ब्लक/कम्पार्टमेन्टसँग मिल्नुपर्छ (नभए स्थानबाट पत्ता लगाइन्छ)।",
                {"column": "unit", "target": "blocks", "fallback": "point_in_polygon"},
            ),
        ),
    )
)


# ══════════════════════════════════════════════════════════════════════════
# accessors
# ══════════════════════════════════════════════════════════════════════════
def get(purpose_id: str) -> Optional[Purpose]:
    return PURPOSES.get(purpose_id)


def ordered() -> list[Purpose]:
    """All purposes, boundary first (order 0), then by ``order``."""
    return sorted(PURPOSES.values(), key=lambda p: (p.order, p.id))


def spatial() -> list[Purpose]:
    return [p for p in ordered() if p.kind in ("spatial", "spatial_or_tabular")]


def tabular() -> list[Purpose]:
    return [p for p in ordered() if p.kind in ("tabular", "spatial_or_tabular")]


def boundary() -> Purpose:
    """The one purpose that must come first / be present in a bundle."""
    return PURPOSES["forest_boundary"]


def by_layer_name(name: str) -> Optional[Purpose]:
    """Classification signal 1 — match a GeoPackage layer or Excel sheet name
    (case / separator insensitive) to a purpose."""
    key = _norm(name)
    for p in PURPOSES.values():
        if key == _norm(p.layer_name) or any(key == _norm(a) for a in p.name_aliases):
            return p
    return None


def _norm(s: str) -> str:
    return "".join(ch for ch in str(s).lower().strip() if ch.isalnum())


def to_dict() -> dict:
    """Full JSON-serializable schema — for the frontend, an API endpoint, and
    the Workbook generator."""
    return {
        "schema_version": SCHEMA_VERSION,
        "thresholds": {
            "max_area_ha": MAX_AREA_HA,
            "max_builtup_cropland_pct": MAX_BUILTUP_CROPLAND_PCT,
            "pa_non_buffer_tolerance_pct": PA_NON_BUFFER_TOLERANCE_PCT,
            "nepal_outside_tolerance_pct": NEPAL_OUTSIDE_TOLERANCE_PCT,
            "unit_outside_tolerance_m": UNIT_OUTSIDE_TOLERANCE_M,
            "unit_min_coverage_pct": UNIT_MIN_COVERAGE_PCT,
            "tree_dbh_max_cm": TREE_DBH_MAX_CM,
            "tree_height_max_m": TREE_HEIGHT_MAX_M,
        },
        "sub_area_categories": list(SUB_AREA_CATEGORIES),
        "purposes": [p.as_dict() for p in ordered()],
    }


if __name__ == "__main__":  # `python -m app.services.upload.schema`
    import json
    import sys

    blob = json.dumps(to_dict(), ensure_ascii=False, indent=2)
    # stdout may be a cp1252 console on Windows — write UTF-8 bytes directly.
    sys.stdout.buffer.write(blob.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
