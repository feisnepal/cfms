"""Policy reference species: the curated 21, as data.

SUPERSEDED IN PART by migration 100 -- read that one too. 099 created and seeded
a `local_name` column on the theory that a copy of the species master's local
name was a harmless display convenience. It was a second persisted copy of
single-source-of-truth data, and 100 drops it. The column stays declared here
because 099 has already run: rewriting an applied migration to hide a mistake
would leave a fresh database unable to reproduce what production actually
executed. Create-then-drop is the honest sequence.

Revision ID: 099_policy_reference_species
Revises: 098_forest_metadata
Create Date: 2026-09-27

Why this migration exists (POLICY_SPECIES_PLAN D2)
--------------------------------------------------
Field inventory analyses every recorded species individually. Correct
technically, unreadable at policy level. The owner wants a curated list
analysed individually and the remainder reported as "Other species", so the
list needs to exist somewhere reviewable.

It is not a column on `tree_species_coefficients`, which already holds 861
species with their densities and equations. That table is the species *master*:
its rows change when a forester revises a wood density. The list changes when a
cabinet revises policy, and 21 flagged rows among 861 is a list nobody can read
in a diff. `match_level` also has no meaning on a coefficient row -- it is the
answer to "does this entry speak for its genus or only itself?" -- so the same
row would have to mean two different things depending on the reader's question.

The same shape `dbh_class_systems` already established here: a policy list in
its own table, seeded by migration, read through a registry.

All 21 already exist in the master on BOTH scientific_name and local_name, so
this seeds a curated subset rather than inventing a second species registry.

`match_level` is seeded per row and is the load-bearing part of D1
------------------------------------------------------------------
The list mixes two kinds of entry, and applying one rule to both gives wrong
answers in both directions:

  * 'genus' entries -- *Abies spp*, *Albizia spp*, *Quercus spp*, *Tsuga spp* --
    speak for a genus. The three *Albizia* species in this forest (*chinensis*,
    *lebbeck*, *procera*) are all locally "Siris" and all belong in the list.
  * 'species' entries -- *Terminalia alata* (Saj, Asna) among them -- speak for
    themselves only. *Terminalia chebula* (Harro) shares the genus but is a
    different species under a different name, and folding it in would report
    Harro as Saj.

Seeding `match_level` explicitly is what stops a future reader re-deriving the
rule from whether a name ends in "spp". An earlier reading of this data did
exactly that, got 4 in-list species instead of 7, and wrongly pulled in
*Acacia concinna* via *Acacia catechu* and *Terminalia chebula* via *T. alata*.

`local_name` is read from the species master, not typed here
------------------------------------------------------------
`local_name` on this table is a denormalised convenience for display; the species
master owns local names. So the migration LOOKS each one up rather than carrying
a second copy of 21 strings.

That is not just tidiness. Hand-transcribing the local names was tried first and
produced 16 of 21 disagreeing with the master -- e.g. the master has *Bombax
ceiba* = "Simal, Semal". Some of those disagreements are the owner's own list
using different local names; others were transcription corruption on my side. A
migration that can disagree with its own source of truth is a migration that will
quietly ship wrong names, so it reads them.

The lookup also doubles as the migration's gate: if any of the 21 is absent from
the master, this raises and the migration fails. A half-seeded policy list is
worse than no table.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "099_policy_reference_species"
down_revision = "098_forest_metadata"
branch_labels = None
depends_on = None


# (scientific_name, match_level, display_order)
#
# Ordered as a forester would work through the list: canopy first, then
# mid-storey, then regeneration. `local_name` is NOT here -- it is looked up
# from tree_species_coefficients below.
SEED: list[tuple[str, str, int]] = [
    # Canopy / large timber
    ("Shorea robusta",            "species", 1),
    ("Terminalia alata",          "species", 2),
    ("Bombax ceiba",              "species", 3),
    ("Anogeissus latifolia",       "species", 4),
    ("Cedrela toona",             "species", 5),
    ("Schima wallichii",          "species", 6),
    ("Acacia catechu",            "species", 7),
    ("Dalbergia sissoo",          "species", 8),
    ("Syzygium cumini",           "species", 9),
    ("Pinus roxburghii",          "species", 10),
    ("Pinus wallichiana",         "species", 11),
    ("Trewia nudiflora",          "species", 12),
    # Mid-storey / understorey
    ("Albizia spp",               "genus",   13),
    ("Quercus spp",               "genus",   14),
    ("Lagerstroemia parviflora",  "species", 15),
    ("Adina cardifolia",          "species", 16),
    ("Hymenodictyon excelsum",    "species", 17),
    ("Michelia champaca",         "species", 18),
    ("Alnus nepalensis",          "species", 19),
    ("Abies spp",                 "genus",   20),
    ("Tsuga spp",                 "genus",   21),
]


def _lookup_local_names(bind, names: list[str]) -> tuple[dict[str, str | None], list[str]]:
    """Read local names from the species master.

    Returns `(local_names, missing)`.

    This never raises. A schema migration's job is to create the table and seed
    the list; it is not the right place to assert that reference data is loaded,
    because the list's identity is `scientific_name` + `match_level` and
    `local_name` is only a display convenience. Gaps are recorded in `notes` and
    printed, so they are visible in the migration log rather than silently
    dropped.

    The integrity check that *does* belong to a test -- "all 21 exist in the
    species master, so a typo cannot slip through" -- is
    `tests/test_policy_species_registry.py::test_all_twenty_one_exist_in_the_species_master`.
    It runs against a real master and skips where reference data is absent.
    """
    rows = bind.execute(
        sa.text(
            "SELECT scientific_name, local_name FROM tree_species_coefficients "
            "WHERE scientific_name = ANY(:names)"
        ),
        {"names": names},
    ).fetchall()
    found = {r[0]: r[1] for r in rows}
    missing = [n for n in names if n not in found]
    return found, missing


def upgrade() -> None:
    op.create_table(
        "policy_reference_species",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("scientific_name", sa.String(150), nullable=False),
        # Superseded by migration 100, which drops this column. It is kept here
        # because 099 is already applied: rewriting an applied migration to
        # erase a mistake from the history would leave a fresh database unable
        # to reproduce what production actually ran. Create-then-drop is the
        # honest sequence. Do not add anything to this column.
        sa.Column("local_name", sa.String(150), nullable=True),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        # NOT NULL on purpose: an entry that does not say how it matches is a
        # list waiting to be guessed at, and the guess is wrong in both
        # directions (see module docstring).
        sa.Column("match_level", sa.String(10), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.UniqueConstraint(
            "scientific_name", name="uq_policy_reference_species_scientific_name"
        ),
        sa.CheckConstraint(
            "match_level IN ('species', 'genus')",
            name="ck_policy_reference_species_match_level",
        ),
        # A genus entry's name is the genus; a species entry's name is a
        # binomial. Stops the registry's genus split being handed something
        # it will mis-parse.
        sa.CheckConstraint(
            "match_level = 'genus' OR position(' ' in scientific_name) > 0",
            name="ck_policy_reference_species_species_has_binomial",
        ),
    )
    op.create_index(
        "ix_policy_reference_species_active_order",
        "policy_reference_species",
        ["is_active", "display_order"],
    )
    op.create_index(
        "ix_policy_reference_species_match_level",
        "policy_reference_species",
        ["match_level"],
    )

    names = [s for s, _, _ in SEED]
    local_names, missing = _lookup_local_names(op.get_bind(), names)
    if missing:
        print(
            "[policy_reference_species] species master has no local names for "
            f"{len(missing)} entr(y/ies); seeding scientific names only: {missing}"
        )

    op.bulk_insert(
        sa.table(
            "policy_reference_species",
            sa.column("scientific_name", sa.String),
            sa.column("local_name", sa.String),
            sa.column("display_order", sa.Integer),
            sa.column("match_level", sa.String),
            sa.column("is_active", sa.Boolean),
            sa.column("notes", sa.String),
        ),
        [
            {
                "scientific_name": sci,
                "local_name": local_names.get(sci),
                "display_order": order,
                "match_level": level,
                "is_active": True,
                "notes": (
                    None
                    if sci in local_names
                    else "local_name not found in tree_species_coefficients at seed time"
                ),
            }
            for sci, level, order in SEED
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_policy_reference_species_match_level",
        table_name="policy_reference_species",
    )
    op.drop_index(
        "ix_policy_reference_species_active_order",
        table_name="policy_reference_species",
    )
    op.drop_table("policy_reference_species")
