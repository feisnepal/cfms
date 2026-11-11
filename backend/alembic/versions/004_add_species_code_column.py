"""Add species_code column to tree_species_coefficients

Revision ID: 004
Revises: fcd1bfe9d1f7
Create Date: 2026-02-13

Adds species_code column to support numeric code input (1-23)
Users can now enter species codes instead of scientific names
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '004'
down_revision = 'fcd1bfe9d1f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add species_code column and populate with codes 1-23"""

    # Add species_code column (nullable initially)
    op.add_column(
        'tree_species_coefficients',
        sa.Column('species_code', sa.Integer(), nullable=True),
        schema='public'
    )

    print("[INFO] Added species_code column")

    # Update species with their codes (based on standard Nepal forest species codes)
    conn = op.get_bind()

    species_code_mapping = [
        (1, 'Abies spp'),
        (2, 'Acacia catechu'),
        (3, 'Adina cardifolia'),
        (4, 'Albizia spp'),
        (5, 'Alnus nepalensis'),
        (6, 'Anogeissus latifolia'),
        (7, 'Bombax ceiba'),
        (8, 'Cedrela toona'),
        (9, 'Dalbergia sissoo'),
        (10, 'Eugenia Jambolana'),
        (11, 'Hymenodictyon excelsum'),
        (12, 'Lagerstroemia parviflora'),
        (13, 'Michelia champaca'),
        (14, 'Pinus roxburghii'),
        (15, 'Pinus wallichiana'),
        (16, 'Quercus spp'),
        (17, 'Schima wallichii'),
        (18, 'Shorea robusta'),
        (19, 'Terminalia alata'),
        (20, 'Trewia nudiflora'),
        (21, 'Tsuga spp'),
        (22, 'Terai spp'),
        (23, 'Hill spp'),
    ]

    # Update each species with its code
    for code, scientific_name in species_code_mapping:
        conn.execute(
            sa.text("""
                UPDATE public.tree_species_coefficients
                SET species_code = :code
                WHERE scientific_name = :name
            """),
            {'code': code, 'name': scientific_name}
        )

    print(f"[OK] Updated {len(species_code_mapping)} species with codes 1-23")

    # Add unique constraint on species_code
    op.create_unique_constraint(
        'uq_species_code',
        'tree_species_coefficients',
        ['species_code'],
        schema='public'
    )

    print("[OK] Added unique constraint on species_code")

    # Create index for faster lookups by code
    op.create_index(
        'idx_species_code',
        'tree_species_coefficients',
        ['species_code'],
        unique=False,
        schema='public'
    )

    print("[OK] Created index on species_code column")


def downgrade() -> None:
    """Remove species_code column"""
    op.drop_index('idx_species_code', table_name='tree_species_coefficients', schema='public')
    op.drop_constraint('uq_species_code', 'tree_species_coefficients', schema='public')
    op.drop_column('tree_species_coefficients', 'species_code', schema='public')
    print("[OK] Removed species_code column and constraints")
