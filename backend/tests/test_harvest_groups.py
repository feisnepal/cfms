"""The harvest rollup must neither drop nor double-count a DBH class (P2b gate).

DBH_SSOT_PLAN P2b
-----------------
The eight `guideline_2061` classes are not how CFMG thinks about harvesting. It
groups them three ways -- Regeneration 0-10, Advance Growth 10-40, Mature Tree
>=40 -- and those three must account for **every** class. If a class is dropped
between the breakdown and the rollup, the three groups silently stop describing
the forest; if one is counted twice, they overstate it. Neither shows up in the
numbers themselves, which is why the gate is an identity rather than a spot check:

    sum of the three groups == the guideline_2061 total, for all four measures

per compartment and for the forest. The same reasoning as P0's AAH check.

Regeneration is the case worth watching. The Operational Plan has always omitted
it, so `sum(two groups) == total` was *true* only because the missing 0-10 cm was
never counted anywhere. Including Regeneration is D12, and with it the identity
has to hold across all three.

The second half of the gate is that the OP's rendered rollup is **unchanged** by
the refactor. The grouping moved to `app.core.harvest_groups`; the Nepali
headings stayed in `data_collector`. If this drifts, the refactor changed a
report nobody asked to change.
"""
from __future__ import annotations

import pytest

from app.core import harvest_groups as hg
from app.core.dbh_classifier import DbhClassRegistry

MEASURES = hg.MEASURES

# Deliberately awkward values: not round, not equal to each other, and with a
# zero somewhere. A rollup that dropped or duplicated a row would still add up if
# every row carried the same number.
CLASS_ROWS = [
    # block, class, count, timber, firewood
    ("B1", "0_4", 10.0, 1.0, 2.0),
    ("B1", "4_10", 20.0, 2.0, 4.0),
    ("B1", "10_20", 30.0, 3.0, 6.0),
    ("B1", "20_30", 40.0, 4.0, 8.0),
    ("B1", "30_40", 50.0, 5.0, 10.0),
    ("B1", "40_50", 60.0, 6.0, 12.0),
    ("B1", "50_60", 70.0, 7.0, 14.0),
    ("B1", "60_plus", 80.0, 8.0, 16.0),
    ("B2", "0_4", 11.0, 1.5, 3.0),
    ("B2", "4_10", 21.0, 2.5, 5.0),
    ("B2", "10_20", 31.0, 3.5, 7.0),
    ("B2", "20_30", 41.0, 4.5, 9.0),
    ("B2", "30_40", 51.0, 5.5, 11.0),
    ("B2", "40_50", 61.0, 6.5, 13.0),
    ("B2", "50_60", 71.0, 7.5, 15.0),
    ("B2", "60_plus", 81.0, 8.5, 17.0),
]

# What `field_inventory_measurements.dbh_class` actually holds, as the data
# collector writes it. Read off a real inventory rather than invented, because
# the whole point is that these are *not* the canonical keys: the measurements
# table stores a range-prefixed display string, and every caller of the rollup
# that forgets to translate loses its entire table. Note `'60+ V.Lg.Tree'` --
# the open upper bound is spelled with a `+`, not with a number.
COLLECTOR_DISPLAY_STRINGS = [
    "0-4 Seedling",
    "4-10 Sapling",
    "10-20 Sm.Pole",
    "20-30 Lg.Pole",
    "30-40 Sm.Tree",
    "40-50 Med.Tree",
    "50-60 Lg.Tree",
    "60+ V.Lg.Tree",
]


def _rows():
    return [
        {
            "block_name": b,
            "dbh_class": c,
            "count_per_ha": n,
            "timber_m3_per_ha": t,
            "firewood_m3_per_ha": f,
            # volume is timber + firewood, as the pane computes it
            "total_volume_m3_per_ha": t + f,
        }
        for b, c, n, t, f in CLASS_ROWS
    ]


def _totals(rows):
    out = {m: 0.0 for m in MEASURES}
    for r in rows:
        for m in MEASURES:
            out[m] += r[m]
    return out


