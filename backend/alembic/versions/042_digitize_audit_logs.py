"""Add digitize_audit_logs table

Revision ID: 042_digitize_audit_logs
Revises: 041_digitize_draft_status
Create Date: 2026-08-01

Adds the forestry-compliance audit trail for on-screen digitizing (Gap 6.1 /
Task 1.4.4): one row per flush (add_feature), plus finalize and discard.
Fully reversible via downgrade().
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "042_digitize_audit_logs"
down_revision = "041_digitize_draft_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "digitize_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("calculation_id", UUID(as_uuid=True), sa.ForeignKey("public.calculations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("layer_id", sa.Integer(), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("feature_count_delta", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("geometry_hash", sa.String(64), nullable=True),
        sa.Column("details", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_digitize_audit_layer", "digitize_audit_logs", ["layer_id", "created_at"])
    op.create_index("idx_digitize_audit_calc", "digitize_audit_logs", ["calculation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_digitize_audit_calc", table_name="digitize_audit_logs")
    op.drop_index("idx_digitize_audit_layer", table_name="digitize_audit_logs")
    op.drop_table("digitize_audit_logs")
