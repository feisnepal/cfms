"""P8 tier 1 - the three bands, the neighbour rule, and the read-only promise.

Boundaries are tested on **both sides**, because an off-by-one at a threshold is the
likely bug and the thresholds are the whole point of the row.
"""

from __future__ import annotations

import pytest

from app.core.constants import MMU_SLIVER_AREA_M2, SQM_PER_HA
from app.services.unit_size_review import (
    Band,
    DEFAULT_REVIEW_PCT,
    build_candidate,
    classify_band,
    describe,
    mmu_hectares,
    pick_largest_touching,
    review_units,
    summarise,
)

MMU = MMU_SLIVER_AREA_M2 / SQM_PER_HA
BOUNDARY = 366.03  # b67f9e1c


# ── band boundaries ────────────────────────────────────────────────────────────
def test_mmu_boundary_on_both_sides():
    assert classify_band(MMU - 0.001, BOUNDARY) is Band.SUB_MMU
    assert classify_band(MMU, BOUNDARY) is Band.REVIEW
    assert classify_band(MMU + 0.001, BOUNDARY) is Band.REVIEW


def test_review_boundary_on_both_sides():
    cut = BOUNDARY * DEFAULT_REVIEW_PCT / 100.0
    assert classify_band(cut - 0.001, BOUNDARY) is Band.REVIEW
    assert classify_band(cut, BOUNDARY) is Band.OK
    assert classify_band(cut + 0.001, BOUNDARY) is Band.OK


def test_mmu_constant_is_unchanged_by_this_feature():
    """The MMU is written policy. If this ever moves, the test is the alarm."""
    assert MMU_SLIVER_AREA_M2 == 10000.0
    assert mmu_hectares() == pytest.approx(1.0)


def test_zero_and_negative_area_never_read_as_ok():
    """A degenerate unit is exactly what this exists to surface."""
    assert classify_band(0.0, BOUNDARY) is Band.SUB_MMU
    assert classify_band(-1.0, BOUNDARY) is Band.SUB_MMU


def test_zero_boundary_falls_back_to_mmu_only():
    """An unknown boundary must not silently make every unit 'ok'."""
    assert classify_band(5.0, 0.0) is Band.REVIEW  # 5 ha is above 1 ha, so not sub_mmu
    assert classify_band(0.5, 0.0) is Band.SUB_MMU


def test_review_pct_is_overridable():
    cut = BOUNDARY * 20.0 / 100.0
    assert classify_band(50.0, BOUNDARY, review_pct=20.0) is Band.REVIEW
    assert classify_band(50.0, BOUNDARY, review_pct=20.0) is not Band.OK


# ── the real forest ────────────────────────────────────────────────────────────
REAL_AREAS = {
    "C-1-SC1": 48.7814, "C-1-SC2": 48.1396, "C-1-SC3": 49.7095,
    "C-3-SC1": 26.0902, "C-3-SC2": 31.4943, "C-3-SC3": 17.0284,
    "C-2-SC1": 9.8376, "C-2-SC2": 9.8289, "C-2-SC3-1": 7.1035,
    "C-2-SC3-2": 2.7232, "C-2-SC4": 9.8084, "C-2-SC5": 9.8358,
    "C-2-SC6": 9.8224, "C-2-SC7": 9.8332, "C-2-SC8": 9.8178,
    "C-4": 15.9095, "C-5": 10.9790, "C-6": 10.9165, "C-7": 10.6822,
    "C-8": 7.5215, "C-9": 6.2105,
    "C35": 0.0178, "C36": 0.1174, "C37": 0.0270,
}


def test_real_forest_band_counts_match_the_plan():
    counts = summarise(review_units(REAL_AREAS, boundary_ha=BOUNDARY))
    # Recorded in the plan: 3 sub-MMU, 16 review, 5 ok.
    assert counts["sub_mmu"] == 3
    assert counts["review"] == 16
    assert counts["ok"] == 5
    assert counts["total"] == 24


def test_the_three_slivers_are_the_only_merge_offers():
    offers = sorted(
        c.block_name for c in review_units(REAL_AREAS, boundary_ha=BOUNDARY) if c.is_offer
    )
    assert offers == ["C35", "C36", "C37"]


