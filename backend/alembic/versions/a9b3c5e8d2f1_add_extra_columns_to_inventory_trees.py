"""Add extra_columns to inventory_trees

Revision ID: a9b3c5e8d2f1
Revises: 004
Create Date: 2026-02-13

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a9b3c5e8d2f1'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add extra_columns JSONB field to inventory_trees table"""
    op.add_column(
        'inventory_trees',
        sa.Column('extra_columns', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema='public'
    )
    print("Added extra_columns JSONB field to inventory_trees table")


def downgrade() -> None:
    """Remove extra_columns field"""
    op.drop_column('inventory_trees', 'extra_columns', schema='public')
    print("Removed extra_columns field from inventory_trees table")
