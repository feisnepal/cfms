"""Classification-driven (stratified) Guideline-2061 sampling
(SLOPE_COMPARTMENT_AND_STRATIFIED_SAMPLING_PLAN, Part B).

`per_block_intensity` lets a caller (the Sampling tab, fed from SFM's
Production/Conservation/Protection classification) override
`productive_intensity` for named blocks only, in a single design — reusing the
per-block loop `create_sampling_design_guideline_2061` already runs, rather
than a new engine. 2.0% (SFM's Production tier, कार्यविधि §16) is also now a
valid intensity, exercised without touching the DoF lookup table (which
doesn't exist in the test DB — see test_sampling_preview.py's identical
monkeypatch note) since anything outside {0.5, 1.0, 0.1} always falls back to
the manual `area * intensity / plot_size` formula, DB-query-free.
"""
import uuid
from decimal import Decimal

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole, UserStatus
from app.services import sampling as svc
from app.utils.auth import hash_password


def _user(db):
    u = User(
        email=f"strat-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("TestPass123!"),
        full_name="Stratified Test",
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _setup_two_equal_blocks(db):
    """Two same-area, non-overlapping blocks so intensity differences show up
    as a clean sample-count difference, not an area-driven one.

    Kept deliberately small (~0.01deg per side, ~98 ha - matching
    test_sampling_preview.py's guideline fixture): the guideline engine
    derives productive area from the actual block GEOMETRY, not the DB
    area_hectares column, so a large test polygon at 1-2% intensity would
    request thousands of systematic-grid plots and hang the test.
    """
    u = _user(db)
    small_boundary = box(83.480, 27.495, 83.510, 27.505)
    calc = Calculation(
        id=uuid.uuid4(), user_id=u.id, forest_name="Stratified Forest",
        boundary_geom=shp_wkt.dumps(small_boundary), is_draft=True, result_data={},
    )
    db.add(calc)
    left = box(83.480, 27.495, 83.494, 27.505)
    right = box(83.496, 27.495, 83.510, 27.505)
    for i, geom in enumerate([left, right]):
        db.add(ForestBlock(
            id=uuid.uuid4(), calculation_id=calc.id, name=f"Block-{i+1}",
            block_name=f"Block-{i+1}", compartment_code=None,
            geometry=shp_wkt.dumps(geom), area_hectares=100.0, index=i,
            is_compartment=False, division_level=1,
            management_orientation="Conservation" if i == 1 else None,
        ))
    db.commit()
    return calc


def _run(db, calc, productive_intensity, per_block_intensity=None, preview=True):
    return svc.create_sampling_design_guideline_2061(
        db=db, calculation_id=calc.id, preview=preview,
        productive_intensity=productive_intensity, sample_protected_zone=False,
        plot_size_sqm=500, plot_shape="circular",
        filter_tree_cover=False, filter_slope=False,
        boundary_buffer_meters=0.0,
        per_block_intensity=per_block_intensity,
    )


@pytest.fixture(autouse=True)
def _stub_guideline_lookup(monkeypatch):
    """The DoF lookup table doesn't exist in the test DB (see
    test_sampling_preview.py); every test here exercises the manual-fallback
    arithmetic instead via a deterministic stand-in, matching the established
    pattern rather than depending on which intensity happens to skip the
    table lookup."""
    monkeypatch.setattr(
        svc, "get_sample_count_from_guideline",
        lambda db, block_area_hectares, intensity_percent, plot_size_sqm:
            max(1, round(block_area_hectares * intensity_percent / 0.05)),
    )


def _counts_by_block(resp):
    return {info.block_name: info.samples_generated for info in resp.blocks_info}


def test_per_block_intensity_overrides_named_block(db):
    calc = _setup_two_equal_blocks(db)
    result = _run(db, calc, productive_intensity=2.0,
                  per_block_intensity={"Block-2": 1.0})
    counts = _counts_by_block(result.response)
    # Block-1 sampled at the 2.0% production floor should get roughly double
    # Block-2's 1.0% conservation-floor count (equal area, same plot size — the
    # stub is a pure area*intensity formula).
    assert counts["Block-1"] > counts["Block-2"]
    assert counts["Block-1"] == pytest.approx(counts["Block-2"] * 2, rel=0.15)


def test_per_block_intensity_falls_back_for_unnamed_block(db):
    calc = _setup_two_equal_blocks(db)
    # Only Block-2 named -> Block-1 (unnamed) must still use the global 2.0%.
    with_override = _run(db, calc, productive_intensity=2.0,
                         per_block_intensity={"Block-2": 1.0})
    baseline = _run(db, calc, productive_intensity=2.0, per_block_intensity=None)
    c1 = _counts_by_block(with_override.response)
    c2 = _counts_by_block(baseline.response)
    assert c1["Block-1"] == c2["Block-1"]


def test_two_percent_is_now_a_valid_global_intensity(db):
    calc = _setup_two_equal_blocks(db)
    result = _run(db, calc, productive_intensity=2.0)
    assert result.response.total_points > 0
    for info in result.response.blocks_info:
        assert info.actual_intensity_percent > 0


def test_invalid_per_block_intensity_names_the_block(db):
    # Any production intensity above 0 is valid (owner, 2026-10-02: 2.5 / 3.7 are fine; 2026-10-08: above 5 % is only a warning);
    # a value that is not above 0 is rejected, and the error must name the block.
    calc = _setup_two_equal_blocks(db)
    with pytest.raises(ValueError, match="Block-1"):
        _run(db, calc, productive_intensity=2.0,
             per_block_intensity={"Block-1": -1.0})


def test_an_intensity_above_the_usual_ceiling_is_accepted_not_refused(db):
    calc = _setup_two_equal_blocks(db)
    result = _run(db, calc, productive_intensity=2.0, per_block_intensity={"Block-1": 7.5})
    assert result.response.total_points > 0


def test_a_decimal_per_block_intensity_up_to_the_ceiling_is_accepted(db):
    calc = _setup_two_equal_blocks(db)
    result = _run(db, calc, productive_intensity=2.0, per_block_intensity={"Block-1": 3.7})
    assert result.response.total_points > 0


def test_no_per_block_intensity_matches_pre_existing_behaviour(db):
    """Omitting per_block_intensity entirely must reproduce the old flat
    behaviour byte-for-byte (both blocks equal, since they're equal area)."""
    calc = _setup_two_equal_blocks(db)
    result = _run(db, calc, productive_intensity=2.0, per_block_intensity=None)
    counts = _counts_by_block(result.response)
    assert counts["Block-1"] == counts["Block-2"]


def test_preview_and_create_agree_on_stratified_point_count(db):
    calc = _setup_two_equal_blocks(db)
    per_block = {"Block-2": 1.0}
    preview_result = _run(db, calc, productive_intensity=2.0,
                           per_block_intensity=per_block, preview=True)
    create_result = _run(db, calc, productive_intensity=2.0,
                          per_block_intensity=per_block, preview=False)
    assert preview_result.response.total_points == create_result.total_points


def test_zero_intensity_excludes_the_unit_and_places_no_plots(db):
    """0% is the owner's "do not sample this unit" (2026-10-03): allowed below
    the stratum floor, recorded as user_excluded, other units unaffected."""
    calc = _setup_two_equal_blocks(db)
    result = _run(db, calc, productive_intensity=2.0,
                  per_block_intensity={"Block-2": 0})
    info = {i.block_name: i for i in result.response.blocks_info}
    assert info["Block-2"].user_excluded is True
    assert info["Block-2"].samples_generated == 0
    assert info["Block-1"].user_excluded is False
    assert info["Block-1"].samples_generated > 0


def test_zero_intensity_on_every_unit_is_refused(db):
    calc = _setup_two_equal_blocks(db)
    with pytest.raises(ValueError, match="0%"):
        _run(db, calc, productive_intensity=2.0,
             per_block_intensity={"Block-1": 0, "Block-2": 0})
