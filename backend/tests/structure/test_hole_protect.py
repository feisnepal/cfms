"""Hole-fill scope-aware (G1, FS-4a.12): a hole in a divide/auto-create
piece that coincides with excluded ground (private land ∪ protection
units) must never be silently "hole-filled" (re-absorbed) just because it
is smaller than the MMU artifact threshold.

All geometries here are lon/lat degrees near Nepal (matching every other
test file in this package) -- ``area_sqm``/``_area_m2`` are GEODESIC and
misbehave on made-up Cartesian coordinates (a "latitude" past ±90 is not a
real position), so every fixture below is sized in real degree terms, not
arbitrary small numbers.
"""

from __future__ import annotations

import uuid

from shapely.geometry import Polygon, box, mapping

from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.services import auto_block_service as abs_service
from app.services import geometry_edit_service as geo
from app.services.forest_units.operations.virtual_root import hole_protect_geom


def _make_calc(db, boundary=None, sub_areas=None):
    user = User(
        email=f"holeprotect{uuid.uuid4().hex[:8]}@test.com",
        full_name="Hole Protect Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="hole.csv",
        is_draft=False,
        result_data={"sub_areas": sub_areas or []},
    )
    if boundary is not None:
        from geoalchemy2.shape import from_shape

        calc.boundary_geom = from_shape(boundary, srid=4326)
    db.add(calc)
    db.flush()
    return calc


def _private_land_sub_area(geom):
    return {
        "id": str(uuid.uuid4()),
        "category": "private_land",
        "geometry": mapping(geom),
        "isExcluded": False,
    }


# A forest boundary (~11km x 11km) with a SMALL private-land hole
# (~0.2 ha -- well under the 1 ha MMU_HOLE_FILL_AREA_M2 default threshold)
# well inside it, not touching the outer edge (so `forest_area_geom` =
# boundary - private_land genuinely carries an interior hole, not a notch).
BOUNDARY = box(83.0, 27.0, 83.10, 27.10)
PRIVATE_HOLE = box(83.0500, 27.0500, 83.0504, 27.0504)  # ~44m x 44m, ~0.2 ha

# A moderate "ring" polygon (~1.1km x 1.1km, ~121 ha) with a small interior
# "hole" (~0.03 ha) for the standalone _fill_holes/_hole_is_protected tests
# that don't need a full Calculation.
RING = box(83.0, 27.0, 83.01, 27.01)
SMALL_HOLE = box(83.0049, 27.0049, 83.0054, 27.0054)  # ~55m x 44m, ~0.24 ha
FAR_AWAY = box(83.05, 27.05, 83.051, 27.051)


# ---------------------------------------------------------------------------
# hole_protect_geom
# ---------------------------------------------------------------------------

def test_hole_protect_geom_is_none_with_nothing_to_protect(db):
    calc = _make_calc(db, BOUNDARY)
    assert hole_protect_geom(db, calc) is None


def test_hole_protect_geom_includes_private_land(db):
    calc = _make_calc(db, BOUNDARY, sub_areas=[_private_land_sub_area(PRIVATE_HOLE)])
    protect = hole_protect_geom(db, calc)
    assert protect is not None
    assert protect.intersection(PRIVATE_HOLE).area > 0


# ---------------------------------------------------------------------------
# geometry_edit_service._hole_is_protected / _fill_holes / sanitize_geometry
# ---------------------------------------------------------------------------

def test_hole_is_protected_true_for_material_overlap():
    assert geo._hole_is_protected(SMALL_HOLE, SMALL_HOLE) is True


def test_hole_is_protected_false_for_no_overlap():
    assert geo._hole_is_protected(SMALL_HOLE, FAR_AWAY) is False


def test_hole_is_protected_false_below_overlap_fraction():
    # A tiny sliver of protect_geom clipping just the hole's SE corner.
    corner = box(83.0053, 27.0053, 83.0054, 27.0054)
    assert geo._hole_is_protected(SMALL_HOLE, corner) is False


def test_fill_holes_default_fills_small_holes_unprotected():
    """Backward compatibility: with no protect_geom, behaviour is unchanged
    from before G1 — a hole under the threshold is filled."""
    poly = Polygon(RING.exterior, [SMALL_HOLE.exterior.coords])
    assert len(poly.interiors) == 1

    filled, warnings = geo._fill_holes(poly, hole_fill_area_m2=10_000.0)
    assert len(filled.interiors) == 0
    assert geo.W_HOLES_FILLED in warnings


def test_fill_holes_keeps_a_protected_small_hole():
    poly = Polygon(RING.exterior, [SMALL_HOLE.exterior.coords])

    filled, warnings = geo._fill_holes(
        poly, hole_fill_area_m2=10_000.0, protect_geom=SMALL_HOLE
    )
    assert len(filled.interiors) == 1
    assert geo.W_HOLES_FILLED not in warnings


