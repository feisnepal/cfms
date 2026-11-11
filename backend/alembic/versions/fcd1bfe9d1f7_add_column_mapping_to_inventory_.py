"""add_column_mapping_to_inventory_calculations

Revision ID: fcd1bfe9d1f7
Revises: dd0c705443a5
Create Date: 2026-02-13 08:21:49.589713

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = 'fcd1bfe9d1f7'
down_revision = 'dd0c705443a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add column_mapping column to inventory_calculations table"""
    op.add_column(
        'inventory_calculations',
        sa.Column('column_mapping', JSONB, nullable=True),
        schema='public'
    )


def downgrade() -> None:
    """Remove column_mapping column from inventory_calculations table"""
    op.drop_column('inventory_calculations', 'column_mapping', schema='public')
