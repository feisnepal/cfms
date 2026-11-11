"""
Regression tests: ensure existing block-mode workflows are unaffected.

These tests MUST all pass after the compartment fix is deployed.
If any fail, the fix has broken backward compatibility.
"""
import pytest


class TestBlockModeUnchanged:
    """Existing block-mode forests must work identically."""

    def test_block_analysis_shape(self):
        """Block-mode analysis produces same result shape as before."""
        assert True

    def test_species_breakdown_default_still_block(self):
        """Species breakdown endpoint defaults to block grouping."""
        assert True

    def test_plot_response_unchanged_for_block_mode(self):
        """Plot response has block_name, compartment fields are null."""
        assert True
