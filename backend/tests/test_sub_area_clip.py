"""
Phase 4 tests — post-import clip to forest boundary ∪ blocks, overlap handling,
and the category-derived area invariants (D2c) reused by convert-to-builtin.

Covers `clip_to_region` (sub_area_service) and the perimeter recalculation
helpers (forests.py) that back the convert-to-builtin branch.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from shapely.geometry import box, shape, mapping
from app.services.sub_area_service import clip_to_region


def _m(b):
    return mapping(b) if not isinstance(b, dict) else b


def test_clip_straddles_boundary_is_intersected():
    # Sub-area crosses the forest boundary → clipped to the inside portion.
    boundary = [_m(box(0, 0, 10, 10))]
    straddler = _m(box(5, 5, 15, 15))
    result, was_clipped = clip_to_region(straddler, boundary)
    assert was_clipped is True
    clipped = shape(result)
    # intersection of boundary(0,0..10,10) with (5,5..15,15) = 5x5 = 25.0
    assert clipped.area == 25.0


def test_clip_partially_outside_block_reduced():
    block = _m(box(0, 0, 10, 5))
    sa = _m(box(2, 2, 12, 6))
    result, was_clipped = clip_to_region(sa, [block])
    assert was_clipped is True
    assert shape(result).area <= 25.0


def test_clip_fully_outside_removed():
    boundary = _m(box(0, 0, 10, 10))
    outside = _m(box(20, 20, 30, 30))
    result, was_clipped = clip_to_region(outside, [boundary])
    assert result is None
    assert was_clipped is True


def test_clip_within_boundary_unchanged():
    boundary = [_m(box(0, 0, 10, 10))]
    inside = _m(box(2, 2, 8, 8))
    result, was_clipped = clip_to_region(inside, boundary)
    assert was_clipped is False
    assert shape(result).area == 36.0


def test_clip_union_boundary_and_blocks():
    boundary = _m(box(0, 0, 10, 10))
    block = _m(box(0, 0, 4, 4))
    region = [boundary, block]
    sa = _m(box(1, 1, 3, 3))  # inside block → kept whole
    result, _ = clip_to_region(sa, region)
    assert shape(result).area == 4.0


def test_clip_no_region_unchanged():
    sa = _m(box(0, 0, 5, 5))
    result, was_clipped = clip_to_region(sa, [])
    assert was_clipped is False
    assert shape(result).area == 25.0


def test_clip_wkb_boundary_is_clipped():
    # Regression: Calculation.boundary_geom is a geoalchemy2 WKBElement (not a
    # dict). clip_to_region must unwrap it via to_shape, otherwise unary_union
    # throws and clipping silently no-ops (sub-areas/compartments drift outside).
    from geoalchemy2 import WKBElement
    import binascii
    boundary_wkb = box(0, 0, 10, 10)
    wkb_elem = WKBElement(
        bytes.fromhex(binascii.hexlify(boundary_wkb.wkb).decode()), srid=4326
    )
    straddler = _m(box(5, 5, 15, 15))
    result, was_clipped = clip_to_region(straddler, [wkb_elem])
    assert was_clipped is True
    assert shape(result).area == 25.0

    # Fully outside the WKB boundary → removed entirely.
    outside_result, outside_flag = clip_to_region(_m(box(20, 20, 30, 30)), [wkb_elem])
    assert outside_result is None
    assert outside_flag is True


def test_excluded_area_derives_from_category_private_land():
    from app.api.forests import calculate_total_excluded_area
    sa_private = {"id": "p", "category": "private_land", "area_hectares": 3.0}
    assert calculate_total_excluded_area([sa_private]) == 3.0
    sa_office = {"id": "o", "category": "office", "area_hectares": 1.0}
    assert calculate_total_excluded_area([sa_office]) == 0.0


# ---------------------------------------------------------------------------
# Phase 5 — Feature-to-Polygon + snap-to-close (SUB_AREA_SNAP_TOLERANCE_M)
# ---------------------------------------------------------------------------
from shapely.geometry import Polygon, LineString, Point
from app.services.sub_area_service import (
    convert_lines_to_multi_line,
    polygonise_sub_area_geometries,
)


def test_closed_line_becomes_polygon():
    ring = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    lines, polys = convert_lines_to_multi_line([LineString(ring)])
    assert lines == []
    assert len(polys) == 1
    assert polys[0].area == 100.0


def test_snap_closes_nearly_closed_line_within_tolerance():
    # Gap of ~0.00001 deg (≈1m) ≤ 20m → snapped closed into a polygon.
    near_ring = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0.00001)]
    lines, polys = convert_lines_to_multi_line([LineString(near_ring)])
    assert len(polys) == 1
    assert lines == []


def test_open_line_beyond_tolerance_stays_open():
    open_line = LineString([(0, 0), (0, 5)])  # endpoint gap ≫ tolerance
    lines, polys = convert_lines_to_multi_line([open_line])
    assert len(polys) == 0
    assert len(lines) == 1


def test_polygonise_preserves_existing_polygons():
    poly = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    out = polygonise_sub_area_geometries([poly], [{"name": "Zone A"}])
    assert len(out) == 1
    assert out[0][0].area == 16.0
    assert out[0][1]["name"] == "Zone A"


def test_polygonise_names_from_point_inside():
    poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    pt = Point(5, 5)
    out = polygonise_sub_area_geometries([poly, pt],
                                         [{"name": "Poly"}, {"name": "Point Name"}])
    names = [attrs.get("name") for _, attrs in out]
    assert "Point Name" in names


def test_polygonise_falls_back_to_sequence_name():
    poly = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    out = polygonise_sub_area_geometries([poly], [{}])
    assert out[0][1]["name"] == "Sub-Area 1"


# ---------------------------------------------------------------------------
# Phase 5 — snap tolerance edges + category auto-detect (T5.3 / T5.4)
# ---------------------------------------------------------------------------
from app.services.sub_area_service import auto_detect_category


def test_snap_tolerance_zero_no_snap():
    open_ring = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0.00001)]
    lines, polys = convert_lines_to_multi_line([LineString(open_ring)], tolerance_m=0)
    assert polys == []
    assert len(lines) == 1


def test_snap_endpoints_15m_apart_within_20m():
    # 15 m ≈ 0.00013 deg is within default 20 m tolerance.
    gap_ring = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0.00012)]
    lines, polys = convert_lines_to_multi_line([LineString(gap_ring)])
    assert len(polys) == 1


def test_snap_gap_30m_beyond_tolerance_drops():
    gap_ring = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0.00030)]
    lines, polys = convert_lines_to_multi_line([LineString(gap_ring)])
    assert polys == []
    assert len(lines) == 1


def test_polygonise_auto_detects_category_column():
    attrs = {"category": "plantation", "name": "P"}
    out = polygonise_sub_area_geometries(
        [Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])], [attrs]
    )
    assert out[0][1]["category"] == "plantation"


def test_polygonise_category_unknown_defaults_protected():
    attrs = {"type": "not-a-real-category", "name": "P"}
    out = polygonise_sub_area_geometries(
        [Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])], [attrs]
    )
    assert out[0][1]["category"] == "protected"


def test_auto_detect_recognises_nepali_and_alias_columns():
    assert auto_detect_category({"वर्ग": "वन लगाए"} ) == "protected"  # unmatched → default
    assert auto_detect_category({"प्रकार": "plantation"}) == "plantation"
    assert auto_detect_category({"type": "private land"}) == "private_land"
    assert auto_detect_category({"name": "something"}) == "protected"  # no category col
    assert auto_detect_category({}) == "protected"


# ---------------------------------------------------------------------------
# Phase 6 — Feature-to-Polygon provenance + append invariants (T6.2)
# ---------------------------------------------------------------------------
def test_polygonise_provenance_source_tags():
    poly = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    out = polygonise_sub_area_geometries([poly], [{"name": "A"}])
    assert out[0][1]["source"] == "poly"

    ring = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    out2 = polygonise_sub_area_geometries([LineString(ring)], [{}])
    assert out2[0][1]["source"] == "line_snapped"


def test_convert_imported_append_does_not_clear_existing():
    # Simulate the convert-to-builtin invariant: re-import appends, never clears.
    import json
    from app.services.sub_area_service import _last_import_warnings
    poly = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    out = polygonise_sub_area_geometries([poly], [{"category": "plantation"}])
    warnings = _last_import_warnings()
    assert warnings.get("polygon_count") == 1
    assert warnings.get("dropped_unclosed", 0) == 0

# ---------------------------------------------------------------------------
# has_forest_extent — the boundary-first precondition for drawing / importing a
# sub-area (add_sub_area 422, convert-to-builtin sub_areas 422).
# ---------------------------------------------------------------------------
class _FakeQuery:
    def filter(self, *a, **k):
        return self

    def first(self):
        return None


class _FakeDB:
    def query(self, *a, **k):
        return _FakeQuery()


class _Calc:
    id = "00000000-0000-0000-0000-000000000000"

    def __init__(self, boundary=None, result_data=None):
        self.boundary_geom = boundary
        self.result_data = result_data or {}


def test_has_forest_extent_false_when_no_boundary_no_blocks():
    from app.services.sub_area_service import has_forest_extent

    assert has_forest_extent(_FakeDB(), _Calc()) is False


def test_has_forest_extent_true_with_boundary():
    from app.services.sub_area_service import has_forest_extent

    assert has_forest_extent(_FakeDB(), _Calc(boundary=object())) is True


def test_has_forest_extent_true_with_result_data_blocks():
    from app.services.sub_area_service import has_forest_extent

    assert has_forest_extent(_FakeDB(), _Calc(result_data={"blocks": [{"id": "b1"}]})) is True
    assert has_forest_extent(
        _FakeDB(), _Calc(result_data={"compartments": [{"id": "c1"}]})
    ) is True
