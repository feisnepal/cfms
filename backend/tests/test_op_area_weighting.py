"""The OP grand total is an area-weighted mean over *every* block in the table.

DBH_SSOT P6. Two things here were wrong before, and they are wrong in opposite
directions, which is why both had to be pinned.

1. The grand total was weighted by **sample-plot count**. That is a
   sampling-intensity mean, not a forest mean, and it is not what the column
   ("कुल जम्मा (भारित)", per-hectare) claimed to be. On the owner's forest plot
   density varies 13-fold, so the intensively-sampled compartments carried up to
   14 times the weight per hectare of the rest.

2. The first attempt at the area-weighted version then **inflated** Mature Tree by
   12% (87.32 against a correct 78.16) -- a bug introduced by the change itself.
   The single-group table only had the blocks that actually hold stems of the
   group in its `block_order`, and dividing by those areas quietly left the
   zero-stem hectares out of the denominator. A compartment with no mature stems
   still occupies land, and that land belongs in a forest-wide rate. The helper
   therefore takes `denominator_blocks` separately from the blocks that supply
   the numerator, and the test below is mostly about that one argument.
"""

from __future__ import annotations

import pytest

from app.services.operational_plan.data_collector import (
    _OP_GT_MEASURES,
    _area_weighted_grand_total,
    _weighted_mean,
)


def _bd(**blocks):
    """block_data shaped as the formatters build it: block -> slot -> measures."""
    return {
        bn: {slot: {m: 0.0 for m in _OP_GT_MEASURES} for slot in slots}
        for bn, slots in blocks.items()
    }


class TestTheWeighting:
    def test_equal_areas_give_the_plain_mean(self):
        bd = _bd(A=("g",), B=("g",))
        bd["A"]["g"]["tot"] = 10.0
        bd["B"]["g"]["tot"] = 20.0
        grand, skipped = _area_weighted_grand_total(
            bd, ["A", "B"], ("g",), {"A": 5.0, "B": 5.0}
        )
        assert grand["g"]["tot"] == pytest.approx(15.0)
        assert skipped == []

    def test_unequal_areas_pull_the_mean_toward_the_bigger_block(self):
        bd = _bd(A=("g",), B=("g",))
        bd["A"]["g"]["tot"] = 10.0
        bd["B"]["g"]["tot"] = 20.0
        grand, _ = _area_weighted_grand_total(
            bd, ["A", "B"], ("g",), {"A": 1.0, "B": 9.0}
        )
        # (10*1 + 20*9) / 10 = 19
        assert grand["g"]["tot"] == pytest.approx(19.0)

    def test_slots_do_not_leak_into_each_other(self):
        bd = _bd(A=("ag", "mt"))
        bd["A"]["ag"]["tot"] = 100.0
        bd["A"]["mt"]["tot"] = 7.0
        grand, _ = _area_weighted_grand_total(
            bd, ["A"], ("ag", "mt"), {"A": 2.0}
        )
        assert grand["ag"]["tot"] == pytest.approx(100.0)
        assert grand["mt"]["tot"] == pytest.approx(7.0)

    def test_all_four_measures_are_carried(self):
        bd = _bd(A=("g",))
        for i, m in enumerate(_OP_GT_MEASURES):
            bd["A"]["g"][m] = float(i + 1)
        grand, _ = _area_weighted_grand_total(bd, ["A"], ("g",), {"A": 3.0})
        for i, m in enumerate(_OP_GT_MEASURES):
            assert grand["g"][m] == pytest.approx(float(i + 1))


