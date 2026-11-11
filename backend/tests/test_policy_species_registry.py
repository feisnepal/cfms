"""Policy species registry: the asymmetric matching rule (P1, D1).

The rule is the whole correctness of this feature, and it is easy to write in a
way that looks symmetric and is not. These tests pin both directions, because
each has a plausible wrong answer:

  * too wide  -- a genus test applied to species-level entries sweeps in
    *Acacia concinna* via *Acacia catechu* and reports Harro as Saj.
  * too narrow -- an exact test applied to genus-level entries dumps three
    Siris species into "Other species".

The first version of this data was read with a blunt genus test and got the
in-list count wrong: 4 instead of 7. So the count is asserted here too, not just
the individual classifications.
"""
from __future__ import annotations

import pytest

from app.core.policy_species_registry import (
    MATCH_LEVEL_GENUS,
    MATCH_LEVEL_SPECIES,
    OTHER,
    REFERENCE,
    PolicySpeciesEntry,
    PolicySpeciesRegistry,
)


def _species(name: str, order: int = 1) -> PolicySpeciesEntry:
    return PolicySpeciesEntry(
        scientific_name=name, local_name=None,
        match_level=MATCH_LEVEL_SPECIES, display_order=order,
    )


def _genus(name: str, order: int = 1) -> PolicySpeciesEntry:
    return PolicySpeciesEntry(
        scientific_name=name, local_name=None,
        match_level=MATCH_LEVEL_GENUS, display_order=order,
    )


# --------------------------------------------------------------------- matching

class TestSpeciesLevelEntries:
    """A species-level entry speaks for itself and nothing else."""

    def test_matches_itself(self):
        assert _species("Terminalia alata").matches("Terminalia alata") is True

    def test_does_not_sweep_its_genus(self):
        """The failure that produced the 4-instead-of-7 count.

        Harro and Saj share a genus. A genus test here would report Harro as
        Saj, which is simply the wrong tree.
        """
        entry = _species("Terminalia alata")
        assert entry.matches("Terminalia chebula") is False

    def test_does_not_capture_a_sibling_species(self):
        entry = _species("Acacia catechu")
        assert entry.matches("Acacia concinna") is False

    def test_does_not_match_a_different_genus(self):
        assert _species("Acacia catechu").matches("Albizia lebbeck") is False


class TestGenusLevelEntries:
    """A genus-level entry speaks for every species under it."""

    def test_captures_a_species_under_it(self):
        assert _genus("Albizia spp").matches("Albizia chinensis") is True

    def test_captures_several_species_under_it(self):
        entry = _genus("Albizia spp")
        for name in ("Albizia chinensis", "Albizia lebbeck", "Albizia procera"):
            assert entry.matches(name) is True, name

    def test_matches_its_own_name(self):
        assert _genus("Albizia spp").matches("Albizia spp") is True

    def test_does_not_capture_another_genus(self):
        assert _genus("Albizia spp").matches("Acacia catechu") is False

    def test_genus_derived_from_the_entry_not_the_target(self):
        """A genus entry's stored name is the bare genus.

        If the genus were taken from the *target* the test would pass for the
        wrong reason -- it would be checking that the target is in its own
        genus, which is always true.
        """
        assert _genus("Albizia spp").genus == "albizia"


class TestNormalisation:
    """Values arrive from a field sheet and from free-text imports."""

    @pytest.mark.parametrize(
        "recorded",
        [
            "Albizia chinensis",
            "albizia chinensis",
            "ALBIZIA CHINENSIS",
            "  Albizia   chinensis  ",
        ],
    )
    def test_case_and_whitespace_insensitive(self, recorded):
        assert _genus("Albizia spp").matches(recorded) is True

    @pytest.mark.parametrize("recorded", ["", "   ", None])
    def test_empty_input_is_not_a_match(self, recorded):
        assert _genus("Albizia spp").matches(recorded) is False


