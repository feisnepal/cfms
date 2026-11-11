"""Add op_table_definitions and op_table_data tables for Operational Plan Tables 1-32

Revision ID: 017
Revises: db18e20ca954
Create Date: 2026-05-19 09:25:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '017'
down_revision = 'db18e20ca954'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('op_table_definitions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('table_id', sa.String(length=20), nullable=False),
        sa.Column('title_ne', sa.String(length=255), nullable=False),
        sa.Column('title_en', sa.String(length=255), nullable=False),
        sa.Column('auto_populatable', sa.Boolean(), nullable=False),
        sa.Column('data_source', sa.String(length=100), nullable=True),
        sa.Column('column_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('table_id'),
        schema='public'
    )

    op.create_table('op_table_data',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('calculation_id', sa.UUID(), nullable=False),
        sa.Column('table_id', sa.String(length=20), nullable=False),
        sa.Column('rows', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('auto_populated', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(['calculation_id'], ['public.calculations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )


def downgrade() -> None:
    op.drop_table('op_table_data', schema='public')
    op.drop_table('op_table_definitions', schema='public')
