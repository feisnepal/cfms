"""The cause shown in brackets next to a forest / regeneration condition (owner rule 2026-10-10)."""
from app.services.operational_plan.unit_maps import condition_why


def test_weak_names_the_limits_that_were_missed():
    w = condition_why({"regeneration_per_ha": 1200, "sapling_per_ha": 300, "total_growing_stock_m3_per_ha": 30,
                       "regeneration_condition": "Weak", "forest_condition": "Weak"})
    assert w["regen_en"] == "seedlings 1,200/ha < 2,000, saplings 300/ha < 800"
    assert w["forest_en"] == "growing stock 30 m³/ha (< 50) + regeneration Weak"


def test_weak_names_only_the_limit_that_failed():
    w = condition_why({"regeneration_per_ha": 3000, "sapling_per_ha": 300, "regeneration_condition": "Weak",
                       "total_growing_stock_m3_per_ha": 120, "forest_condition": "Weak"})
    assert w["regen_en"] == "saplings 300/ha < 800"  # seedlings met their limit, so they are not blamed


def test_good_and_moderate_show_the_limits_that_were_met():
    good = condition_why({"regeneration_per_ha": 6000, "sapling_per_ha": 2500, "regeneration_condition": "Good",
                          "total_growing_stock_m3_per_ha": 250, "forest_condition": "Good"})
    assert good["regen_en"] == "seedlings 6,000/ha ≥ 5,000, saplings 2,500/ha ≥ 2,000"
    assert good["forest_en"] == "growing stock 250 m³/ha (> 200) + regeneration Good"
    mod = condition_why({"regeneration_per_ha": 3000, "sapling_per_ha": 900, "regeneration_condition": "Moderate",
                         "total_growing_stock_m3_per_ha": 120, "forest_condition": "Moderate"})
    assert mod["regen_en"] == "seedlings 3,000/ha ≥ 2,000, saplings 900/ha ≥ 800"
    assert "50–200" in mod["forest_en"]


def test_nepali_is_given_too():
    w = condition_why({"regeneration_per_ha": 1200, "sapling_per_ha": 300, "regeneration_condition": "Weak",
                       "total_growing_stock_m3_per_ha": 30, "forest_condition": "Weak"})
    assert "बिरुवा" in w["regen_ne"] and "लाथ्रा" in w["regen_ne"]
