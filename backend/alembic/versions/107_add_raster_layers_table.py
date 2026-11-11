"""Add `raster_layers` table + `forest_blocks.raster_layer_id` (RASTER_SOURCES P2.5, RS-2.16).

Revision ID: 107_add_raster_layers_table
Revises: 106_add_nasa_raw_dominant_code
Create Date: 2026-09-30

Schema-only step for D51 (independent Auto-Block layers). Today every Auto-Block
source overwrites the same `forest_blocks` rows for a calculation, and
`commit_blocks` refuses forest-wide once any row exists. The owner's model
(RASTER_SOURCES_TRACKER.md, "P2.5") instead has every source create its own
self-contained layer; exactly one layer per forest is later *promoted* to
become the calculation's authoritative blocks/compartments stream.

`raster_layers` is one row per layer: which source carved it, whether it has
been promoted, and if so as which level (blocks/compartments — matches the
existing `commit_blocks(level=...)` vocabulary, not a new one). Deliberately
NOT a self-describing "is this the real structure" flag alone — `promoted_as`
being non-NULL *is* that flag, so there is exactly one thing to check, not two
that could disagree.

`forest_blocks.raster_layer_id` is nullable and ON DELETE CASCADE: a block
belongs to at most one layer, and deleting a layer (e.g. an abandoned
unpromoted trial) takes its rows with it. NULL means "created before this
migration, or via a path this phase has not wired yet (manual draw, import,
divide/cut/merge on legacy data)" — those rows are left exactly as they are;
the promotion-and-filtering behaviour that makes `raster_layer_id`/
`promoted_as` load-bearing is RS-2.17/RS-2.18, not this row. Additive and
nullable throughout, so this migration changes nothing about how any existing
query behaves.

One promoted layer per calculation is enforced with a partial unique index
rather than a DB CHECK (Postgres CHECK constraints cannot do cross-row
aggregates) — `commit_blocks`/the promote endpoint must still handle the
resulting `UniqueViolation` and turn it into the same "already have blocks,
switch first" answer RS-2.16's gate describes, in code, not relying on the
index to produce a friendly error by itself.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "107_add_raster_layers_table"
down_revision = "106_add_nasa_raw_dominant_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raster_layers",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "calculation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("calculations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Same vocabulary as `PREVIEW_FN_BY_SOURCE` in auto_block_service.py
        # (e.g. "mmu", "slope", "aspect", "canopy", "nasa_quality", later
        # "forest_health" / "esa_landcover"). Not an FK to a lookup table —
        # that registry is the single source of truth, per D33/RS-0.3.
        sa.Column("source", sa.String(50), nullable=False),
        # Display name, e.g. "slope-1(19-31)"-style layer label. Distinct from
        # each block's own `block_name`/`name` — this is the LAYER's name.
        sa.Column("name", sa.String(255), nullable=False),
        # NULL = not promoted (a non-counting overlay). "blocks"/"compartments"
        # once promoted — same two values `commit_blocks(level=...)` already
        # takes, so promotion doesn't invent a second vocabulary.
        sa.Column("promoted_as", sa.String(20), nullable=True),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "promoted_as IS NULL OR promoted_as IN ('blocks', 'compartments')",
            name="ck_raster_layers_promoted_as",
        ),
        schema="public",
    )
    op.create_index(
        "idx_raster_layers_calculation_id", "raster_layers", ["calculation_id"], schema="public",
    )
    # Exactly one promoted layer per calculation (D51's "one stream per
    # forest"). A partial unique index, since most rows have promoted_as NULL
    # and must not collide with each other.
    op.create_index(
        "uq_raster_layers_one_promoted_per_calc",
        "raster_layers",
        ["calculation_id"],
        unique=True,
        postgresql_where=sa.text("promoted_as IS NOT NULL"),
        schema="public",
    )

    op.add_column(
        "forest_blocks",
        sa.Column(
            "raster_layer_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("raster_layers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        schema="public",
    )
    op.create_index(
        "idx_forest_blocks_raster_layer_id", "forest_blocks", ["raster_layer_id"], schema="public",
    )


def downgrade() -> None:
    op.drop_index("idx_forest_blocks_raster_layer_id", table_name="forest_blocks", schema="public")
    op.drop_column("forest_blocks", "raster_layer_id", schema="public")
    op.drop_index("uq_raster_layers_one_promoted_per_calc", table_name="raster_layers", schema="public")
    op.drop_index("idx_raster_layers_calculation_id", table_name="raster_layers", schema="public")
    op.drop_table("raster_layers", schema="public")
