"""Add per-feature style to forest_blocks.

Revision ID: 075_add_style_to_forest_blocks
Revises: 074_add_working_circle_to_forest_blocks
Create Date: 2026-09-02

Workspace layer styling, P3 (WORKSPACE_LAYER_STYLING_PLAN.md).

A single unit (block / compartment / sub-compartment) can carry a user-chosen
override for its own fill colour and opacity, set from the attribute table or
the map ⋮ menu. One nullable JSONB column holds the whole override:

    {"fill": "#cc3344", "fillOpacity": 0.5, "stroke": "#7f1d1d", "weight": 2}

NULL / missing means "use the palette / working-circle style" (the render
precedence in ``layerStyles.resolveLayerStyle`` — per-feature beats the custom
layer style, which beats the palette). Every existing row is NULL, so there is
no backfill.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "075_add_style_to_forest_blocks"
down_revision = "074_add_working_circle_to_forest_blocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forest_blocks",
        sa.Column("style", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("forest_blocks", "style")