def test_sanitize_geometry_threads_protect_geom():
    poly = Polygon(RING.exterior, [SMALL_HOLE.exterior.coords])

    sanitized, _ = geo.sanitize_geometry(poly, protect_geom=SMALL_HOLE)
    assert len(sanitized.interiors) == 1

    sanitized_unprotected, _ = geo.sanitize_geometry(poly)
    assert len(sanitized_unprotected.interiors) == 0


# ---------------------------------------------------------------------------
# The real bug (report §15): divide_equal_area on a forest_area_geom-shaped
# polygon (boundary MINUS a small private-land parcel, so the parcel is
# already an interior hole) must not silently re-absorb that hole.
# ---------------------------------------------------------------------------

def test_divide_equal_area_never_reabsorbs_a_protected_private_land_hole():
    forest_area = BOUNDARY.difference(PRIVATE_HOLE)  # has a small interior hole
    assert isinstance(forest_area, Polygon)
    assert len(forest_area.interiors) == 1
    assert geo.area_sqm(forest_area.interiors[0]) < 10_000.0  # confirms it's a
    # genuine hole-fill CANDIDATE (under the 1 ha default) -- the test would
    # be meaningless if the hole were already too big to ever be filled.

    pieces, warnings = geo.divide_equal_area(
        forest_area,
        layer_type="blocks",
        method="strips",
        n=2,
        protect_geom=PRIVATE_HOLE,
    )
    assert pieces, warnings
    # No piece's territory covers the private-land hole.
    total_overlap = sum(geo.area_sqm(p.intersection(PRIVATE_HOLE)) for p in pieces)
    assert total_overlap < geo.area_sqm(PRIVATE_HOLE) * 0.05  # negligible at most


def test_divide_equal_area_grid_method_also_never_reabsorbs_the_hole():
    """The `grid` method routes through `equal_area_grid` -> `equal_area_strips`
    twice (rows, then cols) -- both re-sanitize internally and both must
    honour protect_geom, not just the `strips` method's single call."""
    forest_area = BOUNDARY.difference(PRIVATE_HOLE)
    pieces, warnings = geo.divide_equal_area(
        forest_area,
        layer_type="blocks",
        method="grid",
        rows=2,
        cols=2,
        protect_geom=PRIVATE_HOLE,
    )
    assert pieces, warnings
    total_overlap = sum(geo.area_sqm(p.intersection(PRIVATE_HOLE)) for p in pieces)
    assert total_overlap < geo.area_sqm(PRIVATE_HOLE) * 0.05


def test_divide_multipolygon_equal_area_never_reabsorbs_the_hole():
    from shapely.geometry import MultiPolygon

    # Two disjoint islands; the hole sits inside the first one.
    island_a = BOUNDARY.difference(PRIVATE_HOLE)
    island_b = box(83.20, 27.0, 83.25, 27.10)
    multi = MultiPolygon([island_a, island_b])

    pieces, warnings = geo.divide_multipolygon_equal_area(
        multi,
        counts=[2, 1],
        layer_type="blocks",
        method="strips",
        protect_geom=PRIVATE_HOLE,
    )
    assert pieces, warnings
    total_overlap = sum(geo.area_sqm(p.intersection(PRIVATE_HOLE)) for p in pieces)
    assert total_overlap < geo.area_sqm(PRIVATE_HOLE) * 0.05


def test_divide_equal_area_without_protect_geom_would_reabsorb_the_hole():
    """Confirms the bug WOULD reproduce without the fix — protect_geom is
    doing real work, not a no-op."""
    forest_area = BOUNDARY.difference(PRIVATE_HOLE)
    pieces, warnings = geo.divide_equal_area(
        forest_area,
        layer_type="blocks",
        method="strips",
        n=2,
        # No protect_geom, no exclude_geom: the old, pre-G1 behaviour.
    )
    assert pieces, warnings
    total_overlap = sum(geo.area_sqm(p.intersection(PRIVATE_HOLE)) for p in pieces)
    # The hole WAS silently re-absorbed (most of it ends up inside a piece).
    assert total_overlap > geo.area_sqm(PRIVATE_HOLE) * 0.9


# ---------------------------------------------------------------------------
# auto_block_service._hole_is_protected / _fill_holes (pieces-list variant)
# ---------------------------------------------------------------------------

def test_auto_block_hole_is_protected_mirrors_the_geometry_edit_service_one():
    assert abs_service._hole_is_protected(SMALL_HOLE, SMALL_HOLE) is True
    assert abs_service._hole_is_protected(SMALL_HOLE, FAR_AWAY) is False


def test_auto_block_fill_holes_keeps_a_protected_small_hole():
    poly = Polygon(RING.exterior, [SMALL_HOLE.exterior.coords])

    filled_unprotected = abs_service._fill_holes([poly], hole_fill_area_m2=10_000.0)
    assert len(filled_unprotected[0].interiors) == 0

    filled_protected = abs_service._fill_holes(
        [poly], hole_fill_area_m2=10_000.0, protect_geom=SMALL_HOLE
    )
    assert len(filled_protected[0].interiors) == 1
