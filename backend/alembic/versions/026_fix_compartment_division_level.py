"""Fix compartment and sub-compartment division_level values

Revision ID: 026_fix_compartment_division_level
Revises: 025_create_all_tree_exports
Create Date: 2026-06-19

Compartments created via execute_split before this fix had division_level=0
(same as Block). This migration fixes existing records so that:
  - Blocks with parent_block_id IS NULL → division_level = 0 (unchanged)
  - Compartments (is_compartment=TRUE, parent exists, not sub-compartment) → division_level = 1
  - Sub-compartments (children of compartments) → division_level = 2
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '026_fix_compartment_division_level'
down_revision = '025_create_all_tree_exports'
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()

    # Step 1: Set division_level = 1 for compartments (have parent, is_compartment=TRUE)
    connection.execute(sa.text("""
        UPDATE public.forest_blocks
        SET division_level = 1
        WHERE parent_block_id IS NOT NULL
          AND division_level = 0
          AND is_compartment = TRUE
    """))

    # Step 2: Set division_level = 2 for sub-compartments
    # (children whose parent is already a compartment)
    connection.execute(sa.text("""
        UPDATE public.forest_blocks fb_child
        SET division_level = fb_parent.division_level + 1
        FROM public.forest_blocks fb_parent
        WHERE fb_child.parent_block_id = fb_parent.id
          AND fb_child.division_level = 0
          AND fb_parent.division_level >= 1
    """))


def downgrade() -> None:
    connection = op.get_bind()

    # Revert all corrected records back to division_level = 0
    connection.execute(sa.text("""
        UPDATE public.forest_blocks
        SET division_level = 0
        WHERE is_compartment = TRUE
          AND parent_block_id IS NOT NULL
    """))
