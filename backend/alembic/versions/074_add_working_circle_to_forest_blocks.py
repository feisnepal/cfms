"""Add working_circle to forest_blocks.

Revision ID: 074_add_working_circle_to_forest_blocks
Revises: 073_add_protected_stratum_to_fi_block_summary
Create Date: 2026-09-01

Protection Working Circle, P0 (PROTECTION_WORKING_CIRCLE_PLAN.md).

A forest unit now carries its management working circle:

    production  -- operable forest: felling series + Annual Allowable Harvest
    protection  -- no felling; growing stock still surveyed and reported, but
                   never fed to AAH / MAI. Carved out of the production fabric
                   at auto-create time; numbered in its own P-N series.

Every existing row is production (the server default), so there is no
backfill. Consumers that read the value off a stale ``result_data`` unit
dict must default a missing value to ``'production'``.
"""
from alembic import op
import sqlalchemy as sa

revision = "074_add_working_circle_to_forest_blocks"
down_revision = "073_add_protected_stratum_to_fi_block_summary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forest_blocks",
        sa.Column(
            "working_circle",
            sa.String(length=20),
            nullable=False,
            server_default="production",
        ),
    )
    op.create_index(
        "ix_forest_blocks_working_circle",
        "forest_blocks",
        ["calculation_id", "working_circle"],
    )


def downgrade() -> None:
    op.drop_index("ix_forest_blocks_working_circle", table_name="forest_blocks")
    op.drop_column("forest_blocks", "working_circle")
