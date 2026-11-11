"""Add `forest_blocks.sub_area_category` + `sub_area_excluded` (RASTER_SOURCES P10, RS-10.1).

Revision ID: 109_add_sub_area_category_to_block
Revises: 108_add_dominant_forest_type
Create Date: 2026-10-01

Two columns for the Union composite layer (`union_zonal`/`union_fusion`, P10):

``sub_area_category`` -- the `ForestSubArea.category` (Protected Zone / Plantation /
Religious / ... , 14 values) that covers the LARGEST share of this piece's area, by
vector overlap -- not a raster vote, `ForestSubArea` is already exact geometry.
NULL means no sub-area was ever drawn over this piece, which is the normal case for
most of a forest (sub-areas are hand-digitized only where something notable exists) --
NULL here is "nothing recorded", never an error.

``sub_area_excluded`` -- true when the majority-overlap `ForestSubArea` row has
`is_excluded = true` (Private Land). Carried as a flag, not an omission: the rest of
the system already treats excluded sub-areas as doughnut holes rather than silently
dropping them (`forest_delete_rules.py` / the CLAUDE.md forest-delete convention), and
a Union piece should tell a planner *why* it has no classification rather than just
not showing up.

Not source-specific -- any layer could in principle report these, but only Union
populates them at first (P10 §"Everything both modes share").

Additive and nullable, so the ADD is metadata-only for existing rows.
"""
from alembic import op
import sqlalchemy as sa

revision = "109_add_sub_area_category_to_block"
down_revision = "108_add_dominant_forest_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forest_blocks",
        sa.Column("sub_area_category", sa.String(length=50), nullable=True),
        schema="public",
    )
    op.add_column(
        "forest_blocks",
        sa.Column(
            "sub_area_excluded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("forest_blocks", "sub_area_excluded", schema="public")
    op.drop_column("forest_blocks", "sub_area_category", schema="public")
