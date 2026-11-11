"""NTFP analysis maths (``app.services.ntfp_analysis``), checked against figures worked out by hand."""
import pytest

from app.services.ntfp_analysis import analyse, t95

AREAS = {"A": 10.0, "B": 30.0}
PLOTS = [{"plot_number": n, "stratum": "A" if n <= 4 else "B", "species_keys": ["x", "y"]} for n in range(1, 9)]
SPECIES = [{"species_key": "x", "label": "X", "plot_sqm": 25, "growth_class": "shrub"}, {"species_key": "y", "label": "Y", "plot_sqm": 100, "growth_class": "tree"}]


def _obs(key, counts):
    return [{"plot_number": n, "species_key": key, "count_total": c} for n, c in counts.items()]


X = {1: 2, 2: 4, 3: 0, 4: 2, 5: 1, 6: 1, 7: 1, 8: 1}
Y = {1: 1, 2: 0, 3: 0, 4: 0, 5: 2, 6: 0, 7: 0, 8: 0}
OBS = _obs("x", X) + _obs("y", Y)
WEIGHTS = [{"plot_number": 1, "species_key": "x", "part_group": "ङ", "fresh_weight_g": f, "dry_weight_g": d} for f, d in [(800, 300), (900, 330), (1000, 370)]]


def _run(obs=OBS, weights=WEIGHTS, refs=None):
    res = analyse(AREAS, PLOTS, SPECIES, obs, weights, refs)
    return {r["species_key"]: r for r in res["species"]}, res


def test_frequency_and_stratified_density_by_hand():
    by, res = _run()
    x = by["x"]
    assert (x["plots_surveyed"], x["plots_present"], x["frequency_pct"]) == (8, 7, 87.5)
    # A: 800 plants/ha (counts 2,4,0,2 on 25 m2), B: 400; weighted by area 10 and 30 ha -> 500
    assert x["density_per_ha"] == pytest.approx(500.0)
    assert [(s["name"], s["density_per_ha"]) for s in x["strata"]] == [("A", 800.0), ("B", 400.0)]
    y = by["y"]
    assert y["frequency_pct"] == 25.0 and y["density_per_ha"] == pytest.approx(43.75)   # (10 x 25 + 30 x 50) / 40
    assert x["count_total"] == 12 and res["ivi_parts"] == 2


def test_density_precision_from_the_plot_to_plot_spread():
    # stratum A values 800,1600,0,800 -> variance 426 666.7; se = sqrt((10/40)^2 x 426 666.7 / 4) = 81.65; df 3 + 3 = 6; t 2.447
    x = _run()[0]["x"]
    assert x["density_se"] == pytest.approx(81.65, abs=0.01)
    assert x["density_precision_pct"] == pytest.approx(2.447 * 81.65 / 500 * 100, abs=0.1)


def test_relative_values_and_importance_value():
    by, _ = _run()
    assert by["x"]["relative_frequency_pct"] == pytest.approx(77.78, abs=0.01) and by["y"]["relative_frequency_pct"] == pytest.approx(22.22, abs=0.01)
    assert by["x"]["relative_density_pct"] == pytest.approx(500 / 543.75 * 100, abs=0.01)
    assert by["x"]["ivi"] == pytest.approx(77.78 + 91.95, abs=0.02)
    assert by["x"]["ivi"] + by["y"]["ivi"] == pytest.approx(200.0, abs=0.01)   # the two parts each sum to 100
    assert (by["x"]["ivi_rank"], by["y"]["ivi_rank"]) == (1, 2)


def test_conversion_factor_yield_and_stock_by_hand():
    (part,) = _run()[0]["x"]["parts"]
    assert part["samples"] == 3 and part["mean_fresh_g"] == 900.0
    assert part["conversion_factor"] == pytest.approx(1000 / 2700, abs=1e-4)   # sum dry / sum fresh
    assert part["yield_fresh_kg_ha"] == pytest.approx(450.0)                    # 500 plants/ha x 900 g
    assert part["yield_dry_kg_ha"] == pytest.approx(450 * 1000 / 2700, abs=0.01)
    assert part["stock_fresh_kg"] == pytest.approx(450 * 40) and part["stock_dry_kg"] == pytest.approx(450 * 1000 / 2700 * 40, abs=0.1)


def test_yield_precision_combines_density_and_weight_spread():
    # var(mean w) = var(800, 900, 1000) / 3 = 3333.3; var(Y) = (900^2 x 81.65^2 + 500^2 x 3333.3) / 1e6; df = min(6, 2) -> t 4.303
    (part,) = _run()[0]["x"]["parts"]
    assert part["yield_precision_pct"] == pytest.approx(4.303 * (6233.33 ** 0.5) / 450 * 100, abs=0.2)


def test_the_conversion_factor_uses_only_samples_that_have_a_dry_weight():
    w = WEIGHTS + [{"plot_number": 1, "species_key": "x", "part_group": "ङ", "fresh_weight_g": 5000, "dry_weight_g": None}]
    (part,) = _run(weights=w)[0]["x"]["parts"]
    assert part["samples"] == 4 and part["dry_pairs"] == 3
    assert part["conversion_factor"] == pytest.approx(1000 / 2700, abs=1e-4)
    assert part["mean_fresh_g"] == pytest.approx((2700 + 5000) / 4)   # the mean weight does use every fresh weight


