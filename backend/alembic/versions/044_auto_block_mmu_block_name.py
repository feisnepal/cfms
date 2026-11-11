"""add forest_blocks.block_name + natural_name for auto-block generation

Revision ID: 044_auto_block_mmu_block_name
Revises: 043_map_unification_flags
Create Date: 2026-08-11

Adds the two columns the Auto-Block MMU workflow persists on generated
forest blocks: `block_name` (user-editable serial like "Block-1"/"Block-2",
default computed at generation time) and `natural_name` (best-effort nearest
named river/ridge label, optional). downgrade() removes both columns.
"""
from alembic import op
import sqlalchemy as sa

revision = "044_auto_block_mmu_block_name"
down_revision = "043_map_unification_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forest_blocks",
        sa.Column("block_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "forest_blocks",
        sa.Column("natural_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("forest_blocks", "natural_name")
    op.drop_column("forest_blocks", "block_name")