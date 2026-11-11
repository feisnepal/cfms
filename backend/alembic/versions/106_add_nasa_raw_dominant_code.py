"""Add `forest_blocks.dominant_nasa_code` (RASTER_SOURCES P2, RS-2.14).

Revision ID: 106_add_nasa_raw_dominant_code
Revises: 105_add_raster_dominant_columns
Create Date: 2026-09-30

Migration 105 added `dominant_nasa_quality`, bound 1-3 because the NASA 2020
forest-quality vocabulary only defines Primary / Young Secondary / Old Secondary
as classes. Code **0** is real, mappable ground -- grassland, bare soil, urban --
that the Raster Sources plan (RS-2.5 / D41) carves as geometry but deliberately
never reports as a class.

That left one NULL meaning two different facts. A compartment the raster called
mostly non-forest and a compartment the raster never covered both stored NULL and
both rendered as the same blank cell, so "this block is not forest" was
indistinguishable from "we could not classify this block" (RS-2.14).

This column keeps the raw dominant class 0-3 as the raster has it, so the UI can
show "Non-forest (0)" and a NULL in `dominant_nasa_quality` can be read against
it. `dominant_nasa_quality` itself is unchanged: still 1-3, still NULL when the
dominant class is 0, still the value the edit schema validates.

Additive and nullable, so the ADD is metadata-only for existing rows. The
column is schema-qualified `public.` per the 105 requirement: the table name is
passed unqualified with ``schema="public"`` so Alembic renders
``public.forest_blocks`` (two identifiers) rather than a single quoted object
name.
"""
from alembic import op
import sqlalchemy as sa

revision = "106_add_nasa_raw_dominant_code"
down_revision = "105_add_raster_dominant_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forest_blocks",
        sa.Column("dominant_nasa_code", sa.Integer(), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("forest_blocks", "dominant_nasa_code", schema="public")
