"""Delete the calculations a test committed, so they cannot pollute later tests.

The test database is created once per session and `client` commits, so a
forest committed by one test is still there for every later one. Anything that
looks at *neighbouring* forests (the boundary overlap gate, boundary clipping)
then behaves differently depending on which tests ran before it. A test module
that uses fixed coordinates calls `purge_calculations` from a teardown fixture.
"""

from sqlalchemy import text

_NON_CASCADE_REFS = text(
    """
    SELECT c.conrelid::regclass::text AS tbl, a.attname AS col
      FROM pg_constraint c
      JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
     WHERE c.contype = 'f'
       AND c.confrelid = 'public.calculations'::regclass
       AND c.confdeltype IN ('a', 'r')
    """
)


def purge_calculations(db, calc_ids):
    """Remove the given calculations and every row that blocks their deletion."""
    ids = [str(i) for i in calc_ids]
    if not ids:
        return
    db.rollback()
    for tbl, col in db.execute(_NON_CASCADE_REFS).fetchall():
        db.execute(
            text(f"DELETE FROM {tbl} WHERE {col} = ANY(CAST(:ids AS uuid[]))"),
            {"ids": ids},
        )
    db.execute(
        text("DELETE FROM calculations WHERE id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": ids},
    )
    db.commit()
