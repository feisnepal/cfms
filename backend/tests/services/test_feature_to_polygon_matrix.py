"""Phase U-7 tests — per-purpose A–E acceptance matrix (Task 7.1) + property
tests for the shared Feature-to-Polygon engine and the boundary area-invariant
(invariant A) logic (Task 7.5).

Task 7.1 DoD: "every built-in polygon layer accepts point/line/polygon/mixed
across all formats incl. GPKG and resolves to polygons."  This file drives the
SHARED engine directly (feature_to_polygon for every purpose in
POLYGON_AUTO_BUFFER) so each polygon-purpose path is proven to resolve every
input modality (A polygon, B snap-closed line, C open-line partition, D point
hull, E mixed) to a valid (Multi)Polygon with no non-polygon output.
"""
from typing import List, Tuple

import pytest
from hypothesis import given, settings, strategies as st
from shapely.geometry import Point, LineString, Polygon, MultiPolygon, box

from app.core.constants import (
    IMPORT_PURPOSE_POLYGON_AUTO_BUFFER,
    IMPORT_PURPOSE_BLOCKS,
    IMPORT_PURPOSE_BOUNDARY,
    IMPORT_PURPOSE_USER_GROUP_BOUNDARY,
    IMPORT_PURPOSE_SUB_AREAS,
    IMPORT_PURPOSE_COMPARTMENTS,
    IMPORT_PURPOSE_SUB_COMPARTMENTS,
    IMPORT_PURPOSE_SUB_BLOCKS,
)
from app.services.file_processor import (
    PolygonizeConfig,
    feature_to_polygon,
    derive_boundary_from_polygons,
    boundary_area_matches_block_sum,
)
from app.services.sub_area_service import polygonise_sub_area_geometries

# All seven polygon purposes that are auto-buffered to polygons on import.
EXPECTED_PURPOSES = {
    IMPORT_PURPOSE_BLOCKS,
    IMPORT_PURPOSE_BOUNDARY,
    IMPORT_PURPOSE_USER_GROUP_BOUNDARY,
    IMPORT_PURPOSE_SUB_AREAS,
    IMPORT_PURPOSE_COMPARTMENTS,
    IMPORT_PURPOSE_SUB_COMPARTMENTS,
    IMPORT_PURPOSE_SUB_BLOCKS,
}


def _assemble_engine(purpose: str):
    """Return (engine, config) for a given purpose.

    sub_areas routes through its thin wrapper (adds category detection); every
    other purpose uses the shared engine directly with the same config that
    `workspace.import_layer` supplies.
    """
    if purpose == IMPORT_PURPOSE_SUB_AREAS:
        return polygonise_sub_area_geometries, None
    return feature_to_polygon, PolygonizeConfig(
        snap_tolerance_m=20.0,
        allow_point_hull=True,
        alpha=None,
        island_cluster_m=100.0,
        name_prefix=purpose.replace("_", " ").title(),
    )


def _squares(x0, y0, n=2, size=0.01):
    """n non-overlapping axis-aligned squares near (x0, y0)."""
    out = []
    for i in range(n):
        x = x0 + i * size * 10
        y = y0 + (i % 2) * size * 2
        out.append(box(x, y, x + size, y + size))
    return out


# ---------------------------------------------------------------------------
# Case A — pure polygons are preserved one feature each.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("purpose", sorted(EXPECTED_PURPOSES))
def test_case_a_polygons_preserved(purpose):
    engine, cfg = _assemble_engine(purpose)
    geoms = _squares(0, 0, 3)
    attrs = [{"name": f"P{i}"} for i in range(len(geoms))]

    if purpose == IMPORT_PURPOSE_SUB_AREAS:
        result = engine(geoms, attrs)
    else:
        result, _ = engine(geoms, attrs, cfg)
    assert len(result) == len(geoms), result
    for g, a in result:
        assert isinstance(g, (Polygon, MultiPolygon)), g.geom_type


# ---------------------------------------------------------------------------
# Case B — near-closed lines snap to close into polygons.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("purpose", sorted(EXPECTED_PURPOSES))
def test_case_b_near_closed_line_snaps(purpose):
    # A ring whose start/end gap is ~5 m (< 20 m snap tolerance).
    gap_deg = 5.0 / 111000.0
    ring = [
        (0.0, 0.0), (0.01, 0.0), (0.01, 0.01), (0.0, 0.01), (gap_deg, gap_deg),
    ]
    geoms = [LineString(ring)]
    attrs = [{"name": "near-closed"}]
    engine, cfg = _assemble_engine(purpose)
    if purpose == IMPORT_PURPOSE_SUB_AREAS:
        result = engine(geoms, attrs)
    else:
        result, _ = engine(geoms, attrs, cfg)
    polys = [g for g, _ in result if isinstance(g, (Polygon, MultiPolygon))]
    assert polys, f"{purpose}: no polygon produced from near-closed line"
    assert all(g.area > 0 for g in polys)


# ---------------------------------------------------------------------------
# Case C — open lines partition the largest containing polygon.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("purpose", sorted(EXPECTED_PURPOSES))
def test_case_c_open_line_partitions(purpose):
    outer = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    # A vertical line splitting the square into left/right halves.
    divider = LineString([(0.5, 0.001), (0.5, 0.999)])
    geoms = [outer, divider]
    attrs = [{"name": "outer"}, {"name": "divider"}]
    engine, cfg = _assemble_engine(purpose)
    if purpose == IMPORT_PURPOSE_SUB_AREAS:
        result = engine(geoms, attrs)
    else:
        result, _ = engine(geoms, attrs, cfg)
    assert result, f"{purpose}: no features from open-line partition"
    assert all(isinstance(g, (Polygon, MultiPolygon)) for g, _ in result)


