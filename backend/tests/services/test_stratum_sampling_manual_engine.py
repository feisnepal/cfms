"""SS-1.3: the manual/intensity sampling engine (``create_sampling_design``)
enforces the same SFM कार्यविधि §16 stratum floors, per-stratum plot sizes,
and min-5 floor as the Guideline-2061 engine (SS-1.2, see
test_stratum_sampling_enforcement.py) — unconditionally, regardless of
sampling_type ('systematic'/'random') or whether SFM classification was
explicitly requested.

Exercises the polygon-based path (filter_tree_cover=False) so no raster
tables are required — the same setup as test_sampling_method_reporting.py.
"""

import json
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

BOUNDARY = box(83.4, 27.4, 83.6, 27.6)


def _user(db):
    u = User(
        email=f"ss13-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("TestPass123!"),
        full_name="SS-1.3 Test",
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_calc(db, name="SS-1.3 Forest"):
    u = _user(db)
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=u.id,
        forest_name=name,
        boundary_geom=shp_wkt.dumps(BOUNDARY),
        is_draft=True,
        result_data={},
    )
    db.add(calc)
    db.commit()
    return calc


def _add_block(
    db, calc, name, area_ha, index, *, orientation=None, working_circle=None, buf=-0.01
):
    kwargs = dict(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        block_name=name,
        compartment_code=None,
        geometry=shp_wkt.dumps(BOUNDARY.buffer(buf)),
        area_hectares=area_ha,
        index=index,
        is_compartment=False,
        division_level=1,
    )
    if orientation is not None:
        kwargs["management_orientation"] = orientation
    if working_circle is not None:
        kwargs["working_circle"] = working_circle
    db.add(ForestBlock(**kwargs))


def _multi_strata_calc(db):
    """One block per stratum, each with its own footprint so grid generation
    has room to place plots independently."""
    calc = _make_calc(db)
    _add_block(db, calc, "Prod-1", 5.0, 0, buf=-0.01)
    _add_block(db, calc, "Cons-1", 5.0, 1, orientation="Conservation", buf=-0.015)
    _add_block(db, calc, "Prot-1", 5.0, 2, working_circle="protection", buf=-0.02)
    db.commit()
    return calc


def _run(db, calc, **overrides):
    kwargs = dict(
        db=db,
        calculation_id=calc.id,
        sampling_type="systematic",
        sampling_intensity_percent=Decimal("2.0"),
        min_samples_per_block=5,
        min_samples_small_blocks=2,
        boundary_buffer_meters=0.0,
        filter_tree_cover=False,
        filter_slope=False,
        plot_shape="circular",
        plot_radius_meters=Decimal("12.6156"),
        preview=True,
    )
    kwargs.update(overrides)
    return svc.create_sampling_design(**kwargs)


def _floor_payload(exc):
    return json.loads(str(exc.value).split("SFM_INTENSITY_BELOW_FLOOR: ", 1)[1])


# ---------------------------------------------------------------------------
# Floor enforcement
# ---------------------------------------------------------------------------


def test_below_floor_on_production_block_rejects(db):
    """A production block asked to sample at 1.0% (< floor 2.0%) -> SFM_INTENSITY_BELOW_FLOOR."""
    calc = _make_calc(db)
    _add_block(db, calc, "Prod-1", 5.0, 0)
    db.commit()

    with pytest.raises(ValueError, match="SFM_INTENSITY_BELOW_FLOOR") as exc_info:
        _run(db, calc, sampling_intensity_percent=Decimal("1.0"))

    payload = _floor_payload(exc_info)
    assert payload["unit"] == "Prod-1"
    assert payload["stratum"] == "production"
    assert payload["floor"] == 2.0
    assert payload["value"] == 1.0


def test_at_floor_accepts(db):
    """Intensity exactly at the production floor (2.0%) is accepted."""
    calc = _make_calc(db)
    _add_block(db, calc, "Prod-1", 5.0, 0)
    db.commit()

    resp = _run(db, calc, sampling_intensity_percent=Decimal("2.0")).response
    assert resp.total_blocks == 1
    assert resp.blocks_info[0].stratum == "production"
    assert float(resp.blocks_info[0].floor_intensity_pct) == 2.0


def test_conservation_block_accepts_one_percent_via_override(db):
    """A conservation block overridden to exactly its floor (1.0%) is accepted
    even though the global intensity (2.0%) would also satisfy it -- proves the
    per-block override path is checked against the per-block stratum floor,
    not the global value."""
    calc = _make_calc(db)
    _add_block(db, calc, "Cons-1", 5.0, 0, orientation="Conservation")
    db.commit()

    resp = _run(
        db,
        calc,
        block_overrides={"Cons-1": {"sampling_intensity_percent": 1.0}},
    ).response
    info = resp.blocks_info[0]
    assert info.stratum == "conservation"
    assert float(info.floor_intensity_pct) == 1.0
    assert info.plot_size_sqm == 500


