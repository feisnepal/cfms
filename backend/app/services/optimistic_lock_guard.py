"""Gate G-SYNC-2: a versioned record cannot be updated without the lock.

`optimistic_lock.check_and_bump` is only a guard where somebody calls it. Every
task in this phase has found the same failure -- idempotency reaching 2 of 194
routes, `correlation_id` never set on a record, `log_geometry_audit` with 0
rows after five months, and `geometry_version` bumped twelve times and compared
never. In each case the mechanism was sound and its reach was not, because
reach depended on memory.

So this does not check that the lock is *called*. It checks that a versioned
row cannot be written *without* it: a `before_flush` listener that raises when
a `UPDATE` is about to be emitted for a versioned model whose version was not
taken in this transaction.

**How the two halves meet.** `check_and_bump` records `(table, id)` on the
session; this listener looks for that record. A path that mutates a household
and commits without going through the lock raises `LockNotTakenError` at flush,
naming the row -- loudly, in development and in tests, rather than silently
losing somebody's field data in production.

Deletes are deliberately not covered. Deleting a record the other writer edited
is a different conflict with a different answer, and pretending a version
counter resolves it would be worse than leaving it visible. It belongs with the
per-domain policy work.

Enforcement follows `OPTIMISTIC_LOCK_ENFORCE_GUARD`, which defaults to true in
DEBUG and in tests and false in production -- a guard that turns a missed call
into a 500 for a field worker is not an improvement on the silent overwrite it
replaces. In production the same condition logs at ERROR with the correlation
id (H3.9), so the gap is findable without being fatal.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from ..core.config import settings
from .optimistic_lock import DOMAINS

logger = logging.getLogger(__name__)

# Domains whose version covers the WHOLE row, so any update to it is a write
# the lock should have taken.
#
# `geometry` is deliberately absent. Its counter lives on `calculations`, a row
# that also carries status, lifecycle state, boundary status and export status
# -- all updated constantly by paths that have nothing to do with geometry. The
# guard inspects the row, not the intent, so it cannot tell a boundary edit from
# a status transition and would fire on both. Geometry writes still take the
# lock through `check_and_bump(db, "geometry", ...)` at the endpoints that opt
# in; they simply are not policed here. Narrowing that is a real piece of work
# (a per-column concern, or geometry_version moved to its own row) and is not
# smuggled into this task.
GUARDED_DOMAINS = ("household", "sampling", "inventory", "yearly_plan")

_TABLE_TO_DOMAIN = {DOMAINS[d][0]: d for d in GUARDED_DOMAINS}

# The attribute `check_and_bump` stamps on the session.
_TAKEN = "_optimistic_lock_taken"


class LockNotTakenError(RuntimeError):
    """A versioned row was about to be updated without taking its version."""


def record_lock_taken(session: Session, table: str, row_id: Any) -> None:
    """Called by `check_and_bump`. Scoped to the session, so it cannot leak."""
    taken = getattr(session, _TAKEN, None)
    if taken is None:
        taken = set()
        setattr(session, _TAKEN, taken)
    taken.add((table, str(row_id)))


def _enforcing() -> bool:
    configured = getattr(settings, "OPTIMISTIC_LOCK_ENFORCE_GUARD", None)
    return settings.DEBUG if configured is None else bool(configured)


def _guard(session: Session, flush_context, instances) -> None:
    taken = getattr(session, _TAKEN, set())
    for obj in session.dirty:
        table = getattr(getattr(obj, "__table__", None), "name", None)
        if table not in _TABLE_TO_DOMAIN:
            continue
        state = inspect(obj)
        # Only a real field change counts. An object can land in `session.dirty`
        # having been loaded and touched without anything actually differing,
        # and raising on that would make the guard fire on reads.
        changed = {
            attr.key
            for attr in state.attrs
            if attr.history.has_changes() and attr.key != "version"
        }
        if not changed:
            continue
        if (table, str(obj.id)) in taken:
            continue
        message = (
            f"{table} {obj.id} was updated without taking its version "
            f"(changed: {sorted(changed)}). Call "
            f"optimistic_lock.check_and_bump(db, "
            f"'{_TABLE_TO_DOMAIN[table]}', <id>, expected) first, or the write "
            f"can silently overwrite a concurrent edit."
        )
        if _enforcing():
            raise LockNotTakenError(message)
        logger.error("optimistic_lock guard: %s", message)


def install() -> None:
    """Idempotent, because `configure_logging`-style double calls happen."""
    if getattr(_guard, "_installed", False):
        return
    event.listen(Session, "before_flush", _guard)
    _guard._installed = True  # type: ignore[attr-defined]


install()
