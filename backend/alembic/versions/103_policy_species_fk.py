"""Enforce that the policy list can only name species that exist.

Revision ID: 103_policy_species_fk
Revises: 102_species_master_columns
Create Date: 2026-09-27

Why this migration exists
-------------------------
`tree_species_coefficients` is the species single source of truth, and
`policy_reference_species` names 21 of them. Nothing connected the two: a
misspelt scientific name in the list would have been accepted silently, seeded
into a table that claimed to describe the policy list, and simply never matched
anything. A species that cannot match is worse than an absent one, because the
report would show the in-list group quietly short by a species with nothing to
explain why.

D7 says the policy table stores policy only and copies no species data.
`scientific_name` is not a copy -- it is the key by which the list names a
species -- and this constraint is what makes that key trustworthy. The master has
a UNIQUE constraint on `scientific_name`, so the foreign key is supported.

This could not be added until migrations 101 and 102 landed, and the reason is
worth recording. On a freshly migrated database:

    policy rows with no matching master species   1 of 21   (`Syzygium cumini`)

so the constraint would have failed on every clean build, including every test
run. It would only have held on the one hand-fixed production database, which is
not what a constraint is for. That is now fixed at the source: 101 loads the
master from a committed snapshot, 102 creates the ten master columns no migration
had ever created.

Deliberately NOT `ON DELETE CASCADE`
------------------------------------
If a species is retired from the master, the policy list entry should not vanish
with it -- a policy list that silently forgets a species is the failure mode D5
exists to prevent. The default (`NO ACTION`) is kept so a deletion is *refused*
and has to be a deliberate act: the operator deactivates the list entry
(`is_active = false`) or fixes the master. That is the safer failure direction.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "103_policy_species_fk"
down_revision = "102_species_master_columns"
branch_labels = None
depends_on = None

FK_NAME = "fk_policy_reference_species_scientific_name"
TABLE = "policy_reference_species"
TARGET = "tree_species_coefficients"


def upgrade() -> None:
    bind = op.get_bind()

    existing = bind.execute(
        sa.text(
            # `to_regclass` rather than `:t::regclass` -- SQLAlchemy's text()
            # reads the second colon of a `::` cast as a bind parameter.
            "SELECT count(*) FROM pg_constraint "
            "WHERE conrelid = to_regclass(:t) AND conname = :n"
        ),
        {"t": TABLE, "n": FK_NAME},
    ).scalar()
    if existing:
        print(f"[policy_species_fk] {FK_NAME} already present; nothing to do")
        return

    # Report any orphans rather than letting the ALTER fail with a bare
    # constraint-violation error that says nothing about which species.
    orphans = bind.execute(
        sa.text(
            f"SELECT p.scientific_name FROM {TABLE} p "
            f"WHERE NOT EXISTS (SELECT 1 FROM {TARGET} m "
            f"WHERE m.scientific_name = p.scientific_name) "
            f"ORDER BY p.scientific_name"
        )
    ).fetchall()
    if orphans:
        names = [r[0] for r in orphans]
        raise RuntimeError(
            f"cannot add {FK_NAME}: these policy entries name species that are "
            f"not in {TARGET}: {names}. Fix the list (or the master) rather than "
            "loosening the constraint."
        )

    op.create_foreign_key(
        FK_NAME,
        TABLE,
        TARGET,
        ["scientific_name"],
        ["scientific_name"],
    )
    n = bind.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar()
    print(f"[policy_species_fk] added {FK_NAME}; all {n} policy entries resolve")


def downgrade() -> None:
    op.drop_constraint(FK_NAME, TABLE, type_="foreignkey")