# ------------------------------------------------------------------ the registry

class TestRegistryAgainstTheForest:
    """Against the species the owner's forest actually records.

    These are the real 17 species of calculation b67f9e1c, not a fixture chosen
    to agree with the implementation. The stems and the 7/10 split come from
    `field_inventory_measurements` for that calculation.
    """

    # The seven that belong on the list, with the entry that speaks for them.
    REFERENCE_CASES = [
        ("Shorea robusta", "Shorea robusta"),
        ("Terminalia alata", "Terminalia alata"),
        ("Bombax ceiba", "Bombax ceiba"),
        ("Anogeissus latifolia", "Anogeissus latifolia"),
        ("Albizia chinensis", "Albizia spp"),
        ("Albizia lebbeck", "Albizia spp"),
        ("Albizia procera", "Albizia spp"),
    ]

    # The ten that must not, including the two a genus test would wrongly take.
    OTHER_CASES = [
        "Cassia fistula",
        "Terminalia chebula",   # Harro, not Saj
        "Spondias pinnata",
        "Artocarpus lakoocha",
        "Phyllanthus emblica",
        "Azadirachta indica",
        "Kydia calycina",
        "Bauhinia variegata",
        "Litchi chinensis",
        "Acacia concinna",      # not Acacia catechu
    ]

    @pytest.mark.parametrize("name,via", REFERENCE_CASES)
    def test_in_list_species_are_reference(self, name, via):
        assert PolicySpeciesRegistry.classify(name) == REFERENCE
        entry = PolicySpeciesRegistry.match_reason(name)
        assert entry is not None, name
        assert entry.scientific_name == via, (
            f"{name} was matched by {entry.scientific_name}, expected {via}"
        )

    @pytest.mark.parametrize("name", OTHER_CASES)
    def test_out_of_list_species_are_other(self, name):
        assert PolicySpeciesRegistry.classify(name) == OTHER
        assert PolicySpeciesRegistry.match_reason(name) is None

    def test_the_split_is_seven_and_ten(self):
        """The count, asserted because it is the number the owner was shown.

        A wrong count is what a too-wide genus test produces, and it changes the
        owner's decision about how prominent the in-list group should be.
        """
        all_names = [n for n, _ in self.REFERENCE_CASES] + self.OTHER_CASES
        buckets = PolicySpeciesRegistry.split(all_names)
        assert len(buckets[REFERENCE]) == 7
        assert len(buckets[OTHER]) == 10
        assert len(buckets[REFERENCE]) + len(buckets[OTHER]) == len(all_names)

    def test_split_preserves_first_seen_order(self):
        names = ["Zanthoxylum armatum", "Albizia lebbeck", "Cassia fistula"]
        buckets = PolicySpeciesRegistry.split(names)
        assert buckets[REFERENCE] == ["Albizia lebbeck"]
        assert buckets[OTHER] == ["Zanthoxylum armatum", "Cassia fistula"]

    def test_split_loses_nothing(self):
        """A species must not vanish by being unclassifiable.

        Every recorded species lands in exactly one bucket -- that is what makes
        reference + other a true partition of the forest.
        """
        all_names = [n for n, _ in self.REFERENCE_CASES] + self.OTHER_CASES
        buckets = PolicySpeciesRegistry.split(all_names)
        assert sorted(buckets[REFERENCE] + buckets[OTHER]) == sorted(all_names)

    def test_list_has_twenty_one_entries_with_four_genera(self):
        entries = PolicySpeciesRegistry.entries()
        assert len(entries) == 21
        genera = [e for e in entries if e.match_level == MATCH_LEVEL_GENUS]
        assert len(genera) == 4
        assert {e.genus for e in genera} == {"abies", "albizia", "quercus", "tsuga"}


