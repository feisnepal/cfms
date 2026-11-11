"""Create all_tree_exports table

Revision ID: 025_create_all_tree_exports
Revises: 023
Create Date: 2026-06-07

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision = '025_create_all_tree_exports'
down_revision = '023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'all_tree_exports',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('calculation_id', UUID(as_uuid=True), sa.ForeignKey('public.calculations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('public.users.id'), nullable=False),

        sa.Column('model_type', sa.String(20), nullable=False, server_default='full_extent'),
        sa.Column('model_version', sa.String(20), nullable=False),
        sa.Column('algorithm_config', JSONB, nullable=False),

        sa.Column('total_trees', sa.Integer, nullable=True),
        sa.Column('area_hectares', sa.Float, nullable=True),
        sa.Column('trees_per_hectare', sa.Float, nullable=True),
        sa.Column('min_dbh_cm', sa.Float, nullable=True),
        sa.Column('max_dbh_cm', sa.Float, nullable=True),
        sa.Column('min_height_m', sa.Float, nullable=True),
        sa.Column('max_height_m', sa.Float, nullable=True),

        sa.Column('gpkg_filename', sa.String(255), nullable=True),
        sa.Column('gpkg_size_mb', sa.Float, nullable=True),
        sa.Column('gpkg_path', sa.Text, nullable=True),

        sa.Column('excel_filename', sa.String(255), nullable=True),
        sa.Column('excel_size_mb', sa.Float, nullable=True),
        sa.Column('excel_path', sa.Text, nullable=True),

        sa.Column('csv_filename', sa.String(255), nullable=True),
        sa.Column('csv_size_mb', sa.Float, nullable=True),
        sa.Column('csv_path', sa.Text, nullable=True),

        sa.Column('status', sa.String(20), nullable=False, server_default='processing'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('progress_percent', sa.Integer, nullable=True, server_default='0'),
        sa.Column('current_step', sa.String(100), nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processing_time_seconds', sa.Integer, nullable=True),

        schema='public',
    )

    op.create_index('idx_all_tree_exports_calculation', 'all_tree_exports', ['calculation_id'], schema='public')
    op.create_index('idx_all_tree_exports_user', 'all_tree_exports', ['user_id'], schema='public')
    op.create_index('idx_all_tree_exports_status', 'all_tree_exports', ['status'], schema='public')


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_all_tree_exports_calculation")
    op.execute("DROP INDEX IF EXISTS public.idx_all_tree_exports_user")
    op.execute("DROP INDEX IF EXISTS public.idx_all_tree_exports_status")
    op.drop_table('all_tree_exports', schema='public')
