"""ntfp_plot_observations and ntfp_weight_samples: what the field team records in the NTFP sample plots.

Revision ID: 136_ntfp_observations
Revises: 135_ntfp_profile_canonical_names
Create Date: 2026-10-22

Phase 3 of the NTFP inventory page. Both tables cascade on delete (plot -> observation -> weights, and the forest -> design -> plots before them), so
deleting a forest deletes its records. The design API refuses to replace or delete a design that still has records.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "136_ntfp_observations"
down_revision = "135_ntfp_profile_canonical_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ntfp_plot_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("plot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ntfp_sample_plots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("species_key", sa.String(120), nullable=False),
        sa.Column("visit_date", sa.Date, nullable=True),
        sa.Column("count_total", sa.Integer, nullable=False),
        sa.Column("count_mature", sa.Integer, nullable=True),
        sa.Column("count_small", sa.Integer, nullable=True),
        sa.Column("clumps", sa.Integer, nullable=True),
        sa.Column("tillers", sa.Integer, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("entered_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("plot_id", "species_key", name="uq_ntfp_observation"),
        sa.CheckConstraint(
            "count_total >= 0 AND (count_mature IS NULL OR count_mature >= 0) AND (count_small IS NULL OR count_small >= 0) "
            "AND (clumps IS NULL OR clumps >= 0) AND (tillers IS NULL OR tillers >= 0)", name="ck_ntfp_observation_counts"),
    )
    op.create_index("ix_ntfp_plot_observations_plot_id", "ntfp_plot_observations", ["plot_id"])
    op.create_table(
        "ntfp_weight_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ntfp_plot_observations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sample_no", sa.Integer, nullable=False),
        sa.Column("part_group", sa.String(2), nullable=True),
        sa.Column("fresh_weight_g", sa.Numeric(12, 2), nullable=False),
        sa.Column("dry_weight_g", sa.Numeric(12, 2), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("observation_id", "sample_no", name="uq_ntfp_weight_sample"),
        sa.CheckConstraint("fresh_weight_g > 0 AND (dry_weight_g IS NULL OR (dry_weight_g >= 0 AND dry_weight_g <= fresh_weight_g))", name="ck_ntfp_weight"),
    )
    op.create_index("ix_ntfp_weight_samples_observation_id", "ntfp_weight_samples", ["observation_id"])


def downgrade() -> None:
    op.drop_table("ntfp_weight_samples")
    op.drop_table("ntfp_plot_observations")
