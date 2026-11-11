"""The tree-mapping analysis shows every unit by its own current name, exactly as the attribute table does (owner, 2026-10-15)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.operational_plan.data_collector import relabel_tree_analysis_units, unit_label_map


def _u(name, block_name=None):
    return SimpleNamespace(name=name, block_name=block_name)


UNITS = [
    _u("बनस्खन्डी - Compartment 1"),  # the top compartment: auto-made name, no label
    _u("l", "l"),
    _u("e", "e"),
    _u("बनस्खन्डी - Compartment 1-SC2_merged", "बनस्खन्डी - Compartment 1-SC2_merged"),
    _u("C-9", "north slope"),  # a unit whose label differs from its name
]


def test_every_name_a_unit_has_been_known_by_maps_to_the_name_the_table_shows():
    canon = unit_label_map(UNITS)
    assert canon["l"] == "l"
    assert canon["north slope"] == "C-9"  # a snapshot that kept the label finds the name
    assert canon["C-9"] == "C-9"
    assert canon["बनस्खन्डी - Compartment 1"] == "बनस्खन्डी - Compartment 1"


def test_a_label_never_steals_the_name_of_another_unit():
    canon = unit_label_map([_u("a", "b"), _u("b", "b")])
    assert canon["b"] == "b"  # "b" is the NAME of one unit: it stays that unit


def test_rows_get_the_current_name_and_the_unit_they_are():
    result = {
        "sm_hierarchy_summary": [
            {"block_name": "north slope", "compartment": "north slope", "sub_compartment": "l", "tree_count": 5},
            {"block_name": "-", "compartment": "-", "sub_compartment": "-", "tree_count": 12},
        ]
    }
    relabel_tree_analysis_units(result, unit_label_map(UNITS))
    first, none = result["sm_hierarchy_summary"]
    assert (first["block_name"], first["compartment"], first["sub_compartment"]) == ("C-9", "C-9", "l")
    assert first["unit_name"] == "l"  # the deepest unit the row is
    assert none["unit_name"] == "-"  # trees that fell in no unit stay "-"


def test_a_row_without_a_sub_unit_is_its_compartment_and_the_merge_unit_keeps_its_own_name():
    result = {
        "sm_species_by_hierarchy": [
            {"block_name": "बनस्खन्डी - Compartment 1", "compartment": "बनस्खन्डी - Compartment 1", "sub_compartment": "-", "species": "x"},
            {
                "block_name": "बनस्खन्डी - Compartment 1",
                "compartment": "बनस्खन्डी - Compartment 1",
                "sub_compartment": "बनस्खन्डी - Compartment 1-SC2_merged",
                "species": "y",
            },
        ]
    }
    relabel_tree_analysis_units(result, unit_label_map(UNITS))
    plain, merged = result["sm_species_by_hierarchy"]
    assert plain["unit_name"] == "बनस्खन्डी - Compartment 1"
    assert merged["unit_name"] == "बनस्खन्डी - Compartment 1-SC2_merged"


def test_a_name_that_is_no_unit_is_left_alone():
    result = {"sm_hierarchy_summary": [{"block_name": "Some Forest", "compartment": "-", "sub_compartment": "-"}]}
    relabel_tree_analysis_units(result, unit_label_map(UNITS))
    assert result["sm_hierarchy_summary"][0]["block_name"] == "Some Forest"


def test_the_remark_breakdown_is_renamed_with_the_rows_so_a_row_still_finds_its_numbers():
    result = {
        "sm_hierarchy_summary": [{"compartment": "north slope", "sub_compartment": "l"}],
        "sm_hierarchy_remark_breakdown": {"north slope|l": {"mother_trees": 2, "felling_trees": 1}, "-|-": {"mother_trees": 0, "felling_trees": 0}},
    }
    relabel_tree_analysis_units(result, unit_label_map(UNITS))
    row = result["sm_hierarchy_summary"][0]
    key = f"{row['compartment']}|{row['sub_compartment']}"
    assert result["sm_hierarchy_remark_breakdown"][key] == {"mother_trees": 2, "felling_trees": 1}
    assert "-|-" in result["sm_hierarchy_remark_breakdown"]


def test_other_lists_and_numbers_are_untouched():
    result = {"sm_available": True, "sm_total_trees_analyzed": 7, "sm_felling_dbh_analysis": [{"dbh_class": "10-20", "tree_count": 3}]}
    relabel_tree_analysis_units(result, unit_label_map(UNITS))
    assert result == {"sm_available": True, "sm_total_trees_analyzed": 7, "sm_felling_dbh_analysis": [{"dbh_class": "10-20", "tree_count": 3}]}
