"""P8 §8.1 - the exemption, exercised through the real engine.

The unit tests in ``test_sampling_mmu_exemption`` factor out the floor expression
so the rule can be pinned cheaply. That is a *mirror*, though, and a mirror can
drift from the thing it mirrors. This file calls ``create_sampling_design`` for
real, on a forest that contains a genuine sub-MMU sliver, and checks the plots
actually placed - which is the only way to know the edit landed in the engine and
not merely in a test.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserStatus
from app.services.sampling import create_sampling_design

SQM_PER_HA = 10_000.0

# Real geometry, in DEGREES (SRID 4326), in the Chure hills so the geodesic area
# computation behaves as it does for the real forest.
#
# An earlier version of this fixture used box(0, 0, 200, 100), which is 200 degrees
# of longitude by 100 degrees of latitude - latitude beyond 90 is not a place, and
# the engine's area came back NaN. Metres-per-degree at ~28 N: 1 deg lat ~ 110.9 km,
# 1 deg lon ~ 98 km. So 200 m ~ 0.00180 deg lon, 100 m ~ 0.00090 deg lat, 18 m ~
# 0.00016 deg lon, 10 m ~ 0.00009 deg lat.
M_PER_DEG_LAT = 110_900.0
M_PER_DEG_LON = 98_000.0
LON0, LAT0 = 84.0, 28.5


def _m_box(x_m, y_m, w_m, h_m):
    """A box of w x h metres at an offset in metres from the fixture origin."""
    return box(
        LON0 + x_m / M_PER_DEG_LON,
        LAT0 + y_m / M_PER_DEG_LAT,
        LON0 + (x_m + w_m) / M_PER_DEG_LON,
        LAT0 + (y_m + h_m) / M_PER_DEG_LAT,
    )


BIG = _m_box(0, 0, 200, 100)      # 2.00 ha
BIG2 = _m_box(200, 0, 200, 100)   # 2.00 ha, touching BIG on its eastern edge
SLIVER = _m_box(200, 100, 18, 10)  # 0.018 ha = 180 m2, on the shared edge

# Areas are stated, not derived. Deriving them from the geometry is wrong in
# degrees: a 200 m x 100 m box is 1.6e-6 square DEGREES, and dividing that by
# 10,000 gives ~1.6e-10 ha - so the "2 ha" units were being stored as sub-MMU and
# the exemption correctly caught them. The engine compares against the stored
# `area_hectares`, so that column must carry the real area.
UNITS = [("BIG-1", BIG, 2.0), ("BIG-2", BIG2, 2.0), ("SLIVER", SLIVER, 0.018)]


def _ha(geom) -> float:
    return geom.area / SQM_PER_HA


@pytest.fixture
def forest(db):
    user = User(
        id=uuid.uuid4(),
        email=f"p8-81-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        full_name="P8 8.1",
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user.id,
        forest_name="P8 8.1 fixture",
        result_data={"area_hectares": 4.0},
    )
    db.add(calc)
    db.flush()
    for i, (name, geom, area_ha) in enumerate(UNITS):
        db.add(
            ForestBlock(
                id=uuid.uuid4(),
                calculation_id=calc.id,
                name=name,
                block_name=name,
                geometry=from_shape(geom, srid=4326),
                area_hectares=area_ha,
                index=i,
                is_compartment=False,
                division_level=1,
            )
        )
    db.commit()
    try:
        yield db, calc
    finally:
        db.query(Calculation).filter(Calculation.id == calc.id).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        db.commit()


def _design(db, calc, **kwargs):
    params = dict(
        sampling_type="systematic",
        sampling_intensity_percent=2.0,
        min_samples_per_block=5,
        min_samples_small_blocks=2,
        filter_tree_cover=False,
        filter_slope=False,
    )
    params.update(kwargs)
    return create_sampling_design(
        db=db, calculation_id=calc.id, preview=True, **params
    )


def _by_name(result) -> dict:
    return {b.block_name: b for b in result.response.blocks_info}


def test_sliver_receives_no_plots_under_the_exemption(forest):
    """The headline behaviour: 0 plots, not 5 boundary plots."""
    db, calc = forest
    by_name = _by_name(_design(db, calc))
    sliver = by_name["SLIVER"]
    assert sliver.samples_generated == 0, (
        "a sub-MMU unit must not be forced to carry the flat per-unit minimum"
    )
    assert sliver.mmu_exempt is True
    assert sliver.mmu_exempt_reason and "MMU" in sliver.mmu_exempt_reason
    assert "500 m2" in sliver.mmu_exempt_reason


def test_an_exempt_unit_is_never_reported_as_minimum_enforced(forest):
    """Nothing was enforced on it, so saying so would be a lie in the payload."""
    db, calc = forest
    assert _by_name(_design(db, calc))["SLIVER"].minimum_enforced is False


def test_units_above_the_mmu_keep_the_flat_floor(forest):
    """The load-bearing check: the exemption must not spread."""
    db, calc = forest
    by_name = _by_name(_design(db, calc))
    for name in ("BIG-1", "BIG-2"):
        unit = by_name[name]
        assert unit.mmu_exempt is False
        assert unit.samples_generated >= 5, f"{name} lost the flat per-unit minimum"


def test_switching_the_exemption_off_restores_the_floor(forest):
    """`exempt_sub_mmu_units=False` is the escape hatch the plan requires."""
    db, calc = forest
    by_name = _by_name(_design(db, calc, exempt_sub_mmu_units=False))
    sliver = by_name["SLIVER"]
    assert sliver.mmu_exempt is False
    # And the floor is genuinely applied again - even if placement then fails, the
    # unit is no longer exempt and the payload must not claim a zero by policy.
    assert sliver.minimum_enforced is True or sliver.samples_generated > 0


def test_an_explicit_override_opts_the_sliver_back_in(forest):
    """The owner's way to say "sample it anyway"."""
    db, calc = forest
    by_name = _by_name(
        _design(db, calc, block_overrides={"SLIVER": {"min_samples_per_block": 5}})
    )
    sliver = by_name["SLIVER"]
    assert sliver.mmu_exempt is False


def test_the_exemption_is_visible_on_every_unit_payload(forest):
    """Visible and reproducible, not a silent behaviour change.

    ``default_parameters`` lives on the persisted ``SamplingDesign``, not on
    ``SamplingGenerateResponse``, so the per-unit payload is where a preview can
    see it: every unit reports ``mmu_exempt``, true or false, and the exempt ones
    carry a reason.
    """
    db, calc = forest
    by_name = _by_name(_design(db, calc))
    for name, unit in by_name.items():
        assert hasattr(unit, "mmu_exempt"), f"{name} does not report its exemption state"
        if unit.mmu_exempt:
            assert unit.mmu_exempt_reason, f"{name} is exempt with no stated reason"
        else:
            assert unit.mmu_exempt_reason is None


def test_no_plot_is_placed_in_the_exempt_unit(forest):
    """The failure the exemption exists to prevent: plots in a sliver.

    ``total_points`` is the design-wide count, so the invariant is that it equals
    the sum of the per-unit counts - a design that silently kept plots in the
    exempt unit would break exactly that equality.
    """
    db, calc = forest
    result = _design(db, calc)
    by_name = _by_name(result)
    assert by_name["SLIVER"].samples_generated == 0
    assert result.response.total_points == sum(
        u.samples_generated for u in by_name.values()
    ), "points exist that no unit accounts for"
    # And the two sound units carry the whole design.
    assert result.response.total_points == sum(
        by_name[n].samples_generated for n in ("BIG-1", "BIG-2")
    )
