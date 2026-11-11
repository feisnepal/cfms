"""Drop forest_metadata.cf_chairperson_name: the chairperson is read from the Forest User Committee form.

Revision ID: 121_drop_forest_metadata_chairperson
Revises: 120_forest_metadata_plan_details
Create Date: 2026-10-14

The committee already records every member's position; `अध्यक्ष` is the chairperson. A second place to type the same
name could only disagree with it, so the column added in 120 is removed.
"""

import sqlalchemy as sa
from alembic import op

revision = "121_drop_forest_metadata_chairperson"
down_revision = "120_forest_metadata_plan_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("forest_metadata", "cf_chairperson_name")


def downgrade() -> None:
    op.add_column("forest_metadata", sa.Column("cf_chairperson_name", sa.String(255), nullable=True))
