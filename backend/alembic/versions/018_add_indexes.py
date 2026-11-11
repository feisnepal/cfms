"""Add missing indexes for better query performance

Revision ID: 018
Revises: 017

"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"


def upgrade():
    op.create_index('idx_op_table_data_calc_table', 'op_table_data', ['calculation_id', 'table_id'])
    op.create_index('idx_activity_year_detail_activity', 'activity_year_details', ['proposed_activity_id'])


def downgrade():
    op.drop_index('idx_op_table_data_calc_table')
    op.drop_index('idx_activity_year_detail_activity')
