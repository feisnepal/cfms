"""Add name column to activity_spatial_data for user-defined labels

Revision ID: 021_add_name_to_spatial_data
Revises: 020_add_yearly_activities_enhancements
Create Date: 2026-04-10
"""
from alembic import op
import sqlalchemy as sa


revision = '021_add_name_to_spatial_data'
down_revision = '020_add_yearly_activities_enhancements'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'activity_spatial_data',
        sa.Column('name', sa.String(length=255), nullable=True),
        schema='public'
    )


def downgrade() -> None:
    op.drop_column('activity_spatial_data', 'name', schema='public')
