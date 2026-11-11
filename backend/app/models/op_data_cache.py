"""
OP Data Cache model - caches collected operational plan data to avoid 35-50 queries on every export

Auto-invalidates whenever any model with calculation_id is changed (insert/update/delete).
This ensures the OP preview/export always reflects the latest data without manual cache clearing.
"""
from sqlalchemy import Column, DateTime, func, event
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Session
from datetime import datetime

from ..core.database import Base


class OpDataCache(Base):
    """Cache model for operational plan collected data.

    Stores pre-aggregated data keyed by calculation_id to avoid
    35-50 queries on every OP export. Auto-invalidated on any
    calculation_id model change via after_flush event.
    """
    __tablename__ = "op_data_cache"
    calculation_id = Column(UUID(as_uuid=True), primary_key=True)
    data = Column(JSONB, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=func.now())


# Children of a plan line: they carry no ``calculation_id`` of their own (only the parent
# ``proposed_yearly_activities`` row does), yet they feed the OP's ``ya_*`` / ``cba_*`` variables —
# so a year-row or spatial-assignment write used to leave the cache stale (YEARLY_ACTIVITIES plan §5.8).
_PLAN_LINE_CHILDREN = ("ActivityYearDetail", "ActivitySpatialAssignment")


def _invalidate_op_cache_on_change(session: Session, flush_context):
    """Auto-invalidate OpDataCache when any model with calculation_id changes.

    Fires after flush but before commit — shares the same transaction, so a
    rollback also undoes the cache deletion. Catches insert/update/delete on
    ALL current and future models that have a calculation_id column, plus the
    children of a plan line (resolved to their line's calculation).
    """
    calc_ids = set()
    line_ids = set()
    for obj in list(session.dirty) + list(session.new) + list(session.deleted):
        name = obj.__class__.__name__
        if name == "OpDataCache":
            continue
        cid = getattr(obj, "calculation_id", None)
        if cid is not None:
            calc_ids.add(cid)
        elif name in _PLAN_LINE_CHILDREN:
            line_id = getattr(obj, "proposed_activity_id", None)
            if line_id is not None:
                line_ids.add(line_id)
    if line_ids:
        from .yearly_activities import ProposedYearlyActivity

        calc_ids.update(
            cid
            for (cid,) in session.query(ProposedYearlyActivity.calculation_id).filter(
                ProposedYearlyActivity.id.in_(line_ids)
            )
        )
    if calc_ids:
        session.query(OpDataCache).filter(
            OpDataCache.calculation_id.in_(calc_ids)
        ).delete(synchronize_session=False)


event.listen(Session, "after_flush", _invalidate_op_cache_on_change)
