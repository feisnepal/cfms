"""Convert tree_class from numeric/roman codes to lowercase letters

Forest Regulation 2079 quality classes now use letter codes:
  a = Class 1 (80% timber)
  b = Class 2 (60% timber)
  c = Class 3 (30% timber)
  d = Class 4 (0% timber, all firewood)

This prevents Excel auto-converting "1" to number 1, which broke
formula string comparisons. Letters are immune to auto-conversion.

Revision ID: 022
Revises: 021
Create Date: 2026-05-22 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '022'
down_revision = '021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Convert numeric codes to letters in field_inventory_measurements
    op.execute("""
        UPDATE public.field_inventory_measurements
        SET tree_class = CASE
            WHEN tree_class IN ('1', 'i', 'I') THEN 'a'
            WHEN tree_class IN ('2', 'ii', 'II') THEN 'b'
            WHEN tree_class IN ('3', 'iii', 'III') THEN 'c'
            WHEN tree_class IN ('4', 'iv', 'IV') THEN 'd'
            ELSE lower(tree_class)
        END
        WHERE tree_class IS NOT NULL
          AND tree_class NOT IN ('a', 'b', 'c', 'd')
    """)
    # Same conversion for inventory_trees
    op.execute("""
        UPDATE public.inventory_trees
        SET tree_class = CASE
            WHEN tree_class IN ('1', 'i', 'I') THEN 'a'
            WHEN tree_class IN ('2', 'ii', 'II') THEN 'b'
            WHEN tree_class IN ('3', 'iii', 'III') THEN 'c'
            WHEN tree_class IN ('4', 'iv', 'IV') THEN 'd'
            ELSE lower(tree_class)
        END
        WHERE tree_class IS NOT NULL
          AND tree_class NOT IN ('a', 'b', 'c', 'd')
    """)


def downgrade() -> None:
    # Revert letters back to numeric codes
    op.execute("""
        UPDATE public.field_inventory_measurements
        SET tree_class = CASE
            WHEN tree_class = 'a' THEN '1'
            WHEN tree_class = 'b' THEN '2'
            WHEN tree_class = 'c' THEN '3'
            WHEN tree_class = 'd' THEN '4'
            ELSE tree_class
        END
    """)
    op.execute("""
        UPDATE public.inventory_trees
        SET tree_class = CASE
            WHEN tree_class = 'a' THEN '1'
            WHEN tree_class = 'b' THEN '2'
            WHEN tree_class = 'c' THEN '3'
            WHEN tree_class = 'd' THEN '4'
            ELSE tree_class
        END
    """)
