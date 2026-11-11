"""A divided parent unit gets the area-weighted roll-up of its sub-units (owner rule 2026-10-10)."""
from app.core.forest_condition import assess_conditions
from app.services.unit_rollup import (
    dominant_by_area, leaves_by_parent, rollup_field_inventory, rollup_sfm_types, weighted_mean,
)

TREE = [
    {"id": "P", "name": "Comp 1", "block_name": "", "parent_id": None, "area_ha": 30.0},
    {"id": "A", "name": "SC1", "block_name": "SC1", "parent_id": "P", "area_ha": 10.0},
    {"id": "B", "name": "SC2", "block_name": "SC2", "parent_id": "P", "area_ha": 20.0},
    {"id": "A1", "name": "SC1-1", "block_name": "SC1-1", "parent_id": "A", "area_ha": 4.0},
    {"id": "A2", "name": "SC1-2", "block_name": "SC1-2", "parent_id": "A", "area_ha": 6.0},
]


def test_leaves_are_found_through_every_level():
    lv = leaves_by_parent(TREE)
    assert sorted(u["id"] for u in lv["P"]) == ["A1", "A2", "B"]
    assert sorted(u["id"] for u in lv["A"]) == ["A1", "A2"]
    assert "B" not in lv  # a leaf has no roll-up


def test_weighted_mean_and_dominant_ignore_missing_values():
    assert weighted_mean([(10, 100), (30, 200), (5, None)]) == 175.0
    assert weighted_mean([]) is None
    assert dominant_by_area([(4, "x"), (6, "y"), (5, None)]) == "y"
    assert dominant_by_area([]) is None


def test_inventory_rolls_up_per_ha_by_area_counts_by_sum_and_condition_by_the_rule():
    leaf = {
        "SC1-1": {"total_growing_stock_m3_per_ha": 100.0, "regeneration_per_ha": 6000, "sapling_per_ha": 2500, "total_sample_plots": 3},
        "SC1-2": {"total_growing_stock_m3_per_ha": 200.0, "regeneration_per_ha": 2000, "sapling_per_ha": 500, "total_sample_plots": 5},
        "SC2": {"total_growing_stock_m3_per_ha": 40.0, "regeneration_per_ha": 100, "sapling_per_ha": 50, "total_sample_plots": 2},
    }
    out = rollup_field_inventory(TREE, leaf)
    sc1 = out["SC1"]  # leaves 4 ha @100 and 6 ha @200 -> 160
    assert round(sc1["total_growing_stock_m3_per_ha"], 1) == 160.0
    assert sc1["total_sample_plots"] == 8
    assert (sc1["regeneration_condition"], sc1["forest_condition"]) == assess_conditions(
        sc1["regeneration_per_ha"], sc1["sapling_per_ha"], sc1["total_growing_stock_m3_per_ha"]
    )
    comp = out["Comp 1"]  # 4@100 + 6@200 + 20@40 over 30 ha
    assert round(comp["total_growing_stock_m3_per_ha"], 2) == round((4 * 100 + 6 * 200 + 20 * 40) / 30, 2)
    assert comp["total_sample_plots"] == 10
    assert set(leaf) <= set(out)  # the leaves themselves are untouched


def test_a_parent_that_already_has_a_row_keeps_it():
    leaf = {"SC1-1": {"total_growing_stock_m3_per_ha": 100.0}, "SC1": {"total_growing_stock_m3_per_ha": 7.0}}
    assert rollup_field_inventory(TREE, leaf)["SC1"] == {"total_growing_stock_m3_per_ha": 7.0}


def test_sfm_parent_takes_the_largest_area_type_and_says_it_is_a_summary():
    types = {
        "SC1-1": {"type_no": 3, "orientation": "Production", "plot_count": 2, "gs_ge40_m3_per_ha": 10, "land_class": "forest"},
        "SC1-2": {"type_no": 5, "orientation": "Conservation", "plot_count": 4, "gs_ge40_m3_per_ha": 30, "land_class": "forest"},
        "SC2": {"type_no": None, "orientation": None, "plot_count": 0, "gs_ge40_m3_per_ha": None, "land_class": "forest"},
    }
    sc1 = rollup_sfm_types(TREE, types)["SC1"]
    assert sc1["type_no"] == 5 and sc1["orientation"] == "Conservation"  # 6 ha beats 4 ha
    assert sc1["plot_count"] == 6 and sc1["state"] == "rolled_up" and sc1["needs_review"] is False
    comp = rollup_sfm_types(TREE, types)["Comp 1"]
    assert comp["plot_count"] == 6 and comp["type_no"] == 5  # a leaf with no type does not outvote the ones that have one


def test_no_rolled_up_row_without_any_leaf_data():
    assert rollup_field_inventory(TREE, {}) == {}
    assert rollup_sfm_types(TREE, {}) == {}
