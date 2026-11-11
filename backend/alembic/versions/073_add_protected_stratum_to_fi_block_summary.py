"""Add protection-stratum growing stock to field_inventory_block_summary.

Revision ID: 073_add_protected_stratum_to_fi_block_summary
Revises: 072_add_zone_type_to_fi_sample_plots
Create Date: 2026-09-01

Protected-area sampling stratification (design item #1, increment 2).

The per-block summary is now built from PRODUCTIVE plots only, so forest
condition, MAI and the Annual Allowable Harvest that flow from
``total_growing_stock_m3_per_ha`` exclude the protection stratum (a
protection sub-area is sampled growing-stock-only at ~0.1% and no trees are
felled there).

The protection stratum's growing stock is still wanted -- that is the whole
point of sampling it -- so it is recorded here, alongside its plot count,
and reported separately (never added to AAH).

Both columns are NULL when the block has no protection-stratum plots.
"""
from alembic import op
import sqlalchemy as sa

revision = "073_add_protected_stratum_to_fi_block_summary"
down_revision = "072_add_zone_type_to_fi_sample_plots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "field_inventory_block_summary",
        sa.Column("protected_growing_stock_m3_per_ha", sa.Numeric(15, 6), nullable=True),
        schema="public",
    )
    op.add_column(
        "field_inventory_block_summary",
        sa.Column("protected_sample_plots", sa.Integer(), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("field_inventory_block_summary", "protected_sample_plots", schema="public")
    op.drop_column("field_inventory_block_summary", "protected_growing_stock_m3_per_ha", schema="public")
