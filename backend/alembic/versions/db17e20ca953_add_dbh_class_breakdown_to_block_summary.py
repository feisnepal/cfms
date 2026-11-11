"""add_dbh_class_breakdown_to_block_summary

Revision ID: db17e20ca953
Revises: 67289d260af3
Create Date: 2026-05-12 17:11:13.228251

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'db17e20ca953'
down_revision = '67289d260af3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('field_inventory_block_summary',
        sa.Column('dbh_class_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema='public'
    )


def downgrade() -> None:
    op.drop_column('field_inventory_block_summary', 'dbh_class_breakdown', schema='public')
