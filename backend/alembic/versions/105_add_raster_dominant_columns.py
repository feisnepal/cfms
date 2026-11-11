"""Add the per-unit raster summary columns (RASTER_SOURCES P2, RS-2.1).

Revision ID: 105_add_raster_dominant_columns
Revises: 104_dbh_validation_np_labels
Create Date: 2026-09-30

The four new Auto-Block sources (NASA 2020, NDVI forest health, ESA WorldCover,
DEM) each propose a dominant class for the geometry they carve. Like migration
084/085's ``dominant_slope_band`` / ``dominant_aspect`` / ``dominant_canopy_class``
these are purely additive metadata: NULL for every existing block and for any
block not carved by (or manually assigned) a matching source.

The DEM contributes more than a class: its zone code is for symbology/grouping
only and is not comparable across forests (zone 2 in a Terai forest is a
different altitude than zone 2 in a Himalayan forest), so the compartment also
carries its real altitude so a user can see ``elevation_min_m`` / ``_mean_m`` /
``_max_m`` rather than only a relative zone.

Columns are **schema-qualified public.** (the row's requirement): the table
name is passed unqualified with ``schema="public"`` so Alembic renders
``public.forest_blocks`` (two identifiers), not ``"public.forest_blocks"``
(one literal object name, which is how 051 mistakes were born). All are
nullable so the ADD is a metadata-only change.
"""
from alembic import op
import sqlalchemy as sa

revision = "105_add_raster_dominant_columns"
down_revision = "104_dbh_validation_np_labels"
branch_labels = None
depends_on = None

DOMINANT_COLUMNS = (
    # (column_name, sa_type)  -- integer class codes, same shape as the 084/085
    # dominant_* columns. The value ranges are documented on the model.
    ("dominant_health_class", sa.Integer()),
    ("dominant_nasa_quality", sa.Integer()),
    ("dominant_landcover", sa.Integer()),
    ("dominant_elevation_zone", sa.Integer()),
    # Absolute altitude, visible even when every zone code reads 1/2/3.
    ("elevation_min_m", sa.Numeric(7, 1)),
    ("elevation_mean_m", sa.Numeric(7, 1)),
    ("elevation_max_m", sa.Numeric(7, 1)),
)


def upgrade() -> None:
    for name, col_type in DOMINANT_COLUMNS:
        op.add_column("forest_blocks", sa.Column(name, col_type, nullable=True), schema="public")


def downgrade() -> None:
    for name, _col_type in reversed(DOMINANT_COLUMNS):
        op.drop_column("forest_blocks", name, schema="public")