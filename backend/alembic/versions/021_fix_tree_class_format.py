"""Fix tree_class values stored as '1.0' instead of '1'

Tree class was being stored as str(value) which gave "1.0" for float input,
causing the FSM workaround in OP document queries. Now the import normalizes
to int first, so existing data needs cleanup.

Revision ID: 021
Revises: 020
Create Date: 2026-05-22 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '021'
down_revision = '020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fix field_inventory_measurements — strip ".0" suffix from tree_class
    op.execute("""
        UPDATE public.field_inventory_measurements
        SET tree_class = REPLACE(tree_class, '.0', '')
        WHERE tree_class LIKE '%.0'
    """)
    # Fix inventory_trees — strip ".0" suffix from tree_class
    op.execute("""
        UPDATE public.inventory_trees
        SET tree_class = REPLACE(tree_class, '.0', '')
        WHERE tree_class LIKE '%.0'
    """)


def downgrade() -> None:
    # No clean way to reverse — re-add ".0" would be wrong for already-correct values
    pass
