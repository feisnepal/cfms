"""Template footer text, page-number formats and landscape sections in the OP docx builder."""
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn

from app.services.operational_plan import op_docx_builder as b
from app.services.operational_plan.tree_models import TreeNode


class _Resolver:
    def resolve_node_content(self, content):
        return content.replace("{{user_group_name}}", "रम्भादेवी").replace("{{op_preparation_year}}", "२०८२")


def _pg(section):
    el = section._sectPr.find(qn("w:pgNumType"))
    return None if el is None else (el.get(qn("w:fmt")), el.get(qn("w:start")))


def test_footer_text_is_resolved_and_has_a_page_field_and_no_footer_on_the_cover():
    doc = Document()
    cover = TreeNode(is_cover=True, cover_meta={
        "footer_text": "श्री {{user_group_name}} सामुदायिक वनको वन व्यवस्थापन कार्ययोजना – {{op_preparation_year}}",
        "front_page_format": "lowerRoman"})
    b._apply_document_layout(doc, cover, _Resolver())
    sec = doc.sections[0]
    assert sec.different_first_page_header_footer is True
    xml = sec.footer._element.xml
    assert "रम्भादेवी" in xml and "२०८२" in xml and "{{" not in xml
    assert " PAGE " in xml and "w:tab" in xml
    assert _pg(sec) == ("lowerRoman", "1")
    assert not any(p.text.strip() for p in sec.first_page_footer.paragraphs)   # cover page: empty


def test_no_cover_meta_changes_nothing():
    doc = Document()
    b._apply_document_layout(doc, None, _Resolver())
    assert _pg(doc.sections[0]) is None and not doc.sections[0].different_first_page_header_footer


def test_nodes_start_sections_with_their_own_numbering_and_landscape_returns_to_portrait():
    doc = Document()
    front = TreeNode(title_ne="स्वीकृति", page_format="upperRoman", restart_pages=True)
    chap = TreeNode(title_ne="परिच्छेद १", page_format="decimal", restart_pages=True)
    wide = TreeNode(title_ne="चौडा तालिका", landscape=True)
    plain = TreeNode(title_ne="सामान्य")
    assert b._start_layout_section(doc, front) is True
    assert b._start_layout_section(doc, chap) is True
    assert b._start_layout_section(doc, plain) is False       # no flags: the usual page break instead
    assert b._start_layout_section(doc, wide) is True
    doc._op_pending_portrait = True                     # what _walk_tree sets after a landscape node
    assert b._start_layout_section(doc, wide) is True   # another landscape node: no portrait page in between
    doc._op_pending_portrait = True
    assert b._start_layout_section(doc, plain) is True  # first non-landscape node resumes portrait
    assert b._start_layout_section(doc, plain) is False
    secs = doc.sections
    assert [_pg(s) for s in secs[1:3]] == [("upperRoman", "1"), ("decimal", "1")]
    assert secs[3].orientation == WD_ORIENT.LANDSCAPE and secs[3].page_width > secs[3].page_height
    assert secs[4].orientation == WD_ORIENT.LANDSCAPE
    assert secs[5].orientation == WD_ORIENT.PORTRAIT and secs[5].page_width < secs[5].page_height
    assert len(secs) == 6


def test_verification_stamp_keeps_a_template_footer_and_does_not_repeat_on_linked_sections():
    doc = Document()
    cover = TreeNode(is_cover=True, cover_meta={"footer_text": "शीर्षक"})
    b._apply_document_layout(doc, cover, _Resolver())
    b._start_layout_section(doc, TreeNode(page_format="decimal", restart_pages=True))
    b._stamp_verification_footer(doc, "ABCD-1234")
    first = [p.text for p in doc.sections[0].footer.paragraphs]
    assert any("शीर्षक" in t for t in first) and any("ABCD-1234" in t for t in first)
    assert sum("ABCD-1234" in p.text for p in doc.sections[0].footer.paragraphs) == 1
    assert any("ABCD-1234" in p.text for p in doc.sections[0].first_page_footer.paragraphs)   # the cover is stamped too
