"""Add dominant_aspect and dominant_canopy_class to forest_blocks.

Revision ID: 085_add_dominant_aspect_and_canopy_class
Revises: 084_add_dominant_slope_band_to_forest_blocks
Create Date: 2026-09-11

SLOPE_COMPARTMENT_AND_STRATIFIED_SAMPLING_PLAN follow-on: the Auto-Block
engine gains two more carve sources alongside `slope` -- `aspect`
(rasters.aspect, values 1-8 = N/NE/E/SE/S/SW/W/NW) and `canopy`
(canopy_height5m.tif, binned 1-4 = non-forest/regeneration/pole/tree). Same
shape as migration 084's `dominant_slope_band`: purely additive metadata,
NULL for every existing block and for anything not carved by its matching
source. A block carries at most one of the three dominant_* columns
populated in practice (one Auto-Block run uses one source).
"""
from alembic import op
import sqlalchemy as sa

revision = "085_add_dominant_aspect_and_canopy_class"
down_revision = "084_add_dominant_slope_band_to_forest_blocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forest_blocks",
        sa.Column("dominant_aspect", sa.Integer(), nullable=True),
    )
    op.add_column(
        "forest_blocks",
        sa.Column("dominant_canopy_class", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("forest_blocks", "dominant_canopy_class")
    op.drop_column("forest_blocks", "dominant_aspect")
