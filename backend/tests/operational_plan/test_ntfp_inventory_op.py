"""The NTFP inventory in the operational plan: table_39 and the narrative (``operational_plan/ntfp_inventory_op.py``)."""
from app.services.operational_plan import ntfp_inventory_op as op
from app.services.operational_plan import op_docx_builder as builder
from app.services.operational_plan.section_generators import SECTION_GENERATORS
from app.services.operational_plan.variable_registry import TABLE_ID_ALIAS, get_variable

RESULTS = {
    "plots_in_design": 36, "ivi_parts": 2, "survey": {"pairs_recorded": 20, "pairs_assigned": 84, "weights": 6},
    "species": [
        {"species_key": "a", "label": "ए", "nepali_name": "टिमुर", "scientific_name": "Zanthoxylum armatum", "plots_surveyed": 10, "plots_present": 8,
         "frequency_pct": 80.0, "density_per_ha": 120.5, "ivi": 150.2, "warnings": ["few_plots"],
         "parts": [{"part_group": "ङ", "yield_fresh_kg_ha": 45.0, "yield_dry_kg_ha": 16.5, "stock_fresh_kg": 1800.0, "stock_dry_kg": 660.0,
                    "warnings": ["no_dry_weights"], "price": {"estimated": True}}]},
        {"species_key": "b", "label": "बी", "nepali_name": None, "scientific_name": None, "plots_surveyed": 10, "plots_present": 2,
         "frequency_pct": 20.0, "density_per_ha": 10.0, "ivi": 49.8, "warnings": [], "parts": []},
        {"species_key": "c", "label": "सी", "plots_surveyed": 0, "plots_present": 0, "frequency_pct": None, "density_per_ha": None, "ivi": None, "warnings": ["not_surveyed"], "parts": []},
    ],
}


def test_rows_are_one_per_surveyed_species_and_part_with_devanagari_numbers():
    rows = op.build_rows(RESULTS)
    assert len(rows) == 2                                   # the unsurveyed species has no row
    a, b = rows
    assert a["name"] == "टिमुर (Zanthoxylum armatum)" and a["part"] == "फल र बीज"
    assert a["plots"] == "१० / ८" and a["frequency"] == "८०" and a["density"] == "१२०.५" and a["ivi"] == "१५०.२"
    assert a["yield"] == "४५ / १६.५" and a["stock"] == "१८०० / ६६०"   # the repo formatter drops a trailing .0
    assert "सर्वेक्षण प्लट थोरै" in a["note"] and "सुक्खा तौल छैन" in a["note"] and "मूल्य दर अनुमानित" in a["note"]
    assert b["name"] == "बी" and b["yield"] == "-" and b["part"] == "-"       # no weights yet: dashes, the species still counts
    assert [r["sn"] for r in rows] == ["१", "२"]


def test_the_summary_names_the_highest_importance_values():
    s = op.summary(RESULTS)
    assert (s["species_designed"], s["species_surveyed"], s["plots_recorded"]) == (3, 2, 20)
    assert [t["name"] for t in s["top"]] == ["टिमुर", "बी"]


def test_the_narrative_exists_only_with_a_survey():
    assert op.narrative({"available": False}) is None and op.narrative({}) is None
    text = op.narrative({"available": True, "summary": op.summary(RESULTS)})
    assert "टिमुर" in text and "महत्त्व मूल्य सूचकाङ्क" in text and "२ प्रजाति" in text


def test_the_table_and_the_section_are_registered_everywhere_the_checklist_says():
    assert TABLE_ID_ALIAS["ntfp_inventory"] == "table_39"
    assert get_variable("table:table_39") is not None and get_variable("table:ntfp_inventory") is not None
    assert get_variable("section:ntfp_inventory") is not None
    assert "section:ntfp_inventory" in SECTION_GENERATORS
    assert "table_39" in builder._BUILD_FROM_RAW
    cols = [c for c, _ in builder.NP_HEADERS_BIODIVERSITY["table_39"]]
    assert cols == ["sn", "name", "part", "plots", "frequency", "density", "ivi", "yield", "stock", "note"]
    assert set(cols) == set(op.build_rows(RESULTS)[0])           # every header has a value and every value a header


def test_without_records_the_table_builder_and_the_narrative_say_nothing():
    for raw in ({}, {"ntfp_inventory": {"available": False}}):
        assert builder._BUILD_FROM_RAW["table_39"](raw) == []
        assert SECTION_GENERATORS["section:ntfp_inventory"](raw) is None


def test_with_records_the_builder_returns_the_prepared_rows():
    inv = {"available": True, "table_rows": op.build_rows(RESULTS), "summary": op.summary(RESULTS)}
    assert len(builder._BUILD_FROM_RAW["table_39"]({"ntfp_inventory": inv})) == 2
    assert "टिमुर" in SECTION_GENERATORS["section:ntfp_inventory"]({"ntfp_inventory": inv})
