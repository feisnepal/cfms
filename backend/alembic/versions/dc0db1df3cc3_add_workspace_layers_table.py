"""Add workspace_layers table

Revision ID: dc0db1df3cc3
Revises: 038_map_design_ui_revamp
Create Date: 2026-07-29 20:42:59.987418

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "dc0db1df3cc3"
down_revision = "038_map_design_ui_revamp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_layers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("calculation_id", UUID(as_uuid=True), sa.ForeignKey("public.calculations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(50), nullable=False, server_default="custom"),
        sa.Column("source_format", sa.String(10), nullable=False),
        sa.Column("feature_count", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("geometry_types", JSONB(), nullable=True),
        sa.Column("layer_data", JSONB(), nullable=True),
        sa.Column("layer_metadata", JSONB(), nullable=True),
        sa.Column("layer_hash", sa.String(64), nullable=True),
        sa.Column("is_draft", sa.Boolean(), nullable=True, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_workspace_layers_calc_id", "workspace_layers", ["calculation_id"])
    op.create_index("idx_workspace_layers_calc_draft", "workspace_layers", ["calculation_id", "is_draft"])
    op.create_index("idx_workspace_layers_calc_purpose", "workspace_layers", ["calculation_id", "purpose"])
    op.create_index("idx_workspace_layers_calc_hash", "workspace_layers", ["calculation_id", "layer_hash"])


def downgrade() -> None:
    op.drop_index("idx_workspace_layers_calc_hash", table_name="workspace_layers")
    op.drop_index("idx_workspace_layers_calc_purpose", table_name="workspace_layers")
    op.drop_index("idx_workspace_layers_calc_draft", table_name="workspace_layers")
    op.drop_index("idx_workspace_layers_calc_id", table_name="workspace_layers")
    op.drop_table("workspace_layers")
