"""Create op_template_audit (append-only lifecycle trail).

Revision ID: 068_op_template_audit
Revises: 067_op_plan_kinds
Create Date: 2026-08-31

OP multi-template plan, Phase 0 (OP_MULTI_TEMPLATE_PLAN.md §3.3).

One row per lifecycle transition, written through a single funnel in a later
phase. Phase 0 creates the table and backfills the transitions that can be
inferred from the legacy approval columns.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "068_op_template_audit"
down_revision = "067_op_plan_kinds"
branch_labels = None
depends_on = None

SCHEMA = "public"


def upgrade() -> None:
    op.create_table(
        "op_template_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("template_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("public.op_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("public.users.id"), nullable=True),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_public_op_template_audit_template_id",
        "op_template_audit", ["template_id"], schema=SCHEMA,
    )

    # Backfill inferable history from the legacy approval columns.
    op.execute(
        """
        INSERT INTO public.op_template_audit
            (template_id, actor_id, action, from_status, to_status, note, version, created_at)
        SELECT id, approved_by, 'approve_publish', NULL, 'published',
               NULLIF(approval_note, ''), published_version,
               COALESCE(published_at, approved_at, updated_at)
        FROM public.op_templates
        WHERE status = 'published' AND approved_by IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO public.op_template_audit
            (template_id, actor_id, action, from_status, to_status, note, version, created_at)
        SELECT id, approved_by, 'reject', NULL, 'rejected',
               NULLIF(approval_note, ''), version, updated_at
        FROM public.op_templates
        WHERE status = 'rejected'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_public_op_template_audit_template_id",
                  table_name="op_template_audit", schema=SCHEMA)
    op.drop_table("op_template_audit", schema=SCHEMA)
