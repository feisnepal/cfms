"""The schema half of the forest-delete rule (work package FD, FD-8).

Owner's rule, 2026-09-21: if a forest is deleted, all data associated with it is deleted.

``test_forest_delete_removes_everything.py`` proves that behaviour for the data it seeds. This
file guards the *schema*, so a table added later cannot quietly break the rule:

- every foreign key that points at ``calculations`` must be ``ON DELETE CASCADE``;
- every column named ``calculation_id`` must be a real foreign key, except the tables listed in
  ``app/core/forest_delete_rules.py`` (append-only provenance and an audit log, kept on purpose).

Only links to ``calculations`` are covered here. Links to a forest's *units* (for example a tree's
unit) may be ``SET NULL`` -- that row still belongs to the forest through its own link to it.

If this test fails after you add a table: make the link ``ON DELETE CASCADE`` (and NOT NULL if the row
is meaningless without a forest). Do not add the table to the exception list to make it pass -- a new
exception is an owner decision.
"""

from sqlalchemy import text

from app.core.forest_delete_rules import FOREST_DELETE_EXCEPTIONS

_DELETE_RULES = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}


def test_every_foreign_key_to_calculations_cascades(db):
    rows = db.execute(
        text(
            """
        SELECT c.conrelid::regclass::text AS tbl, a.attname AS col, c.confdeltype AS rule
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.contype = 'f' AND c.confrelid = 'public.calculations'::regclass
        ORDER BY 1, 2
    """
        )
    ).fetchall()
    assert rows, "expected foreign keys to calculations"
    wrong = [
        f"{r.tbl}.{r.col} is {_DELETE_RULES[r.rule]}" for r in rows if r.rule != "c"
    ]
    assert not wrong, "a forest delete would not remove these rows: " + "; ".join(wrong)


def test_every_calculation_id_column_is_a_foreign_key_or_a_documented_exception(db):
    rows = db.execute(
        text(
            """
        SELECT c.table_name
        FROM information_schema.columns c
        WHERE c.table_schema = 'public' AND c.column_name = 'calculation_id'
          AND NOT EXISTS (
              SELECT 1 FROM pg_constraint k
              JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = ANY(k.conkey)
              WHERE k.contype = 'f' AND k.conrelid = ('public.' || quote_ident(c.table_name))::regclass
                AND a.attname = 'calculation_id'
          )
        ORDER BY 1
    """
        )
    ).fetchall()
    unlinked = sorted({r[0] for r in rows} - set(FOREST_DELETE_EXCEPTIONS))
    assert not unlinked, (
        "these tables carry a forest id with no foreign key, so their rows survive a forest delete: "
        + ", ".join(unlinked)
    )


def test_the_documented_exceptions_still_exist_and_are_explained(db):
    for table, reason in FOREST_DELETE_EXCEPTIONS.items():
        assert reason.strip(), f"{table} is an exception without a reason"
        assert db.execute(
            text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
        ).scalar(), f"{table} is listed as an exception but no longer exists -- remove it from the list"
