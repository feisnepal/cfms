"""Who read the household data (H8.7 · S2-68).

`household_information` holds caste classification and precise coordinates
(S1-53) for real families. The write side has an audit trail; the read side had
nothing at all, so there was no record of who had seen or exported those
records. For special-category data an access log is normally a hard requirement
rather than a nicety, and this is one of the two things S2-68 asks for beyond
wiring the geometry audit.

Design notes worth keeping
--------------------------
**Reads are frequent, so this must be cheap and unbreakable.** A logging call
that fails a listing request would make the application worse, not more
accountable -- the same trade the geometry audit makes. Every failure here is
swallowed and logged.

**The kind of access is recorded, not just "read".** Opening one household and
exporting all 298 are different events with different consequences, and a log
that flattens them cannot answer the question anybody will actually ask.

**No foreign key to `calculations`.** Migration 057 made those keys cascade, so
a foreign key here would delete the record of who read a forest's household data
at the moment somebody deletes the forest -- which is precisely when that record
matters.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# What was seen. Kept small and closed: an open vocabulary becomes a dozen
# spellings of "list" and stops being queryable.
ACCESS_LIST = "list"
ACCESS_DETAIL = "detail"
ACCESS_EXPORT = "export"
ACCESS_SUMMARY = "summary"

VALID_ACCESS_TYPES = frozenset(
    {ACCESS_LIST, ACCESS_DETAIL, ACCESS_EXPORT, ACCESS_SUMMARY}
)


def record_household_access(
    db: Session,
    access_type: str,
    calculation_id: Optional[UUID] = None,
    household_id: Optional[UUID] = None,
    record_count: Optional[int] = None,
) -> None:
    """Record one read of household data. Never raises.

    Identity comes from the request context (H8.7), so callers do not have to
    thread `Request` and `current_user` down to every read endpoint -- the habit
    that left `geometry_audits` empty for five months.
    """
    try:
        if access_type not in VALID_ACCESS_TYPES:
            logger.warning("household access log: unknown access_type %r", access_type)
            return

        from ..core.correlation import get_correlation_id
        from ..core.request_context import get_identity

        identity = get_identity()

        db.execute(
            text(
                """
            INSERT INTO public.household_access_log
                (calculation_id, household_id, access_type, record_count,
                 user_id, ip_address, client_type, correlation_id)
            VALUES
                (CAST(:calc AS uuid), CAST(:hh AS uuid), :atype, :count,
                 CAST(:uid AS uuid), :ip, :client, :corr)
        """
            ),
            {
                "calc": str(calculation_id) if calculation_id else None,
                "hh": str(household_id) if household_id else None,
                "atype": access_type,
                "count": record_count,
                "uid": identity.user_id,
                "ip": identity.ip_address,
                "client": identity.client_type,
                "corr": get_correlation_id(),
            },
        )
        # Not committed here. The caller's request commits, or does not -- and a
        # read endpoint that has no other writes will have its transaction
        # closed by the session dependency, which flushes this. Committing
        # inside would open a second transaction on a read path for the sake of
        # a log line.
    except Exception:  # noqa: BLE001 -- a read must never fail because of its own log
        logger.error(
            "household access log: could not record a %s read (calc=%s household=%s)",
            access_type,
            calculation_id,
            household_id,
            exc_info=True,
        )
