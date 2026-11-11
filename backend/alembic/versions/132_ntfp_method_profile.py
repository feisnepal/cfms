"""ntfp_method_profile: how to inventory each NTFP species (NTFP Resource Survey Guideline 2069, Annex 1 and 2).

Revision ID: 132_ntfp_method_profile
Revises: 131_user_types
Create Date: 2026-10-22

Phase 1 of the NTFP inventory page (owner, 2026-10-22: an optional page in the Advanced band). The table is seeded once from
``app.core.ntfp_methods``; from then on it is the source, like ``ntfp_regulation``.
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "132_ntfp_method_profile"
down_revision = "131_user_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "ntfp_method_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("species_key", sa.String(120), nullable=False, unique=True),
        sa.Column("scientific_name", sa.String(255), nullable=True),
        sa.Column("regulation_name", sa.String(255), nullable=True),
        sa.Column("nepali_name", sa.String(255), nullable=False),
        sa.Column("priority_serial", sa.Integer, nullable=True),
        sa.Column("altitude_min_m", sa.Integer, nullable=True),
        sa.Column("altitude_max_m", sa.Integer, nullable=True),
        sa.Column("parts_used_ne", sa.String(255), nullable=True),
        sa.Column("uses_ne", sa.String(255), nullable=True),
        sa.Column("has_method_card", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("life_form_ne", sa.String(120), nullable=True),
        sa.Column("growth_class", sa.String(12), nullable=True),
        sa.Column("part_ne", sa.String(255), nullable=True),
        sa.Column("part_groups", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("sampling_method", sa.String(20), nullable=True),
        sa.Column("plot_min_sqm", sa.Numeric(8, 2), nullable=True),
        sa.Column("plot_max_sqm", sa.Numeric(8, 2), nullable=True),
        sa.Column("maturity_ne", sa.String(255), nullable=True),
        sa.Column("n_individuals_min", sa.Integer, nullable=True),
        sa.Column("n_individuals_max", sa.Integer, nullable=True),
        sa.Column("harvest_fraction_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("conversion_factor", sa.Numeric(6, 4), nullable=True),
        sa.Column("procedure_en", sa.Text, nullable=True),
        sa.Column("source", sa.String(120), nullable=False, server_default="NTFP Resource Survey Guideline 2069"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("sampling_method IN ('destructive','semi_destructive','non_destructive')", name="ck_ntfp_method_sampling"),
        sa.CheckConstraint("growth_class IN ('tree','shrub','climber','herb','fungus','lichen')", name="ck_ntfp_method_growth"),
    )

    from app.core.ntfp_methods import profiles

    # every row carries every column: bulk_insert takes the column list from the first row, and an Annex-1-only row has no card fields
    cols = [c.name for c in table.columns if c.server_default is None or c.name in ("part_groups", "has_method_card")]  # no aliases yet: 135
    op.bulk_insert(table, [{"id": uuid.uuid4(), **{c: row.get(c) for c in cols if c != "id"}} for row in profiles()])


def downgrade() -> None:
    op.drop_table("ntfp_method_profile")
