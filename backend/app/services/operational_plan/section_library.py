"""The section library: one chapter of a plan, kept and shared on its own (owner idea 2026-10-16: "special effort in some cases may
be important for other geography").

A saved section is an ``op_templates`` row with ``item_type='section'`` whose ``tree`` is the chapter and everything under it. It is
shared, licensed, credited, reported and withdrawn exactly like a template (same rules, same code). What is specific to sections:

* **Saving** takes the chapter out of the plan's tokenised document (``plan_live`` / ``template_from_plan``), so it carries the
  template's variables, never this forest's own values.
* **Inserting** copies the chapter into a plan with fresh ids, fills its variables from the plan's forest, and remembers the
  template text so the new sections follow the data too. A section licensed "view only" arrives locked: it can be used, not rewritten.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, List, Optional, Tuple


def find_subtree(tree: List[dict], node_id: str) -> Optional[dict]:
    for n in tree or []:
        if n.get("id") == node_id:
            return n
        hit = find_subtree(n.get("children") or [], node_id)
        if hit is not None:
            return hit
    return None


def extract_section(tokenised_tree: List[dict], node_id: str) -> Optional[List[dict]]:
    """The chapter ``node_id`` (and what is under it) as a one-element tree, or None if it is not in the plan."""
    node = find_subtree(tokenised_tree, node_id)
    if node is None or node.get("is_cover"):
        return None
    out = copy.deepcopy(node)
    out["is_locked"] = False
    out["deleted"] = False
    return [out]


def _fresh_ids(node: dict) -> None:
    node["id"] = str(uuid.uuid4())
    for c in node.get("children") or []:
        _fresh_ids(c)


def _lock(node: dict) -> None:
    node["is_locked"] = True
    for c in node.get("children") or []:
        _lock(c)


def count_nodes(nodes: List[dict]) -> int:
    return sum(1 + count_nodes(n.get("children") or []) for n in nodes or [])


def prepare_for_insert(section_tree: List[dict], *, lock: bool) -> Tuple[List[dict], List[str]]:
    """A copy of the saved chapter with new ids (so it can be inserted twice) and, for a "view only" section, locked.
    Returns ``(nodes, new top-level ids)``."""
    nodes = copy.deepcopy(section_tree or [])
    for n in nodes:
        _fresh_ids(n)
        n.pop("source_content", None)
        n.pop("populated_hash", None)
        if lock:
            _lock(n)
    return nodes, [n["id"] for n in nodes]
