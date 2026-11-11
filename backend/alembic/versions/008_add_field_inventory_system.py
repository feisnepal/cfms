"""add field inventory system

Revision ID: 008
Revises: 007
Create Date: 2026-02-27 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    # Create field_inventory_calculations table
    op.create_table(
        'field_inventory_calculations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('calculation_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),

        # File metadata
        sa.Column('uploaded_filename', sa.String(255), nullable=False),
        sa.Column('column_mapping', postgresql.JSONB, nullable=True),

        # Configurable sample plot sizes (in square meters)
        sa.Column('regeneration_area_sqm', sa.Numeric(10, 2), nullable=False, server_default='10.0'),
        sa.Column('sapling_area_sqm', sa.Numeric(10, 2), nullable=False, server_default='25.0'),
        sa.Column('pole_area_sqm', sa.Numeric(10, 2), nullable=False, server_default='100.0'),
        sa.Column('tree_area_sqm', sa.Numeric(10, 2), nullable=False, server_default='500.0'),

        # Processing status
        sa.Column('status', sa.String(50), nullable=False, server_default='processing'),
        sa.Column('processing_time_seconds', sa.Integer, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),

        # Summary statistics
        sa.Column('total_sample_plots', sa.Integer, nullable=True),
        sa.Column('total_blocks', sa.Integer, nullable=True),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['calculation_id'], ['public.calculations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['public.users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('calculation_id', name='uq_field_inventory_calculations_calculation_id'),
        schema='public'
    )

    # Create indexes for field_inventory_calculations
    op.create_index('idx_field_inventory_calc_user', 'field_inventory_calculations', ['user_id'], schema='public')
    op.create_index('idx_field_inventory_calc_calculation', 'field_inventory_calculations', ['calculation_id'], schema='public')
    op.create_index('idx_field_inventory_calc_status', 'field_inventory_calculations', ['status'], schema='public')

    # Create field_inventory_sample_plots table
    op.create_table(
        'field_inventory_sample_plots',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('field_inventory_calculation_id', postgresql.UUID(as_uuid=True), nullable=False),

        # Plot identification
        sa.Column('block_name', sa.String(255), nullable=False),
        sa.Column('sample_plot_number', sa.Integer, nullable=False),
        sa.Column('location', sa.String, nullable=False),  # Geography stored as WKT

        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['field_inventory_calculation_id'], ['public.field_inventory_calculations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('field_inventory_calculation_id', 'block_name', 'sample_plot_number',
                          name='uq_field_inventory_plots_calc_block_number'),
        schema='public'
    )

    # Create indexes for field_inventory_sample_plots
    op.create_index('idx_field_inventory_plots_calc', 'field_inventory_sample_plots', ['field_inventory_calculation_id'], schema='public')
    op.create_index('idx_field_inventory_plots_block', 'field_inventory_sample_plots', ['block_name'], schema='public')

    # Create field_inventory_measurements table
    op.create_table(
        'field_inventory_measurements',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('sample_plot_id', postgresql.UUID(as_uuid=True), nullable=False),

        # Measurement data
        sa.Column('stand_type', sa.String(20), nullable=False),  # 'Regeneration', 'Sapling', 'Pole', 'Tree'
        sa.Column('sn', sa.Integer, nullable=True),
        sa.Column('species_scientific', sa.String(255), nullable=False),
        sa.Column('species_local', sa.String(255), nullable=True),
        sa.Column('dbh_cm', sa.Numeric(10, 2), nullable=True),
        sa.Column('height_m', sa.Numeric(10, 2), nullable=True),
        sa.Column('height_estimated', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('tree_class', sa.String(10), nullable=True),
        sa.Column('count', sa.Integer, nullable=False, server_default='1'),

        # Calculated volumes (only for Pole and Tree)
        sa.Column('stem_volume', sa.Numeric(15, 6), nullable=True),
        sa.Column('branch_volume', sa.Numeric(15, 6), nullable=True),
        sa.Column('tree_volume', sa.Numeric(15, 6), nullable=True),
        sa.Column('gross_volume', sa.Numeric(15, 6), nullable=True),
        sa.Column('net_volume', sa.Numeric(15, 6), nullable=True),
        sa.Column('net_volume_cft', sa.Numeric(15, 6), nullable=True),
        sa.Column('firewood_m3', sa.Numeric(15, 6), nullable=True),
        sa.Column('firewood_chatta', sa.Numeric(15, 6), nullable=True),

        # DBH classification
        sa.Column('dbh_class', sa.String(50), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['sample_plot_id'], ['public.field_inventory_sample_plots.id'], ondelete='CASCADE'),
        schema='public'
    )

    # Create indexes for field_inventory_measurements
    op.create_index('idx_field_inventory_meas_plot', 'field_inventory_measurements', ['sample_plot_id'], schema='public')
    op.create_index('idx_field_inventory_meas_stand_type', 'field_inventory_measurements', ['stand_type'], schema='public')
    op.create_index('idx_field_inventory_meas_species', 'field_inventory_measurements', ['species_scientific'], schema='public')

    # Create field_inventory_block_summary table
    op.create_table(
        'field_inventory_block_summary',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('field_inventory_calculation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('block_name', sa.String(255), nullable=False),

        # Sample plot statistics
        sa.Column('total_sample_plots', sa.Integer, nullable=False),

        # Per-hectare counts (extrapolated)
        sa.Column('regeneration_per_ha', sa.Integer, nullable=True),
        sa.Column('sapling_per_ha', sa.Integer, nullable=True),
        sa.Column('pole_per_ha', sa.Integer, nullable=True),
        sa.Column('tree_per_ha', sa.Integer, nullable=True),

        # Per-hectare volumes (extrapolated) - timber only
        sa.Column('pole_timber_m3_per_ha', sa.Numeric(15, 6), nullable=True),
        sa.Column('pole_firewood_m3_per_ha', sa.Numeric(15, 6), nullable=True),
        sa.Column('tree_timber_m3_per_ha', sa.Numeric(15, 6), nullable=True),
        sa.Column('tree_firewood_m3_per_ha', sa.Numeric(15, 6), nullable=True),

        # Total growing stock (timber only)
        sa.Column('total_growing_stock_m3_per_ha', sa.Numeric(15, 6), nullable=True),

        # Forest condition assessment
        sa.Column('regeneration_condition', sa.String(20), nullable=True),  # 'Good', 'Moderate', 'Weak'
        sa.Column('forest_condition', sa.String(20), nullable=True),  # 'Good', 'Moderate', 'Weak'

        # Mean Annual Increment (%)
        sa.Column('mai_percent', sa.Numeric(5, 2), nullable=True),
        sa.Column('dominant_growth_rate', sa.String(20), nullable=True),  # 'Fast', 'Moderate', 'Slow'

        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['field_inventory_calculation_id'], ['public.field_inventory_calculations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('field_inventory_calculation_id', 'block_name',
                          name='uq_field_inventory_summary_calc_block'),
        schema='public'
    )

    # Create indexes for field_inventory_block_summary
    op.create_index('idx_field_inventory_summary_calc', 'field_inventory_block_summary', ['field_inventory_calculation_id'], schema='public')
    op.create_index('idx_field_inventory_summary_block', 'field_inventory_block_summary', ['block_name'], schema='public')


def downgrade():
    # Drop tables in reverse order (due to foreign key dependencies)
    op.drop_table('field_inventory_block_summary', schema='public')
    op.drop_table('field_inventory_measurements', schema='public')
    op.drop_table('field_inventory_sample_plots', schema='public')
    op.drop_table('field_inventory_calculations', schema='public')
