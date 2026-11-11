"""Add suggested_orientation, orientation_justification_en, orientation_justification_ne to forest_blocks.

Revision ID: 087_add_suggested_orientation_and_justifications
Revises: 086_add_management_orientation
Create Date: 2026-09-16

Auto-Block (slope source) commit now also seeds:
- suggested_orientation: read-only mirror of SFM's current orientation proposal
- orientation_justification_en/ne: the सि.नं. reference + rule chain from orientation.propose
Populated alongside management_orientation in auto_block_service._apply_management_orientation.
Purely additive metadata, NULL for existing blocks and non-slope origins.
"""
from alembic import op
import sqlalchemy as sa

revision = "087_add_suggested_orientation_and_justifications"
down_revision = "086_add_management_orientation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forest_blocks",
        sa.Column("suggested_orientation", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "forest_blocks",
        sa.Column("orientation_justification_en", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "forest_blocks",
        sa.Column("orientation_justification_ne", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("forest_blocks", "suggested_orientation")
    op.drop_column("forest_blocks", "orientation_justification_en")
    op.drop_column("forest_blocks", "orientation_justification_ne")