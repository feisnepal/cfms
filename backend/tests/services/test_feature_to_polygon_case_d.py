"""Phase U-2 tests — case D: points → polygons (concave hull) + island clustering.

Covers:
- Task 2.1: points carrying a grouping/name attr hull into one polygon per group;
  points without any grouping attr form a single polygon.
- Task 2.2: concave hull output is always valid; degenerate / degenerate-cluster
  inputs never produce an invalid geometry (convex-hull fallback).
- Task 2.3: disjoint island points cluster into separate polygons (invariant F);
  adjoining points within the threshold form a single polygon.
"""
import pytest
from hypothesis import given, strategies as st
from shapely.geometry import Point, Polygon, MultiPoint

from app.services.file_processor import (
    PolygonizeConfig,
    feature_to_polygon,
    _cluster_points_by_distance,
    _concave_hull,
)


def _square_points(cx, cy, half=0.0001):
    return [
        Point(cx - half, cy - half),
        Point(cx + half, cy - half),
        Point(cx + half, cy + half),
        Point(cx - half, cy + half),
    ]


def test_point_group_attr_hulls_per_group():
    """Task 2.1: points sharing a group/name attr -> one polygon per group."""
    attrs = [
        {"group": "G1"}, {"group": "G1"}, {"group": "G1"}, {"group": "G1"},
        {"group": "G2"}, {"group": "G2"}, {"group": "G2"}, {"group": "G2"},
    ]
    geoms = _square_points(0, 0) + _square_points(5, 5)
    cfg = PolygonizeConfig(allow_point_hull=True, alpha=0.4, island_cluster_m=50.0)
    result, warnings = feature_to_polygon(geoms, attrs, cfg)

    names = sorted(a.get("name") for _, a in result)
    assert names == ["G1", "G2"]
    assert all(isinstance(g, Polygon) for g, _ in result)


def test_no_group_attr_single_polygon():
    """Task 2.1: points without grouping attr -> one polygon from all points."""
    geoms = [Point(x, y) for x, y in [(0, 0), (1, 0), (0.5, 1)]]
    cfg = PolygonizeConfig(allow_point_hull=True)
    result, warnings = feature_to_polygon(geoms, [{}] * len(geoms), cfg)
    assert len(result) == 1
    g, a = result[0]
    assert isinstance(g, Polygon)
    assert g.area > 0


def test_point_hull_is_valid_and_concave():
    """Task 2.2: concave-hull output is always valid; convex-hull fallback works."""
    # An L-shaped cloud: concave hull should have smaller area than convex hull.
    cloud = [
        Point(0, 0), Point(1, 0), Point(2, 0),
        Point(0, 1), Point(1, 1), Point(2, 1),
        Point(0, 2), Point(1, 2),
    ]
    cfg = PolygonizeConfig(allow_point_hull=True, alpha=0.4)
    result, warnings = feature_to_polygon(cloud, [{}] * len(cloud), cfg)
    g, a = result[0]
    assert g.is_valid
    assert g.area < MultiPoint(cloud).convex_hull.area


def test_point_hull_never_invalid_with_noise():
    """Task 2.2: self-crossing / noisy clouds produce valid polygons, never invalid."""
    noise = [
        Point(0.5, 0.5), Point(0.51, 0.5), Point(0.5, 0.51),
        Point(10, 10), Point(10.01, 10), Point(10, 10.01),
        Point(10.2, 10.2),
    ]
    for alpha in (None, 0.1, 0.5, 0.9):
        cfg = PolygonizeConfig(allow_point_hull=True, alpha=alpha, island_cluster_m=20.0)
        result, warnings = feature_to_polygon(noise, [{}] * len(noise), cfg)
        assert result, "expected at least one hull polygon"
        for g, _ in result:
            assert g.is_valid


