"""Add compartment fields to forest_blocks

Revision ID: 220a50e38095
Revises: 014
Create Date: 2026-04-04 17:08:51.911534

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '220a50e38095'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(conn)
    existing_cols = [c['name'] for c in inspector.get_columns('forest_blocks', schema='public')]
    existing_indexes = [i['name'] for i in inspector.get_indexes('forest_blocks', schema='public')]

    if 'is_compartment' not in existing_cols:
        op.add_column(
            'forest_blocks',
            sa.Column('is_compartment', sa.Boolean(), nullable=False, server_default='false'),
            schema='public'
        )

    if 'parent_block_id' not in existing_cols:
        op.add_column(
            'forest_blocks',
            sa.Column('parent_block_id', UUID(as_uuid=True), nullable=True),
            schema='public'
        )

    if 'compartment_code' not in existing_cols:
        op.add_column(
            'forest_blocks',
            sa.Column('compartment_code', sa.String(50), nullable=True),
            schema='public'
        )

    if 'area_sqm' not in existing_cols:
        op.add_column(
            'forest_blocks',
            sa.Column('area_sqm', sa.Float(), nullable=True),
            schema='public'
        )

    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.engine.reflection import Inspector
    fks = [fk['name'] for fk in inspector.get_foreign_keys('forest_blocks', schema='public')]
    if 'fk_forest_blocks_parent_block_id' not in fks:
        op.create_foreign_key(
            'fk_forest_blocks_parent_block_id',
            'forest_blocks', 'forest_blocks',
            ['parent_block_id'], ['id'],
            source_schema='public', referent_schema='public',
            ondelete='CASCADE'
        )

    if 'idx_forest_blocks_parent' not in existing_indexes:
        op.create_index(
            'idx_forest_blocks_parent',
            'forest_blocks',
            ['parent_block_id'],
            schema='public'
        )
    if 'idx_forest_blocks_is_compartment' not in existing_indexes:
        op.create_index(
            'idx_forest_blocks_is_compartment',
            'forest_blocks',
            ['is_compartment'],
            schema='public'
        )
    if 'idx_forest_blocks_compartment_code' not in existing_indexes:
        op.create_index(
            'idx_forest_blocks_compartment_code',
            'forest_blocks',
            ['compartment_code'],
            schema='public'
        )


def downgrade() -> None:
    # H1.12 / S1-12: upgrade() guards every create_index with an existence
    # check, so any of these may legitimately not be here. Dropping them
    # unconditionally made `downgrade base` fail with UndefinedObject. The
    # downgrade now mirrors the upgrade's conditionality.
    for _idx in ('idx_forest_blocks_compartment_code',
                 'idx_forest_blocks_is_compartment',
                 'idx_forest_blocks_parent'):
        op.execute(f'DROP INDEX IF EXISTS public.{_idx}')
    op.execute('ALTER TABLE public.forest_blocks '
               'DROP CONSTRAINT IF EXISTS fk_forest_blocks_parent_block_id')
    op.drop_column('forest_blocks', 'area_sqm', schema='public')
    op.drop_column('forest_blocks', 'compartment_code', schema='public')
    op.drop_column('forest_blocks', 'parent_block_id', schema='public')
    op.drop_column('forest_blocks', 'is_compartment', schema='public')
