"""Branch coverage for OP document build/footer paths (H4.2).

The full `build_op_document`/`export_operational_plan` flow is heavy, so the
verification-footer body and the stamp-on-save path are exercised directly on
the builder with its expensive helpers stubbed out. This covers the code that
stamps every page footer with the minted verification code.
"""
from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

from docx import Document

from app.services.operational_plan import op_docx_builder as mod


class _StubResolver:
    def get_raw_data(self):
        return {}


def test_stamp_verification_footer_writes_bilingual_text(monkeypatch):
    """The real footer-stamp body runs: footer access, paragraph, bilingual
    text, and per-run font sizing."""
    doc = Document()
    mod._stamp_verification_footer(doc, "CDE-1234")
    footers = [s.footer for s in doc.sections]
    assert footers, "document should have at least one section footer"
    text = "".join(p.text for f in footers for p in f.paragraphs)
    assert "CDE-1234" in text
    assert "प्रमाणीकरण" in text


def test_build_op_document_stamps_footer_when_code_present(monkeypatch):
    """build_op_document calls _stamp_verification_footer when a code is
    passed, and returns a valid BytesIO byte stream."""
    for name in ("_add_cover_page", "_add_toc_field", "_build_table_cache",
                 "_build_calc_cache", "_walk_tree"):
        monkeypatch.setattr(mod, name, MagicMock(return_value=None))
    monkeypatch.setattr(mod, "_build_calc_cache", MagicMock(return_value={}))
    monkeypatch.setattr(mod, "_build_table_cache", MagicMock(return_value={}))

    stamped = MagicMock()
    monkeypatch.setattr(mod, "_stamp_verification_footer", stamped)

    buffer = mod.build_op_document(
        plan={"plan_metadata": {}},
        tree=[],
        resolver=_StubResolver(),
        calculation_id="00000000-0000-0000-0000-0000000000aa",
        db=None,
        verification_code="ABC-999",
    )
    assert isinstance(buffer, BytesIO)
    stamped.assert_called_once()
    assert buffer.getvalue() != b""


def test_build_op_document_skips_stamp_when_no_code(monkeypatch):
    """Without a verification code the footer is not stamped (3764 branch is
    not taken) but the build still succeeds."""
    for name in ("_add_cover_page", "_add_toc_field", "_build_table_cache",
                 "_build_calc_cache", "_walk_tree"):
        monkeypatch.setattr(mod, name, MagicMock(return_value=None))
    monkeypatch.setattr(mod, "_build_calc_cache", MagicMock(return_value={}))
    monkeypatch.setattr(mod, "_build_table_cache", MagicMock(return_value={}))
    stamped = MagicMock()
    monkeypatch.setattr(mod, "_stamp_verification_footer", stamped)

    buffer = mod.build_op_document(
        plan={"plan_metadata": {}},
        tree=[],
        resolver=_StubResolver(),
        calculation_id="00000000-0000-0000-0000-0000000000aa",
        db=None,
        verification_code=None,
    )
    assert isinstance(buffer, BytesIO)
    stamped.assert_not_called()
