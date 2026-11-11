"""Natural-key uniqueness on field measurements and households.

Revision ID: 054_natural_keys
Revises: 053_idempotency_records
Create Date: 2026-08-26

Why this migration exists (H8.6 / S2-67)
----------------------------------------
053 stopped a retried request from being *executed* twice. This stops two rows
that describe the same tree from *existing*, whatever route they arrived by --
the database-level second line the report asks for, which holds even for a
write that never passed through an idempotency key at all.

`field_inventory_measurements` held **25,948 rows across 1,105 sample plots with
`sn` NULL in every one of them**. The column was always the right natural key;
it was simply never populated. The consequence is worse than "no constraint":
543 plot/species/DBH/height groups contain more than one row, and two *Shorea
robusta* at 24 cm and 18 m in the same plot is both completely normal forestry
AND exactly what a duplicated record looks like. With `sn` NULL the two cases
are **indistinguishable**, so nobody can audit this dataset for duplication --
now or retrospectively. That is the finding: not "there are duplicates", but
"duplication here is unmeasurable".

The contrast makes it an oversight rather than a judgement: the parent table
already carries `UNIQUE (field_inventory_calculation_id, block_name,
sample_plot_number)`, and `fieldbook` already carries `UNIQUE (calculation_id,
point_number)`. Measurement level was the one that was missed.

The key is (sample_plot_id, stand_type, sn), NOT (sample_plot_id, sn)
--------------------------------------------------------------------
The report specifies `UNIQUE (sample_plot_id, sn)`. **That would reject valid
field data.** The upload layout carries four independent serial columns --
`regen_sn`, `sapling_sn`, `pole_sn`, `tree_sn` -- and `tree_distribution.py`
numbers each stand type from 1 separately. So Tree #1 and Pole #1 in one plot
is ordinary, and **1,092 of the 1,105 plots carry more than one stand type**.
Constraining on (sample_plot_id, sn) would have failed on the first upload
after deployment, which is the worst moment to discover a key is wrong.

Why `sn` is backfilled and set NOT NULL rather than left nullable
-----------------------------------------------------------------
In PostgreSQL, NULLs are distinct under a UNIQUE constraint. Adding
`UNIQUE (sample_plot_id, stand_type, sn)` while 25,948 rows hold NULL would
have created a constraint that is satisfied by every one of them and enforces
nothing -- a guard that exists, reports healthy, and does not guard. This
repository has found that shape repeatedly (`MAX_UPLOAD_SIZE_MB` enforced
nowhere, `geometry_audits` with 0 rows after five months, four CI gates that
had never executed). NOT NULL is what makes the constraint real.

**What the backfill can and cannot do.** No upload has ever mapped an SN column
-- 0 of 20 `field_inventory_calculations` carry a `*_sn` key in their stored
`column_mapping` -- so there is no source serial to recover. The numbers
assigned here are positional, ordered by `created_at, id` within each
(plot, stand type), and they are **manufactured identity, not recovered
identity**. They make the constraint enforceable from today forward. They do
NOT make historical duplication detectable: if two of these rows are a
duplicated pair from a past sync, they receive consecutive numbers and remain
indistinguishable from two real trees. Per the report's step 2, that is
recorded here explicitly rather than left for someone to assume otherwise.

Data collected from today does better: `app/models/field_inventory.py` assigns
`sn` on insert, and a file that supplies real tag numbers keeps them.

`household_information` needed no cleanup: 298 rows, `house_no` already NOT
NULL, and **0 duplicates on (calculation_id, house_no)** -- verified before
writing this.

Downgrade keeps the backfilled numbers. They are the only tree identity this
data has, and dropping a constraint is not a reason to destroy it; re-running
the upgrade only touches rows still NULL, so it stays idempotent.
"""
import sqlalchemy as sa
from alembic import op

revision = "054_natural_keys"
down_revision = "053_idempotency_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Positional serial within each (plot, stand type). `created_at, id` makes
    # it deterministic: `id` breaks ties on the many rows that share a
    # timestamp, so re-running this on a copy produces the same numbering.
    op.execute(sa.text("""
        WITH numbered AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY sample_plot_id, stand_type
                       ORDER BY created_at, id
                   ) AS seq
            FROM public.field_inventory_measurements
            WHERE sn IS NULL
        )
        UPDATE public.field_inventory_measurements m
        SET sn = numbered.seq
        FROM numbered
        WHERE m.id = numbered.id
    """))

    # A row that already carried an `sn` was left alone above, so a file that
    # supplied real tag numbers could collide with the numbers just assigned.
    # No such file exists in this database, but the constraint below would fail
    # with a bare "duplicate key" if one ever did. Renumber any group that is
    # not internally unique, so the migration cannot half-apply.
    op.execute(sa.text("""
        WITH dupes AS (
            SELECT sample_plot_id, stand_type
            FROM public.field_inventory_measurements
            GROUP BY sample_plot_id, stand_type, sn
            HAVING count(*) > 1
        ),
        renumbered AS (
            SELECT m.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY m.sample_plot_id, m.stand_type
                       ORDER BY m.created_at, m.id
                   ) AS seq
            FROM public.field_inventory_measurements m
            JOIN dupes d
              ON d.sample_plot_id = m.sample_plot_id
             AND d.stand_type = m.stand_type
        )
        UPDATE public.field_inventory_measurements m
        SET sn = renumbered.seq
        FROM renumbered
        WHERE m.id = renumbered.id
    """))

    op.alter_column(
        "field_inventory_measurements", "sn",
        existing_type=sa.Integer(), nullable=False, schema="public",
    )

    # The constraint this whole migration exists for.
    op.create_unique_constraint(
        "uq_measurement_plot_stand_sn", "field_inventory_measurements",
        ["sample_plot_id", "stand_type", "sn"], schema="public",
    )

    # 298 rows, 0 duplicates, `house_no` already NOT NULL — this one is simply
    # the constraint that was never declared.
    op.create_unique_constraint(
        "uq_household_calculation_house_no", "household_information",
        ["calculation_id", "house_no"], schema="public",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_household_calculation_house_no", "household_information",
        type_="unique", schema="public",
    )
    op.drop_constraint(
        "uq_measurement_plot_stand_sn", "field_inventory_measurements",
        type_="unique", schema="public",
    )
    # `sn` goes back to nullable, but the values stay. See the module docstring.
    op.alter_column(
        "field_inventory_measurements", "sn",
        existing_type=sa.Integer(), nullable=True, schema="public",
    )
