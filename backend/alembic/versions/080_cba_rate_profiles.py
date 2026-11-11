"""Create cba_rate_profiles — org-wide default depot / market rates for the CBA.

Revision ID: 080_cba_rate_profiles
Revises: 079_cba_models
Create Date: 2026-09-08

CBA_MODULE_PLAN.md P8 / D4.

The middle layer of the CBA rate model:
    code ``FALLBACK_RATES`` ▸ **this org row** ▸ per-scenario ``default_rates``.

D4 keeps it to a **single global row** (``key = 'global'``) for v1 — the table
shape mirrors ``soil_erosion_profiles`` / ``hazard_vuln_profiles`` so it can
grow physiography-keyed rows later without a schema change. ``rates`` is a
sparse ``{timber_sal, timber_mixed, timber_softwood, fuelwood, poles, carbon,
grass, bedding}`` patch; a missing key falls through to ``FALLBACK_RATES``.

Idempotent — guarded so it stamps cleanly onto a DB that already has the table.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "080_cba_rate_profiles"
down_revision = "079_cba_models"
branch_labels = None
depends_on = None


def _has(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has("cba_rate_profiles"):
        op.create_table(
            "cba_rate_profiles",
            sa.Column("key", sa.String(40), primary_key=True),
            sa.Column("label", sa.String(120), nullable=False),
            sa.Column(
                "rates",
                postgresql.JSONB(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.execute(
            "INSERT INTO cba_rate_profiles (key, label, rates) "
            "VALUES ('global', 'Organisation default rates', '{}') "
            "ON CONFLICT (key) DO NOTHING"
        )


def downgrade() -> None:
    op.drop_table("cba_rate_profiles")
