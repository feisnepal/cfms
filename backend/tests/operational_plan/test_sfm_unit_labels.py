"""The SFM forest-type map prints "<block name> / Type-N" on each unit, small, as halo text (owner, 2026-10-06).

N is the EFFECTIVE type, so a user's override shows on the map. Units too small to read get less text, or none.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.geometry import box

from app.services.operational_plan.thematic_overlay import _draw_unit_type_labels
from app.services.operational_plan.thematic_map_spec import resolve_spec


def _ax():
    fig, ax = plt.subplots()
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    return ax


def test_labels_name_and_type_and_use_the_effective_type():
    ax = _ax()
    units = [{"name": "Block-1", "geometry": box(0, 0, 5, 5)}]
    # effective_type_no is what the SFM service sets from an override when one exists
    _draw_unit_type_labels(ax, units, {"Block-1": {"effective_type_no": 11, "proposed_type_no": 7}})
    assert [t.get_text() for t in ax.texts] == ["Block-1", "Type-11"]
    assert ax.texts[0].get_fontsize() <= 5.5  # small


def test_small_units_get_the_type_only_and_tiny_ones_nothing():
    ax = _ax()
    units = [
        {"name": "Small", "geometry": box(0, 0, 1, 1)},     # 1% of the map: type only
        {"name": "Tiny", "geometry": box(5, 5, 5.3, 5.3)},  # 0.09%: nothing
    ]
    vals = {"Small": {"effective_type_no": 3}, "Tiny": {"effective_type_no": 3}}
    _draw_unit_type_labels(ax, units, vals)
    assert [t.get_text() for t in ax.texts] == ["Type-3"]


def test_units_without_a_type_are_left_unlabelled_and_the_forest_type_map_turns_labels_on():
    ax = _ax()
    _draw_unit_type_labels(ax, [{"name": "X", "geometry": box(0, 0, 5, 5)}], {"X": {"effective_type_no": None}})
    assert len(ax.texts) == 0
    assert resolve_spec("thememap:sfm__forest_type").show_unit_labels is True
    assert resolve_spec("thememap:sfm__orientation").show_unit_labels is True  # all three SFM maps are labelled


def test_a_block_with_no_type_says_why_on_the_map():
    ax = _ax()
    units = [
        {"name": "Meadow", "geometry": box(0, 0, 4, 4)},
        {"name": "Unsurveyed", "geometry": box(5, 5, 9, 9)},
    ]
    vals = {
        "Meadow": {"effective_type_no": None, "state": "non_forest"},
        "Unsurveyed": {"effective_type_no": None, "state": "inventory_missing"},
    }
    _draw_unit_type_labels(ax, units, vals)
    assert [t.get_text() for t in ax.texts] == ["Meadow", "Non-forest", "Unsurveyed", "No plots"]


class _Spec:
    """Just what the label code reads from a map definition."""

    def __init__(self, kind, basemap="imagery"):
        self.unit_label_kind = kind
        self.basemap = basemap


def _texts(kind, info, spec=None):
    ax = _ax()
    _draw_unit_type_labels(ax, [{"name": "Block-1", "geometry": box(0, 0, 5, 5)}], {"Block-1": info}, spec or _Spec(kind))
    return [t.get_text() for t in ax.texts]


def test_the_forest_type_map_adds_the_slope_band():
    info = {"effective_type_no": 7, "slope_band": 2, "state": "classified"}
    assert _texts("type", info) == ["Block-1", "Type-7 · 19–31°"]
    assert _texts("type", {**info, "slope_band": None}) == ["Block-1", "Type-7"]  # no band known: just the type


def test_the_orientation_map_says_the_orientation_in_the_legend_language():
    info = {"effective_type_no": 7, "orientation": "Conservation", "state": "classified"}
    assert _texts("orientation", info) == ["Block-1", "संरक्षण"]


def test_the_stock_map_says_the_growing_stock():
    assert _texts("stock", {"gs_ge40_m3_per_ha": 209.6}) == ["Block-1", "210 m³/ha"]
    assert _texts("stock", {"gs_ge40_m3_per_ha": None}) == ["Block-1", "—"]


def test_text_is_white_on_imagery_and_dark_otherwise():
    ax = _ax()
    _draw_unit_type_labels(ax, [{"name": "B", "geometry": box(0, 0, 5, 5)}], {"B": {"effective_type_no": 7}}, _Spec("type", "imagery"))
    assert ax.texts[0].get_color() == "#ffffff"
    ax = _ax()
    _draw_unit_type_labels(ax, [{"name": "B", "geometry": box(0, 0, 5, 5)}], {"B": {"effective_type_no": 7}}, _Spec("type", "canvas_light"))
    assert ax.texts[0].get_color() == "#1b1b1b"


def test_the_three_sfm_maps_are_imagery_with_white_outlines_and_translucent_fill():
    for key, kind in (("sfm__forest_type", "type"), ("sfm__orientation", "orientation"), ("sfm__gs_vs_threshold", "stock")):
        spec = resolve_spec("thememap:" + key)
        assert spec.basemap == "imagery" and spec.unit_label_kind == kind and spec.show_unit_labels
        assert spec.edge_color == "#ffffff" and spec.boundary_color == "#ffffff"
        assert 0 < spec.fill_alpha < 0.7  # the imagery shows through


def test_a_provisional_block_says_how_many_plots_it_has():
    info = {"effective_type_no": 7, "slope_band": 2, "state": "provisional", "plot_count": 4}
    assert _texts("type", info) == ["Block-1", "Type-7 · 19–31° · 4 plots"]
    assert _texts("type", {**info, "state": "classified", "plot_count": 9}) == ["Block-1", "Type-7 · 19–31°"]


def test_legend_rows_explain_the_harvest_meaning_and_the_evidence_status():
    from app.services.operational_plan.thematic_overlay import _sfm_legend_rows

    ori = resolve_spec("thememap:sfm__orientation")
    rows = _sfm_legend_rows(ori, [("#aaa", "उत्पादन"), ("#bbb", "प्रतिरक्षा")], [{"name": "B"}], {"B": {"state": "classified"}})
    assert [r[1] for r in rows] == ["उत्पादन — नियमित कटान", "प्रतिरक्षा — कटान छैन"]

    stock = resolve_spec("thememap:sfm__gs_vs_threshold")
    rows = _sfm_legend_rows(
        stock, [("#1", "≤ १५०"), ("#2", "१५० – २००"), ("#3", "> २००")],
        [{"name": "A"}, {"name": "B"}, {"name": "C"}],
        {"A": {"state": "provisional"}, "B": {"state": "inventory_missing"}, "C": {"state": "classified"}},
    )
    labels = [r[1] for r in rows]
    assert "→" not in "".join(labels)  # the Devanagari font has no arrow glyph
    assert any("न्यूनतम तह" in l for l in labels) and any("उच्चतम तह" in l for l in labels)
    assert any("अस्थायी" in l for l in labels) and any("नमुना प्लट छैन" in l for l in labels)
    assert not any("वन जमिन होइन" in l for l in labels)  # no non-forest block on this map: no swatch for it


def test_the_surface_clip_covers_every_part_of_a_multi_part_forest():
    """The raster maps clipped to the FIRST polygon only, hiding the other parts (and their erosion)."""
    from shapely.geometry import MultiPolygon

    from app.services.operational_plan.thematic_overlay import _boundary_clip_path

    ax = _ax()
    forest = MultiPolygon([box(0, 0, 3, 3), box(5, 5, 8, 8)])
    path = _boundary_clip_path(ax, forest)
    assert path.contains_point((1, 1)) and path.contains_point((6, 6))  # both parts inside the clip
    assert not path.contains_point((4, 4))                               # the gap between them stays outside

