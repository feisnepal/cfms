"""Create sfm_forest_type_prescriptions and seed the 14 अनुसूची-१ rows.

Revision ID: 082_sfm_forest_type_prescriptions
Revises: 081_rebuild_system_template
Create Date: 2026-09-10

SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md §4 / P0.

The guideline (दिगो वन व्यवस्थापन कार्यविधि, २०७९ अनुसूची-१) as data: one row per
forest type (सि.नं. 1-14) with its classifier triggers, orientation and per-branch
prescription + yield rule. Super-admin editable via
``PUT /admin/sfm-prescriptions/{type_no}`` (P7) — no code change to re-tune.

Like migration 081, this deliberately imports app code: the row data lives in
``scripts/seed_sfm_prescriptions.py`` (importable, re-runnable standalone), and
the seed is the point of the migration.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

revision = "082_sfm_forest_type_prescriptions"
down_revision = "081_rebuild_system_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sfm_forest_type_prescriptions",
        sa.Column("type_no", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name_ne", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200), nullable=False),
        sa.Column(
            "species_groups",
            postgresql.ARRAY(sa.String(32)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column(
            "zone_triggers",
            postgresql.ARRAY(sa.String(32)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column("slope_band", sa.SmallInteger(), nullable=True),
        sa.Column("origin", sa.String(20), nullable=True),
        sa.Column("orientation", sa.String(20), nullable=False),
        sa.Column("branches", postgresql.JSONB(), nullable=False),
        sa.Column("notes_ne", sa.Text(), nullable=True),
        sa.Column("notes_en", sa.Text(), nullable=True),
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

    from scripts.seed_sfm_prescriptions import seed

    seed(Session(bind=op.get_bind()))


def downgrade() -> None:
    op.drop_table("sfm_forest_type_prescriptions")
