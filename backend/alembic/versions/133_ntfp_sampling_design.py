"""ntfp_sampling_designs and ntfp_sample_plots: the NTFP sample-plot design of a forest.

Revision ID: 133_ntfp_sampling_design
Revises: 132_ntfp_method_profile
Create Date: 2026-10-22

Phase 2 of the NTFP inventory page. One design per forest (unique calculation_id); both tables cascade on delete, so deleting a forest
deletes its NTFP design (owner's forest-delete rule).
"""
import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision = "133_ntfp_sampling_design"
down_revision = "132_ntfp_method_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ntfp_sampling_designs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("calculation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("plot_shape", sa.String(12), nullable=False, server_default="square"),
        sa.Column("seed", sa.Integer, nullable=False),
        sa.Column("min_plots", sa.Integer, nullable=False),
        sa.Column("species", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("layout", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("strata", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("transects", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ntfp_sample_plots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("design_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ntfp_sampling_designs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plot_number", sa.Integer, nullable=False),
        sa.Column("stratum", sa.String(255), nullable=False),
        sa.Column("transect", sa.Integer, nullable=False),
        sa.Column("location", Geometry("POINT", srid=4326, spatial_index=False), nullable=False),
        sa.Column("species_keys", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("design_id", "plot_number", name="uq_ntfp_plot_number"),
    )
    op.create_index("ix_ntfp_sample_plots_design_id", "ntfp_sample_plots", ["design_id"])
    op.create_index("ix_ntfp_sample_plots_location", "ntfp_sample_plots", ["location"], postgresql_using="gist")


def downgrade() -> None:
    op.drop_table("ntfp_sample_plots")
    op.drop_table("ntfp_sampling_designs")
