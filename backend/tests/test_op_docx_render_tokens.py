"""An unrenderable map token must never be printed verbatim into the report.

Reported by the owner: the user-group map appeared in the PREVIEW but the EXPORT
contained the literal text ``{{map:usergroup}}``.

The cause was not the map renderer - ``usergroup`` is a known layer and
``_add_map_standard`` handles it. It was the fallthrough. ``_add_text_content``
dispatches ``{{map:...}}`` only when it is its own part AND ``calculation_id`` and
``db`` are both present; otherwise it falls through to the generic variable
resolver, and that resolver *deliberately* leaves render tokens alone
(``_resolve_var_text`` returns the match verbatim for ``map:``/``chart:``/
``table:``). So the raw token was written into the DOCX.

That is the worst class of bug in a statutory report: no error, the document
opens normally, the section is simply empty except for a placeholder that a
reader has to recognise as a failure. The preview renders because it is a
different code path entirely, which is exactly why the two disagreed.

The test pins the property rather than the fix: whatever the reason a map cannot
be drawn, the output must SAY SO and must not contain the token.
"""

from __future__ import annotations

import re

import pytest

from app.services.operational_plan.op_docx_builder import _add_text_content

TOKEN = re.compile(r"\{\{(?:chart|map|thememap|opsmap|table):\w+\}\}")


def _doc_text(doc) -> str:
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                parts.extend(p.text for p in cell.paragraphs)
    return "\n".join(parts)


class TestRenderTokensAreNeverPrintedVerbatim:
    def test_a_map_token_with_no_calculation_context_is_reported(self):
        """The reported case: no calculation_id, so nothing can be drawn."""
        from docx import Document

        doc = Document()
        _add_text_content(doc, "User group area\n\n{{map:usergroup}}\n")

        text = _doc_text(doc)
        assert not TOKEN.search(text), (
            f"a raw render token reached the document: {text!r}"
        )
        from app.services.operational_plan import no_data

        assert no_data.NO_DATA_NE in text, (
            f"the failure must be visible as 'No data', got: {text!r}"
        )
        flagged = [r for p in doc.paragraphs for r in p.runs if r.text == no_data.NO_DATA_NE]
        assert flagged and flagged[0].font.bold, "'No data' must be bold so the user can find it"

    def test_the_report_names_the_reason(self, caplog):
        """The reader sees 'No data'; the reason goes to the log so the next export still diagnoses itself."""
        import logging

        from docx import Document

        from app.services.operational_plan import no_data

        doc = Document()
        with caplog.at_level(logging.WARNING):
            _add_text_content(doc, "{{map:usergroup}}")

        assert no_data.NO_DATA_NE in _doc_text(doc)
        # And the log says WHY, rather than just that something went wrong.
        assert "calculation" in caplog.text.lower(), caplog.text

    @pytest.mark.parametrize(
        "token",
        [
            "{{map:usergroup}}",
            "{{map:boundary}}",
            "{{thememap:forest}}",
            "{{chart:biomass}}",
            "{{table:fieldinventory}}",
        ],
    )
    def test_every_render_token_kind_is_guarded(self, token):
        from docx import Document

        doc = Document()
        _add_text_content(doc, f"before\n\n{token}\n\nafter")

        text = _doc_text(doc)
        assert not TOKEN.search(text), f"{token} reached the document verbatim"
        assert "before" in text and "after" in text, (
            "the surrounding prose must survive the failure"
        )

    def test_ordinary_prose_is_untouched(self):
        from docx import Document

        doc = Document()
        _add_text_content(doc, "This forest covers twelve hectares in total.")
        text = _doc_text(doc)
        # Note: _fix() localises numerals, so the digits are Devanagari in the
        # output. Assert the prose survived, not the ASCII spelling.
        assert "twelve hectares in total" in text
        assert "not rendered" not in text
