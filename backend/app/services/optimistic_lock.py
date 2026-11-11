"""Compare-and-set on field-data writes (H8.2 · S2-63).

The failure this prevents is a **silent lost update**. Two enumerators survey
overlapping households, or one enumerator syncs from two devices; the second
write lands on top of the first, and nothing anywhere records that a version of
that record ever existed. The loss is invisible by construction: there is no
per-record version to compare after the fact, so it cannot even be found
retrospectively.

What was already here
---------------------
`calculations.geometry_version` is documented as an "optimistic-lock clock
(dedicated column, compare-and-set, atomic)" and the report treats it as
working. It is incremented in twelve places and **compared in none** -- no
request schema carries a version, and `If-Match` / `expected_version` appear
nowhere in the backend. The client side matches: `reconcileVersion()` is called
only from its own tests, and the `stale_server` modal keys off a state nothing
sets. It is a change counter used for cache invalidation, not a lock. So this
module is the first implementation, and geometry is wired into it rather than
assumed to be covered.

Why the check and the bump are one statement
--------------------------------------------
`SELECT` the version, compare it in Python, then `UPDATE` is the exact defect
H2.17 removed from the Redis idempotency service: it checks and then acts, so
two concurrent writers both read version 3, both pass, and both write. The lost
update it exists to prevent happens anyway, and now with a guard in front of it
that reports success.

So the comparison lives in the `WHERE` clause::

    UPDATE ... SET version = version + 1 WHERE id = :id AND version = :expected

The database arbitrates, in one statement, once -- across gunicorn workers and
across hosts. `rowcount == 0` is the conflict, and it cannot be raced.

Resolution policy, per domain
-----------------------------
The report asks for one, and it is deliberately NOT last-write-wins anywhere:

* **household** -- operator-resolved. A household record is a survey of a real
  family; two conflicting versions are two accounts of the same doorstep visit
  and a machine cannot pick between them. The 409 carries both versions so the
  client can show them side by side.
* **sampling** -- operator-resolved. A design change alters which plots get
  visited; silently taking one is a change to the field programme nobody
  approved.
* **inventory** -- refuse and resync. The batch operations are derived from an
  upload, so the safe move is to re-read and re-apply rather than merge.
* **geometry** -- refuse. Already single-primary-writer by intent (the
  frontend's own comment says "never auto-rebase"); this makes the server
  enforce what the client only assumed.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..core.config import settings

logger = logging.getLogger(__name__)

# domain -> (table, version column, policy handed to the client on conflict)
DOMAINS: dict[str, tuple[str, str, str]] = {
    "household": ("household_information", "version", "operator_resolved"),
    "sampling": ("sampling_designs", "version", "operator_resolved"),
    "inventory": ("inventory_calculations", "version", "refuse_and_resync"),
    "geometry": ("calculations", "geometry_version", "refuse"),
    # The yearly activity plan line (YEARLY_ACTIVITIES plan §5.5). Two screens edit the same plan:
    # a stale save is refused with both versions, never a silent overwrite.
    "yearly_plan": ("proposed_yearly_activities", "version", "operator_resolved"),
}


class VersionConflict(HTTPException):
    """409 carrying BOTH versions.

    The report is specific about this: return both so the app can *present* a
    conflict rather than discard one side. A bare 409 tells a field device that
    something went wrong and leaves it with no way to show the enumerator what
    changed -- which in practice means the retry loop discards a side anyway.
    """

    def __init__(self, domain: str, expected: int, actual: int, policy: str):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VERSION_CONFLICT",
                "message": (
                    "This record was changed by someone else while you were "
                    "editing it. Your version and the current one differ."
                ),
                "domain": domain,
                "your_version": expected,
                "current_version": actual,
                "resolution": policy,
            },
        )


def current_version(db: Session, domain: str, row_id: Any) -> Optional[int]:
    """The stored version, or None when the row is gone."""
    table, column, _ = DOMAINS[domain]
    result = db.execute(
        text(
            f"SELECT {column} FROM public.{table} WHERE id = :id"
        ),  # noqa: S608 -- table/column from DOMAINS, never from a request
        {"id": str(row_id)},
    ).first()
    return None if result is None else int(result[0])


def record_derived_write(db: Session, domain: str, row_id: Any, reason: str) -> None:
    """Declare a write that is NOT a user edit, so G-SYNC-2 permits it.

    Some writes to a versioned row are derived data, not somebody's decision --
    caching computed sample points onto the design that produced them, for
    instance. Two things are true of those and of no user edit:

    * bumping the version would be wrong. A client holding version 4 would get
      a 409 on its next write because somebody else *viewed* the record, which
      is a conflict that did not happen.
    * the guard cannot tell them apart on its own. It inspects the row, not the
      intent, so without a way to say so it would either refuse a legitimate
      cache write or be switched off entirely.

    So the intent is declared here, by name and with a reason, and logged. An
    unguarded write is now either through `check_and_bump` or through this --
    never through neither, and never through silence.
    """
    if domain not in DOMAINS:
        raise KeyError(f"unknown optimistic-lock domain: {domain!r}")
    table, _column, _policy = DOMAINS[domain]
    from .optimistic_lock_guard import record_lock_taken  # noqa: PLC0415

    record_lock_taken(db, table, row_id)
    logger.debug(
        "optimistic_lock: derived write to %s/%s (%s) - version not bumped",
        domain,
        row_id,
        reason,
    )


def check_and_bump(
    db: Session,
    domain: str,
    row_id: Any,
    expected: Optional[int],
    *,
    required: Optional[bool] = None,
) -> int:
    """Take the record at `expected`, bump it, and return the new version.

    Raises `VersionConflict` (409) when someone else moved it first, and 404
    when the row does not exist.

    `expected is None` means the caller sent no version. That is accepted and
    logged rather than refused, because the web frontend sends none today and
    refusing would break the live application to protect a mobile client that
    does not exist yet -- the same call H2.17 made for `Idempotency-Key`. Set
    `OPTIMISTIC_LOCK_REQUIRE_VERSION` to turn it into a 428.
    """
    if domain not in DOMAINS:
        raise KeyError(f"unknown optimistic-lock domain: {domain!r}")
    table, column, policy = DOMAINS[domain]

    # Tell the G-SYNC-2 guard this row's version was taken in this transaction.
    # Imported here rather than at module scope: the guard imports DOMAINS from
    # this module, and doing it the other way at import time is a cycle.
    from .optimistic_lock_guard import record_lock_taken  # noqa: PLC0415

    record_lock_taken(db, table, row_id)
    if required is None:
        required = settings.OPTIMISTIC_LOCK_REQUIRE_VERSION

    if expected is None:
        if required:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail={
                    "code": "VERSION_REQUIRED",
                    "message": "This endpoint requires the record's current version.",
                    "domain": domain,
                },
            )
        # Not silent: an unguarded write to a field-data record is exactly what
        # this task exists to find, so it is visible in the log rather than
        # assumed away. With H3.9 in place the line carries the correlation id,
        # so it can be tied back to the request that made it.
        logger.info(
            "optimistic_lock: no version supplied for %s/%s - write is unguarded",
            domain,
            row_id,
        )
        bumped = db.execute(
            text(
                f"UPDATE public.{table} SET {column} = {column} + 1 "  # noqa: S608 -- identifiers come from DOMAINS
                f"WHERE id = :id RETURNING {column}"
            ),
            {"id": str(row_id)},
        ).first()
        if bumped is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
        return int(bumped[0])

    # The whole mechanism is this statement. The comparison is in the WHERE
    # clause, so no other writer can slip between the check and the write.
    bumped = db.execute(
        text(
            f"UPDATE public.{table} SET {column} = {column} + 1 "  # noqa: S608 -- identifiers come from DOMAINS
            f"WHERE id = :id AND {column} = :expected RETURNING {column}"
        ),
        {"id": str(row_id), "expected": expected},
    ).first()
    if bumped is not None:
        return int(bumped[0])

    # Zero rows updated: either the row is gone, or somebody moved it first.
    # Distinguishing the two matters -- a client that deleted a household and a
    # client that lost a race need different things.
    actual = current_version(db, domain, row_id)
    if actual is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    logger.warning(
        "optimistic_lock: conflict on %s/%s - client held %s, current is %s",
        domain,
        row_id,
        expected,
        actual,
    )
    raise VersionConflict(domain, expected, actual, policy)
