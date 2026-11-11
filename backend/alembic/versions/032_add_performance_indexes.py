"""Add performance indexes on frequently queried columns

Revision ID: 032_add_performance_indexes
Revises: 031_add_template_categories_table
Create Date: 2026-07-18

"""
from alembic import op

revision = "032_add_performance_indexes"
down_revision = "031_add_template_categories_table"


def upgrade() -> None:
    # Calculations — filtered in every endpoint
    op.create_index("idx_calculations_user_id", "calculations", ["user_id"])
    op.create_index("idx_calculations_status", "calculations", ["status"])
    op.create_index("idx_calculations_created_at", "calculations", ["created_at"])

    # Inventory trees — FK + class filtering
    op.create_index("idx_inventory_trees_calc_id", "inventory_trees", ["inventory_calculation_id"])
    op.create_index("idx_inventory_trees_class", "inventory_trees", ["tree_class"])

    # Other frequently filtered FK columns
    op.create_index("idx_fieldbook_calc_id", "fieldbook", ["calculation_id"])
    op.create_index("idx_sampling_designs_calc_id", "sampling_designs", ["calculation_id"])
    op.create_index("idx_forest_blocks_calc_id", "forest_blocks", ["calculation_id"])
    # H1.4 / S1-12: two index creations removed here.
    #
    #   idx_field_inventory_calc_id on field_inventory_measurements(calculation_id)
    #       — that table has no calculation_id. It reaches a calculation through
    #         sample_plot_id -> field_inventory_sample_plots.field_inventory_calculation_id.
    #   idx_biodiversity_calc_id on biodiversity_observations(calculation_id)
    #       — that table does not exist in this schema at all.
    #
    # Live cf_db confirms both are absent while the five above are present, so
    # this migration has only ever run partially. Neither statement can succeed,
    # so they are removed rather than repaired: adding a corrected index would
    # create something production does not have, and the goal of the from-empty
    # build is to reproduce production exactly.


def downgrade() -> None:
    # The two indexes these lines dropped are no longer created — see upgrade().
    op.drop_index("idx_forest_blocks_calc_id", "forest_blocks")
    op.drop_index("idx_sampling_designs_calc_id", "sampling_designs")
    op.drop_index("idx_fieldbook_calc_id", "fieldbook")
    op.drop_index("idx_inventory_trees_class", "inventory_trees")
    op.drop_index("idx_inventory_trees_calc_id", "inventory_trees")
    op.drop_index("idx_calculations_created_at", "calculations")
    op.drop_index("idx_calculations_status", "calculations")
    op.drop_index("idx_calculations_user_id", "calculations")
