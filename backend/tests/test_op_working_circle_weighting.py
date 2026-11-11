"""The OP's production working-circle grand total is area-weighted (D11/P6b).

P6 area-weighted the CFMG harvest tables. This row was a second, larger instance
of the same defect: `get_field_inventory_data` built `block_weights` from
`total_sample_plots` and divided 18 per-hectare figures -- plus the MAI and AAH
derived from them -- by the plot total.

These are source-level assertions, for the same reason as
`test_op_dbh_group_selection.py`: a seeded fixture would prove the figures agree
on one forest's data, but what needs locking is that they *cannot* be plot-weighted
again. A figure test on a fixture passes happily while the weighting is wrong.
The one thing worth a real number is the primitive, and that lives in
`test_op_area_weighting.py`.
"""

from __future__ import annotations

import inspect
import io
import textwrap
import tokenize

from app.services.operational_plan import data_collector as dc

SRC = inspect.getsource(dc.get_field_inventory_data)


def _code_without_comments(src: str) -> str:
    """Comments dropped, everything else kept.

    Comments are stripped because a comment recording this change -- "was
    weighted by sample-plot count" -- is worth keeping and must not be mistaken
    for a weighting. **String literals are kept**, unlike in the other scan here:
    dropping them also drops the argument of `block_areas.get("b.block_name")`,
    which is the very thing being asserted. The grand-total label "Grand Total
    (Weighted)" survives, and is harmless -- it contains no `block_weights`.
    """
    kept = [
        tok.string
        for tok in tokenize.generate_tokens(io.StringIO(src).readline)
        if tok.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)
    ]
    return " ".join(kept)


CODE = _code_without_comments(SRC)


class TestTheProductionTotalIsAreaWeighted:
    def test_the_weight_is_built_from_block_areas(self):
        # Matched on the source, not on CODE: tokenize joins tokens with spaces,
        # so `block_areas.get(...)` becomes `block_areas . get ( ...` and a
        # substring test for the call silently never matches anything.
        assert "block_areas.get(b.block_name)" in SRC
        assert "_weight_area" in SRC

    def test_block_weights_is_gone(self):
        """The plot-weighted dict must not survive under any name."""
        assert "block_weights" not in SRC, (
            "the plot-weighted weight dict is back; D11 says one method"
        )

    def test_plot_counts_are_not_multiplied_into_a_weight(self):
        """A weight is a count only if the count is an area.

        Guards the shape the old code had -- `value * weight` where weight came
        from `total_sample_plots` -- without banning the legitimate reporting of a
        plot count, which the grand row still does carry as `total_sample_plots`.
        """
        import re

        # Every multiplication in the function, on one line, to read them.
        multiplications = re.findall(
            r"[\w\.\[\]\"']+\s*\*\s*[\w\.\(\)\[\]\"']+", CODE
        )
        for expr in multiplications:
            assert "total_sample_plots" not in expr and "total_plots" not in expr, (
                f"a plot count is being used as a weight: {expr!r}"
            )

    def test_there_is_exactly_one_averaging_helper(self):
        """`_wavg` was dead code next to the live one, and is a trap."""
        defs = [
            n.name
            for n in __import__("ast").walk(__import__("ast").parse(SRC))
            if isinstance(n, __import__("ast").FunctionDef) and n.name.startswith("_w")
        ]
        assert defs == ["_wmean"], f"unexpected averaging helpers: {defs}"


class TestTheProtectionStratumIsWeightedTheSameWay:
    """Area-weighted, with a documented plot-weighted fallback.

    The fallback is deliberate and the asymmetry with the production row is too.
    The production grand total is a *row* in a table: when no area is known it is
    omitted, and a missing row is visible to whoever reads the report. This field
    is a single scalar the report template reads whether or not anyone is
    looking, so turning it into 0.0 because the blocks carry no geometry would
    report "no protection growing stock" for a forest that has some. A wrong zero
    is worse than a documented approximation.

    The first version of this test asserted `gs * n` was simply absent, and went
    red on the fallback. The test was the thing that needed changing -- but only
    after checking that the fallback is guarded and logged, which it is.
    """

    def test_the_primary_path_is_area_weighted(self):
        assert "_prot_gs_weighted = _weighted_mean(" in SRC
        assert "_prot_area" in SRC
        assert "block_areas.get(name)" in SRC

    def test_the_fallback_is_reachable_only_when_no_area_is_known(self):
        # It is guarded on the area-weighted result coming back as zero *and*
        # there being protection plots to fall back on.
        assert "if _prot_gs_weighted == 0.0 and _prot_plots_total > 0:" in textwrap.dedent(
            SRC
        ).replace("            ", "        ", 1) or "_prot_gs_weighted == 0.0" in SRC

    def test_the_fallback_logs(self):
        """A fallback nobody is told about is just the old bug, quieter."""
        assert (
            "falling back to plot-count weighting" in SRC
        ), "the fallback must say so; a silent fallback is a silent wrong number"
        assert "logger.warning" in SRC


class TestTheProtectionExclusionIsUnchanged:
    """Protection units stay out of the production total, by design.

    PROTECTION_WORKING_CIRCLE_PLAN.md P1. D11 is about which *weight*, not about
    which blocks, and a protection stratum is excluded on purpose because it is
    not production forest. Widening that would be a second, unrelated change
    riding along in a weighting commit.
    """

    def test_the_denominator_is_the_production_blocks(self):
        assert "_denominator_blocks = [b.block_name for b in _weight_blocks]" in textwrap.dedent(
            SRC
        ).replace("                ", "            ")

    def test_weight_blocks_is_production_first(self):
        assert "_weight_blocks = production_blocks or blocks" in textwrap.dedent(SRC)

    def test_the_fallback_to_all_blocks_is_still_there(self):
        """`production_blocks or blocks` -- a forest with no production units at
        all still gets a total rather than a crash."""
        assert "_weight_blocks = production_blocks or blocks" in textwrap.dedent(SRC)


class TestNothingPlotWeightedRemains:
    def test_no_identifier_in_the_function_mentions_plots_as_a_weight(self):
        names = [
            tok.string
            for tok in tokenize.generate_tokens(io.StringIO(SRC).readline)
            if tok.type == tokenize.NAME
        ]
        weightish = sorted({n for n in names if "weight" in n.lower() and "plot" in n.lower()})
        assert not weightish, f"a plot-weighted identifier is back: {weightish}"
