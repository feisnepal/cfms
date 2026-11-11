"""ND-7 (DG5): a list token that resolves to ``[]`` prints a grey "सूची खाली छ" note, never the red
"No data" and never a raw ``{{token}}`` (owner decision 2026-10-18).

An empty list is a legitimate state — the owner may simply not have designated any protected trees yet —
so it must not read as missing data, and it must not block the plan. Before ND-7 the empty-list branch in
``_add_text_content`` printed ``_no_data.add_paragraph`` (red "डाटा उपलब्ध छैन"), the same alarm used for a
figure that could not be found.
"""
from docx import Document

from app.services.operational_plan import no_data
from app.services.operational_plan import op_docx_builder as B


def _runs(doc):
    return [r for p in doc.paragraphs for r in p.runs]


def _raw(language="NP"):
    return {
        "basic_info": {"language": language},
        "committees": {"user_committee": {"members": []}},
    }


def test_empty_list_label_is_nepali_by_default_and_english_for_en_plans():
    assert no_data.empty_list_label(None) == "सूची खाली छ"
    assert no_data.empty_list_label("NP") == no_data.EMPTY_LIST_NE
    assert no_data.empty_list_label("EN") == "List is empty"


def test_empty_list_note_is_grey_and_never_red():
    doc = Document()
    no_data.empty_list_paragraph(doc)
    (run,) = _runs(doc)
    assert run.text == "सूची खाली छ"
    assert str(run.font.color.rgb) == "787878"
    assert not run.font.bold


def test_body_token_resolving_to_empty_list_prints_the_grey_note_not_no_data():
    doc = Document()
    B._add_text_content(doc, "समिति सदस्य:\n{{uc_members}}", raw_data=_raw())
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "{{uc_members}}" not in text
    assert "सूची खाली छ" in text
    assert "डाटा उपलब्ध छैन" not in text
    assert not any(r.text == "डाटा उपलब्ध छैन" for r in _runs(doc))


def test_html_preview_shows_the_same_grey_note_for_an_empty_list():
    html = B._render_html_list_vars("X {{uc_members}} Y", _raw())
    assert "सूची खाली छ" in html
    assert 'class="empty-list"' in html
    assert '#787878' in html
    assert "{{" not in html
    assert "no-data" not in html
