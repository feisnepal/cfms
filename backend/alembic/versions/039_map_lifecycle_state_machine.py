"""Add map lifecycle state machine columns + audit log table

Adds:
- map_lifecycle_status, map_lifecycle_retries, submitted_at, submitted_by,
  locked_at, locked_by, locked_reason, dfo_decision_at, dfo_decision_by,
  dfo_decision_notes on public.calculations
- calculation_audit_log table (immutable state transition audit)

Revision ID: 039_map_lifecycle_state_machine
Revises: 038_map_design_ui_revamp, 4c5dc19e96e5
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "039_map_lifecycle_state_machine"
down_revision = ("038_map_design_ui_revamp", "4c5dc19e96e5")
branch_labels = None
depends_on = None


def upgrade():
    # Columns on public.calculations
    op.add_column("calculations", sa.Column("map_lifecycle_status", sa.String(20), nullable=False, server_default=sa.text("'draft'"), index=True))
    op.add_column("calculations", sa.Column("map_lifecycle_retries", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("calculations", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("calculations", sa.Column("submitted_by", UUID(as_uuid=True), nullable=True))
    op.add_column("calculations", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("calculations", sa.Column("locked_by", UUID(as_uuid=True), nullable=True))
    op.add_column("calculations", sa.Column("locked_reason", sa.Text(), nullable=True))
    op.add_column("calculations", sa.Column("dfo_decision_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("calculations", sa.Column("dfo_decision_by", UUID(as_uuid=True), nullable=True))
    op.add_column("calculations", sa.Column("dfo_decision_notes", sa.Text(), nullable=True))

    op.create_foreign_key(
        "fk_calc_submitted_by", "calculations", "users",
        ["submitted_by"], ["id"], source_schema="public", referent_schema="public",
    )
    op.create_foreign_key(
        "fk_calc_locked_by", "calculations", "users",
        ["locked_by"], ["id"], source_schema="public", referent_schema="public",
    )
    op.create_foreign_key(
        "fk_calc_dfo_decision_by", "calculations", "users",
        ["dfo_decision_by"], ["id"], source_schema="public", referent_schema="public",
    )

    # Audit log table
    op.create_table(
        "calculation_audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("calculation_id", UUID(as_uuid=True), sa.ForeignKey("public.calculations.id"), nullable=False, index=True),
        sa.Column("from_state", sa.String(20), nullable=False),
        sa.Column("to_state", sa.String(20), nullable=False),
        sa.Column("triggered_by", UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="public",
    )


def downgrade():
    op.drop_table("calculation_audit_log", schema="public")
    op.drop_constraint("fk_calc_submitted_by", "calculations", schema="public")
    op.drop_constraint("fk_calc_locked_by", "calculations", schema="public")
    op.drop_constraint("fk_calc_dfo_decision_by", "calculations", schema="public")
    op.drop_column("calculations", "map_lifecycle_status")
    op.drop_column("calculations", "map_lifecycle_retries")
    op.drop_column("calculations", "submitted_at")
    op.drop_column("calculations", "submitted_by")
    op.drop_column("calculations", "locked_at")
    op.drop_column("calculations", "locked_by")
    op.drop_column("calculations", "locked_reason")
    op.drop_column("calculations", "dfo_decision_at")
    op.drop_column("calculations", "dfo_decision_by")
    op.drop_column("calculations", "dfo_decision_notes")
