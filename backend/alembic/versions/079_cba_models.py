"""Create the Cost-Benefit Analysis tables (cost_benefit_analyses + 3 children).

Revision ID: 079_cba_models
Revises: 078_hazard_vuln_profiles
Create Date: 2026-09-08

CBA_MODULE_PLAN.md P0 / §8.

Rebuilds the July-2026 CBA schema that was lost when the repo was
re-initialised. It folds the two original July revisions into one:

  * 04b3e6cd11c1_add_cba_models              (the four tables)
  * 3d34638bb717_increase_cba_category_length (cba_cost_items.category -> 200)

so ``category`` is declared ``VARCHAR(200)`` from the outset.

**Idempotent.** The four tables already exist in ``cf_db`` (orphaned schema
drift — no migration in the current chain created them). Each ``create_table``
is guarded by ``has_table`` so this revision can be stamped onto a database
that already has them, and creates them cleanly on a fresh one. The July test
data (one "testScene" scenario on बृन्दाबन) is disposable — on ``cf_db`` the
four tables were dropped and this revision run clean.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "079_cba_models"
down_revision = "078_hazard_vuln_profiles"
branch_labels = None
depends_on = None


def _has(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has("cost_benefit_analyses"):
        op.create_table(
            "cost_benefit_analyses",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "calculation_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("calculations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "name",
                sa.String(200),
                nullable=False,
                server_default="Base Scenario",
            ),
            sa.Column("description", sa.Text()),
            sa.Column(
                "discount_rate",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="10.00",
            ),
            sa.Column(
                "time_horizon_years",
                sa.Integer(),
                nullable=False,
                server_default="10",
            ),
            sa.Column(
                "irr_start_year", sa.Integer(), nullable=False, server_default="1"
            ),
            sa.Column("currency", sa.String(3), nullable=False, server_default="NPR"),
            sa.Column(
                "default_rates",
                postgresql.JSONB(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "is_base_scenario",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "created_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id"),
            ),
        )
        op.create_index(
            "ix_cba_calculation", "cost_benefit_analyses", ["calculation_id"]
        )

    if not _has("cba_cost_items"):
        op.create_table(
            "cba_cost_items",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "cba_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("cost_benefit_analyses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("category", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("year_from", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("year_to", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "amount_per_year",
                sa.Numeric(14, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "is_recurring",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("total_amount", sa.Numeric(14, 2)),
            sa.Column("source_link", sa.String(200)),
            sa.Column("notes", sa.Text()),
            sa.Column(
                "display_order", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "year_from >= 1 AND year_to >= year_from",
                name="ck_cost_year_range",
            ),
            sa.CheckConstraint("amount_per_year >= 0", name="ck_cost_amount"),
        )
        op.create_index("ix_cba_cost_items_cba", "cba_cost_items", ["cba_id"])

    if not _has("cba_benefit_items"):
        op.create_table(
            "cba_benefit_items",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "cba_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("cost_benefit_analyses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source", sa.String(50), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("year_from", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("year_to", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("quantity", sa.Numeric(14, 2)),
            sa.Column("unit_price", sa.Numeric(12, 2)),
            sa.Column(
                "amount_per_year",
                sa.Numeric(14, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "is_recurring",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("total_amount", sa.Numeric(14, 2)),
            sa.Column("source_link", sa.String(200)),
            sa.Column("notes", sa.Text()),
            sa.Column(
                "display_order", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "year_from >= 1 AND year_to >= year_from",
                name="ck_benefit_year_range",
            ),
            sa.CheckConstraint("amount_per_year >= 0", name="ck_benefit_amount"),
        )
        op.create_index("ix_cba_benefit_items_cba", "cba_benefit_items", ["cba_id"])

    if not _has("cba_results"):
        op.create_table(
            "cba_results",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "cba_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("cost_benefit_analyses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("npv", sa.Numeric(16, 2)),
            sa.Column("irr", sa.Numeric(8, 4)),
            sa.Column("benefit_cost_ratio", sa.Numeric(10, 4)),
            sa.Column("payback_period_years", sa.Numeric(6, 2)),
            sa.Column("total_cost_pv", sa.Numeric(16, 2)),
            sa.Column("total_benefit_pv", sa.Numeric(16, 2)),
            sa.Column("cash_flow_data", postgresql.JSONB()),
            sa.Column(
                "computed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("cba_id", name="uq_cba_results"),
        )


def downgrade() -> None:
    op.drop_table("cba_results")
    op.drop_table("cba_benefit_items")
    op.drop_table("cba_cost_items")
    op.drop_table("cost_benefit_analyses")
