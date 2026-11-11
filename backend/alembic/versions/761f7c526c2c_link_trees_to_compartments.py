"""Link trees to compartments

Revision ID: 761f7c526c2c
Revises: b1028e3b11b0
Create Date: 2026-04-04 17:11:01.523672

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = '761f7c526c2c'
down_revision = 'b1028e3b11b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(conn)
    existing_columns = {col['name'] for col in inspector.get_columns('inventory_trees', schema='public')}

    if 'forest_block_id' not in existing_columns:
        op.add_column(
            'inventory_trees',
            sa.Column('forest_block_id', UUID(as_uuid=True), nullable=True),
            schema='public'
        )
    if 'compartment_id' not in existing_columns:
        op.add_column(
            'inventory_trees',
            sa.Column('compartment_id', UUID(as_uuid=True), nullable=True),
            schema='public'
        )

    existing_fks = {fk['name'] for fk in inspector.get_foreign_keys('inventory_trees', schema='public')}

    if 'fk_inventory_trees_forest_block' not in existing_fks:
        op.create_foreign_key(
            'fk_inventory_trees_forest_block',
            'inventory_trees', 'forest_blocks',
            ['forest_block_id'], ['id'],
            source_schema='public', referent_schema='public',
            ondelete='SET NULL'
        )
    if 'fk_inventory_trees_compartment' not in existing_fks:
        op.create_foreign_key(
            'fk_inventory_trees_compartment',
            'inventory_trees', 'forest_blocks',
            ['compartment_id'], ['id'],
            source_schema='public', referent_schema='public',
            ondelete='SET NULL'
        )

    existing_checks = {ck['name'] for ck in inspector.get_check_constraints('inventory_trees', schema='public')}

    if 'check_tree_assignment' not in existing_checks:
        op.create_check_constraint(
            'check_tree_assignment',
            'inventory_trees',
            '(forest_block_id IS NOT NULL AND compartment_id IS NULL) OR (forest_block_id IS NULL AND compartment_id IS NOT NULL) OR (forest_block_id IS NULL AND compartment_id IS NULL)',
            schema='public'
        )

    existing_indexes = {idx['name'] for idx in inspector.get_indexes('inventory_trees', schema='public')}

    if 'idx_inventory_trees_forest_block' not in existing_indexes:
        op.create_index(
            'idx_inventory_trees_forest_block',
            'inventory_trees',
            ['forest_block_id'],
            schema='public'
        )
    if 'idx_inventory_trees_compartment' not in existing_indexes:
        op.create_index(
            'idx_inventory_trees_compartment',
            'inventory_trees',
            ['compartment_id'],
            schema='public'
        )


def downgrade() -> None:
    op.drop_index('idx_inventory_trees_compartment', table_name='inventory_trees', schema='public')
    op.drop_index('idx_inventory_trees_forest_block', table_name='inventory_trees', schema='public')

    op.drop_constraint('check_tree_assignment', 'inventory_trees', type_='check', schema='public')

    op.drop_constraint('fk_inventory_trees_compartment', 'inventory_trees', type_='foreignkey', schema='public')
    op.drop_constraint('fk_inventory_trees_forest_block', 'inventory_trees', type_='foreignkey', schema='public')

    op.drop_column('inventory_trees', 'compartment_id', schema='public')
    op.drop_column('inventory_trees', 'forest_block_id', schema='public')