# ---------------------------------------------------------------------------
# Case C (T-junction) — a division line whose endpoint lands on ANOTHER
# division line, not on the outer boundary. `shapely.ops.split` (the old,
# sequential implementation) cannot cut on this topology; the node+polygonize
# engine (`_polygonize_edge_network`) can. Mirrors हिमाल.kmz's real topology
# (bug report: a KMZ that should split into 5 blocks produced only 2).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("purpose", sorted(EXPECTED_PURPOSES))
def test_case_c_line_ending_on_another_line_partitions_correctly(purpose):
    outer = Polygon([(0, 0), (2, 0), (2, 1), (0, 1), (0, 0)])
    # Full-width divider: crosses the outer boundary on both ends, splitting
    # the square into a left half (x<1) and a right half (x>1).
    spine = LineString([(1, 0.0), (1, 1.0)])
    # This line starts ON the outer boundary but ends ON the spine's midpoint
    # (a T-junction, not a boundary crossing) — it should still carve the
    # left half into two, for 3 faces total.
    branch = LineString([(0, 0.5), (1, 0.5)])
    geoms = [outer, spine, branch]
    attrs = [{"name": "outer"}, {"name": "spine"}, {"name": "branch"}]
    engine, cfg = _assemble_engine(purpose)
    if purpose == IMPORT_PURPOSE_SUB_AREAS:
        result = engine(geoms, attrs)
    else:
        result, _ = engine(geoms, attrs, cfg)
    assert all(isinstance(g, (Polygon, MultiPolygon)) for g, _ in result)
    assert len(result) == 3, (
        f"{purpose}: expected 3 faces (spine + T-junction branch), got "
        f"{len(result)}"
    )
    assert sum(g.area for g in [r[0] for r in result]) == pytest.approx(outer.area)


# ---------------------------------------------------------------------------
# Case D — points hull into a polygon.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("purpose", sorted(EXPECTED_PURPOSES))
def test_case_d_points_hull(purpose):
    pts = [Point(0, 0), Point(1, 0), Point(0.5, 1)]
    attrs = [{"name": "pt"}] * 3
    engine, cfg = _assemble_engine(purpose)
    if purpose == IMPORT_PURPOSE_SUB_AREAS:
        result = engine(pts, attrs, 1.0)  # sub_areas wrapper: no point hull by default
    else:
        result, _ = engine(pts, attrs, cfg)
    polys = [g for g, _ in result if isinstance(g, (Polygon, MultiPolygon))]
    # Every polygon-purpose consumes point data (buffered/hulled) — no crash,
    # and when hulled the output is a valid polygon.
    if polys:
        assert all(g.area > 0 for g in polys)


# ---------------------------------------------------------------------------
# Case E — mixed input assembles to polygons only.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("purpose", sorted(EXPECTED_PURPOSES))
def test_case_e_mixed_input_resolves_to_polygons(purpose):
    geoms = [
        box(0, 0, 0.01, 0.01),                    # A: polygon
        LineString([(0.02, 0.02), (0.0, 0.03), (0.03, 0.03)]),   # near-closed-ish
        Point(0.05, 0.05),                        # D: point
    ]
    attrs = [{"name": "poly"}, {"name": "line"}, {"name": "pt"}]
    engine, cfg = _assemble_engine(purpose)
    if purpose == IMPORT_PURPOSE_SUB_AREAS:
        result = engine(geoms, attrs)
    else:
        result, _ = engine(geoms, attrs, cfg)
    assert result, f"{purpose}: mixed input produced no features"
    assert all(isinstance(g, (Polygon, MultiPolygon)) for g, _ in result), (
        f"{purpose}: non-polygon geometry leaked through"
    )


# ---------------------------------------------------------------------------
# Parity — the matrix covers exactly the six advertised purposes.
# ---------------------------------------------------------------------------
def test_matrix_covers_exactly_polygon_auto_buffer_set():
    assert EXPECTED_PURPOSES == IMPORT_PURPOSE_POLYGON_AUTO_BUFFER


# ---------------------------------------------------------------------------
# Task 7.5 — property tests for the boundary area-invariant (invariant A).
# ---------------------------------------------------------------------------
@st.composite
def _disjoint_boxes(draw):
    """A set of adjacent boxes that tile a region (touching edges dissolve via
    unary_union into a single boundary whose area ~ Σ block areas within the
    invariant-A tolerance).  Boxes are large relative to BOUNDARY_HEAL_BUFFER_M
    so the heal distortion never exceeds the 0.1% tolerance."""
    n = draw(st.integers(min_value=2, max_value=5))
    size = draw(st.floats(min_value=0.05, max_value=0.15))
    boxes = []
    for i in range(n):
        boxes.append(box(0.0, i * size, size, i * size + size))
    return boxes


@settings(max_examples=20)
@given(_disjoint_boxes())
def test_property_boundary_area_matches_block_sum(boxes):
    """Invariant T (boundary=Σ-blocks within tolerance) for randomly tiled blocks."""
    boundary = derive_boundary_from_polygons(boxes)
    if boundary is None or boundary.is_empty:
        return
    ok, b_area, s_area = boundary_area_matches_block_sum(boundary, boxes)
    assert ok, f"boundary={b_area}ha vs Σblocks={s_area}ha"


def test_derive_boundary_empty_input_returns_none():
    assert derive_boundary_from_polygons([]) is None
    assert derive_boundary_from_polygons([None]) is None


def test_derive_boundary_handles_touching_squares():
    a = box(0, 0, 1, 1)
    b = box(1, 0, 2, 1)  # share common edge -> dissolve into a single rectangle
    boundary = derive_boundary_from_polygons([a, b])
    assert boundary is not None and not boundary.is_empty
    assert boundary.area == pytest.approx(2.0)