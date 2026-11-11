"""ND-4: silviculture values the form leaves empty come from the SFM classification."""
from app.services.operational_plan.silviculture_derived import from_sfm, target_spacing_m


def _block(name, type_no, area, system, regen=None, rot=None, mother=None):
    return {"block_name": name, "effective_type_no": type_no, "area_ha": area,
            "prescription": {"system_ne": system, "regeneration_period_years": regen,
                             "rotation_years": rot, "mother_tree_target": mother}}


def test_target_spacing_from_density():
    assert target_spacing_m(100) == 10.0
    assert target_spacing_m([25, 25]) == 20.0
    assert target_spacing_m(None) is None and target_spacing_m(0) is None


def test_single_system_gives_plain_values():
    out = from_sfm({"blocks": [_block("A", 1, 10, "छत्र", regen=20, rot=80, mother=[100, 100])],
                    "forest_summary": {"dominant_type_no": 1}})
    assert out == {"silviculture_system": "छत्र", "rotation_years": 80,
                   "regeneration_period_years": 20, "mother_tree_spacing_m": 10.0}


def test_mixed_systems_list_dominant_first_then_by_area():
    sfm = {"blocks": [_block("A", 2, 50, "छनौट", rot=[60, 80]),
                      _block("B", 1, 5, "छत्र", regen=20, rot=80),
                      _block("C", 3, 30, "सफा कटान", rot=40)],
           "forest_summary": {"dominant_type_no": 1}}
    out = from_sfm(sfm)
    assert out["silviculture_system"] == "छत्र, छनौट, सफा कटान"
    assert out["rotation_years"] == "80, 60-80, 40"
    assert out["regeneration_period_years"] == 20


def test_no_sfm_gives_nothing():
    assert set(from_sfm({}).values()) == {None}


def test_one_system_spelled_two_ways_is_listed_once():
    a = _block("A", 1, 9, "Coppice with standard system")
    b = _block("B", 1, 5, "रुख सहितको (Coppice with standard System)")
    a["prescription"]["system_en"] = b["prescription"]["system_en"] = "Coppice-with-standard system"
    out = from_sfm({"blocks": [a, b], "forest_summary": {"dominant_type_no": 1}})
    assert out["silviculture_system"] == "Coppice with standard system"
