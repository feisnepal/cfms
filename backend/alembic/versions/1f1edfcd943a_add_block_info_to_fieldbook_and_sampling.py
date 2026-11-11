"""add_block_info_to_fieldbook_and_sampling

Revision ID: 1f1edfcd943a
Revises: 0f8f55ed0b34
Create Date: 2026-02-05 11:51:21.013597

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1f1edfcd943a'
down_revision = '0f8f55ed0b34'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add block information columns to fieldbook table
    op.add_column('fieldbook', sa.Column('block_number', sa.Integer(), nullable=True), schema='public')
    op.add_column('fieldbook', sa.Column('block_name', sa.String(length=100), nullable=True), schema='public')

    # Add block information columns to sampling_designs table
    # Note: For sampling, we store which block each individual point belongs to
    # We'll add a JSONB column to store block assignment for each point
    op.add_column('sampling_designs', sa.Column('points_block_assignment', sa.dialects.postgresql.JSONB(), nullable=True), schema='public')

    # Add index on block_number for faster filtering
    op.create_index('idx_fieldbook_block_number', 'fieldbook', ['block_number'], schema='public')


def downgrade() -> None:
    # Remove index
    op.drop_index('idx_fieldbook_block_number', table_name='fieldbook', schema='public')

    # Remove columns from sampling_designs
    op.drop_column('sampling_designs', 'points_block_assignment', schema='public')

    # Remove columns from fieldbook
    op.drop_column('fieldbook', 'block_name', schema='public')
    op.drop_column('fieldbook', 'block_number', schema='public')
