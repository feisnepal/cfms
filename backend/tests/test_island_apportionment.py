"""
P0 — `allocate_island_counts` apportions N equal-area compartments across the
islands of a multi-part forest boundary.

Covers the worked cases from MULTI_ISLAND_DIVIDE_PLAN.md plus the degenerate
ones (n=1, single island, equal islands, n == island count, huge disparity,
more parcels than compartments, bad input).
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.services.island_apportionment import (
    allocate_island_counts,
    summarise_islands,
    UNDERSIZED_REL,
)


def _counts(areas, n):
    return allocate_island_counts(areas, n)["counts"]


# --------------------------------------------------------------------------
# Worked cases from the plan
# --------------------------------------------------------------------------
def test_90_and_10_into_10_is_9_plus_1():
    r = allocate_island_counts([90.0, 10.0], 10)
    assert r["counts"] == [9, 1]
    assert r["n_effective"] == 10
    assert r["target_area"] == pytest.approx(10.0)
    assert r["undersized"] == []  # 10 ha piece == target


def test_90_and_3_into_10_flags_the_small_parcel():
    r = allocate_island_counts([90.0, 3.0], 10)
    assert r["counts"] == [9, 1]
    assert r["n_effective"] == 10
    assert r["target_area"] == pytest.approx(9.3)
    # 3 ha piece < 0.5 * 9.3 -> undersized
    assert r["undersized"] == [1]


def test_990_and_10_into_10_flags_the_small_parcel():
    r = allocate_island_counts([990.0, 10.0], 10)
    assert r["counts"] == [9, 1]
    assert r["target_area"] == pytest.approx(100.0)
    # big-island pieces are ~110 ha (over target) but not undersized;
    # the 10 ha parcel is 10 < 50 -> undersized
    assert r["undersized"] == [1]
    assert sum(r["counts"]) == 10


def test_more_parcels_than_n_raises_n_to_parcel_count():
    r = allocate_island_counts([2.0, 2.0, 2.0, 2.0, 2.0], 3)
    assert r["counts"] == [1, 1, 1, 1, 1]
    assert r["n_effective"] == 5  # raised from 3
    assert sum(r["counts"]) == 5


# --------------------------------------------------------------------------
# Invariants that must hold for any valid input
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "areas,n",
    [
        ([100.0], 1),
        ([100.0], 7),
        ([50.0, 50.0], 4),
        ([90.0, 10.0], 10),
        ([90.0, 3.0], 10),
        ([1000.0, 10.0, 5.0], 12),
        ([50.0, 1.0, 1.0, 1.0], 4),
        ([10.0, 6.0, 4.0], 5),
        ([33.3, 33.3, 33.4], 9),
        ([500.0, 5.0], 2),
        ([1.0, 1.0, 1.0, 1.0, 1.0, 1.0], 2),
    ],
)
def test_invariants(areas, n):
    r = allocate_island_counts(areas, n)
    c = r["counts"]
    assert len(c) == len(areas)
    assert all(x >= 1 for x in c), "every parcel gets at least one compartment"
    assert sum(c) == r["n_effective"], "counts sum to n_effective"
    assert r["n_effective"] == max(n, len(areas))
    assert r["target_area"] == pytest.approx(sum(areas) / r["n_effective"])


def test_deterministic():
    a = [10.0, 6.0, 4.0, 7.5, 2.2]
    assert allocate_island_counts(a, 11) == allocate_island_counts(list(a), 11)


def test_equal_islands_split_evenly():
    r = allocate_island_counts([25.0, 25.0, 25.0, 25.0], 8)
    assert r["counts"] == [2, 2, 2, 2]


def test_single_island_behaves_like_plain_divide():
    assert _counts([120.0], 6) == [6]
    assert _counts([120.0], 1) == [1]


def test_n_below_one_and_bad_areas_raise():
    with pytest.raises(ValueError):
        allocate_island_counts([10.0, 5.0], 0)
    with pytest.raises(ValueError):
        allocate_island_counts([], 3)
    with pytest.raises(ValueError):
        allocate_island_counts([10.0, 0.0], 3)
    with pytest.raises(ValueError):
        allocate_island_counts([10.0, -2.0], 3)


def test_claw_back_when_floor_of_one_over_allocates():
    # one dominant island + 3 tiny; n == parcel count -> only [1,1,1,1] works
    r = allocate_island_counts([50.0, 1.0, 1.0, 1.0], 4)
    assert r["counts"] == [1, 1, 1, 1]
    assert r["n_effective"] == 4


def test_float_n_is_coerced():
    assert _counts([90.0, 10.0], 10.0) == [9, 1]  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# summarise_islands helper (P2 preview rows)
# --------------------------------------------------------------------------
def test_summarise_islands_rows():
    areas = [90.0, 3.0]
    r = allocate_island_counts(areas, 10)
    rows = summarise_islands(areas, r["counts"], r["target_area"])
    assert rows[0] == {
        "index": 0,
        "area_ha": 90.0,
        "suggested_count": 9,
        "avg_piece_ha": 10.0,
        "undersized": False,
    }
    assert rows[1]["undersized"] is True
    assert rows[1]["avg_piece_ha"] == 3.0


def test_undersized_rel_is_half():
    assert UNDERSIZED_REL == 0.5
