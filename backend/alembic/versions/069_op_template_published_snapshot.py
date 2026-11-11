"""Add op_template_versions.is_published_snapshot.

Revision ID: 069_op_template_published_snapshot
Revises: 068_op_template_audit
Create Date: 2026-08-31

OP multi-template plan, Phase 0 (OP_MULTI_TEMPLATE_PLAN.md §3.6).

Marks the version row that was live when a template last entered `published`
status. Backfill is best-effort: a snapshot row for the current
published_version may not exist (snapshots historically captured the *prior*
tree on each edit), in which case nothing is flagged and the publish funnel
will create the snapshot on the next publish.
"""

import sqlalchemy as sa
from alembic import op

revision = "069_op_template_published_snapshot"
down_revision = "068_op_template_audit"
branch_labels = None
depends_on = None

TABLE = "op_template_versions"
SCHEMA = "public"
COLUMN = "is_published_snapshot"


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    return COLUMN in {c["name"] for c in inspector.get_columns(TABLE, schema=SCHEMA)}


def upgrade() -> None:
    if not _has_column():
        op.add_column(
            TABLE,
            sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
            schema=SCHEMA,
        )

    op.execute(
        """
        UPDATE public.op_template_versions v
        SET is_published_snapshot = TRUE
        FROM public.op_templates t
        WHERE v.template_id = t.id
          AND t.status = 'published'
          AND t.published_version IS NOT NULL
          AND v.version = t.published_version
        """
    )


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN, schema=SCHEMA)
