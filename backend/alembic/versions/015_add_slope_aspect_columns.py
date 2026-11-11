"""Add slope and aspect columns to fieldbook table

Revision ID: 015_add_slope_aspect_columns
Revises: 
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '015_add_slope_aspect_columns'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade():
    # Add slope_code column
    op.add_column('fieldbook', 
        sa.Column('slope_code', sa.Integer(), nullable=True, server_default=None)
    )
    
    # Add slope_class column
    op.add_column('fieldbook',
        sa.Column('slope_class', sa.String(20), nullable=True)
    )
    
    # Add aspect_code column
    op.add_column('fieldbook',
        sa.Column('aspect_code', sa.Integer(), nullable=True)
    )
    
    # Add aspect_class column
    op.add_column('fieldbook',
        sa.Column('aspect_class', sa.String(20), nullable=True)
    )


def downgrade():
    op.drop_column('fieldbook', 'aspect_class')
    op.drop_column('fieldbook', 'aspect_code')
    op.drop_column('fieldbook', 'slope_class')
    op.drop_column('fieldbook', 'slope_code')