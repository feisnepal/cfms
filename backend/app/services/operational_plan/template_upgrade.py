"""Adopt a newer published template version into an existing plan.

OP_MULTI_TEMPLATE_PLAN.md §3.5. The plan's authored content is carried forward
by node id: the new published structure wins for titles / types / ordering /
chart & map refs, while the plan keeps its own richtext, static tables and
hidden/deleted flags for every node it shares by id with the new tree.

Node ids that exist only in the plan (a section the designer removed) are
dropped from the merged tree — they are no longer part of the approved
structure. Ids only in the new tree are inserted as published.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# Fields the PLAN keeps on a matched node (the user's authoring).
_AUTHORED_FIELDS = (
    "content",
    "source_content",  # these two travel with the text: together they say whether the section is still the template's own
    "populated_hash",
    "static_table",
    "inline_tables",
    "hidden_in_export",
    "deleted",
)


def _index_by_id(nodes: List[Dict[str, Any]], acc: Dict[str, Dict[str, Any]]) -> None:
    for n in nodes or []:
        if isinstance(n, dict) and n.get("id"):
            acc[n["id"]] = n
            _index_by_id(n.get("children") or [], acc)


def _titles(nodes: List[Dict[str, Any]], acc: List[str]) -> None:
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        title = (n.get("title_ne") or n.get("title_en") or n.get("id") or "").strip()
        if title:
            acc.append(title)
        _titles(n.get("children") or [], acc)


def merge_plan_onto_template(
    plan_tree: List[Dict[str, Any]],
    new_template_tree: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return (merged_tree, diff).

    merged_tree = a deep-ish copy of new_template_tree with authored fields
    from plan_tree spliced in wherever a node id matches.
    """
    plan_by_id: Dict[str, Dict[str, Any]] = {}
    _index_by_id(plan_tree, plan_by_id)

    new_ids: set[str] = set()
    kept = 0
    content_preserved = 0

    def _clone_merge(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        nonlocal kept, content_preserved
        out: List[Dict[str, Any]] = []
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            m = dict(n)
            nid = m.get("id")
            if nid:
                new_ids.add(nid)
            src = plan_by_id.get(nid) if nid else None
            if src is not None:
                kept += 1
                had = m.get("content", "")
                for f in _AUTHORED_FIELDS:
                    if f in src:
                        m[f] = src[f]
                if (m.get("content") or "") != (had or "") and (
                    m.get("content") or ""
                ).strip():
                    content_preserved += 1
            m["children"] = _clone_merge(n.get("children") or [])
            out.append(m)
        return out

    merged = _clone_merge(new_template_tree)

    new_titles: List[str] = []
    _titles(new_template_tree, new_titles)
    plan_titles: List[str] = []
    _titles(plan_tree, plan_titles)

    added = []
    for n_id, node in _flatten_with_ids(new_template_tree):
        if n_id not in plan_by_id:
            added.append((node.get("title_ne") or node.get("title_en") or n_id).strip())
    removed = []
    for p_id, node in _flatten_with_ids(plan_tree):
        if p_id not in new_ids:
            removed.append(
                (node.get("title_ne") or node.get("title_en") or p_id).strip()
            )

    diff = {
        "added": added,
        "removed": removed,
        "kept": kept,
        "content_preserved": content_preserved,
    }
    return merged, diff


def _flatten_with_ids(nodes: List[Dict[str, Any]]):
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        yield n.get("id"), n
        yield from _flatten_with_ids(n.get("children") or [])
