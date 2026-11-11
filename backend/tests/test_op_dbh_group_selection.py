"""The OP's harvest tables must select classes from the registry, not restate them.

DBH_SSOT follow-up to the P2b regression (`d0b2f14`). While fixing that, a
second copy of the class list turned up in the same module:
`_fetch_dbh_class_breakdown_advance_np` and `_fetch_dbh_class_breakdown_mature_np`
each passed a literal set of the collector's *display* class names --
`{"10-20 Sm.Pole", "20-30 Lg.Pole", "30-40 Sm.Tree"}` and its mature equivalent.
Correct today, and silently wrong the day a class is renamed or CFMG moves a
boundary, with nothing to say so.

These tests are source-level on purpose. A seeded end-to-end test would prove the
formatters agree with the registry on one fixture's data; what actually needs
locking is that they *cannot* disagree, because they no longer contain the list.
The last test closes the loop the hardcoded sets were breaking: it takes the
labels the collector really emits, resolves each one through the registry, and
asserts the resulting groups are the two the tables claim to show.
"""

from __future__ import annotations

import ast
import inspect
import re

import pytest

from app.core import harvest_groups as hg
from app.services.operational_plan import data_collector as dc

# The collector's display labels, as its own source writes them. A class list, so
# the thing under test is that no *other* file has to repeat it.
COLLECTOR_LABELS = {
    "0-4 Seedling",
    "4-10 Sapling",
    "10-20 Sm.Pole",
    "20-30 Lg.Pole",
    "30-40 Sm.Tree",
    "40-50 Med.Tree",
    "50-60 Lg.Tree",
    "60+ V.Lg.Tree",
}

# A DBH class label as the collector writes one: a range, then a name. Matched
# loosely on purpose -- the point is to catch *any* restated class list, so a
# stricter pattern would only make the lock easier to walk around.
LABEL_LITERAL = re.compile(r"['\"][0-9]{1,2}\+?\s?[-+]\s?[0-9]{1,2}\+?\s[^'\"]+['\"]")


_MODULE_SRC = inspect.getsource(dc)


def _fn(name: str) -> ast.FunctionDef:
    tree = ast.parse(_MODULE_SRC)
    return next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == name
    )


def _fn_src(name: str) -> str:
    """The function's own source.

    `inspect.getsource` will not take an `ast.FunctionDef`, and `ast.unparse` is
    worse here: it drops comments, and the comments are where a half-finished
    removal hides -- a class set left behind in a docstring reads as
    documentation and becomes the thing the next reader trusts.
    """
    segment = ast.get_source_segment(_MODULE_SRC, _fn(name))
    assert segment, f"could not locate the source of {name}"
    return segment


class TestTheGroupTablesNoLongerRestateTheClasses:
    @pytest.mark.parametrize(
        "fn_name",
        ["_fetch_dbh_class_breakdown_advance_np", "_fetch_dbh_class_breakdown_mature_np"],
    )
    def test_it_passes_a_group_key_not_a_class_set(self, fn_name):
        """The signature is the lock. A `class_set` parameter cannot be filled from
        the registry, so requiring the opposite makes the regression unrepresentable
        rather than merely discouraged."""
        fn = _fn(fn_name)
        args = [a.arg for a in fn.args.args]
        assert "class_set" not in args, f"{fn_name} still takes a class_set"
        # It forwards a bare name, and that name must be a group key.
        forwarded = [
            n.value
            for n in ast.walk(fn)
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "harvest_groups"
        ]
        assert forwarded, f"{fn_name} forwards no harvest_groups constant"

    def test_the_helper_selects_by_group_not_membership(self):
        fn = _fn("_fetch_dbh_class_breakdown_single_np")
        assert "class_to_group" in _fn_src("_fetch_dbh_class_breakdown_single_np"), (
            "the helper must resolve each row's class and compare groups, rather "
            "than testing membership of a literal set"
        )

    def test_no_dbh_class_label_is_retyped_outside_the_mapping(self):
        """The only place a class label may be written is the collector's own
        Excel-pivot mapping, which is presentation. Everywhere else it must be
        resolved.

        Scoped to the three formatters, because the mapping function legitimately
        contains all eight. A repo-wide scan here would flag that function and
        then get switched off, which is the fate of every over-broad lock.
        """
        offenders = []
        for fn_name in (
            "_fetch_dbh_class_breakdown_advance_np",
            "_fetch_dbh_class_breakdown_mature_np",
            "_fetch_dbh_class_breakdown_single_np",
        ):
            for hit in LABEL_LITERAL.findall(_fn_src(fn_name)):
                offenders.append(f"{fn_name}: {hit}")
        assert not offenders, "a DBH class label is retyped here:\n  " + "\n  ".join(offenders)

    def test_the_docstrings_no_longer_show_the_old_class_set(self):
        # The removal is easy to half-do: leave the set in a docstring, where it
        # reads as documentation and quietly becomes the thing a reader trusts.
        for fn_name in (
            "_fetch_dbh_class_breakdown_advance_np",
            "_fetch_dbh_class_breakdown_mature_np",
        ):
            assert not LABEL_LITERAL.search(_fn_src(fn_name))