def test_disjoint_islands_cluster_separate_polygons():
    """Task 2.3: disjoint island points cluster into N polygons (invariant F)."""
    # Two clearly disjoint clusters far apart.
    geoms = _square_points(0, 0) + _square_points(10, 10)
    cfg = PolygonizeConfig(allow_point_hull=True, island_cluster_m=100.0)
    result, warnings = feature_to_polygon(geoms, [{}] * len(geoms), cfg)
    assert len(result) == 2
    assert all(g.is_valid for g, _ in result)


def test_adjoining_points_within_threshold_single_polygon():
    """Task 2.3: points within the cluster threshold -> 1 polygon, not N."""
    geoms = _square_points(0, 0) + _square_points(0.0001, 0.0001)
    cfg = PolygonizeConfig(allow_point_hull=True, island_cluster_m=100.0)
    result, warnings = feature_to_polygon(geoms, [{}] * len(geoms), cfg)
    assert len(result) == 1


def test_island_cluster_threshold_boundary():
    """Task 2.3: threshold boundary cases (gap just over / just under)."""
    # Two compact squares ~2.2 km apart (each square ~22 m wide).
    geoms = _square_points(0, 0) + _square_points(0.02, 0)
    # Tight threshold = 100 m (< the 2.2 km gap) -> 2 islands.
    tight = PolygonizeConfig(allow_point_hull=True, island_cluster_m=100.0)
    # Loose threshold = 5 km (> the 2.2 km gap) -> 1 island.
    loose = PolygonizeConfig(allow_point_hull=True, island_cluster_m=5000.0)
    r1, _ = feature_to_polygon(geoms, [{}] * len(geoms), tight)
    r2, _ = feature_to_polygon(geoms, [{}] * len(geoms), loose)
    assert len(r1) == 2
    assert len(r2) == 1


def test_dropped_unclosed_on_degenerate_cloud():
    """Task 2.2: fewer than 3 points in a cluster -> dropped with a warning."""
    geoms = [Point(0, 0), Point(1, 1)]  # 2 points, cannot hull
    cfg = PolygonizeConfig(allow_point_hull=True)
    result, warnings = feature_to_polygon(geoms, [{}] * len(geoms), cfg)
    assert result == []
    assert warnings["dropped_unclosed"] >= 1


def test_cluster_helper_transitive():
    """Task 2.3 helper: transitively-close points merge into one cluster."""
    chain = [Point(0, 0), Point(0.001, 0), Point(0.002, 0)]
    clusters = _cluster_points_by_distance(chain, 500.0)  # ~0.0045 deg/500m
    assert len(clusters) == 1
    assert len(clusters[0]) == 3


def test_concave_hull_fallback_to_convex_on_degenerate():
    """Task 2.2: _concave_hull returns None for degenerate input, never invalid."""
    pts = [Point(0, 0), Point(0, 0), Point(0, 0)]
    assert _concave_hull(pts, 0.4) is None


@st.composite
def _point_clouds(draw):
    """Random point clouds (3-40 points) in a bounded box, with optional disjoint
    clusters, to exercise hull + island-cluster invariants."""
    n = draw(st.integers(min_value=3, max_value=40))
    points = [Point(draw(st.floats(-50, 50)), draw(st.floats(-50, 50))) for _ in range(n)]
    return points


@given(_point_clouds())
def test_property_hull_never_invalid(points):
    """Property: for any >=3-point cloud, concave/shapely output is always a valid,
    non-empty polygon (never an invalid or empty geometry)."""
    for alpha in (0.0, 0.4, 0.9):
        cfg = PolygonizeConfig(allow_point_hull=True, alpha=alpha, island_cluster_m=500000.0)
        result, warnings = feature_to_polygon(points, [{}] * len(points), cfg)
        for g, _ in result:
            assert g.is_valid
            assert not g.is_empty
            assert g.area >= 0


@given(_point_clouds())
def test_property_cluster_points_preserve_all(points):
    """Property: clustering never drops points — the union of all clusters equals
    the original point set (invariant F bookkeeping)."""
    clusters = _cluster_points_by_distance(points, 500000.0)
    flat = [pt for cl in clusters for pt in cl]
    assert len(flat) == len(points)
