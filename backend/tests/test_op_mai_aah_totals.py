"""MAI and AAH for the forest are sums of per-block products, not products of means.

DBH_SSOT P6c. The grand-total row used to compute

    mean(growing_stock) * mean(mai_percent)        <- MAI
    that, times one AAH_MULTIPLIER["Moderate"]     <- AAH

Both are wrong, and they are wrong in *opposite* directions, which is why fixing
one alone makes the answer worse:

  * an average of products built from averages. You cannot add 20% of 100 m3 in
    one block to 2% of 200 m3 in another and get "22% of the average 150 m3" --
    the total is 20 + 4 = 24, not 22. Jensen: the error is an *under*statement
    wherever growing stock and MAI% rise together, so it cannot be relied on to
    be conservative either.
  * a single forest-wide multiplier, when the multiplier comes from each block's
    own forest condition. On the owner's forest 5 of 21 blocks are "Weak" (40%)
    against 16 "Moderate" (60%).

The numbers below are chosen so the two methods cannot be confused. Two equal-area
blocks, with growing stock and MAI% moving in opposite directions:

    block A   gs=100 m3/ha   MAI 4.0%   10 ha   Moderate (60%)
    block B   gs=200 m3/ha   MAI 2.0%   10 ha   Weak    (40%)

    MAI  correct  = 100*.04*10 + 200*.02*10      = 40 + 40   =  80 m3/year
    MAI  old      = mean(gs) * mean(pct) * 20   = 150*.03*20 =  90 m3/year
    AAH  correct  = 40*.60 + 40*.40              = 24 + 16   =  40 m3/year
    AAH  old      = 80 * .60                     =            48 m3/year

So the old AAH (48) overshot, the old MAI (90) overshot, and they would have
*both* looked plausible -- 48 is not a number anyone questions on sight.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.calculation import Calculation
from app.models.field_inventory import (
    FieldInventoryBlockSummary,
    FieldInventoryCalculation,
)
from app.models.user import User
from app.services.operational_plan import data_collector as dc

BLOCKS = [
    # name, growing stock m3/ha, mai %, condition, area ha
    ("A", 100.0, 4.0, "Moderate", 10.0),
    ("B", 200.0, 2.0, "Weak", 10.0),
]
TOTAL_AREA = 20.0

# The correct answers, written out by hand above.
MAI_ABS = 80.0
AAH_ABS = 40.0
MAI_PER_HA = 4.0
AAH_PER_HA = 2.0
# What the old code produced.
OLD_MAI_ABS = 90.0
OLD_AAH_ABS = 48.0


@pytest.fixture()
def owner(db):
    u = User(
        email=f"opmai-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="h",
        full_name="OP MAI",
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture()
def seeded(db, owner, monkeypatch):
    calc = Calculation(user_id=owner.id, forest_name="MAI CF")
    db.add(calc)
    db.flush()
    fi = FieldInventoryCalculation(
        user_id=owner.id,
        calculation_id=calc.id,
        uploaded_filename="fi.csv",
        status="completed",
        total_sample_plots=10,
        total_blocks=len(BLOCKS),
    )
    db.add(fi)
    db.flush()
    areas = {}
    for name, gs, pct, cond, area in BLOCKS:
        db.add(
            FieldInventoryBlockSummary(
                field_inventory_calculation_id=fi.id,
                block_name=name,
                total_sample_plots=5,
                total_growing_stock_m3_per_ha=gs,
                mai_percent=pct,
                forest_condition=cond,
            )
        )
        areas[name] = area
    db.commit()

    # Areas cannot be computed from a seeded block with no geometry, so they are
    # supplied directly. Everything under test is downstream of this.
    monkeypatch.setattr(
        dc, "_fetch_block_effective_areas", lambda db, calculation_id: dict(areas)
    )
    monkeypatch.setattr(dc, "_fetch_block_protected_areas", lambda db, calculation_id: {})
    return calc


def _grand(db, calc):
    out = dc.get_field_inventory_data(db, str(calc.id))
    # The grand-total row is the one with no `block_name`; every per-block row
    # carries one. Deliberately *not* keyed on `forest_condition == "—"`: that is
    # an em dash, and a test that depends on a literal non-ASCII character fails
    # confusingly on a terminal that renders it as a hyphen.
    rows = [r for r in out["fi_block_summaries"] if r.get("block_name") is None]
    assert len(rows) == 1, f"expected one grand-total row, got {len(rows)}"
    return rows[0]


class TestMaiIsASumOfProducts:
    def test_it_is_not_the_product_of_the_two_means(self, db, seeded):
        g = _grand(db, seeded)
        assert g["mai_total_m3"] == pytest.approx(MAI_ABS)
        assert g["mai_total_m3"] != pytest.approx(OLD_MAI_ABS), (
            "the grand total is the product of means again"
        )

    def test_the_per_hectare_figure_is_the_absolute_over_the_area(self, db, seeded):
        g = _grand(db, seeded)
        assert g["mai_total_m3_per_ha"] == pytest.approx(MAI_PER_HA)
        assert g["mai_total_m3"] == pytest.approx(g["mai_total_m3_per_ha"] * TOTAL_AREA)

    def test_each_block_contributes_in_proportion_to_its_own_area(self, db, owner, monkeypatch):
        """Ten times the area must be ten times the contribution.

        Summing the rates instead -- the mistake my own measurement script made --
        would make this fail, because the total would not move at all.
        """
        calc = Calculation(user_id=owner.id, forest_name="Areas CF")
        db.add(calc)
        db.flush()
        fi = FieldInventoryCalculation(
            user_id=owner.id, calculation_id=calc.id,
            uploaded_filename="fi.csv", status="completed",
        )
        db.add(fi)
        db.flush()
        for name, gs, pct, cond, _ in BLOCKS:
            db.add(
                FieldInventoryBlockSummary(
                    field_inventory_calculation_id=fi.id,
                    block_name=name, total_sample_plots=5,
                    total_growing_stock_m3_per_ha=gs, mai_percent=pct,
                    forest_condition=cond,
                )
            )
        db.commit()
        monkeypatch.setattr(dc, "_fetch_block_protected_areas", lambda db, cid: {})

        got = []
        for scale in (1.0, 10.0):
            monkeypatch.setattr(
                dc,
                "_fetch_block_effective_areas",
                lambda db, cid, s=scale: {n: a * s for n, _, _, _, a in BLOCKS},
            )
            got.append(_grand(db, calc)["mai_total_m3"])
        assert got[0] == pytest.approx(MAI_ABS)
        assert got[1] == pytest.approx(MAI_ABS * 10.0)


class TestAahUsesEachBlocksOwnMultiplier:
    def test_it_is_not_one_flat_multiplier(self, db, seeded):
        g = _grand(db, seeded)
        assert g["aah_total_m3"] == pytest.approx(AAH_ABS)
        assert g["aah_total_m3"] != pytest.approx(OLD_AAH_ABS), (
            "a single AAH multiplier is being applied to the whole forest again"
        )

    def test_the_per_hectare_figure_is_the_absolute_over_the_area(self, db, seeded):
        g = _grand(db, seeded)
        assert g["aah_total_m3_per_ha"] == pytest.approx(AAH_PER_HA)
        assert g["aah_total_m3"] == pytest.approx(g["aah_total_m3_per_ha"] * TOTAL_AREA)

    def test_a_uniform_condition_collapses_to_the_flat_case(self, db, owner, monkeypatch):
        """With every block in the same condition the two agree, which is why this
        defect survives on a uniform forest and is easy to dismiss."""
        calc = Calculation(user_id=owner.id, forest_name="Uniform CF")
        db.add(calc)
        db.flush()
        fi = FieldInventoryCalculation(
            user_id=owner.id, calculation_id=calc.id,
            uploaded_filename="fi.csv", status="completed",
        )
        db.add(fi)
        db.flush()
        for name, gs, pct, _, _ in BLOCKS:
            db.add(
                FieldInventoryBlockSummary(
                    field_inventory_calculation_id=fi.id,
                    block_name=name, total_sample_plots=5,
                    total_growing_stock_m3_per_ha=gs, mai_percent=pct,
                    forest_condition="Moderate",
                )
            )
        db.commit()
        monkeypatch.setattr(dc, "_fetch_block_protected_areas", lambda db, cid: {})
        monkeypatch.setattr(
            dc,
            "_fetch_block_effective_areas",
            lambda db, cid: {n: a for n, _, _, _, a in BLOCKS},
        )
        g = _grand(db, calc)
        # One multiplier is then correct, and the per-block version must agree
        # with it rather than disagreeing for its own sake.
        assert g["aah_total_m3"] == pytest.approx(MAI_ABS * 0.60)
        assert g["mai_total_m3"] == pytest.approx(MAI_ABS)
        # MAI is still the sum of products, uniform condition or not.
        assert g["mai_total_m3"] != pytest.approx(OLD_MAI_ABS)


class TestTheAbsolutesAreCarried:
    def test_both_are_present_and_consistent(self, db, seeded):
        g = _grand(db, seeded)
        assert g["mai_total_m3"] > 0 and g["aah_total_m3"] > 0
        # AAH is MAI reduced by a multiplier below 1, so it must be the smaller.
        assert g["aah_total_m3"] < g["mai_total_m3"]

    def test_the_per_block_rows_are_untouched(self, db, seeded):
        """Only the total was wrong. The per-block rows were already right, and
        fixing them would have been a third, unnecessary change."""
        out = dc.get_field_inventory_data(db, str(seeded.id))
        # `.get`, and the grand row filtered out: it has no `block_name` key at all.
        rows = {
            r.get("block_name"): r
            for r in out["fi_block_summaries"]
            if r.get("block_name") is not None
        }
        assert rows["A"]["mai_total_m3_per_ha"] == pytest.approx(4.0)
        assert rows["B"]["mai_total_m3_per_ha"] == pytest.approx(4.0)
        # AAH differs between the two blocks on condition alone -- both have
        # MAI 4.0, but A is Moderate (60%) and B is Weak (40%). That the two
        # per-block AAH figures differ is the same fact the total now honours.
        assert rows["A"]["aah_total_m3_per_ha"] == pytest.approx(2.4)
        assert rows["B"]["aah_total_m3_per_ha"] == pytest.approx(1.6)