def test_conservation_block_override_below_floor_rejects(db):
    """A conservation block overridden to 0.5% (< its 1.0% floor) is rejected,
    even though 0.5% would be legal for a protection stratum."""
    calc = _make_calc(db)
    _add_block(db, calc, "Cons-1", 5.0, 0, orientation="Conservation")
    db.commit()

    with pytest.raises(ValueError, match="SFM_INTENSITY_BELOW_FLOOR") as exc_info:
        _run(
            db,
            calc,
            block_overrides={"Cons-1": {"sampling_intensity_percent": 0.5}},
        )
    payload = _floor_payload(exc_info)
    assert payload["unit"] == "Cons-1"
    assert payload["stratum"] == "conservation"
    assert payload["floor"] == 1.0


def test_protection_block_accepts_half_percent(db):
    """A protection-working-circle block at exactly its 0.5% floor is accepted
    and reports the enforced 100 m² plot size."""
    calc = _make_calc(db)
    _add_block(db, calc, "Prot-1", 5.0, 0, working_circle="protection")
    db.commit()

    resp = _run(db, calc, sampling_intensity_percent=Decimal("0.5")).response
    info = resp.blocks_info[0]
    assert info.stratum == "protection"
    assert float(info.floor_intensity_pct) == 0.5
    assert info.plot_size_sqm == 100


def test_random_mode_same_floors_apply(db):
    """Floor enforcement is engine-agnostic within create_sampling_design --
    the 'random' sampling_type is rejected below the production floor too."""
    calc = _make_calc(db)
    _add_block(db, calc, "Prod-1", 5.0, 0)
    db.commit()

    with pytest.raises(ValueError, match="SFM_INTENSITY_BELOW_FLOOR"):
        _run(
            db, calc, sampling_type="random", sampling_intensity_percent=Decimal("1.5")
        )

    resp = _run(
        db, calc, sampling_type="random", sampling_intensity_percent=Decimal("2.0")
    ).response
    assert resp.total_blocks == 1


# ---------------------------------------------------------------------------
# Per-stratum plot size
# ---------------------------------------------------------------------------


def test_per_stratum_plot_size_in_block_info(db):
    """production/conservation get 500 m² plots, protection gets 100 m²."""
    calc = _multi_strata_calc(db)
    resp = _run(db, calc).response
    blocks = {b.block_name: b for b in resp.blocks_info}

    assert blocks["Prod-1"].plot_size_sqm == 500
    assert blocks["Cons-1"].plot_size_sqm == 500
    assert blocks["Prot-1"].plot_size_sqm == 100


# ---------------------------------------------------------------------------
# Sub-MMU exemption (P8 §8.1, 2026-09-28) — amends D4 of 2026-09-15
# ---------------------------------------------------------------------------
#
# HISTORY, because the change reads as a reversal and is not a simple one.
#
# D4 (2026-09-15) removed the old "<1 ha -> 2-plot exception" and applied a flat
# 5-plot floor to *every* unit regardless of area, on the reading that the guideline
# floor admits no size exemption. `test_tiny_block_gets_five_not_two_samples` pinned
# that with a 0.3 ha block.
#
# P8 §8.1 (2026-09-28, owner-approved) reinstates an exemption, but only for units
# **below the absolute MMU** (1 ha), and on a different argument: a sub-MMU unit is not
# a management unit, so the per-unit minimum does not apply to it. A 0.3 ha unit cannot
# hold 5 x 500 m2 production plots (that needs 0.25 ha *plus* the 50 m boundary
# buffer), and the buffer falls back to the original polygon when it empties the
# shape, so the plots land on the boundary. D4's real purpose — the removal of the
# *2-plot* exception — is untouched: a unit at or above the MMU still gets 5, never 2.
#
# So the amendment is narrow: D4 still holds from 1 ha upward; below 1 ha the floor no
# longer applies, and the unit is reported as `mmu_exempt` with a reason.


