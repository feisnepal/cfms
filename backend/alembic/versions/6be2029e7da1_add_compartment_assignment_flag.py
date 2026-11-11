"""Add compartment assignment flag

Revision ID: 6be2029e7da1
Revises: 761f7c526c2c
Create Date: 2026-04-04 17:12:17.957767

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6be2029e7da1'
down_revision = '761f7c526c2c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(conn)
    existing_columns = {col['name'] for col in inspector.get_columns('inventory_calculations', schema='public')}

    if 'needs_compartment_assignment' not in existing_columns:
        op.add_column(
            'inventory_calculations',
            sa.Column('needs_compartment_assignment', sa.Boolean(), nullable=False, server_default='false'),
            schema='public'
        )


def downgrade() -> None:
    op.drop_column('inventory_calculations', 'needs_compartment_assignment', schema='public')
