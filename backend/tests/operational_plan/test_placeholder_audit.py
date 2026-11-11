"""Fixes found by auditing every placeholder of the Rambhadevi template against real forests."""
from docx import Document

from app.services.operational_plan import op_docx_builder as b
from app.services.operational_plan.variable_resolver import VariableResolver


def test_digits_are_made_devanagari_in_prose_but_not_inside_a_token(monkeypatch):
    seen = []
    monkeypatch.setattr(b, "_add_map_standard", lambda doc, token, *a, **k: seen.append(token))
    doc = Document()
    b._add_text_content(doc, "वर्ष 1984 को नक्सा\n{{map:landcover_1984}}", calculation_id="c", db=object(), raw_data={})
    assert seen == ["landcover_1984"]                                   # was 'landcover_१९८४' -> "Unknown map type"
    assert any("१९८४" in p.text for p in doc.paragraphs)


def test_fiscal_year_text_from_forest_metadata_formats():
    f = VariableResolver._fy_text
    assert f("2083/84") == "२०८३/०८४" and f("२०८३/०८४") == "२०८३/०८४" and f("2083/084") == "२०८३/०८४"
    assert f("") is None and f("n/a") is None


def test_registered_names_the_collector_stores_under_another_key_resolve():
    from app.services.operational_plan.variable_resolver import _KEY_ALIAS

    assert _KEY_ALIAS[("field_inventory", "fi_total_plots")] == "total_sample_plots"
    assert _KEY_ALIAS[("raster_analysis", "landcover_1984_dominant")].endswith("landcover_1984_dominant")


def test_compartment_map_function_has_its_depth_constant():
    import inspect

    from app.services.management_plan_docx import plan_map_service as pm

    assert "DEPTH_SUB" in inspect.getsource(pm._add_compartment_polygons_with_labels).split("DEPTH_SUB")[0] + "import DEPTH_SUB" \
        and "import DEPTH_SUB" in inspect.getsource(pm._add_compartment_polygons_with_labels)
