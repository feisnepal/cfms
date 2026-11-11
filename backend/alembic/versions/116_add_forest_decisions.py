"""Answers to the plan decisions a person makes for a forest (Forest summary panel, Decisions needed tab).

Only answers are stored; the questions live in code. Cascades from ``calculations`` so deleting a forest deletes them.
``decided_by`` is SET NULL on user deletion so the answer outlives the account that gave it.

Revision ID: 116_add_forest_decisions
Revises: 115_align_spatial_assignment_constraint
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "116_add_forest_decisions"
down_revision = "115_align_spatial_assignment_constraint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forest_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("calculation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(64), nullable=True),
        sa.Column("choice", sa.String(64), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_forest_decisions_calculation_id", "forest_decisions", ["calculation_id"])
    # One answer per (forest, question, scope); NULLS NOT DISTINCT makes a forest-wide answer (scope NULL) unique too.
    op.create_index(
        "uq_forest_decisions_calc_key_scope", "forest_decisions", ["calculation_id", "key", "scope"],
        unique=True, postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_table("forest_decisions")
