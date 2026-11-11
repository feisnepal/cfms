"""Create soil_erosion_profiles — org-wide RUSLE parameter presets.

Revision ID: 077_soil_erosion_profiles
Revises: 076_add_is_felling_to_potential_activities
Create Date: 2026-09-07

RUSLE_SOIL_LOSS_IMPLEMENTATION_PLAN.md §0.1 / §2 P7.

The middle layer of the 3-tier soil-erosion parameter model
(code default ▸ **global profile** ▸ per-forest override). A super-admin keeps
a small set of physiography presets; a forest with no per-forest override and a
matching dominant physiography zone (``admin.physiography``) auto-picks one.

Four rows are seeded with **empty** ``params`` (a no-op — resolves to the code
defaults) so the picker has options; the super-admin fills the coefficients via
``PUT /admin/soil-erosion-profiles/{key}``. No code change needed for that,
exactly like ``op_plan_kinds`` (migration 067) and its D2b lists.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "077_soil_erosion_profiles"
down_revision = "076_add_is_felling_to_potential_activities"
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
        "soil_erosion_profiles",
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
        "ix_soil_erosion_profiles_hint",
        "soil_erosion_profiles",
        ["physiography_hint"],
    )

    ins = sa.text(
        "INSERT INTO soil_erosion_profiles "
        "(key, label_ne, label_en, physiography_hint, sort_order) "
        "VALUES (:key, :ne, :en, :hint, :sort)"
    )
    bind = op.get_bind()
    for key, ne, en, hint, sort in _SEED:
        bind.execute(ins, dict(key=key, ne=ne, en=en, hint=hint, sort=sort))


def downgrade() -> None:
    op.drop_index("ix_soil_erosion_profiles_hint", "soil_erosion_profiles")
    op.drop_table("soil_erosion_profiles")
