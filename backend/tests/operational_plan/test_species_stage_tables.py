"""Species x stage tables for the Rambhadevi-style plan (species_stage_tables.py)."""
from app.services.operational_plan.species_stage_tables import build_species_stage_data, chart_series

_F = dict(regen_count_per_ha=0, sapling_count_per_ha=0, pole_count_per_ha=0, tree_count_per_ha=0,
          pole_basal_area_m2_per_ha=0, tree_basal_area_m2_per_ha=0, pole_timber_m3_per_ha=0,
          pole_firewood_m3_per_ha=0, tree_timber_m3_per_ha=0, tree_firewood_m3_per_ha=0)


def _row(block, species, **kw):
    return {"block_name": block, "species_scientific": species, "species_local": "", **{**_F, **kw}}


ROWS = [
    _row("C1S1", "Sal", tree_count_per_ha=100, tree_timber_m3_per_ha=10, tree_firewood_m3_per_ha=5, regen_count_per_ha=1000),
    _row("C1S2", "Sal", tree_count_per_ha=50, tree_timber_m3_per_ha=4, tree_firewood_m3_per_ha=2),
    _row("C1S2", "Asna", tree_count_per_ha=30, tree_timber_m3_per_ha=3, tree_firewood_m3_per_ha=1),
]
AREAS = {"C1S1": 10.0, "C1S2": 30.0}


def test_forest_wide_is_area_weighted_and_absent_species_count_as_zero():
    out = build_species_stage_data(ROWS, AREAS)
    tree = {r["प्रजाती"]: r for r in out["fi_species_tree_per_ha_table"]}
    assert tree["Sal"]["संख्या_प्रति_हेक्टर"] == round((100 * 10 + 50 * 30) / 40)  # 62.5 -> 62 (banker's) / 63
    assert tree["Asna"]["संख्या_प्रति_हेक्टर"] == round(30 * 30 / 40)            # absent from C1S1 -> 0 there
    assert tree["जम्मा"]["संख्या_प्रति_हेक्टर"] == round((100 * 10 + 50 * 30 + 30 * 30) / 40)


def test_total_row_last_and_unit_tables_carry_the_unit_column():
    out = build_species_stage_data(ROWS, AREAS)
    assert out["fi_species_tree_per_ha_table"][-1]["प्रजाती"] == "जम्मा"
    unit_rows = out["fi_unit_species_tree_per_ha_table"]
    assert {r["खण्ड"] for r in unit_rows} == {"C1S1", "C1S2"}
    assert sum(1 for r in unit_rows if r["प्रजाती"] == "जम्मा") == 2  # one total per unit


def test_regeneration_percentages_sum_to_100():
    out = build_species_stage_data(ROWS + [_row("C1S1", "Asna", regen_count_per_ha=3000)], AREAS)
    body = [r for r in out["fi_species_regen_per_ha_table"] if r["प्रजाती"] != "जम्मा"]
    assert round(sum(r["विरुवा_प्रतिशत"] for r in body)) == 100


def test_no_rows_gives_nothing_and_chart_series_handles_missing_data():
    assert build_species_stage_data([], AREAS) == {}
    assert chart_series({}, "fi_species_tree_count_bar") is None
    assert chart_series({"fi_species_tree_chart_data": []}, "fi_species_tree_count_bar") is None
    labels, values, title, ylab = chart_series(
        {"fi_species_tree_chart_data": [{"label": "Sal", "count_per_ha": 5, "volume_m3_per_ha": 9}]},
        "fi_species_tree_volume_bar",
    )
    assert (labels, values) == (["Sal"], [9])


def test_species_with_no_poles_is_left_out_of_the_pole_chart():
    out = build_species_stage_data(ROWS, AREAS)
    assert out["fi_species_pole_chart_data"] == []
    assert {d["label"] for d in out["fi_species_tree_chart_data"]} == {"Sal", "Asna"}
