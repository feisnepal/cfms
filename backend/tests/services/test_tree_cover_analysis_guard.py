"""Regression tests for calculate_accessible_forest_area NULL-coercion (fully-treed units)."""
from types import SimpleNamespace

from app.services.tree_cover_analysis import calculate_accessible_forest_area


class _Row(SimpleNamespace):
    pass


class _FakeDB:
    """db.execute(...).first() returns the canned row; the tree-cover-only branch
    issues a single execute, so this is sufficient."""

    def __init__(self, row):
        self._row = row

    def execute(self, query, params):
        self.last_query = str(query)
        return SimpleNamespace(first=lambda: self._row)


def test_fully_treed_unit_non_forest_null_no_crash():
    # A fully-treed compartment has no non-forest pixels → SQL aggregate is NULL.
    db = _FakeDB(_Row(
        total_boundary_area_ha=36.13,
        tree_pixels=3613,
        non_forest_pixels=0,
        total_pixels=3613,
    ))
    info = calculate_accessible_forest_area(
        db=db, geometry_wkt="POLYGON((0 0,0 1,1 1,1 0,0 0))",
        filter_tree_cover=True, filter_slope=False,
    )
    assert info.get("error") is None
    assert float(info["accessible_forest_area_ha"]) == 36.13
    assert info["accessible_forest_percentage"] == 100.00
    assert info["non_forest_area_ha"] == 0
    assert info["non_forest_percentage"] == 0.00
    assert info["accessible_pixels"] == 3613


def test_reverse_null_tree_cover_only_non_forest():
    # No tree pixels but non-forest present (NULL tree aggregate) must not crash.
    db = _FakeDB(_Row(
        total_boundary_area_ha=5.0,
        tree_pixels=None,
        non_forest_pixels=500,
        total_pixels=500,
    ))
    info = calculate_accessible_forest_area(
        db=db, geometry_wkt="POLYGON((0 0,0 1,1 1,1 0,0 0))",
        filter_tree_cover=True, filter_slope=False,
    )
    assert info.get("error") is None
    assert float(info["accessible_forest_area_ha"]) == 0.0
    assert info["accessible_forest_percentage"] == 0.00
    assert info["non_forest_area_ha"] == 5.0
    assert info["non_forest_percentage"] == 100.00


def test_both_null():
    db = _FakeDB(_Row(
        total_boundary_area_ha=0.0, tree_pixels=None,
        non_forest_pixels=None, total_pixels=None,
    ))
    info = calculate_accessible_forest_area(
        db=db, geometry_wkt="POLYGON((0 0,0 1,1 1,1 0,0 0))",
        filter_tree_cover=True, filter_slope=False,
    )
    assert info.get("error") is None
    assert float(info["accessible_forest_area_ha"]) == 0.0
    assert info["accessible_forest_percentage"] == 0.00
    assert info["non_forest_area_ha"] == 0.0


def test_accessible_never_exceeds_authoritative_area_on_raster_overcount():
    # Regression: fully-treed unit whose pixel count (40 ha worth) exceeds its
    # geometry area (31.9 ha). Raw pixel-counting reported 40 ha of accessible
    # forest; the subtraction fix must cap accessible at the geometry area.
    db = _FakeDB(_Row(
        total_boundary_area_ha=31.9,
        tree_pixels=4000,
        non_forest_pixels=0,
        total_pixels=4000,
    ))
    info = calculate_accessible_forest_area(
        db=db, geometry_wkt="POLYGON((0 0,0 1,1 1,1 0,0 0))",
        filter_tree_cover=True, filter_slope=False,
    )
    assert info.get("error") is None
    assert float(info["accessible_forest_area_ha"]) == 31.9
    assert info["accessible_forest_percentage"] == 100.00
    assert float(info["total_boundary_area_ha"]) == 31.9
    assert float(info["non_forest_area_ha"]) == 0.0


def test_partial_cover_non_forest_subtracted_from_geometry():
    # 40 ha of non-forest pixels over a 100 ha geometry → 60 ha accessible.
    db = _FakeDB(_Row(
        total_boundary_area_ha=100.0,
        tree_pixels=6000,
        non_forest_pixels=4000,
        total_pixels=10000,
    ))
    info = calculate_accessible_forest_area(
        db=db, geometry_wkt="POLYGON((0 0,0 1,1 1,1 0,0 0))",
        filter_tree_cover=True, filter_slope=False,
    )
    assert float(info["accessible_forest_area_ha"]) == 60.0
    assert info["accessible_forest_percentage"] == 60.00
    assert float(info["non_forest_area_ha"]) == 40.0
    assert info["non_forest_percentage"] == 40.00
    assert info["accessible_pixels"] == 6000
    assert info["non_forest_pixels"] == 4000


def test_non_forest_overcount_clamped_to_geometry():
    # Non-forest pixel area (12 ha worth) exceeds the geometry (10 ha): the
    # subtraction must clamp so accessible never goes negative.
    db = _FakeDB(_Row(
        total_boundary_area_ha=10.0,
        tree_pixels=0,
        non_forest_pixels=1200,
        total_pixels=1200,
    ))
    info = calculate_accessible_forest_area(
        db=db, geometry_wkt="POLYGON((0 0,0 1,1 1,1 0,0 0))",
        filter_tree_cover=True, filter_slope=False,
    )
    assert float(info["accessible_forest_area_ha"]) == 0.0
    assert info["accessible_forest_percentage"] == 0.00
    assert float(info["non_forest_area_ha"]) == 10.0
    assert info["non_forest_percentage"] == 100.00


def test_clamped_ratio_in_low_tree_cover_helper():
    from app.services.sampling import low_tree_cover_coverage

    # Raster overcount (accessible > block area) must NOT trigger the warning.
    blocks = [
        {"block_name": "C4", "block_area_hectares": 31.88, "accessible_forest_area_ha": 36.13},
        {"block_name": "Block B", "block_area_hectares": 10, "accessible_forest_area_ha": 1.0},
    ]
    assert low_tree_cover_coverage(blocks) == ["Block B"]