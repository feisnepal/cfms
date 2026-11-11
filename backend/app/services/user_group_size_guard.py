"""The user group may not grow beyond the analysis limit (owner decision D2, 2026-10-12).

A group larger than ``USER_GROUP_MAX_ANALYSIS_AREA_HA`` (5,000 ha) cannot be analysed. It used to be SAVED first (replacing the good one) and
"Analysis skipped" was appended to a success message. Now the save is refused, with the reason, and nothing changes.

Two layers, because the group is written from many places (import, upload, draw, auto-buffer, vertex edit, cut, merge, paste):

1. :func:`ensure_candidate_within_limit` -- an explicit check on the CANDIDATE geometry, called by the writers that replace the existing group
   (import, upload, auto-buffer) BEFORE anything is deleted: ``_delete_existing_extents`` commits, so a commit-time check would come too late and
   the old group would already be gone.
2. A backstop on every other path (``before_flush`` remembers the area before the session first touches the group; ``after_flush`` compares). It
   covers every other path, including ones added later, the same way ``user_group_auto_analysis`` reports changes: the ORM tells us, so no path
   has to remember to ask.

A group that is ALREADY over the limit (saved before this rule) may still be edited downward: only a change that makes the group bigger than it
was, and bigger than the limit, is refused. Disabled-by-default checks do not exist: the check runs under pytest too.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.constants import USER_GROUP_MAX_ANALYSIS_AREA_HA
from app.core.exceptions import i18n_error
from app.models.user_group import UserGroupExtent

logger = logging.getLogger(__name__)

_BEFORE_KEY = "user_group_area_before"
_EPS_HA = 0.01  # numerical noise: an edit that does not grow the group is never refused


def _fmt(ha: float) -> str:
    return f"{ha:,.0f}"


def too_large_error(area_ha: float, limit_ha: float = USER_GROUP_MAX_ANALYSIS_AREA_HA):
    """The bilingual 400 the user sees: what the area would be, the limit, that nothing was saved, and what to do."""
    return i18n_error(400, "user_group.too_large", area_ha=_fmt(area_ha), limit_ha=_fmt(limit_ha))


def current_area_ha(db: Session, calculation_id) -> float:
    """Geodesic area (ha) of the union of the group's stored polygons."""
    return float(
        db.execute(
            text(
                "SELECT COALESCE(ST_Area(ST_Union(extent_geometry)::geography), 0) / 10000.0 "
                "FROM user_group_extents WHERE calculation_id = :c"
            ),
            {"c": str(calculation_id)},
        ).scalar()
        or 0.0
    )


def candidate_area_ha(db: Session, calculation_id, wkt: str, *, replace: bool) -> float:
    """Area (ha) the group would have after saving ``wkt``: the candidate alone when it replaces the group, else the union with what is there."""
    if replace:
        sql = "SELECT COALESCE(ST_Area(ST_GeomFromText(:w, 4326)::geography), 0) / 10000.0"
        params = {"w": wkt}
    else:
        sql = (
            # COALESCE the existing union to an EMPTY geometry: with no rows the sub-select is NULL and ST_Union(g, NULL) is NULL (area 0)
            "SELECT COALESCE(ST_Area(ST_Union(ST_GeomFromText(:w, 4326), COALESCE("
            "(SELECT ST_Union(extent_geometry) FROM user_group_extents WHERE calculation_id = :c), "
            "ST_GeomFromText('GEOMETRYCOLLECTION EMPTY', 4326)))::geography), 0) / 10000.0"
        )
        params = {"w": wkt, "c": str(calculation_id)}
    return float(db.execute(text(sql), params).scalar() or 0.0)


def ensure_candidate_within_limit(db: Session, calculation_id, geometry, *, replace: bool) -> None:
    """Raise the bilingual 400 BEFORE anything is written when saving ``geometry`` would put the group over the limit."""
    if geometry is None or geometry.is_empty:
        return
    area = candidate_area_ha(db, calculation_id, geometry.wkt, replace=replace)
    if area > USER_GROUP_MAX_ANALYSIS_AREA_HA:
        raise too_large_error(area)


# ── backstop for every other path ──────────────────────────────────────────────────────────────────────────────────────────────────────
#
# Order matters: SQLAlchemy fires ``before_commit`` BEFORE the final flush, so at that moment the new geometry is not yet in the transaction.
# ``after_flush`` runs once the changed rows have been written (inside the still-open transaction), so the area it measures is the area
# the commit would make permanent; raising there aborts the commit and the caller's transaction is rolled back.

@event.listens_for(Session, "before_flush")
def _remember_area_before(session: Session, flush_context, instances) -> None:
    touched = {
        str(o.calculation_id)
        for o in (*session.new, *session.dirty, *session.deleted)
        if isinstance(o, UserGroupExtent) and o.calculation_id is not None
    }
    if not touched:
        return
    before = session.info.setdefault(_BEFORE_KEY, {})
    for calc_id in touched:
        if calc_id not in before:
            with session.no_autoflush:  # the pre-change state: nothing of this change is in the database yet
                before[calc_id] = current_area_ha(session, calc_id)


@event.listens_for(Session, "after_flush")
def _refuse_a_group_that_grew_past_the_limit(session: Session, flush_context) -> None:
    before: Optional[dict] = session.info.get(_BEFORE_KEY)
    if not before:
        return
    for calc_id, was in before.items():
        now = current_area_ha(session, calc_id)
        if now > USER_GROUP_MAX_ANALYSIS_AREA_HA and now > was + _EPS_HA:
            logger.warning("user group of %s refused: %.0f ha > %s ha (was %.0f ha)", calc_id, now, USER_GROUP_MAX_ANALYSIS_AREA_HA, was)
            session.info.pop(_BEFORE_KEY, None)
            raise too_large_error(now)


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def _forget_area_before(session: Session) -> None:
    session.info.pop(_BEFORE_KEY, None)
