"""Move six application tables out of the raster schema into public.

Revision ID: 051_app_tables_to_public
Revises: 050_refresh_token_rotation
Create Date: 2026-08-21

Why this migration exists (finding S1-74)
-----------------------------------------
``cf_db`` carries a database-level setting::

    search_path = rasters, public, sde

set for the GIS layers. An unqualified ``op.create_table`` lands in the FIRST
entry of that path, so every migration that created a table without naming a
schema put it in ``rasters`` — alongside ``dem``, ``slope`` and
``esa_world_cover``:

===========================  =====  ================================
table                        rows   created by
===========================  =====  ================================
translations                 536    045_add_translations_table
workspace_layers             23     dc0db1df3cc3
dbh_class_systems            5      DBH class system migration
digitize_audit_logs          5      042_digitize_audit_logs
dbh_classification_changes   0      DBH class system migration
refresh_tokens               0      050_refresh_token_rotation
===========================  =====  ================================

Nothing was broken by this at runtime, which is precisely why it survived for
months: ``public`` is second in the path, so every read resolves. ``users``
finds ``public.users``; ``translations`` finds ``rasters.translations``; both
work.

What it breaks is the guarantee Phase 1 exists to provide. A database built
from this chain on a clean server puts all six in ``public``, because the stock
search_path is ``"$user", public``. Two databases report the same revision from
``alembic current`` and have structurally different schemas — and the drift
tooling cannot see it, because the models are unqualified (H1.14) and therefore
match whichever schema the path happens to resolve to.

There is a second edge worth naming. ``dbh_classification_changes`` is the audit
trail H2.3 wired up so that DBH-class mutations stop being untraceable. An audit
table living in a raster schema is one that a ``public``-scoped backup, export
or retention sweep silently skips.

Safety
------
Each move is guarded on the table being in ``rasters`` and NOT already in
``public``, so this is a no-op on any database built from the chain, and
re-running it changes nothing. ``SET SCHEMA`` is a catalog update: it carries
indexes, constraints, sequences and data with the table and rewrites no rows,
so the 536 translations and 23 workspace layers move without being touched.

Foreign keys pointing INTO these tables, and out of them into ``public``, follow
the table by OID and need no repair.

The downgrade deliberately does nothing. Putting an application table back in a
raster schema is not a state worth being able to reach, and reversing the move
on a clean database would create the very defect this repairs.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '051_app_tables_to_public'
down_revision = '050_refresh_token_rotation'
branch_labels = None
depends_on = None

WRONG_SCHEMA = 'rasters'

# Ordered by row count so the log reads usefully if it stops part way.
MISPLACED = (
    'translations',
    'workspace_layers',
    'dbh_class_systems',
    'digitize_audit_logs',
    'dbh_classification_changes',
    'refresh_tokens',
)


def _schemas_holding(bind, table: str) -> set[str]:
    rows = bind.execute(
        sa.text(
            "SELECT n.nspname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = :t AND c.relkind = 'r'"
        ),
        {"t": table},
    )
    return {r[0] for r in rows}


def decide(table: str, schemas: set[str]) -> bool:
    """Whether `table` needs moving, given the schemas that hold it.

    Split out from `upgrade` so the decision can be tested without a database —
    the interesting case is the one that must never be reached silently.
    """
    if WRONG_SCHEMA not in schemas:
        # Built from the chain on a clean server, or already repaired.
        return False

    if 'public' in schemas:
        # Two copies. Which one is live depends on the search_path of whoever
        # wrote last, so guessing here could discard real rows. Refuse and let
        # a human look.
        raise RuntimeError(
            f"{table} exists in BOTH public and {WRONG_SCHEMA}. This migration "
            "will not guess which holds the live data. Compare row counts in "
            f"public.{table} and {WRONG_SCHEMA}.{table}, keep one, drop the "
            "other, then re-run."
        )

    return True


def upgrade() -> None:
    bind = op.get_bind()

    for table in MISPLACED:
        if decide(table, _schemas_holding(bind, table)):
            op.execute(f'ALTER TABLE {WRONG_SCHEMA}."{table}" SET SCHEMA public')


def downgrade() -> None:
    """Deliberately empty — see the module docstring."""
