"""'No data' is one thing, in one place, red and bold (owner rule 2026-10-16)."""
from docx import Document

from app.services.operational_plan import no_data
from app.services.operational_plan.op_docx_builder import _add_text_content, _resolve_var_text


def _runs(doc):
    return [r for p in doc.paragraphs for r in p.runs]


def test_label_follows_plan_language():
    assert no_data.label("EN") == "No data"
    assert no_data.label("NP") == no_data.NO_DATA_NE
    assert no_data.label(None) == no_data.NO_DATA_NE


def test_marked_text_keeps_readable_words_and_round_trips():
    text = "क्षेत्रफल " + no_data.marked("EN") + " हे."
    assert "No data" in no_data.strip(text)
    assert no_data.split(text) == [("क्षेत्रफल ", False), ("No data", True), (" हे.", False)]


def test_add_runs_is_red_bold_only_for_the_no_data_part():
    doc = Document()
    no_data.add_runs(doc.add_paragraph(), "a " + no_data.marked("EN") + " b")
    plain, nd, tail = _runs(doc)
    assert nd.text == "No data" and nd.font.bold and str(nd.font.color.rgb) == "C80000"
    assert not plain.font.bold and not tail.font.bold


def test_standalone_paragraph_is_red_bold_with_name():
    doc = Document()
    no_data.set_language("EN")
    no_data.add_paragraph(doc, what="forest type")
    first, extra = _runs(doc)
    assert first.text == "No data" and first.font.bold and str(first.font.color.rgb) == "C80000"
    assert "forest type" in extra.text
    no_data.set_language(None)


def test_variable_with_no_value_prints_no_data_not_blank():
    out = _resolve_var_text("Area: {{does_not_exist_in_raw}} ha", {"basic_info": {"language": "EN"}})
    assert "No data" in no_data.strip(out)


def test_text_content_writes_the_marker_as_red_bold_run():
    doc = Document()
    _add_text_content(doc, "Total " + no_data.marked("EN") + " ha")
    nd = [r for r in _runs(doc) if r.text == "No data"]
    assert nd and nd[0].font.bold


def test_html_marker_becomes_red_bold_span():
    html = no_data.to_html("x " + no_data.marked("EN"))
    assert 'class="no-data"' in html and "font-weight:700" in html and "No data" in html


# ── found by testing a real exported document (2026-10-18) ───────────────────────────────────────────────

def test_a_table_caption_never_prints_its_unit_placeholder():
    from app.services.operational_plan import op_docx_builder as b

    token = b._UNIT_WORDS.set({"unit_label_np": "कम्पार्टमेन्ट"})
    try:
        assert b._caption("{{unit_label_np}} अनुसार वार्षिक माटो क्षय") == "कम्पार्टमेन्ट अनुसार वार्षिक माटो क्षय"
        assert "{{" not in b._caption("{{unit_label_np}} x")
    finally:
        b._UNIT_WORDS.reset(token)


def test_a_cover_page_list_variable_with_no_rows_prints_no_data_not_the_raw_token():
    from docx import Document
    from app.services.operational_plan import op_docx_builder as b
    from app.services.operational_plan.tree_models import TreeNode

    cover = TreeNode(id="n_cover", type="preamble", title_ne="", title_en="Cover", content_type="richtext",
                     content="Committee:\n{{uc_members}}", is_cover=True, children=[])
    doc = Document()
    b._add_cover_node_page(doc, cover, {"committees": {"user_committee": {"members": []}}})
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "{{" not in text and "सूची खाली छ" in text and "डाटा उपलब्ध छैन" not in text


def test_readiness_reports_an_empty_list_separately_without_blocking_ready():
    """ND-7 (owner 2026-10-18): an empty list prints a grey note, not "No data", so it is reported in
    its own non-blocking bucket and does not make the plan un-ready."""
    import importlib

    pr = importlib.import_module("app.services.operational_plan.plan_readiness")

    class _R:
        def __init__(self, *a, **k): pass
        def resolve_keys(self, keys): return {k: ([] if k == "uc_members" else "x") for k in keys}

    import app.services.operational_plan.variable_resolver as vr
    orig = vr.VariableResolver
    vr.VariableResolver = _R
    try:
        out = pr.plan_readiness(None, None, None, tree=[{"content": "{{uc_members}} {{forest_name}}"}])
    finally:
        vr.VariableResolver = orig
    assert out["missing"] == []
    assert [m["key"] for m in out["empty_lists"]] == ["uc_members"]
    assert out["ready"] is True


def test_a_section_full_token_is_available_when_its_narrative_exists():
    """"section:x:full" is built from the section generator, not resolved as a plain variable (found on a real export)."""
    import importlib

    pr = importlib.import_module("app.services.operational_plan.plan_readiness")

    class _R:
        def __init__(self, *a, **k): pass
        def resolve_keys(self, keys): return {k: None for k in keys}
        def get_raw_data(self): return {"section_generators": {"section:forest_type": "text", "section:fire_loss": ""}}

    import app.services.operational_plan.variable_resolver as vr
    orig = vr.VariableResolver
    vr.VariableResolver = _R
    try:
        out = pr.plan_readiness(None, None, None, tree=[{"content": "{{section:forest_type:full}} {{section:fire_loss:full}}"}])
    finally:
        vr.VariableResolver = orig
    assert [m["key"] for m in out["missing"]] == ["section:fire_loss:full"]


def test_a_point_size_is_applied_once_not_twice():
    """Found on a real export: add_runs turned Pt(11) into Pt(Pt(11)) (a Length is an int), a font size of ~140,000 pt that Word
    draws as giant glyphs - the document looked like black boxes with no text."""
    from docx import Document
    from docx.shared import Pt
    from app.services.operational_plan import no_data

    doc = Document()
    p = doc.add_paragraph()
    no_data.add_runs(p, "plain text " + no_data.marked("EN"), size=Pt(11))
    q = doc.add_paragraph()
    no_data.add_runs(q, "plain number", size=12)
    sizes = [r.font.size for r in p.runs] + [r.font.size for r in q.runs]
    assert sizes[:-1] == [Pt(11)] * (len(sizes) - 1) and sizes[-1] == Pt(12)
    xml = doc.element.xml
    import re
    assert [int(v) for v in re.findall(r'<w:sz w:val="(\d+)"', xml)] and max(int(v) for v in re.findall(r'<w:sz w:val="(\d+)"', xml)) <= 24
