"""The "original updated" notice for a template copy (proposal phase 5).

A copy remembers its original (``source_template_id``) and the version it was taken from (``source_version``, migration 129).
When the original publishes a newer version with sections the copy does not have, the owner of the copy is told and may add them.

The merge only ever ADDS: the copy is the owner's own work, so nothing they wrote, reordered, hid or deleted is touched and no
section is removed because the original dropped it. A section the owner deleted from the copy is not brought back when the
original's old version (the one the copy was taken from) already had it.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.op_template import OPTemplate, OPTemplateVersion

_LIVE = ("published", "deprecated")


def _walk(nodes: List[dict], parent_id: Optional[str] = None):
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        yield n, parent_id
        yield from _walk(n.get("children") or [], n.get("id"))


def _ids(nodes: List[dict]) -> set:
    return {n.get("id") for n, _ in _walk(nodes) if n.get("id")}


def _title(n: dict) -> str:
    return (n.get("title_ne") or n.get("title_en") or n.get("id") or "").strip()


def parent_live_tree(db: Session, parent: OPTemplate) -> List[dict]:
    """The tree people actually get from the original: its newest published snapshot, else its current tree."""
    snap = db.execute(
        select(OPTemplateVersion)
        .where(OPTemplateVersion.template_id == parent.id, OPTemplateVersion.is_published_snapshot.is_(True))
        .order_by(OPTemplateVersion.version.desc())
    ).scalars().first()
    return (snap.tree if snap else parent.tree) or []


def _base_ids(db: Session, parent: OPTemplate, source_version: Optional[int]) -> set:
    """Section ids the original had when the copy was taken (empty when that version is unknown)."""
    if source_version is None:
        return set()
    row = db.execute(
        select(OPTemplateVersion).where(OPTemplateVersion.template_id == parent.id, OPTemplateVersion.version == source_version)
    ).scalars().first()
    return _ids(row.tree) if row else set()


def new_sections(db: Session, copy_t: OPTemplate, parent: OPTemplate) -> List[Tuple[dict, Optional[str]]]:
    """Sections of the original that the copy lacks and that are new since the copy was taken: ``(node, parent_node_id)``."""
    have = _ids(copy_t.tree or []) | _base_ids(db, parent, copy_t.source_version)
    out: List[Tuple[dict, Optional[str]]] = []
    for n, pid in _walk(parent_live_tree(db, parent)):
        nid = n.get("id")
        if nid and nid not in have and not n.get("deleted"):
            out.append((n, pid))
    return out


def status(db: Session, copy_t: OPTemplate) -> Dict[str, Any]:
    """What the owner of a copy sees: is there an original, did it change, and which sections would be added."""
    if not copy_t.source_template_id:
        return {"has_parent": False}
    parent = db.get(OPTemplate, copy_t.source_template_id)
    if parent is None:
        return {"has_parent": False}
    live = parent.status in _LIVE
    added = new_sections(db, copy_t, parent) if live else []
    newer = bool(
        live and parent.published_version and (copy_t.source_version is None or parent.published_version > copy_t.source_version)
    )
    return {
        "has_parent": True,
        "parent_id": str(parent.id),
        "parent_name": parent.name,
        "parent_live": live,
        "based_on_version": copy_t.source_version,
        "parent_version": parent.published_version if live else None,
        "update_available": bool(added) and newer,
        "added": [_title(n) for n, _ in added],
    }


def merge_new_sections(db: Session, copy_t: OPTemplate) -> Tuple[List[dict], Dict[str, Any]]:
    """Return ``(new_tree, report)``: the copy's tree with the original's new sections added. Nothing is removed or changed."""
    info = status(db, copy_t)
    tree = copy.deepcopy(copy_t.tree or [])
    if not info.get("update_available"):
        return tree, {"added": [], "version": info.get("parent_version")}
    parent = db.get(OPTemplate, copy_t.source_template_id)
    fresh = new_sections(db, copy_t, parent)
    fresh_ids = {n.get("id") for n, _ in fresh}
    by_id = {n.get("id"): n for n, _ in _walk(tree) if n.get("id")}
    added: List[str] = []
    for n, pid in fresh:
        # only the top-most new section is copied (its children come with it); a new child of an existing section goes under it
        if pid in fresh_ids:
            continue
        node = copy.deepcopy(n)
        host = by_id.get(pid) if pid else None
        if host is not None:
            host.setdefault("children", []).append(node)
        else:
            tree.append(node)
        added.append(_title(n))
        for sub, _ in _walk([node]):
            if sub.get("id"):
                by_id[sub["id"]] = sub
    return tree, {"added": added, "version": info.get("parent_version")}
