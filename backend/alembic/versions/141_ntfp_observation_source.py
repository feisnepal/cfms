"""ntfp_plot_observations.source: whether a record came from the uploaded form or was typed in on the map.

Revision ID: 141_ntfp_observation_source
Revises: 140_ntfp_india_sources
Create Date: 2026-10-22

A forest's records are either all uploaded or all entered by hand (owner, 2026-10-22): the source of the stored records decides which way is open.
Every record that exists now came from the upload.
"""
import sqlalchemy as sa
from alembic import op

revision = "141_ntfp_observation_source"
down_revision = "140_ntfp_india_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ntfp_plot_observations", sa.Column("source", sa.String(10), nullable=False, server_default="upload"))
    op.create_check_constraint("ck_ntfp_observation_source", "ntfp_plot_observations", "source IN ('upload','manual')")


def downgrade() -> None:
    op.drop_constraint("ck_ntfp_observation_source", "ntfp_plot_observations", type_="check")
    op.drop_column("ntfp_plot_observations", "source")
