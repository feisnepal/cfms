"""The credit chain of a template: who wrote it, and who adapted it after (owner, 2026-10-16).

A template copy remembers its parent (``source_template_id``). Following that link upward gives the chain, original author first:

    Brief FMP, Rambhadevi UG  ->  Terai sal plan, R. Sharma  ->  Chitwan edition, S. Thapa

Rules:
* a name is shown only for a template that has been shared at some time (or is the viewer's own): sharing is the author's
  consent to be credited, and withdrawing the template later does not take that back, so the original author stays on every
  copy (owner, 2026-10-17). A template that was never shared stays anonymous;
* an ancestor that was never shared and that the viewer may not see is shown as "a private template" with no name, so the chain
  does not break;
* the first author stays at the top.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from ...models.op_template import OPTemplate
from ...models.user import User
from . import template_access

MAX_DEPTH = 12


def _shared(t: OPTemplate) -> bool:
    """Put out to others now, or at any earlier time (a withdrawn template is still credited)."""
    return template_access.ever_shared(t)


def author_name(db: Session, t: OPTemplate, viewer: Any = None) -> Optional[str]:
    """The author's name, if the author has put the template out (or the viewer is the author)."""
    if not t.created_by:
        return None
    if not (_shared(t) or t.is_system or (viewer is not None and t.created_by == getattr(viewer, "id", None))):
        return None
    u = db.get(User, t.created_by)
    return (u.full_name or "").strip() or None if u else None


def lineage(db: Session, template_id: UUID, viewer: Any = None) -> List[Dict[str, Any]]:
    """Original first, the requested template last. Stops at a template that no longer exists or after MAX_DEPTH."""
    chain: List[OPTemplate] = []
    seen: set = set()
    cur: Optional[UUID] = template_id
    while cur is not None and cur not in seen and len(chain) < MAX_DEPTH:
        seen.add(cur)
        t = db.get(OPTemplate, cur)
        if t is None:
            break
        chain.append(t)
        cur = t.source_template_id
    out: List[Dict[str, Any]] = []
    for t in reversed(chain):
        openable = viewer is not None and template_access.can_view(t, viewer)
        own = viewer is not None and t.created_by == getattr(viewer, "id", None)
        credited = openable or own or _shared(t)  # may the name and author be shown?
        out.append({
            "id": str(t.id) if openable else None,
            "name": t.name if credited else None,
            "author_name": author_name(db, t, viewer) if credited else None,
            "tier": t.tier,
            "visible": bool(credited),
            "openable": bool(openable),
            "withdrawn": t.status == "retired",
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return out


def credit_line(db: Session, template_id: Optional[UUID], language: str = "NP") -> str:
    """One line for the end of an exported plan, e.g. ``Template: Brief FMP (Rambhadevi UG); adapted by R. Sharma, S. Thapa``.

    Names only for shared templates; private steps are left out. Empty when there is nothing to credit."""
    if not template_id:
        return ""
    chain = lineage(db, template_id, viewer=None)
    if not chain:
        return ""
    ne = not str(language or "").upper().startswith("EN")
    first, rest = chain[0], chain[1:]
    head = first["name"] or ""
    if first["author_name"]:
        head += f" ({first['author_name']})"
    adapted = [c["author_name"] for c in rest if c["author_name"]]
    if ne:
        line = f"टेम्प्लेट: {head}"
        if adapted:
            line += "; सम्पादन: " + ", ".join(dict.fromkeys(adapted))
    else:
        line = f"Template: {head}"
        if adapted:
            line += "; adapted by " + ", ".join(dict.fromkeys(adapted))
    return line
