"""Add dominant_slope_band to forest_blocks.

Revision ID: 084_add_dominant_slope_band_to_forest_blocks
Revises: 083_sfm_profiles
Create Date: 2026-09-11

SLOPE_COMPARTMENT_AND_STRATIFIED_SAMPLING_PLAN, Part A follow-on. A block
carved via the slope-class auto-block source now carries the slope band
(1-4, कार्यविधि §15.2: < 19deg / 19-31deg / 31-45deg / > 45deg) that dominated
its final committed geometry, so it survives into the attribute table instead
of being lost after commit (it previously only existed transiently in the
preview response).

NULL for every existing block and for anything not slope-generated (MMU
auto-blocks, manual draw, import, divide/split) -- this is purely additive
metadata, never required, never backfilled.
"""
from alembic import op
import sqlalchemy as sa

revision = "084_add_dominant_slope_band_to_forest_blocks"
down_revision = "083_sfm_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forest_blocks",
        sa.Column("dominant_slope_band", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("forest_blocks", "dominant_slope_band")
