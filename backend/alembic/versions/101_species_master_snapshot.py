"""Make the species master reproducible: load it from a committed snapshot.

Revision ID: 101_species_master_snapshot
Revises: 100_policy_species_no_local_name
Create Date: 2026-09-27

Why this migration exists
-------------------------
`tree_species_coefficients` is the single source of truth for species, and until
now it had **no reproducible source at all**. Two different datasets claimed to
be it:

  * migration `003_seed_species_data` seeds **25** species, with taxonomy that
    production no longer uses -- it carries `Eugenia Jambolana`, while production
    has `Syzygium cumini` for the same tree.
  * production holds **861** species, loaded by the ad-hoc pipeline under
    `migrations/csv_import/` (six `RUN_SESSION*.bat` scripts). Alembic never
    runs it.

So `alembic upgrade head` produced a database whose species master was wrong,
and every test built on that database inherited the wrong 25. Measured on a
freshly migrated scratch database:

    master rows                     25   (production: 861)
    policy species present          20 of 21  -- `Syzygium cumini` missing
    stale `Eugenia Jambolana`       present
    policy rows with no master row  1 of 21

That last line is why the FOREIGN KEY from `policy_reference_species` to the
master could not be added: it would fail on every freshly migrated database,
including every test run. A constraint that only holds on one hand-fixed
database is not a constraint.

The fix is to make the master *data* live in the repository, the way the schema
does. `alembic/versions/data/species_master.jsonl` holds one JSON object per
species -- 861 lines, one line per species, so a diff of a species correction is
one line rather than a wall. This migration loads it.

The snapshot is taken from the live master, so this does not invent or correct
any species data. It makes the current state *explicit and reviewable*, which is
the point: an SSOT nobody can diff is only nominally a source of truth. Note for
whoever reads the file next: **179 of the 861 rows carry a placeholder
`local_name`** (`nan`, `-`, and similar). They are reproduced faithfully because
silently "fixing" them here would be a data change disguised as a migration.
Fix them in the master, deliberately, with their own migration.

What this migration does, and why each part
------------------------------------------
* **Upsert on `scientific_name`**, which carries a UNIQUE constraint. The master
  is referenced by name throughout the codebase -- nothing anywhere holds a
  foreign key to its `id` (verified: zero referencing tables) -- so the natural
  key is the identity, and re-pointing rows at a corrected snapshot must not
  churn primary keys.
* **Delete master rows absent from the snapshot**, so the master *equals* the
  source of truth rather than being a superset of it. This is what removes
  `Eugenia Jambolana` on a fresh database. On production the snapshot is
  production, so nothing is deleted; the count is printed either way.
* **Idempotent.** Safe to run against a database that already holds the data.

A note on this migration having been edited after it was applied
---------------------------------------------------------------
It ran once against production, where every snapshot column already existed, so
its behaviour there is unchanged. Its first version *raised* when the table was
missing snapshot columns, which turned out to be the normal case on a fresh
database: ten of the master's columns (`family`, `main_uses`, `ecological_role`,
`rarity_status`, `is_tree_species`, `nitrogen_fixing`, `growth_rate`,
`economic_value`, `min_altitude_m`, `max_altitude_m`) are created by **no
migration at all** -- they exist in production only because the ad-hoc import
scripts altered the table. So a fresh database could never get past this
migration.

Rather than leave a migration that crashes on a clean database, it now loads the
columns the table has and reports the rest; migration `102` creates the missing
columns and re-loads with `strict=True`. The alternative -- leaving 101 to crash
-- would mean `alembic upgrade head` cannot build a database at all, which is a
worse outcome than a two-step load.

Migration `003` is left untouched. It has run, and rewriting an applied migration
to erase a mistake would leave a fresh database unable to reproduce what
production executed. 101 supersedes it, the same way 100 superseded 099.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic import op

revision = "101_species_master_snapshot"
down_revision = "100_policy_species_no_local_name"
branch_labels = None
depends_on = None


def _loader():
    """Import the shared loader by path; see that module's docstring."""
    path = Path(__file__).parent / "data" / "species_master_loader.py"
    spec = importlib.util.spec_from_file_location("_species_master_loader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    bind = op.get_bind()
    loader = _loader()

    # Before the load. A UNIQUE constraint on `species_code` -- created by
    # migration 004, absent from production -- makes the snapshot unloadable,
    # because the real master has 861 species across 23 distinct codes. The
    # error it produces reads like a data duplicate, not a stale constraint, so
    # it is worth naming here rather than only in the loader.
    dropped = loader.drop_unsatisfiable_species_code_unique(bind)
    if dropped:
        print(
            f"[species_master_snapshot] dropped {dropped}: species_code is a "
            "coarse code (23 distinct values across 861 species), not an identifier"
        )

    report = loader.load_into_master(bind, loader.load_snapshot(), strict=False)

    msg = (
        f"[species_master_snapshot] loaded {report['loaded']} species; removed "
        f"{report['deleted']} row(s) not in the snapshot; master now holds "
        f"{report['total']}"
    )
    if report["skipped_columns"]:
        msg += (
            f"; {len(report['skipped_columns'])} snapshot column(s) not yet in "
            f"this table and loaded by 102 instead: {report['skipped_columns']}"
        )
    print(msg)


def downgrade() -> None:
    # The snapshot IS the source of truth, so downgrading cannot restore whatever
    # a given database happened to hold before -- that variability is the problem
    # this migration exists to remove. Migration 003's 25-row seed is left in
    # place, so a downgraded database still has a usable master.
    print(
        "[species_master_snapshot] no data to restore: the snapshot is the source "
        "of truth. A downgraded database keeps the 25 species from migration 003."
    )
