"""add translations table (DB-backed i18n overrides)

Revision ID: 045_add_translations_table
Revises: 044_auto_block_mmu_block_name
Create Date: 2026-08-16

Phase 3: the super-admin translation editor persists bilingual overrides in a
`translations` table. The frontend keeps its bundled en/ne.json defaults and
merges only `is_override=true` rows at boot (the overlay endpoint). `history`
is an append-only JSONB array of `{ts, user, note, ...}` snapshots written on
each edit. `source_file` records provenance (`bundle` | `csv` | `editor`).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

revision = "045_add_translations_table"
down_revision = "044_auto_block_mmu_block_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "translations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("en", sa.Text(), nullable=True),
        sa.Column("ne", sa.Text(), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("source_file", sa.String(length=16), nullable=False, server_default="bundle"),
        sa.Column("is_override", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=True),
        sa.Column("history", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    op.create_index("ix_translations_key", "translations", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_translations_key", table_name="translations")
    op.drop_table("translations")