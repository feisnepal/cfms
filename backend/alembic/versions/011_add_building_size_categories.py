"""add building size categories

Revision ID: 011
Revises: 010
Create Date: 2026-03-21

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    # Add building size category columns to user_group_buildings table
    op.add_column('user_group_buildings',
        sa.Column('small_buildings', sa.Integer(), nullable=True, server_default='0'),
        schema='public'
    )
    op.add_column('user_group_buildings',
        sa.Column('medium_buildings', sa.Integer(), nullable=True, server_default='0'),
        schema='public'
    )
    op.add_column('user_group_buildings',
        sa.Column('large_buildings', sa.Integer(), nullable=True, server_default='0'),
        schema='public'
    )

    # Add columns for average building size
    op.add_column('user_group_buildings',
        sa.Column('average_building_size_m2', sa.Numeric(12, 2), nullable=True),
        schema='public'
    )


def downgrade():
    # Remove the added columns
    op.drop_column('user_group_buildings', 'small_buildings', schema='public')
    op.drop_column('user_group_buildings', 'medium_buildings', schema='public')
    op.drop_column('user_group_buildings', 'large_buildings', schema='public')
    op.drop_column('user_group_buildings', 'average_building_size_m2', schema='public')
