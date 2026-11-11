"""Add resource yield columns to field inventory tables for demand-supply

Adds columns to store per-sample-plot and per-hectare resource yield values
(firewood, grass, bedding material) used by the Demand & Supply tab.

Revision ID: 028_add_resource_yield_columns
Revises: 027_add_op_data_cache
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision = '028_add_resource_yield_columns'
down_revision = '027_add_op_data_cache'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns to field_inventory_sample_plots (per-plot kg/100sqm/year)
    op.add_column('field_inventory_sample_plots',
        sa.Column('firewood_kg_per_100sqm_per_year', sa.Numeric(10, 2), nullable=True),
        schema='public'
    )
    op.add_column('field_inventory_sample_plots',
        sa.Column('grass_kg_per_100sqm_per_year', sa.Numeric(10, 2), nullable=True),
        schema='public'
    )
    op.add_column('field_inventory_sample_plots',
        sa.Column('bedding_material_kg_per_100sqm_per_year', sa.Numeric(10, 2), nullable=True),
        schema='public'
    )

    # Add columns to field_inventory_block_summary (per-ha extrapolated kg/ha/year)
    op.add_column('field_inventory_block_summary',
        sa.Column('firewood_kg_per_ha_per_year', sa.Numeric(15, 6), nullable=True),
        schema='public'
    )
    op.add_column('field_inventory_block_summary',
        sa.Column('grass_kg_per_ha_per_year', sa.Numeric(15, 6), nullable=True),
        schema='public'
    )
    op.add_column('field_inventory_block_summary',
        sa.Column('bedding_material_kg_per_ha_per_year', sa.Numeric(15, 6), nullable=True),
        schema='public'
    )


def downgrade() -> None:
    # Remove columns from field_inventory_block_summary
    op.drop_column('field_inventory_block_summary', 'bedding_material_kg_per_ha_per_year', schema='public')
    op.drop_column('field_inventory_block_summary', 'grass_kg_per_ha_per_year', schema='public')
    op.drop_column('field_inventory_block_summary', 'firewood_kg_per_ha_per_year', schema='public')

    # Remove columns from field_inventory_sample_plots
    op.drop_column('field_inventory_sample_plots', 'bedding_material_kg_per_100sqm_per_year', schema='public')
    op.drop_column('field_inventory_sample_plots', 'grass_kg_per_100sqm_per_year', schema='public')
    op.drop_column('field_inventory_sample_plots', 'firewood_kg_per_100sqm_per_year', schema='public')
