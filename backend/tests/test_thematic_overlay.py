"""thematic_overlay rendering core (P1). No DB — drives compose() directly
with synthetic shapely geometry + value dicts (§3.7 test note in the plan)."""

import io
import os
import sys
import warnings

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shapely.geometry import Polygon  # noqa: E402

from app.core import semantic_palettes as sp  # noqa: E402
from app.services.operational_plan import thematic_overlay as to  # noqa: E402
from app.services.operational_plan.thematic_map_spec import (
    ThematicMapSpec,
    resolve_spec,
)  # noqa: E402


# ── synthetic 3-unit forest ──────────────────────────────────────────────
def _units():
    return [
        {
            "name": "B-1",
            "geometry": Polygon(
                [(84.0, 28.0), (84.1, 28.0), (84.1, 28.1), (84.0, 28.1)]
            ),
        },
        {
            "name": "B-2",
            "geometry": Polygon(
                [(84.1, 28.0), (84.2, 28.0), (84.2, 28.1), (84.1, 28.1)]
            ),
        },
        {
            "name": "B-3",
            "geometry": Polygon(
                [(84.0, 28.1), (84.1, 28.1), (84.1, 28.2), (84.0, 28.2)]
            ),
        },
    ]


def _values():
    spec = [
        ("B-1", 120, "Good", 8),
        ("B-2", 60, "Weak", 3),
        ("B-3", 200, "Moderate", 11),
    ]
    return {
        n: {
            "total_growing_stock_m3_per_ha": v,
            "forest_condition": c,
            "regeneration_condition": c,
            "carbon_stock_tc_per_ha": v / 2.0,
            "co2_equivalent_tco2_per_ha": v * 1.8,
            "total_biomass_t_per_ha": v * 1.1,
            "basal_area_m2_per_ha": v / 6.0,
            "tree_per_ha": int(v * 2),
            "pole_per_ha": int(v),
            "regeneration_per_ha": int(v * 3),
            "mai_percent": 2.0,
            "mai_total_m3_per_ha": v / 40.0,
            "aah_total_m3_per_ha": v / 70.0,
            "total_sample_plots": p,
            "satellite_volume_m3_per_ha": v * 0.9,
            "working_circle": "protection" if n == "B-2" else "production",
        }
        for n, v, c, p in spec
    }


_BBOX = (84.0, 28.0, 84.2, 28.2)
_BOUNDARY = Polygon([(84.0, 28.0), (84.2, 28.0), (84.2, 28.2), (84.0, 28.2)])
_WC = {"B-1": "production", "B-2": "protection", "B-3": "production"}


def _png_ok(buf: io.BytesIO, min_bytes: int = 6000):
    data = buf.getvalue()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    assert len(data) >= min_bytes, f"PNG suspiciously small: {len(data)}"


# ── A. every P1 technique renders ────────────────────────────────────────
@pytest.mark.parametrize(
    "key",
    [
        "unit__working_circle",
        "unit__forest_condition",
        "unit__regeneration_condition",
        "unit__growing_stock",
        "unit__growing_stock__graduated",
        "unit__growing_stock__label",
        "unit__satellite_stock",
        "unit__field_vs_satellite",
        "unit__basal_area",
        "unit__stock_reliability",
        "unit__condition_x_stocking",
        "unit__stems_total",
        "unit__tree_per_ha",
        "unit__regeneration_stems",
        "unit__mai",
        "unit__mai_percent",
        "unit__aah",
        "unit__aah__graduated",
        "unit__aah__label",
        "unit__carbon",
        "unit__co2",
        "unit__biomass",
        "unit__carbon__graduated",
    ],
)
def test_technique_renders_a_png(key):
    spec = resolve_spec("thememap:" + key)
    assert spec is not None
    buf = to.compose(
        spec, _units(), _values(), _WC, _BBOX, _BOUNDARY, [], "Buddhinagar CF", 96
    )
    _png_ok(buf)


def test_geometry_source_technique_renders_without_values():
    for key in ("unit__area", "unit__area_share"):
        spec = resolve_spec("thememap:" + key)
        units = _units()
        # source="geometry" reads area_ha / area_share_pct off the unit dicts
        for i, u in enumerate(units):
            u["area_ha"] = 10.0 * (i + 1)
            u["area_share_pct"] = [16.7, 33.3, 50.0][i]
        buf = to.compose(spec, units, {}, _WC, _BBOX, _BOUNDARY, [], "CF", 96)
        _png_ok(buf)


def test_render_emits_no_missing_glyph_warnings():
    spec = resolve_spec("thememap:unit__mai")  # NE title + Latin "MAI" / "m³"
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        to.compose(
            spec, _units(), _values(), _WC, _BBOX, _BOUNDARY, [], "Buddhinagar CF", 96
        )


# ── B. classification ───────────────────────────────────────────────────
def test_sequential_colours_and_legend():
    spec = resolve_spec("thememap:unit__growing_stock")
    feat, rows = to._colour_map(_units(), _values(), spec)
    assert set(feat) == {"B-1", "B-2", "B-3"}
    # low stock (B-2=60) must be a lighter green than high stock (B-3=200)
    assert feat["B-2"] != feat["B-3"]
    assert rows and all(isinstance(c, str) and c.startswith("#") for c, _ in rows)


def test_categorical_colours_use_semantic_palette():
    spec = resolve_spec("thememap:unit__forest_condition")
    feat, rows = to._colour_map(_units(), _values(), spec)
    assert feat["B-1"] == sp.CATEGORICAL["condition"]["Good"]
    assert feat["B-2"] == sp.CATEGORICAL["condition"]["Weak"]


def test_diverging_reference_zero_splits_sign():
    spec = resolve_spec("thememap:unit__field_vs_satellite")
    vals = dict(_values())
    vals["B-1"]["_field_minus_satellite"] = 12.0
    vals["B-2"]["_field_minus_satellite"] = -15.0
    vals["B-3"]["_field_minus_satellite"] = -5.0
    feat, _rows = to._colour_map(_units(), vals, spec)
    assert feat["B-1"] != feat["B-2"]


def test_missing_value_falls_to_no_data_colour_and_legend_row():
    spec = resolve_spec("thememap:unit__growing_stock")
    vals = _values()
    del vals["B-2"]["total_growing_stock_m3_per_ha"]
    feat, rows = to._colour_map(_units(), vals, spec)
    assert feat["B-2"] == sp.NO_DATA_FILL
    assert any(lbl == sp.NO_DATA_LABEL_NE for _c, lbl in rows)


def test_bivariate_returns_nine_class_legend():
    spec = resolve_spec("thememap:unit__condition_x_stocking")
    feat, rows = to._colour_map(_units(), _values(), spec)
    assert len(rows) == 9
    assert all(v in sp.BIVARIATE["bivariate_gp"] or v is None for v in feat.values())


# ── C. placeholder ─────────────────────────────────────────────────────
def test_placeholder_png_is_a_valid_image():
    spec = resolve_spec("thememap:unit__growing_stock")
    buf = to._placeholder_png(spec, "CF", "यस वनमा तथ्याङ्क छैन", 96)
    _png_ok(buf, min_bytes=2000)
