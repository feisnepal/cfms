"""Foundations for the yearly-activities planner (YEARLY_ACTIVITIES_WORKSPACE_PLAN P0b).

Revision ID: 091_yearly_plan_foundations
Revises: 090_activity_map_kind
Create Date: 2026-09-20

- ``proposed_yearly_activities.version``      the optimistic-lock counter (plan §5.5).
- ``proposed_yearly_activities.reviewed_at``  set when the user typed or confirmed the numbers; it is
  what makes the "placeholder" flag clearable, and is never set by the system (plan §4.5, §5.1).
- Partial unique indexes, so "get-or-create the plan line" cannot race and make duplicates. A plain
  unique index would not do: NULL block / sub-area values are distinct to PostgreSQL, so one index per
  location level is needed. (The legacy duplicate check compared ``block_id == NULL`` and so never
  matched; nothing stopped a duplicate.)
- ``potential_activities.name_en`` / ``search_terms``: nullable, additive. English name and search
  words so an activity can be found by typing English or romanised Nepali (plan §4.11, D29). Seeded
  later by ``scripts/seed_activity_search_terms.py``; nothing reads them until then.

The live data has no duplicate plan lines, so the indexes apply cleanly; the upgrade still refuses
with a readable message rather than a bare constraint error if that ever stops being true.
"""

import sqlalchemy as sa
from alembic import op

revision = "091_yearly_plan_foundations"
down_revision = "090_activity_map_kind"
branch_labels = None
depends_on = None

INDEXES = (
    (
        "uq_proposed_activity_forest",
        "(calculation_id, potential_activity_id)",
        "block_id IS NULL AND sub_area_id IS NULL",
        "calculation_id, potential_activity_id",
    ),
    (
        "uq_proposed_activity_block",
        "(calculation_id, potential_activity_id, block_id)",
        "block_id IS NOT NULL AND sub_area_id IS NULL",
        "calculation_id, potential_activity_id, block_id",
    ),
    (
        "uq_proposed_activity_sub_area",
        "(calculation_id, potential_activity_id, block_id, sub_area_id)",
        "sub_area_id IS NOT NULL",
        "calculation_id, potential_activity_id, block_id, sub_area_id",
    ),
)


def _refuse_if_duplicates(conn) -> None:
    for name, _cols, where, group_by in INDEXES:
        dupes = conn.execute(
            sa.text(
                f"SELECT count(*) FROM (SELECT 1 FROM proposed_yearly_activities WHERE {where} "  # noqa: S608 -- static
                f"GROUP BY {group_by} HAVING count(*) > 1) d"
            )
        ).scalar()
        if dupes:
            raise RuntimeError(
                f"Cannot create {name}: {dupes} group(s) of duplicate plan lines exist. "
                "Merge or delete the duplicates first (same forest, same activity, same location)."
            )


def upgrade() -> None:
    conn = op.get_bind()
    _refuse_if_duplicates(conn)

    op.add_column(
        "proposed_yearly_activities",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "proposed_yearly_activities",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for name, cols, where, _group in INDEXES:
        op.execute(
            f"CREATE UNIQUE INDEX {name} ON proposed_yearly_activities {cols} WHERE {where}"
        )

    op.add_column(
        "potential_activities", sa.Column("name_en", sa.Text(), nullable=True)
    )
    op.add_column(
        "potential_activities", sa.Column("search_terms", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("potential_activities", "search_terms")
    op.drop_column("potential_activities", "name_en")
    for name, _cols, _where, _group in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.drop_column("proposed_yearly_activities", "reviewed_at")
    op.drop_column("proposed_yearly_activities", "version")
