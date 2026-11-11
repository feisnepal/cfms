"""ntfp_harvest_plan: the owner's annual harvest of each NTFP species and part (NTFP inventory, phase 5b).

Revision ID: 137_ntfp_harvest_plan
Revises: 136_ntfp_observations
Create Date: 2026-10-22

The guideline gives no harvest rule, so the annual quantity is typed by the owner (the page offers a share-of-stock helper). It is what the cost-benefit
benefit rows and the yearly-plan collection line are built from. The weight basis (fresh or dry) is explicit per row. Cascades with the forest.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "137_ntfp_harvest_plan"
down_revision = "136_ntfp_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ntfp_harvest_plan",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("calculation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("species_key", sa.String(120), nullable=False),
        sa.Column("part_group", sa.String(2), nullable=False),
        sa.Column("annual_quantity", sa.Numeric(14, 2), nullable=False),
        sa.Column("unit", sa.String(10), nullable=False, server_default="kg"),
        sa.Column("weight_basis", sa.String(5), nullable=False, server_default="dry"),
        sa.Column("price_override", sa.Numeric(12, 2), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("calculation_id", "species_key", "part_group", name="uq_ntfp_harvest_plan"),
        sa.CheckConstraint("annual_quantity >= 0", name="ck_ntfp_harvest_quantity"),
        sa.CheckConstraint("unit IN ('kg','piece')", name="ck_ntfp_harvest_unit"),
        sa.CheckConstraint("weight_basis IN ('fresh','dry')", name="ck_ntfp_harvest_basis"),
        sa.CheckConstraint("price_override IS NULL OR price_override >= 0", name="ck_ntfp_harvest_price"),
    )
    op.create_index("ix_ntfp_harvest_plan_calculation_id", "ntfp_harvest_plan", ["calculation_id"])


def downgrade() -> None:
    op.drop_table("ntfp_harvest_plan")
