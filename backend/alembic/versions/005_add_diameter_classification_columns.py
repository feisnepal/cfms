"""Add diameter classification columns to inventory_trees

Revision ID: 005
Revises: a9b3c5e8d2f1
Create Date: 2026-02-15

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '005'
down_revision = 'a9b3c5e8d2f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add stand_type and dbh_class columns to inventory_trees table"""

    # Add stand_type column (simple 3-category classification)
    op.add_column(
        'inventory_trees',
        sa.Column('stand_type', sa.String(length=20), nullable=True),
        schema='public'
    )
    print("Added stand_type column to inventory_trees table")

    # Add dbh_class column (detailed 7-category classification)
    op.add_column(
        'inventory_trees',
        sa.Column('dbh_class', sa.String(length=50), nullable=True),
        schema='public'
    )
    print("Added dbh_class column to inventory_trees table")


def downgrade() -> None:
    """Remove diameter classification columns"""

    op.drop_column('inventory_trees', 'dbh_class', schema='public')
    print("Removed dbh_class column from inventory_trees table")

    op.drop_column('inventory_trees', 'stand_type', schema='public')
    print("Removed stand_type column from inventory_trees table")
