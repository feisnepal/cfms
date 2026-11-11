"""Drop the archive of deleted forests (work package FD, FD-10).

Revision ID: 093_drop_deleted_calculations
Revises: 092_forest_delete_cascades
Create Date: 2026-09-21

Owner's rule, 2026-09-21 (replaces the 2026-08-27 "archive, never destroy" rule): if a forest is
deleted, ALL data associated with it is deleted. The archive table is exactly such data, so on the
owner's instruction ("delete them all") its 79 records -- copies of forests deleted between
2026-08-27 and 2026-09-17 -- are deleted with the table.

Migration 056 warned that its ``ON DELETE CASCADE`` foreign keys were "safe only because the archive
runs first". That worry belonged to the old rule; under the new one destroying a deleted forest's data
is the intended outcome, so nothing remains to protect.

The application no longer reads or writes this table: ``services/calculation_archive.py`` was removed
in migration 092's work, and the two super-admin endpoints that listed and exported the archive
(``GET /calculations/archived`` and ``.../archived/{id}/export``) and the ``DeletedCalculation`` model
are removed with this migration.

``downgrade`` recreates the table **empty** (same columns and indexes as migration 056). The 79
snapshots are not recoverable from the database once this has run; the owner holds a separate backup.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "093_drop_deleted_calculations"
down_revision = "092_forest_delete_cascades"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The indexes go with the table.
    op.execute("DROP TABLE IF EXISTS public.deleted_calculations")


def downgrade() -> None:
    op.create_table(
        "deleted_calculations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "original_calculation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("forest_name", sa.String(255), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("table_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_by_role", sa.String(32), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="public",
    )
    op.create_index(
        "ix_deleted_calculations_deleted_at",
        "deleted_calculations",
        ["deleted_at"],
        schema="public",
    )
