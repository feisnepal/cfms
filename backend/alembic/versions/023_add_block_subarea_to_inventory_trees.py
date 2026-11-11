"""Add block_id and sub_area_id to inventory_trees

Revision ID: 023_add_block_subarea
Revises: 022_add_activity_spatial_tables
Create Date: 2026-04-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '023_add_block_subarea'
down_revision = '022_add_activity_spatial_tables'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(conn)
    existing_cols = [c['name'] for c in inspector.get_columns('inventory_trees')]

    if 'block_id' not in existing_cols:
        op.add_column('inventory_trees',
            sa.Column('block_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('public.forest_blocks.id', ondelete='SET NULL'),
                      nullable=True))

    if 'block_name' not in existing_cols:
        op.add_column('inventory_trees',
            sa.Column('block_name', sa.String(255), nullable=True))

    if 'sub_area_id' not in existing_cols:
        op.add_column('inventory_trees',
            sa.Column('sub_area_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('public.forest_sub_areas.id', ondelete='SET NULL'),
                      nullable=True))

    if 'sub_area_name' not in existing_cols:
        op.add_column('inventory_trees',
            sa.Column('sub_area_name', sa.String(255), nullable=True))

    from sqlalchemy import inspect as sa_inspect
    existing_indexes = [i['name'] for i in inspector.get_indexes('inventory_trees')]
    if 'idx_inventory_trees_block_id' not in existing_indexes:
        op.create_index('idx_inventory_trees_block_id', 'inventory_trees', ['block_id'])
    if 'idx_inventory_trees_sub_area_id' not in existing_indexes:
        op.create_index('idx_inventory_trees_sub_area_id', 'inventory_trees', ['sub_area_id'])


def downgrade():
    op.drop_index('idx_inventory_trees_sub_area_id', 'inventory_trees')
    op.drop_index('idx_inventory_trees_block_id', 'inventory_trees')
    op.drop_column('inventory_trees', 'sub_area_name')
    op.drop_column('inventory_trees', 'sub_area_id')
    op.drop_column('inventory_trees', 'block_name')
    op.drop_column('inventory_trees', 'block_id')
