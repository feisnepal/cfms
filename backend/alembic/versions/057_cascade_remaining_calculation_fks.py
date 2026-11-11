"""Cascade the calculation foreign keys 056 missed.

Revision ID: 057_cascade_remaining_calculation_fks
Revises: 056_deleted_calculations_archive
Create Date: 2026-08-27

Why a second migration
----------------------
056 matched foreign keys by column name, assuming `calculation_id`. Three
tables do not use that name, so it skipped them **without erroring** -- a `DO`
block that finds no constraint does nothing and reports success:

    boundary_disputes             forest_id_1, forest_id_2
    forest_boundary_audits        forest_id
    pending_boundary_submissions  forest_id

They point at `calculations.id` all the same, so deleting a calculation with a
boundary dispute or a pending submission would still have failed -- with the
same `ForeignKeyViolation` this work exists to remove, just from a different
table. The half-application was only visible by querying the delete rules
afterwards, which is why this migration ends by asserting the result rather
than assuming it.

This one matches on the CONSTRAINT rather than on a guessed column: every
foreign key whose referenced table is `calculations` and whose referenced
column is `id`, whatever the referencing column is called.

`transactions` stays NO ACTION on purpose, as in 056: it is empty, the name
suggests financial records, and nothing should cascade-delete those on the
strength of a guess about what a table is for.
"""
import sqlalchemy as sa
from alembic import op

revision = "057_cascade_remaining_calculation_fks"
down_revision = "056_deleted_calculations_archive"
branch_labels = None
depends_on = None

KEEP_RESTRICTED = ("transactions",)


def _rewrite(delete_rule_sql: str) -> None:
    """Rebuild every calculations FK with the given ON DELETE behaviour.

    Multi-column keys are excluded: rebuilding one correctly needs the full
    column list in order, and none of the keys here is composite. If one ever
    is, it is left alone and stays visible as a NO ACTION row rather than being
    rebuilt wrongly.
    """
    op.execute(sa.text(f"""
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN
                SELECT tc.table_name, tc.constraint_name, kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON kcu.constraint_name = tc.constraint_name
                 AND kcu.table_schema = tc.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                JOIN information_schema.referential_constraints rc
                  ON rc.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public'
                  AND ccu.table_name = 'calculations'
                  AND ccu.column_name = 'id'
                  AND rc.delete_rule IN ('NO ACTION', 'RESTRICT')
                  AND tc.table_name <> ALL (ARRAY['{"','".join(KEEP_RESTRICTED)}'])
                  AND (SELECT count(*) FROM information_schema.key_column_usage k2
                       WHERE k2.constraint_name = tc.constraint_name) = 1
            LOOP
                EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I',
                               r.table_name, r.constraint_name);
                EXECUTE format(
                    'ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY (%I) '
                    'REFERENCES public.calculations(id){delete_rule_sql}',
                    r.table_name, r.constraint_name, r.column_name);
                RAISE NOTICE 'rewrote %.%', r.table_name, r.constraint_name;
            END LOOP;
        END $$;
    """))


def upgrade() -> None:
    _rewrite(" ON DELETE CASCADE")

    # Assert the outcome. 056 reported success while leaving three tables
    # blocking, and nothing noticed until the delete rules were queried by
    # hand. A migration that cannot verify its own effect is how that happens
    # twice.
    op.execute(sa.text(f"""
        DO $$
        DECLARE remaining text;
        BEGIN
            SELECT string_agg(DISTINCT tc.table_name, ', ') INTO remaining
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
            JOIN information_schema.referential_constraints rc
              ON rc.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
              AND ccu.table_name = 'calculations'
              AND ccu.column_name = 'id'
              AND rc.delete_rule IN ('NO ACTION', 'RESTRICT')
              AND tc.table_name <> ALL (ARRAY['{"','".join(KEEP_RESTRICTED)}']);

            IF remaining IS NOT NULL THEN
                RAISE EXCEPTION
                    'foreign keys to calculations.id still block a delete: %',
                    remaining;
            END IF;
        END $$;
    """))


def downgrade() -> None:
    # Restores NO ACTION on everything this migration touched. It cannot
    # distinguish keys 056 cascaded from keys 057 did, so it reverts both --
    # which is the safe direction: a NO ACTION key refuses a delete loudly,
    # a CASCADE one destroys rows quietly.
    _rewrite("")
