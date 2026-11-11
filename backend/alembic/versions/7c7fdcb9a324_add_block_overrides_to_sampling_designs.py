"""add_block_overrides_to_sampling_designs

Revision ID: 7c7fdcb9a324
Revises: 2749022978b3
Create Date: 2026-02-08 07:16:05.182785

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c7fdcb9a324'
down_revision = '2749022978b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add block override support for per-block sampling parameters"""

    # Add default_parameters column to store default sampling parameters
    op.add_column('sampling_designs',
        sa.Column('default_parameters', sa.dialects.postgresql.JSONB(), nullable=True),
        schema='public'
    )

    # Add block_overrides column to store per-block parameter overrides
    op.add_column('sampling_designs',
        sa.Column('block_overrides', sa.dialects.postgresql.JSONB(), nullable=True),
        schema='public'
    )

    # Add index for faster JSON queries
    op.execute("""
        CREATE INDEX idx_sampling_block_overrides
        ON public.sampling_designs USING gin(block_overrides)
    """)

    print("Added default_parameters and block_overrides columns to sampling_designs")


def downgrade() -> None:
    """Remove block override columns"""

    # Drop index
    op.execute("DROP INDEX IF EXISTS public.idx_sampling_block_overrides")

    # Drop columns
    op.drop_column('sampling_designs', 'block_overrides', schema='public')
    op.drop_column('sampling_designs', 'default_parameters', schema='public')
