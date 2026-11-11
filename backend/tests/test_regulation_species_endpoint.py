"""GET /field-inventory/{id}/regulation-species: the OP's regulation tables, each with its placeholder."""
from app.services.operational_plan import species_regulation_view as view


def test_variants_carry_their_own_tokens(monkeypatch):
    from app.services.operational_plan import species_regulation_tables as srt

    rows = [
        {"block_name": "a", "species_scientific": "Pinus wallichiana", "species_local": "x", "regeneration_per_ha": 10,
         "sapling_per_ha": 5, "pole_per_ha": 4, "tree_per_ha": 3, "pole_volume_m3_per_ha": 1.0, "tree_volume_m3_per_ha": 2.0},
        {"block_name": "a", "species_scientific": "Somethingelse sp", "species_local": "y", "regeneration_per_ha": 10,
         "sapling_per_ha": 5, "pole_per_ha": 4, "tree_per_ha": 3, "pole_volume_m3_per_ha": 1.0, "tree_volume_m3_per_ha": 2.0},
    ]
    data = srt.build_all_variants(rows, {"a": 1.0}, "hill")
    all_v, cls_v = view._variant(data, "fi_reg"), view._variant(data, "fi_regc")
    assert [t["token"] for t in all_v["tables"]][0] == "{{fi_reg_species_regen_per_ha_table}}"
    assert [t["token"] for t in cls_v["tables"]][0] == "{{fi_regc_species_regen_per_ha_table}}"
    assert all_v["narration"]["token"] == "{{section:fi_reg_species_narration:full}}"
    assert all(c["token"].startswith("{{chart:fi_reg_") for c in all_v["charts"])
    # the classified view never carries the Other row
    assert not any("अन्य" in str(r) for t in cls_v["tables"] for r in t["rows"])
    assert any("अन्य" in str(r) for t in all_v["tables"] for r in t["rows"])
