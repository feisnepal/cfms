"""add_unique_constraint_calculation_id_inventory

Revision ID: 54ffbb599b3c
Revises: 1f1edfcd943a
Create Date: 2026-02-05 20:58:43.569393

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '54ffbb599b3c'
down_revision = '1f1edfcd943a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add UNIQUE constraint on calculation_id in inventory_calculations table.
    This ensures only one tree mapping per calculation.
    """
    # First, remove any duplicate entries (keep the most recent one for each calculation_id)
    op.execute("""
        DELETE FROM public.inventory_calculations
        WHERE id NOT IN (
            SELECT DISTINCT ON (calculation_id) id
            FROM public.inventory_calculations
            WHERE calculation_id IS NOT NULL
            ORDER BY calculation_id, created_at DESC
        )
        AND calculation_id IS NOT NULL;
    """)

    # Add unique constraint on calculation_id
    op.create_unique_constraint(
        'uq_inventory_calculations_calculation_id',
        'inventory_calculations',
        ['calculation_id'],
        schema='public'
    )


def downgrade() -> None:
    """
    Remove UNIQUE constraint from calculation_id
    """
    op.drop_constraint(
        'uq_inventory_calculations_calculation_id',
        'inventory_calculations',
        schema='public',
        type_='unique'
    )
