"""Add performance indexes to forest_blocks table

Revision ID: 024_add_forest_blocks_indexes
Revises: b1028e3b11b0
Create Date: 2026-04-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '024_add_forest_blocks_indexes'
down_revision = 'b1028e3b11b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(conn)
    existing_indexes = {idx['name'] for idx in inspector.get_indexes('forest_blocks', schema='public')}

    if 'idx_forest_blocks_calculation' not in existing_indexes:
        op.create_index('idx_forest_blocks_calculation', 'forest_blocks', ['calculation_id'], schema='public')
    if 'idx_forest_blocks_parent' not in existing_indexes:
        op.create_index('idx_forest_blocks_parent', 'forest_blocks', ['parent_block_id'], schema='public')
    if 'idx_forest_blocks_is_compartment' not in existing_indexes:
        op.create_index('idx_forest_blocks_is_compartment', 'forest_blocks', ['is_compartment'], schema='public')
    if 'idx_forest_blocks_geometry' not in existing_indexes:
        op.create_index('idx_forest_blocks_geometry', 'forest_blocks', ['geometry'], schema='public', postgresql_using='gist')
    if 'idx_forest_blocks_calc_compartment' not in existing_indexes:
        op.create_index('idx_forest_blocks_calc_compartment', 'forest_blocks', ['calculation_id', 'is_compartment'], schema='public')


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_forest_blocks_calculation")
    op.execute("DROP INDEX IF EXISTS idx_forest_blocks_parent")
    op.execute("DROP INDEX IF EXISTS idx_forest_blocks_is_compartment")
    op.execute("DROP INDEX IF EXISTS idx_forest_blocks_geometry")
    op.execute("DROP INDEX IF EXISTS idx_forest_blocks_calc_compartment")
