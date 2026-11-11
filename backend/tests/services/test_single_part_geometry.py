"""Single-part-feature invariant: `app/utils/single_part_geometry.py` +
the `@validates('geometry')` guards on `ForestBlock`/`ForestSubArea`.

Reproduces the exact महाभारत Compartment-13 corruption (2026-09-12): a
MultiPolygon bundling real polygons with degenerate numerical-noise slivers,
persisted as one row. `explode_and_filter_slivers` is the "N real pieces ->
N rows" helper; `ensure_single_polygon` (and the ORM validators built on it)
is the last-line guard that repairs the noise-only case and raises loudly on
the genuinely-multi-part case, so a future write path that forgets to
explode fails immediately instead of silently persisting corrupt data.
"""
import uuid

import pytest
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import MultiPolygon, Polygon, mapping, shape

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.forest_sub_area import ForestSubArea
from app.models.user import User, UserRole
from app.services.forest_units.model import DEPTH_SUB, DEPTH_TOP_BLOCK, DEPTH_TOP_COMPARTMENT
from app.utils.single_part_geometry import (
    MultiPartFeatureError,
    ensure_single_polygon,
    explode_and_filter_slivers,
    strip_degenerate_holes,
)


def _square(x, y, size=0.01):
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def _needle(x, y, size=0.0000001):
    """A near-zero-area sliver — the exact shape of the महाभारत noise."""
    return Polygon([(x, y), (x, y + size), (x + size, y + size), (x + size, y)])


def _needle_hole_ring(cx, cy, size=0.0000001):
    """A near-zero-area interior-ring coordinate list, same scale as
    `_needle` — the exact shape of the point-touch-glue-produced holes found
    live in महाभारत (2026-09-12): each with real vertices/perimeter but an
    enclosed area of a fraction of a square millimetre."""
    return [(cx, cy), (cx, cy + size), (cx + size, cy + size), (cx + size, cy)]


