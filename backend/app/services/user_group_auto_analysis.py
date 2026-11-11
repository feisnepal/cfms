"""Re-analyse the user group by itself whenever its polygons change (owner, 2026-10-05).

Drawing, importing, auto-buffering, CUTTING, merging, editing vertices, dividing, pasting or restoring all change
`user_group_extents` rows. Rather than wiring a call into every one of those code paths (cutting was missed, and
the next path would be too), the ORM reports the change: a mapper event notes the forest, and when that session
COMMITS a background thread re-runs `analyze_all` for it. One run per forest at a time; edits that arrive while
it runs trigger one more run afterwards.

The analysis never writes to `user_group_extents`, so it cannot re-trigger itself. Bulk `Query.delete()` bypasses
mapper events on purpose: the replace-then-create flows (import, auto-buffer) insert a row right after.
Disabled under pytest, where a thread must not reach the real database.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import event, text
from sqlalchemy.orm import Session, object_session

from app.models.user_group import UserGroupExtent

logger = logging.getLogger(__name__)

_DIRTY_KEY = "user_group_dirty_calcs"
_guard = threading.Lock()
_running: set[str] = set()
_pending: set[str] = set()


def _enabled() -> bool:
    return "PYTEST_CURRENT_TEST" not in os.environ


# ── the analysis status, stored with the calculation ───────────────────────────────────────────────────────────────────────────────────
#
# Kept in `calculations.result_data['user_group_analysis_status']` (not in this process's memory): the server may run several workers and a
# restart must not forget it. Written with one atomic `jsonb_set`, so it cannot clobber the other keys other writers put in `result_data`.
# Shape: {state: running|done|failed|skipped, started_at, finished_at, message, steps: {settlements, land_cover}}.
STATUS_KEY = "user_group_analysis_status"
STALE_RUNNING_AFTER = timedelta(minutes=15)  # a 'running' that old means the worker died; report it instead of spinning forever


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_status(calculation_id: str, db: Optional[Session] = None, **fields) -> None:
    """Merge ``fields`` into the stored status (atomic; never raises into the analysis)."""
    from app.core.database import SessionLocal

    own = db is None
    session = db or SessionLocal()
    try:
        session.execute(
            text(
                "UPDATE calculations SET result_data = jsonb_set(COALESCE(result_data, '{}'::jsonb), '{" + STATUS_KEY + "}', "
                "COALESCE(result_data -> '" + STATUS_KEY + "', '{}'::jsonb) || CAST(:patch AS jsonb), true) WHERE id = :c"
            ),
            {"patch": json.dumps(fields, default=str), "c": calculation_id},
        )
        session.commit()
    except Exception:  # noqa: BLE001 -- a status write must never break (or be mistaken for) the analysis itself
        logger.exception("could not write the user-group analysis status for %s", calculation_id)
        session.rollback()
    finally:
        if own:
            session.close()


def read_status(result_data: Optional[dict]) -> dict:
    """The stored status as the API reports it: ``{state: 'idle'}`` when nothing ever ran; a stale 'running' is reported as failed."""
    st = dict((result_data or {}).get(STATUS_KEY) or {})
    if not st:
        return {"state": "idle", "steps": {}}
    if st.get("state") == "running":
        try:
            started = datetime.fromisoformat(str(st.get("started_at")))
            if datetime.now(timezone.utc) - started > STALE_RUNNING_AFTER:
                st.update(state="failed", message="interrupted")
        except (TypeError, ValueError):
            st.update(state="failed", message="interrupted")
    st.setdefault("steps", {})
    return st


async def _analyse(db: Session, calculation_id: str) -> None:
    """Settlements first, then land cover & biomass (owner, 2026-10-12: nothing for the user to press)."""
    from app.services.user_group_analysis import UserGroupAnalysisService, UserGroupTooLarge

    svc = UserGroupAnalysisService(db)
    steps: dict = {}
    write_status(calculation_id, db, steps=steps)
    try:
        await svc.analyze_all(calculation_id)
        steps["settlements"] = "done"
    except UserGroupTooLarge as e:
        write_status(calculation_id, db, state="skipped", finished_at=_now(), message=str(e), steps=steps)
        logger.warning("user-group auto-analysis skipped for %s: %s", calculation_id, e)
        return
    except Exception as e:  # noqa: BLE001 -- recorded as the status; Re-analyze stays available
        logger.exception("user-group auto-analysis failed for %s", calculation_id)
        steps["settlements"] = "failed"
        write_status(calculation_id, db, state="failed", finished_at=_now(), message=str(e)[:300], steps=steps)
        return
    write_status(calculation_id, db, steps=steps)
    try:
        await svc.analyze_land_cover(calculation_id, force_refresh=True)
        steps["land_cover"] = "done"
        write_status(calculation_id, db, state="done", finished_at=_now(), message=None, steps=steps)
    except Exception as e:  # noqa: BLE001 -- the settlement analysis is still good; say which step did not run
        logger.warning("user-group land cover not computed for %s: %s", calculation_id, e)
        steps["land_cover"] = "failed"
        write_status(calculation_id, db, state="done", finished_at=_now(), message=str(e)[:300], steps=steps)


def _run(calculation_id: str) -> None:
    from app.core.database import SessionLocal

    while True:
        write_status(calculation_id, state="running", started_at=_now(), finished_at=None, message=None, steps={})
        db = SessionLocal()
        try:
            asyncio.run(_analyse(db, calculation_id))
            logger.info("user-group auto-analysis finished for %s", calculation_id)
        except Exception as e:  # noqa: BLE001 -- background thread: log and record, then stop; Re-analyze remains available
            logger.exception("user-group auto-analysis crashed for %s", calculation_id)
            write_status(calculation_id, state="failed", finished_at=_now(), message=str(e)[:300])
        finally:
            db.close()
        with _guard:
            if calculation_id in _pending:  # edited again while we ran: go once more
                _pending.discard(calculation_id)
                continue
            _running.discard(calculation_id)
            return


def schedule(calculation_id: str) -> None:
    if not _enabled():
        return
    with _guard:
        if calculation_id in _running:
            _pending.add(calculation_id)
            return
        _running.add(calculation_id)
    write_status(calculation_id, state="running", started_at=_now(), finished_at=None, message=None, steps={})  # visible the moment the save returns
    threading.Thread(target=_run, args=(calculation_id,), name=f"ug-analysis-{calculation_id}", daemon=True).start()


def _mark(mapper, connection, target) -> None:
    session = object_session(target)
    if session is not None and target.calculation_id is not None:
        session.info.setdefault(_DIRTY_KEY, set()).add(str(target.calculation_id))


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    for calc_id in session.info.pop(_DIRTY_KEY, set()):
        schedule(calc_id)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_DIRTY_KEY, None)


for _evt in ("after_insert", "after_update", "after_delete"):
    event.listen(UserGroupExtent, _evt, _mark)
