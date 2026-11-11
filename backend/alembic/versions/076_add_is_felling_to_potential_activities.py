"""Add is_felling flag to potential_activities.

Revision ID: 076_add_is_felling_to_potential_activities
Revises: 075_add_style_to_forest_blocks
Create Date: 2026-09-03

THEMATIC_MAP_VARIABLES_PLAN §3.4B / P5c, decision D18.

The `opsmap:unit__felling_year` / `felling_series` / `harvest_vs_aah` maps need
to know which of a forest's planned activities are *felling* (harvest)
activities — there was no marker for that. One nullable boolean on the master
activity list (`potential_activities`); an admin ticks it for the harvest /
felling / कटान rows. NULL is treated as "not a felling activity" by every
consumer, so no backfill is required (an admin can flag the existing rows).
"""

import sqlalchemy as sa
from alembic import op

revision = "076_add_is_felling_to_potential_activities"
down_revision = "075_add_style_to_forest_blocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "potential_activities",
        sa.Column("is_felling", sa.Boolean(), nullable=True),
    )
    # Best-effort seed: flag rows whose name/programme clearly denotes harvesting
    # so a fresh install is not entirely blank. Admins refine via the UI.
    op.execute(
        """
        UPDATE potential_activities
           SET is_felling = TRUE
         WHERE is_felling IS NULL
           AND (
                lower(coalesce(activities, ''))  ~ '(felling|fell |harvest|कटान|कटानी)'
             OR lower(coalesce(progarms, ''))    ~ '(felling|harvest|कटान)'
             OR lower(coalesce(project_name,'')) ~ '(felling|harvest|कटान)'
           )
        """
    )


def downgrade() -> None:
    op.drop_column("potential_activities", "is_felling")
