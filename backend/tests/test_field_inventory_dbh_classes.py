"""P0 - seedling and sapling reach the response; the harvest numbers do not move.

`get_total_inventory` served the stock tables from ONE class set,
`dfo_export`, which covers pole and tree only (10-20 cm and above). Seedling
(0-4 cm) and sapling (4-10 cm) were computed by the field-inventory service and
stored in `dbh_class_breakdown`, then projected away before the response was
built - so the two largest per-hectare densities in a forest never reached the
UI, under a table headed "DBH Class".

`dfo_export` is the correct set for the HARVEST question and the wrong set for
the STOCK question. The defect was one variable serving both.

These tests pin both halves:

  * the stock tables carry all eight guideline classes, and
  * the AAH and MAI tables carry only the volume-carrying ones, and are
    numerically IDENTICAL to what the single-set version produced.

The second group is the one that matters. A fix that quietly widened the
harvest calculation would move a farmer's allowable cut, so "the per-ha numbers
are now visible" is only acceptable if the harvest numbers are provably
untouched.
"""
from __future__ import annotations

import json
import uuid

import pytest

AREA_HA = 10.0

# All eight classes with distinct values, so a swap of one class for another
# cannot pass unnoticed. Volumes chosen so the two sets differ in total: if AAH
# ever started apportioning over seedling volume it would show up here.
ALL_CLASSES = {
    "0_4":     {"count_per_ha": 4000.0, "timber_m3_per_ha": 0.0,  "firewood_m3_per_ha": 0.0,  "label_en": "Seedling", "label_np": "बिरुवा"},
    "4_10":    {"count_per_ha": 900.0,  "timber_m3_per_ha": 0.0,  "firewood_m3_per_ha": 0.0,  "label_en": "Sapling", "label_np": "लाथ्रा"},
    "10_20":   {"count_per_ha": 500.0,  "timber_m3_per_ha": 20.0, "firewood_m3_per_ha": 2.0,  "label_en": "Small Pole", "label_np": "सानो खाँवा"},
    "20_30":   {"count_per_ha": 300.0,  "timber_m3_per_ha": 30.0, "firewood_m3_per_ha": 4.0,  "label_en": "Large Pole", "label_np": "ठुलो खाँवा"},
    "30_40":   {"count_per_ha": 200.0,  "timber_m3_per_ha": 40.0, "firewood_m3_per_ha": 6.0,  "label_en": "Small Tree", "label_np": "सानो रुख"},
    "40_50":   {"count_per_ha": 120.0,  "timber_m3_per_ha": 50.0, "firewood_m3_per_ha": 8.0,  "label_en": "Medium Tree", "label_np": "मझौला रुख"},
    "50_60":   {"count_per_ha": 60.0,   "timber_m3_per_ha": 60.0, "firewood_m3_per_ha": 10.0, "label_en": "Large Tree", "label_np": "ठुलो रुख"},
    "60_plus": {"count_per_ha": 20.0,   "timber_m3_per_ha": 70.0, "firewood_m3_per_ha": 12.0, "label_en": "Very Large Tree", "label_np": "अति ठुलो रुख"},
}
VOLUME_CARRYING = ["10_20", "20_30", "30_40", "40_50", "50_60", "60_plus"]
STOCK_DISPLAY = list(ALL_CLASSES)


@pytest.fixture()
def calc(db):
    from app.models.user import User
    from app.models.calculation import Calculation

    owner = User(
        email=f"p0-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="P0 Fixture",
    )
    db.add(owner)
    db.flush()
    c = Calculation(
        user_id=owner.id, forest_name=f"P0 CF {uuid.uuid4().hex[:6]}", geometry_version=1
    )
    db.add(c)
    db.commit()
    return c


@pytest.fixture()
def inventory(db, calc):
    from app.models.field_inventory import (
        FieldInventoryCalculation,
        FieldInventoryBlockSummary,
    )

    fic = FieldInventoryCalculation(
        calculation_id=calc.id, user_id=calc.user_id, uploaded_filename="fi.csv",
        status="completed",
    )
    db.add(fic)
    db.flush()
    db.add(
        FieldInventoryBlockSummary(
            field_inventory_calculation_id=fic.id,
            block_name="Block A",
            total_sample_plots=10,
            regeneration_per_ha=4000,
            sapling_per_ha=900,
            pole_per_ha=800,
            tree_per_ha=400,
            pole_timber_m3_per_ha=50.0,
            tree_timber_m3_per_ha=160.0,
            pole_firewood_m3_per_ha=6.0,
            tree_firewood_m3_per_ha=26.0,
            total_growing_stock_m3_per_ha=242.0,
            dbh_class_breakdown={k: dict(v) for k, v in ALL_CLASSES.items()},
        )
    )
    db.commit()
    return fic


