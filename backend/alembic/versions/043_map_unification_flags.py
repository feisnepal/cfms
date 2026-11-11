"""map & workspace unification flags + optimistic-lock clock

Revision ID: 043_map_unification_flags
Revises: 042_digitize_audit_logs
Create Date: 2026-08-02

Applies the U01/U02/U08/U11/U12 prerequisite columns and the tenant_flags
table (per the Map Unification plan §2 / A.7). downgrade() is the exact
inverse — all columns, the tenant_flags table, and the GiST index are removed.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "043_map_unification_flags"
down_revision = "042_digitize_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Dark-launch flag on each calc (U08 fallback level: user.opt_out > calc.enabled > tenant.default)
    op.add_column(
        "calculations",
        sa.Column("unified_shell_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Optimistic-lock clock (U02/A.5): dedicated column, compare-and-set, atomic (NOT JSONB).
    op.add_column(
        "calculations",
        sa.Column("geometry_version", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    # U12 OP-export lease: idle|queued|running|complete|failed — only 'running' blocks geometry writes.
    op.add_column(
        "calculations",
        sa.Column("export_status", sa.String(20), nullable=False, server_default=sa.text("'idle'")),
    )
    op.add_column("calculations", sa.Column("export_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("calculations", sa.Column("export_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    # U11 draft lifecycle: soft-archive (recycled) before hard purge (24h grace).
    op.add_column("calculations", sa.Column("draft_recycle_state", sa.String(20), nullable=True))
    op.add_column("calculations", sa.Column("recycled_at", sa.DateTime(timezone=True), nullable=True))

    # U08: per-user opt-out (highest precedence), default true = participates.
    op.add_column(
        "users",
        sa.Column("unified_shell_opt_out", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # U08: tenant/global default flag — NULL tenant_id row = the GLOBAL default.
    # A composite PRIMARY KEY (tenant_id, key) can NOT hold a NULL tenant_id
    # (PG forbids NULLs in PK columns), so we use a surrogate id PK + separate
    # uniqueness rules for tenant-scoped vs global rows:
    #   - exactly one row per (tenant_id, key) when tenant_id is NOT NULL
    #   - at most one GLOBAL row per key (partial index on tenant_id IS NULL)
    op.create_table(
        "tenant_flags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="public",
    )
    op.create_index("uq_tenant_flags_tenant_key", "tenant_flags", ["tenant_id", "key"], unique=True, schema="public")
    op.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_flags_global ON tenant_flags (key) WHERE tenant_id IS NULL'
    )
    op.execute(
        "INSERT INTO tenant_flags(tenant_id, key, value) VALUES (NULL, 'unified_shell_default', false)"
        " ON CONFLICT DO NOTHING"
    )

    # U05: speed EPSG:3857 grid bucketing of inventory_trees.location (functional GiST index).
    # Note: `location` is stored as GEOGRAPHY; ST_Transform requires GEOMETRY, so cast it.
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_tree_3857 ON inventory_trees USING gist (st_transform(location::geometry, 3857))'
    )


def downgrade() -> None:
    op.drop_index("idx_tree_3857", table_name="inventory_trees", schema="public")
    op.execute("DROP INDEX IF EXISTS uq_tenant_flags_global")
    op.drop_index("uq_tenant_flags_tenant_key", table_name="tenant_flags", schema="public")
    op.drop_table("tenant_flags", schema="public")
    op.drop_column("users", "unified_shell_opt_out")
    op.drop_column("calculations", "recycled_at")
    op.drop_column("calculations", "draft_recycle_state")
    op.drop_column("calculations", "export_heartbeat_at")
    op.drop_column("calculations", "export_started_at")
    op.drop_column("calculations", "export_status")
    op.drop_column("calculations", "geometry_version")
    op.drop_column("calculations", "unified_shell_enabled")