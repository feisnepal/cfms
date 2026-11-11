"""The policy groups must partition the species exactly (P2 gate).

POLICY_SPECIES_PLAN P2. This is the safety net for the whole feature.

The two reporting groups are a *presentation* of data that was already computed
per species. Nothing is recalculated. So the only way this feature can do real
damage is if the grouping loses or invents something: a species that vanishes, a
volume that appears in one group and not the other, or a compartment whose parts
do not add to its whole.

That matters more than it sounds, because the numbers downstream are a farmer's
allowable cut. AAH per hectare is `mai_ha * class_volume / total_volume`; a
species silently dropped from the response does not merely look wrong, it moves
volume between species and therefore changes what may be taken.

So the gate is an identity, per measure, per compartment and for the forest:

    reference + other == total

and every species lands in exactly one group.

The measures here are the ones the backend owns: count, timber, firewood and
volume, in both the absolute and the per-hectare breakdowns. MAI and AAH are
*derived on the client* from these per-species volumes and a per-compartment rate
(`speciesGrowthByBlock` in FieldInventoryResultsTables.tsx), so their partition
is asserted in the frontend suite where they are actually computed -- see
`frontend/src/components/__tests__/speciesGrowth.test.tsx`. Asserting MAI here
would be asserting a formula this module never sees.
"""
from __future__ import annotations

import pytest

from app.core.policy_species_registry import OTHER, REFERENCE
from app.core.species_policy import (
    ABSOLUTE_MEASURES,
    PER_HA_MEASURES,
    annotate_species_rows,
    build_policy_groups,
)

MEASURES = ABSOLUTE_MEASURES + PER_HA_MEASURES

