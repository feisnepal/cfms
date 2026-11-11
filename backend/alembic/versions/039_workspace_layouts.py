"""workspace_layouts table — per-user persistent panel layout

Stores the resizable-dock layout (panel sizes + collapsed state) for the
map design UI. One row per (user_id, layout_key); layout_json is an opaque
JSONB blob owned by the frontend.

Revision ID: 039_workspace_layouts
Revises: 040_calculation_progress_and_cost, dc0db1df3cc3
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "039_workspace_layouts"
down_revision = ("040_calculation_progress_and_cost", "dc0db1df3cc3")


def upgrade() -> None:
    op.create_table(
        "workspace_layouts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("layout_key", sa.String(64), nullable=False, server_default="workspace"),
        sa.Column("layout_json", JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "layout_key", name="uq_workspace_layouts_user_key"),
        schema="public",
    )
    op.create_index("idx_workspace_layouts_user_id", "workspace_layouts", ["user_id"], schema="public")


def downgrade() -> None:
    op.drop_index("idx_workspace_layouts_user_id", table_name="workspace_layouts", schema="public")
    op.drop_table("workspace_layouts", schema="public")