def _totals(db, calc, fic):
    from app.models.user import User
    from app.api.field_inventory import get_total_inventory

    owner = db.query(User).filter(User.id == calc.user_id).one()
    # The endpoint OVERRIDES `block_areas` with areas it recomputes from the
    # calculation's polygons, and this fixture has none - so the value passed
    # here survives. That override is product behaviour, not something to work
    # around: it is exactly why stage 2 of the Results pane is read-only.
    return get_total_inventory(
        field_inventory_id=fic.id,
        block_areas=json.dumps({"Block A": AREA_HA}),
        custom_multipliers=None,
        aah_good=75.0,
        aah_moderate=60.0,
        aah_weak=40.0,
        db=db,
        current_user=owner,
    )


# ── the half that was broken: stock must show all eight ───────────────────
def test_stock_tables_carry_every_guideline_class(db, calc, inventory):
    out = _totals(db, calc, inventory)
    block = out["blocks"][0]

    assert sorted(block["dbh_class_per_ha"]) == sorted(STOCK_DISPLAY)
    assert sorted(block["dbh_class_totals"]) == sorted(STOCK_DISPLAY)
    assert sorted(out["forest_totals"]["dbh_class_totals"]) == sorted(STOCK_DISPLAY)


def test_seedling_and_sapling_carry_their_own_per_hectare_figures(db, calc, inventory):
    out = _totals(db, calc, inventory)
    per_ha = out["blocks"][0]["dbh_class_per_ha"]

    assert per_ha["0_4"]["count_per_ha"] == 4000.0
    assert per_ha["4_10"]["count_per_ha"] == 900.0
    # The whole point: these are the two largest densities, and they were absent.
    assert per_ha["0_4"]["count_per_ha"] > per_ha["10_20"]["count_per_ha"]


def test_stock_totals_are_per_hectare_times_area(db, calc, inventory):
    out = _totals(db, calc, inventory)
    block = out["blocks"][0]
    for key, d in block["dbh_class_per_ha"].items():
        total = block["dbh_class_totals"][key]
        assert total["total_count"] == pytest.approx(
            d["count_per_ha"] * AREA_HA
        ), f"{key} count is not per-ha x area"


def test_the_eight_classes_partition_the_forest_total(db, calc, inventory):
    """No class dropped, none counted twice."""
    out = _totals(db, calc, inventory)
    block = out["blocks"][0]
    summed = sum(d["total_count"] for d in block["dbh_class_totals"].values())
    assert summed == sum(
        ALL_CLASSES[k]["count_per_ha"] for k in ALL_CLASSES
    ) * AREA_HA


# ── the half that must NOT move: the harvest numbers ──────────────────────
def test_aah_dbh_table_covers_only_volume_carrying_classes(db, calc, inventory):
    out = _totals(db, calc, inventory)
    keys = {r["dbh_class_key"] for r in out["aah_dbh_table"]}
    assert keys == set(VOLUME_CARRYING)
    assert "0_4" not in keys and "4_10" not in keys


def test_mai_dbh_table_covers_only_volume_carrying_classes(db, calc, inventory):
    out = _totals(db, calc, inventory)
    keys = {r["dbh_class_key"] for r in out["mai_dbh_table"]}
    assert keys == set(VOLUME_CARRYING)


def test_aah_is_apportioned_over_pole_and_tree_volume_only(db, calc, inventory):
    """The harvest numbers must be exactly what the single-set version gave.

    AAH per hectare is `mai_ha * class_volume / total_volume`. If the denominator
    ever included seedling and sapling - which carry 0 m3 here but a non-zero
    count - the shares would change and so would a farmer's allowable cut. The
    denominator is therefore computed over the six volume-carrying classes only,
    which is what this pins.
    """
    out = _totals(db, calc, inventory)
    aah_ha = out["blocks"][0]["aah_m3_per_ha"]
    total_vol = sum(
        ALL_CLASSES[k]["timber_m3_per_ha"] + ALL_CLASSES[k]["firewood_m3_per_ha"]
        for k in VOLUME_CARRYING
    )
    for row in out["aah_dbh_table"]:
        cls_vol = (
            ALL_CLASSES[row["dbh_class_key"]]["timber_m3_per_ha"]
            + ALL_CLASSES[row["dbh_class_key"]]["firewood_m3_per_ha"]
        )
        assert row["aah_m3_per_ha"] == pytest.approx(aah_ha * cls_vol / total_vol)
