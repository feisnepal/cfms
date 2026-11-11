"""add_forest_name_block_name_to_calculations

Revision ID: 5f6a2dd6d50f
Revises: 001
Create Date: 2026-01-23 13:19:33.616731

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5f6a2dd6d50f'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add forest_name and block_name columns to calculations table
    op.add_column('calculations',
                  sa.Column('forest_name', sa.String(length=255), nullable=True),
                  schema='public')
    op.add_column('calculations',
                  sa.Column('block_name', sa.String(length=255), nullable=True),
                  schema='public')
    print("Added forest_name and block_name columns to calculations table")


def downgrade() -> None:
    # Remove forest_name and block_name columns from calculations table
    op.drop_column('calculations', 'block_name', schema='public')
    op.drop_column('calculations', 'forest_name', schema='public')
    print("Removed forest_name and block_name columns from calculations table")
