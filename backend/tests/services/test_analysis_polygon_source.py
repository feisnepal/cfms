"""Tests for the polygon source strategy pattern."""
import pytest
from app.services.analysis_polygon_source import (
    BlockPolygonSource,
    CompartmentPolygonSource,
    PolygonSource,
)


class TestBlockPolygonSource:
    def test_returns_blocks_from_result_data(self):
        result_data = {
            "blocks": [
                {"block_name": "Block 1", "geometry": {"type": "Polygon"}, "area_hectares": 10},
            ]
        }
        source = BlockPolygonSource(result_data)
        polygons = source.get_polygons()
        assert len(polygons) == 1
        assert polygons[0]["block_name"] == "Block 1"

    def test_returns_empty_when_no_blocks(self):
        source = BlockPolygonSource({})
        polygons = source.get_polygons()
        assert polygons == []


class TestCompartmentPolygonSource:
    def test_returns_compartments(self):
        result_data = {
            "compartments": [
                {"name": "Comp 1", "compartment_code": "C1", "is_compartment": True},
            ]
        }
        source = CompartmentPolygonSource(result_data)
        polygons = source.get_polygons()
        assert len(polygons) == 1
        assert polygons[0]["compartment_code"] == "C1"

    def test_falls_back_to_blocks_when_no_compartments(self):
        result_data = {
            "blocks": [
                {"block_name": "Block 1", "geometry": {"type": "Polygon"}},
            ]
        }
        source = CompartmentPolygonSource(result_data)
        polygons = source.get_polygons()
        assert len(polygons) == 1

    def test_returns_empty_when_no_data(self):
        source = CompartmentPolygonSource({})
        polygons = source.get_polygons()
        assert polygons == []


class TestPolygonSourceFactory:
    def test_for_result_data_uses_block_source(self):
        source = PolygonSource.for_result_data({"blocks": []})
        assert isinstance(source, BlockPolygonSource)

    def test_for_result_data_uses_compartment_source(self):
        source = PolygonSource.for_result_data({"compartments": [{"name": "C1"}]})
        assert isinstance(source, CompartmentPolygonSource)

    def test_for_result_data_defaults_to_block(self):
        source = PolygonSource.for_result_data({})
        assert isinstance(source, BlockPolygonSource)

    def test_for_result_data_none(self):
        source = PolygonSource.for_result_data(None)
        assert isinstance(source, BlockPolygonSource)

    def test_has_compartments_true(self):
        assert PolygonSource.has_compartments({"compartments": [{}]}) is True

    def test_has_compartments_false(self):
        assert PolygonSource.has_compartments({"blocks": []}) is False

    def test_has_compartments_none(self):
        assert PolygonSource.has_compartments(None) is False
