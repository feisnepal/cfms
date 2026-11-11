"""Add building size category columns to user_group_buildings.

Revision ID: 064_add_user_group_building_size_categories
Revises: 063_blocks_cleared_by_user
Create Date: 2026-08-31

The UserGroupBuilding model gains per-size-class building counts and an
average building footprint. The original migration (011) that defined these
columns lives on an orphaned migration branch and was never applied to
production/staging, so the OP DOCX export (which resolves ug_small_buildings
etc. via data_collector.get_user_group_data) crashed with UndefinedColumn.
Backfill with server_default=0 so existing rows are populated and the query
never sees NULL.
"""

import sqlalchemy as sa
from alembic import op

revision = "064_add_user_group_building_size_categories"
down_revision = "063_blocks_cleared_by_user"
branch_labels = None
depends_on = None


def _existing_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        col["name"]
        for col in inspector.get_columns("user_group_buildings", schema="public")
    }


def _add_if_missing(table: str, column: sa.Column, schema: str) -> None:
    if column.name not in _existing_columns():
        op.add_column(table, column, schema=schema)


def upgrade() -> None:
    # 011 lives on an orphaned/merged branch that from-scratch `upgrade head`
    # still walks, so these four columns may already exist by the time this
    # migration runs. Guard each add_column so a clean schema build cannot
    # collide ("column ... already exists"), while incremental upgrades on a
    # DB that never had 011 still backfill them.
    _add_if_missing(
        "user_group_buildings",
        sa.Column("small_buildings", sa.Integer(), nullable=True, server_default="0"),
        "public",
    )
    _add_if_missing(
        "user_group_buildings",
        sa.Column("medium_buildings", sa.Integer(), nullable=True, server_default="0"),
        "public",
    )
    _add_if_missing(
        "user_group_buildings",
        sa.Column("large_buildings", sa.Integer(), nullable=True, server_default="0"),
        "public",
    )
    _add_if_missing(
        "user_group_buildings",
        sa.Column("average_building_size_m2", sa.Numeric(12, 2), nullable=True),
        "public",
    )


def downgrade() -> None:
    op.drop_column("user_group_buildings", "average_building_size_m2", schema="public")
    op.drop_column("user_group_buildings", "large_buildings", schema="public")
    op.drop_column("user_group_buildings", "medium_buildings", schema="public")
    op.drop_column("user_group_buildings", "small_buildings", schema="public")