def test_a_part_with_no_dry_weights_has_fresh_yield_only_and_says_so():
    w = [{"plot_number": 1, "species_key": "x", "part_group": "ङ", "fresh_weight_g": 800, "dry_weight_g": None}]
    (part,) = _run(weights=w)[0]["x"]["parts"]
    assert part["yield_dry_kg_ha"] is None and part["stock_dry_kg"] is None and part["yield_fresh_kg_ha"] == pytest.approx(400.0)
    assert {"no_dry_weights", "few_samples"} <= set(part["warnings"])
    assert part["yield_precision_pct"] is None   # one sample: the weight spread is unknown, not zero


def test_a_measured_conversion_factor_far_from_the_guidelines_is_flagged():
    (part,) = _run(refs={"x": {"conversion_factor": 0.6}})[0]["x"]["parts"]
    assert "cf_differs_from_guideline" in part["warnings"] and part["conversion_factor_reference"] == 0.6
    (part,) = _run(refs={"x": {"conversion_factor": 0.37}})[0]["x"]["parts"]
    assert "cf_differs_from_guideline" not in part["warnings"]


def test_two_parts_of_one_species_are_separate_rows_with_the_same_density():
    w = WEIGHTS + [{"plot_number": 2, "species_key": "x", "part_group": "ग", "fresh_weight_g": 200, "dry_weight_g": 60},
                   {"plot_number": 2, "species_key": "x", "part_group": "ग", "fresh_weight_g": 300, "dry_weight_g": 90}]
    parts = _run(weights=w)[0]["x"]["parts"]
    assert [p["part_group"] for p in parts] == ["ग", "ङ"]
    assert parts[0]["yield_fresh_kg_ha"] == pytest.approx(500 * 250 / 1000)


def test_unsurveyed_not_found_and_incomplete_are_named_not_hidden():
    by, _ = _run(obs=_obs("x", {1: 3, 2: 3}) + _obs("y", {n: 0 for n in range(1, 9)}), weights=[])
    assert {"few_plots", "survey_incomplete"} <= set(by["x"]["warnings"])
    assert "not_found" in by["y"]["warnings"] and by["y"]["density_per_ha"] == 0 and by["y"]["frequency_pct"] == 0
    by, _ = _run(obs=_obs("x", X), weights=[])
    assert "not_surveyed" in by["y"]["warnings"] and by["y"]["frequency_pct"] is None and by["y"]["ivi"] is None
    assert "no_weights" in by["x"]["warnings"]
    assert by["x"]["relative_frequency_pct"] == pytest.approx(100.0)   # the only surveyed species


def test_coverage_is_the_share_of_the_forest_the_surveyed_plots_speak_for():
    only_a = _obs("x", {1: 2, 2: 2, 3: 2, 4: 2})
    x = _run(obs=only_a, weights=[])[0]["x"]
    assert x["area_surveyed_ha"] == 10.0 and x["coverage_pct"] == 25.0 and x["density_per_ha"] == pytest.approx(800.0)
    assert _run()[0]["x"]["coverage_pct"] == 100.0


def test_one_plot_in_a_stratum_gives_unknown_precision_not_zero():
    x = _run(obs=_obs("x", {1: 2, 5: 1}), weights=[])[0]["x"]
    assert x["density_precision_pct"] is None and x["density_per_ha"] == pytest.approx((10 * 800 + 30 * 400) / 40)


def test_t_values():
    assert t95(1) == 12.706 and t95(6) == 2.447 and t95(30) == 2.042 and t95(500) == 1.96


def test_a_fraction_taken_scales_the_weights_up_to_the_whole_part():
    # 25 % of the part was weighed: 900 g recorded stands for 3 600 g; the yield is 500 plants/ha x 3 600 g = 1 800 kg/ha; the precision does not change
    base = _run()[0]["x"]["parts"][0]
    (part,) = _run(refs={"x": {"harvest_fraction_pct": 25.0}})[0]["x"]["parts"]
    assert part["mean_fresh_g"] == 900.0 and part["scale_factor"] == 4.0 and part["mean_whole_fresh_g"] == 3600.0
    assert part["yield_fresh_kg_ha"] == pytest.approx(1800.0)
    assert part["yield_dry_kg_ha"] == pytest.approx(1800 * 1000 / 2700, abs=0.01)    # the dry/fresh ratio is a ratio: unchanged
    assert part["stock_fresh_kg"] == pytest.approx(1800 * 40)
    assert part["yield_precision_pct"] == pytest.approx(base["yield_precision_pct"], abs=0.05)


@pytest.mark.parametrize("pct", [None, 0, 100, 150])
def test_no_fraction_or_the_whole_part_leaves_the_weights_as_recorded(pct):
    (part,) = _run(refs={"x": {"harvest_fraction_pct": pct}})[0]["x"]["parts"]
    assert part["scale_factor"] == 1.0 and part["yield_fresh_kg_ha"] == pytest.approx(450.0)
