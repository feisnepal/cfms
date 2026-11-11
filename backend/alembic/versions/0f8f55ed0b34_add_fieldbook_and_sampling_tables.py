"""add_fieldbook_and_sampling_tables

Revision ID: 0f8f55ed0b34
Revises: 003
Create Date: 2026-02-03 23:45:10.437418

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from geoalchemy2 import Geometry


# revision identifiers, used by Alembic.
revision = '0f8f55ed0b34'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create sampling_designs table
    op.create_table(
        'sampling_designs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('calculation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('sampling_type', sa.String(50), nullable=False),
        sa.Column('intensity_per_hectare', sa.Numeric(10, 4), nullable=True),
        sa.Column('grid_spacing_meters', sa.Integer(), nullable=True),
        sa.Column('min_distance_meters', sa.Integer(), nullable=True),
        sa.Column('plot_shape', sa.String(50), nullable=True),
        sa.Column('plot_radius_meters', sa.Numeric(10, 2), nullable=True),
        sa.Column('plot_length_meters', sa.Numeric(10, 2), nullable=True),
        sa.Column('plot_width_meters', sa.Numeric(10, 2), nullable=True),
        sa.Column('exclusion_geometry', Geometry('MULTIPOLYGON', srid=4326), nullable=True),
        sa.Column('points_geometry', Geometry('MULTIPOINT', srid=4326), nullable=True),
        sa.Column('total_points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['calculation_id'], ['public.calculations.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )

    # Create indexes for sampling_designs
    op.create_index('idx_sampling_designs_calculation', 'sampling_designs',
                    ['calculation_id'], unique=False, schema='public')
    op.create_index('idx_sampling_designs_points', 'sampling_designs',
                    ['points_geometry'], unique=False, schema='public',
                    postgresql_using='gist')

    # Create fieldbook table
    op.create_table(
        'fieldbook',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('calculation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('point_number', sa.Integer(), nullable=False),
        sa.Column('point_type', sa.String(20), nullable=False),
        sa.Column('longitude', sa.Numeric(10, 7), nullable=False),
        sa.Column('latitude', sa.Numeric(10, 7), nullable=False),
        sa.Column('easting_utm', sa.Numeric(12, 3), nullable=True),
        sa.Column('northing_utm', sa.Numeric(12, 3), nullable=True),
        sa.Column('utm_zone', sa.Integer(), nullable=True),
        sa.Column('azimuth_to_next', sa.Numeric(5, 2), nullable=True),
        sa.Column('distance_to_next', sa.Numeric(8, 2), nullable=True),
        sa.Column('elevation', sa.Numeric(8, 2), nullable=True),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('is_verified', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('point_geometry', Geometry('POINT', srid=4326), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['calculation_id'], ['public.calculations.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('calculation_id', 'point_number',
                           name='uq_fieldbook_calc_point'),
        schema='public'
    )

    # Create indexes for fieldbook
    op.create_index('idx_fieldbook_calculation', 'fieldbook',
                    ['calculation_id'], unique=False, schema='public')
    op.create_index('idx_fieldbook_point_number', 'fieldbook',
                    ['calculation_id', 'point_number'], unique=False, schema='public')
    op.create_index('idx_fieldbook_geometry', 'fieldbook',
                    ['point_geometry'], unique=False, schema='public',
                    postgresql_using='gist')

    print("Created fieldbook and sampling_designs tables successfully")


def downgrade() -> None:
    # Drop fieldbook table
    op.drop_index('idx_fieldbook_geometry', table_name='fieldbook', schema='public')
    op.drop_index('idx_fieldbook_point_number', table_name='fieldbook', schema='public')
    op.drop_index('idx_fieldbook_calculation', table_name='fieldbook', schema='public')
    op.drop_table('fieldbook', schema='public')

    # Drop sampling_designs table
    op.drop_index('idx_sampling_designs_points', table_name='sampling_designs', schema='public')
    op.drop_index('idx_sampling_designs_calculation', table_name='sampling_designs', schema='public')
    op.drop_table('sampling_designs', schema='public')

    print("Dropped fieldbook and sampling_designs tables successfully")
