"""Add calculation_progress table + cost_estimate to calculations

Adds:
- calculation_progress table (per-step progress tracking)
- cost_estimate JSONB column on public.calculations

Revision ID: 040_calculation_progress_and_cost
Revises: 039_map_lifecycle_state_machine, 038_map_design_ui_revamp, 4c5dc19e96e5
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "040_calculation_progress_and_cost"
down_revision = ("039_map_lifecycle_state_machine", "038_map_design_ui_revamp", "4c5dc19e96e5")
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "calculation_progress",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("calculation_id", UUID(as_uuid=True), sa.ForeignKey("public.calculations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("current_step", sa.String(50), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("step_label", sa.String(255), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_steps", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("percent", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("detail", JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="public",
    )

    op.add_column("calculations", sa.Column("cost_estimate", JSONB(), nullable=True, comment="Resource cost breakdown: {cpu_seconds, peak_memory_mb, cpu_cost, memory_cost, total_cost, currency}"), schema="public")


def downgrade():
    op.drop_column("calculations", "cost_estimate", schema="public")
    op.drop_table("calculation_progress", schema="public")
