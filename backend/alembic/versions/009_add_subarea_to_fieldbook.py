"""Add sub_area fields to fieldbook

Revision ID: 009_add_subarea_to_fieldbook
Revises: 008
Create Date: 2026-03-09

"""
from alembic import op
import sqlalchemy as sa

revision = '009_add_subarea_to_fieldbook'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(conn)
    existing_cols = [c['name'] for c in inspector.get_columns('fieldbook')]

    if 'sub_area_name' not in existing_cols:
        op.add_column('fieldbook',
            sa.Column('sub_area_name', sa.String(length=100), nullable=True),
            schema='public'
        )

    if 'is_excluded' not in existing_cols:
        op.add_column('fieldbook',
            sa.Column('is_excluded', sa.Boolean(), nullable=True),
            schema='public'
        )


def downgrade():
    op.drop_column('fieldbook', 'is_excluded', schema='public')
    op.drop_column('fieldbook', 'sub_area_name', schema='public')