def _make_user(db):
    user = User(
        email=f"spg{uuid.uuid4().hex[:8]}@test.com",
        full_name="Single-Part Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    return user


def _make_calc(db):
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=_make_user(db).id,
        uploaded_filename="single-part-test.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    return calc


# ---------------------------------------------------------------------------
# explode_and_filter_slivers
# ---------------------------------------------------------------------------

def test_explode_drops_slivers_and_keeps_real_parts():
    real_a = _square(0, 0)
    real_b = _square(1, 1)
    needle = _needle(2, 2)
    bundled = MultiPolygon([real_a, real_b, needle])

    cleaned = explode_and_filter_slivers([bundled])

    assert len(cleaned) == 2
    assert all(isinstance(p, Polygon) for p in cleaned)


def test_explode_passes_through_a_single_polygon_list():
    solo = _square(0, 0)
    assert explode_and_filter_slivers([solo]) == [solo] or len(explode_and_filter_slivers([solo])) == 1


def test_explode_drops_none_and_empty_inputs():
    empty = Polygon()
    assert explode_and_filter_slivers([None, empty]) == []


def test_explode_unwraps_a_geometry_collection_from_make_valid():
    """`shapely.validation.make_valid` on a self-touching/degenerate shape
    (a real polygon with a zero-width spike -- exactly what independent
    per-piece smoothing can leave along a shared boundary) can return
    `GeometryCollection(Polygon, LineString)`, not a bare Polygon or
    MultiPolygon. The real polygon must still come through; the LineString
    repair remnant must be dropped, not treated as "no valid geometry"."""
    from shapely.geometry import GeometryCollection, LineString

    real = _square(0, 0)
    remnant = LineString([(5, 5), (5, 6)])
    bundled = GeometryCollection([real, remnant])

    cleaned = explode_and_filter_slivers([bundled])

    assert len(cleaned) == 1
    assert cleaned[0].equals(real)


# ---------------------------------------------------------------------------
# ensure_single_polygon
# ---------------------------------------------------------------------------

def test_ensure_single_polygon_passes_through_a_clean_polygon_unchanged():
    solo = _square(0, 0)
    assert ensure_single_polygon(solo) is solo


def test_ensure_single_polygon_auto_repairs_real_part_plus_noise_slivers():
    """The exact महाभारत shape: 1 real polygon + noise -> the real polygon,
    silently, with no exception (auto-heal, not a hard failure)."""
    real = _square(0, 0)
    needle = _needle(5, 5)
    bundled = MultiPolygon([real, needle])

    fixed = ensure_single_polygon(bundled)

    assert isinstance(fixed, Polygon)
    assert fixed.equals(real) or abs(fixed.area - real.area) < 1e-9


def test_ensure_single_polygon_raises_on_genuinely_multi_part():
    """2+ real disjoint pieces bundled into one geometry is a bug at the
    call site (it should be exploded into N rows) -- fail loudly, don't
    silently persist a MultiPolygon row."""
    bundled = MultiPolygon([_square(0, 0), _square(1, 1)])
    with pytest.raises(MultiPartFeatureError):
        ensure_single_polygon(bundled)


def test_ensure_single_polygon_raises_on_all_noise():
    bundled = MultiPolygon([_needle(0, 0), _needle(1, 1)])
    with pytest.raises(ValueError):
        ensure_single_polygon(bundled)


# ---------------------------------------------------------------------------
# strip_degenerate_holes (user report, 2026-09-12: "why do I see a line
# within the polygon like a boundary?" -- a merge "point-touch glue" on an
# already-complex महाभारत compartment left 11 sub-mm² interior rings, each
# with real vertices/perimeter, rendering as visible seams despite the
# polygon itself being perfectly valid and single-part -- not the multi-part
# problem the rest of this module guards against.)
# ---------------------------------------------------------------------------

def test_strip_degenerate_holes_drops_a_needle_thin_hole():
    outer = _square(0, 0, 1.0)
    poly = Polygon(outer.exterior, [_needle_hole_ring(0.5, 0.5)])
    assert len(poly.interiors) == 1

    fixed = strip_degenerate_holes(poly)

    assert len(fixed.interiors) == 0
    assert abs(fixed.area - outer.area) < 1e-15


def test_strip_degenerate_holes_keeps_a_real_hole():
    outer = _square(0, 0, 1.0)
    real_hole = [(0.4, 0.4), (0.4, 0.6), (0.6, 0.6), (0.6, 0.4)]  # a real 400 m^2-ish hole
    poly = Polygon(outer.exterior, [real_hole])

    fixed = strip_degenerate_holes(poly)

    assert len(fixed.interiors) == 1
    assert fixed.area < outer.area


def test_strip_degenerate_holes_passes_through_a_hole_free_polygon_unchanged():
    poly = _square(0, 0)
    assert strip_degenerate_holes(poly) is poly


def test_ensure_single_polygon_strips_degenerate_holes_on_the_fast_path():
    """The "already a single Polygon" fast path must not skip hole-cleanup
    -- a degenerate hole can appear on an otherwise perfectly valid,
    single-part polygon, which the multi-part checks alone would never see."""
    outer = _square(0, 0, 1.0)
    poly = Polygon(outer.exterior, [_needle_hole_ring(0.5, 0.5)])

    fixed = ensure_single_polygon(poly)

    assert isinstance(fixed, Polygon)
    assert len(fixed.interiors) == 0


def test_explode_and_filter_slivers_strips_degenerate_holes_too():
    outer = _square(0, 0, 1.0)
    poly = Polygon(outer.exterior, [_needle_hole_ring(0.5, 0.5)])

    cleaned = explode_and_filter_slivers([poly])

    assert len(cleaned) == 1
    assert len(cleaned[0].interiors) == 0


# ---------------------------------------------------------------------------
# ORM-level guard: ForestBlock / ForestSubArea
# ---------------------------------------------------------------------------

def test_forest_block_auto_heals_a_sliver_bundled_geometry(db):
    calc = _make_calc(db)
    real = _square(10, 10)
    needle = _needle(20, 20)
    bundled = MultiPolygon([real, needle])

    block = ForestBlock(
        calculation_id=calc.id,
        name="Test Block",
        geometry=from_shape(bundled, srid=4326),
        area_hectares=1.0,
        index=0,
    )
    db.add(block)
    db.flush()

    stored = to_shape(block.geometry)
    assert stored.geom_type == "Polygon"


def test_forest_block_strips_degenerate_holes_on_write(db):
    calc = _make_calc(db)
    outer = _square(30, 30, 1.0)
    poly = Polygon(outer.exterior, [_needle_hole_ring(30.5, 30.5)])

    block = ForestBlock(
        calculation_id=calc.id,
        name="Test Block",
        geometry=from_shape(poly, srid=4326),
        area_hectares=1.0,
        index=0,
    )
    db.add(block)
    db.flush()

    stored = to_shape(block.geometry)
    assert stored.geom_type == "Polygon"
    assert len(stored.interiors) == 0


@pytest.mark.parametrize(
    "is_compartment,division_level",
    [
        (False, DEPTH_TOP_BLOCK),        # a plain Block
        (True, DEPTH_TOP_COMPARTMENT),   # a Compartment
        (True, DEPTH_SUB),               # a Sub-Compartment
    ],
    ids=["block", "compartment", "sub_compartment"],
)
def test_forest_block_strips_degenerate_holes_regardless_of_layer(db, is_compartment, division_level):
    """User report, 2026-09-13: "not only in compartment but ... block,
    sub-areas, sub-compartment in all layers" -- blocks/compartments/
    sub-compartments are all the SAME `forest_blocks` table with ONE shared
    `@validates('geometry')` guard, so this was already true by construction;
    this test makes that explicit rather than leaving it implied."""
    calc = _make_calc(db)
    outer = _square(60, 60, 1.0)
    poly = Polygon(outer.exterior, [_needle_hole_ring(60.5, 60.5)])

    row = ForestBlock(
        calculation_id=calc.id,
        name="Test Row",
        geometry=from_shape(poly, srid=4326),
        area_hectares=1.0,
        index=0,
        is_compartment=is_compartment,
        division_level=division_level,
    )
    db.add(row)
    db.flush()

    stored = to_shape(row.geometry)
    assert stored.geom_type == "Polygon"
    assert len(stored.interiors) == 0


def test_forest_block_rejects_a_genuinely_multi_part_geometry(db):
    """@validates fires on attribute assignment, i.e. at construction time
    (the declarative base's default __init__ does setattr per kwarg) — so
    the raise happens here, before the row ever reaches the session."""
    calc = _make_calc(db)
    bundled = MultiPolygon([_square(10, 10), _square(20, 20)])

    with pytest.raises(MultiPartFeatureError):
        ForestBlock(
            calculation_id=calc.id,
            name="Test Block",
            geometry=from_shape(bundled, srid=4326),
            area_hectares=1.0,
            index=0,
        )


def test_forest_block_plain_polygon_write_is_unaffected(db):
    """The overwhelmingly common case -- a plain single Polygon -- must
    round-trip byte-for-byte identically; the guard must never touch it."""
    calc = _make_calc(db)
    solo = _square(30, 30)

    block = ForestBlock(
        calculation_id=calc.id,
        name="Plain Block",
        geometry=from_shape(solo, srid=4326),
        area_hectares=1.0,
        index=0,
    )
    db.add(block)
    db.flush()

    stored = to_shape(block.geometry)
    assert stored.equals(solo)


def test_forest_sub_area_auto_heals_a_sliver_bundled_geometry(db):
    calc = _make_calc(db)
    real = _square(40, 40)
    needle = _needle(50, 50)
    bundled = MultiPolygon([real, needle])

    sa = ForestSubArea(
        calculation_id=calc.id,
        name="Test Sub-Area",
        category="conservation",
        geometry=from_shape(bundled, srid=4326),
        area_hectares=1.0,
    )
    db.add(sa)
    db.flush()

    stored = to_shape(sa.geometry)
    assert stored.geom_type == "Polygon"


def test_forest_sub_area_rejects_a_genuinely_multi_part_geometry(db):
    calc = _make_calc(db)
    bundled = MultiPolygon([_square(40, 40), _square(50, 50)])

    with pytest.raises(MultiPartFeatureError):
        ForestSubArea(
            calculation_id=calc.id,
            name="Test Sub-Area",
            category="conservation",
            geometry=from_shape(bundled, srid=4326),
            area_hectares=1.0,
        )


# ---------------------------------------------------------------------------
# Calculation.result_data guard — sub-areas live ONLY in this JSONB blob
# (the ForestSubArea table above is effectively unused by current app code:
# nothing in the app constructs one outside its own class definition), so
# the ForestBlock/ForestSubArea ORM guards above do not actually protect the
# active sub-area storage. User report, 2026-09-13: "ensure it applies to
# ... sub-areas ... in all layers" — this is that guard, at the one choke
# point every result_data write already passes through.
# ---------------------------------------------------------------------------

def test_calculation_result_data_strips_a_degenerate_sub_area_hole():
    calc = Calculation()
    outer = _square(0, 0, 1.0)
    dirty = Polygon(outer.exterior, [_needle_hole_ring(0.5, 0.5)])

    calc.result_data = {"sub_areas": [{"id": "sa-1", "name": "Test", "geometry": mapping(dirty)}]}

    stored = shape(calc.result_data["sub_areas"][0]["geometry"])
    assert len(stored.interiors) == 0
    assert abs(stored.area - outer.area) < 1e-12


def test_calculation_result_data_ignores_a_genuinely_multi_part_sub_area():
    """A pre-existing structural multi-part sub-area is left untouched, not
    raised on — restructuring it into multiple entries is out of scope for
    this defensive, best-effort guard."""
    calc = Calculation()
    bundled = MultiPolygon([_square(0, 0), _square(5, 5)])

    calc.result_data = {"sub_areas": [{"id": "sa-1", "name": "Test", "geometry": mapping(bundled)}]}

    stored = shape(calc.result_data["sub_areas"][0]["geometry"])
    assert stored.geom_type == "MultiPolygon"


def test_calculation_result_data_passes_through_when_no_sub_areas():
    calc = Calculation()
    payload = {"blocks": [{"id": "b1"}], "total_blocks": 1}
    calc.result_data = payload
    assert calc.result_data == payload


def test_calculation_result_data_passes_through_a_clean_sub_area_unchanged():
    calc = Calculation()
    payload = {"sub_areas": [{"id": "sa-1", "name": "Test", "geometry": mapping(_square(0, 0))}]}
    calc.result_data = payload
    assert calc.result_data["sub_areas"][0]["geometry"] == mapping(_square(0, 0))
