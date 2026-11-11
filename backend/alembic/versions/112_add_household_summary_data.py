"""Household summary (totals only) for forests without household-wise data.

Revision ID: 112_add_household_summary_data
Revises: 111_add_fieldbook_lines
Create Date: 2026-10-05

One row per calculation, ON DELETE CASCADE (deleting a forest deletes everything). Additive.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "112_add_household_summary_data"
down_revision = "111_add_fieldbook_lines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "household_summary_data",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("calculation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("public.calculations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("total_households", sa.Integer(), nullable=False),
        sa.Column("male_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("female_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("forest_occupation_households", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("other_occupation_households", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cow_ox_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buffalo_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("goat_sheep_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_land_area", sa.Numeric(10, 4), nullable=True),
        sa.Column("land_unit", sa.String(20), nullable=True),
        sa.Column("timber_demand_cft", sa.Numeric(12, 2), nullable=True),
        sa.Column("pole_demand", sa.Integer(), nullable=True),
        sa.Column("firewood_demand_bhari", sa.Numeric(12, 2), nullable=True),
        sa.Column("grass_demand_bhari", sa.Numeric(12, 2), nullable=True),
        sa.Column("bedding_demand_bhari", sa.Numeric(12, 2), nullable=True),
        sa.Column("demands_auto_calculated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("caste_distribution", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("prosperity_distribution", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("public.users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("calculation_id", name="uq_household_summary_calculation"),
        schema="public",
    )


def downgrade() -> None:
    op.drop_table("household_summary_data", schema="public")