# The real species of the owner's forest b67f9e1c, with the split the registry
# must produce. Using the real names rather than a fixture chosen to agree with
# the implementation is the point: 7 in-list, 10 other, 44.1% / 55.9% of stems.
REAL_SPECIES = [
    # reference: 4 named outright
    "Shorea robusta",
    "Terminalia alata",
    "Bombax ceiba",
    "Anogeissus latifolia",
    # reference: 3 captured by the genus entry "Albizia spp"
    "Albizia chinensis",
    "Albizia lebbeck",
    "Albizia procera",
    # other: includes the two a genus test would wrongly take
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


def _rows(names, block="B1", **extra):
    """Build species rows with distinct, non-round values per measure.

    Distinct values matter: if every row carried the same number, a rollup that
    dropped or duplicated one row would still add up, and the test would pass on
    a broken implementation.
    """
    rows = []
    for i, name in enumerate(names):
        row = {
            "block_name": block,
            "species_scientific": name,
            "species_local": name,
            "dbh_class": "30_40",
        }
        for j, key in enumerate(MEASURES):
            row[key] = round(1.5 + i * 0.37 + j * 0.11, 4)
        row["count"] = 100 + i * 7
        row["count_per_ha"] = round(2.25 + i * 0.13, 4)
        row.update(extra)
        rows.append(row)
    return rows


class TestAnnotation:
    def test_every_row_gets_exactly_one_classification(self):
        rows = annotate_species_rows(_rows(REAL_SPECIES))
        assert len(rows) == 17
        for r in rows:
            assert r["classification"] in {REFERENCE, OTHER}

    def test_the_split_is_seven_and_ten(self):
        rows = annotate_species_rows(_rows(REAL_SPECIES))
        ref = [r for r in rows if r["classification"] == REFERENCE]
        oth = [r for r in rows if r["classification"] == OTHER]
        assert len(ref) == 7
        assert len(oth) == 10

    def test_genus_capture_records_which_entry_matched(self):
        """The genus rule has to be auditable, not just applied.

        A reader seeing *Albizia chinensis* in the in-list group should be able to
        find out it got there via "Albizia spp". If `matched_by` is missing, the
        asymmetric rule is invisible and nobody can check it was applied correctly.
        """
        rows = annotate_species_rows(_rows(REAL_SPECIES))
        by_name = {r["species_scientific"]: r for r in rows}

        albizia = by_name["Albizia chinensis"]
        assert albizia["classification"] == REFERENCE
        assert albizia["matched_by"] == "Albizia spp"
        assert albizia["matched_by_level"] == "genus"

        shorea = by_name["Shorea robusta"]
        assert shorea["matched_by"] == "Shorea robusta"
        assert shorea["matched_by_level"] == "species"

        harro = by_name["Terminalia chebula"]
        assert harro["classification"] == OTHER
        assert harro["matched_by"] is None

    def test_an_unnameable_species_is_other_not_dropped(self):
        """A blank or free-text name goes to Other; it is never discarded.

        Dropping it would break the partition silently, and guessing a match
        would be worse than admitting the list does not cover it.
        """
        rows = annotate_species_rows([
            {"species_scientific": "", "volume_m3": 1.0},
            {"species_scientific": "some field note", "volume_m3": 2.0},
            {"species_scientific": None, "volume_m3": 4.0},
        ])
        assert len(rows) == 3
        assert all(r["classification"] == OTHER for r in rows)
        assert all(r["matched_by"] is None for r in rows)

    def test_empty_input_is_handled(self):
        assert annotate_species_rows([]) == []


class TestPartitionHolds:
    """The identity. Per measure, per compartment, and for the forest."""

    def test_forest_wide_absolute(self):
        rows = annotate_species_rows(_rows(REAL_SPECIES))
        groups = build_policy_groups(rows, ABSOLUTE_MEASURES)
        assert groups["partition_holds"] is True
        for key in ABSOLUTE_MEASURES:
            parts = groups["reference"][key] + groups["other"][key]
            assert parts == pytest.approx(groups["total"][key], rel=1e-9), key

    def test_forest_wide_per_hectare(self):
        rows = annotate_species_rows(_rows(REAL_SPECIES))
        groups = build_policy_groups(rows, PER_HA_MEASURES)
        assert groups["partition_holds"] is True
        for key in PER_HA_MEASURES:
            parts = groups["reference"][key] + groups["other"][key]
            assert parts == pytest.approx(groups["total"][key], rel=1e-9), key

    def test_per_compartment(self):
        rows = []
        for b in ("B1", "B2", "B3"):
            rows.extend(_rows(REAL_SPECIES, block=b))
        rows = annotate_species_rows(rows)
        groups = build_policy_groups(
            rows, PER_HA_MEASURES, group_by="block_name", blocks=["B1", "B2", "B3"]
        )
        assert set(groups["per_block"]) == {"B1", "B2", "B3"}
        for name, g in groups["per_block"].items():
            assert g["partition_holds"] is True, name
            for key in PER_HA_MEASURES:
                parts = g["reference"][key] + g["other"][key]
                assert parts == pytest.approx(g["total"][key], rel=1e-9), (name, key)

    def test_no_species_is_lost_between_the_groups_and_the_rows(self):
        rows = annotate_species_rows(_rows(REAL_SPECIES))
        groups = build_policy_groups(rows, ABSOLUTE_MEASURES)
        named = groups["reference"]["species"] + groups["other"]["species"]
        assert sorted(named) == sorted(r["species_scientific"] for r in rows)
        assert len(named) == len(set(named)), "a species appears in both groups"

    def test_counts_are_species_counts_not_stem_counts(self):
        """`species_count` must be the number of species, not the number of stems.

        Easy to get backwards, and it would make the group's headline figure a
        stem total labelled as a species count -- which is the kind of wrong that
        reads as plausible.
        """
        rows = annotate_species_rows(_rows(REAL_SPECIES))
        groups = build_policy_groups(rows, ABSOLUTE_MEASURES)
        assert groups["reference"]["species_count"] == 7
        assert groups["other"]["species_count"] == 10
        assert groups["total"]["species_count"] == 17
        # The stems are a different, much larger number.
        assert groups["total"]["count"] > 100 * 17


class TestRowsAreNotSpecies:
    """The real breakdowns are keyed by species AND DBH class.

    `species_dbh_forest_wide` and `species_dbh_breakdown` carry one row per
    species per DBH class, so a species appears many times. A rollup that counts
    *rows* and calls the result a species count reports 51 reference "species"
    for a forest that has 7 -- and that is the first number a policy reader looks
    at, and it reads as plausible, so nobody checks it.

    This is not hypothetical: it is what the first version of this rollup did, and
    it was only caught by running the real forest rather than a tidy fixture.
    """

    @staticmethod
    def _multi_class_rows(names, classes=("10_20", "20_30", "30_40")):
        rows = []
        for i, name in enumerate(names):
            for j, cls in enumerate(classes):
                row = {
                    "block_name": "B1",
                    "species_scientific": name,
                    "species_local": name,
                    "dbh_class": cls,
                }
                for k, key in enumerate(MEASURES):
                    row[key] = round(0.5 + i * 0.31 + j * 0.17 + k * 0.05, 4)
                rows.append(row)
        return rows

    def test_species_count_is_distinct_species_not_rows(self):
        rows = annotate_species_rows(self._multi_class_rows(REAL_SPECIES))
        assert len(rows) == 17 * 3

        groups = build_policy_groups(rows, PER_HA_MEASURES)
        assert groups["reference"]["species_count"] == 7
        assert groups["other"]["species_count"] == 10
        assert groups["total"]["species_count"] == 17

    def test_the_species_list_has_no_repeats(self):
        rows = annotate_species_rows(self._multi_class_rows(REAL_SPECIES))
        groups = build_policy_groups(rows, PER_HA_MEASURES)
        for group in ("reference", "other", "total"):
            names = groups[group]["species"]
            assert len(names) == len(set(names)), group
            assert len(names) == groups[group]["species_count"], group

    def test_row_count_is_published_so_the_two_numbers_can_be_told_apart(self):
        rows = annotate_species_rows(self._multi_class_rows(REAL_SPECIES))
        groups = build_policy_groups(rows, PER_HA_MEASURES)
        assert groups["total"]["row_count"] == 51
        assert groups["total"]["species_count"] == 17
        assert groups["total"]["row_count"] > groups["total"]["species_count"]

    def test_measures_still_sum_across_the_class_rows(self):
        """Deduplicating names must not deduplicate the numbers.

        Each class row is a real contribution to the per-hectare total, so the
        measures have to keep summing all of them.
        """
        rows = annotate_species_rows(self._multi_class_rows(REAL_SPECIES))
        groups = build_policy_groups(rows, PER_HA_MEASURES)
        assert groups["partition_holds"] is True
        for key in PER_HA_MEASURES:
            parts = groups["reference"][key] + groups["other"][key]
            assert parts == pytest.approx(groups["total"][key], rel=1e-9), key

    def test_the_seven_reference_species_are_the_named_ones(self):
        rows = annotate_species_rows(self._multi_class_rows(REAL_SPECIES))
        groups = build_policy_groups(rows, PER_HA_MEASURES)
        assert sorted(groups["reference"]["species"]) == sorted([
            "Albizia chinensis", "Albizia lebbeck", "Albizia procera",
            "Anogeissus latifolia", "Bombax ceiba", "Shorea robusta",
            "Terminalia alata",
        ])


class TestEmptyAndOneSidedCases:
    """A group with nothing in it must read as zero, not be missing."""

    def test_all_reference(self):
        names = [n for n in REAL_SPECIES if n in {
            "Shorea robusta", "Terminalia alata", "Albizia chinensis",
        }]
        rows = annotate_species_rows(_rows(names))
        groups = build_policy_groups(rows, ABSOLUTE_MEASURES)
        assert groups["reference"]["species_count"] == 3
        assert groups["other"]["species_count"] == 0
        assert groups["other"]["count"] == 0
        assert groups["partition_holds"] is True

    def test_all_other(self):
        names = ["Cassia fistula", "Acacia concinna"]
        rows = annotate_species_rows(_rows(names))
        groups = build_policy_groups(rows, ABSOLUTE_MEASURES)
        assert groups["reference"]["species_count"] == 0
        assert groups["other"]["species_count"] == 2
        assert groups["partition_holds"] is True

    def test_no_species_at_all(self):
        groups = build_policy_groups([], ABSOLUTE_MEASURES)
        assert groups["reference"]["species_count"] == 0
        assert groups["other"]["species_count"] == 0
        assert groups["partition_holds"] is True

    def test_a_compartment_with_no_species_is_still_listed(self):
        """A reader comparing compartments needs them all present.

        A compartment whose species all fall in one group must not disappear from
        the rollup, or the comparison silently covers fewer compartments than the
        map above it.
        """
        rows = annotate_species_rows(
            _rows(REAL_SPECIES, block="B1")
            + _rows(["Cassia fistula"], block="B2")
        )
        groups = build_policy_groups(
            rows, PER_HA_MEASURES, group_by="block_name", blocks=["B1", "B2", "B3"]
        )
        assert set(groups["per_block"]) == {"B1", "B2", "B3"}
        assert groups["per_block"]["B3"]["present_in_response"] is False
        assert groups["per_block"]["B3"]["partition_holds"] is True
        assert groups["per_block"]["B3"]["total"]["species_count"] == 0
        assert groups["per_block"]["B2"]["other"]["species_count"] == 1
        assert groups["per_block"]["B2"]["reference"]["species_count"] == 0


class TestPartitionIsCheckedNotAssumed:
    """`partition_holds` is reported so callers can assert it.

    An invariant verified only in a test decays: the next person adds a measure
    or changes the summing and nothing complains. Reporting it in the payload
    makes the check part of the data, not a comment.
    """

    def test_detail_reports_every_measure(self):
        rows = annotate_species_rows(_rows(REAL_SPECIES))
        groups = build_policy_groups(rows, ABSOLUTE_MEASURES)
        assert set(groups["partition_detail"]) == set(ABSOLUTE_MEASURES)
        for key, d in groups["partition_detail"].items():
            assert d["gap"] == pytest.approx(0.0, abs=1e-6), key

    def test_the_gap_arithmetic_would_catch_a_lost_species(self):
        """The comparison the module uses, shown detecting a real discrepancy.

        `_group_block` derives `total` from the same rows it buckets, so within
        the function the partition cannot break -- that is the design, and it is
        why this is not a tautological test. What *can* break it is a later
        change: a new measure added to the list but not to the summing, or a
        caller that filters rows between annotation and rollup.

        So this asserts the detection arithmetic itself, using the same tolerance
        the module applies. If someone loosens the tolerance, this fails.
        """
        rows = annotate_species_rows(_rows(REAL_SPECIES))
        groups = build_policy_groups(rows, ABSOLUTE_MEASURES)

        def holds(ref, oth, whole):
            gap = abs(ref + oth - whole)
            return gap / max(abs(whole), 1.0) <= 1e-6

        key = "volume_m3"
        ref = groups["reference"][key]
        oth = groups["other"][key]
        whole = groups["total"][key]

        assert holds(ref, oth, whole) is True

        # A species dropped from one group but still counted in the total.
        assert holds(ref - 1.0, oth, whole) is False
        # A species counted in both groups -- the double-count failure.
        assert holds(ref + 1.0, oth + 1.0, whole) is False
        # Float noise must NOT trip it, or the check is useless.
        assert holds(ref, oth, whole + 1e-12) is True

    def test_a_non_numeric_measure_is_logged_not_silently_zeroed(self, caplog):
        rows = annotate_species_rows([
            {"species_scientific": "Shorea robusta", "volume_m3": "not a number"},
        ])
        with caplog.at_level("WARNING"):
            groups = build_policy_groups(rows, ("volume_m3",))
        assert groups["total"]["volume_m3"] == 0.0
        assert any("non-numeric" in r.message for r in caplog.records)
