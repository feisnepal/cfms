"""make workspace_layers.purpose nullable (unassigned = NULL)

Revision ID: 046_make_workspace_layers_purpose_nullable
Revises: 045_add_translations_table
Create Date: 2026-08-18

Optional Import Purpose: a layer imported without a purpose ("Skip / Assign
Purpose Later") must persist as NULL so the "Unassigned" badge and the
"Assign Purpose" context-menu action keep working after a page reload.
Previously the column default coerced None -> 'custom', which the frontend
reads as an assigned purpose (truthy), hiding the badge and disabling the
action. 'custom' remains a legitimate assignable purpose; only the default is
removed. Existing rows are untouched.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "046_make_workspace_layers_purpose_nullable"
down_revision = "045_add_translations_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "workspace_layers",
        "purpose",
        existing_type=sa.String(50),
        nullable=True,
        existing_server_default=sa.text("'custom'"),
        server_default=None,
    )


def downgrade() -> None:
    # Coerce existing unassigned rows back to 'custom' before restoring NOT NULL.
    op.execute("UPDATE workspace_layers SET purpose = 'custom' WHERE purpose IS NULL")
    op.alter_column(
        "workspace_layers",
        "purpose",
        existing_type=sa.String(50),
        nullable=False,
        existing_server_default=None,
        server_default=sa.text("'custom'"),
    )