class TestTheDenominatorCoversEveryBlock:
    """The regression: a block with no stems still owns hectares."""

    def test_a_stemless_block_lowers_the_mean_rather_than_being_ignored(self):
        bd = _bd(A=("g",), B=("g",))
        bd["A"]["g"]["tot"] = 100.0
        # B holds no stems of this group, so it supplies nothing to the numerator.
        grand, _ = _area_weighted_grand_total(
            bd,
            ["A"],
            ("g",),
            {"A": 10.0, "B": 90.0},
            denominator_blocks=["A", "B"],
        )
        # 100*10 / (10+90) = 10, not 100/10 = 100.
        assert grand["g"]["tot"] == pytest.approx(10.0)

    def test_omitting_it_from_the_denominator_would_inflate_it(self):
        """The bug, stated as a test, so the wrong version cannot pass quietly."""
        bd = _bd(A=("g",), B=("g",))
        bd["A"]["g"]["tot"] = 100.0
        inflated, _ = _area_weighted_grand_total(
            bd, ["A"], ("g",), {"A": 10.0, "B": 90.0}
        )
        correct, _ = _area_weighted_grand_total(
            bd,
            ["A"],
            ("g",),
            {"A": 10.0, "B": 90.0},
            denominator_blocks=["A", "B"],
        )
        assert inflated["g"]["tot"] == pytest.approx(100.0)
        assert correct["g"]["tot"] == pytest.approx(10.0)
        assert correct["g"]["tot"] < inflated["g"]["tot"]

    def test_denominator_defaults_to_the_numerator_blocks(self):
        bd = _bd(A=("g",), B=("g",))
        bd["A"]["g"]["tot"] = 10.0
        bd["B"]["g"]["tot"] = 20.0
        with_default, _ = _area_weighted_grand_total(
            bd, ["A", "B"], ("g",), {"A": 1.0, "B": 1.0}
        )
        without, _ = _area_weighted_grand_total(
            bd, ["A", "B"], ("g",), {"A": 1.0, "B": 1.0}, denominator_blocks=["A", "B"]
        )
        assert with_default["g"]["tot"] == pytest.approx(without["g"]["tot"])


class TestBlocksWithNoArea:
    def test_they_are_reported_rather_than_silently_dropped(self):
        bd = _bd(A=("g",), B=("g",))
        bd["A"]["g"]["tot"] = 10.0
        grand, skipped = _area_weighted_grand_total(
            bd, ["A", "B"], ("g",), {"A": 5.0}
        )
        assert skipped == ["B"]
        # And it is excluded from the mean, since its area is unknown.
        assert grand["g"]["tot"] == pytest.approx(10.0)

    def test_no_areas_at_all_yields_zeros_so_the_caller_emits_nothing(self):
        bd = _bd(A=("g",))
        bd["A"]["g"]["tot"] = 50.0
        grand, skipped = _area_weighted_grand_total(bd, ["A"], ("g",), {})
        assert grand["g"]["tot"] == 0.0
        assert skipped == ["A"]
        # A zero here is the signal the callers use to skip the row entirely,
        # rather than print a total derived from nothing.
        assert not any(any(v for v in g.values()) for g in grand.values())

    def test_an_explicit_zero_area_counts_as_missing(self):
        bd = _bd(A=("g",), B=("g",))
        bd["A"]["g"]["tot"] = 10.0
        grand, skipped = _area_weighted_grand_total(
            bd, ["A", "B"], ("g",), {"A": 4.0, "B": 0.0}
        )
        assert skipped == ["B"]
        assert grand["g"]["tot"] == pytest.approx(10.0)


