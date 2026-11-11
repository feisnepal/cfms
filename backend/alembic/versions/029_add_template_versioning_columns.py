"""Add versioning columns to op_templates

Adds version, is_active, template_category, preview_image,
changelog, and source_template_id columns.

Revision ID: 029_add_template_versioning_columns
Revises: 028_add_resource_yield_columns
Create Date: 2026-06-29

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "029_add_template_versioning_columns"
down_revision = "028_add_resource_yield_columns"

def upgrade():
    op.add_column("op_templates", sa.Column("version", sa.Integer(), nullable=False, server_default="1"), schema="public")
    op.add_column("op_templates", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"), schema="public")
    op.add_column("op_templates", sa.Column("template_category", sa.String(50), nullable=True), schema="public")
    op.add_column("op_templates", sa.Column("preview_image_url", sa.Text(), nullable=True), schema="public")
    op.add_column("op_templates", sa.Column("changelog", sa.Text(), nullable=True), schema="public")
    op.add_column("op_templates", sa.Column("source_template_id", UUID(as_uuid=True), nullable=True), schema="public")
    op.create_foreign_key(
        "fk_op_templates_source_template",
        "op_templates", "op_templates",
        ["source_template_id"], ["id"],
        source_schema="public", referent_schema="public",
    )


def downgrade():
    op.drop_constraint("fk_op_templates_source_template", "op_templates", schema="public")
    op.drop_column("op_templates", "source_template_id", schema="public")
    op.drop_column("op_templates", "changelog", schema="public")
    op.drop_column("op_templates", "preview_image_url", schema="public")
    op.drop_column("op_templates", "template_category", schema="public")
    op.drop_column("op_templates", "is_active", schema="public")
    op.drop_column("op_templates", "version", schema="public")
