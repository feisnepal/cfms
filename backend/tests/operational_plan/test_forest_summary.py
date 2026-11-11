"""FP-3 gate: the forest summary (tiles, themes, verdict) is built only from the OP data, never invents a number,
and never judges a share or a stock against a threshold. Pure functions, hand-made OP data."""
import re

import pytest

from app.services import translation_service
from app.services.operational_plan import forest_summary as fs


UNITS = {"B1": 200.0, "B2": 150.0, "B3": 62.0}  # leaf units of the forest, from the forest_blocks table


def _build(op, households=None, area=fs.FOREST):
    return fs.build_summary(op, households, area, UNITS)


def _op(**over):
    op = {
        "basic_info": {"total_area_sqm": 4_120_000.0},
        "field_inventory": {
            "available": True, "fi_growing_stock_m3_per_ha": 168.4, "fi_carbon_stock_tc_per_ha": 31.0,
            "fi_aah_table": [{"block_name": "B1", "total_aah_m3_per_ha": 1.0},
                             {"block_name": "Grand Total (Weighted)", "total_aah_m3_per_ha": 2.1}],
            "fi_block_summaries": [{"block_name": "B1", "forest_condition": "Good"},
                                   {"block_name": "B2", "forest_condition": "Moderate"},
                                   {"block_name": "B3", "forest_condition": "Weak"}],
        },
        "hazard_vuln": {"lsi_prone_area_pct": 25.0, "lsi_prone_area_ha": 103.0, "lsi_class_method": "quantile",
                        "hh_count": 214, "hh_priority_count": 14},
        "soil_erosion": {"soil_loss_available": True, "soil_loss_mean_t_ha": 8.2, "soil_loss_ug_mean_t_ha": 11.5},
        "species": {"species_count": 47},
        "user_group": {"available": True, "user_group_area_ha": 120.0},
    }
    op.update(over)
    return op


def _tiles(summary):
    return {t["key"]: t for t in summary["tiles"]}


def test_every_tile_equals_the_op_figure():
    s = _build(_op(), {"total_households": 214})
    t = _tiles(s)
    assert t["area"]["value"] == 412.0 and t["area"]["unit_count"] == 3
    assert t["growing_stock"]["value"] == 168.4 and t["growing_stock"]["unit"] == "m3/ha"
    assert t["carbon"]["value"] == 31.0
    assert t["co2e"]["value"] == round(31.0 * 3.67, 2)
    assert t["aah"]["value"] == 2.1
    assert t["condition_good"]["value"] == round(100 * 200 / 412, 1)
    assert t["landslide_high"]["value"] == 25.0 and t["landslide_high"]["relative"] is True
    assert t["species"]["value"] == 47
    assert all(t[k]["state"] == fs.READY for k in t)
    assert [x["key"] for x in s["tiles"]] == ["area", "growing_stock", "carbon", "co2e", "aah", "condition_good",
                                                "landslide_high", "species"]


def test_condition_shares_are_weighted_by_unit_area_and_name_the_weak_units():
    shares = fs.condition_shares(_op(), UNITS)
    assert shares == {"good": 48.5, "moderate": 36.4, "weak": 15.0, "weak_units": ["B3"]}


def test_missing_inventory_is_not_computed_and_names_the_step():
    op = _op(field_inventory={"available": False})
    t = _tiles(_build(op, None))
    for key in ("growing_stock", "carbon", "co2e", "aah", "condition_good"):
        assert t[key]["state"] == fs.NOT_COMPUTED and t[key]["value"] is None and t[key]["source_step"] == 5
    assert t["area"]["state"] == fs.READY


def test_without_units_there_is_no_condition_share_and_no_block_count():
    s = fs.build_summary(_op(), None, fs.FOREST, None)
    t = _tiles(s)
    assert t["condition_good"]["state"] == fs.NOT_COMPUTED and t["area"]["unit_count"] is None
    assert fs.condition_shares(_op(), {}) is None


def test_units_are_never_read_from_the_op_block_snapshots():
    """The OP data's own 'blocks' arrays are the legacy snapshots that go stale; the summary must ignore them."""
    op = _op(blocks={"total_blocks": 99, "blocks": [{"name": "B1", "area_hectares": 1.0}]})
    t = _tiles(fs.build_summary(op, None, fs.FOREST, UNITS))
    assert t["area"]["unit_count"] == 3
    assert t["condition_good"]["value"] == round(100 * 200 / 412, 1)


def test_missing_hazard_and_species_are_not_computed():
    op = _op(hazard_vuln={"hazard_vuln_available": False}, species={"available": False})
    t = _tiles(_build(op, None))
    assert t["landslide_high"]["state"] == fs.NOT_COMPUTED and t["landslide_high"]["source_step"] == 11
    assert t["species"]["state"] == fs.NOT_COMPUTED and t["species"]["source_step"] == 6


def test_fixed_landslide_method_is_not_called_relative():
    op = _op()
    op["hazard_vuln"]["lsi_class_method"] = "fixed"
    assert _tiles(_build(op, None))["landslide_high"]["relative"] is False


