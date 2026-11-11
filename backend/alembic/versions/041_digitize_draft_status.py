"""Add digitize draft_status + last_validation_error columns

Revision ID: 041_digitize_draft_status
Revises: 039_workspace_layouts
Create Date: 2026-08-01

Adds the draft lifecycle columns for on-screen digitizing (Gap 1.1 / Task 1.4.1):

- draft_status: None=legacy import, else active/syncing/validation_failed/finalized/discarded
- last_validation_error: JSON {rule, message, feature_id} when validation_failed

Backfill: existing import rows keep is_draft as-is and get draft_status='finalized'
when is_draft=False, 'active' when is_draft=True. Reversible via downgrade().
"""
from alembic import op
import sqlalchemy as sa

revision = "041_digitize_draft_status"
down_revision = "039_workspace_layouts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_layers",
        sa.Column("draft_status", sa.String(20), nullable=True),
    )
    op.add_column(
        "workspace_layers",
        sa.Column("last_validation_error", sa.JSON(), nullable=True),
    )
    # Backfill: finalized = old is_draft=False, active = old is_draft=True
    op.execute(
        "UPDATE workspace_layers SET draft_status = 'finalized' WHERE is_draft = false"
    )
    op.execute(
        "UPDATE workspace_layers SET draft_status = 'active' WHERE is_draft = true"
    )
    op.create_index(
        "idx_workspace_layers_calc_draft_status",
        "workspace_layers",
        ["calculation_id", "draft_status"],
    )


def downgrade() -> None:
    op.drop_index("idx_workspace_layers_calc_draft_status", table_name="workspace_layers")
    op.drop_column("workspace_layers", "last_validation_error")
    op.drop_column("workspace_layers", "draft_status")
