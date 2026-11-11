"""Unit tests for the sampling area-basis helpers (Phase D.2)."""
import pytest

from app.services.sampling import area_basis_from_filter, low_tree_cover_coverage


class _FakeBlock:
    def __init__(self, name, area, accessible):
        self.block_name = name
        self.block_area_hectares = area
        self.accessible_forest_area_ha = accessible


class TestAreaBasisFromFilter:
    def test_tree_cover_when_filtering_on(self):
        assert area_basis_from_filter(True) == "tree_cover"

    def test_full_area_when_filtering_off(self):
        assert area_basis_from_filter(False) == "full_area"


class TestLowTreeCoverCoverage:
    def test_returns_empty_for_full_area_basis(self):
        blocks = [
            {"block_name": "Block A", "block_area_hectares": 10, "accessible_forest_area_ha": 10},
            {"block_name": "Block B", "block_area_hectares": 1, "accessible_forest_area_ha": 1},
        ]
        assert low_tree_cover_coverage(blocks) == []

    def test_returns_low_coverage_names_for_models(self):
        blocks = [
            _FakeBlock("Block A", 10, 9.5),
            _FakeBlock("Block B", 10, 1.0),
            _FakeBlock("Block C", 5, 0.2),
        ]
        assert low_tree_cover_coverage(blocks) == ["Block B", "Block C"]

    def test_custom_threshold(self):
        blocks = [
            {"block_name": "Block A", "block_area_hectares": 100, "accessible_forest_area_ha": 25},
        ]
        assert low_tree_cover_coverage(blocks, threshold_percent=30.0) == ["Block A"]
        assert low_tree_cover_coverage(blocks, threshold_percent=20.0) == []

    def test_handles_missing_or_invalid_fields(self):
        blocks = [
            {"block_area_hectares": 0},
            {"block_name": "Odd", "block_area_hectares": "bad", "accessible_forest_area_ha": 1},
            _FakeBlock("None", None, 5),
        ]
        assert low_tree_cover_coverage(blocks) == []

    def test_handles_blank_names(self):
        blocks = [
            {"block_name": "", "block_area_hectares": 10, "accessible_forest_area_ha": 0.5},
        ]
        assert low_tree_cover_coverage(blocks) == []