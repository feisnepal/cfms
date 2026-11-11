"""Keep a plan's text in step with the forest's data, without ever touching what the user wrote (owner decision 2026-10-17).

The problem: creating a plan used to replace every ``{{variable}}`` in the template text by the forest's value and store the
result. The text was then frozen: data entered later, or a corrected figure, never reached the plan, a "No data" stayed "No
data" for ever, and nothing could tell which sections the user had edited and which were still the template's own words.

How it works now. When a section's text is first filled in from the template, the plan remembers

* ``source_content``: the template's own text, variables and all;
* ``populated_hash``: a fingerprint of the text it printed from that.

A section is **live** while its text still has that fingerprint, which means nobody has changed it. Whenever the document is
previewed, exported, checked or saved as a template, a live section is read from ``source_content``, so it always carries the
current values. The moment a user edits the text the fingerprint no longer matches; the section is **theirs** and is never
rewritten (its own ``{{variables}}`` still resolve, as before). "Update values" re-fills the stored text of live sections only.

A plan made before this change has no ``source_content`` anywhere and behaves as it always did.
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Callable, Dict, Iterable, List

_HAS_TOKEN = re.compile(r"\{\{\w+(?::\w+)*\}\}")


def content_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def has_tokens(text: str) -> bool:
    return bool(text) and _HAS_TOKEN.search(text) is not None


# ── on the node objects (TreeNode) ───────────────────────────────────────────

def is_live(node: Any) -> bool:
    """Still the template's own words, so it should follow the data."""
    src = getattr(node, "source_content", None)
    return src is not None and getattr(node, "populated_hash", None) == content_hash(node.content or "")


def populate_node(node: Any, resolve: Callable[[str], str]) -> None:
    """Fill a section's text from its template text and remember how, so it can follow the data later.

    A section whose text has no variable is static: nothing to remember."""
    if getattr(node, "content_type", "richtext") != "richtext" or not (node.content or "").strip():
        return
    if is_live(node):
        source = node.source_content
    elif getattr(node, "source_content", None) is None and has_tokens(node.content):
        source = node.content
    else:
        # the user's own text (or static text): only the variables they typed are filled in
        node.content = resolve(node.content)
        return
    node.source_content = source
    node.content = resolve(source)
    node.populated_hash = content_hash(node.content)


def resolve_for_output(nodes: Iterable[Any], resolve: Callable[[str], str]) -> None:
    """Preview / export: live sections are read fresh from their template text, every other section resolves its own text.

    Mutates the (in-memory) nodes; the stored plan is not touched."""
    for node in nodes:
        if not node.content and getattr(node, "source_content", None) is None:
            continue
        text = node.source_content if is_live(node) else node.content
        if text:
            node.content = resolve(text)


# ── on plain dicts (readiness, save-as-template) ─────────────────────────────

def is_live_dict(node: Dict[str, Any]) -> bool:
    src = node.get("source_content")
    return src is not None and node.get("populated_hash") == content_hash(node.get("content") or "")


def effective_tree(tree: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A copy of ``tree`` in which every live section carries its template text (variables unresolved)."""
    out = copy.deepcopy(tree or [])

    def walk(nodes: List[Dict[str, Any]]) -> None:
        for n in nodes or []:
            if is_live_dict(n):
                n["content"] = n["source_content"]
            walk(n.get("children") or [])

    walk(out)
    return out
