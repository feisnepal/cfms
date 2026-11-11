"""Add OP-template lifecycle + plan-kind columns and backfill status.

Revision ID: 066_op_template_lifecycle_columns
Revises: 065_add_template_designer_role
Create Date: 2026-08-31

OP multi-template plan, Phase 0 (OP_MULTI_TEMPLATE_PLAN.md §3.3 / §4).

Adds the columns for the single lifecycle state machine and the two-axis
plan kind. Phase 0 is inert: no application code reads `status` / `plan_kind`
yet — the legacy visibility / approval_status / is_active flags still drive
every endpoint. This migration only makes the columns exist and derives an
initial `status` from `approval_status` so a later phase can switch over
without a data gap.

Backfill:
    approval_status = 'approved'  -> published  (+ published_version/at/by)
    approval_status = 'pending'   -> in_review
    approval_status = 'rejected'  -> rejected
    otherwise                     -> draft
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "066_op_template_lifecycle_columns"
down_revision = "065_add_template_designer_role"
branch_labels = None
depends_on = None

TABLE = "op_templates"
SCHEMA = "public"

_NEW_COLUMNS = [
    sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
    sa.Column("plan_kind", sa.String(50), nullable=True),
    sa.Column("plan_regime", sa.String(30), nullable=True),
    sa.Column("plan_stage", sa.String(20), nullable=True),
    sa.Column("published_version", sa.Integer(), nullable=True),
    sa.Column("published_by", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("deprecated_by_template_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("retired_reason", sa.Text(), nullable=True),
    sa.Column("retired_by", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
]


def _existing_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns(TABLE, schema=SCHEMA)}


def upgrade() -> None:
    have = _existing_columns()
    for col in _NEW_COLUMNS:
        if col.name not in have:
            op.add_column(TABLE, col, schema=SCHEMA)

    # published_by / retired_by are FK-less by design (see model comment),
    # mirroring source_template_id / source_calculation_id on this table.

    op.execute(
        """
        UPDATE public.op_templates
        SET status = CASE
                WHEN approval_status = 'approved' THEN 'published'
                WHEN approval_status = 'pending'  THEN 'in_review'
                WHEN approval_status = 'rejected' THEN 'rejected'
                ELSE 'draft'
            END
        """
    )
    op.execute(
        """
        UPDATE public.op_templates
        SET published_version = version,
            published_at      = COALESCE(approved_at, updated_at),
            published_by      = approved_by
        WHERE status = 'published'
        """
    )


def downgrade() -> None:
    for col in reversed(_NEW_COLUMNS):
        op.drop_column(TABLE, col.name, schema=SCHEMA)
