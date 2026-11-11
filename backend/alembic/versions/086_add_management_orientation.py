"""Add management_orientation to forest_blocks.

Revision ID: 086_add_management_orientation
Revises: 085_add_dominant_aspect_and_canopy_class
Create Date: 2026-09-12

User report: a slope-carved compartment should carry an editable "Management
Orientation" (Production/Conservation/Protection), auto-suggested from SFM's
own classification pipeline at Auto-Block commit time and always
user-overridable. Purely additive metadata, NULL for every existing block and
for anything not carved by the slope Auto-Block source -- same shape as
migrations 084/085's dominant_* columns. Stores the same capitalized strings
SFM's own `orientation.py` returns ("Production"/"Conservation"/"Protection"),
so it compares directly against the live "Suggested Orientation" read from
SFM's cache with no re-casing step.
"""
from alembic import op
import sqlalchemy as sa

revision = "086_add_management_orientation"
down_revision = "085_add_dominant_aspect_and_canopy_class"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forest_blocks",
        sa.Column("management_orientation", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("forest_blocks", "management_orientation")
