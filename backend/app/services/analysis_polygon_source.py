"""Strategy pattern for block vs compartment polygon sources in analysis.

Provides BlockPolygonSource and CompartmentPolygonSource strategies
so that analyze_block_geometry() can operate on any polygon regardless
of whether the forest uses blocks or compartments.

Usage:
    source = PolygonSource.for_result_data(result_data)
    for polygon in source.get_polygons():
        ...
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class PolygonSource(ABC):
    """Abstract strategy for providing polygon geometries to analysis."""

    @abstractmethod
    def get_polygons(self) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def get_metadata_key(self) -> str:
        ...

    @classmethod
    def for_result_data(
        cls,
        result_data: Optional[Dict[str, Any]],
    ) -> "PolygonSource":
        """Select strategy based on compartment existence in result_data.

        If compartments exist in result_data, returns CompartmentPolygonSource.
        Otherwise falls back to BlockPolygonSource.
        """
        result_data = result_data or {}
        compartments = result_data.get("compartments", [])
        if compartments:
            return CompartmentPolygonSource(result_data)
        return BlockPolygonSource(result_data)

    @classmethod
    def has_compartments(cls, result_data: Optional[Dict[str, Any]]) -> bool:
        """Check if the result_data indicates compartment mode."""
        result_data = result_data or {}
        return bool(result_data.get("compartments", []))


class BlockPolygonSource(PolygonSource):
    """Strategy for block-mode forests — reads result_data['blocks']."""

    def __init__(self, result_data: Dict[str, Any]):
        self._result_data = result_data

    def get_polygons(self) -> List[Dict[str, Any]]:
        return list(self._result_data.get("blocks", []))

    def get_metadata_key(self) -> str:
        return "blocks"


class CompartmentPolygonSource(PolygonSource):
    """Strategy for compartment-mode forests — reads result_data['compartments'].

    Falls back to result_data['blocks'] if compartments list is empty
    (defensive — should not happen in practice).
    """

    def __init__(self, result_data: Dict[str, Any]):
        self._result_data = result_data

    def get_polygons(self) -> List[Dict[str, Any]]:
        compartments = self._result_data.get("compartments", [])
        if compartments:
            return list(compartments)
        return list(self._result_data.get("blocks", []))

    def get_metadata_key(self) -> str:
        return "compartments"