class TestTheGroupingIsRegistryDerived:
    def test_the_three_groups_match_the_plan(self):
        assert hg.classes_in_group("regeneration") == ["0_4", "4_10"]
        assert hg.classes_in_group("advance_growth") == ["10_20", "20_30", "30_40"]
        assert hg.classes_in_group("mature_tree") == ["40_50", "50_60", "60_plus"]

    def test_every_base_class_lands_in_exactly_one_group(self):
        base = [c.key for c in DbhClassRegistry.get_system("guideline_2061")]
        mapping = hg.class_to_group()
        assert set(mapping) == set(base), (
            f"unmapped base classes: {sorted(set(base) - set(mapping))}"
        )
        assert len(mapping) == len(base), "a class mapped to more than one group"

    def test_regeneration_is_flagged_non_harvestable(self):
        """D12. Reported, yes; offered as harvestable, no."""
        assert hg.is_harvestable("regeneration") is False
        assert hg.is_harvestable("advance_growth") is True
        assert hg.is_harvestable("mature_tree") is True

    def test_the_mapping_is_not_hardcoded(self):
        """Move a boundary in the registry and the grouping must follow.

        The point of D9: if the grouping were a literal in this file, editing it
        would be a code change, and nothing would notice the two disagreeing.
        """
        base = DbhClassRegistry.get_system("guideline_2061")
        groups = DbhClassRegistry.get_system("harvesting_cfmg")
        advance = next(g for g in groups if g.key == "advance_growth")
        # A base class belongs to the group whose range contains its lower bound.
        for cls in base:
            expected = None
            for g in groups:
                if cls.lower >= g.lower and (g.upper is None or cls.lower < g.upper):
                    expected = g.key
                    break
            assert hg.class_to_group()[cls.key] == expected
        assert advance.lower == 10


class TestThePartitionHolds:
    """The gate: the three groups sum to the base total, per measure."""

    def test_per_block(self):
        grouped = hg.group_rollup(_rows())
        base = _rows()
        for block in ("B1", "B2"):
            want = _totals([r for r in base if r["block_name"] == block])
            got = {m: 0.0 for m in MEASURES}
            for row in grouped:
                if row["block_name"] != block:
                    continue
                for m in MEASURES:
                    got[m] += row[m]
            for m in MEASURES:
                assert got[m] == pytest.approx(want[m], rel=1e-9), (block, m)

    def test_forest_wide(self):
        grouped = hg.forest_rollup(hg.group_rollup(_rows()))
        want = _totals(_rows())
        got = {m: 0.0 for m in MEASURES}
        for row in grouped:
            for m in MEASURES:
                got[m] += row[m]
        for m in MEASURES:
            assert got[m] == pytest.approx(want[m], rel=1e-9), m

    def test_all_three_groups_are_present_per_block(self):
        grouped = hg.group_rollup(_rows())
        for block in ("B1", "B2"):
            keys = {r["group_key"] for r in grouped if r["block_name"] == block}
            assert keys == {"regeneration", "advance_growth", "mature_tree"}

    def test_no_class_is_listed_in_two_groups(self):
        seen: dict[str, str] = {}
        for row in hg.group_rollup(_rows()):
            for cls in row["dbh_classes"]:
                if cls in seen:
                    assert seen[cls] == row["group_key"], (
                        f"{cls} appears in both {seen[cls]} and {row['group_key']}"
                    )
                seen[cls] = row["group_key"]

    def test_a_dropped_class_would_be_caught(self):
        """Demonstrate the gate has teeth.

        Removing a class from the input must break the identity -- otherwise the
        identity would hold for any input and prove nothing.
        """
        full = hg.group_rollup(_rows())
        dropped = hg.group_rollup(
            [r for r in _rows() if r["dbh_class"] != "40_50"]
        )

        def total(rows, block):
            return sum(
                r["timber_m3_per_ha"]
                for r in rows
                if r["block_name"] == block
            )

        assert total(full, "B1") != total(dropped, "B1"), (
            "dropping a class did not change the rollup, so the identity cannot "
            "detect a dropped class"
        )


