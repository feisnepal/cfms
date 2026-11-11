"""A sub-area assignment names its unit AND its sub-area (the model's rule), and the sub-area has no foreign key.

Migration 022 made a sub-area assignment impossible (its CHECK allowed a block XOR a sub-area) and pointed
``sub_area_id`` at the unused ``forest_sub_areas`` table, while sub-areas live in ``calculations.result_data``. The
development database had been aligned by hand; a database built from the migrations was not. This makes both the same.

Revision ID: 115_align_spatial_assignment_constraint
Revises: 114_add_user_role_changes
Create Date: 2026-10-08
"""
from alembic import op

revision = "115_align_spatial_assignment_constraint"
down_revision = "114_add_user_role_changes"
branch_labels = None
depends_on = None

_RULE = (
    "(assignment_type = 'all_blocks') OR "
    "(block_id IS NOT NULL AND sub_area_id IS NULL AND assignment_type = 'block') OR "
    "(block_id IS NOT NULL AND sub_area_id IS NOT NULL AND assignment_type = 'sub_area')"
)


def upgrade() -> None:
    op.execute("ALTER TABLE activity_spatial_assignments DROP CONSTRAINT IF EXISTS chk_block_or_subarea")
    op.execute("ALTER TABLE activity_spatial_assignments DROP CONSTRAINT IF EXISTS activity_spatial_assignments_sub_area_id_fkey")
    op.execute(f"ALTER TABLE activity_spatial_assignments ADD CONSTRAINT chk_block_or_subarea CHECK ({_RULE})")


def downgrade() -> None:
    # The old rule would reject existing sub-area rows; nothing sensible to restore.
    pass
