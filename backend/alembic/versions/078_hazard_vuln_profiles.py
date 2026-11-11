"""Create hazard_vuln_profiles — org-wide landslide-hazard + household-vuln presets.

Revision ID: 078_hazard_vuln_profiles
Revises: 077_soil_erosion_profiles
Create Date: 2026-09-08

HOUSEHOLD_VULNERABILITY_ANALYSIS_PLAN.md §0.1 / §2 P8.

The middle layer of the 3-tier hazard/vulnerability parameter model
(code default ▸ **global profile** ▸ per-forest override). A super-admin keeps a
small set of physiography presets; a forest with no per-forest override and a
matching dominant physiography zone (``admin.physiography``) auto-picks one
(``hazard_vuln_config._load_global_profile``).

Five rows are seeded with **empty** ``params`` (a no-op — resolves to the code
defaults) so the picker has options; the super-admin fills the coefficients via
``PUT /admin/hazard-vuln-profiles/{key}``. Same shape and seed set as
``soil_erosion_profiles`` (migration 077).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "078_hazard_vuln_profiles"
down_revision = "077_soil_erosion_profiles"
branch_labels = None
depends_on = None

# (key, label_ne, label_en, physiography_hint, sort_order)
# physiography_hint matches admin.physiography."physiography Zone" verbatim.
_SEED = [
    ("terai", "तराई / मधेश", "Terai / Madhesh", "Terai or Madhesh", 10),
    ("bhabar", "भाबर", "Bhabar", "Bhawar", 20),
    ("chure", "चुरे पहाड", "Chure Hills", "Chure Hillslopes", 30),
    ("mid_hill", "मध्य पहाड", "Mid-Hills", "Middle Mountain", 40),
    ("high_mountain", "उच्च पहाड", "High Mountains", "High Mountain", 50),
]


def upgrade() -> None:
    op.create_table(
        "hazard_vuln_profiles",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("label_ne", sa.String(120), nullable=False),
        sa.Column("label_en", sa.String(120), nullable=False),
        sa.Column("physiography_hint", sa.String(60), nullable=True),
        sa.Column(
            "params",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
    )
    op.create_index(
        "ix_hazard_vuln_profiles_hint",
        "hazard_vuln_profiles",
        ["physiography_hint"],
    )

    ins = sa.text(
        "INSERT INTO hazard_vuln_profiles "
        "(key, label_ne, label_en, physiography_hint, sort_order) "
        "VALUES (:key, :ne, :en, :hint, :sort)"
    )
    bind = op.get_bind()
    for key, ne, en, hint, sort in _SEED:
        bind.execute(ins, dict(key=key, ne=ne, en=en, hint=hint, sort=sort))


def downgrade() -> None:
    op.drop_index("ix_hazard_vuln_profiles_hint", "hazard_vuln_profiles")
    op.drop_table("hazard_vuln_profiles")