def test_user_group_scope_uses_user_group_figures_and_marks_forest_only_ones():
    s = _build(_op(), None, fs.USER_GROUP)
    t = _tiles(s)
    assert t["area"]["value"] == 120.0
    for key in ("growing_stock", "carbon", "co2e", "aah", "condition_good", "landslide_high"):
        assert t[key]["state"] == fs.FOREST_ONLY and t[key]["value"] is None
    hazard_rows = {r["key"]: r for r in next(th for th in s["themes"] if th["key"] == "hazard")["rows"]}
    assert hazard_rows["soil_loss"]["value"] == 11.5  # the user group's own mean, not the forest's 8.2
    assert s["verdict_inputs"]["stock"] is None and s["verdict_inputs"]["landslide_pct"] is None


def test_themes_and_households():
    s = _build(_op(), {"total_households": 214})
    assert [th["key"] for th in s["themes"]] == ["stock", "health", "biodiversity", "hazard", "people"]
    people = {r["key"]: r for r in s["themes"][4]["rows"]}
    assert people["households"]["value"] == 214
    hazard = {r["key"]: r for r in s["themes"][3]["rows"]}
    assert hazard["priority_households"]["value"] == 14 and hazard["priority_households"]["of"] == 214
    assert hazard["soil_loss"]["value"] == 8.2
    # no household data at all -> not computed, not zero
    no_hh = {r["key"]: r for r in _build(_op(), None)["themes"][4]["rows"]}
    assert no_hh["households"]["state"] == fs.NOT_COMPUTED


# ---- the verdict -----------------------------------------------------------------------------------------------------

def _fake(key, **params):
    return f"<{key}:" + ",".join(f"{k}={v}" for k, v in sorted(params.items())) + ">"


def test_verdict_has_one_clause_per_available_fact_in_order():
    inputs = _build(_op(), None)["verdict_inputs"]
    text = fs.build_verdict(inputs, _fake)
    keys = re.findall(r"<([\w.]+):", text)
    assert keys == ["forestSummary.verdict.condition", "forestSummary.verdict.weak_units", "forestSummary.verdict.stock",
                    "forestSummary.verdict.landslide_relative"]
    assert "good=48.5" in text and "units=B3" in text and "stock=168" in text and "pct=25" in text


def test_verdict_leaves_out_what_is_not_computed_and_falls_back_when_nothing_is():
    inputs = _build(_op(field_inventory={"available": False}), None)["verdict_inputs"]
    assert fs.build_verdict(inputs, _fake) == "<forestSummary.verdict.landslide_relative:pct=25>"
    empty = _build(_op(field_inventory={"available": False}, hazard_vuln={}), None)["verdict_inputs"]
    assert fs.build_verdict(empty, _fake) == "<forestSummary.verdict.empty:>"


def test_verdict_uses_the_fixed_wording_only_for_a_fixed_method():
    op = _op()
    op["hazard_vuln"]["lsi_class_method"] = "fixed"
    assert "landslide_fixed" in fs.build_verdict(_build(op, None)["verdict_inputs"], _fake)


def test_a_translator_that_does_not_know_a_key_drops_the_clause():
    inputs = _build(_op(), None)["verdict_inputs"]
    assert fs.build_verdict(inputs, lambda key, **p: None if key.endswith("stock") else key) .count("stock") == 0


@pytest.mark.parametrize("lang", ["en", "ne"])
def test_real_wording_exists_fills_every_placeholder_and_never_judges(db, lang):
    translate = translation_service.make_translator(db, lang)
    text = fs.build_verdict(_build(_op(), None)["verdict_inputs"], translate)
    assert text and "{{" not in text and "<" not in text
    assert "168" in text and "25" in text and "B3" in text
    if lang == "en":
        assert "relative" in text.lower()
        for word in ("below", "above", "threshold", "poor", "healthy", "dangerous", "safe"):
            assert word not in text.lower()
    else:
        assert re.search(r"[ऀ-ॿ]", text) and "सापेक्ष" in text


def test_nepali_wording_keeps_every_placeholder_of_the_english():
    en, ne = translation_service.load_bundle_pairs()
    keys = [k for k in en if k.startswith("forestSummary.")]
    assert keys, "forestSummary keys are missing from the English bundle"
    for key in keys:
        assert ne.get(key), f"{key} has no Nepali"
        assert set(translation_service.placeholders_of(ne[key])) == set(translation_service.placeholders_of(en[key])), key


def test_verdict_numbers_follow_the_language_but_unit_names_do_not():
    inputs = _build(_op())["verdict_inputs"]
    ne = fs.build_verdict(inputs, _fake, "ne")
    en = fs.build_verdict(inputs, _fake, "en")
    assert "good=४८.५" in ne and "stock=१६८" in ne and "pct=२५" in ne
    assert "units=B3" in ne  # a unit name keeps its Latin characters
    assert "good=48.5" in en and "stock=168" in en



def test_fmt_is_whole_or_one_decimal_in_the_languages_digits():
    assert fs._fmt(168.4, "en") == "168.4" and fs._fmt(168.4, "ne") == "१६८.४"
    assert fs._fmt(25.0, "ne") == "२५" and fs._fmt(0.02, "ne") == "०"
