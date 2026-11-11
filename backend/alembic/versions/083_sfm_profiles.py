"""Create sfm_profiles — org-wide Sustainable-Forest-Management parameter presets.

Revision ID: 083_sfm_profiles
Revises: 082_sfm_forest_type_prescriptions
Create Date: 2026-09-10

SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md §3.1 / P0.

The middle layer of the 3-tier SFM parameter model
(code default ▸ **global profile** ▸ per-forest override). A super-admin keeps a
small set of physiography presets; a forest with no per-forest override and a
matching dominant physiography zone (``admin.physiography``) auto-picks one.

Five rows are seeded with **empty** ``params`` (a no-op — resolves to the code
defaults) so the picker has options; the super-admin fills the tuning knobs via
``PUT /admin/sfm-profiles/{key}`` (P7). Exact shape of ``soil_erosion_profiles``
(077) / ``hazard_vuln_profiles`` (078).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "083_sfm_profiles"
down_revision = "082_sfm_forest_type_prescriptions"
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
        "sfm_profiles",
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
        "ix_sfm_profiles_hint",
        "sfm_profiles",
        ["physiography_hint"],
    )

    ins = sa.text(
        "INSERT INTO sfm_profiles "
        "(key, label_ne, label_en, physiography_hint, sort_order) "
        "VALUES (:key, :ne, :en, :hint, :sort)"
    )
    bind = op.get_bind()
    for key, ne, en, hint, sort in _SEED:
        bind.execute(ins, dict(key=key, ne=ne, en=en, hint=hint, sort=sort))


def downgrade() -> None:
    op.drop_index("ix_sfm_profiles_hint", "sfm_profiles")
    op.drop_table("sfm_profiles")
