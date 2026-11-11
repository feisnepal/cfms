"""Audit trail for role changes (super-admin user panel).

Revision ID: 114_add_user_role_changes
Revises: 113_fix_janajati_spelling
Create Date: 2026-10-07
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "114_add_user_role_changes"
down_revision = "113_fix_janajati_spelling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_role_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("old_role", sa.String(40), nullable=False),
        sa.Column("new_role", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="public",
    )
    op.create_index("idx_user_role_changes_user", "user_role_changes", ["user_id", "created_at"], schema="public")


def downgrade() -> None:
    op.drop_index("idx_user_role_changes_user", table_name="user_role_changes", schema="public")
    op.drop_table("user_role_changes", schema="public")
