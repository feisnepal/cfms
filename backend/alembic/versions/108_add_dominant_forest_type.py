"""Add `forest_blocks.dominant_forest_type` + `dominant_contour_band` (RASTER_SOURCES P9, RS-9.5/9.3).

Revision ID: 108_add_dominant_forest_type
Revises: 107_add_raster_layers_table
Create Date: 2026-10-01

Two columns, added together because building one surfaced the need for the
other:

``dominant_forest_type`` -- FRTC forest type (`rasters.forest_type`, RS-4.2)
joins the six other `dominant_*` columns migration 105 added -- same
source-agnostic pass-through pattern: a block carries at most one of these in
practice (the source it was carved by). Code 26 ("Unclassified" in this app)
is anonymous (RS-9.5), so this column is NULL for any piece dominated by it,
same as `dominant_nasa_quality` is NULL for NASA's anonymous code 0.

``dominant_contour_band`` -- the DEM contour-carve source's own band (RS-9.3),
kept SEPARATE from `dominant_elevation_zone`. That column is RS-2.19's
forest-relative percentile attribute, computed for every unit from any source
and explicitly documented as "not set by any one carve source" -- if the DEM
carve wrote its own per-forest equal-elevation-interval band into that same
column, `commit_blocks`' unconditional RS-2.19 pass would silently overwrite
it with the percentile-based number right after, and the two numbers do not
even mean the same thing (one is "which of N equal-height slices", the other
is "which third of this forest's units by elevation"). Keeping them apart
means a DEM-carved piece honestly carries both, never with one silently
destroying the other.

Additive and nullable, so the ADD is metadata-only for existing rows.
"""
from alembic import op
import sqlalchemy as sa

revision = "108_add_dominant_forest_type"
down_revision = "107_add_raster_layers_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forest_blocks",
        sa.Column("dominant_forest_type", sa.Integer(), nullable=True),
        schema="public",
    )
    op.add_column(
        "forest_blocks",
        sa.Column("dominant_contour_band", sa.Integer(), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("forest_blocks", "dominant_contour_band", schema="public")
    op.drop_column("forest_blocks", "dominant_forest_type", schema="public")
