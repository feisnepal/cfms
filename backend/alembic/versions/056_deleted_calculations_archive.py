"""Archive deleted calculations; make the blocking foreign keys cascade.

Revision ID: 056_deleted_calculations_archive
Revises: 055_optimistic_lock_versions
Create Date: 2026-08-27

Why this migration exists
-------------------------
Two things, and the order matters.

**1. Deleting a calculation was impossible.** It failed with

    ForeignKeyViolation: update or delete on table "calculations" violates
    foreign key constraint "structure_lock_audits_calculation_id_fkey"

Nine of the 33 foreign keys pointing at `calculations.id` were `NO ACTION`.
`calculation_audit_log` is one of them, and it gets a row from
`log_state_transition` on every submission -- so **any calculation that had
ever been submitted could not be deleted at all**. Fixing only the constraint
named in the error would have moved the failure to the next of the nine.

**2. No permanent delete.** The owner's decision, 2026-08-27: a deleted
calculation is kept "in another table in the intact way, separated from all
other processes, like it is dead". `services/calculation_archive.py` captures
the calculation and every row that references it into one JSONB payload before
the delete runs, in the same transaction.

The cascade is safe **only because of that order**. Archive first, then delete.
If the archive were ever removed or bypassed, these cascades would silently
destroy exactly the data this migration exists to keep -- which is why the
delete endpoint archives unconditionally rather than on a flag.

`transactions` is deliberately left as `NO ACTION`
--------------------------------------------------
The eighth blocking table is named `transactions`. It is empty (0 rows), so it
blocks nothing today, and the name suggests financial or billing records that
should not be cascade-deleted on the strength of a guess about what a table is
for. It stays as it is until somebody establishes what writes it. If it ever
gains rows, deleting such a calculation will fail loudly with a clear FK error
-- which is the right outcome for data nobody has yet justified destroying.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "056_deleted_calculations_archive"
down_revision = "055_optimistic_lock_versions"
branch_labels = None
depends_on = None

# (table, constraint, column) — the NO ACTION foreign keys that block a delete.
# `transactions` is absent on purpose; see the module docstring.
CASCADE_TARGETS = [
    ("activity_drawn_features", "calculation_id"),
    ("boundary_disputes", "calculation_id"),
    ("calculation_audit_log", "calculation_id"),
    ("forest_boundary_audits", "calculation_id"),
    ("geometry_audits", "calculation_id"),
    ("pending_boundary_submissions", "calculation_id"),
    ("structure_lock_audits", "calculation_id"),
]


def upgrade() -> None:
    op.create_table(
        "deleted_calculations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Not a foreign key. The row it points at is gone by design, and a
        # constraint would make this table impossible to write.
        sa.Column("original_calculation_id", postgresql.UUID(as_uuid=True),
                  nullable=False, index=True),
        # Denormalised so a super admin can find "that Rukum forest somebody
        # deleted last year" without grepping a JSONB column.
        sa.Column("forest_name", sa.String(255), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        # The whole thing: the calculation row plus every row that referenced
        # it, geometry rendered as WKT so the payload stays readable.
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("table_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_by_role", sa.String(32), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # H1.14 / S1-74: name the schema. cf_db carries
        # `search_path = rasters, public, sde`, so an unqualified create_table
        # lands in `rasters`.
        schema="public",
    )
    op.create_index("ix_deleted_calculations_deleted_at", "deleted_calculations",
                    ["deleted_at"], schema="public")

    for table, column in CASCADE_TARGETS:
        # The constraint name is read rather than assumed: several of these were
        # created by different migrations over two years and do not all follow
        # the `<table>_<column>_fkey` convention.
        op.execute(sa.text(f"""
            DO $$
            DECLARE con text;
            BEGIN
                SELECT tc.constraint_name INTO con
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                JOIN information_schema.key_column_usage kcu
                  ON kcu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public'
                  AND tc.table_name = '{table}'
                  AND kcu.column_name = '{column}'
                  AND ccu.table_name = 'calculations'
                LIMIT 1;

                IF con IS NOT NULL THEN
                    EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I',
                                   '{table}', con);
                    EXECUTE format(
                        'ALTER TABLE public.%I ADD CONSTRAINT %I '
                        'FOREIGN KEY ("{column}") REFERENCES public.calculations(id) '
                        'ON DELETE CASCADE', '{table}', con);
                END IF;
            END $$;
        """))


def downgrade() -> None:
    for table, column in CASCADE_TARGETS:
        op.execute(sa.text(f"""
            DO $$
            DECLARE con text;
            BEGIN
                SELECT tc.constraint_name INTO con
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                JOIN information_schema.key_column_usage kcu
                  ON kcu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public'
                  AND tc.table_name = '{table}'
                  AND kcu.column_name = '{column}'
                  AND ccu.table_name = 'calculations'
                LIMIT 1;

                IF con IS NOT NULL THEN
                    EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I',
                                   '{table}', con);
                    EXECUTE format(
                        'ALTER TABLE public.%I ADD CONSTRAINT %I '
                        'FOREIGN KEY ("{column}") REFERENCES public.calculations(id)',
                        '{table}', con);
                END IF;
            END $$;
        """))

    op.drop_index("ix_deleted_calculations_deleted_at", table_name="deleted_calculations",
                  schema="public")
    op.drop_table("deleted_calculations", schema="public")
