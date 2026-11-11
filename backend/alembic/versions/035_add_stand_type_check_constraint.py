"""Add CHECK constraints to stand_type columns (B7 fix).

Revision ID: 035_add_stand_type_check_constraint
Revises: 034_add_dbh_class_systems
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa

revision = "035_add_stand_type_check_constraint"
down_revision = "034_add_dbh_class_systems"

# Valid stand_type values matching the guideline_simple system + field_inventory
# 'Regeneration' is used by field_inventory (DBH 0-10 aggregated)
ALLOWED_STAND_TYPES = ("Seedling", "Sapling", "Pole", "Tree", "Regeneration")
CONSTRAINT_NAME_FI = "ck_field_inventory_meas_stand_type"
CONSTRAINT_NAME_IT = "ck_inventory_trees_stand_type"


def upgrade():
    # FieldInventoryMeasurement.stand_type (non-nullable)
    op.create_check_constraint(
        CONSTRAINT_NAME_FI,
        "field_inventory_measurements",
        sa.text(f"stand_type IN {ALLOWED_STAND_TYPES}"),
    )
    # InventoryTree.stand_type (nullable — CHECK allows NULL per SQL standard)
    op.create_check_constraint(
        CONSTRAINT_NAME_IT,
        "inventory_trees",
        sa.text(f"stand_type IS NULL OR stand_type IN {ALLOWED_STAND_TYPES}"),
    )


def downgrade():
    op.drop_constraint(CONSTRAINT_NAME_FI, "field_inventory_measurements")
    op.drop_constraint(CONSTRAINT_NAME_IT, "inventory_trees")
