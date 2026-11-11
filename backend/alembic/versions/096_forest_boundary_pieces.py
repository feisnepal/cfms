"""Add forest_boundary_pieces table (BOUNDARY_PIECES_PLAN.md P1).

Revision ID: 096_forest_boundary_pieces
Revises: 095_unit_id_link
Create Date: 2026-09-23

Purely additive: one row per disjoint piece of a forest's outer boundary, so a
multi-island forest ("like Japan") can have each piece individually named and
listed, instead of only surviving as an anonymous MultiPolygon inside
`calculations.boundary_geom`. That column keeps its exact current meaning (the
union of every piece) -- nothing that reads it needs to change; see the plan's
"Explicit non-goals / guardrails" section.

Schema mirrors `forest_sub_areas` (migration 013) exactly, minus the
category/block_id/is_excluded columns a boundary piece has no use for (D3:
deliberately minimal -- name + area only for the first cut).

No backfill here -- migrations in this codebase create schema only; the
one-time backfill of existing forests' `boundary_geom` into piece rows is a
separate, explicitly dry-runnable script (`scripts/backfill_boundary_pieces.py`,
BOUNDARY_PIECES_PLAN.md D5), run manually against `cf_db` after this applies.
"""
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '096_forest_boundary_pieces'
down_revision = '095_unit_id_link'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names(schema='public')

    if 'forest_boundary_pieces' not in existing_tables:
        op.execute("""
            CREATE TABLE public.forest_boundary_pieces (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                calculation_id UUID NOT NULL REFERENCES public.calculations(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                geometry geometry(GEOMETRY, 4326) NOT NULL,
                area_hectares DOUBLE PRECISION NOT NULL CHECK (area_hectares > 0),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
            )
        """)

    existing_indexes = (
        [i['name'] for i in inspector.get_indexes('forest_boundary_pieces', schema='public')]
        if 'forest_boundary_pieces' in existing_tables else []
    )
    if 'idx_forest_boundary_pieces_calculation_id' not in existing_indexes:
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_forest_boundary_pieces_calculation_id "
            "ON public.forest_boundary_pieces(calculation_id)"
        )
    if 'idx_forest_boundary_pieces_geometry' not in existing_indexes:
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_forest_boundary_pieces_geometry "
            "ON public.forest_boundary_pieces USING GIST(geometry)"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_forest_boundary_pieces_geometry")
    op.execute("DROP INDEX IF EXISTS idx_forest_boundary_pieces_calculation_id")
    op.execute("DROP TABLE IF EXISTS public.forest_boundary_pieces")
