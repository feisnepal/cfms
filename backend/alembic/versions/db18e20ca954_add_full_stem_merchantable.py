"""add_full_stem_merchantable_to_species_coefficients

Revision ID: db18e20ca954
Revises: db17e20ca953
Create Date: 2026-05-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'db18e20ca954'
down_revision = 'db17e20ca953'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tree_species_coefficients',
        sa.Column('full_stem_merchantable', sa.Boolean(),
                  nullable=False, server_default=sa.text('false')),
        schema='public'
    )
    # Acacia catechu (Khair) — entire stem is merchantable per Regulation 2079
    op.execute(
        "UPDATE public.tree_species_coefficients "
        "SET full_stem_merchantable = TRUE "
        "WHERE scientific_name = 'Acacia catechu'"
    )


def downgrade() -> None:
    op.drop_column('tree_species_coefficients', 'full_stem_merchantable', schema='public')
