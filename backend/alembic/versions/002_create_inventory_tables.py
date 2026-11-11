"""Create inventory tables

Revision ID: 002
Revises: 001
Create Date: 2026-02-01

Tables:
- tree_species_coefficients
- inventory_calculations
- inventory_trees
- inventory_validation_logs
- inventory_validation_issues
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from geoalchemy2 import Geography

# revision identifiers
revision = '002'
down_revision = '12a9084b095b'  # Latest migration from main branch
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create inventory-related tables"""

    # 1. Tree species coefficients table
    op.create_table(
        'tree_species_coefficients',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('scientific_name', sa.String(length=255), nullable=False, unique=True),
        sa.Column('local_name', sa.String(length=100), nullable=True),

        # Volume equation coefficients
        sa.Column('a', sa.Float(), nullable=True),
        sa.Column('b', sa.Float(), nullable=True),
        sa.Column('c', sa.Float(), nullable=True),
        sa.Column('a1', sa.Float(), nullable=True),
        sa.Column('b1', sa.Float(), nullable=True),

        # Additional parameters
        sa.Column('s', sa.Float(), nullable=True),
        sa.Column('m', sa.Float(), nullable=True),
        sa.Column('bg', sa.Float(), nullable=True),

        # Species metadata
        sa.Column('aliases', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('max_dbh_cm', sa.Float(), nullable=True),
        sa.Column('max_height_m', sa.Float(), nullable=True),
        sa.Column('typical_hd_ratio_min', sa.Float(), nullable=True),
        sa.Column('typical_hd_ratio_max', sa.Float(), nullable=True),

        # Status
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )

    # Indexes for species table
    op.create_index('idx_species_scientific_name', 'tree_species_coefficients', ['scientific_name'], unique=True, schema='public')
    op.create_index('idx_species_local_name', 'tree_species_coefficients', ['local_name'], unique=False, schema='public')
    op.create_index('idx_species_aliases', 'tree_species_coefficients', ['aliases'], unique=False, schema='public', postgresql_using='gin')

    print("[OK] Created tree_species_coefficients table")

    # 2. Inventory calculations table
    op.create_table(
        'inventory_calculations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('calculation_id', postgresql.UUID(as_uuid=True), nullable=True),  # Link to main calculation
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('uploaded_filename', sa.String(length=255), nullable=False),

        # Grid settings for mother tree selection
        sa.Column('grid_spacing_meters', sa.Float(), nullable=False, server_default='20.0'),
        sa.Column('projection_epsg', sa.Integer(), nullable=False, server_default='32644'),

        # Processing status
        sa.Column('status', sa.String(length=50), nullable=False, server_default='processing'),
        sa.Column('processing_time_seconds', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),

        # Summary statistics
        sa.Column('total_trees', sa.Integer(), nullable=True),
        sa.Column('mother_trees_count', sa.Integer(), nullable=True),
        sa.Column('felling_trees_count', sa.Integer(), nullable=True),
        sa.Column('seedling_count', sa.Integer(), nullable=True),
        sa.Column('total_volume_m3', sa.Float(), nullable=True),
        sa.Column('total_net_volume_m3', sa.Float(), nullable=True),
        sa.Column('total_net_volume_cft', sa.Float(), nullable=True),
        sa.Column('total_firewood_m3', sa.Float(), nullable=True),
        sa.Column('total_firewood_chatta', sa.Float(), nullable=True),

        sa.ForeignKeyConstraint(['calculation_id'], ['public.calculations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['public.users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )

    # Indexes for inventory_calculations
    op.create_index('idx_inventory_calc_user', 'inventory_calculations', ['user_id'], unique=False, schema='public')
    op.create_index('idx_inventory_calc_calculation', 'inventory_calculations', ['calculation_id'], unique=False, schema='public')
    op.create_index('idx_inventory_calc_status', 'inventory_calculations', ['status'], unique=False, schema='public')

    print("[OK] Created inventory_calculations table")

    # 3. Inventory trees table
    op.create_table(
        'inventory_trees',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('inventory_calculation_id', postgresql.UUID(as_uuid=True), nullable=False),

        # Original data
        sa.Column('species', sa.String(length=255), nullable=False),
        sa.Column('dia_cm', sa.Float(), nullable=False),
        sa.Column('height_m', sa.Float(), nullable=True),
        sa.Column('tree_class', sa.String(length=10), nullable=True),

        # Spatial location (stored as Geography for accurate distance calculations)
        # H1.4 / S1-12: spatial_index=False — GeoAlchemy2 otherwise auto-emits an
        # index named `idx_inventory_trees_location`, the same name this migration
        # creates explicitly at the end of upgrade(). Running from an empty database
        # therefore failed with DuplicateTable. Latent until now because no one had
        # ever built this schema from migrations.
        sa.Column('location', Geography('POINT', srid=4326, spatial_index=False),
                  nullable=False),

        # Calculated volumes
        sa.Column('stem_volume', sa.Float(), nullable=True),
        sa.Column('branch_volume', sa.Float(), nullable=True),
        sa.Column('tree_volume', sa.Float(), nullable=True),
        sa.Column('gross_volume', sa.Float(), nullable=True),
        sa.Column('net_volume', sa.Float(), nullable=True),
        sa.Column('net_volume_cft', sa.Float(), nullable=True),
        sa.Column('firewood_m3', sa.Float(), nullable=True),
        sa.Column('firewood_chatta', sa.Float(), nullable=True),

        # Mother tree designation
        sa.Column('remark', sa.String(length=50), nullable=True),  # 'Mother Tree' or 'Felling Tree'
        sa.Column('grid_cell_id', sa.Integer(), nullable=True),

        # Metadata
        sa.Column('local_name', sa.String(length=100), nullable=True),
        sa.Column('row_number', sa.Integer(), nullable=True),  # Original row in CSV

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

        sa.ForeignKeyConstraint(['inventory_calculation_id'], ['public.inventory_calculations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )

    # Indexes for inventory_trees
    op.create_index('idx_inventory_trees_calc', 'inventory_trees', ['inventory_calculation_id'], unique=False, schema='public')
    op.create_index('idx_inventory_trees_location', 'inventory_trees', ['location'], unique=False, schema='public', postgresql_using='gist')
    op.create_index('idx_inventory_trees_remark', 'inventory_trees', ['remark'], unique=False, schema='public')
    op.create_index('idx_inventory_trees_species', 'inventory_trees', ['species'], unique=False, schema='public')

    print("[OK] Created inventory_trees table")

    # 4. Validation logs table
    op.create_table(
        'inventory_validation_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('inventory_calculation_id', postgresql.UUID(as_uuid=True), nullable=True),

        # Validation metadata
        sa.Column('validated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('total_rows', sa.Integer(), nullable=True),
        sa.Column('valid_rows', sa.Integer(), nullable=True),
        sa.Column('error_rows', sa.Integer(), nullable=True),
        sa.Column('warning_rows', sa.Integer(), nullable=True),
        sa.Column('auto_corrections', sa.Integer(), nullable=True),

        # Detection results
        sa.Column('detected_crs', sa.String(length=20), nullable=True),
        sa.Column('detected_diameter_type', sa.String(length=20), nullable=True),  # 'diameter' or 'girth'
        sa.Column('coordinate_x_column', sa.String(length=50), nullable=True),
        sa.Column('coordinate_y_column', sa.String(length=50), nullable=True),

        # Full validation report (JSON)
        sa.Column('validation_report', postgresql.JSONB, nullable=True),

        # User actions
        sa.Column('user_confirmed', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('user_confirmation_time', sa.DateTime(timezone=True), nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

        sa.ForeignKeyConstraint(['inventory_calculation_id'], ['public.inventory_calculations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )

    # Indexes for validation_logs
    op.create_index('idx_validation_logs_calc', 'inventory_validation_logs', ['inventory_calculation_id'], unique=False, schema='public')

    print("[OK] Created inventory_validation_logs table")

    # 5. Validation issues table (row-level issues)
    op.create_table(
        'inventory_validation_issues',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('validation_log_id', postgresql.UUID(as_uuid=True), nullable=False),

        # Issue details
        sa.Column('row_number', sa.Integer(), nullable=False),
        sa.Column('column_name', sa.String(length=100), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=False),  # 'error', 'warning', 'info'
        sa.Column('issue_type', sa.String(length=50), nullable=True),  # 'species_fuzzy_match', 'girth_detected', etc.

        # Values
        sa.Column('original_value', sa.Text(), nullable=True),
        sa.Column('corrected_value', sa.Text(), nullable=True),

        # Message
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),  # 0.0 to 1.0

        # User action
        sa.Column('user_accepted', sa.Boolean(), nullable=True),  # NULL = pending, TRUE = accepted, FALSE = rejected

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

        sa.ForeignKeyConstraint(['validation_log_id'], ['public.inventory_validation_logs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )

    # Indexes for validation_issues
    op.create_index('idx_validation_issues_log', 'inventory_validation_issues', ['validation_log_id'], unique=False, schema='public')
    op.create_index('idx_validation_issues_severity', 'inventory_validation_issues', ['severity'], unique=False, schema='public')

    print("[OK] Created inventory_validation_issues table")

    print("\n=== Inventory tables created successfully ===")


def downgrade() -> None:
    """Drop inventory-related tables"""

    # Drop in reverse order (due to foreign keys)
    op.drop_table('inventory_validation_issues', schema='public')
    print("[OK] Dropped inventory_validation_issues table")

    op.drop_table('inventory_validation_logs', schema='public')
    print("[OK] Dropped inventory_validation_logs table")

    op.drop_table('inventory_trees', schema='public')
    print("[OK] Dropped inventory_trees table")

    op.drop_table('inventory_calculations', schema='public')
    print("[OK] Dropped inventory_calculations table")

    op.drop_table('tree_species_coefficients', schema='public')
    print("[OK] Dropped tree_species_coefficients table")

    print("\n=== Inventory tables dropped successfully ===")