def test_a_unit_in_the_review_band_is_never_offered_a_merge():
    for candidate in review_units(REAL_AREAS, boundary_ha=BOUNDARY):
        if candidate.band is Band.REVIEW:
            assert candidate.action == "flag_only"
            assert candidate.neighbour is None


def test_c9_and_c4_are_review_not_slivers():
    """The 5% screen must not sweep in sound mid-sized compartments."""
    by_name = {c.block_name: c for c in review_units(REAL_AREAS, boundary_ha=BOUNDARY)}
    assert by_name["C-9"].band is Band.REVIEW
    assert by_name["C-4"].band is Band.REVIEW
    assert by_name["C-1-SC1"].band is Band.OK


# ── neighbour selection ────────────────────────────────────────────────────────
def test_largest_touching_wins_over_nearest():
    areas = {"sliver": 0.1, "near_small": 5.0, "far_big": 50.0}
    touching = ["near_small", "far_big"]
    assert pick_largest_touching("sliver", areas, touching) == "far_big"


def test_empty_touching_set_yields_no_neighbour():
    """``pick_largest_touching`` trusts its ``touching`` argument - computing
    adjacency is the caller's job. Given nothing, it must propose nothing."""
    areas = {"sliver": 0.1, "big": 900.0}
    assert pick_largest_touching("sliver", areas, []) is None


def test_touching_but_unmeasured_neighbour_is_skipped_not_ranked_as_zero():
    """It cannot be ranked, and the preview's resulting-area figure must not be a guess."""
    areas = {"sliver": 0.1, "big": 900.0}
    assert pick_largest_touching("sliver", areas, ["small_neighbour"]) is None
    assert pick_largest_touching("sliver", areas, ["small_neighbour", "big"]) == "big"


def test_a_unit_never_proposes_itself():
    areas = {"a": 0.1, "b": 5.0}
    assert pick_largest_touching("a", areas, ["a", "b"]) == "b"


def test_equal_area_tie_is_stable():
    areas = {"sliver": 0.1, "x": 5.0, "y": 5.0}
    assert pick_largest_touching("sliver", areas, ["x", "y"]) == "x"


def test_unmergeable_when_nothing_touches():
    candidate = build_candidate(
        "island", 0.1, Band.SUB_MMU, areas={"island": 0.1}, touching=[]
    )
    assert candidate.unmergeable is True
    assert candidate.neighbour is None
    assert candidate.is_offer is True  # still needs an explicit decision


def test_missing_adjacency_cannot_fake_a_clean_bill_of_health():
    """A caller that forgets to supply adjacency must not see 'no action'."""
    candidate = build_candidate("sliver", 0.1, Band.SUB_MMU)
    assert candidate.unmergeable is True


# ── the message has to carry the why ───────────────────────────────────────────
def test_sub_mmu_message_states_the_numbers():
    candidate = build_candidate(
        "C35", 0.0178, Band.SUB_MMU, areas={"C35": 0.0178, "C-6": 10.9165},
        touching=["C-6"],
    )
    text = describe(candidate, mmu_ha=1.0, plot_area_sqm=500, min_plots=5)
    assert "0.0178" in text
    assert "1 ha" in text
    assert "C-6" in text
    assert "5 x 500 m2" in text


def test_unmergeable_message_says_it_cannot_be_merged():
    candidate = build_candidate("island", 0.1, Band.SUB_MMU, areas={"island": 0.1}, touching=[])
    text = describe(candidate, mmu_ha=1.0, plot_area_sqm=500, min_plots=5)
    assert "cannot be merged" in text


def test_review_message_never_suggests_a_merge():
    candidate = build_candidate("C-9", 6.2105, Band.REVIEW)
    text = describe(candidate, mmu_ha=1.0, plot_area_sqm=500, min_plots=5)
    assert "no merge proposed" in text


# ── read-only ──────────────────────────────────────────────────────────────────
def test_review_units_does_not_mutate_its_input():
    areas = dict(REAL_AREAS)
    before = dict(areas)
    touching = {"C35": ["C-6"]}
    review_units(areas, boundary_ha=BOUNDARY, touching=touching)
    assert areas == before
    assert touching == {"C35": ["C-6"]}
