"""add_basal_area_to_field_inventory

Revision ID: 67289d260af3
Revises: 4c5dc19e96e5
Create Date: 2026-05-12 10:25:40.018624

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '67289d260af3'
down_revision = '4c5dc19e96e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add basal_area_m2 to field_inventory_measurements
    op.add_column('field_inventory_measurements',
        sa.Column('basal_area_m2', sa.Numeric(15, 6), nullable=True),
        schema='public'
    )

    # Add basal_area_m2_per_ha to field_inventory_block_summary
    op.add_column('field_inventory_block_summary',
        sa.Column('basal_area_m2_per_ha', sa.Numeric(15, 6), nullable=True),
        schema='public'
    )


def downgrade() -> None:
    # Remove basal_area_m2_per_ha from field_inventory_block_summary
    op.drop_column('field_inventory_block_summary', 'basal_area_m2_per_ha', schema='public')

    # Remove basal_area_m2 from field_inventory_measurements
    op.drop_column('field_inventory_measurements', 'basal_area_m2', schema='public')
