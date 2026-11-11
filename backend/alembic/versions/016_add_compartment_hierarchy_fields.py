"""Add compartment hierarchy fields

Revision ID: 015
Revises: 014
Create Date: 2026-05-07

This migration adds support for:
- Hierarchical compartment structure (sub-compartments)
- Color coding for visual distinction
- Lock mechanism to prevent further division
- Child count caching for performance
- Display order for sorting
"""
from alembic import op
import sqlalchemy as sa


revision = '016'
down_revision = '015_add_slope_aspect_columns'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add new columns to forest_blocks table for hierarchy support
    """
    # Add division_level column (0=Block, 1=Compartment, 2+=Sub-Compartment)
    op.add_column(
        'forest_blocks',
        sa.Column('division_level', sa.Integer(), nullable=True),
        schema='public'
    )
    
    # Add color column (hex color like "#FF5733")
    op.add_column(
        'forest_blocks',
        sa.Column('color', sa.String(7), nullable=True),
        schema='public'
    )
    
    # Add is_locked column (prevent further division)
    op.add_column(
        'forest_blocks',
        sa.Column('is_locked', sa.Boolean(), nullable=True),
        schema='public'
    )
    
    # Add child_count column (cached count of children)
    op.add_column(
        'forest_blocks',
        sa.Column('child_count', sa.Integer(), nullable=True),
        schema='public'
    )
    
    # Add display_order column (order within parent's list)
    op.add_column(
        'forest_blocks',
        sa.Column('display_order', sa.Integer(), nullable=True),
        schema='public'
    )
    
    # Create indexes for performance
    op.create_index(
        'idx_forest_blocks_parent_id',
        'forest_blocks',
        ['parent_block_id'],
        schema='public'
    )
    
    op.create_index(
        'idx_forest_blocks_calc_division',
        'forest_blocks',
        ['calculation_id', 'division_level'],
        schema='public'
    )
    
    # Set default values for existing records
    connection = op.get_bind()
    
    # Set division_level based on existing data
    connection.execute(sa.text("""
        UPDATE public.forest_blocks 
        SET division_level = CASE 
            WHEN parent_block_id IS NULL THEN 0 
            ELSE 1 
        END
        WHERE division_level IS NULL
    """))
    
    # Assign random colors to existing compartments
    connection.execute(sa.text("""
        UPDATE public.forest_blocks 
        SET color = '#' || LPAD(TO_HEX(FLOOR(RANDOM() * 16777215)::INT), 6, '0')
        WHERE is_compartment = TRUE AND color IS NULL
    """))
    
    # Set default values for boolean/integer fields
    connection.execute(sa.text("""
        UPDATE public.forest_blocks 
        SET is_locked = FALSE 
        WHERE is_locked IS NULL
    """))
    
    connection.execute(sa.text("""
        UPDATE public.forest_blocks 
        SET child_count = 0 
        WHERE child_count IS NULL
    """))
    
    connection.execute(sa.text("""
        UPDATE public.forest_blocks 
        SET display_order = index 
        WHERE display_order IS NULL
    """))
    
    # Update child_count for parent blocks that have compartments
    connection.execute(sa.text("""
        UPDATE public.forest_blocks b
        SET child_count = (
            SELECT COUNT(*) 
            FROM public.forest_blocks 
            WHERE parent_block_id = b.id
        )
        WHERE b.parent_block_id IS NULL
    """))
    
    # Now make non-nullable columns required (after setting defaults)
    op.alter_column(
        'forest_blocks',
        'division_level',
        existing_type=sa.Integer(),
        nullable=False,
        schema='public'
    )
    
    op.alter_column(
        'forest_blocks',
        'is_locked',
        existing_type=sa.Boolean(),
        nullable=False,
        schema='public'
    )
    
    op.alter_column(
        'forest_blocks',
        'child_count',
        existing_type=sa.Integer(),
        nullable=False,
        schema='public'
    )
    
    op.alter_column(
        'forest_blocks',
        'display_order',
        existing_type=sa.Integer(),
        nullable=False,
        schema='public'
    )


def downgrade():
    """
    Remove added columns and indexes
    """
    # Drop indexes
    op.drop_index('idx_forest_blocks_calc_division', schema='public')
    op.drop_index('idx_forest_blocks_parent_id', schema='public')
    
    # Drop columns
    op.drop_column('forest_blocks', 'display_order', schema='public')
    op.drop_column('forest_blocks', 'child_count', schema='public')
    op.drop_column('forest_blocks', 'is_locked', schema='public')
    op.drop_column('forest_blocks', 'color', schema='public')
    op.drop_column('forest_blocks', 'division_level', schema='public')
