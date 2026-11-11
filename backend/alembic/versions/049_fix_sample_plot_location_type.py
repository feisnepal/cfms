"""Correct field_inventory_sample_plots.location to geography.

Revision ID: 049_fix_plot_location
Revises: 048_fix_sub_area_category
Create Date: 2026-08-20

Why this migration exists (report S1-12, task H1.11)
----------------------------------------------------
``008_add_field_inventory_system`` creates the column as::

    sa.Column('location', sa.String, nullable=False)  # Geography stored as WKT

Production does not look like that. There the column is a real PostGIS
``geography(POINT, 4326)``, matching ``models/field_inventory.py:79``. Someone
altered it by hand and the chain was never updated, so the two diverged
silently.

The consequence only appears on a database built from migrations: every
``ST_*`` predicate against sample-plot locations — distance, containment,
nearest-neighbour — operates on text rather than geography, and the GiST index
``idx_field_inventory_plots_location`` cannot be built on a varchar column at
all. That is 1,166 sample plots' worth of spatial behaviour, wrong on any newly
provisioned environment while looking fine on the one machine that had been
patched.

This was invisible until ``alembic upgrade head`` could run from empty (H1.4)
and the resulting schema could be compared against the models (H1.11).

Why a new revision rather than editing 008
------------------------------------------
008 has genuinely run — production carries the table it creates. Editing an
applied migration would leave every existing database untouched while silently
changing history. A forward migration corrects new builds and is a no-op where
the column is already right.

Safety
------
Guarded: the ALTER runs only when the column is not already ``geography``, so
applying this to production changes nothing. ``USING`` reinterprets the existing
text as WKT, which is exactly the encoding the original comment describes.
"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2

# revision identifiers, used by Alembic.
revision = '049_fix_plot_location'
down_revision = '048_fix_sub_area_category'
branch_labels = None
depends_on = None

TABLE = 'field_inventory_sample_plots'
COLUMN = 'location'
INDEX = 'idx_field_inventory_plots_location'


def _udt(bind) -> str | None:
    return bind.execute(sa.text("""
        SELECT udt_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name=:t AND column_name=:c
    """), {"t": TABLE, "c": COLUMN}).scalar()


def upgrade() -> None:
    """Convert the column to geography(POINT,4326) unless it already is."""
    bind = op.get_bind()
    current = _udt(bind)
    if current is None:
        return  # table absent — nothing to correct
    if current == 'geography':
        return  # already correct (production); no-op

    op.execute(
        f'ALTER TABLE public.{TABLE} '
        f'ALTER COLUMN {COLUMN} TYPE geography(POINT,4326) '
        f'USING {COLUMN}::geometry::geography'
    )
    # The GiST index the model declares cannot exist on a varchar column, so it
    # is only creatable now.
    op.execute(
        f'CREATE INDEX IF NOT EXISTS {INDEX} '
        f'ON public.{TABLE} USING GIST ({COLUMN})'
    )


def downgrade() -> None:
    """Return the column to text. Drops the spatial index first."""
    bind = op.get_bind()
    if _udt(bind) != 'geography':
        return
    op.execute(f'DROP INDEX IF EXISTS public.{INDEX}')
    op.execute(
        f'ALTER TABLE public.{TABLE} '
        f'ALTER COLUMN {COLUMN} TYPE VARCHAR '
        f'USING ST_AsText({COLUMN}::geometry)'
    )
