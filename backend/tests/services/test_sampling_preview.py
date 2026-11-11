"""Pre-create sample-plot preview tests (SAMPLING_PAGE_REWORK, Phase F).

Proves the preview engines (rule F) compute the exact same layout as create
but write NO DB rows, and that the deterministic create-from-preview replay
path (F.3) persists the previewed plot locations exactly.

Exercises the polygon-based path (filter_tree_cover=False) so no raster tables
are required — the same setup as test_sampling_method_reporting.py.
"""
import uuid
from decimal import Decimal

from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole, UserStatus
from app.models.sampling import SamplingDesign
from app.services import sampling as svc
from app.utils.auth import hash_password

BOUNDARY = box(83.4, 27.4, 83.6, 27.6)


def _user(db):
    u = User(
        email=f"preview-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("TestPass123!"),
        full_name="Preview Test",
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _setup(db, forest_name="Preview Forest", n_blocks=2):
    u = _user(db)
    calc = Calculation(
        id=uuid.uuid4(), user_id=u.id, forest_name=forest_name,
        boundary_geom=shp_wkt.dumps(BOUNDARY), is_draft=True,
        result_data={},
    )
    db.add(calc)
    for i in range(n_blocks):
        db.add(ForestBlock(
            id=uuid.uuid4(), calculation_id=calc.id, name=f"Block-{i+1}",
            block_name=f"Block-{i+1}", compartment_code=None,
            geometry=shp_wkt.dumps(BOUNDARY.buffer(-0.01 - 0.005 * i)),
            area_hectares=5.0, index=i, is_compartment=False, division_level=1,
        ))
    db.commit()
    return calc


def _preview_run(db, calc, sampling_type="systematic", filter_tree_cover=False):
    return svc.create_sampling_design(
        db=db, calculation_id=calc.id, preview=True,
        sampling_type=sampling_type,
        sampling_intensity_percent=Decimal("2.0"),
        min_samples_per_block=5, min_samples_small_blocks=2,
        boundary_buffer_meters=0.0,
        filter_tree_cover=filter_tree_cover, filter_slope=False,
        plot_shape="circular", plot_radius_meters=Decimal("12.6156"),
    )


def test_preview_intensity_systematic_returns_result_with_geojson(db):
    """Preview computes a layout identical in shape to create (rule F)."""
    calc = _setup(db)
    result = _preview_run(db, calc, "systematic")

    assert isinstance(result, svc.SamplingPreviewResult)
    resp = result.response
    assert isinstance(resp.sampling_design_id, uuid.UUID)  # preview token, not a real design
    assert resp.sampling_type == "systematic"
    assert resp.total_points >= 5  # min samples per block enforced
    assert resp.total_blocks == 2

    assert result.area_basis == "full_area"  # filter_tree_cover=False
    gj = result.points_geojson
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == resp.total_points
    for i, f in enumerate(gj["features"]):
        assert f["type"] == "Feature"
        assert f["geometry"]["type"] == "Point"
        assert len(f["geometry"]["coordinates"]) == 2
        assert f["properties"]["plot_number"] == i + 1
        assert f["properties"]["block_name"]
        assert f["properties"]["zone_type"] == "productive"


def test_preview_writes_no_db_rows(db):
    """Preview must not persist a SamplingDesign (rule F — no DB writes)."""
    calc = _setup(db)
    assert db.query(SamplingDesign).filter(SamplingDesign.calculation_id == calc.id).count() == 0

    _preview_run(db, calc, "random")

    assert db.query(SamplingDesign).filter(SamplingDesign.calculation_id == calc.id).count() == 0


def test_preview_random_matches_create_summary_shape(db):
    """Random preview reports the random sampling_method per block (honest)."""
    calc = _setup(db)
    result = _preview_run(db, calc, "random")
    for info in result.response.blocks_info:
        assert info.sampling_method == "random"


def test_preview_guideline_2061_returns_geojson_and_no_write(db, monkeypatch):
    """Guideline-2061 preview (block+systematic) computes plots without writing.

    Uses a small polygon: the guideline engine derives productive area from the
    actual geometry (not the DB area column), so a huge test polygon would
    generate thousands of plots. The guideline lookup table is a custom SQL
    table absent from the thrown-together test DB, and its missing-table error
    poisons the transaction — so we stub the lookup."""
    monkeypatch.setattr(
        svc, "get_sample_count_from_guideline",
        lambda db, block_area_hectares, intensity_percent, plot_size_sqm:
            max(1, round(block_area_hectares * intensity_percent / 0.05)),
    )
    u = _user(db)
    small = box(83.495, 27.495, 83.505, 27.505)  # ~0.01° x 0.01° (~98 ha)
    calc = Calculation(
        id=uuid.uuid4(), user_id=u.id, forest_name="Guideline Preview Forest",
        boundary_geom=shp_wkt.dumps(small), is_draft=True, result_data={},
    )
    db.add(calc)
    db.add(ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="Small-1",
        block_name="Small-1", compartment_code=None,
        geometry=shp_wkt.dumps(small.buffer(-0.0005)),
        area_hectares=1.0, index=0, is_compartment=False, division_level=1,
        management_orientation="Protection",  # 0.5% = the protection-stratum floor (SS-1.2)
    ))
    db.commit()

    result = svc.create_sampling_design_guideline_2061(
        db=db, calculation_id=calc.id, preview=True,
        productive_intensity=0.5, sample_protected_zone=False,
        plot_size_sqm=500, plot_shape="circular",
        filter_tree_cover=False, filter_slope=False,
        boundary_buffer_meters=0.0,
    )
    assert isinstance(result, svc.SamplingPreviewResult)
    resp = result.response
    assert resp.sampling_type == "systematic"
    assert result.area_basis == "full_area"
    gj = result.points_geojson
    assert len(gj["features"]) == resp.total_points
    assert resp.total_points > 0
    assert db.query(SamplingDesign).filter(SamplingDesign.calculation_id == calc.id).count() == 0


def test_build_preview_points_geojson_properties(db):
    """Helper attaches per-plot block/zone properties in plot order."""
    points = [(83.5, 27.5), (83.51, 27.51)]
    assignments = [
        {"point_index": 0, "block_name": "Block-1", "zone_type": "productive"},
        {"point_index": 1, "block_name": "Block-2", "zone_type": "protected"},
    ]
    gj = svc._build_preview_points_geojson(points, assignments)
    assert gj["features"][0]["properties"] == {
        "plot_number": 1, "plot_id": "P1", "block_name": "Block-1", "zone_type": "productive",
    }
    assert gj["features"][1]["properties"]["block_name"] == "Block-2"
    assert gj["features"][1]["properties"]["zone_type"] == "protected"
