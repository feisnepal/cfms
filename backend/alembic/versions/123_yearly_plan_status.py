"""yearly_plan_status: the owner's "yearly activities are done" mark (workflow step 15).

Revision ID: 123_yearly_plan_status
Revises: 122_forest_metadata_forest_facts
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "123_yearly_plan_status"
down_revision = "122_forest_metadata_forest_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "yearly_plan_status",
        sa.Column("calculation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calculations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("is_done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("done_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopened_reason", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("yearly_plan_status")
