"""H3.5 — a partial calculation is never reported as `completed` (S2-37).

The report calls this the most insidious defect category in the codebase, and
the reasoning is what these tests protect: in a geospatial pipeline a swallowed
exception does not produce an error, it produces a plausible-looking wrong
number. `analysis.py` deliberately continues past a failed block so one failure
does not discard the rest — and the pipeline then wrote `completed` regardless,
making a partial result indistinguishable from a whole one, in a document with
regulatory standing.
"""
import pytest

from app.services.calculation_integrity import (
    ERROR_MARKER,
    failed_units,
    partial_failure_reason,
)


def block(name: str, error: str | None = None) -> dict:
    unit = {"name": name, "area_hectares": 12.5}
    if error:
        unit[ERROR_MARKER] = error
    return unit


class TestDetection:
    def test_a_whole_result_reports_nothing(self):
        data = {"blocks": [block("Block 1"), block("Block 2")]}
        assert partial_failure_reason(data) is None
        assert failed_units(data) == []

    def test_one_failed_unit_is_caught(self):
        data = {"blocks": [block("Block 1"), block("Block 2", "CRS transform failed")]}
        assert partial_failure_reason(data) is not None

    def test_compartments_are_checked_too(self):
        """`get_metadata_key()` returns blocks OR compartments by dimension mode."""
        data = {"compartments": [block("Cmt 1", "area computation failed")]}
        assert partial_failure_reason(data) is not None

    def test_sub_compartments_are_checked_too(self):
        data = {"sub_compartments": [block("Sub 1", "boom")]}
        assert partial_failure_reason(data) is not None

    def test_failures_across_collections_are_all_counted(self):
        data = {
            "blocks": [block("B1", "x"), block("B2")],
            "compartments": [block("C1", "y")],
        }
        assert len(failed_units(data)) == 2

    @pytest.mark.parametrize("data", [None, {}, {"blocks": []}, {"blocks": "not-a-list"}])
    def test_malformed_input_is_not_a_failure(self, data):
        """A detector that crashes on odd input would fail every calculation."""
        assert partial_failure_reason(data) is None


class TestTheMessage:
    def test_names_the_units_not_just_the_count(self):
        """"3 blocks failed" sends somebody to the logs; naming them does not."""
        data = {"blocks": [block("Block 4", "boom"), block("Block 7", "boom"), block("Block 9")]}
        msg = partial_failure_reason(data)
        assert "Block 4" in msg and "Block 7" in msg

    def test_gives_the_scope(self):
        data = {"blocks": [block("B1", "boom"), block("B2"), block("B3")]}
        assert "1 of 3" in partial_failure_reason(data)

    def test_carries_the_first_underlying_error(self):
        data = {"blocks": [block("B1", "ST_Transform: invalid SRID 9999")]}
        assert "invalid SRID 9999" in partial_failure_reason(data)

    def test_long_lists_are_summarised_rather_than_dumped(self):
        data = {"blocks": [block(f"B{i}", "boom") for i in range(12)]}
        msg = partial_failure_reason(data)
        assert "and 7 more" in msg
        assert len(msg) < 600

    def test_says_why_it_is_failed_rather_than_completed(self):
        """The message is read by whoever opens a calculation and finds it failed."""
        data = {"blocks": [block("B1", "boom")]}
        msg = partial_failure_reason(data)
        assert "failed rather than completed" in msg


class TestUnnamedUnits:
    def test_falls_back_to_a_position_when_there_is_no_name(self):
        data = {"blocks": [{"analysis_error": "boom"}]}
        assert "#1" in partial_failure_reason(data)

    def test_uses_block_name_when_name_is_absent(self):
        data = {"blocks": [{"block_name": "Ward 3 Block", "analysis_error": "boom"}]}
        assert "Ward 3 Block" in partial_failure_reason(data)


class TestRunnerIntegration:
    def test_the_runner_raises_a_distinct_type(self):
        """So the failure path can tell a broken pipeline from an incomplete one."""
        from app.services.calculation_runner import PartialCalculationError

        assert issubclass(PartialCalculationError, Exception)

    def test_the_check_runs_after_result_data_is_assigned(self):
        """Partial results must survive the failure — somebody has to see them.

        The runner assigns `calc.result_data` and only then raises, so the
        existing failure handler commits the partial data alongside the failed
        status. If the raise moved above the assignment, a failed calculation
        would carry nothing at all.
        """
        import inspect

        from app.services import calculation_runner

        src = inspect.getsource(calculation_runner.run_calculation_task)
        assign = src.index("calc.result_data = updated_result_data")
        raise_at = src.index("raise PartialCalculationError")
        assert assign < raise_at, "the partial-failure raise must come after result_data is stored"
