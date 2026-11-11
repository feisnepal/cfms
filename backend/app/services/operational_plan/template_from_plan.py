"""Turn an edited plan back into a template that holds no forest's own figures.

Why this exists: when a plan is created its ``{{tokens}}`` are replaced by this forest's values (``create`` auto-populates), so
the stored document says "Brindaban, 250 ha" where the template said ``{{forest_name}}, {{area_ha}}``. Saving that tree as a
template would give the next user another forest's name and numbers.

What it does, node by node (matched to the template the plan was built from, by node id):

* **Unedited** -- the plan text still has the template's wording around the values. The template's own text, tokens and all, is
  put back.
* **Edited or new** -- the user wrote it. Text values that came from the forest (names, places: 4+ characters, not just
  digits) are turned back into their tokens where they appear. Numbers are NOT touched: a "250" could be anything, so an edited
  section is reported and the author decides.

The report says how many of each, so the screen can tell the author which sections still need a look.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from . import no_data
from .plan_live import is_live_dict

_TOKEN = re.compile(r"\{\{(\w+(?::\w+)*)\}\}")
# tokens that stand for a table / chart / map / asset are structure, not values
_STRUCTURAL = ("chart:", "map:", "thememap:", "opsmap:", "table:", "asset:", "section:")
_NUMBERISH = re.compile(r"^[\s\d०-९.,%\-/+:()]+$")


def _flatten(nodes: Iterable[dict]) -> Iterable[dict]:
    for n in nodes or []:
        yield n
        yield from _flatten(n.get("children") or [])


def _skeleton(parent_content: str) -> "re.Pattern[str]":
    """A pattern that matches the plan text made from ``parent_content``: the literal wording must be the same, each token may
    have become anything."""
    parts = _TOKEN.split(parent_content)  # literal, name, literal, name, ... (names at odd positions)
    rx = "".join((".*?" if i % 2 else re.escape(p)) for i, p in enumerate(parts))
    return re.compile(rx, re.S)


def is_unedited(plan_text: str, parent_text: str) -> bool:
    if plan_text == parent_text:
        return True
    return _skeleton(parent_text).fullmatch(plan_text) is not None


def value_tokens(keys: Iterable[str], resolve: Callable[[str], str]) -> List[Tuple[str, str]]:
    """``[(text_as_printed, "{{key}}")]`` for the forest's text values, longest first so a long name wins over a short one."""
    out: Dict[str, str] = {}
    for key in keys:
        if key.startswith(_STRUCTURAL) or key.endswith(":full"):
            continue
        shown = resolve("{{%s}}" % key)
        if not shown or len(shown) < 4 or _NUMBERISH.match(shown) or "{{" in shown or no_data.has_marker(shown):
            continue
        out.setdefault(shown, "{{%s}}" % key)
    return sorted(out.items(), key=lambda kv: -len(kv[0]))


def _untangle(text: str, values: List[Tuple[str, str]]) -> Tuple[str, int]:
    n = 0
    for shown, token in values:
        if shown in text:
            n += text.count(shown)
            text = text.replace(shown, token)
    return text, n


def build_template_tree(
    plan_tree: List[dict],
    parent_tree: Optional[List[dict]],
    values: List[Tuple[str, str]],
) -> Tuple[List[dict], Dict[str, Any]]:
    """Return ``(tree, report)``. Works on copies; the plan is never changed."""
    import copy

    tree = copy.deepcopy(plan_tree)
    parents = {n.get("id"): n for n in _flatten(parent_tree or [])}
    report: Dict[str, Any] = {
        "parent_found": parent_tree is not None,
        "restored": 0,
        "edited": [],
        "new": [],
        "values_turned_into_tokens": 0,
    }
    for node in _flatten(tree):
        content = node.get("content") or ""
        if not content.strip() or node.get("content_type", "richtext") != "richtext":
            continue
        title = node.get("title_en") or node.get("title_ne") or node.get("id")
        if is_live_dict(node):
            # nobody has edited it: the template's own text is on record, no guessing needed
            node["content"] = node["source_content"]
            report["restored"] += 1
            continue
        parent = parents.get(node.get("id"))
        if parent is not None and is_unedited(content, parent.get("content") or ""):
            node["content"] = parent.get("content") or ""
            report["restored"] += 1
            continue
        node["content"], swapped = _untangle(content, values)
        report["values_turned_into_tokens"] += swapped
        report["new" if parent is None else "edited"].append({"id": node.get("id"), "title": title})
    for node in _flatten(tree):  # a template carries its own text only, never a plan's bookkeeping
        node.pop("source_content", None)
        node.pop("populated_hash", None)
    return tree, report
