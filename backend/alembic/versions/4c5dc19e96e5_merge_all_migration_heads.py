"""Merge all migration heads

Revision ID: 4c5dc19e96e5
Revises: 009_add_subarea_to_fieldbook, 013, 016, 016_create_operational_plans_table, 024_add_forest_blocks_indexes, 6be2029e7da1, 90daf66d2ae9
Create Date: 2026-05-09 17:54:30.440979

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4c5dc19e96e5'
# H1.4 / S1-12: '013' removed from this tuple. 014 was relinked to descend from
# 013 (see 014_add_default_blocks_for_existing_calculations.py), so 013 is no
# longer a head — it is now an ancestor of '016' via 014 ->
# 015_add_slope_aspect_columns -> 016, which is already listed here. A merge
# revision may only name revisions that are heads at that point in the graph;
# leaving the stale entry made the graph unresolvable (KeyError: '013').
down_revision = ('009_add_subarea_to_fieldbook', '016', '016_create_operational_plans_table', '024_add_forest_blocks_indexes', '6be2029e7da1', '90daf66d2ae9')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
