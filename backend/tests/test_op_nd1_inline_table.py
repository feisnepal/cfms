"""ND-1 (RC1): {{inline_table:N}} is a builder placement instruction, never data.

Before ND-1 `VariableResolver._replacer` had no `inline_table:` pass-through, so
`resolve_for_output` (export, `operational_plans.py:2888`) replaced the token by
the red "डाटा उपलब्ध छैन" marker just before `_add_text_content` could split it
out and place the table — a red paragraph where the table belongs (evidence docx:
12 of its 41 markers). Readiness meanwhile listed `inline_table:0` as
"not a registered variable" (`known=False`), so `ready` could never become true
for a template that uses an inline table.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.operational_plan import no_data
from app.services.operational_plan.plan_readiness import classify_tokens
from app.services.operational_plan.variable_resolver import VariableResolver


def _resolver() -> VariableResolver:
    r = VariableResolver(MagicMock(), "c", SimpleNamespace(plan_metadata={}))
    r._raw_data = {"basic_info": {"language": "NP"}}
    return r


def test_resolve_node_content_keeps_inline_table_tokens_intact():
    out = _resolver().resolve_node_content(
        "पहिलो {{inline_table:0}} दोस्रो {{inline_table:1}} अन्त्य।"
    )
    assert out == "पहिलो {{inline_table:0}} दोस्रो {{inline_table:1}} अन्त्य।"
    assert not no_data.has_marker(out)


def test_unknown_variable_still_prints_no_data():
    # the pass-through must stay narrow: an unregistered *data* key is still loud
    out = _resolver().resolve_node_content("क्षेत्रफल {{definitely_not_registered_xyz}} हे.")
    assert "{{definitely_not_registered_xyz}}" not in out
    assert no_data.has_marker(out)


def test_structural_tokens_still_pass_through():
    src = "{{chart:volume_trend}} {{map:boundary}} {{table:blocks}} {{asset:cf_logo}}"
    assert _resolver().resolve_node_content(src) == src


def test_classify_puts_inline_table_with_the_opaque_tokens():
    values, maps, opaque = classify_tokens(
        [{"title_en": "s", "content": "{{inline_table:0}} {{forest_name}}", "children": []}]
    )
    assert opaque == {"inline_table:0"}
    assert values == {"forest_name"}
    assert maps == set()


def test_plan_readiness_never_reports_inline_table_as_missing():
    # readiness builds `missing` only from the value bucket (plan_readiness.py:227),
    # so the token must sit with the opaque ones — and never block `ready`.
    from app.services.operational_plan.plan_readiness import plan_readiness

    rep = plan_readiness(
        None,
        None,
        None,
        tree=[{"title_en": "s", "content": "{{inline_table:0}}", "children": []}],
    )
    assert rep["missing"] == []
    assert rep["unverified_tokens"] == ["inline_table:0"]
    assert rep["ready"] is True


def test_resolver_then_builder_places_the_table_without_a_marker():
    """The full RC1 chain: resolve_for_output then _add_text_content.

    Old behaviour: the resolver swapped the token for the red marker, the
    builder's split never saw it, and the paragraph carried a red
    "डाटा उपलब्ध छैन" where the table belongs (12 in the evidence docx).
    """
    from docx import Document

    from app.services.operational_plan import op_docx_builder as B

    raw = {"basic_info": {"language": "NP"}}
    resolved = _resolver().resolve_node_content(
        "तालिका यहाँ आउँछ: {{inline_table:0}} यसपछि।"
    )

    doc = Document()
    used = set()
    B._add_text_content(
        doc,
        resolved,
        raw_data=raw,
        inline_tables=[
            {
                "caption": "तालिका १",
                "columns": ["क्र.सं.", "विवरण"],
                "rows": [["१", "काम"]],
            }
        ],
        used_inline=used,
    )

    paras = "\n".join(p.text for p in doc.paragraphs)
    assert "{{" not in paras
    assert not no_data.has_marker(paras)
    assert len(doc.tables) == 1
    assert used == {0}
