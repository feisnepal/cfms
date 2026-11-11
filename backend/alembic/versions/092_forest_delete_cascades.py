"""Deleting a forest deletes everything that belongs to it (work package FD, FD-6).

Revision ID: 092_forest_delete_cascades
Revises: 091_yearly_plan_foundations
Create Date: 2026-09-21

Owner's rule, 2026-09-21 (replaces the 2026-08-27 "archive, never destroy" rule):
**if a forest is deleted, all data associated with it is deleted.**

Of the 33 foreign keys pointing at ``calculations`` 30 already cascaded. The rest did not, and one of
them is exactly how 77,560 trees outlived the forests they belonged to:

- ``inventory_calculations.calculation_id``        ``SET NULL``  -> ``CASCADE`` and ``NOT NULL``.
  Deleting a forest used to keep the inventory (and its trees, correction logs) as a forest-less orphan.
- ``field_inventory_calculations.calculation_id``  ``SET NULL``  -> ``CASCADE`` and ``NOT NULL``
  (same leak for its plots and block summaries).
- ``transactions.calculation_id``                  ``NO ACTION`` -> ``CASCADE``. ``NO ACTION`` would
  have *blocked* deleting a forest that had a transaction. (The table holds no rows; nothing is live.)
- ``op_data_cache.calculation_id``                 had **no foreign key at all** -> ``CASCADE``.

Rows that would violate the new rules are removed first, on purpose, because the rule says they must
not exist: inventories and field inventories with no forest, and cache rows whose forest is gone. The
database this ran against had none (the owner's clean-up on 2026-09-21 removed them); the counts are
logged.

Deliberately NOT touched (documented exceptions, ``app/core/forest_delete_rules.py``):
``document_issuances`` (append-only provenance) and ``household_access_log`` (audit trail).
"""

import logging

import sqlalchemy as sa
from alembic import op

revision = "092_forest_delete_cascades"
down_revision = "091_yearly_plan_foundations"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def _table_exists(table: str) -> bool:
    """`transactions` exists in the development database but is created by no migration (known
    schema drift), so a database built from migrations alone does not have it."""
    return (
        op.get_bind()
        .execute(
            sa.text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"}
        )
        .scalar()
    )


def _drop_foreign_keys_to_calculations(table: str) -> None:
    """Drop every foreign key from ``table`` to ``calculations`` whatever it is named."""
    op.execute(
        f"""
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'public.{table}'::regclass
                  AND contype = 'f'
                  AND confrelid = 'public.calculations'::regclass
            LOOP
                EXECUTE format('ALTER TABLE public.{table} DROP CONSTRAINT %I', r.conname);
            END LOOP;
        END $$;
        """
    )


def _link_to_calculations(table: str, ondelete: str | None) -> None:
    _drop_foreign_keys_to_calculations(table)
    op.create_foreign_key(
        f"{table}_calculation_id_fkey",
        table,
        "calculations",
        ["calculation_id"],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    bind = op.get_bind()

    # Rows that may not exist under the new rule. Removed, not "fixed": a forest-less inventory is
    # the very leak this migration closes.
    for table in ("inventory_calculations", "field_inventory_calculations"):
        removed = bind.execute(
            sa.text(f"DELETE FROM public.{table} WHERE calculation_id IS NULL")
        ).rowcount
        if removed:
            logger.warning("092: removed %s forest-less row(s) from %s", removed, table)
    removed = bind.execute(
        sa.text(
            "DELETE FROM public.op_data_cache "
            "WHERE calculation_id NOT IN (SELECT id FROM public.calculations)"
        )
    ).rowcount
    if removed:
        logger.warning("092: removed %s dangling row(s) from op_data_cache", removed)

    for table in ("inventory_calculations", "field_inventory_calculations"):
        _link_to_calculations(table, "CASCADE")
        op.alter_column(
            table,
            "calculation_id",
            existing_type=sa.dialects.postgresql.UUID(),
            nullable=False,
        )

    if _table_exists("transactions"):
        _link_to_calculations("transactions", "CASCADE")

    # op_data_cache never had a foreign key; its calculation_id is its primary key.
    op.create_foreign_key(
        "op_data_cache_calculation_id_fkey",
        "op_data_cache",
        "calculations",
        ["calculation_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "op_data_cache_calculation_id_fkey", "op_data_cache", type_="foreignkey"
    )

    if _table_exists("transactions"):
        _link_to_calculations("transactions", None)  # NO ACTION, as before

    for table in ("inventory_calculations", "field_inventory_calculations"):
        op.alter_column(
            table,
            "calculation_id",
            existing_type=sa.dialects.postgresql.UUID(),
            nullable=True,
        )
        _link_to_calculations(table, "SET NULL")
