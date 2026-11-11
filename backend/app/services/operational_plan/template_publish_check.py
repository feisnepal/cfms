"""The check a template passes before its author shares it (owner decision 2026-10-16: anyone signed in may publish).

Errors stop the sharing; warnings are shown and the author decides.

* Structure: the template gate (unknown variables, charts/tables/maps with no type, duplicate ids...) *without* the
  rules for an Official plan kind (required chapters), because users may reshape their own templates.
* A short description (so others can tell what it is for).
* **No forest's own name.** The author's forests (and their user groups) are looked up and their names must not appear in the
  text: a name there means a figure from one forest is about to be shown to everyone. This is the check that matters most.
* Numbers typed by hand in the text are only a warning: they may be right for any forest (a legal limit) or only for one.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from .template_validation import validate_template

MIN_DESCRIPTION = 40
_TEMPLATE_ONLY_KIND_RULES = frozenset({
    "missing_required_section", "below_min_sections", "kind_required", "unknown_plan_kind",
    "description_short", "description_too_short",
})
_TOKEN = re.compile(r"\{\{[^}]*\}\}")
_TYPED_NUMBER = re.compile(r"(?<![\w{])[0-9०-९][0-9०-९,.]{2,}(?![\w}])")


def _walk(nodes: Iterable[dict]):
    for n in nodes or []:
        yield n
        yield from _walk(n.get("children") or [])


def _issue(sev: str, code: str, message: str, node: dict | None = None, **extra: Any) -> Dict[str, Any]:
    out = {"severity": sev, "code": code, "message": message, "node_id": (node or {}).get("id"),
           "title": ((node or {}).get("title_en") or (node or {}).get("title_ne") or "")}
    out.update(extra)
    return out


def author_forest_names(db: Session, user_id: Any) -> List[str]:
    """Names that identify the author's own forests: the forest name and the user-group name on each."""
    rows = db.execute(
        text(
            "SELECT c.forest_name, m.group_name FROM calculations c "
            "LEFT JOIN forest_metadata m ON m.calculation_id = c.id WHERE c.user_id = :u"
        ),
        {"u": str(user_id)},
    ).fetchall()
    names = {str(v).strip() for r in rows for v in r if v and len(str(v).strip()) >= 4}
    return sorted(names, key=len, reverse=True)


# a single chapter has no cover page and no contents list of its own
_WHOLE_DOCUMENT_ONLY = frozenset({"no_cover_node", "multiple_cover_nodes", "no_toc_node", "empty_tree"})


def publish_check(db: Session, *, user_id: Any, name: str, description: str, tree: List[dict], item_type: str = "template") -> Dict[str, Any]:
    gate = validate_template(db, tree, plan_kind=None, for_publish=False)
    skip = _TEMPLATE_ONLY_KIND_RULES | (_WHOLE_DOCUMENT_ONLY if item_type == "section" else frozenset())
    errors = [i for i in gate.get("errors", []) if i.get("code") not in skip]
    warnings = [i for i in gate.get("warnings", []) if i.get("code") not in skip]
    if item_type == "section" and not tree:
        errors.append(_issue("error", "section_empty", "The section has nothing in it."))

    if not (name or "").strip():
        errors.append(_issue("error", "name_missing", "The template needs a name."))
    if len((description or "").strip()) < MIN_DESCRIPTION:
        errors.append(_issue("error", "description_short",
                             f"Write a short description (at least {MIN_DESCRIPTION} characters) so others know what it is for."))

    names = author_forest_names(db, user_id)
    if names:
        for node in _walk(tree):
            body = " ".join([node.get("title_en") or "", node.get("title_ne") or "", _TOKEN.sub(" ", node.get("content") or "")])
            for cell_text in _static_table_text(node):
                body += " " + cell_text
            low = body.lower()
            for n in names:
                if n.lower() in low:
                    errors.append(_issue("error", "forest_name_inside", f"'{n}' is the name of one of your forests. "
                                         "Replace it with a variable so the template works for any forest.", node, name=n))
        low_desc = f"{name} {description}".lower()
        for n in names:
            if n.lower() in low_desc:
                errors.append(_issue("error", "forest_name_inside", f"'{n}' is the name of one of your forests; take it out "
                                     "of the template name and description.", name=n))

    for node in _walk(tree):
        if node.get("content_type", "richtext") != "richtext":
            continue
        typed = _TYPED_NUMBER.findall(_TOKEN.sub(" ", node.get("content") or ""))
        if typed:
            warnings.append(_issue("warning", "typed_numbers", f"Numbers typed by hand ({', '.join(typed[:3])}) may belong to "
                                   "one forest only. Check they are right for any forest.", node, numbers=typed[:5]))
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _static_table_text(node: dict):
    st = node.get("static_table") or {}
    for row in st.get("rows") or []:
        for cell in row:
            yield str(cell)
    for t in node.get("inline_tables") or []:
        for row in t.get("rows") or []:
            for cell in row:
                yield str(cell)
