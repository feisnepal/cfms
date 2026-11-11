"""NTFP sample plots: the "I am here" check and a photo per plot.

Revision ID: 142_ntfp_plot_presence_photos
Revises: 141_ntfp_observation_source
Create Date: 2026-10-22

``ntfp_sample_plots`` gets the last position check (where the person stood, the GPS accuracy, the distance to the plot, the verdict); ``ntfp_plot_photos`` holds the photos
taken at a plot (the files live under uploads/ntfp_photos/<forest id>/). Both go with the plot, and so with the forest.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "142_ntfp_plot_presence_photos"
down_revision = "141_ntfp_observation_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ntfp_sample_plots", sa.Column("here_latitude", sa.Float, nullable=True))
    op.add_column("ntfp_sample_plots", sa.Column("here_longitude", sa.Float, nullable=True))
    op.add_column("ntfp_sample_plots", sa.Column("here_accuracy_m", sa.Float, nullable=True))
    op.add_column("ntfp_sample_plots", sa.Column("here_distance_m", sa.Float, nullable=True))
    op.add_column("ntfp_sample_plots", sa.Column("here_verdict", sa.String(10), nullable=True))
    op.add_column("ntfp_sample_plots", sa.Column("here_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_ntfp_plot_here_verdict", "ntfp_sample_plots", "here_verdict IS NULL OR here_verdict IN ('at','far','uncertain')")
    op.create_table(
        "ntfp_plot_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("plot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ntfp_sample_plots.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("file_name", sa.String(255), nullable=False),          # what the camera called it: shown, never used as a path
        sa.Column("stored_name", sa.String(80), nullable=False),         # what it is called on disk
        sa.Column("content_type", sa.String(40), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("caption", sa.String(300), nullable=True),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("ntfp_plot_photos")
    op.drop_constraint("ck_ntfp_plot_here_verdict", "ntfp_sample_plots", type_="check")
    for c in ("here_at", "here_verdict", "here_distance_m", "here_accuracy_m", "here_longitude", "here_latitude"):
        op.drop_column("ntfp_sample_plots", c)
