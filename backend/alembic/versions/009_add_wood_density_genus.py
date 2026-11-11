"""Add wood_density and genus columns to tree_species_coefficients

Revision ID: 009
Revises: 008
Create Date: 2026-03-03

Adds three new columns:
- wood_density_gm_cm3: Wood density in grams per cubic centimeter
- wood_density_source: Source reference for wood density data
- genus: Genus name extracted from scientific name
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add wood_density_gm_cm3, wood_density_source, and genus columns"""

    # Add wood_density_gm_cm3 column (numeric, nullable)
    op.add_column(
        'tree_species_coefficients',
        sa.Column('wood_density_gm_cm3', sa.Numeric(precision=5, scale=3), nullable=True),
        schema='public'
    )
    print("[INFO] Added wood_density_gm_cm3 column")

    # Add wood_density_source column (text, nullable)
    op.add_column(
        'tree_species_coefficients',
        sa.Column('wood_density_source', sa.Text(), nullable=True),
        schema='public'
    )
    print("[INFO] Added wood_density_source column")

    # Add genus column (string, nullable)
    op.add_column(
        'tree_species_coefficients',
        sa.Column('genus', sa.String(length=100), nullable=True),
        schema='public'
    )
    print("[INFO] Added genus column")

    # Create index on genus for faster searches
    op.create_index(
        'idx_species_genus',
        'tree_species_coefficients',
        ['genus'],
        unique=False,
        schema='public'
    )
    print("[OK] Created index on genus column")

    print("[OK] Migration complete - 3 new columns added to tree_species_coefficients")


def downgrade() -> None:
    """Remove wood_density_gm_cm3, wood_density_source, and genus columns"""

    # Drop index first
    op.drop_index('idx_species_genus', table_name='tree_species_coefficients', schema='public')

    # Drop columns in reverse order
    op.drop_column('tree_species_coefficients', 'genus', schema='public')
    op.drop_column('tree_species_coefficients', 'wood_density_source', schema='public')
    op.drop_column('tree_species_coefficients', 'wood_density_gm_cm3', schema='public')

    print("[OK] Removed wood_density and genus columns")
