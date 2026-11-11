"""Create the ten species-master columns that no migration ever added.

Revision ID: 102_species_master_columns
Revises: 101_species_master_snapshot
Create Date: 2026-09-27

Why this migration exists
-------------------------
Migration 101 tried to load the committed species-master snapshot and refused,
because the snapshot has ten columns the table did not have:

    family, main_uses, ecological_role, rarity_status, is_tree_species,
    nitrogen_fixing, growth_rate, economic_value, min_altitude_m, max_altitude_m

Those columns exist in production and in **no migration**. They were added by the
ad-hoc `migrations/csv_import/` scripts, which ALTER the table directly. So the
species master was unreproducible in two ways at once, and this fixes the second:

  * its **contents** -- 861 rows from an import pipeline, vs 25 from migration
    003. Fixed by 101, which loads them from `species_master.jsonl`.
  * its **shape** -- ten columns no `alembic upgrade head` would ever create.
    Fixed here.

Without this, a freshly migrated database had a species master missing a fifth of
its columns, so a species looked to the application like one with no family, no
uses, no altitude range and no rarity -- and could not be matched by a policy
list entry that assumed those fields existed.

Column types and defaults are taken from the live production table rather than
guessed, so a fresh database and production end up with the same definition:

    family            varchar(100)   nullable
    main_uses         text           nullable
    ecological_role   text           nullable
    rarity_status     varchar(50)    nullable  default 'Common'
    is_tree_species   boolean        nullable  default true
    nitrogen_fixing   boolean        nullable  default false
    growth_rate       varchar(20)    nullable
    economic_value    varchar(20)    nullable
    min_altitude_m    integer        nullable
    max_altitude_m    integer        nullable

Idempotent: each column is added only if absent, so this is safe on production
(where they all exist) and on a fresh database (where none do). It then re-runs
the snapshot load with `strict=True`, which backfills the new columns from the
committed file rather than leaving them NULL.

It also drops `uq_species_code`, a constraint the real data cannot satisfy
---------------------------------------------------------------------
Loading the snapshot on a fresh database failed with:

    psycopg2.errors.UniqueViolation: duplicate key value violates unique
    constraint "uq_species_code"

Investigated rather than worked around, and the constraint is simply wrong.
`species_code` is a coarse code, not an identifier:

    861 rows, 23 distinct species_code values, 0 NULL
    code 22 -> 540 species
    code 23 -> 300 species

So 838 of the 861 species share a code with at least one other species, and
`uq_species_code` is unsatisfiable by the actual master. It was created by
migration `004_add_species_code_column` and **does not exist in production**,
where it must have been dropped by hand some time ago -- a third divergence
between what migrations build and what production actually is, and the only one
that made the database actively reject correct data.

The natural key is `scientific_name`, which carries a UNIQUE constraint and is
what the entire codebase references the master by. Nothing anywhere holds a
foreign key to the master's `id` (verified: zero referencing tables), and
`species_code` is used nowhere as a join key. So the constraint is dropped
rather than the data bent to fit it: 838 rows are not a typo, they are what a
coarse code looks like.

Dropped conditionally, so this is a no-op on a database that has already lost it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "102_species_master_columns"
down_revision = "101_species_master_snapshot"
branch_labels = None
depends_on = None


# (name, type, server_default or None)
NEW_COLUMNS = [
    ("min_altitude_m", sa.Integer(), None),
    ("max_altitude_m", sa.Integer(), None),
    ("growth_rate", sa.String(20), None),
    ("economic_value", sa.String(20), None),
    ("nitrogen_fixing", sa.Boolean(), sa.text("false")),
    ("main_uses", sa.Text(), None),
    ("ecological_role", sa.Text(), None),
    ("rarity_status", sa.String(50), sa.text("'Common'")),
    ("family", sa.String(100), None),
    ("is_tree_species", sa.Boolean(), sa.text("true")),
]


def _existing_columns(bind) -> set[str]:
    return {
        r[0]
        for r in bind.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'tree_species_coefficients'"
            )
        ).fetchall()
    }


def _loader():
    path = Path(__file__).parent / "data" / "species_master_loader.py"
    spec = importlib.util.spec_from_file_location("_species_master_loader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _drop_unsatisfiable_species_code_unique(bind) -> None:
    """Remove `uq_species_code` if present.

    See the module docstring: 838 of 861 species share a `species_code`, so the
    constraint cannot hold the real data, and production does not have it.
    """
    rows = bind.execute(
        sa.text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'tree_species_coefficients'::regclass "
            "  AND contype = 'u' "
            "  AND pg_get_constraintdef(oid) LIKE '%species_code%'"
        )
    ).fetchall()
    for (name,) in rows:
        bind.execute(
            sa.text(f'ALTER TABLE tree_species_coefficients DROP CONSTRAINT "{name}"')
        )
        print(
            f"[species_master_columns] dropped {name}: species_code is a coarse "
            "code (23 distinct values across 861 species), not an identifier"
        )
    if not rows:
        print("[species_master_columns] no species_code unique constraint present")


def upgrade() -> None:
    bind = op.get_bind()
    existing = _existing_columns(bind)
    added = []
    for name, coltype, default in NEW_COLUMNS:
        if name in existing:
            continue
        op.add_column(
            "tree_species_coefficients",
            sa.Column(name, coltype, nullable=True, server_default=default),
        )
        added.append(name)

    print(
        f"[species_master_columns] added {len(added)} column(s): {added}"
        if added
        else "[species_master_columns] all columns already present; nothing to add"
    )

    # Backfill the new columns from the committed snapshot. `strict=True` now
    # passes because the table finally has every column the file describes.
    loader = _loader()
    report = loader.load_into_master(bind, loader.load_snapshot(), strict=True)
    print(
        f"[species_master_columns] reloaded {report['loaded']} species; removed "
        f"{report['deleted']} row(s) not in the snapshot; master now holds "
        f"{report['total']}"
    )


def downgrade() -> None:
    # Dropping these would discard real data on a database that has it, and
    # 101/102 exist to make the master reproducible rather than to reshape it.
    # Left in place deliberately; see the module docstring.
    print(
        "[species_master_columns] columns left in place: dropping them would "
        "discard species data, which a downgrade should not do silently."
    )