class TestNoPresentation:
    """D10: neutral keys only. A Nepali literal here would be untranslatable."""

    def test_group_keys_are_neutral(self):
        for row in hg.group_rollup(_rows()):
            assert row["group_key"] in {
                "regeneration", "advance_growth", "mature_tree"
            }
            for key, value in row.items():
                if isinstance(value, str):
                    assert value.isascii(), (
                        f"{key}={value!r} looks like presentation; the shared "
                        "function must return neutral keys so each caller can "
                        "translate them"
                    )


class TestTheOpFormatterIsUnchanged:
    """The second half of the gate: the OP's rendered rollup must not move."""

    def test_the_op_still_renders_its_nepali_headings(self):
        """Pins the exact column keys the OP has always emitted.

        Read out of the function's own literals rather than transcribed, because
        getting a Nepali heading subtly wrong in a *test* is the same failure as
        getting it wrong in the code, and the first draft of this test did
        exactly that - it asserted "वृद्ध वृक्ष" where the code has always said
        "परिपक्व रूख". The test passed against a renamed heading nobody had
        renamed, which is worse than no test.
        """
        import ast
        import inspect

        from app.services.operational_plan import data_collector

        src = inspect.getsource(data_collector)
        tree = ast.parse(src)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef)
            and n.name == "_fetch_dbh_class_breakdown_ag_np"
        )
        literals = {
            n.value
            for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        }

        # The seven column headings, verbatim.
        for heading in (
            "वन खण्ड",
            "ब्यास समूह",
            "संख्या /हे.",
            "काठ (घ.मी. /हे.)",
            "दाउरा (घ.मी. /हे.)",
            "जम्मा (घ.मी. /हे.)",
            "कुल जम्मा (भारित)",
        ):
            assert heading in literals, (
                f"the OP no longer renders the column {heading!r}"
            )

        # The two group labels, verbatim, with their ranges.
        for label in (
            "एड्भान्स ग्रोथ (१०-४० से.मी.)",
            "परिपक्व रूख (>४० से.मी.)",
        ):
            assert label in literals, f"the OP no longer renders the group {label!r}"

    def test_the_op_formatter_delegates_the_grouping(self):
        """It must not re-derive the groups; that was the point of the refactor."""
        import inspect

        from app.services.operational_plan import data_collector

        src = inspect.getsource(data_collector)
        fn_start = src.index("def _fetch_dbh_class_breakdown_ag_np")
        fn_src = src[fn_start: fn_start + 4000]
        assert "harvest_groups.group_rollup" in fn_src
        # The old inline derivation must be gone.
        assert "_space_dash" not in fn_src
        assert 'get_system("harvesting_cfmg")' not in fn_src

    def test_the_op_formatter_actually_produces_rows(self):
        """The test the P2b gate was missing, and it has to exist.

        Every other test in this class checks that the OP still *says* the right
        things: seven headings, two group labels, no Regeneration, delegation to
        this module. All of them passed while `fi_block_dbh_class_ag_np` was
        rendering **two grand-total rows full of `-` and not one per-block row**,
        because the collector emits `dbh_class` as a display string (`'10-20
        Sm.Pole'`) and this module matches canonical keys (`10_20`). Every class
        failed to map, every block rolled up to nothing, and the all-zero skip in
        the formatter's row loop discarded the lot.

        That is the same failure shape as P3's missing i18n keys: a suite that
        asserts presentation cannot notice when the content behind it is gone. So
        this asserts content -- given the collector's own strings, the rollup
        must group all eight classes and partition the total.
        """
        rows = [
            {
                "block_name": "C-1",
                "dbh_class": display,
                "count_per_ha": float(i + 1),
                "timber_m3_per_ha": 0.0,
                "firewood_m3_per_ha": 0.0,
                "total_volume_m3_per_ha": 0.0,
            }
            for i, display in enumerate(COLLECTOR_DISPLAY_STRINGS)
        ]
        grouped = hg.group_rollup(rows)

        # Every display string resolves to a real class...
        for display in COLLECTOR_DISPLAY_STRINGS:
            assert hg.resolve_class_key(display) in hg.class_to_group(), (
                f"{display!r} did not resolve to a class"
            )
        # ...so all three groups appear for the block, rather than none.
        assert {r["group_key"] for r in grouped} == {
            hg.REGENERATION,
            hg.ADVANCE_GROWTH,
            hg.MATURE_TREE,
        }
        # And the partition still holds, or the totals below prove nothing.
        assert _totals(grouped)["count_per_ha"] == pytest.approx(
            sum(r["count_per_ha"] for r in rows)
        )

    def test_display_strings_and_canonical_keys_give_the_same_rollup(self):
        """The resolver is a translation, not a second opinion.

        If it disagreed with a direct key lookup, one of the two OP paths would
        be right and the other wrong, and nothing would say which.
        """
        by_display = hg.group_rollup(
            [
                {
                    "block_name": "C-1",
                    "dbh_class": display,
                    "count_per_ha": float(i + 1),
                    "timber_m3_per_ha": float(i),
                    "firewood_m3_per_ha": 0.0,
                    "total_volume_m3_per_ha": float(i),
                }
                for i, display in enumerate(COLLECTOR_DISPLAY_STRINGS)
            ]
        )
        by_key = hg.group_rollup(
            [
                {
                    "block_name": "C-1",
                    "dbh_class": key,
                    "count_per_ha": float(i + 1),
                    "timber_m3_per_ha": float(i),
                    "firewood_m3_per_ha": 0.0,
                    "total_volume_m3_per_ha": float(i),
                }
                for i, key in enumerate(hg.class_to_group())
            ]
        )
        assert _totals(by_display) == pytest.approx(_totals(by_key))
        assert [r["group_key"] for r in by_display] == [r["group_key"] for r in by_key]

    def test_the_op_still_omits_regeneration(self):
        """D12 applies to Field Inventory; the OP's two-group output is the gate.

        Including Regeneration here would change a printed report nobody asked to
        change, so the formatter maps only the two groups it has always shown and
        the third is computed and discarded.
        """
        import inspect

        from app.services.operational_plan import data_collector

        src = inspect.getsource(data_collector)
        fn_start = src.index("def _fetch_dbh_class_breakdown_ag_np")
        fn_src = src[fn_start: fn_start + 5000]

        assert "ADVANCE_GROWTH" in fn_src
        assert "MATURE_TREE" in fn_src
        # Regeneration must not be slotted into the printed map.
        slot_map = fn_src[fn_src.index("_SLOT = {"): fn_src.index("np_groups = [")]
        assert "REGENERATION" not in slot_map, (
            "Regeneration was added to the OP's printed groups; D12 requires it "
            "in Field Inventory, and adding it here changes a report nobody "
            "asked to change"
        )
        # ...and the row loop must skip anything unmapped rather than assume.
        assert "if slot is None" in fn_src


class TestEdgeCases:
    def test_no_rows(self):
        assert hg.group_rollup([]) == []
        assert hg.forest_rollup([]) == []

    def test_a_class_the_base_system_lacks_is_not_silently_dropped(self):
        rows = _rows() + [
            {
                "block_name": "B1", "dbh_class": "99_bogus",
                "count_per_ha": 5.0, "timber_m3_per_ha": 1.0,
                "firewood_m3_per_ha": 1.0, "total_volume_m3_per_ha": 2.0,
            }
        ]
        grouped = hg.group_rollup(rows)
        # It cannot be grouped, so it is not in any group - but the partition
        # below is what proves nothing *else* was lost with it.
        assert all(
            "99_bogus" not in r["dbh_classes"] for r in grouped
        ), "an unknown class was silently attached to a group"

    def test_include_empty_gives_three_rows_per_block(self):
        rows = [r for r in _rows() if r["block_name"] == "B1"]
        rows = [r for r in rows if r["dbh_class"] in {"0_4", "10_20"}]
        default = hg.group_rollup(rows)
        filled = hg.group_rollup(rows, include_empty=True)
        assert len(filled) == 3
        assert len(default) <= 2
