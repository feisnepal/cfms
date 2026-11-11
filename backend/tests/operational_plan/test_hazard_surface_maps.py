"""The hazard / soil-loss surface maps (owner, 2026-10-06): shares in the legend, gaps shown as gaps, the unsafe cells
outlined, and a label per unit."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from affine import Affine
from shapely.geometry import MultiPolygon, box

from app.services.operational_plan.thematic_overlay import (
    _boundary_cell_mask,
    _draw_raster_surface,
    _draw_surface_extras,
    _surface_unit_texts,
)


class _Grid:
    """A 10 x 10 grid of 1-degree cells over (0..10, 0..10); each cell 2 ha."""

    height = width = 10
    transform = Affine(1, 0, 0, 0, -1, 10)
    bounds = (0, 0, 10, 10)
    cell_area_ha = np.full((10, 10), 2.0)


def _ax():
    fig, ax = plt.subplots()
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    return ax


def test_the_legend_gives_area_and_share_per_class_within_the_forest():
    g = _Grid()
    arr = np.zeros((10, 10))
    arr[:, 5:] = 20.0  # right half: class 1
    forest = box(0, 0, 10, 10)
    mask = _boundary_cell_mask(g, forest)
    rows = _draw_raster_surface(_ax(), arr, g.bounds, [10.0], ["#aaa", "#bbb"], forest, cell_area_ha=g.cell_area_ha, mask=mask)
    assert len(rows) == 2
    assert "100.0" in rows[0][1].replace("१", "1").replace("०", "0") or "(50%)" in rows[0][1]
    assert all("(50%)" in r[1] for r in rows)


def test_a_forest_part_with_no_value_is_hatched_and_named_in_the_legend():
    g = _Grid()
    arr = np.full((10, 10), 5.0)
    arr[:, :5] = np.nan  # the west half has no value
    forest = MultiPolygon([box(0, 0, 4, 10), box(6, 0, 10, 10)])
    rows = _draw_surface_extras(_ax(), arr, g, forest, units=None, unit_texts={})
    assert any("तथ्याङ्क उपलब्ध छैन" in r[1] for r in rows)


def test_no_hatch_row_when_every_cell_inside_has_a_value():
    g = _Grid()
    rows = _draw_surface_extras(_ax(), np.full((10, 10), 5.0), g, box(0, 0, 10, 10), units=None, unit_texts={})
    assert rows == []


def test_the_unsafe_cells_get_an_outline_and_a_legend_entry():
    g = _Grid()
    arr = np.full((10, 10), 1.0)
    danger = np.zeros((10, 10), dtype=bool)
    danger[2:4, 2:4] = True
    rows = _draw_surface_extras(_ax(), arr, g, box(0, 0, 10, 10), units=None, unit_texts={}, danger=danger, danger_label="रेखाङ्कित")
    assert rows and rows[0][3] == "#5d0000" and rows[0][1] == "रेखाङ्कित"
    # nothing unsafe: no outline row (an empty legend entry would promise something that is not there)
    assert _draw_surface_extras(_ax(), arr, g, box(0, 0, 10, 10), units=None, unit_texts={}, danger=np.zeros((10, 10), bool), danger_label="x") == []


def test_unit_texts_say_the_mean_loss_and_the_unsafe_share():
    g = _Grid()
    units = [{"name": "W", "geometry": box(0, 0, 5, 10)}, {"name": "E", "geometry": box(5, 0, 10, 10)}]
    arr = np.zeros((10, 10))
    arr[:, :5] = 30.0
    arr[:, 5:] = 50.0
    assert _surface_unit_texts("soil", arr, g, units) == {"W": "30 t/ha/yr", "E": "50 t/ha/yr"}

    surf = np.full((10, 10), 2.0)  # stable everywhere ...
    surf[:, 5:7] = 1.0             # ... but 2 of the 5 columns in the east unit are marginal
    texts = _surface_unit_texts("fs", surf, g, units, classes=surf)
    assert texts["W"].startswith("0%") and texts["E"].startswith("40%")


def test_the_findings_say_when_the_classes_are_relative():
    """A quantile class always holds ~20% of the forest, so "40% is High+" says nothing about absolute hazard."""
    from app.services.operational_plan.hazard_vuln_narration import findings

    d = {"hazard_vuln_available": True, "lsi_prone_area_ha": 39.5, "lsi_prone_area_pct": 40.3, "lsi_high_units_str": "—"}
    for lang, marker in (("ne", "सापेक्ष"), ("en", "relative order")):
        assert marker in findings({**d, "lsi_class_method": "quantile"}, lang)
        assert marker in findings({**d, "lsi_class_method": "equal"}, lang)
        assert marker not in findings({**d, "lsi_class_method": "fixed"}, lang)


def test_the_advice_about_a_large_prone_share_is_not_printed_for_relative_classes():
    """With relative classes ~40% of every forest is 'High+', so 'a large share is landslide-prone' would be boilerplate."""
    from app.services.operational_plan.hazard_vuln_narration import prescription

    d = {"hazard_vuln_available": True, "lsi_prone_area_pct": 40.0, "lsi_high_units_str": "—"}
    assert "पहिरो-प्रवण" not in prescription({**d, "lsi_class_method": "quantile"}, "ne")
    assert "landslide-prone" not in prescription({**d, "lsi_class_method": "quantile"}, "en")
    assert "पहिरो-प्रवण" in prescription({**d, "lsi_class_method": "fixed"}, "ne")


def test_the_prone_area_is_named_for_what_it_is():
    from app.services.operational_plan.thematic_map_spec import resolve_spec
    from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY as VARIABLES

    spec = resolve_spec("thememap:hazard__landslide_prone_area")
    assert "सापेक्ष" in spec.label_ne and "Relatively" in spec.label_en
    for key in ("lsi_prone_area_pct", "hazard_landslide_prone_area_pct"):
        assert "Relatively" in VARIABLES[key].label_en and "सापेक्ष" in VARIABLES[key].label_ne