def test_sub_mmu_block_is_exempt_from_the_five_plot_floor(db):
    """A 0.3 ha block - below the 1 ha MMU - gets 0 plots and says why.

    This is the test that used to assert the opposite. The flip is deliberate; see
    the history note above.

    A sound unit is added alongside: a design in which *every* unit is exempt
    produces no points at all, and the engine correctly refuses an empty design with
    NO_POINTS_GENERATED rather than storing a blank one.
    """
    calc = _make_calc(db)
    _add_block(db, calc, "Tiny-1", 0.3, 0)
    _add_block(db, calc, "Prod-1", 5.0, 1, buf=-0.01)
    db.commit()

    blocks = {b.block_name: b for b in _run(db, calc, min_samples_small_blocks=2).response.blocks_info}
    info = blocks["Tiny-1"]
    assert info.mmu_exempt is True
    assert info.samples_generated == 0
    assert info.minimum_enforced is False
    assert info.mmu_exempt_reason and "MMU" in info.mmu_exempt_reason
    # And the sound unit is untouched.
    assert blocks["Prod-1"].mmu_exempt is False
    assert blocks["Prod-1"].samples_generated >= 5


def test_block_just_above_the_mmu_still_gets_five_not_two(db):
    """D4's purpose survives: from 1 ha up, the floor is 5 and never 2."""
    calc = _make_calc(db)
    _add_block(db, calc, "Small-1", 1.5, 0)
    db.commit()

    info = _run(db, calc, min_samples_small_blocks=2).response.blocks_info[0]
    assert info.mmu_exempt is False
    assert info.samples_generated >= 5
    assert info.minimum_enforced is True


def test_sub_mmu_block_can_be_opted_in_by_raising_its_minimum(db):
    """Asking for more than the guideline floor is never accidental, so it opts in."""
    calc = _make_calc(db)
    _add_block(db, calc, "Tiny-1", 0.3, 0)
    db.commit()

    info = _run(db, calc, min_samples_per_block=8).response.blocks_info[0]
    assert info.mmu_exempt is False
    assert info.samples_generated >= 8


def test_sub_mmu_exemption_can_be_switched_off(db):
    """`exempt_sub_mmu_units=False` restores the D4 behaviour for every unit."""
    calc = _make_calc(db)
    _add_block(db, calc, "Tiny-1", 0.3, 0)
    db.commit()

    info = _run(
        db, calc, min_samples_small_blocks=2, exempt_sub_mmu_units=False
    ).response.blocks_info[0]
    assert info.mmu_exempt is False
    assert info.samples_generated >= 5


def test_min_samples_per_block_override_may_only_raise_floor(db):
    """A caller-requested min_samples_per_block above 5 still applies (raises
    the floor further); one below 5 is silently floored at 5, never lower."""
    calc = _make_calc(db)
    _add_block(db, calc, "Prod-1", 1.5, 0)
    db.commit()

    resp_low = _run(db, calc, min_samples_per_block=1).response
    assert resp_low.blocks_info[0].samples_generated >= 5

    resp_high = _run(db, calc, min_samples_per_block=8).response
    assert resp_high.blocks_info[0].samples_generated >= 8


def test_enforce_min_samples_production_false_lets_caller_go_below_five(db):
    """enforce_min_samples_production=False (owner request, 2026-09-15,
    refined the same day to be per-stratum) drops the कार्यविधि §16 flat
    5-plot floor entirely for Production units -- the caller's own
    min_samples_per_block becomes the true floor, even below 5."""
    calc = _make_calc(db)
    _add_block(db, calc, "Tiny-1", 1.5, 0)  # defaults to production stratum
    db.commit()

    resp = _run(
        db, calc, min_samples_per_block=1, enforce_min_samples_production=False
    ).response
    info = resp.blocks_info[0]
    assert info.samples_generated < 5
    assert info.samples_generated == 1


def test_enforce_min_samples_is_independent_per_stratum(db):
    """Disabling the floor for Production must not affect Conservation or
    Protection units in the same design (D2, 2026-09-15)."""
    calc = _make_calc(db)
    _add_block(db, calc, "Prod-1", 1.5, 0, buf=-0.01)
    _add_block(db, calc, "Cons-1", 1.5, 1, orientation="Conservation", buf=-0.015)
    _add_block(db, calc, "Prot-1", 1.5, 2, working_circle="protection", buf=-0.02)
    db.commit()

    resp = _run(
        db,
        calc,
        min_samples_per_block=1,
        enforce_min_samples_production=False,
    ).response
    blocks = {b.block_name: b for b in resp.blocks_info}

    assert blocks["Prod-1"].samples_generated < 5
    assert blocks["Cons-1"].samples_generated >= 5
    assert blocks["Prot-1"].samples_generated >= 5


def test_enforce_min_samples_true_is_the_default(db):
    """Not passing enforce_min_samples at all still applies the guideline
    floor (default True) -- existing callers are unaffected."""
    calc = _make_calc(db)
    _add_block(db, calc, "Tiny-1", 1.5, 0)
    db.commit()

    resp = _run(db, calc, min_samples_per_block=1).response
    assert resp.blocks_info[0].samples_generated >= 5
