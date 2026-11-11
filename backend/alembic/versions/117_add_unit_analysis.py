"""Per-unit analysis results (Run analysis, every block / compartment / sub-block / sub-compartment).

One row per ``forest_blocks`` unit holding every value the analysis computed for that polygon: ``values`` flattened to ``an_*`` keys
for the attribute table, ``raw`` the full result the Operational Plan reads. Cascades from both the forest and the unit, so deleting either deletes the results.

Revision ID: 117_add_unit_analysis
Revises: 116_add_forest_decisions
Create Date: 2026-10-10
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "117_add_unit_analysis"
down_revision = "116_add_forest_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "unit_analysis",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("calculation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("forest_blocks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("values", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # The analyser's full, unflattened result: what the Operational Plan placeholders read (class breakdowns, lists).
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_unit_analysis_calculation_id", "unit_analysis", ["calculation_id"])
    op.create_index("uq_unit_analysis_block_id", "unit_analysis", ["block_id"], unique=True)


def downgrade() -> None:
    op.drop_table("unit_analysis")
