"""add_biodiversity_tables

Revision ID: 048860bbe041
Revises: 8783c06de11a
Create Date: 2026-02-07 18:50:25.336679

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '048860bbe041'
down_revision = '8783c06de11a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create biodiversity_species table (master species data)
    op.create_table(
        'biodiversity_species',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('sub_category', sa.String(50)),
        sa.Column('nepali_name', sa.String(255), nullable=False),
        sa.Column('english_name', sa.String(255), nullable=False),
        sa.Column('scientific_name', sa.String(255), nullable=False),
        sa.Column('primary_use', sa.String(100)),
        sa.Column('secondary_uses', sa.Text()),
        sa.Column('iucn_status', sa.String(10)),
        sa.Column('cites_appendix', sa.String(20)),
        sa.Column('distribution', sa.String(255)),
        sa.Column('notes', sa.Text()),
        sa.Column('is_invasive', sa.Boolean(), server_default='false'),
        sa.Column('is_protected', sa.Boolean(), server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )

    # Create indexes for efficient searching
    op.create_index('idx_biodiversity_category', 'biodiversity_species', ['category', 'sub_category'], schema='public')
    op.create_index('idx_biodiversity_invasive', 'biodiversity_species', ['is_invasive'], schema='public')
    op.create_index('idx_biodiversity_protected', 'biodiversity_species', ['is_protected'], schema='public')

    # Create full-text search index for species names
    op.execute("""
        CREATE INDEX idx_biodiversity_search ON public.biodiversity_species
        USING gin(to_tsvector('simple', nepali_name || ' ' || english_name || ' ' || scientific_name))
    """)

    # Create calculation_biodiversity table (user selections per CFOP)
    op.create_table(
        'calculation_biodiversity',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('calculation_id', sa.UUID(), nullable=False),
        sa.Column('species_id', sa.UUID(), nullable=False),
        sa.Column('presence_status', sa.String(20), server_default='present'),
        sa.Column('abundance', sa.String(20)),
        sa.Column('notes', sa.Text()),
        sa.Column('photo_url', sa.String(500)),
        sa.Column('latitude', sa.Numeric(10, 8)),
        sa.Column('longitude', sa.Numeric(11, 8)),
        sa.Column('recorded_by', sa.UUID()),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['calculation_id'], ['public.calculations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['species_id'], ['public.biodiversity_species.id']),
        sa.ForeignKeyConstraint(['recorded_by'], ['public.users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('calculation_id', 'species_id', name='uq_calc_species'),
        schema='public'
    )

    # Create indexes for calculation_biodiversity
    op.create_index('idx_calc_biodiversity', 'calculation_biodiversity', ['calculation_id'], schema='public')
    op.create_index('idx_species_biodiversity', 'calculation_biodiversity', ['species_id'], schema='public')

    print("Created biodiversity tables successfully")


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table('calculation_biodiversity', schema='public')
    op.drop_table('biodiversity_species', schema='public')

    print("Dropped biodiversity tables")