class TestThePrimitive:
    """`_weighted_mean` -- the one weighted mean, both call sites go through it.

    P6b generalised P6's helper rather than adding a second, because D11's whole
    claim is that one method is used everywhere. Its denominator semantics are
    therefore worth pinning directly, not only through the wrapper.
    """

    def test_equal_weights_give_the_plain_mean(self):
        assert _weighted_mean({"A": 10.0, "B": 20.0}, {"A": 1.0, "B": 1.0}) == pytest.approx(15.0)

    def test_weights_pull_the_mean(self):
        assert _weighted_mean({"A": 10.0, "B": 20.0}, {"A": 1.0, "B": 9.0}) == pytest.approx(19.0)

    def test_a_block_in_the_denominator_but_not_in_values_counts_as_zero(self):
        # The whole point of the separate argument: no stems, but still hectares.
        assert _weighted_mean(
            {"A": 100.0}, {"A": 10.0, "B": 90.0}, ["A", "B"]
        ) == pytest.approx(10.0)

    def test_a_block_in_values_but_outside_the_denominator_is_ignored(self):
        assert _weighted_mean(
            {"A": 10.0, "Z": 999.0}, {"A": 1.0, "Z": 50.0}, ["A"]
        ) == pytest.approx(10.0)

    def test_no_positive_weight_gives_zero_rather_than_a_division_error(self):
        assert _weighted_mean({"A": 10.0}, {"A": 0.0}) == 0.0
        assert _weighted_mean({"A": 10.0}, {}) == 0.0
        assert _weighted_mean({}, {}) == 0.0

    def test_none_values_are_treated_as_zero(self):
        assert _weighted_mean({"A": None, "B": 20.0}, {"A": 1.0, "B": 1.0}) == pytest.approx(10.0)

    def test_individual_weights_are_not_clamped_but_a_nonpositive_total_is(self):
        """Two separate guarantees, and conflating them hides a real one.

        A *negative* individual weight is not clamped -- nothing in the data
        should produce one, so a bad area should show up as a wrong figure rather
        than a plausible one. But a *non-positive total* returns 0.0, which is the
        divide-by-zero guard and is deliberate: a forest whose areas sum to zero
        has no mean, and returning 0.0 is what makes the caller emit no row rather
        than print a number derived from nothing.

        The first draft of this test asserted `{"A": 1.0, "B": -1.0}` averages to
        -5.0, and got 0.0 -- because that pair sums to zero and took the guard. The
        test was wrong, not the code.
        """
        # Total stays positive, so the value is really used, negative and all:
        assert _weighted_mean({"A": 10.0, "B": 20.0}, {"A": 1.0, "B": -0.5}) == pytest.approx(0.0)
        # Total is zero: the guard, not an average.
        assert _weighted_mean({"A": 10.0, "B": 20.0}, {"A": 1.0, "B": -1.0}) == 0.0
        assert _weighted_mean({"A": 10.0, "B": 20.0}, {"A": -1.0, "B": -1.0}) == 0.0


class TestPlotWeightingIsGone:
    def test_the_helpers_do_not_mention_plots(self):
        """D11 says one method. A plot count creeping back in is the regression.

        Checked over **identifiers only**, via `tokenize`, with comments and string
        literals dropped. Both exclusions are deliberate and each one was earned:

        * The docstring has to be able to say what the weighting replaced, or
          nobody reading it later can tell a decision from an accident. The first
          version matched the whole source and went red on its own explanation.
        * So do the comments recording the change. A comment saying "was weighted
          by sample-plot count" is the most useful line in the function, and a
          lock that forbids it would push the history out of the code.

        That leaves an identifier containing "plot" as the only thing that can fail
        this, which is exactly the regression: a `block_plot_counts` dict or a
        `total_plots` denominator coming back.
        """
        import inspect
        import io
        import textwrap
        import tokenize

        from app.services.operational_plan import data_collector as dc

        for name in (
            "_area_weighted_grand_total",
            "_fetch_dbh_class_breakdown_ag_np",
            "_fetch_dbh_class_breakdown_single_np",
        ):
            src = textwrap.dedent(inspect.getsource(getattr(dc, name)))
            names = [
                tok.string
                for tok in tokenize.generate_tokens(io.StringIO(src).readline)
                if tok.type in (tokenize.NAME, tokenize.NUMBER)
            ]
            offenders = sorted({n for n in names if "plot" in n.lower()})
            assert not offenders, (
                f"{name} weights by plots again ({offenders}); the weighting must be "
                "area only (D11)"
            )

    def test_the_three_harvest_tables_all_take_block_areas(self):
        import inspect

        from app.services.operational_plan import data_collector as dc

        for name in (
            "_fetch_dbh_class_breakdown_ag_np",
            "_fetch_dbh_class_breakdown_advance_np",
            "_fetch_dbh_class_breakdown_mature_np",
            "_fetch_dbh_class_breakdown_single_np",
        ):
            params = list(inspect.signature(getattr(dc, name)).parameters)
            assert "block_areas" in params, f"{name} still takes no areas"
            assert "class_set" not in params, f"{name} still takes a class set"
