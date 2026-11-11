"""Add draft support to calculations

Revision ID: 015
Revises: 014
Create Date: 2026-03-29

Add draft_data and is_draft columns to calculations table to support
saving work-in-progress polygon creation (islands) to the server.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade():
    # Add is_draft column
    op.add_column('calculations',
        sa.Column('is_draft', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add draft_data JSONB column for storing work-in-progress
    op.add_column('calculations',
        sa.Column('draft_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )

    # Add index on is_draft for faster draft queries
    op.create_index('ix_calculations_is_draft', 'calculations', ['is_draft', 'user_id'])

    print("[OK] Added draft support columns to calculations table")


def downgrade():
    # Remove index
    op.drop_index('ix_calculations_is_draft', table_name='calculations')

    # Remove columns
    op.drop_column('calculations', 'draft_data')
    op.drop_column('calculations', 'is_draft')

    print("[OK] Removed draft support columns from calculations table")
