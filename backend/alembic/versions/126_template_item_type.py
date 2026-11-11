"""op_templates.item_type: a template, or a single section kept in the shared section library.

Revision ID: 126_template_item_type
Revises: 125_template_sharing
Create Date: 2026-10-17

A section of a plan (a chapter and what is under it) can be saved to the library and shared like a template: the same row, the same
sharing, licence, trust tier, credit chain, reports and withdrawal. ``item_type`` tells the two apart; every existing row is a template.
"""

import sqlalchemy as sa
from alembic import op

revision = "126_template_item_type"
down_revision = "125_template_sharing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("op_templates", sa.Column("item_type", sa.String(10), nullable=False, server_default="template"))
    op.create_check_constraint("ck_op_templates_item_type", "op_templates", "item_type IN ('template','section')")
    op.create_index("ix_op_templates_item_type", "op_templates", ["item_type"])


def downgrade() -> None:
    op.drop_index("ix_op_templates_item_type", table_name="op_templates")
    op.drop_constraint("ck_op_templates_item_type", "op_templates", type_="check")
    op.drop_column("op_templates", "item_type")
