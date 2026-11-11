"""Drop the legacy op_templates flags now derived from `status`.

Revision ID: 071_drop_op_template_legacy_flags
Revises: 070_backfill_template_cover_nodes
Create Date: 2026-08-31

OP multi-template plan, Phase 7 (OP_MULTI_TEMPLATE_PLAN.md §4 / §6).

`status` (migration 066) is now the single authority for a template's
lifecycle, and the API derives the old flags for response compatibility:

    is_active       = status in (published, deprecated)
    visibility      = global if public else private
    approval_status = draft->none / in_review->pending / rejected->rejected
                      / published|deprecated->approved / retired->none

`is_default` had no meaning left in the two-axis model — per-kind defaults
live in op_plan_kinds.default_template_id, and the seeded base is is_system.

`approval_note` is KEPT: it carries the reviewer's free-text reason, which is
not derivable from `status`.

Rollback re-creates the columns (nullable, default-filled); the per-row
values are not recoverable — see the plan's rollback note ("—").
"""

import sqlalchemy as sa
from alembic import op

revision = "071_drop_op_template_legacy_flags"
down_revision = "070_backfill_template_cover_nodes"
branch_labels = None
depends_on = None

TABLE = "op_templates"
SCHEMA = "public"
_DROP = ("is_active", "is_default", "visibility", "approval_status")


def _cols() -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(TABLE, schema=SCHEMA)}


def upgrade() -> None:
    have = _cols()
    for name in _DROP:
        if name in have:
            op.drop_column(TABLE, name, schema=SCHEMA)


def downgrade() -> None:
    have = _cols()
    if "visibility" not in have:
        op.add_column(TABLE, sa.Column("visibility", sa.String(20), nullable=False,
                                       server_default="private"), schema=SCHEMA)
    if "approval_status" not in have:
        op.add_column(TABLE, sa.Column("approval_status", sa.String(20), nullable=False,
                                       server_default="none"), schema=SCHEMA)
    if "is_default" not in have:
        op.add_column(TABLE, sa.Column("is_default", sa.Boolean(), nullable=False,
                                       server_default=sa.false()), schema=SCHEMA)
    if "is_active" not in have:
        op.add_column(TABLE, sa.Column("is_active", sa.Boolean(), nullable=False,
                                       server_default=sa.false()), schema=SCHEMA)
    # best-effort refill from status
    op.execute("""
        UPDATE public.op_templates SET
            is_active       = (status IN ('published','deprecated')),
            visibility      = CASE WHEN status IN ('published','deprecated') THEN 'global' ELSE 'private' END,
            approval_status = CASE status
                                WHEN 'in_review' THEN 'pending'
                                WHEN 'rejected'  THEN 'rejected'
                                WHEN 'published' THEN 'approved'
                                WHEN 'deprecated' THEN 'approved'
                                ELSE 'none' END,
            is_default      = is_system
    """)
