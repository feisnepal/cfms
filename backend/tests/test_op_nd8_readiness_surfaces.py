"""ND-8 (guard-rail): readiness must see every surface the document renders.

Before ND-8 :func:`plan_readiness._iter_content` walked only ``content``, so a
``{{token}}`` that lived in a static-table cell, an ``inline_tables`` cell or a
node title was invisible to the readiness report even though
``op_docx_builder`` printed it (cells through ``_resolve_var_text``, ND-2). A
plan could therefore read "ready" while the document carried a cell that
rendered nothing.

The gate: a fixture plan whose only failure is a cell must be reported
``missing``, and the ``{{inline_table:N}}`` placement token must never be
reported as a value (it is builder furniture, not data — ND-1).
"""
from __future__ import annotations

from types import SimpleNamespace

from app.services.operational_plan.plan_readiness import classify_tokens, plan_readiness


def _node(**fields):
    return {"children": [], **fields}


class _StubResolver:
    """Mirrors the real contract: only keys in the map come back."""

    values: dict = {}

    def __init__(self, db, calculation_id, plan):
        pass

    def resolve_keys(self, keys):
        return {k: self.values.get(k) for k in keys if k in self.values}


def _stub(monkeypatch, values):
    import app.services.operational_plan.variable_resolver as vr

    class _R(_StubResolver):
        pass

    _R.values = values
    monkeypatch.setattr(vr, "VariableResolver", _R)


def test_classify_walks_static_table_and_inline_tables_cells():
    values, maps, opaque = classify_tokens(
        [
            _node(
                content="body {{a}}",
                static_table={"columns": ["x"], "rows": [["{{b}}", "lit"]]},
                inline_tables=[{"caption": "{{c}}", "rows": [["{{thememap:m}}"]]}],
            )
        ]
    )
    assert values == {"a", "b", "c"}
    assert maps == {"thememap:m"}
    assert opaque == set()


def test_classify_walks_title_tokens():
    values, maps, _opaque = classify_tokens(
        [_node(title_ne="{{opsmap:unit__silviculture_year}}", title_en="{{d}}")]
    )
    assert values == {"d"}
    assert maps == {"opsmap:unit__silviculture_year"}


def test_cell_only_failure_is_reported_missing(monkeypatch):
    """Gate: the plan's only failure is inside a cell -> readiness reports it."""
    _stub(monkeypatch, {"cell_var": None})
    tree = [_node(content="कोही चल", static_table={"rows": [["{{cell_var}}"]]})]
    out = plan_readiness(None, None, None, tree=tree)
    assert [m["key"] for m in out["missing"]] == ["cell_var"]
    assert out["missing"][0]["known"] is True
    assert out["ready"] is False


def test_inline_table_never_reported_as_a_value(monkeypatch):
    """Gate: the placement token is opaque furniture, never a missing value."""
    _stub(monkeypatch, {})
    tree = [
        _node(
            content="तालिका {{inline_table:0}}",
            inline_tables=[{"caption": "तालिका १", "rows": [["स्थिर"]]}],
        )
    ]
    out = plan_readiness(None, None, None, tree=tree)
    assert out["missing"] == []
    assert out["unverified_tokens"] == ["inline_table:0"]
    assert out["ready"] is True


def test_opsmap_silviculture_year_is_a_known_map_spec():
    """ND-8b: the token is a *known* opsmap spec (not an unregistered variable)."""
    from app.services.operational_plan.thematic_map_spec import resolve_spec

    specced = "opsmap:unit__silviculture_year"
    values, maps, _opaque = classify_tokens([_node(content="{{" + specced + "}}")])
    assert values == set()
    assert maps == {specced}

    spec = resolve_spec(specced)
    assert spec is not None
    assert list(spec.requires) == ["proposed_activities"]
