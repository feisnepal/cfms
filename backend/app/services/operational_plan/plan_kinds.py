"""Plan-kind lookup + required-section resolution.

A plan kind = (plan_stage x plan_regime), stored in ``op_plan_kinds`` and
seeded by migration 067. A ``*_revision`` kind inherits its parent ``*_new``
kind's required sections (parent UNION own).

See OP_MULTI_TEMPLATE_PLAN.md §3.2 / §3.4.
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models.op_template import OPPlanKind


def list_plan_kinds(db: Session, *, active_only: bool = False) -> List[OPPlanKind]:
    stmt = select(OPPlanKind).order_by(OPPlanKind.sort_order, OPPlanKind.key)
    if active_only:
        stmt = stmt.where(OPPlanKind.is_active.is_(True))
    return list(db.execute(stmt).scalars().all())


def get_plan_kind(db: Session, key: str) -> Optional[OPPlanKind]:
    if not key:
        return None
    return db.execute(
        select(OPPlanKind).where(OPPlanKind.key == key)
    ).scalar_one_or_none()


def resolve_kind_key(
    key: Optional[str], regime: Optional[str], stage: Optional[str]
) -> Optional[str]:
    """Compose the "<regime>_<stage>" key from either an explicit key or the
    regime + stage pair. Returns None when nothing usable is supplied."""
    if key:
        return key
    if regime and stage:
        return f"{regime}_{stage}"
    return None


def effective_required_sections(db: Session, key: str) -> List[str]:
    """A kind's own required sections plus its parent's (one level of
    inheritance — enough for the seeded *_revision -> *_new links). Order
    preserved, de-duplicated."""
    seen: list[str] = []

    def _add(values) -> None:
        for v in values or []:
            if v not in seen:
                seen.append(v)

    kind = get_plan_kind(db, key)
    if kind is None:
        return []
    if kind.parent_kind_key:
        parent = get_plan_kind(db, kind.parent_kind_key)
        if parent is not None:
            _add(parent.required_section_keys)
    _add(kind.required_section_keys)
    return seen


def default_template_id(db: Session, key: str) -> Optional[UUID]:
    kind = get_plan_kind(db, key)
    return kind.default_template_id if kind else None
