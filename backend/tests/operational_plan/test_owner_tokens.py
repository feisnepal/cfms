"""Variables the owner tried in the system template and found not working (2026-10-17):

  {{landcover_1984_percentages}} / {{section:land_cover_1984:full}}  -- "producing wrong values" (they printed nothing)
  {{map:nasa_forest_2020}}                                           -- not a known map
  {{table:ntfp}} / {{section:ntfp}}                                  -- no such table or narrative
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from docx import Document

from app.core.ntfp import ntfp_species
from app.services.operational_plan import op_docx_builder as B
from app.services.operational_plan.section_generators import generate_land_cover_1984, generate_ntfp
from app.services.operational_plan.template_validation import validate_template
from app.services.operational_plan.variable_resolver import VariableResolver, format_breakdown


def _resolver(raw):
    r = VariableResolver(MagicMock(), "c", SimpleNamespace(plan_metadata={}))
    r._raw_data = raw
    return r


HIST = {
    "landcover_1984_dominant": "Forest",
    "landcover_1984_percentages": {"Forest": 96.09, "Cultivated": 3.81, "Barren / Rock": 0.1},
    "landcover_1984_area_ha": {"Forest": 480.45, "Cultivated": 19.05, "Barren / Rock": 0.5},
}
RAW = {"raster_analysis": {"landcover_historical": HIST}, "basic_info": {"language": "NP"}}


# -- 1984 land use ---------------------------------------------------------------

def test_breakdown_is_one_line_largest_first_in_nepali_labels_with_devanagari_digits():
    text = format_breakdown(HIST["landcover_1984_percentages"], "landcover_1984_percentages")
    assert text.startswith("वन ९६.०९%") and "खेतीयोग्य ३.८१%" in text and "बाँझो / चट्टान ०.१%" in text
    assert text.index("वन") < text.index("खेतीयोग्य")


def test_area_breakdown_carries_hectares_and_other_dicts_are_left_alone():
    assert "हे." in format_breakdown(HIST["landcover_1984_area_ha"], "landcover_1984_area_ha")
    assert format_breakdown({"a": {"nested": 1}}, "x") is None
    assert format_breakdown({}, "x") is None


def test_the_percentages_variable_resolves_inside_a_sentence():
    out = _resolver(RAW).resolve_node_content("सन् १९८४ मा: {{landcover_1984_percentages}}।")
    assert "वन ९६.०९%" in out and "{{" not in out


def test_dominant_1984_resolves_from_the_historical_block():
    out = _resolver(RAW).resolve_node_content("{{landcover_1984_dominant}}")
    assert out == "Forest"


def test_the_1984_narrative_names_the_classes_and_areas_and_is_none_without_data():
    text = generate_land_cover_1984(RAW)
    assert "सन् १९८४" in text and "वन ९६.०९%" in text and "४८०.४५ हेक्टर" in text
    assert "वन" in text and "खेतीयोग्य" in text and "हेक्टर" in text
    assert generate_land_cover_1984({"raster_analysis": {}}) is None
    assert generate_land_cover_1984({"raster_analysis": {"landcover_historical": {"landcover_1984_percentages": {}}}}) is None


def test_the_full_section_prints_a_heading_and_the_narrative():
    raw = {**RAW, "section_generators": {"section:land_cover_1984": generate_land_cover_1984(RAW)}}
    doc = Document()
    B._add_section_full_docx(doc, "section:land_cover_1984:full", raw)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "सन् १९८४ को भू-उपयोग" in text and "त्यस बखतको भू-उपयोग" in text


# -- the NASA forest quality map ---------------------------------------------------

def test_nasa_forest_2020_is_a_known_map_drawn_by_the_thematic_nasa_quality_map(monkeypatch):
    called = {}
    monkeypatch.setattr(B, "_add_thematic_map_docx", lambda doc, key, *a, **k: called.setdefault("key", key))
    B._add_map_standard(Document(), "nasa_forest_2020", "c", MagicMock())
    assert called["key"] == "thememap:zone__nasa_quality_dominant"
    from app.services.operational_plan.thematic_map_spec import LEGACY_MAP_META

    assert "map:nasa_forest_2020" in LEGACY_MAP_META


# -- NTFP (the regulation's designated list, Schedule-7) ----------------------------------

VEG = [
    {"name": "टिमुर", "scientific_name": "Zanthoxylum armatum", "sub_category": "Tree", "primary_use": "Spice", "abundance": "common"},
    {"name": "सल्ला", "scientific_name": "Pinus roxburghii", "sub_category": "Tree", "primary_use": "Timber", "abundance": "abundant"},
    {"name": "साल", "scientific_name": "Shorea robusta", "sub_category": "Tree", "primary_use": "Timber", "abundance": "abundant"},
    {"name": "बनमारा", "scientific_name": "Chromolaena odorata", "sub_category": "Invasive Plant", "primary_use": "Invasive", "abundance": "rare"},
    {"name": "खुर्सानी", "scientific_name": "Capsicum annuum", "sub_category": "Vegetable", "primary_use": "Vegetable", "abundance": ""},
]


def test_only_species_on_the_designated_list_are_ntfp():
    rows = ntfp_species(VEG)
    # Timur is listed (fruit), Chir pine is listed (Pinus spp.: bark, resin; P. roxburghii: seed), Sal is listed for its seed and resin;
    # an invasive weed and a garden chilli are not listed, whatever their recorded use
    assert [r["name"] for r in rows] == ["टिमुर", "सल्ला", "साल"]
    assert "Capsicum annuum" not in [r["scientific_name"] for r in rows]


def test_a_species_listed_for_several_parts_shows_each_part_and_price():
    pine = ntfp_species([VEG[1]])[0]
    assert pine["parts"] == "फल र बीज, बोक्रा, गम, रेजिन, लोहावन"
    assert "फल र बीज रु. २००" in pine["price_text"] and "बोक्रा रु. २" in pine["price_text"] and "रु. १२" in pine["price_text"]


def test_the_ntfp_table_rows_and_narrative():
    raw = {"biodiversity": {"available": True, "vegetation": VEG}}
    rows = B._build_ntfp_rows(raw)
    assert [r["sn"] for r in rows] == [1, 2, 3] and rows[0]["parts"] == "फल र बीज" and rows[0]["price_text"] == "फल र बीज रु. १०"
    assert B._BUILD_FROM_RAW["table_38"] is B._build_ntfp_rows
    text = generate_ntfp(raw)
    assert "३ प्रजाति" in text and "अनुसूची-७" in text
    assert B._build_ntfp_rows({"biodiversity": {"available": False}}) == []
    assert generate_ntfp({"biodiversity": {"available": True, "vegetation": [VEG[3], VEG[4]]}}) is None


def test_ntfp_is_an_alias_of_a_registered_table():
    from app.services.operational_plan.variable_registry import TABLE_ID_ALIAS, VARIABLE_REGISTRY

    assert TABLE_ID_ALIAS["ntfp"] == "table_38" and "table:table_38" in VARIABLE_REGISTRY and "table:ntfp" in VARIABLE_REGISTRY


# -- all five tokens are now known to the plan check -------------------------------

def test_the_owners_five_tokens_are_known_variables():
    tree = [{"id": "n", "type": "section", "title_en": "T", "title_ne": "T", "content_type": "richtext", "children": [],
             "content": "{{section:land_cover_1984:full}} {{landcover_1984_percentages}} {{section:land_cover_1984}} "
                        "{{map:nasa_forest_2020}} {{table:ntfp}} {{section:ntfp}}"}]
    result = validate_template(MagicMock(), tree, plan_kind=None, for_publish=False)
    assert [e for e in result["errors"] if e["code"] == "unknown_token"] == []
