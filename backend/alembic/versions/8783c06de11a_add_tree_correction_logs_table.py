"""add_tree_correction_logs_table

Revision ID: 8783c06de11a
Revises: 54ffbb599b3c
Create Date: 2026-02-05 21:55:34.109788

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8783c06de11a'
down_revision = '54ffbb599b3c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add tree_correction_logs table and correction tracking fields to inventory_trees
    """
    # Create tree_correction_logs table
    op.create_table(
        'tree_correction_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('inventory_calculation_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tree_row_number', sa.Integer(), nullable=False),
        sa.Column('species', sa.String(255), nullable=True),
        sa.Column('original_x', sa.Float(), nullable=False),
        sa.Column('original_y', sa.Float(), nullable=False),
        sa.Column('corrected_x', sa.Float(), nullable=False),
        sa.Column('corrected_y', sa.Float(), nullable=False),
        sa.Column('distance_moved_meters', sa.Float(), nullable=False),
        sa.Column('correction_reason', sa.String(100), nullable=False),
        sa.Column('corrected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['inventory_calculation_id'], ['public.inventory_calculations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )

    # Add indexes for faster queries
    op.create_index('idx_tree_corrections_inventory', 'tree_correction_logs', ['inventory_calculation_id'], schema='public')

    # Add correction tracking fields to inventory_trees
    op.add_column('inventory_trees', sa.Column('was_corrected', sa.Boolean(), nullable=False, server_default='false'), schema='public')
    op.add_column('inventory_trees', sa.Column('original_x', sa.Float(), nullable=True), schema='public')
    op.add_column('inventory_trees', sa.Column('original_y', sa.Float(), nullable=True), schema='public')


def downgrade() -> None:
    """
    Remove correction tracking
    """
    # Remove columns from inventory_trees
    op.drop_column('inventory_trees', 'original_y', schema='public')
    op.drop_column('inventory_trees', 'original_x', schema='public')
    op.drop_column('inventory_trees', 'was_corrected', schema='public')

    # Drop indexes
    op.drop_index('idx_tree_corrections_inventory', table_name='tree_correction_logs', schema='public')

    # Drop table
    op.drop_table('tree_correction_logs', schema='public')
