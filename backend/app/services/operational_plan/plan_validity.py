"""The "check my document" pass for an edited plan (owner decision 2026-10-16: users may change structure, so the system
must say when a change would leave a hole).

It is the template gate (``template_validation.validate_template``: unknown variables, charts/tables/maps with no type or an
unknown one, empty sections, duplicate ids, too-deep nesting) run on the plan's document, plus one check the gate does not
make: a variable that was typed wrongly. A ``{{ forest_name }}`` with spaces, a lone ``{{`` or a ``{{name}`` with one brace
is not a token to the resolver, so it would print as plain text in the finished plan. Hidden and removed sections are not
printed, so nothing in them is reported.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from .template_validation import validate_template

# checks the template gate makes for a template that is about to be published; they say nothing about a person's own plan
_TEMPLATE_ONLY = frozenset({
    "description_short", "description_too_short", "kind_required", "unknown_plan_kind", "below_min_sections", "no_toc_node",
})
_VALID_TOKEN = re.compile(r"\{\{\w+(?::\w+)*\}\}")


def _printed(nodes: List[dict]) -> List[dict]:
    out: List[dict] = []
    for n in nodes or []:
        if n.get("deleted") or n.get("hidden_in_export"):
            continue
        copy = dict(n)
        copy["children"] = _printed(n.get("children") or [])
        out.append(copy)
    return out


def _walk(nodes: List[dict]):
    for n in nodes or []:
        yield n
        yield from _walk(n.get("children") or [])


def broken_tokens(content: str) -> List[str]:
    """Pieces of ``content`` that look like a variable but are not one the resolver understands."""
    rest = _VALID_TOKEN.sub("", content or "")
    found = re.findall(r"\{\{[^{}]{0,60}\}?\}?|\{[^{}\s]{1,60}\}\}|\{\{|\}\}", rest)
    return [f for f in found if f]


def plan_validity(db: Session, tree: List[dict]) -> Dict[str, Any]:
    """``{ok, errors, warnings}``; each issue carries ``title`` (the section it is in) next to the gate's own fields."""
    shown = _printed(tree)
    result = validate_template(db, shown, plan_kind=None, for_publish=False)
    errors = [i for i in result.get("errors", []) if i.get("code") not in _TEMPLATE_ONLY]
    warnings = [i for i in result.get("warnings", []) if i.get("code") not in _TEMPLATE_ONLY]

    titles: Dict[str, str] = {}
    for n in _walk(shown):
        titles[n.get("id") or ""] = (n.get("title_en") or n.get("title_ne") or "").strip()
        for bit in broken_tokens(n.get("content") or "")[:5]:
            errors.append({
                "severity": "error",
                "code": "broken_token",
                "message": f"'{bit}' looks like a variable but is not written correctly, so it will print as plain text.",
                "node_id": n.get("id"),
                "token": bit,
            })
    for issue in errors + warnings:
        issue["title"] = titles.get(issue.get("node_id") or "", "")
    return {"ok": not errors, "errors": errors, "warnings": warnings}