class TestSeedAndFallbackAgree:
    """The shipped fallback must not drift from the migration.

    There are two copies of the list -- the migration seed and the registry's
    fallback -- because the fallback is what keeps reports alive if the
    migration has not run. Two copies drift unless something checks.
    """

    @staticmethod
    def _migration_seed() -> list[tuple[str, str]]:
        """Read SEED straight out of the migration file.

        Loaded by path: `alembic/versions` is not a package.
        """
        import importlib.util
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[1]
            / "alembic" / "versions" / "099_policy_reference_species.py"
        )
        assert path.exists(), f"migration file missing: {path}"
        spec = importlib.util.spec_from_file_location("_mig099", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return [(name, level) for name, level, _ in module.SEED]

    def test_fallback_matches_the_migration_seed(self):
        seeded = self._migration_seed()
        shipped = list(PolicySpeciesRegistry._FALLBACK)
        assert shipped == seeded, (
            "the registry fallback and migration 099 list different species; "
            "an unseeded deployment would report a different policy list"
        )

    def test_migration_seed_has_twenty_one_unique_names(self):
        seeded = self._migration_seed()
        names = [n for n, _ in seeded]
        assert len(names) == 21
        assert len(set(names)) == 21, "duplicate entry in the policy list"

    def test_migration_seed_covers_the_three_siris_species(self):
        """The three Siris species must be capturable without the DB.

        If the fallback were missing 'Albizia spp', an unseeded deployment would
        quietly move 386 stems from the in-list group into Other.
        """
        entries = [
            PolicySpeciesEntry(n, None, l, i)
            for i, (n, l) in enumerate(PolicySpeciesRegistry._FALLBACK, 1)
        ]
        for name in ("Albizia chinensis", "Albizia lebbeck", "Albizia procera"):
            assert any(e.matches(name) for e in entries), name


class TestListIsASubsetOfTheSpeciesMaster:
    """Every entry must exist in the master, or it can never match anything.

    This is the check that catches a misspelt scientific name, and it lives here
    rather than in the migration on purpose. The migration must not depend on
    reference data being loaded -- on a clean test database the master is empty,
    and a schema migration that raises there cannot create the table at all. So
    the migration seeds best-effort and records gaps in `notes`, and the
    integrity assertion is made where it can require a real master.
    """

    def test_all_twenty_one_exist_in_the_species_master(self, db):
        """No misspelt scientific name.

        Now checkable strictly. It could not be before migrations 101-103: a
        freshly migrated database carried only migration 003's 25 species, so
        `Syzygium cumini` was simply absent and a plain "is this name present"
        assertion failed while reporting the wrong problem. The master is now
        loaded from `alembic/versions/data/species_master.jsonl`, a fresh build
        reproduces production, and a FOREIGN KEY enforces it -- so this test
        asserts the straightforward thing and the database agrees.
        """
        from sqlalchemy import text

        names = [n for n, _ in PolicySpeciesRegistry._FALLBACK]
        found = {
            r[0]
            for r in db.execute(
                text(
                    "SELECT scientific_name FROM tree_species_coefficients "
                    "WHERE scientific_name = ANY(:names)"
                ),
                {"names": names},
            ).fetchall()
        }
        missing = [n for n in names if n not in found]
        assert not missing, (
            "these policy entries are not in tree_species_coefficients, so they "
            f"can never match a recorded species: {missing}"
        )

    def test_the_database_enforces_it_too(self, db):
        """The foreign key is the real guarantee; this checks it is installed.

        A test asserting data correctness is worth less than a constraint that
        makes the incorrect state impossible, so assert the constraint exists
        rather than only that the data happens to be right today.
        """
        from sqlalchemy import text

        n = db.execute(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid = to_regclass('policy_reference_species') "
                "  AND contype = 'f' "
                "  AND pg_get_constraintdef(oid) LIKE '%scientific_name%'"
            )
        ).scalar()
        assert n >= 1, (
            "no foreign key from policy_reference_species.scientific_name to the "
            "species master; a misspelt name would be accepted silently"
        )

    def test_the_fresh_master_is_the_committed_snapshot(self, db):
        """The master must be reproducible, or tests diverge from production.

        This is the assertion that would have caught the original problem: the
        master had 25 species in migrations and 861 in production, and nothing
        recorded that. It compares against the committed file, so a species added
        to the master without updating the snapshot fails here.
        """
        import importlib.util
        from pathlib import Path

        from sqlalchemy import text

        path = (
            Path(__file__).resolve().parents[1]
            / "alembic" / "versions" / "data" / "species_master.jsonl"
        )
        assert path.exists(), (
            f"species master snapshot missing: {path}. The master is the single "
            "source of truth; without a committed copy a fresh database gets a "
            "different one."
        )
        spec = importlib.util.spec_from_file_location(
            "_species_master_loader", path.parent / "species_master_loader.py"
        )
        loader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loader)
        snapshot = {r["scientific_name"] for r in loader.load_snapshot()}

        in_db = {
            r[0]
            for r in db.execute(
                text("SELECT scientific_name FROM tree_species_coefficients")
            ).fetchall()
        }
        assert in_db == snapshot, (
            "the species master does not match the committed snapshot: "
            f"{len(in_db - snapshot)} in the database only, "
            f"{len(snapshot - in_db)} in the snapshot only"
        )

    def test_policy_table_stores_no_species_data_of_its_own(self, db):
        """The policy table must not copy anything out of the species master.

        `tree_species_coefficients` is the single source of truth for what a
        species is. An earlier version of this table carried a `local_name`
        column seeded by copying the master, on the reasoning that it was a
        harmless display convenience; 16 of the 21 copies already disagreed with
        their source, and the only defence was a test that asserted they agreed.
        A test that polices a duplicate is a confession the duplicate should not
        exist, so the column was dropped instead.

        Asserted on the live schema, so re-adding a copy of master data fails
        here rather than quietly reintroducing a second source of truth.
        """
        from sqlalchemy import text

        cols = {
            r[0]
            for r in db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'policy_reference_species'"
                )
            ).fetchall()
        }
        assert cols, "policy_reference_species not present - is 099 applied?"
        # Policy columns only. Anything naming a species attribute belongs in
        # the master: local_name, genus, family, aliases, coefficients, density.
        assert cols == {
            "id",
            "scientific_name",
            "display_order",
            "match_level",
            "is_active",
            "created_at",
            "updated_at",
            "notes",
        }, f"unexpected columns on the policy table: {sorted(cols)}"

    def test_local_names_are_resolved_from_the_master(self, db):
        """`local_name_for` must answer from the master, or say nothing.

        179 of the master's 861 rows carry a placeholder ('nan', '-', ...) in
        `local_name`. A report that prints "nan" as a tree's name is worse than
        one that prints nothing, so placeholders become None at the boundary.
        """
        from sqlalchemy import text

        total = db.execute(
            text("SELECT count(*) FROM tree_species_coefficients")
        ).scalar()
        if not total:
            pytest.skip("species master not loaded in this database")

        names = list(PolicySpeciesRegistry.local_names())
        assert len(names) == 21

        for sci in names:
            master = db.execute(
                text(
                    "SELECT local_name FROM tree_species_coefficients "
                    "WHERE scientific_name = :n"
                ),
                {"n": sci},
            ).scalar()
            expected = (master or "").strip()
            if expected.casefold() in {"", "nan", "na", "n/a", "-", "--",
                                       "unknown", "none", "null"}:
                expected = None
            assert PolicySpeciesRegistry.local_name_for(sci) == expected, (
                f"{sci}: registry disagrees with the species master"
            )

    def test_unknown_species_has_no_local_name(self):
        assert PolicySpeciesRegistry.local_name_for("Not A Realus species") is None
        assert PolicySpeciesRegistry.local_name_for("") is None
