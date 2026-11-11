"""Keep the fire lines in step with the forest by themselves (owner option B, 2026-10-19).

The fire lines are derived from the boundary, the units and the sub-areas. Rather than wiring a call into every code path that
can change one of them (and missing the next one), the ORM reports the change: a mapper event notes the forest, and when that
session COMMITS a background thread runs ``sync_fire_lines`` for it. Same pattern as ``user_group_auto_analysis``.

* One run per forest at a time; a change that arrives while it runs triggers one more run afterwards.
* A short delay first, so a burst of edits (dragging a vertex, an import) is one run.
* ``sync_fire_lines`` skips quickly when its inputs are unchanged (a stored signature), so a liberal trigger is cheap.
* The sync's own commit sets ``session.info['fire_line_sync']`` and is ignored here, so it cannot re-trigger itself.
* Disabled under pytest, where a thread must not reach the real database.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from sqlalchemy import event
from sqlalchemy.orm import Session, object_session
from sqlalchemy.orm.attributes import get_history

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock

logger = logging.getLogger(__name__)

_DIRTY_KEY = "fire_line_dirty_calcs"
DELAY_S = 3.0
_guard = threading.Lock()
_running: set[str] = set()
_pending: set[str] = set()


def _enabled() -> bool:
    return "PYTEST_CURRENT_TEST" not in os.environ


def _run(calculation_id: str) -> None:
    from app.core.database import SessionLocal
    from app.services.fire_line_service import sync_fire_lines
    from app.services.river_bank_service import sync_river_banks

    while True:
        time.sleep(DELAY_S)  # let the edit that triggered us (and any that follow at once) finish
        db = SessionLocal()
        try:
            # the two kinds are independent: a refusal or an error in one must not stop the other
            for label, run in (("fire lines", sync_fire_lines), ("river banks", sync_river_banks)):
                try:
                    logger.info("%s for %s: %s", label, calculation_id, run(db, calculation_id))
                except Exception:  # noqa: BLE001 -- background thread: log, then go on; the next change retries
                    logger.exception("%s sync failed for %s", label, calculation_id)
                    db.rollback()
        finally:
            db.close()
        with _guard:
            if calculation_id in _pending:
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
    threading.Thread(target=_run, args=(calculation_id,), name=f"fire-line-sync-{calculation_id}", daemon=True).start()


def _note(session: Session | None, calculation_id) -> None:
    if session is None or calculation_id is None or session.info.get("fire_line_sync"):
        return
    session.info.setdefault(_DIRTY_KEY, set()).add(str(calculation_id))


def _calc_changed(mapper, connection, target: Calculation) -> None:
    # the boundary, the geometry clock every geometry writer bumps, or result_data (which holds the sub-areas)
    if any(get_history(target, attr).has_changes() for attr in ("boundary_geom", "geometry_version", "result_data")):
        _note(object_session(target), target.id)


def _block_changed(mapper, connection, target: ForestBlock) -> None:
    # a unit's outline or name; the many other columns (dominant_*, elevation_*) are analysis results and do not move a boundary
    if any(get_history(target, attr).has_changes() for attr in ("geometry", "name", "block_name", "working_circle")):
        _note(object_session(target), target.calculation_id)


def _block_gone(mapper, connection, target: ForestBlock) -> None:
    _note(object_session(target), target.calculation_id)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    for calc_id in session.info.pop(_DIRTY_KEY, set()):
        schedule(calc_id)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_DIRTY_KEY, None)


event.listen(Calculation, "after_update", _calc_changed)
event.listen(ForestBlock, "after_insert", _block_gone)
event.listen(ForestBlock, "after_delete", _block_gone)
event.listen(ForestBlock, "after_update", _block_changed)
