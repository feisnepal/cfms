"""Forest metadata: the plan details that belong to the forest (officers, handover / renewal dates, history, service provider).

Revision ID: 120_forest_metadata_plan_details
Revises: 119_rambhadevi_missing_activities
Create Date: 2026-10-14

Eight nullable columns on forest_metadata. They are optional (not in the mandatory EDITABLE_FIELDS), so no existing row
changes meaning and no workflow step turns red. An operational plan's own form still wins; these are what a plan falls
back to when its form field is empty.
"""

import sqlalchemy as sa
from alembic import op

revision = "120_forest_metadata_plan_details"
down_revision = "119_rambhadevi_missing_activities"
branch_labels = None
depends_on = None

COLUMNS = [
    ("cf_chairperson_name", sa.String(255)),
    ("sub_division_chief", sa.String(255)),
    ("forest_management_section_chief", sa.String(255)),
    ("division_forest_officer", sa.String(255)),
    ("technical_assistance_org", sa.String(255)),
    ("cf_handover_date", sa.String(32)),
    ("cf_first_renewal_date", sa.String(32)),
    ("cf_history_note", sa.Text()),
]


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column("forest_metadata", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("forest_metadata", name)
