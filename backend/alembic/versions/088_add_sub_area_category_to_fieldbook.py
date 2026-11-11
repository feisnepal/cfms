"""Add sub_area_category to fieldbook.

Revision ID: 088_add_sub_area_category
Revises: 087_add_suggested_orientation_and_justifications
Create Date: 2026-09-19

fieldbook_implementation_plan.md: the fieldbook already carried sub_area_name
+ is_excluded but never the sub-area's own category (religious/plantation/
private_land/etc, from sub_area_service.VALID_CATEGORIES). Purely additive,
NULL for every existing row and for any point that isn't on a sub-area
boundary. Populated alongside sub_area_name in generate_fieldbook_points;
when two sub-areas share a vertex their categories are comma-joined the same
way their names are (plan D5).
"""
from alembic import op
import sqlalchemy as sa

revision = "088_add_sub_area_category"
down_revision = "087_add_suggested_orientation_and_justifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fieldbook",
        sa.Column("sub_area_category", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fieldbook", "sub_area_category")
