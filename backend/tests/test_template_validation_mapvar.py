"""template_validation advisory for thememap:/opsmap: map variables (P4 / §3.9.1).

A 🔴 (capability-not-in-system) map variable → a *warning*, not an error;
a real, buildable spec → nothing; an unknown spec → a warning.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.operational_plan.template_validation import validate_template  # noqa: E402


def _tree(*content_nodes):
    # a minimal valid tree: one cover section holding the given content
    return [
        {
            "id": "cover", "type": "section", "content_type": "richtext",
            "title_ne": "आवरण", "title_en": "Cover", "is_cover": True,
            "content": "", "children": list(content_nodes),
        }
    ]


def _warn_codes(res):
    return {w["code"] for w in res["warnings"]}


def test_real_thememap_token_raises_no_warning_or_error(db):
    tree = _tree({
        "id": "n1", "type": "subsection", "content_type": "richtext",
        "title_ne": "मौज्दात", "title_en": "Stock",
        "content": "{{thememap:unit__growing_stock}}", "children": [],
    })
    res = validate_template(db, tree)
    assert "unknown_token" not in {e["code"] for e in res["errors"]}
    assert "map_variable_not_available" not in _warn_codes(res)


def test_unknown_thememap_token_warns_not_errors(db):
    tree = _tree({
        "id": "n1", "type": "subsection", "content_type": "richtext",
        "title_ne": "x", "title_en": "x",
        "content": "{{thememap:unit__does_not_exist}}", "children": [],
    })
    res = validate_template(db, tree)
    assert "map_variable_unknown" in _warn_codes(res)
    assert "unknown_token" not in {e["code"] for e in res["errors"]}


def test_map_node_with_thememap_type_is_checked(db):
    tree = _tree({
        "id": "m1", "type": "subsection", "content_type": "map",
        "title_ne": "नक्सा", "title_en": "Map",
        "map_type": "thememap:unit__carbon", "content": "", "children": [],
    })
    res = validate_template(db, tree)
    assert "map_type_unknown" not in _warn_codes(res)  # not treated as a legacy map:
