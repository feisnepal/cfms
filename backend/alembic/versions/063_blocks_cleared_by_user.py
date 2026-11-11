"""Block lifecycle decoupling: durable "blocks cleared" flag.

Revision ID: 063_blocks_cleared_by_user
Revises: 062_boundary_gap_preview_fields
Create Date: 2026-08-29

Deleting the last remaining block used to be self-healing: the boundary<->
blocks coverage invariant treated "0 blocks left" as a gap and immediately
re-inserted a full-boundary Remainder Block in the same request, so the
forest boundary could never actually reach an unlocked, block-free state.

Going forward, a delete that leaves the top-level `blocks` division at zero
rows is a deliberate "clear structure" action: the remainder auto-fill is
skipped and this flag is set instead, so `persist_boundary`'s single-block
auto-create stays off across every subsequent boundary save until the user
explicitly regenerates a block via `POST .../create-single-block` (which
clears the flag).

Nullable-safe: `server_default=false` backfills every existing row with the
old (auto-block-on) behaviour, so no existing calculation changes behaviour
on migrate.
"""

import sqlalchemy as sa
from alembic import op

revision = "063_blocks_cleared_by_user"
down_revision = "062_boundary_gap_preview_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "calculations",
        sa.Column(
            "blocks_cleared_by_user",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("calculations", "blocks_cleared_by_user", schema="public")
