"""Create operational_plans table

Revision ID: 016_create_operational_plans_table
Revises: 015_add_slope_aspect_columns
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime

# revision identifiers
revision = '016_create_operational_plans_table'
down_revision = 'fcd1bfe9d1f7'
branch_labels = None
depends_on = None


def upgrade():
    # Create operational_plans table
    op.create_table(
        'operational_plans',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('calculation_id', UUID(as_uuid=True), sa.ForeignKey('public.calculations.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('forest_name', sa.String(255), nullable=True),
        sa.Column('sections', JSONB, nullable=True, default={}),
        sa.Column('plan_metadata', JSONB, nullable=True, default={}),
        sa.Column('status', sa.String(50), nullable=False, server_default='draft'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('public.users.id'), nullable=True),
        sa.Column('approved_by', UUID(as_uuid=True), sa.ForeignKey('public.users.id'), nullable=True),
        schema='public'
    )

    # Create indexes
    op.create_index('idx_operational_plans_calculation_id', 'operational_plans', ['calculation_id'], schema='public')
    op.create_index('idx_operational_plans_status', 'operational_plans', ['status'], schema='public')


def downgrade():
    op.drop_table('operational_plans', schema='public')
