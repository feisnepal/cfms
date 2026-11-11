from app.core.regulation_species import (
    build_regulation_groups,
    region_for_zone,
    regulation_code,
)
from app.core.species_policy import ABSOLUTE_MEASURES


def _row(name, n):
    return {
        "species_scientific": name,
        "count": n,
        "timber_m3": n * 2.0,
        "fuelwood_m3": n * 1.0,
        "volume_m3": n * 3.0,
    }


def test_region_for_zone():
    assert region_for_zone("Bhawar") == "terai"
    assert region_for_zone("Middle Mountain") == "hill"
    assert region_for_zone(None) == "hill"


def test_codes():
    assert regulation_code("Shorea robusta", "hill") == 18
    assert regulation_code("Albizia chinensis", "hill") == 4  # genus rule
    assert regulation_code("Terminalia chebula", "terai") == 22
    assert regulation_code("Ficus religiosa", "hill") == 23


def test_groups_partition_and_other_bucket():
    rows = [
        _row("Shorea robusta", 10),
        _row("Albizia lebbeck", 4),
        _row("Ficus religiosa", 3),
        _row("Terminalia chebula", 2),
    ]
    out = build_regulation_groups(rows, ABSOLUTE_MEASURES, "terai")
    by_code = {g["code"]: g for g in out["groups"]}
    assert set(by_code) == {18, 4, 22}
    assert by_code[22]["count"] == 5
    assert by_code[22]["species"] == ["Ficus religiosa", "Terminalia chebula"]
    assert out["partition_holds"]
    assert out["total"]["count"] == 19


def test_op_regulation_tables_separate_keys():
    from app.services.operational_plan.species_regulation_tables import build_regulation_stage_data
    from app.services.operational_plan import species_stage_tables as sst

    def r(unit, name, n):
        return {"block_name": unit, "species_scientific": name, "species_local": name,
                **{f: float(n) for f in sst._FIELDS}}

    rows = [r("A", "Shorea robusta", 5), r("A", "Ficus religiosa", 2), r("A", "Ficus benghalensis", 3)]
    out = build_regulation_stage_data(rows, {"A": 10.0}, "terai")
    assert "fi_reg_species_tree_per_ha_table" in out
    assert "fi_reg_unit_species_tree_per_ha_table" in out
    assert not any(k.startswith("fi_species_") for k in out)
    tree = out["fi_reg_species_tree_per_ha_table"]
    other = next(x for x in tree if "अन्य" in x["प्रजाती"])
    assert other["संख्या_प्रति_हेक्टर"] == 5  # two Other species merged
    assert tree[-1]["संख्या_प्रति_हेक्टर"] == 10  # total row


def test_classified_only_drops_other():
    rows = [_row("Shorea robusta", 10), _row("Ficus religiosa", 3)]
    out = build_regulation_groups(rows, ABSOLUTE_MEASURES, "hill", include_other=False)
    assert [g["code"] for g in out["groups"]] == [18]
    assert out["total"]["count"] == 10 and out["partition_holds"]


def test_classified_twin_charts_and_narration():
    from app.services.operational_plan import species_stage_tables as sst
    from app.services.operational_plan.species_regulation_tables import (
        build_all_variants, chart_series, narration)

    def r(name, n):
        return {"block_name": "A", "species_scientific": name, "species_local": name,
                **{f: float(n) for f in sst._FIELDS}}

    fi = build_all_variants([r("Shorea robusta", 5), r("Ficus religiosa", 2)], {"A": 10.0}, "hill")
    cls = fi["fi_regc_species_tree_per_ha_table"]
    assert all("अन्य" not in x["प्रजाती"] for x in cls)
    assert any("अन्य" in x["प्रजाती"] for x in fi["fi_reg_species_tree_per_ha_table"])
    assert chart_series(fi, "fi_regc_species_tree_count_bar")[0] == ["Shorea robusta"]
    assert "अन्य" in " ".join(chart_series(fi, "fi_reg_species_tree_count_bar")[0])
    assert "२१" in narration(fi, "fi_regc") and narration({}, "fi_reg") is None


def test_template_section_tokens_are_registered_and_idempotent():
    import re
    from app.services.operational_plan.regulation_species_section import SECTIONS, insert_into_tree
    from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY

    tokens = {t.removesuffix(":full") for _k, _a, _b, c in SECTIONS for t in re.findall(r"\{\{([^}]+)\}\}", c)}
    assert len(tokens) == 2 * (6 + 4 + 1)
    assert [t for t in tokens if t not in VARIABLE_REGISTRY] == []
    tree = [{"id": "a", "type": "section", "title_ne": "S", "content": "", "children": [], "level": 1}]
    assert insert_into_tree(tree, into_section_title="S") is True
    assert insert_into_tree(tree, into_section_title="S") is False
    assert len(tree[0]["children"]) == 2