class TestEveryClassHasANepaliWord:
    """The D4 join, on the side that has no i18n bundle behind it.

    The OP's Nepali output is formatted in Python, so its translations live in
    `np_label_map` rather than in a locale file. That map was keyed by the
    collector's display label -- a fifth copy of the class list -- and a class
    added to the database would have rendered as its raw English label with
    nothing to report it. Keyed canonically, the same omission is a failing
    assertion instead of a silent English word in a Nepali report.
    """

    @staticmethod
    def _np_label_map() -> dict[str, str]:
        fn = _fn("_fetch_dbh_class_breakdown_np")
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "np_label_map" for t in node.targets
            ):
                return ast.literal_eval(node.value)
        raise AssertionError("np_label_map not found")

    def test_it_is_keyed_by_canonical_class_key(self):
        keys = set(self._np_label_map())
        assert keys == set(hg.class_to_group()), (
            "the Nepali map and the base system disagree on which classes exist; "
            f"map-only={keys - set(hg.class_to_group())} "
            f"system-only={set(hg.class_to_group()) - keys}"
        )

    def test_every_value_is_a_real_word_not_a_key(self):
        for key, word in self._np_label_map().items():
            assert word.strip(), f"{key} has no Nepali label"
            assert word != key, f"{key} renders as its own key"

    def test_no_display_label_is_used_as_a_key(self):
        for key in self._np_label_map():
            assert key in hg.class_to_group(), (
                f"{key!r} is a display label, not a class key; the map is meant to "
                "be keyed canonically so a renamed label cannot orphan a class"
            )


class TestTheLabelsResolveToTheGroupsTheTablesClaim:
    """The loop the hardcoded sets were breaking, checked end to end.

    collector label -> `resolve_class_key` -> `class_to_group` -> the group the
    two single-group tables say they show. If a label is renamed, or the mapping
    stops producing one, this fails; if CFMG moves a boundary, the expected group
    set moves with it and the assertion follows rather than drifting.
    """

    def test_every_collector_label_resolves(self):
        resolved = {label: hg.resolve_class_key(label) for label in COLLECTOR_LABELS}
        missing = {k: v for k, v in resolved.items() if v is None}
        assert not missing, f"collector labels that resolve to no class: {missing}"

    def test_the_labels_cover_the_whole_base_system(self):
        resolved = {hg.resolve_class_key(label) for label in COLLECTOR_LABELS}
        assert resolved == set(hg.class_to_group()), (
            "the collector's labels and the base system disagree; every class must "
            "be labelable and every label must be a class"
        )

    def test_the_two_tables_cover_exactly_the_harvestable_groups(self):
        group_of = hg.class_to_group()
        resolved = {hg.resolve_class_key(label): label for label in COLLECTOR_LABELS}
        advance = {resolved[k] for k, g in group_of.items() if g == hg.ADVANCE_GROWTH}
        mature = {resolved[k] for k, g in group_of.items() if g == hg.MATURE_TREE}
        assert advance == {"10-20 Sm.Pole", "20-30 Lg.Pole", "30-40 Sm.Tree"}
        assert mature == {"40-50 Med.Tree", "50-60 Lg.Tree", "60+ V.Lg.Tree"}
        # And Regeneration belongs to neither, which is why the two single-group
        # tables need no exclusion of their own.
        assert not {resolved[k] for k, g in group_of.items() if g == hg.REGENERATION} & (
            advance | mature
        )
