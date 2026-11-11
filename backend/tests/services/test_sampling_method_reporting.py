"""Unit tests for the intensity engine's honest 'sampling_method' reporting
and systematic grid behaviour (SAMPLING_PAGE_REWORK bug: random showed 'Systematic').

Exercises the polygon-based path (filter_tree_cover=False) so no raster tables
are required; per-block sampling_method must reflect the requested type.
"""
import uuid
from decimal import Decimal

from shapely import wkt as shp_wkt
from shapely.geometry import box
from shapely.affinity import rotate

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole, UserStatus
from app.services import sampling as svc
from app.utils.auth import hash_password

BOUNDARY = box(83.4, 27.4, 83.6, 27.6)


def _user(db):
    u = User(
        email=f"honest-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("TestPass123!"),
        full_name="Honest Test",
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _setup(db):
    u = _user(db)
    calc = Calculation(
        id=uuid.uuid4(), user_id=u.id, forest_name="Honest Forest",
        boundary_geom=shp_wkt.dumps(BOUNDARY), is_draft=True,
    )
    db.add(calc)
    for i, geom in enumerate([BOUNDARY.buffer(-0.01), BOUNDARY.buffer(-0.015)]):
        db.add(ForestBlock(
            id=uuid.uuid4(), calculation_id=calc.id, name=f"Block-{i+1}",
            block_name=f"Block-{i+1}", compartment_code=None,
            geometry=shp_wkt.dumps(geom), area_hectares=5.0, index=i,
            is_compartment=False, division_level=1,
        ))
    db.commit()
    return calc


def _run(db, calc, sampling_type):
    return svc.create_sampling_design(
        db=db, calculation_id=calc.id,
        sampling_type=sampling_type,
        sampling_intensity_percent=Decimal("2.0"),
        min_samples_per_block=5, min_samples_small_blocks=2,
        boundary_buffer_meters=0.0,
        filter_tree_cover=False, filter_slope=False,
        plot_shape="circular", plot_radius_meters=Decimal("12.6156"),
    )


def test_systematic_blocks_report_systematic(db):
    calc = _setup(db)
    resp = _run(db, calc, "systematic")
    for info in resp.blocks_info:
        assert info.sampling_method == "systematic"
    assert resp.sampling_type == "systematic"


def test_random_blocks_report_random_not_systematic(db):
    # Regression: per-unit method was never set -> frontend showed 'Systematic'.
    calc = _setup(db)
    resp = _run(db, calc, "random")
    for info in resp.blocks_info:
        assert info.sampling_method == "random"
    assert resp.sampling_type == "random"


def _elongated_setup(db):
    """A thin diagonal strip whose bounding box is much larger than the polygon —
    the exact geometry shape that caused full-area systematic under-generation
    (grid spacing deduced from area assumed a square bbox; most cells fell outside
    the strip, leaving 0.7% actual instead of 2% requested)."""
    u = _user(db)
    calc = Calculation(
        id=uuid.uuid4(), user_id=u.id, forest_name="Elongated Forest",
        boundary_geom=shp_wkt.dumps(BOUNDARY), is_draft=True,
    )
    db.add(calc)
    strip = box(83.45, 27.49, 83.55, 27.4925)  # ~9.8km x 0.28km
    diagonal = rotate(strip, 45, origin=(83.5, 27.49125))
    # Correct area ≈ 543 ha; use a value consistent with degrees->meters approx
    area_ha = 543.0
    db.add(ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="E1",
        block_name="E1", compartment_code=None,
        geometry=shp_wkt.dumps(diagonal), area_hectares=area_ha, index=0,
        is_compartment=False, division_level=1,
    ))
    db.commit()

    # Sanity: the polygon must NOT fill its bounding box (the bug trigger)
    minx, miny, maxx, maxy = diagonal.bounds
    bbox_area_deg = (maxx - minx) * (maxy - miny)
    poly_area_deg = diagonal.area
    assert poly_area_deg < bbox_area_deg * 0.4, "test polygon must be elongated/non-filling"
    return calc


def test_systematic_full_area_reaches_requested_intensity(db):
    """Regression: Full Area (filter_tree_cover=False) systematic on an elongated
    polygon must produce ~samples_for_block points (actual % ≈ requested), not a
    tiny fraction. Old code used one grid pass at spacing=sqrt(area/n) which
    dropped most points outside the polygon (0.7% actual vs 2% requested)."""
    calc = _elongated_setup(db)
    resp = svc.create_sampling_design(
        db=db, calculation_id=calc.id,
        sampling_type="systematic",
        sampling_intensity_percent=Decimal("2.0"),
        min_samples_per_block=5, min_samples_small_blocks=2,
        boundary_buffer_meters=50.0,
        filter_tree_cover=False, filter_slope=False,
        plot_shape="circular", plot_radius_meters=Decimal("12.6156"),
    )
    assert len(resp.blocks_info) == 1
    info = resp.blocks_info[0]
    # 2% of 543ha / 0.05ha plots ≈ 21.7 → 21 samples from intensity (> min 5)
    expected = int(543.0 * 0.02 / 0.05)
    assert expected >= 10
    assert info.samples_generated >= expected, (
        f"full-area systematic under-generated: {info.samples_generated} samples "
        f"(actual {float(info.actual_intensity_percent):.2f}%) vs {expected} expected"
    )
    assert float(info.actual_intensity_percent) >= 1.5


def _min_pair_distance(points):
    import itertools
    best = float("inf")
    for (ax, ay), (bx, by) in itertools.combinations(points, 2):
        d = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
        best = min(best, d)
    return best


def test_tree_cover_top_up_spreads_pixels_not_scan_order():
    """Regression: tree-cover systematic top-up must even-pick across the
    spatially-sorted unclaimed pixels, NOT slice raster-scan-adjacent pixels.
    Old code returned [pixel_points[:needed]] whose consecutive entries are
    physically adjacent ~10m pixels — those plots clustered and, numbered in
    list order, looked like a blotch (user report "8,9,10,11,12 / 93,94,95 all
    very close together"). The residual plots must stay spread."""
    # block_points clustered at the origin (the under-filled part)
    block_points = [(0.0, 0.0), (0.0001, 0.0001)]
    # raster-scan-ordered unclaimed pixels: 10 rows of 10 adjacent points
    pixel_points = [
        (0.001 + col * 0.0001, 0.001 + row * 0.0001)
        for row in range(10) for col in range(10)
    ]
    need = 4
    top = svc._top_up_pixels(block_points, pixel_points, len(block_points) + need)
    assert len(top) == need

    # Old scan-order slice took rows 0..3 all at lat=0.001: all 4 points are
    # within the same lat band (min pair distance < 2 cells apart).
    old_scan = pixel_points[:need]
    assert _min_pair_distance(old_scan) < 0.0002, "sanity: old slice is clustered"

    # New even-pick spans the whole 10x10 field: min pair distance must exceed
    # the old cluster width (a few cells) — points tile the area, not a band.
    assert _min_pair_distance(top) > 0.0004, (
        f"top-up still clustered: min pair dist {_min_pair_distance(top):.6f}"
    )

    # And every top-up pixel must be an unclaimed one (no duplicates with base).
    seen = set(block_points)
    assert all(p not in seen for p in top)
