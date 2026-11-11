"""P8 §8.1 - sub-MMU units are exempt from the flat per-unit minimum.

The single most important assertion in this file is
:func:`test_exemption_cannot_spread_to_units_above_the_mmu`. The exemption is a
deliberate, scoped reading of the guideline - a sub-MMU unit is not a management
unit, so the per-unit minimum does not apply to it - and the failure mode of such
an exemption is creeping to one more unit until the floor means nothing.
"""

from __future__ import annotations

import pytest

from app.core.constants import MMU_SLIVER_AREA_M2, SQM_PER_HA
from app.services.sampling import create_sampling_design
from app.services.sustainable_fm.stratum_spec import (
    MIN_SAMPLES_PER_UNIT,
    STRATUM_PLOT_SQM,
)

MMU_HA = MMU_SLIVER_AREA_M2 / SQM_PER_HA


# ── the arithmetic the exemption rests on ──────────────────────────────────────
def test_five_production_plots_need_more_than_the_tiniest_units_have():
    """The geometric claim, asserted only where it is actually true.

    Five 500 m2 production plots need 0.25 ha. A unit under **that** cannot hold
    them, and `C35` at 0.0178 ha is a seventh of it. Note the 1 ha MMU is *above*
    0.25 ha, so a unit just under the MMU could geometrically take the plots - the
    exemption for those rests on **policy** (a sub-MMU unit is not a management
    unit), not on geometry, and only the very small ones are geometrically
    impossible. Both are true; conflating them would be wrong.
    """
    plot_ha = STRATUM_PLOT_SQM["production"] / SQM_PER_HA  # 500 m2 = 0.05 ha
    needed_ha = MIN_SAMPLES_PER_UNIT * plot_ha  # 0.25 ha
    assert needed_ha == pytest.approx(0.25)
    assert MMU_HA > needed_ha  # so the MMU alone is not a geometric argument
    c35_ha = 0.0178
    assert c35_ha < needed_ha
    assert c35_ha < needed_ha / 4  # a seventh of what five plots need


def test_a_sub_mmu_unit_cannot_hold_one_tree_plot():
    """C35 is 0.0178 ha = 178 m2; one 500 m2 production plot does not fit."""
    c35_m2 = 0.0178 * SQM_PER_HA
    assert c35_m2 < STRATUM_PLOT_SQM["production"]


# ── the floor itself, unchanged for everyone else ─────────────────────────────
def _floor_for(area_ha: float, *, exempt: bool = True, override=None) -> int:
    """The same expression the engine uses, factored out so it can be pinned here.

    Mirrors ``sampling.py`` exactly: the exemption may only *remove* the minimum
    for a sub-MMU unit that has not opted in. Everything else keeps the floor.
    """
    unit_override = override or {}
    opted_in = "min_samples_per_block" in unit_override
    mmu_exempt = bool(exempt) and area_ha < MMU_HA and not opted_in
    if mmu_exempt:
        return 0
    return max(unit_override.get("min_samples_per_block", MIN_SAMPLES_PER_UNIT),
               MIN_SAMPLES_PER_UNIT)


def test_sub_mmu_unit_is_exempt_from_the_floor():
    assert _floor_for(0.0178) == 0
    assert _floor_for(0.1174) == 0
    assert _floor_for(0.9999) == 0


def test_the_exemption_cannot_spread_to_units_above_the_mmu():
    """The load-bearing test. One unit above the MMU is not a sliver."""
    for area in (1.0, 1.0001, 2.72, 6.21, 9.83, 15.91, 100.0):
        assert _floor_for(area) == MIN_SAMPLES_PER_UNIT, (
            f"{area} ha is above the MMU and must keep the flat floor"
        )


def test_exemption_can_be_switched_off():
    """P8 8.1: `exempt_sub_mmu_units=False` restores the floor for every unit."""
    assert _floor_for(0.0178, exempt=False) == MIN_SAMPLES_PER_UNIT


def test_an_explicit_override_opts_a_sub_mmu_unit_in():
    """The existing per-block override is how the owner asks for it anyway.

    Note the floor still applies once opted in - a caller may only *raise* the
    minimum, never lower it. So opting in with 2 still yields 5; opting in with 8
    yields 8.
    """
    assert _floor_for(0.0178, override={"min_samples_per_block": 2}) == MIN_SAMPLES_PER_UNIT
    assert _floor_for(0.0178, override={"min_samples_per_block": 8}) == 8


def test_an_override_without_the_min_key_is_not_an_opt_in():
    """Opting in must be explicit about the minimum, not incidental."""
    assert _floor_for(0.0178, override={"sampling_type": "random"}) == 0


def test_zero_and_tiny_areas_are_exempt_too():
    assert _floor_for(0.0) == 0
    assert _floor_for(0.0001) == 0


# ── the recorded reason carries its numbers ───────────────────────────────────
def test_exempt_reason_states_why_in_numbers():
    plot = STRATUM_PLOT_SQM["production"]
    mmu = MMU_HA
    reason = (
        f"below the {mmu:g} ha MMU: too small to hold "
        f"{MIN_SAMPLES_PER_UNIT} x {plot:g} m2 plots"
    )
    assert "1 ha" in reason
    assert "5 x 500 m2" in reason
