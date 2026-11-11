"""Add op_data_cache table for OP export data caching

Revision ID: 027_add_op_data_cache
Revises: 026_fix_compartment_division_level
Create Date: 2026-06-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision = '027_add_op_data_cache'
down_revision = '026_fix_compartment_division_level'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'op_data_cache',
        sa.Column('calculation_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('data', JSONB, nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
        schema='public',
    )


def downgrade() -> None:
    op.drop_table('op_data_cache', schema='public')
