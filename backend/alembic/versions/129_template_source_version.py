"""op_templates.source_version: the version of the original a copy was taken from.

Revision ID: 129_template_source_version
Revises: 128_ntfp_regulation
Create Date: 2026-10-18

A copy remembers its original (``source_template_id``) but not which version of it. Without that the store cannot tell a copy
that is up to date from one whose original has since changed, so it cannot show the "original updated" notice. Existing copies
get NULL, which the notice reads as "unknown, compare by section ids".
"""
import sqlalchemy as sa
from alembic import op

revision = "129_template_source_version"
down_revision = "128_ntfp_regulation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("op_templates", sa.Column("source_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("op_templates", "source_version")
