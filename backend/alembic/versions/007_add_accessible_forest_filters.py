"""Add accessible forest filtering columns to sampling_designs

Revision ID: 007
Revises: 006
Create Date: 2026-02-21

This migration adds columns to support accessible forest area filtering:
- filter_tree_cover: Filter to ESA WorldCover tree pixels (value=10)
- filter_slope: Filter by slope accessibility
- max_slope_degrees: Maximum slope threshold
- accessible_area_hectares: Calculated accessible forest area
- inaccessible_steep_hectares: Tree cover but too steep
- non_forest_area_hectares: Non-tree cover area
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add accessible forest filtering columns to sampling_designs table"""

    print("Adding accessible forest filtering columns to sampling_designs...")

    # Add filter configuration columns
    op.add_column('sampling_designs',
                  sa.Column('filter_tree_cover', sa.Boolean(),
                           nullable=False,
                           server_default='true',
                           comment='Filter to ESA WorldCover tree pixels (value=10)'),
                  schema='public')

    op.add_column('sampling_designs',
                  sa.Column('filter_slope', sa.Boolean(),
                           nullable=False,
                           server_default='false',
                           comment='Filter by slope accessibility'),
                  schema='public')

    op.add_column('sampling_designs',
                  sa.Column('max_slope_degrees', sa.Numeric(precision=4, scale=1),
                           nullable=True,
                           comment='Maximum slope threshold in degrees'),
                  schema='public')

    # Add area breakdown columns
    op.add_column('sampling_designs',
                  sa.Column('accessible_area_hectares', sa.Numeric(precision=10, scale=4),
                           nullable=True,
                           comment='Accessible forest area (tree cover + slope OK)'),
                  schema='public')

    op.add_column('sampling_designs',
                  sa.Column('inaccessible_steep_hectares', sa.Numeric(precision=10, scale=4),
                           nullable=True,
                           comment='Tree cover but too steep for sampling'),
                  schema='public')

    op.add_column('sampling_designs',
                  sa.Column('non_forest_area_hectares', sa.Numeric(precision=10, scale=4),
                           nullable=True,
                           comment='Non-tree cover area (grassland, cropland, water, etc.)'),
                  schema='public')

    print("SUCCESS: Added 6 columns to sampling_designs table")
    print("  - filter_tree_cover (BOOLEAN, default TRUE)")
    print("  - filter_slope (BOOLEAN, default FALSE)")
    print("  - max_slope_degrees (NUMERIC(4,1))")
    print("  - accessible_area_hectares (NUMERIC(10,4))")
    print("  - inaccessible_steep_hectares (NUMERIC(10,4))")
    print("  - non_forest_area_hectares (NUMERIC(10,4))")


def downgrade() -> None:
    """Remove accessible forest filtering columns from sampling_designs table"""

    print("Removing accessible forest filtering columns from sampling_designs...")

    op.drop_column('sampling_designs', 'non_forest_area_hectares', schema='public')
    op.drop_column('sampling_designs', 'inaccessible_steep_hectares', schema='public')
    op.drop_column('sampling_designs', 'accessible_area_hectares', schema='public')
    op.drop_column('sampling_designs', 'max_slope_degrees', schema='public')
    op.drop_column('sampling_designs', 'filter_slope', schema='public')
    op.drop_column('sampling_designs', 'filter_tree_cover', schema='public')

    print("SUCCESS: Removed accessible forest filtering columns")
