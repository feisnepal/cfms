"""The owner's "yearly activities are done" mark (workflow step 15).

Owner decisions 2026-10-15: the step is complete only when the owner says Done; any later add / edit / delete of a plan line, its
year rows or its drawn features reopens it automatically. The reopening is a session ``before_flush`` hook, so every write path
(legacy endpoints, the plan facade, the wizard, future grid saves) is covered without each one remembering to call it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Set
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.models.yearly_activities import (
    ActivityDrawnFeature,
    ActivityYearDetail,
    ProposedYearlyActivity,
    YearlyPlanStatus,
)

logger = logging.getLogger(__name__)

REOPENED_BY_CHANGE = "plan_changed"


def get_status(db: Session, calculation_id: UUID) -> Dict[str, Any]:
    row = db.query(YearlyPlanStatus).filter(YearlyPlanStatus.calculation_id == calculation_id).first()
    if row is None:
        return {"done": False, "done_at": None, "done_by": None, "reopened_reason": None}
    return {
        "done": bool(row.is_done),
        "done_at": row.done_at.isoformat() if row.done_at else None,
        "done_by": str(row.done_by) if row.done_by else None,
        "reopened_reason": row.reopened_reason,
    }


def set_done(db: Session, calculation_id: UUID, done: bool, user_id: UUID) -> Dict[str, Any]:
    """Mark the forest's yearly activities done (or open again). The caller has already checked ownership."""
    row = db.query(YearlyPlanStatus).filter(YearlyPlanStatus.calculation_id == calculation_id).first()
    if row is None:
        row = YearlyPlanStatus(calculation_id=calculation_id)
        db.add(row)
    row.is_done = bool(done)
    row.done_by = user_id if done else None
    row.done_at = datetime.now(timezone.utc) if done else None
    row.reopened_reason = None
    db.commit()
    return get_status(db, calculation_id)


def _touched_calculations(session: Session) -> Set[str]:
    """The forests whose plan lines / year rows / drawn features this flush adds, changes or removes."""
    calcs: Set[str] = set()
    detail_line_ids: Set[str] = set()
    for obj in list(session.new) + list(session.deleted) + [o for o in session.dirty if session.is_modified(o)]:
        if isinstance(obj, ProposedYearlyActivity) and obj.calculation_id:
            calcs.add(str(obj.calculation_id))
        elif isinstance(obj, ActivityDrawnFeature):
            if obj.calculation_id:
                calcs.add(str(obj.calculation_id))
            elif obj.proposed_activity_id:
                detail_line_ids.add(str(obj.proposed_activity_id))
        elif isinstance(obj, ActivityYearDetail) and obj.proposed_activity_id:
            detail_line_ids.add(str(obj.proposed_activity_id))
    if detail_line_ids:
        rows = session.execute(
            text("SELECT DISTINCT calculation_id::text FROM proposed_yearly_activities WHERE id::text = ANY(:ids)"),
            {"ids": list(detail_line_ids)},
        ).fetchall()
        calcs.update(r[0] for r in rows)
    return calcs


@event.listens_for(Session, "before_flush")
def _reopen_when_plan_changes(session: Session, flush_context: Any, instances: Any) -> None:
    try:
        calcs = _touched_calculations(session)
        if not calcs:
            return
        session.execute(
            text(
                "UPDATE yearly_plan_status SET is_done = false, done_by = NULL, done_at = NULL, "
                "reopened_reason = :why, updated_at = now() "
                "WHERE is_done AND calculation_id::text = ANY(:ids)"
            ),
            {"why": REOPENED_BY_CHANGE, "ids": list(calcs)},
        )
    except Exception:  # noqa: BLE001 -- the reopening is a courtesy; it must never make a plan save fail
        logger.warning("could not reopen the yearly-activities mark", exc_info=True)
