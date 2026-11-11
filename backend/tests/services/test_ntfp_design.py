"""NTFP sampling design maths (Resource Survey Guideline 2069, section 3.3): ``app.services.ntfp_design``."""
import math
import random

import pytest
from shapely.geometry import Polygon, box

from app.services.ntfp_design import (MIN_PLOTS_PER_STRATUM, SpeciesSpec, composite, design, lay_out, plot_count, plot_polygon, plot_spacing_m)

FORTY_HA = box(0, 0, 632.4555, 632.4555)  # 40 ha


def test_the_guidelines_worked_example_40_ha_shrub_half_a_percent():
    # 3.3.4: sample area 0.5 % of 40 ha = 0.2 ha = 2000 m2; plot 25 m2 -> 80 plots; 3.3.5: a = sqrt(400000 / 81) = 70.27 m
    assert plot_count(400_000, 25, 0.5) == 80
    assert plot_spacing_m(400_000, 80) == pytest.approx(70.27, abs=0.01)


def test_count_has_a_floor_and_a_ceiling():
    assert plot_count(10_000, 25, 0.05) == MIN_PLOTS_PER_STRATUM  # 0.05 % of 1 ha is a fifth of a plot: the floor applies
    assert plot_count(50, 25, 100, min_plots=5) == 2             # cannot hold more plots than fit
    assert plot_count(0, 25, 1) == 0 and plot_count(1000, 25, 0) == 0


def test_the_plot_is_a_square_or_a_circle_of_the_same_area():
    assert plot_polygon(0, 0, 25).area == pytest.approx(25)
    assert plot_polygon(0, 0, 25, "circular").area == pytest.approx(25, rel=0.01)


def test_lay_out_gives_the_wanted_count_on_transect_lines_with_whole_plots():
    pos, spacing, warns = lay_out(FORTY_HA, 80, 25, random.Random(1))
    assert len(pos) == 80 and not warns
    assert spacing >= 5 and spacing <= 80
    for _row, x, y in pos:
        assert FORTY_HA.contains(plot_polygon(x, y, 25))
    assert len({r for r, _, _ in pos}) >= 5  # several transect lines


def test_the_same_seed_gives_the_same_plots():
    a = design({"forest": FORTY_HA}, [SpeciesSpec("a", 25, 0.5)], seed=7)
    b = design({"forest": FORTY_HA}, [SpeciesSpec("a", 25, 0.5)], seed=7)
    c = design({"forest": FORTY_HA}, [SpeciesSpec("a", 25, 0.5)], seed=8)
    assert [(p.x, p.y) for p in a.plots] == [(p.x, p.y) for p in b.plots]
    assert [(p.x, p.y) for p in a.plots] != [(p.x, p.y) for p in c.plots]


def test_a_stratum_too_small_for_its_plots_says_so():
    tiny = box(0, 0, 12, 12)
    res = design({"u": tiny}, [SpeciesSpec("a", 100, 50)], seed=1)
    assert res.strata[0].plots_laid < res.strata[0].plots_wanted or res.strata[0].plots_wanted <= 1
    assert res.warnings or res.strata[0].plots_laid >= 1


def test_species_of_different_sizes_share_plot_positions_and_each_samples_its_own_share():
    herb = SpeciesSpec("herb", 4, 0.1, "herb")
    shrub = SpeciesSpec("shrub", 25, 0.5, "shrub")
    tree = SpeciesSpec("tree", 100, 0.5, "tree")
    res = design({"forest": FORTY_HA}, [herb, shrub, tree], seed=3)
    by = {s["species_key"]: s for s in res.species}
    n_herb = plot_count(FORTY_HA.area, 4, 0.1)
    n_shrub = plot_count(FORTY_HA.area, 25, 0.5)
    n_tree = plot_count(FORTY_HA.area, 100, 0.5)
    assert by["herb"]["plots"] == n_herb and by["shrub"]["plots"] == n_shrub and by["tree"]["plots"] == n_tree
    assert res.strata[0].plots_laid == max(n_herb, n_shrub, n_tree)
    # every plot position carries at least one species, and a species only measures where it was assigned
    assert all(p.species_keys for p in res.plots)
    assert sum("herb" in p.species_keys for p in res.plots) == n_herb
    assert [p.number for p in res.plots] == list(range(1, len(res.plots) + 1))


def test_the_composite_plot_nests_the_smaller_sizes_in_the_corners_of_the_largest():
    lay = composite([SpeciesSpec("tree", 400, 0.5), SpeciesSpec("shrub", 25, 0.5), SpeciesSpec("herb", 4, 0.1), SpeciesSpec("shrub2", 25, 0.5)])
    assert lay["frame_sqm"] == 400
    assert [s["plot_sqm"] for s in lay["subplots"]] == [25, 4]
    assert lay["subplots"][0]["species_keys"] == ["shrub", "shrub2"]  # one sub-plot per size
    assert lay["subplots"][0]["offset_m"] == [-7.5, -7.5]           # 5 m square in the SW corner of a 20 m square
    assert lay["subplots"][1]["offset_m"] == [9.0, -9.0]            # 2 m square in the SE corner


def test_strata_are_laid_out_one_by_one_and_numbered_through():
    res = design({"A": box(0, 0, 300, 300), "B": box(1000, 0, 1300, 400)}, [SpeciesSpec("s", 25, 0.5)], seed=2)
    assert [s.name for s in res.strata] == ["A", "B"]
    assert {p.stratum for p in res.plots} == {"A", "B"}
    assert [p.number for p in res.plots] == list(range(1, len(res.plots) + 1))
    assert all(0 <= p.x <= 300 for p in res.plots if p.stratum == "A")


def test_a_concave_forest_keeps_plots_inside():
    l_shape = Polygon([(0, 0), (400, 0), (400, 100), (100, 100), (100, 400), (0, 400)])
    res = design({"f": l_shape}, [SpeciesSpec("s", 100, 1.0)], seed=5)
    for p in res.plots:
        assert l_shape.contains(plot_polygon(p.x, p.y, 100))


def test_bad_input_is_refused():
    with pytest.raises(ValueError):
        design({"f": FORTY_HA}, [])
    with pytest.raises(ValueError):
        design({"f": FORTY_HA}, [SpeciesSpec("a", 25, 1), SpeciesSpec("a", 25, 1)])
    with pytest.raises(ValueError):
        design({"f": FORTY_HA}, [SpeciesSpec("a", 25, 1)], shape="hexagon")
