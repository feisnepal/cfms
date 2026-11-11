"""Create op_template_versions table for template version history

Revision ID: 030_add_template_versions_table
Revises: 029_add_template_versioning_columns
Create Date: 2026-06-29

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "030_add_template_versions_table"
down_revision = "029_add_template_versioning_columns"


def upgrade():
    op.create_table(
        "op_template_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("public.op_templates.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tree", JSONB(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("changelog", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="public",
    )


def downgrade():
    op.drop_table("op_template_versions", schema="public")
