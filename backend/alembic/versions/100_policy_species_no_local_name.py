"""Drop the duplicated local_name from policy_reference_species.

Revision ID: 100_policy_species_no_local_name
Revises: 099_policy_reference_species
Create Date: 2026-09-27

Why this migration exists
-------------------------
Migration 099 created `policy_reference_species` with a `local_name` column,
seeded by copying the value out of `tree_species_coefficients`. The reasoning
was that it was a harmless denormalised convenience for display.

It was not harmless. `tree_species_coefficients` is the species single source of
truth -- 32 columns covering names, coefficients, wood density, genus, family,
aliases and ecology, with a UNIQUE constraint on `scientific_name`. Copying one
of its columns into a policy overlay table created a *second persisted copy* of
SSOT data, which is the thing an SSOT exists to prevent:

  * It could drift, and there was no mechanism preventing it. 16 of the 21 copies
    already disagreed with their source at seed time -- not because the copy was
    wrong, but because the two were written independently.
  * The only defence was a test asserting the copy agreed with the master, which
    detects the symptom after the fact rather than removing the cause. A test
    that polices a duplicate is a confession that the duplicate should not exist.
  * A correction to a local name in the master would reach every other reader of
    the master and would *not* reach this table, so the policy report would keep
    printing the old name while everything else printed the new one.

So the column is dropped. The policy table now says only *which species are on
the list* -- `scientific_name`, `match_level`, `display_order`, `is_active` --
and every species attribute is read from the master.
`PolicySpeciesRegistry` resolves local names by joining the master on
`scientific_name`, which is safe because the master has a UNIQUE constraint on
that column.

`scientific_name` stays, and that is not a duplicate: it is the *key* by which
the list names a species, not a copy of the master's data. An actual FOREIGN KEY
would be the strongest form of that, and the master is unique enough to support
one -- but it cannot be added yet. A test database built by `alembic upgrade head`
carries a different, smaller species master (from `003_seed_species_data`, which
has no `Syzygium cumini`), so a FK would fail the migration on a clean test
database. Aligning the test master with production is the prerequisite, and is
recorded in POLICY_SPECIES_TRACKER as open work rather than done silently here.

Downgrade restores the column and re-copies from the master, so the old shape is
still reachable.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "100_policy_species_no_local_name"
down_revision = "099_policy_reference_species"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("policy_reference_species", "local_name")


def downgrade() -> None:
    op.add_column(
        "policy_reference_species",
        sa.Column("local_name", sa.String(150), nullable=True),
    )
    # Re-copy from the source of truth rather than inventing values, so the
    # restored shape is the one 099 was supposed to have produced.
    op.execute(
        """
        UPDATE policy_reference_species AS p
        SET local_name = m.local_name
        FROM tree_species_coefficients AS m
        WHERE m.scientific_name = p.scientific_name
        """
    )
