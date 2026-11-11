"""Add activity_spatial_assignments and activity_drawn_features tables

Revision ID: 022_add_activity_spatial_tables
Revises: 021_add_name_to_spatial_data
Create Date: 2026-04-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from geoalchemy2 import Geometry

revision = '022_add_activity_spatial_tables'
down_revision = '021_add_name_to_spatial_data'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'activity_spatial_assignments' not in existing_tables:
        op.create_table(
            'activity_spatial_assignments',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
            sa.Column('proposed_activity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('proposed_yearly_activities.id', ondelete='cascade'), nullable=False),
            sa.Column('block_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('forest_blocks.id', ondelete='cascade'), nullable=True),
            sa.Column('sub_area_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('forest_sub_areas.id', ondelete='cascade'), nullable=True),
            sa.Column('assignment_type', sa.String(20), nullable=False, server_default='all_blocks'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
            sa.CheckConstraint(
                "(block_id IS NOT NULL AND sub_area_id IS NULL) OR (block_id IS NULL AND sub_area_id IS NOT NULL) OR (assignment_type = 'all_blocks')",
                name='chk_block_or_subarea'
            ),
            sa.CheckConstraint("assignment_type IN ('all_blocks', 'block', 'sub_area')", name='chk_assignment_type')
        )

    if 'activity_drawn_features' not in existing_tables:
        op.create_table(
            'activity_drawn_features',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
            sa.Column('proposed_activity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('proposed_yearly_activities.id', ondelete='cascade'), nullable=False),
            sa.Column('feature_type', sa.String(20), nullable=False),
            sa.Column('geometry', Geometry, nullable=False),
            sa.Column('properties', postgresql.JSONB, server_default='{}'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
            sa.CheckConstraint("feature_type IN ('point', 'line', 'polygon')", name='chk_feature_type')
        )

    existing_cols = [c['name'] for c in inspector.get_columns('proposed_yearly_activities')]
    if 'assign_to_all_blocks' not in existing_cols:
        op.add_column('proposed_yearly_activities', sa.Column('assign_to_all_blocks', sa.Boolean(), server_default='false'))
    if 'use_custom_yearly_values' not in existing_cols:
        op.add_column('proposed_yearly_activities', sa.Column('use_custom_yearly_values', sa.Boolean(), server_default='false'))


def downgrade():
    op.drop_column('proposed_yearly_activities', 'use_custom_yearly_values')
    op.drop_column('proposed_yearly_activities', 'assign_to_all_blocks')
    op.drop_table('activity_drawn_features')
    op.drop_table('activity_spatial_assignments')
