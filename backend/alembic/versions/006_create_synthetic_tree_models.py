"""Create synthetic_tree_models table

Revision ID: 006
Revises: 005
Create Date: 2026-02-18

Stores metadata for generated synthetic tree distribution models
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create synthetic_tree_models table"""

    op.create_table(
        'synthetic_tree_models',
        sa.Column('id', postgresql.UUID(as_uuid=True),
                  nullable=False,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('calculation_id', postgresql.UUID(as_uuid=True),
                  nullable=False),

        # Model parameters
        sa.Column('model_version', sa.String(length=20), nullable=False),
        sa.Column('algorithm_config', postgresql.JSONB, nullable=False,
                  comment='Algorithm parameters: min_dbh, min_height, max_trees_per_ha, etc.'),

        # Generation statistics
        sa.Column('total_trees', sa.Integer(), nullable=True),
        sa.Column('area_hectares', sa.Float(), nullable=True),
        sa.Column('trees_per_hectare', sa.Float(), nullable=True),
        sa.Column('min_dbh_cm', sa.Float(), nullable=True),
        sa.Column('max_dbh_cm', sa.Float(), nullable=True),
        sa.Column('min_height_m', sa.Float(), nullable=True),
        sa.Column('max_height_m', sa.Float(), nullable=True),

        # File information
        sa.Column('gpkg_filename', sa.String(length=255), nullable=True),
        sa.Column('file_size_mb', sa.Float(), nullable=True),
        sa.Column('file_path', sa.Text(), nullable=True),

        # Status tracking
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='processing',
                  comment='processing, completed, failed'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('progress_percent', sa.Integer(), nullable=True,
                  server_default='0'),
        sa.Column('current_step', sa.String(length=100), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True),
                  nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processing_time_seconds', sa.Integer(), nullable=True),

        # User tracking
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),

        # Foreign keys
        sa.ForeignKeyConstraint(['calculation_id'], ['public.calculations.id'],
                               ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['public.users.id']),

        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )

    # Create indexes
    op.create_index('idx_synthetic_models_calculation',
                    'synthetic_tree_models',
                    ['calculation_id'],
                    unique=False,
                    schema='public')

    op.create_index('idx_synthetic_models_user',
                    'synthetic_tree_models',
                    ['user_id'],
                    unique=False,
                    schema='public')

    op.create_index('idx_synthetic_models_status',
                    'synthetic_tree_models',
                    ['status'],
                    unique=False,
                    schema='public')

    print("Created synthetic_tree_models table successfully")


def downgrade() -> None:
    """Drop synthetic_tree_models table"""
    op.drop_index('idx_synthetic_models_status',
                  table_name='synthetic_tree_models',
                  schema='public')
    op.drop_index('idx_synthetic_models_user',
                  table_name='synthetic_tree_models',
                  schema='public')
    op.drop_index('idx_synthetic_models_calculation',
                  table_name='synthetic_tree_models',
                  schema='public')
    op.drop_table('synthetic_tree_models', schema='public')

    print("Dropped synthetic_tree_models table")
