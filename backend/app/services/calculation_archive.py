"""Deleting a calculation archives it. Nothing is permanently destroyed.

The owner's decision, 2026-08-27: a deleted calculation is kept "in another
table in the intact way, separated from all other processes, like it is dead."
No permanent delete. A super admin may export the archive, because the data may
matter for a future use case; there is deliberately no restore path.

Why this also fixes the delete bug
----------------------------------
Deleting a calculation used to fail outright:

    ForeignKeyViolation: update or delete on table "calculations" violates
    foreign key constraint "structure_lock_audits_calculation_id_fkey"

Nine of the 33 foreign keys pointing at `calculations.id` were `NO ACTION`, so
any calculation that had ever been submitted -- which writes
`calculation_audit_log` -- could not be deleted at all. Fixing only the
constraint named in the error would have moved the failure to the next table of
the nine.

Cascading them is only safe **because of this module**: the rows are captured
here first, so the cascade destroys nothing that has not already been kept.
Archive-then-cascade, in that order, in one transaction.

Why the payload is built from the live foreign-key graph
--------------------------------------------------------
The tables are not listed. They are discovered from `information_schema` at
call time: every table with a foreign key to `calculations.id`, whatever it is
called. A table added next month is archived on the day it is added, without
anybody remembering this file exists.

A hand-kept list is the failure this codebase keeps finding -- `SUB_ROUTERS`,
the idempotency call sites, `NEPAL_BOUNDS` wired to one path of two. A list
that must be maintained is a list that silently goes stale, and here staleness
means data is destroyed rather than archived.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Bumped when the payload's shape changes, so a reader years from now can tell
# which layout it is looking at rather than guessing from the keys present.
PAYLOAD_SCHEMA_VERSION = 1

# Tables whose rows reference a calculation but are not that calculation's
# data: they belong to the system, not to the forest. Archiving them would
# duplicate rows that still exist and still matter elsewhere.
NOT_THE_CALCULATIONS_DATA: frozenset[str] = frozenset()


def referencing_tables(db: Session) -> list[tuple[str, str]]:
    """[(table, column)] for every FK pointing at `calculations.id`.

    Read from the database rather than from a list in this file. See the module
    docstring: a maintained list goes stale, and staleness here loses data.
    """
    rows = db.execute(
        text(
            """
        SELECT DISTINCT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON kcu.constraint_name = tc.constraint_name
         AND kcu.table_schema = tc.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
          AND ccu.table_name = 'calculations'
          AND ccu.column_name = 'id'
        ORDER BY tc.table_name
    """
        )
    ).fetchall()
    return [(r[0], r[1]) for r in rows if r[0] not in NOT_THE_CALCULATIONS_DATA]


def _rows_as_dicts(
    db: Session, table: str, column: str, calc_id: UUID
) -> list[dict[str, Any]]:
    """Every row of `table` belonging to this calculation, JSON-safe.

    Geometry columns are rendered as WKT rather than the binary EWKB the driver
    returns: a payload nobody can read is not an archive, and WKT survives a
    PostGIS version change in a way a binary blob does not.
    """
    geom_cols = {
        r[0]
        for r in db.execute(
            text(
                """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name=:t
              AND udt_name IN ('geometry','geography')
        """
            ),
            {"t": table},
        )
    }
    selected = "*"
    if geom_cols:
        others = [
            r[0]
            for r in db.execute(
                text(
                    """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='public' AND table_name=:t
                ORDER BY ordinal_position
            """
                ),
                {"t": table},
            )
            if r[0] not in geom_cols
        ]
        parts = [f'"{c}"' for c in others]
        parts += [f'ST_AsText("{g}") AS "{g}"' for g in sorted(geom_cols)]
        selected = ", ".join(parts)

    result = db.execute(
        text(
            f'SELECT {selected} FROM public."{table}" WHERE "{column}" = :cid'
        ),  # noqa: S608 -- identifiers come from information_schema, never a request
        {"cid": str(calc_id)},
    )
    return [{k: _jsonable(v) for k, v in row._mapping.items()} for row in result]


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def build_payload(db: Session, calc_id: UUID) -> dict[str, Any]:
    """Everything belonging to this calculation, as one JSON document."""
    calc_rows = _rows_as_dicts(db, "calculations", "id", calc_id)
    if not calc_rows:
        raise ValueError(f"calculation {calc_id} does not exist")

    related: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for table, column in referencing_tables(db):
        try:
            rows = _rows_as_dicts(db, table, column, calc_id)
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- one unreadable table must not lose the rest
            # Recorded IN the payload, not only in the log: whoever opens this
            # archive years from now needs to know a table was missed, and a log
            # line from today will not be there.
            related[f"__unreadable__{table}"] = [{"error": str(exc)[:300]}]
            logger.error(
                "archive: could not read %s for calculation %s: %s",
                table,
                calc_id,
                exc,
                exc_info=True,
            )
            continue
        if rows:
            related[table] = rows
            total += len(rows)

    return {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "calculation": calc_rows[0],
        "related": related,
        "counts": {
            "tables": len(related),
            "rows": total,
        },
    }


def archive_calculation(
    db: Session, calc_id: UUID, user_id: UUID, user_role: str, reason: str | None = None
) -> UUID:
    """Snapshot the calculation into `deleted_calculations`. Returns its id.

    Called BEFORE the delete, in the same transaction, so the two either both
    happen or neither does. An archive written in a separate transaction could
    be committed while the delete fails, leaving a live calculation and a
    tombstone claiming it is gone.
    """
    payload = build_payload(db, calc_id)
    archive_id = uuid4()
    calc = payload["calculation"]

    db.execute(
        text(
            """
        INSERT INTO public.deleted_calculations
            (id, original_calculation_id, forest_name, owner_user_id,
             payload, row_count, table_count, deleted_by, deleted_by_role,
             reason, deleted_at)
        VALUES
            (:id, :orig, :forest_name, :owner, CAST(:payload AS jsonb),
             :rows, :tables, :by, :role, :reason, now())
    """
        ),
        {
            "id": str(archive_id),
            "orig": str(calc_id),
            # Denormalised on purpose: a super admin looking for "that Rukum forest
            # somebody deleted last year" should not have to grep a JSONB column.
            "forest_name": calc.get("forest_name"),
            "owner": calc.get("user_id"),
            "payload": json.dumps(payload, ensure_ascii=False),
            "rows": payload["counts"]["rows"],
            "tables": payload["counts"]["tables"],
            "by": str(user_id),
            "role": user_role,
            "reason": reason,
        },
    )

    logger.info(
        "archive: calculation %s (%s) archived as %s — %d rows across %d tables",
        calc_id,
        calc.get("forest_name"),
        archive_id,
        payload["counts"]["rows"],
        payload["counts"]["tables"],
    )
    return archive_id
