"""What people change in the plans built from a template: the evidence for where the template, or the system, should develop next.

Everything is read from the stored plans; nothing new is recorded. For each template that plans were built from, and for each of
its sections, it counts in how many plans the section was

* kept as the template wrote it (still live: nobody edited it),
* edited (the owner changed the text),
* hidden from the export, or removed,
* printed with a "No data" in it,

and it lists the sections people *added* that the template does not have, and the variables they typed by hand into their own text.

**Anonymous.** The report holds no forest name and no user: only counts. An added section title or a typed variable is listed
only when at least ``min_owners`` different people did it, so a title one person typed cannot be traced back to them.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import no_data
from .plan_live import is_live_dict
from .template_from_plan import is_unedited

_TOKEN = re.compile(r"\{\{(\w+(?::\w+)*)\}\}")
_STRUCTURAL = ("chart:", "map:", "thememap:", "opsmap:", "table:", "asset:", "inline_table")


def _walk(nodes: Iterable[dict]):
    for n in nodes or []:
        yield n
        yield from _walk(n.get("children") or [])


def _title(n: dict) -> str:
    return (n.get("title_en") or n.get("title_ne") or "").strip()


def _tokens(text_: str) -> Set[str]:
    return {t for t in _TOKEN.findall(text_ or "") if not t.startswith(_STRUCTURAL) and not t.endswith(":full")}


def _state(node: dict, parent_content: Optional[str]) -> str:
    """kept | edited | hidden | removed for one section of one plan."""
    if node.get("deleted"):
        return "removed"
    if node.get("hidden_in_export"):
        return "hidden"
    if node.get("source_content") is not None:
        return "kept" if is_live_dict(node) else "edited"
    content = node.get("content") or ""
    if parent_content is None or not content.strip():
        return "kept"
    return "kept" if is_unedited(content, parent_content) else "edited"


def analyse(db: Session, *, min_owners: int = 2, min_plans: int = 1) -> Dict[str, Any]:
    rows = db.execute(
        text(
            "SELECT p.id, p.sections, p.plan_metadata, c.user_id "
            "FROM operational_plans p JOIN calculations c ON c.id = p.calculation_id"
        )
    ).fetchall()

    by_template: Dict[str, List[Tuple[dict, str]]] = defaultdict(list)  # template id -> [(plan tree, owner id)]
    for _pid, sections, meta, owner in rows:
        meta = meta or {}
        if meta.get("authoring") or not meta.get("template_id"):
            continue
        tree = (sections or {}).get("tree") or []
        if tree:
            by_template[str(meta["template_id"])].append((tree, str(owner)))

    out: List[Dict[str, Any]] = []
    for tid, plans in by_template.items():
        if len(plans) < min_plans:
            continue
        tmpl = db.execute(text("SELECT id, name, tree FROM op_templates WHERE id = :i"), {"i": tid}).first()
        if tmpl is None:
            continue
        t_nodes = {n["id"]: n for n in _walk(tmpl.tree or []) if n.get("id")}
        per_node: Dict[str, Counter] = {nid: Counter() for nid in t_nodes}
        added_owners: Dict[str, Set[str]] = defaultdict(set)
        typed_owners: Dict[str, Set[str]] = defaultdict(set)
        owners: Set[str] = set()

        for tree, owner in plans:
            owners.add(owner)
            seen: Set[str] = set()
            for node in _walk(tree):
                nid = node.get("id")
                if nid in t_nodes:
                    seen.add(nid)
                    parent_content = t_nodes[nid].get("content")
                    state = _state(node, parent_content)
                    c = per_node[nid]
                    c["plans"] += 1
                    c[state] += 1
                    if no_data.has_marker(node.get("content") or ""):
                        c["no_data"] += 1
                    if state == "edited":
                        for tok in _tokens(node.get("content")) - _tokens(parent_content):
                            typed_owners[tok].add(owner)
                else:
                    if node.get("deleted"):
                        continue
                    t = _title(node)
                    if t:
                        added_owners[t].add(owner)
                    for tok in _tokens(node.get("content")):
                        typed_owners[tok].add(owner)
            for nid in set(t_nodes) - seen:  # taken out of the document altogether
                per_node[nid]["plans"] += 1
                per_node[nid]["removed"] += 1

        sections = []
        for nid, c in per_node.items():
            n = c["plans"]
            if not n:
                continue
            node = t_nodes[nid]
            if node.get("is_cover") or not (node.get("title_en") or node.get("title_ne")):
                continue
            changed = c["edited"] + c["hidden"] + c["removed"]
            sections.append({
                "node_id": nid, "title_en": node.get("title_en") or "", "title_ne": node.get("title_ne") or "",
                "plans": n, "kept": c["kept"], "edited": c["edited"], "hidden": c["hidden"], "removed": c["removed"],
                "no_data": c["no_data"], "changed_pct": round(100.0 * changed / n, 1), "no_data_pct": round(100.0 * c["no_data"] / n, 1),
            })
        sections.sort(key=lambda s: (-s["changed_pct"], -s["plans"], s["title_en"]))

        out.append({
            "template_id": tid, "template_name": tmpl.name, "plans": len(plans), "owners": len(owners),
            "sections": sections,
            "added_sections": [
                {"title": t, "owners": len(o)} for t, o in sorted(added_owners.items(), key=lambda kv: -len(kv[1])) if len(o) >= min_owners
            ][:50],
            "typed_variables": [
                {"variable": f"{{{{{t}}}}}", "owners": len(o)} for t, o in sorted(typed_owners.items(), key=lambda kv: -len(kv[1])) if len(o) >= min_owners
            ][:50],
        })
    out.sort(key=lambda t: -t["plans"])
    return {"min_owners": min_owners, "templates": out}
